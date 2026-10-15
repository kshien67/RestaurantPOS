"""User accounts: password hashing, login, and staff management.

Passwords are NEVER stored as plain text. We store a salted PBKDF2 hash:
    pbkdf2_sha256$<iterations>$<salt hex>$<hash hex>
Even if someone copies the database file, they cannot read the passwords.
"""
import hashlib
import hmac
import os
import sqlite3
import time
from dataclasses import dataclass

import config
from database import db

ITERATIONS = 200_000
MIN_PASSWORD_LENGTH = 4

# Quick login: tap your name, then type a PIN. A 4-digit PIN is easy to guess
# by trying many times, so after MAX_PIN_TRIES wrong PINs that person's PIN
# login is locked for LOCK_SECONDS.
PIN_LENGTH = 4
MAX_PIN_TRIES = 5
LOCK_SECONDS = 60
_pin_failures = {}   # user id -> (wrong tries so far, locked until)
# Same idea for admin approvals (e.g. voids), so nobody can guess an admin's
# password by trying again and again.
_approval_failures = {}   # username (lower case) -> (wrong tries so far, locked until)


def _now():
    return time.monotonic()


class AuthError(Exception):
    """Raised with a message that is safe to show to the user."""


@dataclass
class User:
    id: int
    username: str
    full_name: str
    role: str

    @property
    def is_admin(self):
        return self.role == config.ROLE_ADMIN


def hash_password(password):
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
    )
    # compare_digest takes the same time whether the first or last byte differs,
    # so attackers can't guess the hash by timing.
    return hmac.compare_digest(digest.hex(), hash_hex)


def has_any_admin():
    with db.connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM users WHERE role = ? AND is_active = 1 LIMIT 1",
            (config.ROLE_ADMIN,),
        ).fetchone()
    return row is not None


def _validate(username, full_name, password, role):
    if not username.strip():
        raise AuthError("Username is required.")
    if not full_name.strip():
        raise AuthError("Full name is required.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if role not in config.ROLES:
        raise AuthError("Invalid role.")


def _check_pin_format(pin):
    if len(pin) != PIN_LENGTH or not pin.isdigit():
        raise AuthError(f"PIN must be exactly {PIN_LENGTH} digits.")


def create_user(username, full_name, password, role, created_by=None, pin=None):
    _validate(username, full_name, password, role)
    if pin:
        _check_pin_format(pin)
    try:
        with db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, full_name, role, password_hash, pin_hash) "
                "VALUES (?, ?, ?, ?, ?)",
                (username.strip(), full_name.strip(), role, hash_password(password),
                 hash_password(pin) if pin else None),
            )
            user_id = cur.lastrowid
    except sqlite3.IntegrityError:
        raise AuthError(f"Username '{username.strip()}' is already taken.")
    db.log_action(created_by or user_id, "create_user", f"{username.strip()} ({role})")
    return user_id


def authenticate(username, password):
    """Return a User if the login is correct, otherwise raise AuthError."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username.strip(),)
        ).fetchone()

    # Same message for "no such user" and "wrong password", so nobody can
    # find out which usernames exist.
    if row is None or not verify_password(password, row["password_hash"]):
        raise AuthError("Wrong username or password.")
    if not row["is_active"]:
        raise AuthError("This account has been disabled. Ask the admin.")

    db.log_action(row["id"], "login")
    return User(row["id"], row["username"], row["full_name"], row["role"])


def list_users():
    with db.connect() as conn:
        return conn.execute(
            "SELECT id, username, full_name, role, is_active, created_at, "
            "pin_hash IS NOT NULL AS has_pin FROM users ORDER BY role, username"
        ).fetchall()


# ---------------- Admin approval ----------------

def list_admins():
    """Active admins, shown as buttons on the 'admin approval' pop-up."""
    with db.connect() as conn:
        return conn.execute(
            "SELECT id, username, full_name FROM users WHERE role = ? AND is_active = 1 "
            "ORDER BY full_name", (config.ROLE_ADMIN,)).fetchall()


def approve_as_admin(username, password):
    """An admin confirms an action (like a void) by typing their password.
    Returns that admin's User, or raises AuthError with a message for the screen.
    After MAX_PIN_TRIES wrong passwords, that admin's approvals are locked
    for LOCK_SECONDS."""
    key = username.strip().lower()
    tries, locked_until = _approval_failures.get(key, (0, 0))
    if locked_until > _now():
        wait = int(locked_until - _now()) + 1
        raise AuthError(f"Too many wrong passwords. Try again in {wait} seconds.")

    with db.connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?",
                           (username.strip(),)).fetchone()
    # Check the role BEFORE the password, so this can't be used to test
    # other staff members' passwords.
    if row is None or row["role"] != config.ROLE_ADMIN or not row["is_active"]:
        raise AuthError("Only an active admin can approve this.")

    if not verify_password(password, row["password_hash"]):
        tries += 1
        if tries >= MAX_PIN_TRIES:
            _approval_failures[key] = (0, _now() + LOCK_SECONDS)
            db.log_action(row["id"], "approval_locked")
            raise AuthError(f"Too many wrong passwords. Locked for {LOCK_SECONDS} seconds.")
        _approval_failures[key] = (tries, 0)
        raise AuthError(f"Wrong password. {MAX_PIN_TRIES - tries} tries left.")

    _approval_failures.pop(key, None)
    return User(row["id"], row["username"], row["full_name"], row["role"])


# ---------------- PIN login ----------------

def list_pin_users():
    """Active staff who have a PIN, for the 'tap your name' login screen."""
    with db.connect() as conn:
        return conn.execute(
            "SELECT id, username, full_name, role FROM users "
            "WHERE is_active = 1 AND pin_hash IS NOT NULL ORDER BY full_name"
        ).fetchall()


def set_pin(user_id, pin, by_user_id):
    """Set a staff member's PIN. An empty pin removes PIN login for them."""
    if pin:
        _check_pin_format(pin)
    with db.connect() as conn:
        cur = conn.execute("UPDATE users SET pin_hash = ? WHERE id = ?",
                           (hash_password(pin) if pin else None, user_id))
        if cur.rowcount == 0:
            raise AuthError("User not found.")
    _pin_failures.pop(user_id, None)
    db.log_action(by_user_id, "set_pin" if pin else "remove_pin", f"user_id={user_id}")


def authenticate_pin(user_id, pin):
    """Return a User if the PIN is right, otherwise raise AuthError."""
    tries, locked_until = _pin_failures.get(user_id, (0, 0))
    if locked_until > _now():
        wait = int(locked_until - _now()) + 1
        raise AuthError(f"Too many wrong PINs. Try again in {wait} seconds.")

    with db.connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None or not row["is_active"] or not row["pin_hash"]:
        raise AuthError("PIN login is not available for this account.")

    if not verify_password(pin, row["pin_hash"]):
        tries += 1
        if tries >= MAX_PIN_TRIES:
            _pin_failures[user_id] = (0, _now() + LOCK_SECONDS)
            db.log_action(user_id, "pin_locked")
            raise AuthError(f"Too many wrong PINs. Locked for {LOCK_SECONDS} seconds.")
        _pin_failures[user_id] = (tries, 0)
        raise AuthError(f"Wrong PIN. {MAX_PIN_TRIES - tries} tries left.")

    _pin_failures.pop(user_id, None)
    db.log_action(row["id"], "login", "pin")
    return User(row["id"], row["username"], row["full_name"], row["role"])


def _active_admin_count(conn):
    return conn.execute(
        "SELECT COUNT(*) FROM users WHERE role = ? AND is_active = 1",
        (config.ROLE_ADMIN,),
    ).fetchone()[0]


def set_active(user_id, active, by_user_id):
    with db.connect() as conn:
        row = conn.execute("SELECT username, role, is_active FROM users WHERE id = ?",
                           (user_id,)).fetchone()
        if row is None:
            raise AuthError("User not found.")
        if not active and user_id == by_user_id:
            raise AuthError("You cannot disable your own account.")
        if (not active and row["role"] == config.ROLE_ADMIN and row["is_active"]
                and _active_admin_count(conn) <= 1):
            raise AuthError("You cannot disable the last admin account.")
        conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (int(active), user_id))
    db.log_action(by_user_id, "enable_user" if active else "disable_user", row["username"])


def reset_password(user_id, new_password, by_user_id):
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    with db.connect() as conn:
        cur = conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                           (hash_password(new_password), user_id))
        if cur.rowcount == 0:
            raise AuthError("User not found.")
    db.log_action(by_user_id, "reset_password", f"user_id={user_id}")
