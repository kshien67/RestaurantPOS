"""Restaurant POS - start the app with:  py main.py
Try it with sample data (a separate demo database):  py main.py --demo

The App class is the single window. Each screen is a Frame class; show_page()
destroys the current screen and builds a fresh one, so every screen always
shows up-to-date data from the database.
"""
import sys
import tkinter as tk
from tkinter import messagebox

import config
from database import db
from services import auth, demo
from ui import keyboard, theme
from ui.addons_page import AddonsPage
from ui.home_pages import AdminHome, CashierHome
from ui.login_page import LoginPage
from ui.menu_page import MenuPage
from ui.open_orders_page import OpenOrdersPage
from ui.order_page import OrderPage
from ui.printers_page import PrintersPage
from ui.receipts_page import ReceiptsPage
from ui.settings_page import SettingsPage
from ui.setup_page import SetupPage
from ui.staff_page import StaffPage
from ui.tables_admin_page import TablesAdminPage
from ui.tables_page import TablesPage

# page name -> (screen class, admin only?)
PAGES = {
    "setup": (SetupPage, False),
    "login": (LoginPage, False),
    "admin_home": (AdminHome, True),
    "cashier_home": (CashierHome, False),
    "order": (OrderPage, False),
    "open_orders": (OpenOrdersPage, False),
    "tables": (TablesPage, False),
    "receipts": (ReceiptsPage, False),
    "tables_admin": (TablesAdminPage, True),
    "printers": (PrintersPage, True),
    "staff": (StaffPage, True),
    "menu": (MenuPage, True),
    "addons": (AddonsPage, True),
    "settings": (SettingsPage, True),
}
PUBLIC_PAGES = {"setup", "login"}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(config.APP_TITLE)
        self.geometry(config.WINDOW_SIZE)
        self.minsize(1024, 700)
        self.configure(bg=theme.BG)
        theme.apply_ttk_styles(self)
        keyboard.install(self)    # on-screen keyboard pops up when a text box is tapped

        self.current_user = None
        self.current_page = None
        self.container = tk.Frame(self, bg=theme.BG)
        self.container.pack(fill="both", expand=True)

        # F11 toggles full screen (useful on the shop's touchscreen).
        self.bind("<F11>", lambda _e: self.attributes(
            "-fullscreen", not self.attributes("-fullscreen")))
        # The window's X button also asks before throwing away an unsaved order.
        self.protocol("WM_DELETE_WINDOW", self.close)

        self._switch("login" if auth.has_any_admin() else "setup")

    def show_page(self, name, **kwargs):
        """Go to another screen. Extra kwargs are passed to the screen,
        e.g. show_page("order", order_id=5)."""
        if self._may_leave():
            self._switch(name, **kwargs)

    def _may_leave(self):
        # A screen with unsaved work (like the order screen) can ask "are you sure?".
        page = self.current_page
        if page is not None and hasattr(page, "confirm_leave"):
            return page.confirm_leave()
        return True

    def _switch(self, name, **kwargs):
        page_class, admin_only = PAGES[name]
        if name not in PUBLIC_PAGES and self.current_user is None:
            name, page_class, kwargs = "login", LoginPage, {}
        elif admin_only and not self.current_user.is_admin:
            messagebox.showerror("Not allowed", "Only an admin can open this screen.")
            return

        keyboard.hide_all()
        if self.current_page is not None:
            self.current_page.destroy()
        self.current_page = page_class(self.container, self, **kwargs)
        self.current_page.pack(fill="both", expand=True)

    def login(self, user):
        self.current_user = user
        self._switch("admin_home" if user.is_admin else "cashier_home")

    def logout(self):
        if not self._may_leave():
            return
        if self.current_user:
            db.log_action(self.current_user.id, "logout")
        self.current_user = None
        self._switch("login")

    def close(self):
        if self._may_leave():
            self.destroy()


if __name__ == "__main__":
    if "--demo" in sys.argv:
        db.init_db(config.DEMO_DB_PATH)
        demo.ensure_demo_data()        # fills the demo database the first time
    else:
        db.init_db()
    App().mainloop()
