"""Automatic checks for Phase 5 (checkout and receipts).
Run with:  py -m unittest discover tests
"""
import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from database import db  # noqa: E402
from services import auth, checkout, menu, orders, receipts, settings, tables  # noqa: E402
from services.checkout import Discount  # noqa: E402

SETTINGS = {"shop_name": "Kopi Corner", "shop_address": "12 Jalan Bukit, KL",
            "shop_phone": "03-1234 5678", "tax_reg_no": "W10-1808-31000000",
            "receipt_footer": "Thank you!", "tax_name": "SST", "tax_rate": "6",
            "service_rate": "10", "service_dine_in_only": True, "tax_on_service": True,
            "cash_rounding": True, "cashier_discounts": True}


class QuoteTests(unittest.TestCase):
    S = {"tax_rate_bp": 600, "service_rate_bp": 1000, "service_dine_in_only": True,
         "tax_on_service": True, "cash_rounding_cents": 5}

    def test_rounding_only_for_cash(self):
        cash = checkout.quote(4730, "takeaway", self.S, method="cash")
        card = checkout.quote(4730, "takeaway", self.S, method="card")
        self.assertEqual((cash.bill.total, cash.rounding, cash.due), (5014, 1, 5015))
        self.assertEqual((card.rounding, card.due), (0, 5014))
        no_rounding = dict(self.S, cash_rounding_cents=0)
        self.assertEqual(checkout.quote(4730, "takeaway", no_rounding).due, 5014)

    def test_discounts(self):
        self.assertEqual(Discount("percent", 1000).cents(4730), 473)
        self.assertEqual(Discount("amount", 500).cents(4730), 500)
        self.assertEqual(Discount("amount", 9999).cents(4730), 4730)   # never below zero
        self.assertEqual(Discount("percent", 1000).label(), "10%")
        self.assertEqual(Discount("amount", 500).label("RM"), "RM 5.00")
        for kind, value in [("percent", 0), ("percent", 10_001), ("amount", -1), ("x", 5)]:
            with self.assertRaises(ValueError, msg=(kind, value)):
                Discount(kind, value)
        q = checkout.quote(4730, "takeaway", self.S, Discount("percent", 1000), "card")
        # 47.30 - 4.73 = 42.57; SST 6% = 2.55; total 45.12
        self.assertEqual((q.bill.discount, q.bill.tax, q.due), (473, 255, 4512))

    def test_suggested_notes(self):
        self.assertEqual(checkout.suggested_notes(3245), [3500, 4000, 5000])
        self.assertEqual(checkout.suggested_notes(3700), [4000, 5000, 10000])
        self.assertEqual(checkout.suggested_notes(5515), [6000, 10000])
        self.assertEqual(checkout.suggested_notes(5000), [10000])
        self.assertEqual(checkout.suggested_notes(0), [])


class PaymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.init_db(Path(self.tmp.name) / "test.db")
        admin_id = auth.create_user("boss", "Owner", "secret", config.ROLE_ADMIN)
        auth.create_user("amy", "Amy Tan", "1234", config.ROLE_CASHIER)
        self.admin = auth.authenticate("boss", "secret")
        self.cashier = auth.authenticate("amy", "1234")
        settings.save(SETTINGS, admin_id)
        self.s = settings.load()
        cat = menu.save_category(None, "Food", None, True, admin_id)
        self.nasi = menu.save_item(None, cat, "Nasi Lemak", 1290, True, True, set(), admin_id)
        self.latte = menu.save_item(None, cat, "Latte", 1100, True, True, set(), admin_id)
        self.table = tables.save_table(None, "T1", 4, True, admin_id)

    def tearDown(self):
        self.tmp.cleanup()

    def _lines(self):
        return [orders.CartLine(self.nasi, "Nasi Lemak", 1290, [], 2),
                orders.CartLine(self.latte, "Latte", 1100, [orders.Modifier(None, "Iced", 50)], 1)]

    def _due(self, lines, order_type, method="cash", discount=None):
        subtotal = sum(line.total for line in lines)
        return checkout.quote(subtotal, order_type, self.s, discount, method).due

    def _count(self, table):
        with db.connect() as conn:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def test_pay_new_takeaway_in_one_step(self):
        lines = self._lines()
        due = self._due(lines, "takeaway")
        # 25.80 + 11.50 = 37.30; SST 2.24; total 39.54 -> cash 39.55
        self.assertEqual(due, 3955)
        result = checkout.pay(None, "takeaway", lines, self.cashier, "cash", due, tendered=5000)
        self.assertEqual((result.paid, result.rounding, result.change), (3955, 1, 1045))
        self.assertTrue(all(line.is_sent for line in lines))

        order, saved = orders.load_order(result.order_id)
        self.assertEqual((order["status"], order["total_cents"], order["rounding_cents"]),
                         ("paid", 3954, 1))
        self.assertIsNotNone(order["closed_at"])
        self.assertEqual(len(saved), 2)
        with db.connect() as conn:
            p = conn.execute("SELECT * FROM payments").fetchone()
        self.assertEqual((p["method"], p["amount_cents"], p["tendered_cents"], p["change_cents"]),
                         ("cash", 3955, 5000, 1045))
        self.assertEqual(orders.list_open_orders(), [])

    def test_failed_payment_saves_nothing(self):
        lines = self._lines()
        due = self._due(lines, "takeaway")
        with self.assertRaisesRegex(orders.OrderError, "less than"):
            checkout.pay(None, "takeaway", lines, self.cashier, "cash", due, tendered=due - 5)
        with self.assertRaises(checkout.BillChanged):
            checkout.pay(None, "takeaway", lines, self.cashier, "cash", due + 5, tendered=10000)
        self.assertEqual((self._count("orders"), self._count("order_items"),
                          self._count("payments")), (0, 0, 0))
        self.assertFalse(any(line.is_sent for line in lines))

    def test_pay_dine_in_with_discount_by_card_frees_the_table(self):
        first = self._lines()[:1]                     # 2 x Nasi Lemak, saved earlier
        order_id, _ = orders.save_order(None, "dine_in", first, self.cashier.id,
                                        table_id=self.table)
        self.assertEqual(tables.free_tables(), [])
        extra = [orders.CartLine(self.latte, "Latte", 1100)]   # added just before paying
        discount = Discount("percent", 1000)
        due = self._due(first + extra, "dine_in", "card", discount)
        result = checkout.pay(order_id, "dine_in", first + extra, self.cashier, "card", due,
                              reference="  APPR 123456 ", discount=discount)
        # 36.80 - 10% (3.68) = 33.12; service 3.31; SST on 36.43 = 2.19; total 38.62
        self.assertEqual((result.bill.discount, result.bill.service, result.bill.tax,
                          result.paid, result.change), (368, 331, 219, 3862, None))
        self.assertEqual([t["name"] for t in tables.free_tables()], ["T1"])
        order, _lines = orders.load_order(order_id)
        self.assertEqual((order["discount_label"], order["rounding_cents"]), ("10%", 0))
        with db.connect() as conn:
            p = conn.execute("SELECT * FROM payments").fetchone()
        self.assertEqual((p["method"], p["tendered_cents"], p["reference"]),
                         ("card", None, "APPR 123456"))

    def test_discount_permission(self):
        settings.save(dict(SETTINGS, cashier_discounts=False), self.admin.id)
        lines = self._lines()
        discount = Discount("amount", 500)
        due = self._due(lines, "takeaway", "card", discount)
        with self.assertRaisesRegex(orders.OrderError, "Cashiers can't give discounts"):
            checkout.pay(None, "takeaway", lines, self.cashier, "card", due,
                         reference="111111", discount=discount)
        # ...unless an admin approves it with their password
        checkout.pay(None, "takeaway", lines, self.cashier, "card", due, reference="111111",
                     discount=discount, discount_approver=self.admin)
        # An admin can give a small discount (RM 5 of RM 37.30 = 13%) without approval
        again = self._lines()
        checkout.pay(None, "takeaway", again, self.admin, "card", due, reference="111112",
                     discount=discount)

    def test_card_and_ewallet_need_a_reference(self):
        for method in ("card", "ewallet"):
            lines = self._lines()
            due = self._due(lines, "takeaway", method)
            before = self._count("orders")
            for bad in (None, "", "   ", "12", "x" * 41):
                with self.assertRaises(orders.OrderError, msg=(method, bad)):
                    checkout.pay(None, "takeaway", lines, self.cashier, method, due,
                                 reference=bad)
            self.assertEqual(self._count("orders"), before)     # nothing was saved
            checkout.pay(None, "takeaway", lines, self.cashier, method, due,
                         reference=" TNG  20261014 8812 ")
        with db.connect() as conn:
            refs = [r["reference"] for r in conn.execute("SELECT reference FROM payments")]
        self.assertEqual(refs, ["TNG 20261014 8812"] * 2)       # spaces tidied up
        # Cash and delivery-app payments don't need one
        cash = self._lines()
        checkout.pay(None, "takeaway", cash, self.cashier, "cash", self._due(cash, "takeaway"),
                     tendered=5000)

    def test_cannot_pay_twice(self):
        lines = self._lines()
        due = self._due(lines, "takeaway", "card")
        result = checkout.pay(None, "takeaway", lines, self.cashier, "card", due,
                              reference="222222")
        with self.assertRaisesRegex(orders.OrderError, "closed"):
            checkout.pay(result.order_id, "takeaway", lines, self.cashier, "card", due,
                         reference="333333")
        self.assertEqual(self._count("payments"), 1)

    def test_nothing_to_pay(self):
        lines = self._lines()[:1]
        order_id, _ = orders.save_order(None, "takeaway", lines, self.cashier.id)
        orders.void_line(lines[0].order_item_id, self.admin, "Wrong item / order entered")
        with self.assertRaisesRegex(orders.OrderError, "nothing to pay"):
            checkout.pay(order_id, "takeaway", [], self.cashier, "cash", 0, tendered=0)

    def test_free_order_with_full_discount(self):
        lines = self._lines()
        discount = Discount("percent", 10_000)
        result = checkout.pay(None, "takeaway", lines, self.admin, "cash", 0, tendered=0,
                              discount=discount, discount_approver=self.admin)
        self.assertEqual((result.paid, result.change), (0, 0))

    def test_receipt_text(self):
        lines = self._lines()
        lines[1].note = "less ice please, and a very long note to test wrapping"
        due = self._due(lines, "takeaway")
        result = checkout.pay(None, "takeaway", lines, self.cashier, "cash", due, tendered=5000)
        text = receipts.build(result.order_id)
        joined = "\n".join(text)
        self.assertTrue(all(len(line) <= receipts.WIDTH for line in text), joined)
        for expected in ["KOPI CORNER", "SST Reg No: W10-1808-31000000", "RECEIPT",
                         "Takeaway #1", "Cashier: Amy Tan", "2 x Nasi Lemak", "    Iced (+0.50)",
                         "    Note: less ice please",
                         "SST 6%", "Rounding adjustment", "TOTAL PAID", "RM 39.55",
                         "Change", "10.45", "Thank you!"]:
            self.assertIn(expected, joined)
        # 58mm paper (32 characters) works too
        self.assertTrue(all(len(line) <= 32 for line in receipts.build(result.order_id, 32)))

    def test_bill_before_payment(self):
        order_id, _ = orders.save_order(None, "dine_in", self._lines(), self.cashier.id,
                                        table_id=self.table)
        joined = "\n".join(receipts.build(order_id))
        self.assertIn("BILL", joined)
        self.assertIn("Service charge 10%", joined)
        self.assertNotIn("Change", joined)

    def test_methods_offered(self):
        self.assertEqual(checkout.methods_for("delivery", "GrabFood"),
                         ["platform", "cash", "card", "ewallet"])
        self.assertEqual(checkout.methods_for("delivery", "Phone order"),
                         ["cash", "card", "ewallet"])
        self.assertEqual(checkout.methods_for("takeaway"), ["cash", "card", "ewallet"])
        self.assertEqual(checkout.method_label("platform", "foodpanda"), "foodpanda")
        self.assertEqual(checkout.method_label("ewallet"), "E-wallet")

    def test_delivery_app_order_paid_through_the_app(self):
        lines = self._lines()
        due = self._due(lines, "delivery", "platform")
        self.assertEqual(due, 3954)                      # no cash rounding
        result = checkout.pay(None, "delivery", lines, self.cashier, "platform", due,
                              delivery_platform="GrabFood", delivery_ref="GF-881")
        self.assertEqual((result.paid, result.rounding, result.tendered, result.change),
                         (3954, 0, None, None))
        totals = receipts.day_totals(receipts.list_receipts(date.today()))
        self.assertEqual((totals["platform"], totals["cash"], totals["card"], totals["ewallet"]),
                         (3954, 0, 0, 0))                # the cash drawer is not affected
        joined = "\n".join(receipts.build(result.order_id))
        self.assertIn("Paid via GrabFood", joined)
        self.assertIn("Ref: GF-881", joined)

    def test_app_payment_only_for_app_orders(self):
        for order_type, platform in [("takeaway", None), ("delivery", "Phone order")]:
            lines = self._lines()
            due = self._due(lines, order_type, "platform")
            with self.assertRaisesRegex(orders.OrderError, "can't be used", msg=platform):
                checkout.pay(None, order_type, lines, self.cashier, "platform", due,
                             delivery_platform=platform)
        self.assertEqual(self._count("orders"), 0)

    def test_amount_discount_label_shows_what_was_taken(self):
        lines = [orders.CartLine(self.latte, "Latte", 1100)]
        discount = Discount("amount", 5000)                # RM 50 off an RM 11 bill
        result = checkout.pay(None, "takeaway", lines, self.cashier, "cash", 0, tendered=0,
                              discount=discount, discount_approver=self.admin)
        order, _lines = orders.load_order(result.order_id)
        self.assertEqual((order["discount_cents"], order["discount_label"]), (1100, "RM 11.00"))

    def test_day_list_and_totals(self):
        a = self._lines()
        checkout.pay(None, "takeaway", a, self.cashier, "cash", self._due(a, "takeaway"),
                     tendered=5000)
        b = self._lines()
        checkout.pay(None, "takeaway", b, self.cashier, "ewallet",
                     self._due(b, "takeaway", "ewallet"), reference="DUITNOW 778812")
        orders.save_order(None, "takeaway", self._lines(), self.cashier.id)   # still open
        rows = receipts.list_receipts(date.today())
        self.assertEqual(len(rows), 2)
        totals = receipts.day_totals(rows)
        self.assertEqual((totals["cash"], totals["ewallet"], totals["card"], totals["total"]),
                         (3955, 3954, 0, 7909))
        self.assertEqual(rows[0]["reference"], "DUITNOW 778812")

    def test_voids_listed_but_not_counted_as_takings(self):
        paid = self._lines()
        checkout.pay(None, "takeaway", paid, self.cashier, "cash", self._due(paid, "takeaway"),
                     tendered=5000)
        order_id, _ = orders.save_order(None, "dine_in", self._lines(), self.cashier.id,
                                        table_id=self.table)
        orders.void_order(order_id, self.admin, "Customer left without paying",
                          requested_by=self.cashier.id)
        rows = receipts.list_receipts(date.today())
        self.assertEqual(sorted(r["status"] for r in rows), ["paid", "void"])
        void = next(r for r in rows if r["status"] == "void")
        self.assertEqual((void["void_reason"], void["staff_name"]),
                         ("Customer left without paying", "Owner"))
        totals = receipts.day_totals(rows)
        self.assertEqual((totals["total"], totals["cash"], totals["void_count"]), (3955, 3955, 1))
        self.assertGreater(totals["void_total"], 0)
        slip = "\n".join(receipts.build(order_id))
        for expected in ["VOID", "Reason: Customer left without paying", "Approved by: Owner"]:
            self.assertIn(expected, slip)
        self.assertEqual([t["name"] for t in tables.free_tables()], ["T1"])


class ApprovalTests(unittest.TestCase):
    """The admin password check used before every void."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.init_db(Path(self.tmp.name) / "test.db")
        auth._approval_failures.clear()
        self.admin_id = auth.create_user("boss", "Owner", "secret", config.ROLE_ADMIN)
        auth.create_user("amy", "Amy Tan", "1234", config.ROLE_CASHIER)

    def tearDown(self):
        self.tmp.cleanup()

    def test_right_admin_password(self):
        approver = auth.approve_as_admin("BOSS", "secret")
        self.assertEqual((approver.id, approver.is_admin), (self.admin_id, True))
        self.assertEqual([a["username"] for a in auth.list_admins()], ["boss"])

    def test_refused(self):
        with self.assertRaisesRegex(auth.AuthError, "Wrong password"):
            auth.approve_as_admin("boss", "nope")
        with self.assertRaisesRegex(auth.AuthError, "Only an active admin"):   # a cashier
            auth.approve_as_admin("amy", "1234")
        with self.assertRaisesRegex(auth.AuthError, "Only an active admin"):
            auth.approve_as_admin("nobody", "secret")
        boss2 = auth.create_user("boss2", "Partner", "pw1234", config.ROLE_ADMIN)
        auth.set_active(boss2, False, self.admin_id)
        with self.assertRaisesRegex(auth.AuthError, "Only an active admin"):   # disabled
            auth.approve_as_admin("boss2", "pw1234")

    def test_locked_after_too_many_wrong_passwords(self):
        clock = [5000.0]
        real_now = auth._now
        auth._now = lambda: clock[0]
        try:
            for _ in range(auth.MAX_PIN_TRIES):
                with self.assertRaises(auth.AuthError):
                    auth.approve_as_admin("boss", "wrong")
            with self.assertRaisesRegex(auth.AuthError, "Try again"):    # even the right one
                auth.approve_as_admin("boss", "secret")
            clock[0] += auth.LOCK_SECONDS + 1
            auth.approve_as_admin("boss", "secret")
        finally:
            auth._now = real_now


class PaymentsTableUpgradeTest(unittest.TestCase):
    def test_version_5_payments_survive_the_rebuild(self):
        """Version 6 rebuilds the payments table. Existing payments must survive."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v5.db"
            conn = sqlite3.connect(path)
            conn.isolation_level = None
            for version in range(1, 6):                    # build a version-5 database
                conn.execute("BEGIN")
                db.MIGRATIONS[version](conn)
                conn.execute(f"PRAGMA user_version = {version}")
                conn.execute("COMMIT")
            conn.execute("INSERT INTO users (username, full_name, role, password_hash) "
                         "VALUES ('boss', 'Owner', 'admin', 'x')")
            conn.execute("INSERT INTO orders (order_no, order_type, status, created_by) "
                         "VALUES ('20261014-0001', 'takeaway', 'paid', 1)")
            conn.execute("INSERT INTO payments (order_id, method, amount_cents, tendered_cents, "
                         "change_cents, received_by) VALUES (1, 'cash', 3955, 5000, 1045, 1)")
            conn.close()

            db.init_db(path)
            with db.connect() as c:
                self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0],
                                 db.SCHEMA_VERSION)
                row = c.execute("SELECT * FROM payments").fetchone()
                self.assertEqual((row["id"], row["method"], row["amount_cents"],
                                  row["change_cents"]), (1, "cash", 3955, 1045))
                c.execute("INSERT INTO payments (order_id, method, amount_cents, received_by) "
                          "VALUES (1, 'platform', 100, 1)")       # now allowed
                index = c.execute("SELECT name FROM sqlite_master "
                                  "WHERE name = 'idx_payments_order'").fetchone()
                self.assertIsNotNone(index)
            with self.assertRaises(sqlite3.IntegrityError):       # still checked
                with db.connect() as c:
                    c.execute("INSERT INTO payments (order_id, method, amount_cents, "
                              "received_by) VALUES (1, 'bitcoin', 100, 1)")


if __name__ == "__main__":
    unittest.main()
