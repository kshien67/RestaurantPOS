"""Login screen.

Quick login: tap your name, then type your 4-digit PIN.
Backup: username + password (needed until the admin sets PINs in Staff Accounts).

After login, admins go to the admin dashboard and cashiers go to the sales screen.
"""
import tkinter as tk

from database import db
from services import auth, demo
from ui import theme
from ui.pinpad import PinPad


class LoginPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=theme.BG)
        self.app = app
        self.pin_users = auth.list_pin_users()
        self.body = None
        self.pinpad = None
        self.password = None

        if self.pin_users:
            self.show_names()
        else:
            self.show_password_form()

        self.bind_all("<Return>", self._on_return)
        self.bind_all("<KeyPress>", self._on_key)

    def destroy(self):
        self.unbind_all("<Return>")
        self.unbind_all("<KeyPress>")
        super().destroy()

    def _new_body(self):
        if self.body is not None:
            self.body.destroy()
        self.body = tk.Frame(self, bg=theme.BG)
        self.body.pack(fill="both", expand=True)
        self.pinpad = None
        self.password = None
        return self.body

    # ---------- step 1: tap your name ----------
    def show_names(self):
        body = self._new_body()
        theme.label(body, db.get_setting("shop_name"), font=theme.F_TITLE,
                    bg=theme.BG).pack(pady=(50, 4))
        theme.label(body, "Tap your name", color=theme.TEXT_MUTED, bg=theme.BG).pack(pady=(0, 24))

        grid = tk.Frame(body, bg=theme.BG)
        grid.pack()
        for i, user in enumerate(self.pin_users):
            color = theme.HEADER if user["role"] == "admin" else theme.PRIMARY
            btn = theme.button(grid, user["full_name"], lambda u=user: self.show_pinpad(u),
                               color=color, width=14, font=(theme.FONT, 17, "bold"))
            btn.configure(pady=28)
            btn.grid(row=i // 4, column=i % 4, padx=10, pady=10)

        theme.small_button(body, "Log in with username & password",
                           self.show_password_form).pack(side="bottom", pady=24)
        if demo.is_demo():
            tk.Label(body, text=demo.LOGIN_HINT, font=theme.F_BODY, bg="#F2C14E",
                     fg=theme.TEXT, padx=12, pady=8).pack(side="bottom")

    # ---------- step 2: PIN ----------
    def show_pinpad(self, user):
        body = self._new_body()
        self.pin_user = user
        self.pinpad = PinPad(body, f"Hi {user['full_name']}, enter your PIN",
                             self._check_pin, on_cancel=self.show_names, length=auth.PIN_LENGTH)
        self.pinpad.place(relx=0.5, rely=0.5, anchor="center")

    def _check_pin(self, pin):
        try:
            user = auth.authenticate_pin(self.pin_user["id"], pin)
        except auth.AuthError as err:
            return str(err)
        self.app.login(user)
        return None

    # ---------- backup: username + password ----------
    def show_password_form(self):
        body = self._new_body()
        box = theme.card(body)
        box.place(relx=0.5, rely=0.5, anchor="center")

        theme.label(box, db.get_setting("shop_name"), font=theme.F_TITLE).pack()
        theme.label(box, "Staff login", color=theme.TEXT_MUTED).pack(pady=(0, 20))

        theme.label(box, "Username", anchor="w").pack(fill="x")
        self.username = theme.entry(box, width=26)
        self.username.pack(ipady=8, pady=(2, 12))

        theme.label(box, "Password", anchor="w").pack(fill="x")
        self.password = theme.entry(box, show="*", width=26)
        self.password.pack(ipady=8, pady=(2, 8))

        self.error = theme.label(box, "", color=theme.DANGER, font=theme.F_SMALL)
        self.error.pack(pady=(0, 8))

        theme.button(box, "Log in", self.submit, width=20).pack(fill="x")
        if self.pin_users:
            theme.small_button(box, "Back to PIN login", self.show_names
                               ).pack(fill="x", pady=(10, 0))
        self.username.focus_set()

    def submit(self):
        try:
            user = auth.authenticate(self.username.get(), self.password.get())
        except auth.AuthError as err:
            self.error.config(text=str(err))
            self.password.delete(0, "end")
            self.password.focus_set()
            return
        self.app.login(user)

    # ---------- keys ----------
    def _on_return(self, _event):
        if self.password is not None and self.password.winfo_exists():
            self.submit()

    def _on_key(self, event):
        if self.pinpad is not None and self.pinpad.winfo_exists():
            self.pinpad.type_key(event)
