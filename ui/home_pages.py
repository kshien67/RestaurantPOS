"""Landing screens after login.

AdminHome   - big tiles for each management area.
CashierHome - start an order (dine-in, takeaway, delivery), re-open a saved
              one, or look up today's receipts.

Tiles for features not built yet are greyed out with "coming soon", so you can
see the whole plan in the app as it grows.
"""
import tkinter as tk

import config
from services import orders
from ui import dialogs, theme
from ui.header import Header


def _tile_grid(parent, tiles, columns=3):
    grid = tk.Frame(parent, bg=theme.BG)
    grid.pack(expand=True)
    for i, (text, command) in enumerate(tiles):
        ready = command is not None
        btn = theme.button(
            grid, text if ready else f"{text}\n(coming soon)",
            command or (lambda: None),
            color=theme.PRIMARY if ready else theme.DISABLED,
            width=18, font=(theme.FONT, 17, "bold"),
            state="normal" if ready else "disabled",
        )
        btn.configure(pady=40)
        btn.grid(row=i // columns, column=i % columns, padx=14, pady=14)
    return grid


class AdminHome(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=theme.BG)
        Header(self, app, "Admin").pack(fill="x")

        theme.label(self, f"Hello, {app.current_user.full_name}", font=theme.F_TITLE,
                    bg=theme.BG).pack(pady=(30, 10))

        _tile_grid(self, [
            ("Take Orders", lambda: app.show_page("cashier_home")),
            ("Staff Accounts", lambda: app.show_page("staff")),
            ("Menu", lambda: app.show_page("menu")),
            ("Add-ons", lambda: app.show_page("addons")),
            ("Shop Settings", lambda: app.show_page("settings")),
            ("Tables", lambda: app.show_page("tables_admin")),
            ("Printers", lambda: app.show_page("printers")),
            ("Stock", None),              # Phase 7
        ], columns=4)


class CashierHome(tk.Frame):
    def __init__(self, parent, app, flash=None):
        super().__init__(parent, bg=theme.BG)
        self.app = app
        back = "admin_home" if app.current_user.is_admin else None
        Header(self, app, "Sales", back_to=back).pack(fill="x")

        if flash:   # e.g. "Takeaway #12 saved" after coming back from an order
            tk.Label(self, text=flash, font=theme.F_HEADING, bg=theme.TOGGLE_ON,
                     fg=theme.TEXT, pady=10).pack(fill="x")

        theme.label(self, "New order", font=theme.F_TITLE, bg=theme.BG).pack(pady=(30, 10))

        open_count = len(orders.list_open_orders())
        _tile_grid(self, [
            ("Dine-in (Tables)", lambda: app.show_page("tables")),
            ("Takeaway", lambda: app.show_page("order", order_type="takeaway")),
            ("Delivery", self.start_delivery),
            (f"Open orders ({open_count})", lambda: app.show_page("open_orders")),
            ("Receipts", lambda: app.show_page("receipts")),
        ], columns=3)

    def start_delivery(self):
        platform = dialogs.ask_choice(self, "Delivery", "Which delivery platform?",
                                      config.DELIVERY_PLATFORMS)
        if platform is None:
            return
        ref = dialogs.ask_text(self, "Delivery", f"{platform} order number (optional):")
        if ref is None:
            return
        self.app.show_page("order", order_type="delivery", delivery_platform=platform,
                           delivery_ref=ref.strip() or None)
