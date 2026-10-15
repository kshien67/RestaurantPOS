"""A day's receipts (paid orders), plus voided orders in red with their
reason and the admin who approved them. Tap one to see it on the right.

The bar at the top shows the day's takings by payment method: at closing
time, the Cash figure is what should be in the cash drawer (plus any float
you started the day with). 'Delivery apps' is money GrabFood etc. will pay
out later - it is NOT in the drawer.
"""
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import messagebox

from services import checkout, formats, orders, printing, receipts
from services import settings as shop_settings
from ui import theme
from ui.header import Header
from ui.receipt_view import ReceiptView


class ReceiptsPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=theme.BG)
        self.app = app
        self.day = date.today()
        self.currency = shop_settings.load()["currency"]
        Header(self, app, "Receipts", back_to="cashier_home").pack(fill="x")

        bar = tk.Frame(self, bg=theme.BG, padx=16, pady=10)
        bar.pack(fill="x")
        theme.small_button(bar, "◀", lambda: self.change_day(-1), width=3).pack(side="left")
        self.day_label = theme.label(bar, "", font=theme.F_HEADING, bg=theme.BG, width=17)
        self.day_label.pack(side="left")
        self.next_button = theme.small_button(bar, "▶", lambda: self.change_day(1), width=3)
        self.next_button.pack(side="left")
        theme.small_button(bar, "Today", self.go_today).pack(side="left", padx=(10, 0))
        self.summary = theme.label(bar, "", bg=theme.BG, font=(theme.FONT, 13, "bold"),
                                   justify="right")
        self.summary.pack(side="right")

        body = tk.Frame(self, bg=theme.BG, padx=16)
        body.pack(fill="both", expand=True, pady=(0, 16))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        left = theme.card(body, padx=14, pady=12)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        # "Ref" = card approval code / e-wallet transaction ID, for matching
        # against the bank's settlement report at closing time.
        self.table = theme.tree(left, [("time", "Time", 90), ("order", "Order", 170),
                                       ("method", "Paid by", 100), ("ref", "Ref", 120),
                                       ("amount", "Amount", 110), ("staff", "Staff", 110)])
        self.table.tag_configure("void", foreground=theme.DANGER)
        self.table.pack(fill="both", expand=True)
        self.table.bind("<<TreeviewSelect>>", self.show_selected)

        right = tk.Frame(body, bg=theme.BG)
        right.grid(row=0, column=1, sticky="ns")
        # Buttons first, so they always stay visible under the slip.
        self.reprint_button = theme.small_button(right, "Reprint receipt (marked COPY)",
                                                 self.reprint, color=theme.HEADER)
        self.reprint_button.pack(side="bottom", fill="x", pady=(8, 0))
        self.chars = printing.load_config("receipt").chars
        self.view = ReceiptView(right, height=24, width=self.chars)
        self.view.pack(fill="both", expand=True)
        self.selected_id = None
        self.load()

    def change_day(self, step):
        self.day = min(date.today(), self.day + timedelta(days=step))
        self.load()

    def go_today(self):
        self.day = date.today()
        self.load()

    def load(self):
        rows = receipts.list_receipts(self.day)
        is_today = self.day == date.today()
        self.day_label.config(text="Today" if is_today else self.day.strftime("%a %d %b %Y"))
        self.next_button.config(state="disabled" if is_today else "normal",
                                bg=theme.DISABLED if is_today else theme.NEUTRAL)

        self.table.delete(*self.table.get_children())
        for r in rows:
            when = datetime.strptime(r["closed_at"], "%Y-%m-%d %H:%M:%S").strftime("%I:%M %p")
            name = orders.describe(r["order_type"], r["order_no"], r["delivery_platform"],
                                   r["table_name"])
            if r["status"] == "void":
                # Voided orders are listed (in red) for checking, but are not takings.
                # Staff = the admin who approved the void.
                values = (when, name, "VOID", "", formats.money(r["total_cents"], self.currency),
                          r["staff_name"])
                tags = ("void",)
            else:
                values = (when, name, checkout.method_label(r["method"], r["delivery_platform"]),
                          r["reference"] or "", formats.money(r["amount_cents"], self.currency),
                          r["staff_name"])
                tags = ()
            self.table.insert("", "end", iid=str(r["id"]), values=values, tags=tags)

        t = receipts.day_totals(rows)
        money = lambda c: formats.money(c, self.currency)   # noqa: E731
        paid = len(rows) - t["void_count"]
        voids = (f"   ·   Voided {t['void_count']} ({money(t['void_total'])})"
                 if t["void_count"] else "")
        self.summary.config(
            text=f"{paid} receipt{'' if paid == 1 else 's'}   ·   Total {money(t['total'])}"
                 f"{voids}\n"
                 f"Cash {money(t['cash'])}   ·   Card {money(t['card'])}   ·   "
                 f"E-wallet {money(t['ewallet'])}   ·   Delivery apps {money(t['platform'])}")
        self.view.show(["", "  Tap a receipt on the left to see it."] if rows
                       else ["", "  No receipts on this day."])
        self.selected_id = None
        self._update_reprint_button(None)

    def show_selected(self, _event):
        sel = self.table.selection()
        if sel:
            self.selected_id = int(sel[0])
            self.view.show(receipts.build(self.selected_id, self.chars))
            self._update_reprint_button("void" in self.table.item(sel[0], "tags"))

    def _update_reprint_button(self, is_void):
        # Only paid receipts can be reprinted (not voids, not before choosing one).
        ready = is_void is False
        self.reprint_button.config(state="normal" if ready else "disabled",
                                   bg=theme.HEADER if ready else theme.DISABLED)

    def reprint(self):
        if self.selected_id is None:
            return
        result = printing.print_receipt(self.selected_id, self.app.current_user.id)
        if result.ok:
            messagebox.showinfo("Reprint", result.message)
        else:
            messagebox.showwarning("Printer problem", result.message)
