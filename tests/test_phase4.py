"""Automatic checks for Phase 4 (tables).
Run with:  py -m unittest discover tests
"""
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from database import db  # noqa: E402
from services import auth, menu, orders, tables  # noqa: E402


class TableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.init_db(Path(self.tmp.name) / "test.db")
        self.admin_id = auth.create_user("boss", "Owner", "secret", config.ROLE_ADMIN)
        self.admin = auth.authenticate("boss", "secret")
        cat = menu.save_category(None, "Food", None, True, self.admin_id)
        self.item = menu.save_item(None, cat, "Nasi Lemak", 1290, True, True, set(), self.admin_id)

    def tearDown(self):
        self.tmp.cleanup()

    def _lines(self):
        return [orders.CartLine(self.item, "Nasi Lemak", 1290, [], 2)]

    def _dine_in(self, table_id):
        return orders.save_order(None, "dine_in", self._lines(), self.admin_id, table_id=table_id)

    # ---------- setting up tables ----------
    def test_save_table_rules(self):
        t1 = tables.save_table(None, " T1 ", 4, True, self.admin_id)
        self.assertEqual(tables.list_tables()[0]["name"], "T1")
        for name, seats in [("", 4), ("A very long table name", 4), ("T2", 0), ("T2", 99)]:
            with self.assertRaises(tables.TableError, msg=(name, seats)):
                tables.save_table(None, name, seats, True, self.admin_id)
        with self.assertRaises(tables.TableError):           # duplicate name
            tables.save_table(None, "T1", 2, True, self.admin_id)
        tables.save_table(t1, "Patio 1", 6, True, self.admin_id)
        self.assertEqual(tables.list_tables()[0]["name"], "Patio 1")

    def test_add_several_continues_numbering(self):
        self.assertEqual(tables.add_tables(3, 4, self.admin_id), ["T1", "T2", "T3"])
        tables.save_table(None, "Patio 1", 2, True, self.admin_id)
        self.assertEqual(tables.add_tables(2, 2, self.admin_id), ["T4", "T5"])
        with self.assertRaises(tables.TableError):
            tables.add_tables(0, 4, self.admin_id)

    def test_reorder(self):
        tables.add_tables(3, 4, self.admin_id)
        t3 = tables.list_tables()[2]["id"]
        tables.move_table(t3, -1)
        self.assertEqual([t["name"] for t in tables.list_tables()], ["T1", "T3", "T2"])

    # ---------- orders on tables ----------
    def test_dine_in_needs_a_table(self):
        with self.assertRaises(orders.OrderError):
            orders.save_order(None, "dine_in", self._lines(), self.admin_id)

    def test_one_open_order_per_table(self):
        t1, t2 = (tables.save_table(None, n, 4, True, self.admin_id) for n in ("T1", "T2"))
        order_id, _ = self._dine_in(t1)
        with self.assertRaisesRegex(orders.OrderError, "already has an open order"):
            self._dine_in(t1)
        self._dine_in(t2)                                  # another table is fine
        # Adding items to the existing order is fine
        orders.save_order(order_id, "dine_in", self._lines(), self.admin_id)

    def test_database_blocks_second_open_order_too(self):
        """Even bypassing the app's check, the database refuses."""
        t1 = tables.save_table(None, "T1", 4, True, self.admin_id)
        self._dine_in(t1)
        with self.assertRaises(sqlite3.IntegrityError):
            with db.connect() as conn:
                conn.execute("INSERT INTO orders (order_no, order_type, table_id, created_by) "
                             "VALUES ('X-1', 'dine_in', ?, ?)", (t1, self.admin_id))

    def test_table_is_free_again_after_void(self):
        t1 = tables.save_table(None, "T1", 4, True, self.admin_id)
        order_id, _ = self._dine_in(t1)
        self.assertEqual(tables.free_tables(), [])
        orders.void_order(order_id, self.admin, "left")
        self.assertEqual([t["name"] for t in tables.free_tables()], ["T1"])
        self._dine_in(t1)                                  # can be used again

    def test_table_map(self):
        t1, _t2 = (tables.save_table(None, n, 4, True, self.admin_id) for n in ("T1", "T2"))
        hidden = tables.save_table(None, "Old", 4, False, self.admin_id)
        order_id, order_no = self._dine_in(t1)
        rows = {r["name"]: r for r in tables.table_map()}
        self.assertNotIn("Old", rows)
        self.assertEqual((rows["T1"]["order_id"], rows["T1"]["order_no"],
                          rows["T1"]["item_count"]), (order_id, order_no, 2))
        self.assertIsNone(rows["T2"]["order_id"])
        with self.assertRaises(orders.OrderError):         # hidden table can't be used
            self._dine_in(hidden)

    def test_cannot_hide_table_with_open_order(self):
        t1 = tables.save_table(None, "T1", 4, True, self.admin_id)
        self._dine_in(t1)
        with self.assertRaises(tables.TableError):
            tables.save_table(t1, "T1", 4, False, self.admin_id)

    def test_move_table(self):
        t1, t2, t3 = (tables.save_table(None, n, 4, True, self.admin_id)
                      for n in ("T1", "T2", "T3"))
        order_id, _ = self._dine_in(t1)
        self._dine_in(t3)
        with self.assertRaises(orders.OrderError):         # T3 is busy
            orders.move_to_table(order_id, t3, self.admin_id)
        orders.move_to_table(order_id, t2, self.admin_id)
        order, _lines = orders.load_order(order_id)
        self.assertEqual(order["table_name"], "T2")
        self.assertEqual([t["name"] for t in tables.free_tables()], ["T1"])

        takeaway_id, _ = orders.save_order(None, "takeaway", self._lines(), self.admin_id)
        with self.assertRaises(orders.OrderError):         # takeaway has no table
            orders.move_to_table(takeaway_id, t1, self.admin_id)

    def test_names_and_times(self):
        self.assertEqual(orders.describe("dine_in", "20261013-0014", table_name="T3"),
                         "Table T3 #14")
        self.assertEqual(orders.describe("dine_in", table_name="T3"), "Table T3 (new order)")
        self.assertEqual(tables.format_minutes(45), "45 min")
        self.assertEqual(tables.format_minutes(125), "2 h 05")
        ago = (datetime.now() - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        self.assertIn(tables.minutes_since(ago), (29, 30, 31))


if __name__ == "__main__":
    unittest.main()
