"""Admin screen to add cashiers/admins, disable accounts and reset passwords.

Accounts are disabled, never deleted, so old sales still show who made them.
"""
import tkinter as tk
from tkinter import messagebox, ttk

import config
from services import auth
from ui import dialogs, theme
from ui.header import Header


class StaffPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=theme.BG)
        self.app = app
        Header(self, app, "Staff Accounts", back_to="admin_home").pack(fill="x")

        body = tk.Frame(self, bg=theme.BG, padx=24, pady=20)
        body.pack(fill="both", expand=True)

        # ----- Left: list of staff -----
        left = theme.card(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 16))
        theme.label(left, "All staff", font=theme.F_HEADING).pack(anchor="w", pady=(0, 10))

        cols = ("username", "full_name", "role", "status", "pin")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        for col, text, width in [("username", "Username", 140), ("full_name", "Name", 200),
                                 ("role", "Role", 100), ("status", "Status", 100),
                                 ("pin", "PIN", 70)]:
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True)

        actions = tk.Frame(left, bg=theme.SURFACE)
        actions.pack(fill="x", pady=(12, 0))
        theme.button(actions, "Enable / Disable", self.toggle_active,
                     color=theme.NEUTRAL).pack(side="left")
        theme.button(actions, "Reset password", self.reset_password,
                     color=theme.NEUTRAL).pack(side="left", padx=10)
        theme.button(actions, "Set PIN", self.set_pin, color=theme.NEUTRAL).pack(side="left")

        # ----- Right: add new staff -----
        right = theme.card(body, padx=24, pady=20)
        right.pack(side="right", fill="y")
        top = tk.Frame(right, bg=theme.SURFACE)
        top.pack(fill="x", pady=(0, 10))
        theme.label(top, "Add staff", font=theme.F_HEADING).pack(side="left")
        # Button at the top so the on-screen keyboard never covers it.
        theme.small_button(top, "Add", self.add_staff, color=theme.SUCCESS, width=6
                           ).pack(side="right")

        self.fields = {}
        for key, text, show, numeric in [
            ("full_name", "Full name", None, False),
            ("username", "Username", None, False),
            ("password", "Password", "*", False),
            ("pin", f"{auth.PIN_LENGTH}-digit PIN (optional)", "*", True),
        ]:
            theme.label(right, text, anchor="w").pack(fill="x")
            e = theme.entry(right, show=show, numeric=numeric)
            e.pack(ipady=6, pady=(2, 10))
            self.fields[key] = e

        theme.label(right, "Role", anchor="w").pack(fill="x")
        self.role = tk.StringVar(value=config.ROLE_CASHIER)
        role_row = tk.Frame(right, bg=theme.SURFACE)
        role_row.pack(fill="x", pady=(2, 16))
        for r in config.ROLES:
            tk.Radiobutton(role_row, text=r.title(), value=r, variable=self.role,
                           font=theme.F_BODY, bg=theme.SURFACE, indicatoron=False,
                           selectcolor=theme.PRIMARY, width=9, pady=8
                           ).pack(side="left", padx=(0, 8))

        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for u in auth.list_users():
            self.tree.insert("", "end", iid=str(u["id"]), values=(
                u["username"], u["full_name"], u["role"].title(),
                "Active" if u["is_active"] else "Disabled",
                "Set" if u["has_pin"] else "-",
            ))

    def _selected_id(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Select staff", "Tap a staff member in the list first.")
            return None
        return int(sel[0])

    def add_staff(self):
        v = {k: e.get() for k, e in self.fields.items()}
        try:
            auth.create_user(v["username"], v["full_name"], v["password"], self.role.get(),
                             created_by=self.app.current_user.id, pin=v["pin"].strip())
        except auth.AuthError as err:
            messagebox.showerror("Cannot add staff", str(err))
            return
        for e in self.fields.values():
            e.delete(0, "end")
        self.refresh()

    def toggle_active(self):
        user_id = self._selected_id()
        if user_id is None:
            return
        is_active = self.tree.set(str(user_id), "status") == "Active"
        try:
            auth.set_active(user_id, not is_active, self.app.current_user.id)
        except auth.AuthError as err:
            messagebox.showerror("Not allowed", str(err))
            return
        self.refresh()
        self.tree.selection_set(str(user_id))

    def reset_password(self):
        user_id = self._selected_id()
        if user_id is None:
            return
        name = self.tree.set(str(user_id), "username")
        new = dialogs.ask_text(self, "Reset password", f"New password for {name}:", show="*")
        if not new:
            return
        try:
            auth.reset_password(user_id, new, self.app.current_user.id)
        except auth.AuthError as err:
            messagebox.showerror("Cannot reset", str(err))
            return
        messagebox.showinfo("Done", f"Password for {name} has been changed.")

    def set_pin(self):
        user_id = self._selected_id()
        if user_id is None:
            return
        name = self.tree.set(str(user_id), "username")
        pin = dialogs.ask_text(self, "Set PIN",
                               f"New {auth.PIN_LENGTH}-digit PIN for {name}\n"
                               "(leave empty to remove PIN login):", show="*", numeric=True)
        if pin is None:
            return
        pin = pin.strip()
        if pin:
            again = dialogs.ask_text(self, "Set PIN", f"Type the PIN for {name} again:",
                                     show="*", numeric=True)
            if again is None:
                return
            if again.strip() != pin:
                messagebox.showerror("PIN", "The two PINs do not match.")
                return
        try:
            auth.set_pin(user_id, pin, self.app.current_user.id)
        except auth.AuthError as err:
            messagebox.showerror("Cannot set PIN", str(err))
            return
        self.refresh()
        self.tree.selection_set(str(user_id))
        messagebox.showinfo("Done", f"PIN for {name} has been {'set' if pin else 'removed'}.")
