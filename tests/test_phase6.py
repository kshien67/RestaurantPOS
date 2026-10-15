"""Automatic checks for Phase 6 (printing) and the discount approval rule.
Run with:  py -m unittest discover tests

No real printer is needed: the network printer is faked with a tiny TCP
server on this computer, and nothing is ever sent to installed printers.
"""
import re
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from database import db  # noqa: E402
from services import (auth, checkout, escpos, menu, orders, pdf, printing,  # noqa: E402
                      receipts, settings, tables)
from services.checkout import Discount  # noqa: E402

SETTINGS = {"shop_name": "Kopi Corner", "shop_address": "12 Jalan Bukit, George Town",
            "shop_phone": "04-123 4567", "tax_reg_no": "P11-1808-31000000",
            "receipt_footer": "Thank you!", "tax_name": "SST", "tax_rate": "6",
            "service_rate": "10", "service_dine_in_only": True, "tax_on_service": True,
            "cash_rounding": True, "cashier_discounts": True, "discount_limit": "20"}


class FakeNetworkPrinter:
    """Pretends to be a LAN receipt printer: accepts one connection and keeps the bytes."""

    def __init__(self):
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.data = b""
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        conn, _addr = self.server.accept()
        with conn:
            while chunk := conn.recv(65536):
                self.data += chunk

    def received(self):
        self.thread.join(timeout=5)
        self.server.close()
        return self.data


def free_port():
    """A port with nothing listening on it (a 'switched off' printer)."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class PrintingTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.init_db(Path(self.tmp.name) / "test.db")
        auth._approval_failures.clear()
        self.admin_id = auth.create_user("boss", "Owner", "secret", config.ROLE_ADMIN)
        self.cashier_id = auth.create_user("amy", "Amy Tan", "1234", config.ROLE_CASHIER)
        self.admin = auth.authenticate("boss", "secret")
        self.cashier = auth.authenticate("amy", "1234")
        settings.save(SETTINGS, self.admin_id)
        food = menu.save_category(None, "Food", None, True, self.admin_id)
        self.nasi = menu.save_item(None, food, "Nasi Lemak", 1290, True, True, set(),
                                   self.admin_id)
        # Desserts come from the counter: not on the kitchen ticket.
        self.cake = menu.save_item(None, food, "Cheesecake", 1200, False, True, set(),
                                   self.admin_id)
        self.table = tables.save_table(None, "T1", 4, True, self.admin_id)

    def tearDown(self):
        self.tmp.cleanup()

    def lines(self):
        return [orders.CartLine(self.nasi, "Nasi Lemak", 1290,
                                [orders.Modifier(None, "Fried egg", 200)], 2, "extra sambal"),
                orders.CartLine(self.cake, "Cheesecake", 1200)]

    def printouts(self):
        return sorted(p.name for p in printing.printouts_dir().rglob("*.pdf"))

    def use_network(self, role, port):
        printing.save_config(role, {"kind": "network", "host": "127.0.0.1", "port": port,
                                    "paper": 80}, self.admin_id)


class EscPosTests(unittest.TestCase):
    def test_encode(self):
        data = escpos.encode([("KOPI", "big", "center"), ("1 x Latte  11.00", "normal", "left"),
                              ("TOTAL", "bold", "left"), ("Teh × 2 茶", "tall", "left")],
                             open_drawer=True)
        self.assertTrue(data.startswith(escpos.INIT + escpos.CODE_PAGE_PC437 + escpos.OPEN_DRAWER))
        self.assertIn(escpos.ALIGN["center"] + escpos.SIZE["big"] + escpos.BOLD[True] + b"KOPI\n",
                      data)
        self.assertIn(escpos.SIZE["normal"] + escpos.BOLD[False] + b"1 x Latte  11.00\n", data)
        self.assertIn(b"Teh ? 2 ?\n", data)               # no crash on other characters
        self.assertTrue(data.endswith(escpos.FEED_AND_CUT))
        self.assertNotIn(escpos.OPEN_DRAWER, escpos.encode([("x", "normal", "left")]))


class PdfTests(unittest.TestCase):
    def test_structure_and_xref_offsets(self):
        lines = [("KOPI CORNER", "big", "center"), ("Price (RM) 12.50 \\ ok", "normal", "left"),
                 ("TOTAL", "bold", "left"), ("2 x Latte", "tall", "left"), ("Teh × 茶", "normal", "left")]
        data = pdf.render(lines, 48, 80)
        self.assertTrue(data.startswith(b"%PDF-1.4"))
        self.assertTrue(data.rstrip().endswith(b"%%EOF"))
        # Every xref entry must point exactly at the start of "N 0 obj".
        xref_at = int(re.search(rb"startxref\n(\d+)", data).group(1))
        self.assertTrue(data[xref_at:].startswith(b"xref"))
        entries = re.findall(rb"(\d{10}) 00000 n", data[xref_at:])
        self.assertEqual(len(entries), 6)
        for number, offset in enumerate(entries, start=1):
            self.assertTrue(data[int(offset):].startswith(b"%d 0 obj" % number), number)
        self.assertIn(rb"Price \(RM\) 12.50 \\ ok", data)   # brackets/backslash escaped


class ReceiptLayoutTests(PrintingTestCase):
    def test_styled_receipt_fits_80mm_and_58mm(self):
        lines = self.lines()
        due = checkout.quote(sum(l.total for l in lines), "takeaway", settings.load()).due
        result = checkout.pay(None, "takeaway", lines, self.cashier, "cash", due, tendered=10000)
        for width in (48, 32):
            styled = receipts.build_styled(result.order_id, width)
            for text, style, _align in styled:
                limit = width // 2 if style == "big" else width
                self.assertLessEqual(len(text), limit, (width, text))
            self.assertIn(("TOTAL", "bold", "left"), [(t.split()[0], s, a) for t, s, a in styled
                                                        if t.startswith("TOTAL ")])
        plain = receipts.build(result.order_id)
        self.assertIn("RECEIPT", "\n".join(plain))
        self.assertIn("RECEIPT (COPY)", "\n".join(receipts.build(result.order_id, copy=True)))

    def test_kitchen_ticket(self):
        lines = self.lines()
        order_id, _ = orders.save_order(None, "dine_in", lines, self.cashier_id,
                                        table_id=self.table)
        ids = [l.order_item_id for l in lines]
        ticket = receipts.to_text(receipts.kitchen_ticket(order_id, ids, staff="Amy Tan"))
        joined = "\n".join(ticket)
        for expected in ["KITCHEN", "Table T1 #1", "Amy Tan", "2 x Nasi Lemak", "+ Fried egg",
                         "NOTE: extra sambal", "2 items"]:
            self.assertIn(expected, joined)
        self.assertNotIn("Cheesecake", joined)           # not a kitchen item
        self.assertEqual(receipts.kitchen_ticket(order_id, [lines[1].order_item_id]), [])
        self.assertEqual(receipts.kitchen_ticket(order_id, []), [])

        # A VOID ticket still finds the item after it was voided.
        orders.void_line(ids[0], self.admin, "Wrong item / order entered")
        void = "\n".join(receipts.to_text(receipts.kitchen_ticket(
            order_id, [ids[0]], void=True, reason="Wrong item / order entered")))
        for expected in ["*** VOID ***", "2 x Nasi Lemak", "Reason: Wrong item", "DO NOT MAKE"]:
            self.assertIn(expected, void)


class PrinterSettingsTests(PrintingTestCase):
    def test_defaults_are_virtual(self):
        for role in ("receipt", "kitchen"):
            cfg = printing.load_config(role)
            self.assertEqual((cfg.kind, cfg.paper, cfg.chars), ("virtual", 80, 48))
        self.assertTrue(printing.load_config("receipt").auto_print)

    def test_validation(self):
        bad = [("receipt", {"kind": "none"}),                       # receipt can't be 'none'
               ("kitchen", {"kind": "network", "host": "", "port": 9100}),
               ("kitchen", {"kind": "network", "host": "192.168.1.50; rm", "port": 9100}),
               ("kitchen", {"kind": "network", "host": "192.168.1.50", "port": 70000}),
               ("receipt", {"kind": "windows", "windows_name": ""}),
               ("receipt", {"kind": "virtual", "paper": 76})]
        for role, raw in bad:
            with self.assertRaises(ValueError, msg=raw):
                printing.validate_config(role, raw)
        cfg = printing.save_config("kitchen", {"kind": "network", "host": "192.168.1.50",
                                               "port": "9100", "paper": "58"}, self.admin_id)
        self.assertEqual(printing.load_config("kitchen"), cfg)
        self.assertEqual(cfg.chars, 32)


class PrintingTests(PrintingTestCase):
    def test_virtual_printer_saves_pdf_and_text_next_to_the_database(self):
        result = printing.test_print(printing.load_config("receipt"))
        self.assertTrue(result.ok, result.message)
        folder = printing.printouts_dir()
        self.assertTrue(str(folder).startswith(self.tmp.name))    # never the real data folder
        pdfs = list(folder.rglob("*.pdf"))
        self.assertEqual(len(pdfs), 1)
        self.assertTrue(pdfs[0].read_bytes().startswith(b"%PDF"))
        self.assertIn("TEST PRINT", pdfs[0].with_suffix(".txt").read_text(encoding="utf-8"))

    def test_network_printer_gets_escpos_bytes(self):
        fake = FakeNetworkPrinter()
        self.use_network("kitchen", fake.port)
        lines = self.lines()
        order_id, _ = orders.save_order(None, "takeaway", lines, self.cashier_id)
        result = printing.print_kitchen(order_id, [l.order_item_id for l in lines],
                                        self.cashier_id)
        self.assertTrue(result.ok, result.message)
        data = fake.received()
        self.assertTrue(data.startswith(escpos.INIT))
        self.assertIn(b"2 x Nasi Lemak", data)
        self.assertNotIn(b"Cheesecake", data)
        self.assertTrue(data.endswith(escpos.FEED_AND_CUT))

    def test_printer_off_keeps_a_copy_and_never_raises(self):
        self.use_network("receipt", free_port())
        lines = self.lines()
        due = checkout.quote(sum(l.total for l in lines), "takeaway", settings.load()).due
        paid = checkout.pay(None, "takeaway", lines, self.cashier, "cash", due, tendered=10000)
        result = printing.print_receipt(paid.order_id, self.cashier_id, open_drawer=True)
        self.assertFalse(result.ok)
        self.assertIn("NOT printed", result.message)
        self.assertIn("A copy was saved", result.message)
        self.assertEqual(len(self.printouts()), 1)
        with db.connect() as conn:                       # failed print isn't counted
            self.assertEqual(conn.execute("SELECT receipt_prints FROM orders").fetchone()[0], 0)

    def test_missing_windows_printer(self):
        printing.save_config("receipt", {"kind": "windows", "paper": 80,
                                         "windows_name": "No Such Printer 12345"}, self.admin_id)
        result = printing.test_print(printing.load_config("receipt"))
        self.assertFalse(result.ok)
        self.assertIn("was not found", result.message)

    def test_reprints_are_marked_copy(self):
        lines = self.lines()
        due = checkout.quote(sum(l.total for l in lines), "takeaway", settings.load()).due
        paid = checkout.pay(None, "takeaway", lines, self.cashier, "cash", due, tendered=10000)
        first = printing.print_receipt(paid.order_id, self.cashier_id)
        second = printing.print_receipt(paid.order_id, self.cashier_id)
        self.assertTrue(first.message.startswith("Receipt saved"))
        self.assertTrue(second.message.startswith("Receipt copy saved"))
        texts = sorted(printing.printouts_dir().rglob("*.txt"))
        contents = [p.read_text(encoding="utf-8") for p in texts]
        self.assertEqual(sum("RECEIPT (COPY)" in c for c in contents), 1)
        with db.connect() as conn:
            log = conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'reprint_receipt'"
                               ).fetchone()[0]
        self.assertEqual(log, 1)

    def test_after_payment_order_and_drawer(self):
        lines = self.lines()
        due = checkout.quote(sum(l.total for l in lines), "takeaway", settings.load()).due
        new = [l for l in lines if not l.is_sent]
        paid = checkout.pay(None, "takeaway", lines, self.cashier, "cash", due, tendered=10000)
        results = printing.after_payment(paid.order_id, "cash", [l.order_item_id for l in new],
                                         self.cashier_id)
        self.assertEqual([r.message.split(" saved")[0] for r in results],
                         ["Kitchen ticket", "Receipt"])          # kitchen first
        self.assertIn("cash drawer would open", results[1].message)

        # Automatic receipt switched off: card payment prints nothing for the customer.
        printing.save_config("receipt", {"kind": "virtual", "paper": 80, "auto_print": False,
                                         "cash_drawer": True}, self.admin_id)
        card_lines = [orders.CartLine(self.cake, "Cheesecake", 1200)]
        due = checkout.quote(1200, "takeaway", settings.load(), method="card").due
        paid = checkout.pay(None, "takeaway", card_lines, self.cashier, "card", due,
                            reference="APPR 1234")
        self.assertEqual(printing.after_payment(paid.order_id, "card",
                                                [card_lines[0].order_item_id], self.cashier_id),
                         [])                                       # cake isn't a kitchen item

    def test_kitchen_printer_none(self):
        printing.save_config("kitchen", {"kind": "none", "paper": 80}, self.admin_id)
        lines = self.lines()
        order_id, _ = orders.save_order(None, "takeaway", lines, self.cashier_id)
        self.assertIsNone(printing.print_kitchen(order_id, [l.order_item_id for l in lines],
                                                 self.cashier_id))

    def test_bill(self):
        lines = self.lines()
        order_id, _ = orders.save_order(None, "dine_in", lines, self.cashier_id,
                                        table_id=self.table)
        result = printing.print_bill(order_id, self.cashier_id)
        self.assertTrue(result.ok)
        text = next(printing.printouts_dir().rglob("*.txt")).read_text(encoding="utf-8")
        self.assertIn("BILL", text)
        self.assertIn("Service charge 10%", text)


class DiscountApprovalTests(PrintingTestCase):
    def pay(self, user, discount, approver=None):
        lines = self.lines()                     # subtotal RM 41.80
        due = checkout.quote(sum(l.total for l in lines), "takeaway", settings.load(),
                             discount, "card").due
        return checkout.pay(None, "takeaway", lines, user, "card", due, reference="APPR 5555",
                            discount=discount, discount_approver=approver)

    def test_rule(self):
        s = settings.load()
        self.assertEqual(s["discount_limit_bp"], 2000)
        need = checkout.needs_discount_approval
        self.assertFalse(need(836, 4180, s, self.cashier))     # exactly 20%: fine
        self.assertTrue(need(837, 4180, s, self.cashier))      # just over 20%
        self.assertTrue(need(837, 4180, s, self.admin))        # admins too (password)
        self.assertFalse(need(0, 4180, s, self.cashier))
        self.assertFalse(need(500, 0, s, self.cashier))
        off = dict(s, cashier_discounts=False)
        self.assertTrue(need(100, 4180, off, self.cashier))    # switch off: any discount
        self.assertFalse(need(100, 4180, off, self.admin))

    def test_small_discount_needs_nobody(self):
        result = self.pay(self.cashier, Discount("percent", 2000))
        order, _ = orders.load_order(result.order_id)
        self.assertEqual((order["discount_label"], order["discount_approved_by"]), ("20%", None))

    def test_big_discount_needs_an_admin(self):
        for user in (self.cashier, self.admin):
            with self.assertRaisesRegex(orders.OrderError, "over 20% need an admin"):
                self.pay(user, Discount("percent", 2500))
            with self.assertRaises(orders.OrderError):          # a cashier can't approve
                self.pay(user, Discount("amount", 1000), approver=self.cashier)
        result = self.pay(self.cashier, Discount("amount", 1000), approver=self.admin)
        order, _ = orders.load_order(result.order_id)
        self.assertEqual((order["discount_cents"], order["discount_approved_by"]),
                         (1000, self.admin_id))
        with db.connect() as conn:
            log = conn.execute("SELECT details FROM audit_log WHERE action = 'payment' "
                               "ORDER BY id DESC").fetchone()["details"]
        self.assertIn("approved by Owner", log)

    def test_limit_can_be_changed(self):
        settings.save(dict(SETTINGS, discount_limit="50"), self.admin_id)
        self.pay(self.cashier, Discount("percent", 5000))       # 50% now fine
        settings.save(dict(SETTINGS, cashier_discounts=False), self.admin_id)
        with self.assertRaisesRegex(orders.OrderError, "Cashiers can't"):
            self.pay(self.cashier, Discount("percent", 500))


if __name__ == "__main__":
    unittest.main()
