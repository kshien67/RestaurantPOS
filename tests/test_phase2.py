"""Automatic checks for Phase 2 (menu, add-ons, settings, bill maths).
Run with:  py -m unittest discover tests
"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from database import db  # noqa: E402
from services import auth, formats, menu, pricing, settings  # noqa: E402


class FormatTests(unittest.TestCase):
    def test_parse_money(self):
        self.assertEqual(formats.parse_money("12.50"), 1250)
        self.assertEqual(formats.parse_money("RM 8"), 800)
        self.assertEqual(formats.parse_money("0.1"), 10)
        for bad in ["", "abc", "-1", "1.234", "nan"]:
            with self.assertRaises(ValueError, msg=bad):
                formats.parse_money(bad)

    def test_percent_and_display(self):
        self.assertEqual(formats.parse_percent("6"), 600)
        self.assertEqual(formats.parse_percent("6.5%"), 650)
        with self.assertRaises(ValueError):
            formats.parse_percent("101")
        self.assertEqual(formats.percent(650), "6.5")
        self.assertEqual(formats.percent(1000), "10")
        self.assertEqual(formats.money(123456), "RM 1,234.56")
        self.assertEqual(formats.money_plain(805), "8.05")


class PricingTests(unittest.TestCase):
    S = {"tax_rate_bp": 600, "service_rate_bp": 1000,
         "service_dine_in_only": True, "tax_on_service": True}

    def test_dine_in_tax_on_service(self):
        b = pricing.calculate_bill(10000, "dine_in", self.S)
        self.assertEqual((b.service, b.tax, b.total), (1000, 660, 11660))

    def test_takeaway_has_no_service(self):
        b = pricing.calculate_bill(10000, "takeaway", self.S)
        self.assertEqual((b.service, b.tax, b.total), (0, 600, 10600))

    def test_tax_not_on_service(self):
        s = dict(self.S, tax_on_service=False)
        b = pricing.calculate_bill(10000, "dine_in", s)
        self.assertEqual((b.service, b.tax, b.total), (1000, 600, 11600))

    def test_discount_applied_first(self):
        b = pricing.calculate_bill(10000, "dine_in", self.S, discount=2000)
        self.assertEqual((b.service, b.tax, b.total), (800, 528, 9328))

    def test_cent_rounding(self):
        # 6% of RM 0.25 = 1.5 sen -> rounds up to 2 sen
        self.assertEqual(pricing.percent_of(25, 600), 2)

    def test_cash_rounding(self):
        expected = {4730: 4730, 4731: 4730, 4732: 4730, 4733: 4735, 4734: 4735,
                    4736: 4735, 4737: 4735, 4738: 4740, 4739: 4740}
        for cents, rounded in expected.items():
            self.assertEqual(pricing.round_cash(cents), rounded, cents)
        self.assertEqual(pricing.round_cash(4733, 0), 4733)


class DbTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.init_db(Path(self.tmp.name) / "test.db")
        self.admin = auth.create_user("boss", "Owner", "secret", config.ROLE_ADMIN)

    def tearDown(self):
        self.tmp.cleanup()


class SettingsTests(DbTestCase):
    RAW = {"shop_name": " Kopi  Corner ", "shop_address": "", "shop_phone": "",
           "tax_reg_no": "W10-1234", "receipt_footer": "Thanks", "tax_name": "SST",
           "tax_rate": "8", "service_rate": "10", "service_dine_in_only": True,
           "tax_on_service": False, "cash_rounding": True}

    def test_save_and_load(self):
        settings.save(self.RAW, self.admin)
        s = settings.load()
        self.assertEqual(s["shop_name"], "Kopi Corner")
        self.assertEqual(s["tax_rate_bp"], 800)
        self.assertEqual(s["service_rate_bp"], 1000)
        self.assertFalse(s["tax_on_service"])
        self.assertEqual(s["cash_rounding_cents"], 5)

    def test_bad_values_rejected(self):
        with self.assertRaises(ValueError):
            settings.save(dict(self.RAW, tax_rate="abc"), self.admin)
        with self.assertRaises(ValueError):
            settings.save(dict(self.RAW, shop_name="  "), self.admin)


class MenuTests(DbTestCase):
    def test_categories_and_items(self):
        drinks = menu.save_category(None, "Drinks", "#2E8B57", True, self.admin)
        food = menu.save_category(None, "Food", None, True, self.admin)
        with self.assertRaises(menu.MenuError):
            menu.save_category(None, "Drinks", None, True, self.admin)

        size = menu.save_group(None, "Size", True, 1, True, self.admin)
        menu.save_modifier(None, size, "Large", 150, True, self.admin)

        latte = menu.save_item(None, drinks, "Latte", 1100, True, True, {size}, self.admin)
        menu.save_item(None, drinks, "Mocha", 1250, True, True, set(), self.admin)
        with self.assertRaises(menu.MenuError):
            menu.save_item(None, drinks, "latte", 900, True, True, set(), self.admin)
        # The same name in a different category is fine.
        menu.save_item(None, food, "Latte", 900, True, True, set(), self.admin)

        item, groups = menu.get_item(latte)
        self.assertEqual(item["price_cents"], 1100)
        self.assertEqual(groups, {size})

        # Edit: new price, remove add-on, hide it.
        menu.save_item(latte, drinks, "Latte", 1200, True, False, set(), self.admin)
        item, groups = menu.get_item(latte)
        self.assertEqual((item["price_cents"], item["is_active"], groups), (1200, 0, set()))
        self.assertEqual([i["name"] for i in menu.list_items(drinks, active_only=True)],
                         ["Mocha"])

    def test_reorder(self):
        ids = [menu.save_category(None, n, None, True, self.admin) for n in "ABC"]
        menu.move_category(ids[2], -1)
        self.assertEqual([c["name"] for c in menu.list_categories()], ["A", "C", "B"])
        menu.move_category(ids[0], -1)       # already first: no change
        self.assertEqual([c["name"] for c in menu.list_categories()], ["A", "C", "B"])

    def test_moving_item_to_other_category_goes_last(self):
        a = menu.save_category(None, "A", None, True, self.admin)
        b = menu.save_category(None, "B", None, True, self.admin)
        menu.save_item(None, b, "B1", 100, True, True, set(), self.admin)
        x = menu.save_item(None, a, "X", 100, True, True, set(), self.admin)
        menu.save_item(x, b, "X", 100, True, True, set(), self.admin)
        self.assertEqual([i["name"] for i in menu.list_items(b)], ["B1", "X"])

    def test_group_rules(self):
        self.assertEqual(menu.group_rule_text(1, 1), "Pick 1 (required)")
        self.assertEqual(menu.group_rule_text(0, 1), "Optional, pick 1")
        self.assertEqual(menu.group_rule_text(0, 3), "Optional, up to 3")
        with self.assertRaises(menu.MenuError):
            menu.save_group(None, "Bad", False, 0, True, self.admin)

    def test_sample_menu(self):
        self.assertTrue(menu.is_menu_empty())
        menu.seed_sample_menu(self.admin)
        self.assertEqual(len(menu.list_categories()), 4)
        with self.assertRaises(menu.MenuError):
            menu.seed_sample_menu(self.admin)


class MigrationTests(unittest.TestCase):
    def test_upgrade_existing_version_1_database(self):
        """A shop that ran Phase 1 keeps its staff accounts after upgrading."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            conn = sqlite3.connect(path)
            conn.isolation_level = None
            conn.execute("BEGIN")
            db._migrate_to_1(conn)
            conn.execute("PRAGMA user_version = 1")
            conn.execute("COMMIT")
            conn.close()

            db.init_db(path)
            auth.create_user("boss", "Owner", "secret", config.ROLE_ADMIN)
            db.init_db(path)                  # running again must be harmless
            with db.connect() as c:
                self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0],
                                 db.SCHEMA_VERSION)
                cols = [r["name"] for r in c.execute("PRAGMA table_info(categories)")]
            self.assertIn("color", cols)
            self.assertEqual(db.get_setting("receipt_footer"), "Thank you! Please come again.")
            auth.authenticate("boss", "secret")


if __name__ == "__main__":
    unittest.main()
