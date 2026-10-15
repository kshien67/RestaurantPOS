"""List of saved orders that haven't been paid yet. Tap one to open it."""
import tkinter as tk
from datetime import datetime

from database import db
from services import formats, orders
from ui import theme
from ui.header import Header


class OpenOrdersPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=theme.BG)
        self.app = app
        currency = db.get_setting("currency")
        Header(self, app, "Open orders", back_to="cashier_home").pack(fill="x")

        box = theme.card(self, padx=20, pady=16)
        box.pack(fill="both", expand=True, padx=16, pady=16)
        theme.label(box, "Tap an order to open it", color=theme.TEXT_MUTED).pack(anchor="w")

        self.table = theme.tree(box, [("order", "Order", 200), ("ref", "Ref", 160),
                                      ("items", "Items", 80), ("total", "Total", 140),
                                      ("time", "Time", 120), ("staff", "Taken by", 180)],
                                height=12)
        self.table.pack(fill="both", expand=True, pady=(8, 0))
        self.table.bind("<<TreeviewSelect>>", self.open_selected)

        rows = orders.list_open_orders()
        for o in rows:
            time_text = datetime.strptime(o["created_at"], "%Y-%m-%d %H:%M:%S").strftime("%I:%M %p")
            self.table.insert("", "end", iid=str(o["id"]), values=(
                orders.describe(o["order_type"], o["order_no"], o["delivery_platform"],
                                o["table_name"]),
                o["delivery_ref"] or "", o["item_count"],
                formats.money(o["total_cents"], currency), time_text, o["staff_name"]))
        if not rows:
            theme.label(box, "No open orders.", color=theme.TEXT_MUTED).pack(pady=20)

    def open_selected(self, _event):
        sel = self.table.selection()
        if sel:
            self.app.show_page("order", order_id=int(sel[0]))
