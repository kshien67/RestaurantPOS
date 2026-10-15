"""Checkout: covers the order screen when 'Pay' is tapped.

Left:   the bill - subtotal, discount, service charge, tax, cash rounding.
Right:  how the customer pays.
        Cash     -> quick buttons (Exact, RM 60, RM 100...) or the number pad,
                    and the change to give back.
        Card /   -> take the money on the bank's terminal or QR first, enter
        E-wallet    its approval code / transaction ID (required), then Confirm.
        GrabFood -> (delivery-app orders only) the app collects the money;
        etc.        counted separately from the cash drawer.
After paying it shows the change in big numbers and the receipt.
Nothing is saved until 'Confirm' succeeds; 'Back' changes nothing.
"""
import tkinter as tk
from tkinter import messagebox

from services import checkout, formats, orders, printing, receipts
from services import settings as shop_settings
from ui import dialogs, theme
from ui.approval import ask_admin_password
from ui.receipt_view import ReceiptView

KEY_BG = "#EEE9E1"
BILL_BG = "#FAF7F2"
DISCOUNT_CHOICES = ["5%", "10%", "15%", "20%", "50%", "Other %", "RM amount", "No discount"]
PAD_KEYS = [("7", "8", "9", "⌫"), ("4", "5", "6", "C"), ("1", "2", "3", ""), ("0", "00", ".", "")]


class CheckoutPanel(tk.Frame):
    def __init__(self, page):
        super().__init__(page, bg="#59636B")                 # dark backdrop
        self.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.page = page
        self.app = page.app
        self.discount = None
        self.discount_approver = None    # the admin who approved a big discount
        # GrabFood etc. orders start on "paid through the app"; others on cash.
        self.methods = checkout.methods_for(page.order_type, page.delivery_platform)
        self.method = self.methods[0]
        self.amount = ""            # what has been typed on the cash pad, e.g. "50.00"
        self.reference = ""

        self.card = tk.Frame(self, bg=theme.SURFACE, padx=24, pady=16)
        self.card.place(relx=0.5, rely=0.5, anchor="center")
        # Build with the cash layout (the biggest one), measure it, and keep
        # that size, so nothing gets cut off and the window doesn't jump
        # around when switching between methods.
        first_method, self.method = self.method, "cash"
        self._build()
        self.render()
        self.update_idletasks()
        self.method_area.config(width=max(470, self.method_area.winfo_reqwidth()),
                                height=self.method_area.winfo_reqheight())
        self.method_area.pack_propagate(False)
        if first_method != "cash":
            self.set_method(first_method)

    @property
    def settings(self):
        return self.page.settings

    def money(self, cents):
        return self.page.money(cents)

    # ================= layout =================
    def _build(self):
        c = self.card
        theme.label(c, f"Pay  ·  {self.page.title_text()}", font=theme.F_HEADING
                    ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        # ----- left: the bill -----
        left = tk.Frame(c, bg=theme.SURFACE)
        left.grid(row=1, column=0, sticky="nw", padx=(0, 24))
        self.bill = tk.Frame(left, bg=BILL_BG, padx=16, pady=12)
        self.bill.pack(fill="x")
        self.bill.columnconfigure(0, minsize=230)
        self.bill.columnconfigure(1, minsize=130)
        self.discount_row = tk.Frame(left, bg=theme.SURFACE)
        self.discount_row.pack(fill="x", pady=(12, 0))

        # ----- right: payment -----
        right = tk.Frame(c, bg=theme.SURFACE)
        right.grid(row=1, column=1, sticky="nw")
        methods = tk.Frame(right, bg=theme.SURFACE)
        methods.pack(anchor="w")
        self.method_buttons = {}
        for key in self.methods:
            text = checkout.method_label(key, self.page.delivery_platform)
            b = tk.Button(methods, text=text, width=9, font=(theme.FONT, 15, "bold"),
                          relief="flat", bd=0, pady=12, cursor="hand2",
                          command=lambda k=key: self.set_method(k))
            b.pack(side="left", padx=(0, 6))
            self.method_buttons[key] = b
        self.method_area = tk.Frame(right, bg=theme.SURFACE)
        self.method_area.pack(anchor="w", pady=(12, 0))
        self._build_method_area()

        # ----- bottom -----
        self.message = theme.label(c, "", color=theme.DANGER)
        self.message.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        bottom = tk.Frame(c, bg=theme.SURFACE)
        bottom.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        theme.button(bottom, "Back", self.destroy, color=theme.NEUTRAL).pack(side="left")
        self.confirm_button = theme.button(bottom, "", self.confirm, color=theme.SUCCESS)
        self.confirm_button.pack(side="right", fill="x", expand=True, padx=(10, 0))

    def _build_method_area(self):
        area = self.method_area
        for w in area.winfo_children():
            w.destroy()
        if self.method == "cash":
            theme.label(area, "Amount received", font=(theme.FONT, 13, "bold"),
                        color=theme.TEXT_MUTED).pack(anchor="w")
            self.amount_label = tk.Label(area, font=(theme.FONT, 24, "bold"), bg=BILL_BG,
                                         anchor="e", padx=12, pady=4)
            self.amount_label.pack(fill="x")
            self.quick = tk.Frame(area, bg=theme.SURFACE)
            self.quick.pack(fill="x", pady=(8, 6))
            pad = tk.Frame(area, bg=theme.SURFACE)
            pad.pack(anchor="w")
            for r, row in enumerate(PAD_KEYS):
                for col, key in enumerate(row):
                    if key:
                        tk.Button(pad, text=key, width=5, font=(theme.FONT, 18, "bold"),
                                  bg=KEY_BG, fg=theme.TEXT, activebackground=theme.TOGGLE_ON,
                                  relief="flat", bd=0, pady=1, cursor="hand2",
                                  command=lambda k=key: self.press(k)
                                  ).grid(row=r, column=col, padx=3, pady=2)
            # " " (not "") so the label takes up its full height from the start.
            self.change_label = tk.Label(area, text=" ", font=(theme.FONT, 20, "bold"),
                                         bg=theme.SURFACE)
            self.change_label.pack(anchor="w", pady=(10, 0))
        elif self.method == "platform":
            app_name = self.page.delivery_platform
            theme.label(area, f"{app_name} collects the money from the customer\n"
                              "and pays the shop later.\n\n"
                              "Tap Confirm to close this order. It is counted as\n"
                              f"'{app_name}', not as cash in the drawer.",
                        justify="left", font=(theme.FONT, 15)).pack(anchor="w", pady=(6, 16))
        else:
            where = "card terminal" if self.method == "card" else "customer's e-wallet / QR"
            code = ("approval code from the card slip" if self.method == "card"
                    else "transaction ID from the e-wallet")
            theme.label(area, f"1. Take the payment on the {where}.\n"
                              f"2. Enter the {code}.\n"
                              "3. Tap Confirm below.",
                        justify="left", font=(theme.FONT, 15)).pack(anchor="w", pady=(6, 16))
            row = tk.Frame(area, bg=theme.SURFACE)
            row.pack(anchor="w")
            theme.small_button(row, "Enter reference no.", self.ask_reference,
                               color=theme.HEADER).pack(side="left")
            self.reference_label = theme.label(row, "", font=(theme.FONT, 15, "bold"))
            self.reference_label.pack(side="left", padx=12)

    # ================= numbers =================
    def quote(self):
        subtotal = sum(line.total for line in self.page.lines)
        return checkout.quote(subtotal, self.page.order_type, self.settings,
                              self.discount, self.method)

    def tendered(self):
        """The cash amount typed so far, in cents (None if nothing / not a number)."""
        try:
            return formats.parse_money(self.amount, "Amount received") if self.amount else None
        except ValueError:
            return None

    # ================= drawing =================
    def render(self):
        q = self.quote()
        bill = q.bill
        for w in self.bill.winfo_children():
            w.destroy()
        rows = [("Subtotal", bill.subtotal, False)]
        if bill.discount:
            label = self.discount.label(self.settings["currency"], bill.discount)
            rows.append((f"Discount ({label})", -bill.discount, False))
        if bill.service_rate_bp:
            rows.append((f"Service charge {formats.percent(bill.service_rate_bp)}%",
                         bill.service, False))
        if bill.tax_rate_bp:
            rows.append((f"{self.settings['tax_name']} {formats.percent(bill.tax_rate_bp)}%",
                         bill.tax, False))
        rows.append(("Total", bill.total, not q.rounding))
        if q.rounding:
            rows.append(("Cash rounding", q.rounding, False))
            rows.append(("To pay", q.due, True))
        for r, (name, cents, big) in enumerate(rows):
            font = (theme.FONT, 20 if big else 14, "bold" if big else "normal")
            tk.Label(self.bill, text=name, font=font, bg=BILL_BG, fg=theme.TEXT
                     ).grid(row=r, column=0, sticky="w", pady=2)
            tk.Label(self.bill, text=self.money(cents), font=font, bg=BILL_BG, fg=theme.TEXT
                     ).grid(row=r, column=1, sticky="e", pady=2)

        for w in self.discount_row.winfo_children():
            w.destroy()
        theme.small_button(self.discount_row, "Change discount" if self.discount else "Discount",
                           self.choose_discount).pack(side="left")
        if self.discount:
            theme.small_button(self.discount_row, "Remove", self.remove_discount,
                               color=theme.DANGER).pack(side="left", padx=8)
        if self.discount_approver:
            theme.label(self.discount_row, f"✓ approved by {self.discount_approver.full_name}",
                        color=theme.SUCCESS, font=theme.F_SMALL).pack(side="left", padx=4)

        for key, b in self.method_buttons.items():
            on = key == self.method
            b.config(bg=theme.PRIMARY if on else KEY_BG, fg="white" if on else theme.TEXT,
                     activebackground=theme.PRIMARY_DARK if on else theme.TOGGLE_ON)

        if self.method == "cash":
            self._render_cash(q)
        elif self.method in checkout.NEEDS_REFERENCE:
            if self.reference:
                self.reference_label.config(text=self.reference, fg=theme.TEXT)
            else:
                self.reference_label.config(text="required", fg=theme.DANGER)
        name = checkout.method_label(self.method, self.page.delivery_platform)
        if self.method != "platform":
            name = name.lower()                   # "cash", but keep "GrabFood" as is
        self.confirm_button.config(text=f"Confirm {name} payment   {self.money(q.due)}")

    def _render_cash(self, q):
        if self.amount:
            self.amount_label.config(text=f"{self.settings['currency']} {self.amount}",
                                     fg=theme.TEXT)
        else:
            self.amount_label.config(text="Tap a button or type", fg=theme.TEXT_MUTED)

        for w in self.quick.winfo_children():
            w.destroy()
        # Always at most 4 buttons of the same width, so they always fit.
        for cents in [q.due] + checkout.suggested_notes(q.due):
            text = "Exact" if cents == q.due else self.money(cents)
            theme.small_button(self.quick, text, lambda c=cents: self.set_amount(c),
                               color=theme.HEADER, width=max(9, len(text))
                               ).pack(side="left", padx=(0, 6))

        got = self.tendered()
        if got is None:
            self.change_label.config(text=" ")
        elif got >= q.due:
            self.change_label.config(text=f"Change:  {self.money(got - q.due)}", fg=theme.SUCCESS)
        else:
            self.change_label.config(text=f"Short by {self.money(q.due - got)}", fg=theme.DANGER)

    # ================= actions =================
    def set_method(self, method):
        if method != self.method:
            self.reference = ""     # a card approval code is not an e-wallet ID
        self.method = method
        self.message.config(text="")
        self._build_method_area()
        self.render()

    def set_amount(self, cents):
        self.amount = formats.money_plain(cents)
        self.render()

    def press(self, key):
        """A key on the cash number pad."""
        if key == "C":
            self.amount = ""
        elif key == "⌫":
            self.amount = self.amount[:-1]
        elif key == ".":
            if "." not in self.amount:
                self.amount = (self.amount or "0") + "."
        else:
            whole, dot, cents = self.amount.partition(".")
            if dot and len(cents) + len(key) > 2:
                return                                     # max 2 decimal places
            if not dot and len(whole) + len(key) > 5:
                return                                     # max RM 99,999
            new = self.amount + key
            self.amount = new if dot else (new.lstrip("0") or "0")
        self.message.config(text="")
        self.render()

    def ask_reference(self):
        """Ask for the card approval code / e-wallet transaction ID.
        Returns True if a valid one was entered."""
        prompt = ("Approval code from the card terminal slip:" if self.method == "card"
                  else "Transaction ID / reference from the e-wallet:")
        text = dialogs.ask_text(self, "Reference", prompt, initial=self.reference)
        if text is None:
            return False
        text = " ".join(text.split())
        if not checkout.MIN_REFERENCE <= len(text) <= checkout.MAX_REFERENCE:
            self.message.config(text=f"The reference must be {checkout.MIN_REFERENCE} to "
                                     f"{checkout.MAX_REFERENCE} characters.")
            return False
        self.reference = text
        self.message.config(text="")
        self.render()
        return True

    def choose_discount(self):
        choice = dialogs.ask_choice(self, "Discount", "Discount on the whole bill:",
                                    DISCOUNT_CHOICES, columns=4, width=10)
        if choice is None:
            return
        try:
            if choice == "No discount":
                discount = None
            elif choice == "Other %":
                text = dialogs.ask_text(self, "Discount", "Discount in % (e.g. 12.5):",
                                        numeric=True)
                if text is None:
                    return
                discount = checkout.Discount("percent", formats.parse_percent(text, "Discount"))
            elif choice == "RM amount":
                text = dialogs.ask_text(self, "Discount",
                                        f"Discount amount ({self.settings['currency']}):",
                                        numeric=True)
                if text is None:
                    return
                discount = checkout.Discount("amount", formats.parse_money(text, "Discount"))
            else:
                discount = checkout.Discount("percent", formats.parse_percent(choice))
        except ValueError as err:
            self.message.config(text=str(err))
            return

        # A new discount always needs a new approval (if it needs one at all).
        approver = None
        if discount is not None:
            subtotal = sum(line.total for line in self.page.lines)
            taken = discount.cents(subtotal)
            if checkout.needs_discount_approval(taken, subtotal, self.settings,
                                                self.app.current_user):
                label = discount.label(self.settings["currency"], taken)
                limit = formats.percent(self.settings["discount_limit_bp"])
                why = (f"Discounts over {limit}% need an admin's password."
                       if self.settings["cashier_discounts"] or self.app.current_user.is_admin
                       else "Cashiers need an admin's password for any discount.")
                approver = ask_admin_password(self, f"Discount {label}", why)
                if approver is None:
                    return                         # cancelled: keep the old discount
        self.discount, self.discount_approver = discount, approver
        self.message.config(text="")
        self.render()

    def remove_discount(self):
        self.discount, self.discount_approver = None, None
        self.render()

    def confirm(self):
        q = self.quote()
        tendered = None
        if self.method == "cash":
            if not self.amount:
                self.message.config(text="Tap 'Exact' or type the amount the customer gave.")
                return
            tendered = self.tendered()
            if tendered is None:
                self.message.config(text="The amount received is not a valid number.")
                return
            if tendered < q.due:
                self.message.config(text=f"The customer gave less than {self.money(q.due)}.")
                return
        elif self.method in checkout.NEEDS_REFERENCE and not self.reference:
            # Every card / e-wallet payment needs its reference: ask for it now.
            if not self.ask_reference():
                return
        p = self.page
        user = self.app.current_user
        new_lines = [line for line in p.lines if not line.is_sent]   # saved by this payment
        try:
            result = checkout.pay(
                p.order_id, p.order_type, p.lines, user, self.method, q.due,
                tendered=tendered, reference=self.reference, discount=self.discount,
                delivery_platform=p.delivery_platform, delivery_ref=p.delivery_ref,
                table_id=p.table_id, discount_approver=self.discount_approver)
        except checkout.BillChanged as err:
            p.settings = shop_settings.load()      # pick up the new settings and redraw
            p.refresh_cart(select=p.selected)
            self.render()
            self.message.config(text=str(err))
            return
        except orders.OrderError as err:
            self.message.config(text=str(err))
            return
        p.order_id = result.order_id
        # The sale is saved. Now print: kitchen ticket for the new items,
        # the receipt, and the cash drawer. Printing problems never undo the sale.
        printed = printing.after_payment(result.order_id, result.method,
                                         [line.order_item_id for line in new_lines], user.id)
        self.show_done(result, printed)

    # ================= after payment =================
    def show_done(self, result, printed=()):
        for w in self.card.winfo_children():
            w.destroy()
        c = self.card
        method = checkout.method_label(result.method, self.page.delivery_platform)
        theme.label(c, f"✓  Paid {self.money(result.paid)} by {method}",
                    font=theme.F_TITLE, color=theme.SUCCESS).pack(anchor="w")
        if result.change is not None:
            theme.label(c, f"Change:  {self.money(result.change)}",
                        font=(theme.FONT, 34, "bold")).pack(anchor="w", pady=(4, 0))

        # What was printed (or what went wrong, so it can be fixed and reprinted).
        self.print_status = tk.Frame(c, bg=theme.SURFACE)
        self.print_status.pack(fill="x", pady=(6, 0))
        for item in printed:
            self._show_print_result(item)

        chars = printing.load_config("receipt").chars
        view = ReceiptView(c, height=15, width=chars)
        view.pack(fill="x", pady=(10, 10))
        view.show(receipts.build(result.order_id, chars))

        buttons = tk.Frame(c, bg=theme.SURFACE)
        buttons.pack(fill="x")
        theme.button(buttons, "Print receipt",
                     lambda: self._show_print_result(printing.print_receipt(
                         result.order_id, self.app.current_user.id)),
                     color=theme.HEADER).pack(side="left")
        theme.button(buttons, "Next order  ▶", lambda: self.page.after_payment(result),
                     color=theme.SUCCESS).pack(side="right", fill="x", expand=True, padx=(10, 0))

    def _show_print_result(self, item):
        mark, color = ("✓", theme.SUCCESS) if item.ok else ("⚠", theme.DANGER)
        theme.label(self.print_status, f"{mark} {item.message}", color=color,
                    font=theme.F_SMALL, wraplength=640, justify="left").pack(anchor="w")
        if not item.ok:
            messagebox.showwarning("Printer problem", item.message)
