"""Automatic checks for Phase 1. Run with:  py -m unittest discover tests

Each test uses a fresh temporary database, so your real data is never touched.
"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from database import db  # noqa: E402
from services import auth  # noqa: E402


class Phase1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.init_db(Path(self.tmp.name) / "test.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_schema_version_and_settings(self):
        with db.connect() as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0],
                             db.SCHEMA_VERSION)
        self.assertEqual(db.get_setting("currency"), "RM")
        db.set_setting("tax_rate_bp", 600)
        self.assertEqual(db.get_setting("tax_rate_bp"), "600")

    def test_init_twice_is_safe(self):
        db.set_setting("shop_name", "Kopi Corner")
        db.init_db(db._db_path)
        self.assertEqual(db.get_setting("shop_name"), "Kopi Corner")

    def test_login_and_roles(self):
        self.assertFalse(auth.has_any_admin())
        auth.create_user("boss", "Owner", "secret123", config.ROLE_ADMIN)
        auth.create_user("amy", "Amy Tan", "1234", config.ROLE_CASHIER)
        self.assertTrue(auth.has_any_admin())

        admin = auth.authenticate("BOSS", "secret123")   # username not case-sensitive
        self.assertTrue(admin.is_admin)
        cashier = auth.authenticate("amy", "1234")
        self.assertFalse(cashier.is_admin)

        with self.assertRaises(auth.AuthError):
            auth.authenticate("amy", "wrong")
        with self.assertRaises(auth.AuthError):
            auth.authenticate("nobody", "1234")

    def test_password_not_stored_in_plain_text(self):
        auth.create_user("amy", "Amy", "mypassword", config.ROLE_CASHIER)
        with db.connect() as conn:
            stored = conn.execute("SELECT password_hash FROM users").fetchone()[0]
        self.assertNotIn("mypassword", stored)
        self.assertTrue(stored.startswith("pbkdf2_sha256$"))

    def test_duplicate_and_invalid_users(self):
        auth.create_user("amy", "Amy", "1234", config.ROLE_CASHIER)
        with self.assertRaises(auth.AuthError):
            auth.create_user("AMY", "Other Amy", "1234", config.ROLE_CASHIER)
        with self.assertRaises(auth.AuthError):
            auth.create_user("bob", "Bob", "12", config.ROLE_CASHIER)  # too short

    def test_disable_and_reset(self):
        boss = auth.create_user("boss", "Owner", "secret", config.ROLE_ADMIN)
        amy = auth.create_user("amy", "Amy", "1234", config.ROLE_CASHIER)

        auth.set_active(amy, False, boss)
        with self.assertRaises(auth.AuthError):
            auth.authenticate("amy", "1234")
        auth.set_active(amy, True, boss)
        auth.reset_password(amy, "5678", boss)
        auth.authenticate("amy", "5678")

        with self.assertRaises(auth.AuthError):      # can't disable yourself
            auth.set_active(boss, False, boss)

    def test_cannot_disable_last_admin(self):
        boss = auth.create_user("boss", "Owner", "secret", config.ROLE_ADMIN)
        boss2 = auth.create_user("boss2", "Partner", "secret", config.ROLE_ADMIN)
        auth.set_active(boss2, False, boss)
        auth.set_active(boss2, True, boss)
        auth.set_active(boss, False, boss2)          # fine, boss2 still active
        with self.assertRaises(auth.AuthError):
            auth.set_active(boss2, False, boss)     # would leave no active admin

    def test_foreign_keys_enforced(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with db.connect() as conn:
                conn.execute("INSERT INTO menu_items (category_id, name, price_cents) "
                             "VALUES (999, 'Ghost', 100)")


if __name__ == "__main__":
    unittest.main()
