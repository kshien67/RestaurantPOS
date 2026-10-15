"""The cashier's table map.

White table  = free      -> tap to start a dine-in order there.
Orange table = occupied  -> shows order number, time seated and bill so far;
                            tap to open the order and add more items.
The map refreshes itself every 30 seconds so the times stay current.
"""
import math
import tkinter as tk

from database import db
from services import formats, orders, tables
from ui import theme
from ui.header import Header

COLS, ROWS = 6, 4            # tables per page
REFRESH_MS = 30_000


class TablesPage(tk.Frame):
    def __init__(self, parent, app, flash=None):
        super().__init__(parent, bg=theme.BG)
        self.app = app
        self.currency = db.get_setting("currency")
        self.page = 0
        self._after_id = None
        Header(self, app, "Tables", back_to="cashier_home").pack(fill="x")

        if flash:
            tk.Label(self, text=flash, font=theme.F_HEADING, bg=theme.TOGGLE_ON,
                     fg=theme.TEXT, pady=10).pack(fill="x")

        self.summary = theme.label(self, "", bg=theme.BG, color=theme.TEXT_MUTED)
        self.summary.pack(anchor="w", padx=20, pady=(12, 0))
        self.area = tk.Frame(self, bg=theme.BG)
        self.area.pack(fill="both", expand=True, padx=14, pady=(6, 14))
        self.refresh()

    def destroy(self):
        if self._after_id:
            self.after_cancel(self._after_id)   # stop the timer when leaving
        super().destroy()

    def refresh(self):
        if self._after_id:
            self.after_cancel(self._after_id)
        for w in self.area.winfo_children():
            w.destroy()

        rows = tables.table_map()
        if not rows:
            self.summary.config(text="")
            theme.label(self.area, "No tables yet. An admin can add them in Admin → Tables.",
                        bg=theme.BG, color=theme.TEXT_MUTED).pack(pady=40)
            return

        busy = sum(1 for t in rows if t["order_id"])
        self.summary.config(text=f"{busy} of {len(rows)} tables occupied   ·   "
                                 "white = free,  orange = occupied")

        per_page = COLS * ROWS
        pages = max(1, math.ceil(len(rows) / per_page))
        self.page = min(self.page, pages - 1)
        shown = rows[self.page * per_page:(self.page + 1) * per_page]

        grid = tk.Frame(self.area, bg=theme.BG)
        grid.pack(fill="both", expand=True)
        for c in range(COLS):
            grid.columnconfigure(c, weight=1, uniform="col")
        for r in range(ROWS):
            grid.rowconfigure(r, weight=1, uniform="row")

        for i, t in enumerate(shown):
            if t["order_id"]:
                minutes = tables.format_minutes(tables.minutes_since(t["created_at"]))
                text = (f"{t['name']}\n{orders.short_number(t['order_no'])}  ·  {minutes}\n"
                        f"{formats.money(t['total_cents'], self.currency)}")
                colors = dict(bg=theme.PRIMARY, fg="white", activebackground=theme.PRIMARY_DARK,
                              activeforeground="white", relief="flat", bd=0)
            else:
                text = f"{t['name']}\n{t['seats']} seats"
                colors = dict(bg=theme.SURFACE, fg=theme.TEXT, activebackground=theme.TOGGLE_ON,
                              activeforeground=theme.TEXT, relief="solid", bd=1)
            tk.Button(grid, text=text, command=lambda table=t: self.open_table(table),
                      font=(theme.FONT, 16, "bold"), cursor="hand2", **colors
                      ).grid(row=i // COLS, column=i % COLS, sticky="nsew", padx=6, pady=6)

        if pages > 1:
            nav = tk.Frame(self.area, bg=theme.BG)
            nav.pack(fill="x", pady=(6, 0))
            theme.small_button(nav, "◀ Prev", lambda: self.turn_page(-1)).pack(side="left")
            theme.label(nav, f"Page {self.page + 1} of {pages}", bg=theme.BG
                        ).pack(side="left", expand=True)
            theme.small_button(nav, "Next ▶", lambda: self.turn_page(1)).pack(side="right")

        self._after_id = self.after(REFRESH_MS, self.refresh)

    def turn_page(self, step):
        self.page = max(0, self.page + step)
        self.refresh()

    def open_table(self, table):
        if table["order_id"]:
            self.app.show_page("order", order_id=table["order_id"])
        else:
            self.app.show_page("order", order_type="dine_in", table_id=table["id"])
