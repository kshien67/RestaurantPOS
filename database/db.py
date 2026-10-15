"""SQLite connection helper and database setup.

Usage:
    from database import db
    db.init_db()                      # once, at app start
    with db.connect() as conn:        # anywhere you need the database
        conn.execute("SELECT ...")

The `with` block commits automatically if no error happens, and rolls back
if one does, so a half-finished sale is never saved.
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import config

SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"

# Bump this when the schema changes, and add a step to MIGRATIONS below.
# schema.sql is version 1; every later change is a migration function, so a
# shop that already has data gets upgraded instead of starting over.
SCHEMA_VERSION = 8

# Default shop settings. Admin can change these later in the Settings screen.
# Tax and service rates start at 0 on purpose: set the real rates for your shop.
DEFAULT_SETTINGS = {
    "shop_name": "My Restaurant",
    "shop_address": "",
    "shop_phone": "",
    "currency": "RM",
    "tax_name": "SST",
    "tax_rate_bp": "0",            # 600 = 6.00%
    "service_rate_bp": "0",        # 1000 = 10.00%
    "service_dine_in_only": "1",   # 1 = only charge service for dine-in
    "tax_on_service": "1",         # 1 = tax is calculated on subtotal + service
    "cash_rounding_cents": "5",    # round cash totals to nearest 5 sen (0 = off)
    "tax_reg_no": "",              # SST registration no. printed on receipts
    "receipt_footer": "Thank you! Please come again.",
    "cashier_discounts": "1",      # 1 = cashiers may give discounts (always logged)
    "discount_limit_bp": "2000",   # discounts above 20% need an admin's password
    # Printers (Admin -> Printers). Types: virtual / network / windows (+ none for kitchen)
    "receipt_printer": "virtual",
    "receipt_host": "",
    "receipt_port": "9100",
    "receipt_windows_name": "",
    "receipt_paper": "80",
    "receipt_auto_print": "1",     # print the receipt automatically after payment
    "cash_drawer": "1",            # open the cash drawer on cash payments
    "kitchen_printer": "virtual",
    "kitchen_host": "",
    "kitchen_port": "9100",
    "kitchen_windows_name": "",
    "kitchen_paper": "80",
}

_db_path = config.DB_PATH


def _open(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row          # rows behave like dicts: row["name"]
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite leaves this OFF by default
    return conn


@contextmanager
def connect():
    conn = _open(_db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _sql_statements(sql):
    """Split a .sql file into single statements (comments are kept, harmlessly)."""
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            yield buffer
            buffer = ""


def _migrate_to_1(conn):
    for statement in _sql_statements(SCHEMA_FILE.read_text(encoding="utf-8")):
        conn.execute(statement)
    conn.executemany(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
        DEFAULT_SETTINGS.items(),
    )


def _migrate_to_2(conn):
    """Phase 2: category colours, ordering and hiding for add-ons, new settings."""
    conn.execute("ALTER TABLE categories ADD COLUMN color TEXT NOT NULL DEFAULT '#D9822B'")
    conn.execute("ALTER TABLE modifier_groups ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
    conn.execute("ALTER TABLE modifier_groups ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE modifiers ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
    conn.executemany(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
        DEFAULT_SETTINGS.items(),
    )


def _migrate_to_3(conn):
    """PIN login for staff, and which delivery platform an order came from."""
    conn.execute("ALTER TABLE users ADD COLUMN pin_hash TEXT")
    conn.execute("ALTER TABLE orders ADD COLUMN delivery_platform TEXT")


def _migrate_to_4(conn):
    """Tables: admin-chosen order, and at most ONE open order per table.
    The 'partial unique index' lets the database itself refuse a second open
    order on the same table, even if the app has a bug."""
    conn.execute("ALTER TABLE dining_tables ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
    conn.execute("CREATE UNIQUE INDEX idx_one_open_order_per_table ON orders(table_id) "
                 "WHERE status = 'open' AND table_id IS NOT NULL")


def _migrate_to_5(conn):
    """Checkout: remember how a discount was given (e.g. '10%') for the receipt,
    and find a day's receipts quickly."""
    conn.execute("ALTER TABLE orders ADD COLUMN discount_label TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_closed ON orders(closed_at)")
    conn.executemany(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
        DEFAULT_SETTINGS.items(),
    )


def _migrate_to_6(conn):
    """Allow a 4th payment method, 'platform' (paid through GrabFood etc.).
    SQLite can't change a CHECK rule in place, so the payments table is
    rebuilt: make the new table, copy every row across, swap the names."""
    conn.execute("""
        CREATE TABLE payments_new (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id       INTEGER NOT NULL REFERENCES orders(id),
            method         TEXT    NOT NULL
                           CHECK (method IN ('cash', 'card', 'ewallet', 'platform')),
            amount_cents   INTEGER NOT NULL,
            tendered_cents INTEGER,
            change_cents   INTEGER,
            reference      TEXT,
            received_by    INTEGER NOT NULL REFERENCES users(id),
            created_at     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
        )""")
    columns = ("id, order_id, method, amount_cents, tendered_cents, change_cents, "
               "reference, received_by, created_at")
    conn.execute(f"INSERT INTO payments_new ({columns}) SELECT {columns} FROM payments")
    conn.execute("DROP TABLE payments")
    conn.execute("ALTER TABLE payments_new RENAME TO payments")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_order ON payments(order_id)")


def _migrate_to_7(conn):
    """Voids need a reason and an admin's approval: remember both on the
    voided order / item itself, so they can be reviewed later."""
    conn.execute("ALTER TABLE orders ADD COLUMN void_reason TEXT")
    conn.execute("ALTER TABLE orders ADD COLUMN voided_by INTEGER REFERENCES users(id)")
    conn.execute("ALTER TABLE order_items ADD COLUMN void_reason TEXT")
    conn.execute("ALTER TABLE order_items ADD COLUMN voided_by INTEGER REFERENCES users(id)")


def _migrate_to_8(conn):
    """Big discounts need an admin: remember who approved it. Printing: count
    how many times a receipt was printed (later prints are marked COPY), and
    add the default printer settings."""
    conn.execute("ALTER TABLE orders ADD COLUMN discount_approved_by INTEGER REFERENCES users(id)")
    conn.execute("ALTER TABLE orders ADD COLUMN receipt_prints INTEGER NOT NULL DEFAULT 0")
    conn.executemany(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
        DEFAULT_SETTINGS.items(),
    )


# version number -> function that upgrades the DB from (version - 1) to version
MIGRATIONS = {
    1: _migrate_to_1,
    2: _migrate_to_2,
    3: _migrate_to_3,
    4: _migrate_to_4,
    5: _migrate_to_5,
    6: _migrate_to_6,
    7: _migrate_to_7,
    8: _migrate_to_8,
}


def init_db(path=None):
    """Create the database file if needed and bring it up to SCHEMA_VERSION."""
    global _db_path
    _db_path = Path(path) if path else config.DB_PATH
    _db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = _open(_db_path)
    conn.isolation_level = None    # we control BEGIN/COMMIT ourselves below
    try:
        conn.execute("PRAGMA journal_mode = WAL")  # safer if the PC loses power
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        for version in range(current + 1, SCHEMA_VERSION + 1):
            # Each upgrade is all-or-nothing: if any step fails, none of it is kept.
            conn.execute("BEGIN")
            try:
                MIGRATIONS[version](conn)
                conn.execute(f"PRAGMA user_version = {version}")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
    finally:
        conn.close()


def data_folder():
    """The folder holding the database in use (data/ normally, a temporary
    folder during tests). Printouts are saved next to it."""
    return Path(_db_path).parent


def get_setting(key):
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else DEFAULT_SETTINGS.get(key)


def set_setting(key, value):
    with connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )


def next_sort_order(conn, table, where="", params=()):
    """The sort_order for a new row so it goes at the end of its list."""
    sql = f"SELECT COALESCE(MAX(sort_order), 0) + 1 FROM {table} {where}"
    return conn.execute(sql, params).fetchone()[0]


def reorder(table, row_id, direction, scope_col=None):
    """Swap a row with its neighbour (direction -1 = up, +1 = down), then
    renumber the whole list 1, 2, 3... so the order is always clean.
    scope_col limits the list, e.g. items within one category."""
    with connect() as conn:
        if scope_col:
            scope = conn.execute(f"SELECT {scope_col} FROM {table} WHERE id = ?",
                                 (row_id,)).fetchone()[0]
            rows = conn.execute(f"SELECT id FROM {table} WHERE {scope_col} = ? "
                                "ORDER BY sort_order, id", (scope,)).fetchall()
        else:
            rows = conn.execute(f"SELECT id FROM {table} ORDER BY sort_order, id").fetchall()
        ids = [r["id"] for r in rows]
        i = ids.index(row_id)
        j = i + direction
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
        for position, rid in enumerate(ids, start=1):
            conn.execute(f"UPDATE {table} SET sort_order = ? WHERE id = ?", (position, rid))


def log_action(user_id, action, details=""):
    """Write a line to the audit log (who did what, and when)."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO audit_log (user_id, action, details) VALUES (?, ?, ?)",
            (user_id, action, details),
        )
