"""First-run screen: shown only when there is no admin account yet.

The shop owner sets the shop name and creates the first admin login.
This avoids shipping a default password like admin/admin, which is unsafe.
"""
import tkinter as tk
from tkinter import messagebox

import config
from database import db
from services import auth
from ui import theme


class SetupPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=theme.BG)
        self.app = app

        box = theme.card(self)
        box.place(relx=0.5, rely=0.5, anchor="center")

        theme.label(box, "Welcome! Let's set up your POS", font=theme.F_TITLE
                    ).grid(row=0, column=0, columnspan=2, pady=(0, 6))
        theme.label(box, "Create the owner / admin account. You can add cashiers later.",
                    color=theme.TEXT_MUTED).grid(row=1, column=0, columnspan=2, pady=(0, 20))

        self.fields = {}
        rows = [
            ("shop_name", "Shop name", None),
            ("full_name", "Your full name", None),
            ("username", "Admin username", None),
            ("password", "Password", "*"),
            ("confirm", "Confirm password", "*"),
            ("pin", f"{auth.PIN_LENGTH}-digit PIN (optional)", "*"),
        ]
        for i, (key, text, show) in enumerate(rows, start=2):
            theme.label(box, text).grid(row=i, column=0, sticky="e", padx=(0, 12), pady=6)
            e = theme.entry(box, show=show, width=28, numeric=(key == "pin"))
            e.grid(row=i, column=1, pady=6, ipady=6)
            self.fields[key] = e

        theme.button(box, "Create account", self.submit, width=20
                     ).grid(row=len(rows) + 2, column=0, columnspan=2, pady=(20, 0))

        self.fields["shop_name"].focus_set()
        self.bind_all("<Return>", lambda _e: self.submit())

    def destroy(self):
        self.unbind_all("<Return>")
        super().destroy()

    def submit(self):
        v = {k: e.get() for k, e in self.fields.items()}
        if not v["shop_name"].strip():
            messagebox.showerror("Missing", "Please enter the shop name.")
            return
        if v["password"] != v["confirm"]:
            messagebox.showerror("Password", "The two passwords do not match.")
            return
        try:
            auth.create_user(v["username"], v["full_name"], v["password"], config.ROLE_ADMIN,
                             pin=v["pin"].strip())
        except auth.AuthError as err:
            messagebox.showerror("Cannot create account", str(err))
            return

        db.set_setting("shop_name", v["shop_name"].strip())
        messagebox.showinfo("Done", "Admin account created. Please log in.")
        self.app.show_page("login")
