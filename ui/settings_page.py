"""Admin screen: shop details printed on receipts, and tax / service charge.

The "Example bill" box updates as you type, using the same calculation the
real checkout will use, so you can check the numbers before saving.
"""
import tkinter as tk
from tkinter import messagebox

from services import formats, pricing, settings
from ui import theme
from ui.header import Header

EXAMPLE_SUBTOTAL = 4730   # RM 47.30, chosen so cash rounding is visible


class SettingsPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=theme.BG)
        self.app = app
        s = settings.load()
        self.currency = s["currency"]
        Header(self, app, "Shop Settings", back_to="admin_home").pack(fill="x")

        bar = tk.Frame(self, bg=theme.BG, padx=16, pady=12)
        bar.pack(fill="x")
        theme.button(bar, "Save settings", self.save, color=theme.SUCCESS).pack(side="right")

        body = tk.Frame(self, bg=theme.BG, padx=16)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1, uniform="col")
        body.columnconfigure(1, weight=1, uniform="col")
        body.rowconfigure(0, weight=1)

        # ----- Left: receipt details -----
        left = theme.card(body, padx=20, pady=14)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12), pady=(0, 16))
        theme.label(left, "Receipt details", font=theme.F_HEADING).pack(anchor="w", pady=(0, 8))
        self.vars = {}
        for key, text in [("shop_name", "Shop name"), ("shop_address", "Address"),
                          ("shop_phone", "Phone"), ("tax_reg_no", "SST registration no."),
                          ("receipt_footer", "Message at bottom of receipt")]:
            self._text_field(left, key, text, s[key])

        theme.label(left, "Discounts", font=theme.F_HEADING).pack(anchor="w", pady=(8, 4))
        var = tk.BooleanVar(value=s["cashier_discounts"])
        theme.toggle(left, "Cashiers can give discounts", var).pack(anchor="w")
        self.vars["cashier_discounts"] = var
        # Bigger discounts need an admin's password (every discount is also logged).
        limit_row = tk.Frame(left, bg=theme.SURFACE)
        limit_row.pack(anchor="w", pady=(6, 0))
        theme.label(limit_row, "Discounts above").pack(side="left")
        limit = tk.StringVar(value=formats.percent(s["discount_limit_bp"]))
        theme.entry(limit_row, width=5, numeric=True, textvariable=limit
                    ).pack(side="left", padx=6, ipady=3)
        theme.label(limit_row, "% need an admin's password").pack(side="left")
        self.vars["discount_limit"] = limit

        # ----- Right: tax & charges -----
        right = theme.card(body, padx=20, pady=14)
        right.grid(row=0, column=1, sticky="nsew", pady=(0, 16))
        theme.label(right, "Tax & charges", font=theme.F_HEADING).pack(anchor="w", pady=(0, 8))

        rates = tk.Frame(right, bg=theme.SURFACE)
        rates.pack(fill="x")
        for col, (key, text, value, numeric) in enumerate([
            ("tax_name", "Tax name", s["tax_name"], False),
            ("tax_rate", "Tax rate %", formats.percent(s["tax_rate_bp"]), True),
            ("service_rate", "Service charge %", formats.percent(s["service_rate_bp"]), True),
        ]):
            cell = tk.Frame(rates, bg=theme.SURFACE)
            cell.grid(row=0, column=col, sticky="w", padx=(0, 12))
            self._text_field(cell, key, text, value, numeric=numeric, width=12)

        for key, text, value in [
            ("service_dine_in_only", "Service charge for dine-in only", s["service_dine_in_only"]),
            ("tax_on_service", "Charge tax on service charge too", s["tax_on_service"]),
            ("cash_rounding", "Round cash bills to nearest 5 sen", s["cash_rounding_cents"] == 5),
        ]:
            var = tk.BooleanVar(value=value)
            var.trace_add("write", lambda *_: self.update_preview())
            theme.toggle(right, text, var).pack(anchor="w", pady=3)
            self.vars[key] = var

        theme.label(right, "Menu prices are entered WITHOUT tax; tax is added at checkout.",
                    font=theme.F_SMALL, color=theme.TEXT_MUTED).pack(anchor="w", pady=(6, 4))

        self.preview = tk.Frame(right, bg="#FAF7F2", padx=12, pady=8)
        self.preview.pack(fill="x", pady=(6, 0))
        self.update_preview()

    def _text_field(self, parent, key, text, value, numeric=False, width=30):
        theme.label(parent, text, anchor="w").pack(fill="x")
        var = tk.StringVar(value=value)
        var.trace_add("write", lambda *_: self.update_preview())
        theme.entry(parent, width=width, numeric=numeric, textvariable=var
                    ).pack(fill="x", ipady=5, pady=(2, 8))
        self.vars[key] = var

    def _raw(self):
        return {key: var.get() for key, var in self.vars.items()}

    def update_preview(self):
        if not hasattr(self, "preview"):
            return                       # still building the screen
        for child in self.preview.winfo_children():
            child.destroy()

        def cell(text, row, col, bold=False):
            tk.Label(self.preview, text=text, bg="#FAF7F2", fg=theme.TEXT,
                     font=(theme.FONT, 12, "bold" if bold else "normal")
                     ).grid(row=row, column=col, sticky="w" if col == 0 else "e", padx=6)

        try:
            s = settings.validate(self._raw())
        except ValueError as err:
            cell(f"Example bill: {err}", 0, 0)
            return

        money = lambda c: formats.money(c, self.currency)    # noqa: E731
        bills = [pricing.calculate_bill(EXAMPLE_SUBTOTAL, t, s) for t in ("dine_in", "takeaway")]
        cell(f"Example bill: food {money(EXAMPLE_SUBTOTAL)}", 0, 0, bold=True)
        cell("Dine-in", 0, 1, bold=True)
        cell("Takeaway", 0, 2, bold=True)
        rows = [
            ("Service charge", [f"{money(b.service)} ({formats.percent(b.service_rate_bp)}%)"
                                for b in bills]),
            (f"{s['tax_name']}", [f"{money(b.tax)} ({formats.percent(b.tax_rate_bp)}%)"
                                  for b in bills]),
            ("Total", [money(b.total) for b in bills]),
        ]
        if s["cash_rounding_cents"]:
            rows.append(("Total if paid by cash",
                         [money(pricing.round_cash(b.total, s["cash_rounding_cents"]))
                          for b in bills]))
        for r, (name, values) in enumerate(rows, start=1):
            bold = name.startswith("Total")
            cell(name, r, 0, bold)
            cell(values[0], r, 1, bold)
            cell(values[1], r, 2, bold)

    def save(self):
        try:
            settings.save(self._raw(), self.app.current_user.id)
        except ValueError as err:
            messagebox.showerror("Cannot save", str(err))
            return
        messagebox.showinfo("Saved", "Settings saved.")
        self.app.show_page("settings")   # reload so the header shows the new shop name
