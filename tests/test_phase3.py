"""Automatic checks for PIN login and Phase 3 (orders).
Run with:  py -m unittest discover tests
"""
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from database import db  # noqa: E402
from services import auth, menu, orders, settings, tables  # noqa: E402


class DbTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.init_db(Path(self.tmp.name) / "test.db")
        auth._pin_failures.clear()
        self.admin_id = auth.create_user("boss", "Owner", "secret", config.ROLE_ADMIN)
        self.cashier_id = auth.create_user("amy", "Amy", "1234", config.ROLE_CASHIER, pin="2468")
        self.admin = auth.authenticate("boss", "secret")
        self.cashier = auth.authenticate("amy", "1234")

    def tearDown(self):
        self.tmp.cleanup()


class PinTests(DbTestCase):
    def test_pin_login(self):
        self.assertEqual([u["username"] for u in auth.list_pin_users()], ["amy"])
        user = auth.authenticate_pin(self.cashier_id, "2468")
        self.assertEqual(user.username, "amy")
        with self.assertRaises(auth.AuthError):
            auth.authenticate_pin(self.cashier_id, "1111")
        with self.assertRaises(auth.AuthError):          # admin has no PIN yet
            auth.authenticate_pin(self.admin_id, "2468")

    def test_pin_format(self):
        for bad in ["123", "12345", "12a4"]:
            with self.assertRaises(auth.AuthError, msg=bad):
                auth.set_pin(self.admin_id, bad, self.admin_id)
        auth.set_pin(self.admin_id, "9999", self.admin_id)
        auth.authenticate_pin(self.admin_id, "9999")

    def test_remove_pin_and_disabled_user(self):
        auth.set_pin(self.cashier_id, "", self.admin_id)
        self.assertEqual(auth.list_pin_users(), [])
        with self.assertRaises(auth.AuthError):
            auth.authenticate_pin(self.cashier_id, "2468")

        auth.set_pin(self.cashier_id, "1357", self.admin_id)
        auth.set_active(self.cashier_id, False, self.admin_id)
        self.assertEqual(auth.list_pin_users(), [])
        with self.assertRaises(auth.AuthError):
            auth.authenticate_pin(self.cashier_id, "1357")

    def test_lock_after_too_many_wrong_pins(self):
        clock = [1000.0]
        real_now = auth._now
        auth._now = lambda: clock[0]
        try:
            for _ in range(auth.MAX_PIN_TRIES):
                with self.assertRaises(auth.AuthError):
                    auth.authenticate_pin(self.cashier_id, "0000")
            # Even the right PIN is refused while locked...
            with self.assertRaisesRegex(auth.AuthError, "Try again"):
                auth.authenticate_pin(self.cashier_id, "2468")
            # ...and works again after the lock time.
            clock[0] += auth.LOCK_SECONDS + 1
            auth.authenticate_pin(self.cashier_id, "2468")
        finally:
            auth._now = real_now

    def test_correct_pin_resets_the_count(self):
        for _ in range(auth.MAX_PIN_TRIES - 1):
            with self.assertRaises(auth.AuthError):
                auth.authenticate_pin(self.cashier_id, "0000")
        auth.authenticate_pin(self.cashier_id, "2468")
        with self.assertRaisesRegex(auth.AuthError, "Wrong PIN"):   # not locked
            auth.authenticate_pin(self.cashier_id, "0000")


class CartTests(unittest.TestCase):
    def test_line_maths_and_merging(self):
        large = orders.Modifier(1, "Large", 150)
        iced = orders.Modifier(2, "Iced", 50)
        lines = []
        a = orders.add_line(lines, orders.CartLine(10, "Latte", 1100, [large, iced], 2))
        self.assertEqual((a.unit_price, a.total), (1300, 2600))
        # Same item + same add-ons -> merged
        b = orders.add_line(lines, orders.CartLine(10, "Latte", 1100, [large, iced], 1))
        self.assertIs(a, b)
        self.assertEqual((len(lines), a.qty), (1, 3))
        # Different add-ons -> new line
        orders.add_line(lines, orders.CartLine(10, "Latte", 1100, [large], 1))
        self.assertEqual(len(lines), 2)
        # A line that was already sent is never merged into
        a.order_item_id = 99
        orders.add_line(lines, orders.CartLine(10, "Latte", 1100, [large, iced], 1))
        self.assertEqual(len(lines), 3)

    def test_describe(self):
        self.assertEqual(orders.short_number("20261013-0012"), "#12")
        self.assertEqual(orders.describe("takeaway", "20261013-0012"), "Takeaway #12")
        self.assertEqual(orders.describe("delivery", "20261013-0003", "GrabFood"), "GrabFood #3")
        self.assertEqual(orders.describe("takeaway"), "New takeaway order")


class AddonRuleTests(DbTestCase):
    def setUp(self):
        super().setUp()
        cat = menu.save_category(None, "Coffee", None, True, self.admin_id)
        self.size = menu.save_group(None, "Size", True, 1, True, self.admin_id)
        self.regular = menu.save_modifier(None, self.size, "Regular", 0, True, self.admin_id)
        self.large = menu.save_modifier(None, self.size, "Large", 150, True, self.admin_id)
        self.extras = menu.save_group(None, "Extras", False, 2, True, self.admin_id)
        self.shot = menu.save_modifier(None, self.extras, "Extra shot", 200, True, self.admin_id)
        self.syrup = menu.save_modifier(None, self.extras, "Syrup", 150, True, self.admin_id)
        self.cream = menu.save_modifier(None, self.extras, "Cream", 100, True, self.admin_id)
        hidden = menu.save_group(None, "Old group", False, 1, False, self.admin_id)
        menu.save_modifier(None, hidden, "Old", 0, True, self.admin_id)
        self.latte = menu.save_item(None, cat, "Latte", 1100, True, True,
                                    {self.size, self.extras, hidden}, self.admin_id)

    def test_groups_offered(self):
        groups = menu.item_addon_groups(self.latte)
        self.assertEqual([g["name"] for g, _opts in groups], ["Size", "Extras"])

    def test_rules(self):
        groups = menu.item_addon_groups(self.latte)
        mods = orders.validate_choices(groups, {self.large, self.shot})
        self.assertEqual([m.name for m in mods], ["Large", "Extra shot"])
        with self.assertRaisesRegex(orders.OrderError, "Size"):       # required
            orders.validate_choices(groups, {self.shot})
        with self.assertRaises(orders.OrderError):                     # two sizes
            orders.validate_choices(groups, {self.regular, self.large})
        with self.assertRaises(orders.OrderError):                     # 3 extras, max 2
            orders.validate_choices(groups, {self.regular, self.shot, self.syrup, self.cream})
        with self.assertRaises(orders.OrderError):                     # unknown option
            orders.validate_choices(groups, {self.regular, 9999})


class OrderTests(DbTestCase):
    def setUp(self):
        super().setUp()
        settings.save({"shop_name": "Test", "tax_name": "SST", "tax_rate": "6",
                       "service_rate": "10", "service_dine_in_only": True,
                       "tax_on_service": True, "cash_rounding": True}, self.admin_id)
        cat = menu.save_category(None, "Food", None, True, self.admin_id)
        self.nasi = menu.save_item(None, cat, "Nasi Lemak", 1290, True, True, set(), self.admin_id)
        self.egg = orders.Modifier(None, "Fried egg", 200)

    def _cart(self):
        return [orders.CartLine(self.nasi, "Nasi Lemak", 1290, [self.egg], 2, "extra sambal"),
                orders.CartLine(self.nasi, "Nasi Lemak", 1290, [], 1)]

    def test_save_and_load(self):
        lines = self._cart()
        order_id, order_no = orders.save_order(None, "takeaway", lines, self.cashier_id)
        self.assertRegex(order_no, r"^\d{8}-0001$")
        self.assertTrue(all(line.is_sent for line in lines))

        order, loaded = orders.load_order(order_id)
        self.assertEqual(order["status"], "open")
        # (12.90 + 2.00) x 2 + 12.90 = 42.70; takeaway: no service; 6% SST = 2.56
        self.assertEqual((order["subtotal_cents"], order["service_cents"], order["tax_cents"],
                          order["total_cents"]), (4270, 0, 256, 4526))
        self.assertEqual([(l.name, l.qty, l.note, [m.name for m in l.modifiers]) for l in loaded],
                         [("Nasi Lemak", 2, "extra sambal", ["Fried egg"]),
                          ("Nasi Lemak", 1, "", [])])

        _id2, order_no2 = orders.save_order(None, "delivery", self._cart(), self.cashier_id,
                                            "GrabFood", "GF-881")
        self.assertTrue(order_no2.endswith("-0002"))

    def test_menu_change_does_not_change_saved_order(self):
        order_id, _ = orders.save_order(None, "takeaway", self._cart(), self.cashier_id)
        menu.save_item(self.nasi, menu.list_categories()[0]["id"], "Nasi Lemak Special",
                       1990, True, True, set(), self.admin_id)
        _order, loaded = orders.load_order(order_id)
        self.assertEqual((loaded[0].name, loaded[0].base_price), ("Nasi Lemak", 1290))

    def test_add_more_items_later(self):
        lines = self._cart()
        table = tables.save_table(None, "T1", 4, True, self.admin_id)
        order_id, _ = orders.save_order(None, "dine_in", lines, self.cashier_id, table_id=table)
        with self.assertRaises(orders.OrderError):             # nothing new
            orders.save_order(order_id, "dine_in", lines, self.cashier_id)
        lines.append(orders.CartLine(self.nasi, "Nasi Lemak", 1290))
        orders.save_order(order_id, "dine_in", lines, self.cashier_id)
        order, loaded = orders.load_order(order_id)
        self.assertEqual(len(loaded), 3)
        # 55.60 food + 10% service 5.56 + 6% SST on 61.16 = 3.67 -> 64.83
        self.assertEqual((order["subtotal_cents"], order["service_cents"], order["tax_cents"],
                          order["total_cents"]), (5560, 556, 367, 6483))

    def test_void_line_needs_admin_and_reason(self):
        lines = self._cart()
        order_id, _ = orders.save_order(None, "takeaway", lines, self.cashier_id)
        item_id = lines[0].order_item_id
        with self.assertRaises(orders.OrderError):              # a cashier can't approve
            orders.void_line(item_id, self.cashier, "mistake")
        with self.assertRaisesRegex(orders.OrderError, "reason"):
            orders.void_line(item_id, self.admin, "   ")
        orders.void_line(item_id, self.admin, "Wrong item / order entered",
                         requested_by=self.cashier_id)
        order, loaded = orders.load_order(order_id)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(order["subtotal_cents"], 1290)
        with db.connect() as conn:
            item = conn.execute("SELECT void_reason, voided_by FROM order_items WHERE id = ?",
                                (item_id,)).fetchone()
            log = conn.execute("SELECT user_id, details FROM audit_log "
                               "WHERE action = 'void_item'").fetchone()
        self.assertEqual((item["void_reason"], item["voided_by"]),
                         ("Wrong item / order entered", self.admin_id))
        self.assertEqual(log["user_id"], self.admin_id)
        self.assertIn("Approved by Owner, requested by Amy", log["details"])
        with self.assertRaises(orders.OrderError):              # already void
            orders.void_line(item_id, self.admin, "again")

    def test_void_order(self):
        order_id, _ = orders.save_order(None, "takeaway", self._cart(), self.cashier_id)
        self.assertEqual(len(orders.list_open_orders()), 1)
        with self.assertRaises(orders.OrderError):
            orders.void_order(order_id, self.cashier, "customer left")
        with self.assertRaises(orders.OrderError):
            orders.void_order(order_id, self.admin, "")
        orders.void_order(order_id, self.admin, "Customer left without paying",
                          requested_by=self.cashier_id)
        self.assertEqual(orders.list_open_orders(), [])
        with self.assertRaises(orders.OrderError):              # can't add to a void order
            orders.save_order(order_id, "takeaway", self._cart(), self.cashier_id)
        order, _lines = orders.load_order(order_id)
        self.assertEqual((order["status"], order["void_reason"], order["voided_by"]),
                         ("void", "Customer left without paying", self.admin_id))
        with db.connect() as conn:
            log = conn.execute("SELECT details FROM audit_log WHERE action = 'void_order'"
                               ).fetchone()["details"]
        self.assertTrue(re.search("Customer left without paying", log))
        self.assertIn("requested by Amy", log)

    def test_open_orders_list(self):
        orders.save_order(None, "takeaway", self._cart(), self.cashier_id)
        row = orders.list_open_orders()[0]
        self.assertEqual((row["item_count"], row["staff_name"]), (3, "Amy"))

    def test_note_length(self):
        self.assertEqual(orders.clean_note("  no   ice "), "no ice")
        with self.assertRaises(orders.OrderError):
            orders.clean_note("x" * (orders.MAX_NOTE + 1))


if __name__ == "__main__":
    unittest.main()
