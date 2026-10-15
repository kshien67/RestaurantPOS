"""The order screen: categories (left), item buttons (middle), the order (right).

Tap an item: if it has add-ons, a picker opens; otherwise it goes straight in.
Tap a line in the order to change it with  − / + / Edit / Note / Remove.
'Save order' stores the new lines (Phase 6 will also print the kitchen ticket then).
'Pay' opens checkout, which saves any new lines and takes payment in one step.
"""
import math
import tkinter as tk
from tkinter import messagebox, ttk

from services import formats, menu, orders, pricing, printing, tables
from services import settings as shop_settings
from ui import dialogs, theme
from ui.approval import ask_void_approval
from ui.checkout_panel import CheckoutPanel
from ui.header import Header

COLS, ROWS = 4, 6              # item buttons per page
OPTION_BG = "#EEE9E1"
OPTIONS_PER_ROW = 6            # add-on buttons per row in the picker


class OrderPage(tk.Frame):
    def __init__(self, parent, app, order_id=None, order_type="takeaway",
                 delivery_platform=None, delivery_ref=None, table_id=None):
        super().__init__(parent, bg=theme.BG)
        self.app = app
        self.settings = shop_settings.load()
        self.order_id = order_id
        self.order_type = order_type
        self.delivery_platform = delivery_platform
        self.delivery_ref = delivery_ref
        self.table_id = table_id
        self.table_name = None
        self.order_no = None
        self.lines = []
        self.selected = None           # the CartLine tapped in the order
        if order_id is not None:
            order, self.lines = orders.load_order(order_id)
            self.order_type = order["order_type"]
            self.delivery_platform = order["delivery_platform"]
            self.delivery_ref = order["delivery_ref"]
            self.order_no = order["order_no"]
            self.table_id = order["table_id"]
            self.table_name = order["table_name"]
        elif table_id is not None:
            self.table_name = next((t["name"] for t in tables.list_tables()
                                    if t["id"] == table_id), None)

        self.categories = menu.list_categories(active_only=True)
        self.category_id = self.categories[0]["id"] if self.categories else None
        self.item_page = 0
        self.picker = None

        # Dine-in orders go back to the table map; others to the sales screen.
        self.home = "tables" if self.order_type == "dine_in" else "cashier_home"
        title = self.title_text()
        Header(self, app, title, back_to=self.home).pack(fill="x")

        body = tk.Frame(self, bg=theme.BG, padx=12, pady=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self.cat_frame = tk.Frame(body, bg=theme.BG)
        self.cat_frame.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        self.item_area = tk.Frame(body, bg=theme.BG)
        self.item_area.grid(row=0, column=1, sticky="nsew", padx=(0, 10))
        cart = theme.card(body, padx=14, pady=12)
        cart.grid(row=0, column=2, sticky="nsew")
        self._build_cart(cart, title)

        self.draw_categories()
        self.draw_items()
        self.refresh_cart()

    def money(self, cents):
        return formats.money(cents, self.settings["currency"])

    def title_text(self, order_no=None):
        return orders.describe(self.order_type, order_no or self.order_no,
                               self.delivery_platform, self.table_name)

    # ================= categories & items =================
    def draw_categories(self):
        for w in self.cat_frame.winfo_children():
            w.destroy()
        for c in self.categories:
            on = c["id"] == self.category_id
            tk.Button(self.cat_frame, text=c["name"], width=12, wraplength=170,
                      command=lambda cid=c["id"]: self.select_category(cid),
                      font=(theme.FONT, 15, "bold"),
                      bg=c["color"] if on else theme.tint(c["color"]),
                      fg="white" if on else theme.TEXT,
                      activebackground=c["color"], activeforeground="white",
                      relief="flat", bd=0, pady=14, cursor="hand2").pack(fill="x", pady=(0, 8))

    def select_category(self, cat_id):
        self.category_id = cat_id
        self.item_page = 0
        self.draw_categories()
        self.draw_items()

    def draw_items(self):
        for w in self.item_area.winfo_children():
            w.destroy()
        if self.category_id is None:
            theme.label(self.item_area, "The menu is empty. An admin can add items "
                        "on the Menu screen.", bg=theme.BG, color=theme.TEXT_MUTED).pack(pady=40)
            return

        category = next(c for c in self.categories if c["id"] == self.category_id)
        items = menu.list_items(self.category_id, active_only=True)
        per_page = COLS * ROWS
        pages = max(1, math.ceil(len(items) / per_page))
        self.item_page = min(self.item_page, pages - 1)
        shown = items[self.item_page * per_page:(self.item_page + 1) * per_page]

        grid = tk.Frame(self.item_area, bg=theme.BG)
        grid.pack(fill="both", expand=True)
        for c in range(COLS):
            grid.columnconfigure(c, weight=1, uniform="col")
        for r in range(ROWS):
            grid.rowconfigure(r, weight=1, uniform="row")
        for i, item in enumerate(shown):
            tk.Button(grid, text=f"{item['name']}\n{self.money(item['price_cents'])}",
                      command=lambda it=item: self.tap_item(it), wraplength=140,
                      font=(theme.FONT, 14, "bold"), bg=category["color"], fg="white",
                      activebackground=theme.PRIMARY_DARK, activeforeground="white",
                      relief="flat", bd=0, cursor="hand2"
                      ).grid(row=i // COLS, column=i % COLS, sticky="nsew", padx=4, pady=4)
        if not items:
            theme.label(grid, "No items in this category.", bg=theme.BG,
                        color=theme.TEXT_MUTED).grid(row=0, column=0, columnspan=COLS)

        if pages > 1:
            nav = tk.Frame(self.item_area, bg=theme.BG)
            nav.pack(fill="x", pady=(6, 0))
            theme.small_button(nav, "◀ Prev", lambda: self.turn_page(-1)).pack(side="left")
            theme.label(nav, f"Page {self.item_page + 1} of {pages}", bg=theme.BG
                        ).pack(side="left", expand=True)
            theme.small_button(nav, "Next ▶", lambda: self.turn_page(1)).pack(side="right")

    def turn_page(self, step):
        self.item_page = max(0, self.item_page + step)
        self.draw_items()

    def tap_item(self, item):
        groups = menu.item_addon_groups(item["id"])
        if groups:
            self.open_picker(item["name"], item["price_cents"], groups,
                             on_done=lambda mods, qty: self._add_new(item, mods, qty))
        else:
            self._add_new(item, [], 1)

    def _add_new(self, item, modifiers, qty):
        line = orders.CartLine(item["id"], item["name"], item["price_cents"], modifiers, qty)
        self.refresh_cart(select=orders.add_line(self.lines, line))

    # ================= add-on picker =================
    def open_picker(self, name, base_price, groups, on_done, chosen_ids=None, qty=1):
        def done(mods, new_qty):
            self.close_picker()
            on_done(mods, new_qty)
        self.picker = AddonPicker(self, name, base_price, groups, self.money, done,
                                  self.close_picker, chosen_ids, qty)

    def close_picker(self):
        if self.picker is not None:
            self.picker.destroy()
            self.picker = None

    # ================= the order (cart) =================
    def _build_cart(self, card, title):
        top = tk.Frame(card, bg=theme.SURFACE)
        top.pack(fill="x")
        theme.label(top, title, font=theme.F_HEADING).pack(side="left")
        if self.order_id is not None and self.order_type == "dine_in":
            theme.small_button(top, "Move table", self.move_table).pack(side="right")
            theme.small_button(top, "Print bill", self.print_bill).pack(side="right", padx=(0, 6))
        if self.delivery_ref:
            theme.label(card, f"Ref: {self.delivery_ref}", color=theme.TEXT_MUTED).pack(anchor="w")

        box = tk.Frame(card, bg=theme.SURFACE)
        box.pack(fill="both", expand=True, pady=(8, 8))
        # height=6 is the minimum; the list grows to fill whatever space is left.
        self.cart = ttk.Treeview(box, columns=("amount",), show="tree", selectmode="browse",
                                 style="Cart.Treeview", height=6)
        self.cart.column("#0", width=270)
        self.cart.column("amount", width=105, anchor="e")
        self.cart.tag_configure("line", font=(theme.FONT, 14, "bold"))
        self.cart.tag_configure("sent", foreground=theme.TEXT_MUTED)
        self.cart.tag_configure("sub", font=(theme.FONT, 12), foreground=theme.TEXT_MUTED)
        bar = ttk.Scrollbar(box, orient="vertical", command=self.cart.yview)
        self.cart.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.cart.pack(side="left", fill="both", expand=True)
        self.cart.bind("<<TreeviewSelect>>", self.on_cart_select)

        controls = tk.Frame(card, bg=theme.SURFACE)
        controls.pack(fill="x")
        for text, command, color in [("−", self.decrease, theme.NEUTRAL),
                                     ("+", self.increase, theme.NEUTRAL),
                                     ("Edit", self.edit_line, theme.NEUTRAL),
                                     ("Note", self.note_line, theme.NEUTRAL),
                                     ("Remove", self.remove_line, theme.DANGER)]:
            theme.small_button(controls, text, command, color=color
                               ).pack(side="left", expand=True, fill="x", padx=2)

        self.totals = tk.Frame(card, bg=theme.SURFACE)
        self.totals.pack(fill="x", pady=(10, 8))

        actions = tk.Frame(card, bg=theme.SURFACE)
        actions.pack(fill="x")
        if self.order_id is None:
            theme.button(actions, "Cancel", self.cancel, color=theme.DANGER).pack(side="left")
        else:
            theme.button(actions, "Void order", self.void_order, color=theme.DANGER
                         ).pack(side="left")
        theme.button(actions, "Save order", self.save, color=theme.SUCCESS
                     ).pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.pay_button = theme.button(card, "Pay", self.pay, color=theme.PRIMARY,
                                       font=(theme.FONT, 17, "bold"))
        self.pay_button.pack(fill="x", pady=(8, 0))

    def refresh_cart(self, select=None):
        self.cart.delete(*self.cart.get_children())
        for i, line in enumerate(self.lines):
            mark = "✓ " if line.is_sent else ""
            tags = ("line", "sent") if line.is_sent else ("line",)
            self.cart.insert("", "end", iid=f"L{i}", text=f"{mark}{line.qty} × {line.name}",
                             values=(self.money(line.total),), tags=tags)
            for j, m in enumerate(line.modifiers):
                extra = f"  (+{formats.money_plain(m.price)})" if m.price else ""
                self.cart.insert("", "end", iid=f"L{i}-m{j}", text=f"      + {m.name}{extra}",
                                 tags=("sub",))
            if line.note:
                self.cart.insert("", "end", iid=f"L{i}-n", text=f"      Note: {line.note}",
                                 tags=("sub",))

        self.selected = select if select in self.lines else None
        if self.selected is not None:
            iid = f"L{self.lines.index(self.selected)}"
            self.cart.selection_set(iid)
            self.cart.see(iid)
        self._draw_totals()

    def _draw_totals(self):
        for w in self.totals.winfo_children():
            w.destroy()
        bill = pricing.calculate_bill(sum(line.total for line in self.lines),
                                      self.order_type, self.settings)
        rows = [("Subtotal", bill.subtotal)]
        if bill.service_rate_bp:
            rows.append((f"Service charge {formats.percent(bill.service_rate_bp)}%", bill.service))
        if bill.tax_rate_bp:
            rows.append((f"{self.settings['tax_name']} {formats.percent(bill.tax_rate_bp)}%",
                         bill.tax))
        rows.append(("Total", bill.total))
        for r, (name, cents) in enumerate(rows):
            big = name == "Total"
            font = (theme.FONT, 18 if big else 13, "bold" if big else "normal")
            theme.label(self.totals, name, font=font).grid(row=r, column=0, sticky="w")
            theme.label(self.totals, self.money(cents), font=font).grid(row=r, column=1, sticky="e")
        self.totals.columnconfigure(1, weight=1)
        self.pay_button.config(text=f"Pay   {self.money(bill.total)}" if self.lines else "Pay")

    def on_cart_select(self, _event):
        sel = self.cart.selection()
        if not sel:
            return
        index = int(sel[0][1:].split("-")[0])
        self.selected = self.lines[index]
        if sel[0] != f"L{index}":            # tapped an add-on/note row: select its line
            self.cart.selection_set(f"L{index}")

    def _need_selection(self):
        if self.selected is None:
            messagebox.showinfo("Choose an item", "Tap an item in the order first.")
            return None
        return self.selected

    def _sent_message(self):
        messagebox.showinfo("Already sent", "This item was already sent to the kitchen, "
                            "so it can't be changed. Use Remove to void it "
                            "(needs a reason and an admin's password).")

    def increase(self):
        line = self._need_selection()
        if line is None:
            return
        if line.is_sent:
            # Sent lines are locked, so add one more as a new line.
            copy = orders.CartLine(line.menu_item_id, line.name, line.base_price,
                                   list(line.modifiers), 1, line.note)
            self.refresh_cart(select=orders.add_line(self.lines, copy))
            return
        line.qty = min(orders.MAX_QTY, line.qty + 1)
        self.refresh_cart(select=line)

    def decrease(self):
        line = self._need_selection()
        if line is None:
            return
        if line.is_sent:
            self.remove_line()
        elif line.qty > 1:
            line.qty -= 1
            self.refresh_cart(select=line)
        else:
            self.lines.remove(line)
            self.refresh_cart()

    def remove_line(self):
        line = self._need_selection()
        if line is None:
            return
        if not line.is_sent:
            # Never saved, so nothing was recorded: no approval needed.
            self.lines.remove(line)
            self.refresh_cart()
            return
        # Already sent to the kitchen: needs a reason + an admin's password.
        approval = ask_void_approval(
            self, f"Void {line.qty} × {line.name}   ({self.money(line.total)})")
        if approval is None:
            return
        approver, reason = approval
        try:
            orders.void_line(line.order_item_id, approver, reason,
                             requested_by=self.app.current_user.id)
        except orders.OrderError as err:
            messagebox.showerror("Cannot void", str(err))
            return
        self.lines.remove(line)
        self.refresh_cart()
        # Tell the kitchen to stop making it.
        self._report_print(printing.print_kitchen(
            self.order_id, [line.order_item_id], self.app.current_user.id,
            void=True, reason=reason))

    def edit_line(self):
        line = self._need_selection()
        if line is None:
            return
        if line.is_sent:
            self._sent_message()
            return
        groups = menu.item_addon_groups(line.menu_item_id)
        if not groups:
            messagebox.showinfo("No add-ons", f"{line.name} has no add-ons to change.")
            return

        def done(mods, qty):
            line.modifiers, line.qty = mods, qty
            self.refresh_cart(select=line)
        self.open_picker(line.name, line.base_price, groups, done,
                         chosen_ids={m.id for m in line.modifiers}, qty=line.qty)

    def note_line(self):
        line = self._need_selection()
        if line is None:
            return
        if line.is_sent:
            self._sent_message()
            return
        text = dialogs.ask_text(self, "Note", f"Note for {line.name} (e.g. no ice):",
                                initial=line.note)
        if text is None:
            return
        try:
            line.note = orders.clean_note(text)
        except orders.OrderError as err:
            messagebox.showerror("Note", str(err))
            return
        self.refresh_cart(select=line)

    # ================= save / cancel =================
    def unsent_count(self):
        return sum(line.qty for line in self.lines if not line.is_sent)

    def confirm_leave(self):
        """Called by the app before leaving this screen."""
        count = self.unsent_count()
        if count == 0:
            return True
        return messagebox.askyesno("Leave this order?",
                                   f"{count} item(s) have not been saved.\n"
                                   "Leave and lose them?")

    def save(self):
        if not self.unsent_count():
            messagebox.showinfo("Nothing to save",
                                "There are no new items to save." if self.lines
                                else "Tap items on the left to add them first.")
            return
        count = self.unsent_count()
        new_lines = [line for line in self.lines if not line.is_sent]
        try:
            order_id, order_no = orders.save_order(
                self.order_id, self.order_type, self.lines, self.app.current_user.id,
                self.delivery_platform, self.delivery_ref, self.table_id)
        except orders.OrderError as err:
            messagebox.showerror("Cannot save", str(err))
            return
        # Saved. Now the kitchen ticket for the new items (never undoes the save).
        result = printing.print_kitchen(order_id, [line.order_item_id for line in new_lines],
                                        self.app.current_user.id)
        self._report_print(result)
        printed = f"  {result.message}" if result and result.ok else ""
        self.app.show_page(self.home, flash=f"{self.title_text(order_no)} saved "
                                            f"({count} new item(s)).{printed}")

    def print_bill(self):
        """Print the bill for a table that asks for it (before paying)."""
        if self.unsent_count():
            messagebox.showinfo("Save first", "Save the new items first, so they are on the bill.")
            return
        result = printing.print_bill(self.order_id, self.app.current_user.id)
        if result.ok:
            messagebox.showinfo("Bill", result.message)
        else:
            self._report_print(result)

    def _report_print(self, result):
        """A printer problem must be noticed (e.g. the kitchen never got the order)."""
        if result is not None and not result.ok:
            messagebox.showwarning("Printer problem", result.message)

    def pay(self):
        if not self.lines:
            messagebox.showinfo("Nothing to pay", "Tap items on the left to add them first.")
            return
        CheckoutPanel(self)          # saving + paying happens there, in one step

    def after_payment(self, result):
        change = f"  Change: {self.money(result.change)}." if result.change else ""
        self.app.show_page(self.home, flash=f"{self.title_text(result.order_no)} paid.{change}")

    def cancel(self):
        if self.lines and not messagebox.askyesno("Cancel order",
                                                  "Remove all items and cancel this order?"):
            return
        self.lines = []
        self.app.show_page(self.home)

    def void_order(self):
        """Anyone can ask, but it needs a reason and an admin's password."""
        title = self.title_text()
        saved = sum(line.total for line in self.lines if line.is_sent)
        total = pricing.calculate_bill(saved, self.order_type, self.settings).total
        approval = ask_void_approval(self, f"Void {title}   ({self.money(total)})")
        if approval is None:
            return
        approver, reason = approval
        sent_ids = [line.order_item_id for line in self.lines if line.is_sent]
        try:
            orders.void_order(self.order_id, approver, reason,
                              requested_by=self.app.current_user.id)
        except orders.OrderError as err:
            messagebox.showerror("Cannot void", str(err))
            return
        # Tell the kitchen to stop making everything on this order.
        self._report_print(printing.print_kitchen(self.order_id, sent_ids,
                                                  self.app.current_user.id,
                                                  void=True, reason=reason))
        self.lines = []
        self.app.show_page(self.home, flash=f"{title} was voided "
                                            f"(approved by {approver.full_name}).")

    def move_table(self):
        if self.unsent_count():
            messagebox.showinfo("Save first", "Save or remove the new items first, "
                                "then move the table.")
            return
        free = tables.free_tables()
        if not free:
            messagebox.showinfo("No free tables", "All tables are occupied.")
            return
        title = self.title_text()
        # More columns when there are many free tables, so the window never
        # gets taller than the screen (max ~5 rows).
        choice = dialogs.ask_choice(self, "Move table", f"Move {title} to which table?",
                                    [t["name"] for t in free],
                                    columns=max(6, math.ceil(len(free) / 5)), width=7)
        if choice is None:
            return
        new_table = next(t for t in free if t["name"] == choice)
        try:
            orders.move_to_table(self.order_id, new_table["id"], self.app.current_user.id)
        except orders.OrderError as err:
            messagebox.showerror("Cannot move", str(err))
            return
        self.app.show_page("tables", flash=f"{title} moved to table {choice}.")


class AddonPicker(tk.Frame):
    """Covers the order screen while the cashier chooses add-ons for one item."""

    def __init__(self, page, name, base_price, groups, money, on_add, on_cancel,
                 chosen_ids=None, qty=1):
        super().__init__(page, bg="#59636B")          # dark backdrop
        self.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.groups = groups
        self.money = money
        self.base_price = base_price
        self.on_add = on_add
        self.qty = qty
        self.prices = {m["id"]: m["price_cents"] for _g, opts in groups for m in opts}
        if chosen_ids is None:
            # Required single-choice groups start with their first option picked
            # (e.g. Size: Regular), which saves a tap on most orders.
            chosen_ids = {opts[0]["id"] for g, opts in groups
                          if g["min_select"] >= 1 and g["max_select"] == 1}
        self.chosen = set(chosen_ids)

        card = tk.Frame(self, bg=theme.SURFACE, padx=24, pady=16)
        card.place(relx=0.5, rely=0.5, anchor="center")
        theme.label(card, f"{name}   {money(base_price)}", font=theme.F_HEADING
                    ).pack(anchor="w", pady=(0, 6))

        # The bottom part is packed first, so it always stays on screen
        # however many add-ons the item has.
        buttons = tk.Frame(card, bg=theme.SURFACE)
        buttons.pack(side="bottom", fill="x", pady=(6, 0))
        theme.button(buttons, "Cancel", on_cancel, color=theme.NEUTRAL).pack(side="left")
        self.add_button = theme.button(buttons, "", self.add, color=theme.SUCCESS)
        self.add_button.pack(side="right", fill="x", expand=True, padx=(10, 0))

        self.message = theme.label(card, "", color=theme.DANGER)
        self.message.pack(side="bottom", anchor="w", pady=(6, 0))

        qty_row = tk.Frame(card, bg=theme.SURFACE)
        qty_row.pack(side="bottom", anchor="w", pady=(10, 0))
        theme.label(qty_row, "Quantity", font=(theme.FONT, 13, "bold"),
                    color=theme.TEXT_MUTED).pack(side="left", padx=(0, 12))
        theme.small_button(qty_row, "−", lambda: self.change_qty(-1), width=3).pack(side="left")
        self.qty_label = theme.label(qty_row, "", font=theme.F_HEADING, width=3)
        self.qty_label.pack(side="left")
        theme.small_button(qty_row, "+", lambda: self.change_qty(1), width=3).pack(side="left")

        # One row per add-on group: name on the left, options on the right.
        # The rows sit on a Canvas so they can scroll if there are too many.
        area = tk.Frame(card, bg=theme.SURFACE)
        area.pack(side="top", fill="both", expand=True)
        canvas = tk.Canvas(area, bg=theme.SURFACE, highlightthickness=0)
        inner = tk.Frame(canvas, bg=theme.SURFACE)
        canvas.create_window(0, 0, window=inner, anchor="nw")
        scrollable = [canvas, inner]

        self.buttons = {}
        for r, (group, options) in enumerate(groups):
            rule = menu.group_rule_text(group["min_select"], group["max_select"])
            heading = tk.Label(inner, text=f"{group['name']}\n{rule}", justify="left",
                               anchor="nw", width=16, wraplength=170, bg=theme.SURFACE,
                               fg=theme.TEXT_MUTED, font=(theme.FONT, 12, "bold"))
            heading.grid(row=r, column=0, sticky="nw", padx=(0, 8), pady=6)
            row = tk.Frame(inner, bg=theme.SURFACE)
            row.grid(row=r, column=1, sticky="w", pady=2)
            scrollable += [heading, row]
            for k, m in enumerate(options):
                price = f"\n+{formats.money_plain(m['price_cents'])}" if m["price_cents"] else ""
                b = tk.Button(row, text=m["name"] + price, width=11, height=2,
                              font=(theme.FONT, 13, "bold"), relief="flat", bd=0,
                              cursor="hand2", fg=theme.TEXT,
                              command=lambda g=group, o=options, mod=m: self.tap(g, o, mod))
                b.grid(row=k // OPTIONS_PER_ROW, column=k % OPTIONS_PER_ROW, padx=3, pady=3)
                self.buttons[m["id"]] = b
                scrollable.append(b)
        canvas.pack(side="left", fill="both", expand=True)

        # Size the list to fit the screen; add a scrollbar only if it doesn't fit.
        self.update_idletasks()
        width, height = inner.winfo_reqwidth(), inner.winfo_reqheight()
        room = page.winfo_height() - (card.winfo_reqheight() - canvas.winfo_reqheight()) - 30
        shown = max(120, min(height, room))
        canvas.config(width=width, height=shown, scrollregion=(0, 0, width, height))
        if height > shown:
            bar = ttk.Scrollbar(area, orient="vertical", command=canvas.yview)
            canvas.config(yscrollcommand=bar.set)
            bar.pack(side="right", fill="y", before=canvas)
            for w in scrollable:
                w.bind("<MouseWheel>",
                       lambda e: canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.render()

    def tap(self, group, options, mod):
        ids = {m["id"] for m in options}
        if mod["id"] in self.chosen:
            self.chosen.discard(mod["id"])
        elif group["max_select"] == 1:
            self.chosen -= ids                 # pick only one: swap the choice
            self.chosen.add(mod["id"])
        elif len(self.chosen & ids) >= group["max_select"]:
            self.message.config(text=f"{group['name']}: choose at most {group['max_select']}.")
            return
        else:
            self.chosen.add(mod["id"])
        self.message.config(text="")
        self.render()

    def change_qty(self, step):
        self.qty = max(1, min(orders.MAX_QTY, self.qty + step))
        self.render()

    def render(self):
        for mod_id, b in self.buttons.items():
            on = mod_id in self.chosen
            b.config(bg=theme.SUCCESS if on else OPTION_BG, fg="white" if on else theme.TEXT,
                     activebackground=theme.SUCCESS if on else OPTION_BG)
        self.qty_label.config(text=str(self.qty))
        unit = self.base_price + sum(self.prices[i] for i in self.chosen)
        self.add_button.config(text=f"Add to order   {self.money(unit * self.qty)}")

    def add(self):
        try:
            mods = orders.validate_choices(self.groups, self.chosen)
        except orders.OrderError as err:
            self.message.config(text=str(err))
            return
        self.on_add(mods, self.qty)
