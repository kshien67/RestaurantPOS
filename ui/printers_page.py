"""Admin screen: which printers to use for receipts and kitchen tickets.

Each printer can be:
  Virtual (PDF)  - no printer needed: every slip is saved as a PDF + a text
                   file in the printouts folder. Perfect for demos.
  Network (LAN)  - a thermal printer on the shop's network. Enter its IP
                   address (it's on the printer's self-test slip).
  Windows / USB  - a printer installed in Windows (install its driver first).
'Test print' uses what's on the screen, so you can try before saving.
"""
import os
import tkinter as tk
from tkinter import messagebox, ttk

from services import printing
from ui import theme
from ui.header import Header

OPTION_BG = "#EEE9E1"


class PrinterForm(tk.Frame):
    """One card: the settings for the receipt printer or the kitchen printer."""

    def __init__(self, parent, role, cfg, on_test):
        super().__init__(parent, bg=theme.SURFACE, padx=20, pady=14,
                         highlightthickness=1, highlightbackground="#E2DED7")
        self.role = role
        title = "Receipt printer (counter)" if role == "receipt" else "Kitchen printer"
        theme.label(self, title, font=theme.F_HEADING).pack(anchor="w")

        self.kind = tk.StringVar(value=cfg.kind)
        self.host = tk.StringVar(value=cfg.host)
        self.port = tk.StringVar(value=str(cfg.port))
        self.windows_name = tk.StringVar(value=cfg.windows_name)
        self.paper = tk.StringVar(value=str(cfg.paper))
        self.auto_print = tk.BooleanVar(value=cfg.auto_print)
        self.cash_drawer = tk.BooleanVar(value=cfg.cash_drawer)

        self._choices("Type", self.kind,
                      [(k, printing.KIND_NAMES[k]) for k in printing.KINDS[role]],
                      command=self._show_details)
        self.details = tk.Frame(self, bg=theme.SURFACE)
        self.details.pack(fill="x", pady=(8, 0))
        self._choices("Paper", self.paper, [("80", "80mm"), ("58", "58mm")])
        if role == "receipt":
            theme.toggle(self, "Print the receipt automatically after payment",
                         self.auto_print).pack(anchor="w", pady=(10, 3))
            theme.toggle(self, "Open the cash drawer on cash payments",
                         self.cash_drawer).pack(anchor="w", pady=3)
        theme.small_button(self, "Test print", lambda: on_test(self), color=theme.HEADER
                           ).pack(anchor="w", pady=(12, 0))
        self._show_details()

    def _choices(self, label, variable, options, command=None):
        row = tk.Frame(self, bg=theme.SURFACE)
        row.pack(fill="x", pady=(10, 0))
        theme.label(row, label, width=6, anchor="w").pack(side="left")
        for value, text in options:
            tk.Radiobutton(row, text=text, value=value, variable=variable, indicatoron=False,
                           font=(theme.FONT, 13, "bold"), bg=OPTION_BG, fg=theme.TEXT,
                           selectcolor=theme.TOGGLE_ON, activebackground=theme.TOGGLE_ON,
                           relief="flat", bd=0, padx=10, pady=8, cursor="hand2",
                           command=command).pack(side="left", padx=(0, 6))

    def _hint(self, text):
        theme.label(self.details, text, color=theme.TEXT_MUTED, font=theme.F_SMALL,
                    wraplength=520, justify="left").pack(anchor="w", pady=(4, 0))

    def _show_details(self):
        for w in self.details.winfo_children():
            w.destroy()
        kind = self.kind.get()
        if kind == "none":
            self._hint("No kitchen tickets will be printed.")
        elif kind == "virtual":
            self._hint("No printer needed: every slip is saved as a PDF and a text file in "
                       "the printouts folder.")
        elif kind == "network":
            row = tk.Frame(self.details, bg=theme.SURFACE)
            row.pack(fill="x")
            theme.label(row, "IP address").pack(side="left")
            theme.entry(row, width=16, numeric=True, textvariable=self.host
                        ).pack(side="left", padx=(8, 16), ipady=5)
            theme.label(row, "Port").pack(side="left")
            theme.entry(row, width=6, numeric=True, textvariable=self.port
                        ).pack(side="left", padx=(8, 0), ipady=5)
            self._hint("The IP address is printed on the printer's self-test slip "
                       "(usually: hold FEED while switching it on). Port is normally 9100.")
        else:
            row = tk.Frame(self.details, bg=theme.SURFACE)
            row.pack(fill="x")
            box = ttk.Combobox(row, textvariable=self.windows_name, state="readonly",
                               font=theme.F_BODY, width=28)
            box.pack(side="left")

            found = theme.label(self.details, "", color=theme.DANGER, font=theme.F_SMALL)

            def refresh():
                names = printing.list_windows_printers()
                found.config(text="" if names else "No receipt printers found in Windows yet.")
                if self.windows_name.get() and self.windows_name.get() not in names:
                    names.insert(0, self.windows_name.get())
                box.config(values=names)
            theme.small_button(row, "Refresh", refresh).pack(side="left", padx=8)
            found.pack(anchor="w", pady=(4, 0))
            refresh()
            self._hint("Plug in the printer and install its Windows driver, then tap Refresh "
                       "and choose it. The app sends it ESC/POS commands directly.")

    def values(self):
        return {"kind": self.kind.get(), "host": self.host.get(), "port": self.port.get(),
                "windows_name": self.windows_name.get(), "paper": self.paper.get(),
                "auto_print": self.auto_print.get(), "cash_drawer": self.cash_drawer.get()}


class PrintersPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=theme.BG)
        self.app = app
        Header(self, app, "Printers", back_to="admin_home").pack(fill="x")

        bar = tk.Frame(self, bg=theme.BG, padx=16, pady=12)
        bar.pack(fill="x")
        theme.small_button(bar, "Open printouts folder", self.open_folder).pack(side="left")
        theme.label(bar, "Works with ESC/POS thermal printers: Epson, Xprinter, POSMAC, "
                         "Rongta, HPRT...", bg=theme.BG, color=theme.TEXT_MUTED,
                    font=theme.F_SMALL).pack(side="left", padx=12)
        theme.button(bar, "Save printers", self.save, color=theme.SUCCESS).pack(side="right")

        body = tk.Frame(self, bg=theme.BG, padx=16)
        body.pack(fill="both", expand=True, pady=(0, 16))
        body.columnconfigure(0, weight=1, uniform="col")
        body.columnconfigure(1, weight=1, uniform="col")
        body.rowconfigure(0, weight=1)
        self.forms = {}
        for col, role in enumerate(("receipt", "kitchen")):
            form = PrinterForm(body, role, printing.load_config(role), self.test)
            form.grid(row=0, column=col, sticky="nsew", padx=(0, 12) if col == 0 else 0)
            self.forms[role] = form

    def save(self):
        try:
            # Check both first, so nothing is half-saved.
            for role, form in self.forms.items():
                printing.validate_config(role, form.values())
            for role, form in self.forms.items():
                printing.save_config(role, form.values(), self.app.current_user.id)
        except ValueError as err:
            messagebox.showerror("Cannot save", str(err))
            return
        messagebox.showinfo("Saved", "Printer settings saved.")

    def test(self, form):
        try:
            cfg = printing.validate_config(form.role, form.values())
        except ValueError as err:
            messagebox.showerror("Check the settings", str(err))
            return
        result = printing.test_print(cfg)
        if result.ok:
            messagebox.showinfo("Test print", result.message)
        else:
            messagebox.showwarning("Printer problem", result.message)

    def open_folder(self):
        folder = printing.printouts_dir()
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)           # opens it in Windows Explorer
