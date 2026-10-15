"""Dining tables: setting them up (admin) and the live table map (cashier).

A table is "occupied" while it has an open dine-in order. It becomes free
again when that order is paid (Phase 5) or voided. Tables are hidden, never
deleted, because old orders still point at them.
"""
import re
import sqlite3
from datetime import datetime

from database import db

MAX_NAME = 12          # must fit on a table tile
MAX_SEATS = 50


class TableError(Exception):
    """Raised with a message that is safe to show to the user."""


def list_tables(active_only=False):
    sql = "SELECT * FROM dining_tables"
    if active_only:
        sql += " WHERE is_active = 1"
    with db.connect() as conn:
        return conn.execute(sql + " ORDER BY sort_order, id").fetchall()


def _open_order_on(conn, table_id):
    return conn.execute("SELECT id, order_no FROM orders WHERE table_id = ? AND status = 'open'",
                        (table_id,)).fetchone()


def save_table(table_id, name, seats, is_active, user_id):
    """Create (table_id=None) or update a table. Returns its id."""
    name = " ".join(str(name).split())
    if not name:
        raise TableError("Table name is required.")
    if len(name) > MAX_NAME:
        raise TableError(f"Table name is too long (max {MAX_NAME} characters).")
    if not 1 <= seats <= MAX_SEATS:
        raise TableError(f"Seats must be between 1 and {MAX_SEATS}.")
    try:
        with db.connect() as conn:
            if table_id is None:
                cur = conn.execute(
                    "INSERT INTO dining_tables (name, seats, is_active, sort_order) "
                    "VALUES (?, ?, ?, ?)",
                    (name, seats, int(is_active), db.next_sort_order(conn, "dining_tables")))
                table_id = cur.lastrowid
            else:
                if not is_active and _open_order_on(conn, table_id):
                    raise TableError("This table has an open order. Pay or void it "
                                     "before hiding the table.")
                conn.execute("UPDATE dining_tables SET name = ?, seats = ?, is_active = ? "
                             "WHERE id = ?", (name, seats, int(is_active), table_id))
    except sqlite3.IntegrityError:
        raise TableError(f"There is already a table called '{name}'.")
    db.log_action(user_id, "save_table", name)
    return table_id


def add_tables(count, seats, user_id):
    """Quickly add `count` tables named T1, T2, ... continuing after the
    highest existing 'T<number>'. Returns the new names."""
    if not 1 <= count <= 50:
        raise TableError("You can add 1 to 50 tables at a time.")
    numbers = [int(m.group(1)) for t in list_tables()
               if (m := re.fullmatch(r"T(\d+)", t["name"]))]
    start = max(numbers, default=0) + 1
    names = [f"T{n}" for n in range(start, start + count)]
    for name in names:
        save_table(None, name, seats, True, user_id)
    return names


def move_table(table_id, direction):
    db.reorder("dining_tables", table_id, direction)


def minutes_since(timestamp):
    """Minutes from a 'YYYY-MM-DD HH:MM:SS' database time until now."""
    started = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
    return max(0, int((datetime.now() - started).total_seconds() // 60))


def format_minutes(minutes):
    """45 -> '45 min', 125 -> '2 h 05'."""
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d}"


def table_map():
    """Every visible table, with its open order (if any):
    id, name, seats, order_id, order_no, total_cents, item_count, created_at."""
    with db.connect() as conn:
        return conn.execute(
            "SELECT t.id, t.name, t.seats, o.id AS order_id, o.order_no, o.total_cents, "
            "o.created_at, "
            "(SELECT COALESCE(SUM(quantity), 0) FROM order_items "
            " WHERE order_id = o.id AND is_void = 0) AS item_count "
            "FROM dining_tables t "
            "LEFT JOIN orders o ON o.table_id = t.id AND o.status = 'open' "
            "WHERE t.is_active = 1 ORDER BY t.sort_order, t.id").fetchall()


def free_tables():
    return [t for t in table_map() if t["order_id"] is None]
