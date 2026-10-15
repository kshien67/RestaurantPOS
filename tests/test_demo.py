"""Automatic checks for demo mode (py main.py --demo).
Run with:  py -m unittest discover tests
"""
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from database import db  # noqa: E402
from services import auth, demo, menu, orders, receipts, tables  # noqa: E402


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.init_db(Path(self.tmp.name) / "demo.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_demo_data(self):
        self.assertFalse(demo.is_demo())
        self.assertTrue(demo.ensure_demo_data())
        self.assertTrue(demo.is_demo())

        # Staff: everyone can log in with their PIN or the demo password.
        self.assertEqual(len(auth.list_pin_users()), len(demo.STAFF))
        for username, _name, role, pin in demo.STAFF:
            user = next(u for u in auth.list_pin_users() if u["username"] == username)
            self.assertEqual(auth.authenticate_pin(user["id"], pin).role, role)
            auth.authenticate(username, demo.PASSWORD)

        self.assertEqual(len(menu.list_categories()), 4)
        self.assertEqual(len(tables.list_tables()), 10)
        busy = sorted(t["name"] for t in tables.table_map() if t["order_id"])
        self.assertEqual(busy, ["T2", "T5"])
        self.assertEqual(len(orders.list_open_orders()), 3)          # + a GrabFood order

        rows = receipts.list_receipts(date.today())
        self.assertEqual(sorted(r["status"] for r in rows).count("paid"), 7)
        self.assertEqual(sorted(r["status"] for r in rows).count("void"), 1)
        totals = receipts.day_totals(rows)
        for method in ("cash", "card", "ewallet", "platform"):
            self.assertGreater(totals[method], 0, method)
        void = next(r for r in rows if r["status"] == "void")
        self.assertEqual(void["void_reason"], "Customer left without paying")

        # Order numbers follow the clock (oldest first).
        paid = sorted((r["closed_at"], r["order_no"]) for r in rows)
        self.assertEqual([no for _t, no in paid], sorted(no for _t, no in paid))

        # Running it again changes nothing.
        self.assertFalse(demo.ensure_demo_data())
        self.assertEqual(len(receipts.list_receipts(date.today())), len(rows))

    def test_demo_database_is_separate(self):
        self.assertNotEqual(config.DEMO_DB_PATH, config.DB_PATH)
        self.assertEqual(config.DEMO_DB_PATH.parent.parent, config.DB_PATH.parent)


if __name__ == "__main__":
    unittest.main()
