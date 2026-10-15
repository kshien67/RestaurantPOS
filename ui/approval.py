"""'Admin approval' pop-ups.

ask_void_approval()  - before voiding an order, or an item already sent to the
                       kitchen. Step 1: choose a reason. Step 2: admin password.
ask_admin_password() - just the admin password, e.g. for a discount above the
                       shop's limit (20% by default).

An admin taps their name and types their PASSWORD - every time, even when an
admin is the one logged in, so nothing can be approved from an admin's
unattended screen. 5 wrong passwords lock that admin's approvals for a minute.
"""
import tkinter as tk
from tkinter import messagebox

import config
from services import auth, orders
from ui import dialogs, theme

OTHER = "Other reason..."
NAME_BG = "#EEE9E1"


def _open_window(parent, title):
    root = parent.winfo_toplevel()
    win = tk.Toplevel(root)
    win.title(title)
    win.configure(bg=theme.SURFACE)
    win.transient(root)
    win.resizable(False, False)
    body = tk.Frame(win, bg=theme.SURFACE, padx=28, pady=20)
    body.pack(fill="both", expand=True)
    win.bind("<Escape>", lambda _e: win.destroy())
    return root, win, body


def _show_and_wait(root, win):
    # At the top of the main window, leaving room for the keyboard below.
    win.update_idletasks()
    x = root.winfo_rootx() + max(0, (root.winfo_width() - win.winfo_reqwidth()) // 2)
    win.geometry(f"+{x}+{root.winfo_rooty() + 10}")
    win.grab_set()                    # block the rest of the app until this closes
    win.wait_window()


def _clear(body):
    for w in body.winfo_children():
        w.destroy()


def _password_step(win, body, what, subtitle, on_approved, info=None):
    """Admin name buttons + password box. Calls on_approved(admin User).
    `info` = optional (text, button text, command) row, e.g. the void reason.
    Kept compact on purpose: the on-screen keyboard opens below it, and both
    together must fit on the screen."""
    _clear(body)
    top = tk.Frame(body, bg=theme.SURFACE)
    top.pack(fill="x")
    theme.label(top, what, font=theme.F_HEADING).pack(side="left")
    theme.label(top, f"   {subtitle}", color=theme.TEXT_MUTED).pack(side="left")
    if info:
        text, button_text, command = info
        row = tk.Frame(body, bg=theme.SURFACE)
        row.pack(fill="x", pady=(8, 0))
        theme.label(row, text, wraplength=520, justify="left",
                    font=(theme.FONT, 14, "bold")).pack(side="left")
        if button_text:
            theme.small_button(row, button_text, command).pack(side="right")

    admin_row = tk.Frame(body, bg=theme.SURFACE)
    admin_row.pack(fill="x", pady=(12, 0))
    theme.label(admin_row, "Admin:", width=9, anchor="nw").pack(side="left", anchor="n", pady=8)
    names = tk.Frame(admin_row, bg=theme.SURFACE)
    names.pack(side="left")
    admins = auth.list_admins()
    buttons = {}
    chosen = {"admin": None}

    password_row = tk.Frame(body, bg=theme.SURFACE)
    password_row.pack(fill="x", pady=(8, 0))
    theme.label(password_row, "Password:", width=9, anchor="w").pack(side="left")
    password = theme.entry(password_row, show="*", width=28)
    error = theme.label(body, "", color=theme.DANGER)

    def choose(admin):
        chosen["admin"] = admin
        for admin_id, b in buttons.items():
            on = admin_id == admin["id"]
            b.config(bg=theme.PRIMARY if on else NAME_BG, fg="white" if on else theme.TEXT)
        error.config(text="")
        password.focus_set()          # brings up the on-screen keyboard

    def approve():
        if chosen["admin"] is None:
            error.config(text="Tap an admin's name first.")
            return
        try:
            approver = auth.approve_as_admin(chosen["admin"]["username"], password.get())
        except auth.AuthError as err:
            error.config(text=str(err))
            password.delete(0, "end")
            return
        on_approved(approver)

    for i, admin in enumerate(admins):
        b = tk.Button(names, text=admin["full_name"], width=14, bg=NAME_BG, fg=theme.TEXT,
                      font=(theme.FONT, 14, "bold"), relief="flat", bd=0, pady=8,
                      cursor="hand2", command=lambda a=admin: choose(a))
        b.grid(row=i // 4, column=i % 4, padx=(0, 8), pady=3)
        buttons[admin["id"]] = b

    password.pack(side="left", fill="x", expand=True, ipady=6)
    password.bind("<Return>", lambda _e: approve())
    error.pack(anchor="w", pady=(4, 0))
    bottom = tk.Frame(body, bg=theme.SURFACE)
    bottom.pack(fill="x", pady=(6, 0))
    theme.small_button(bottom, "Cancel", win.destroy, width=8).pack(side="left")
    theme.small_button(bottom, "Approve", approve, color=theme.DANGER
                       ).pack(side="right", fill="x", expand=True, padx=(10, 0))
    if len(admins) == 1:
        choose(admins[0])


def ask_void_approval(parent, what):
    """`what` describes the void, e.g. 'Void Table T3 #12 (RM 44.07)'.
    Returns (admin User, reason), or None if cancelled."""
    root, win, body = _open_window(parent, "Admin approval")
    state = {"reason": None, "result": None}

    def step_reason():
        _clear(body)
        theme.label(body, what, font=theme.F_HEADING).pack(anchor="w")
        theme.label(body, "Step 1 of 2:  why is it being voided?", color=theme.TEXT_MUTED
                    ).pack(anchor="w", pady=(2, 14))
        grid = tk.Frame(body, bg=theme.SURFACE)
        grid.pack(fill="x")
        for i, reason in enumerate(list(config.VOID_REASONS) + [OTHER]):
            theme.button(grid, reason, lambda r=reason: pick_reason(r),
                         color=theme.NEUTRAL if reason == OTHER else theme.HEADER,
                         width=26, font=(theme.FONT, 14, "bold")
                         ).grid(row=i // 2, column=i % 2, padx=5, pady=5, sticky="ew")
        theme.button(body, "Cancel", win.destroy, color=theme.NEUTRAL
                     ).pack(fill="x", pady=(14, 0))

    def pick_reason(reason):
        if reason == OTHER:
            text = dialogs.ask_text(win, "Void reason", "Type the reason:")
            win.grab_set()            # take control back after the typing pop-up closes
            if text is None:
                return
            try:
                reason = orders.clean_reason(text)
            except orders.OrderError as err:
                messagebox.showerror("Reason", str(err), parent=win)
                return
        state["reason"] = reason
        _password_step(win, body, what, "Step 2 of 2: admin approval", approved,
                       info=(f"Reason: {reason}", "Change", step_reason))

    def approved(admin):
        state["result"] = (admin, state["reason"])
        win.destroy()

    step_reason()
    _show_and_wait(root, win)
    return state["result"]


def ask_admin_password(parent, what, why):
    """Just an admin's password. Returns the admin User, or None if cancelled."""
    root, win, body = _open_window(parent, "Admin approval")
    state = {"result": None}

    def approved(admin):
        state["result"] = admin
        win.destroy()

    _password_step(win, body, what, "Admin approval", approved, info=(why, None, None))
    _show_and_wait(root, win)
    return state["result"]
