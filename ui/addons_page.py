"""Admin screen for add-ons: groups like "Size" or "Extras" (left), the options
in the chosen group (middle), and the edit form (right).

Which menu items use which group is chosen on the Menu screen, in each item's form.
"""
import tkinter as tk
from tkinter import messagebox

from database import db
from services import formats, menu
from ui import theme
from ui.editor import EditorPanel, ListPanel
from ui.header import Header


class AddonsPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=theme.BG)
        self.app = app
        self.currency = db.get_setting("currency")
        self.group_id = None
        Header(self, app, "Add-ons", back_to="admin_home").pack(fill="x")

        body = tk.Frame(self, bg=theme.BG, padx=16, pady=16)
        body.pack(fill="both", expand=True)
        for col, weight in enumerate((3, 3, 3)):
            body.columnconfigure(col, weight=weight, uniform="col")
        body.rowconfigure(0, weight=1)

        self.groups = ListPanel(
            body, "Add-on groups", [("name", "Group", 130), ("rule", "Rule", 150)],
            on_select=self.on_group_selected, on_new=self.new_group, on_move=self.move_group)
        self.groups.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        self.options = ListPanel(
            body, "Options", [("name", "Option", 150), ("price", "Extra", 90), ("status", "", 60)],
            on_select=self.edit_option, on_new=self.new_option, on_move=self.move_option,
            new_text="+ New option")
        self.options.grid(row=0, column=1, sticky="nsew", padx=(0, 12))

        self.editor = EditorPanel(body)
        self.editor.grid(row=0, column=2, sticky="nsew")
        self.editor.message(
            "A group is a question the cashier asks, e.g. 'Size' with options "
            "Regular / Large (+RM 1.50).\n\nTap '+ New' to add a group, then add its options.")

        self.load_groups()

    # ---------- loading ----------
    def load_groups(self, select=None):
        rows = []
        for g in menu.list_groups():
            rule = menu.group_rule_text(g["min_select"], g["max_select"])
            if not g["is_active"]:
                rule = "Hidden"
            rows.append((g["id"], (g["name"], rule), g["is_active"]))
        self.groups.load(rows, select)

    def load_options(self, select=None):
        if self.group_id is None:
            self.options.load([])
            return
        rows = [(m["id"], (m["name"], "+" + formats.money(m["price_cents"], self.currency)
                           if m["price_cents"] else "free",
                           "" if m["is_active"] else "Hidden"), m["is_active"])
                for m in menu.list_modifiers(self.group_id)]
        self.options.load(rows, select)

    def _group(self, group_id):
        return next((g for g in menu.list_groups() if g["id"] == group_id), None)

    # ---------- groups ----------
    def on_group_selected(self, group_id):
        if group_id != self.group_id:
            self.group_id = group_id
            group = self._group(group_id)
            self.options.title.config(text=f"Options in {group['name']}" if group else "Options")
            self.load_options()
        self._group_form(self._group(group_id))

    def new_group(self):
        self.groups.clear_selection()
        self._group_form(None)

    def _group_form(self, group):
        self.editing_id = group["id"] if group else None
        self.editor.start("Edit group" if group else "New add-on group", self.save_group)
        self.editor.text("name", "Name (e.g. Size, Extras)", group["name"] if group else "")
        self.editor.toggle("required", "Customer MUST choose",
                           group["min_select"] >= 1 if group else False)
        self.editor.text("max", "Max choices (1 = pick only one)",
                         str(group["max_select"]) if group else "1", numeric=True)
        self.editor.toggle("active", "Show on order screen", group["is_active"] if group else True)

    def save_group(self):
        v = self.editor.values()
        try:
            max_select = formats.parse_count(v["max"], "Max choices", 1, 20)
            group_id = menu.save_group(self.editing_id, v["name"], v["required"], max_select,
                                       v["active"], self.app.current_user.id)
        except (ValueError, menu.MenuError) as err:
            messagebox.showerror("Cannot save", str(err))
            return
        self.load_groups(select=group_id)

    def move_group(self, group_id, direction):
        menu.move_group(group_id, direction)
        self.load_groups(select=group_id)

    # ---------- options ----------
    def new_option(self):
        if self.group_id is None:
            messagebox.showinfo("Choose a group", "Tap an add-on group first.")
            return
        self.options.clear_selection()
        self._option_form(None)

    def edit_option(self, mod_id):
        mod = next((m for m in menu.list_modifiers(self.group_id) if m["id"] == mod_id), None)
        if mod is not None:
            self._option_form(mod)

    def _option_form(self, mod):
        self.editing_id = mod["id"] if mod else None
        self.editor.start("Edit option" if mod else "New option", self.save_option)
        self.editor.text("name", "Name (e.g. Large, Extra shot)", mod["name"] if mod else "")
        self.editor.text("price", f"Extra price ({self.currency}, 0 = free)",
                         formats.money_plain(mod["price_cents"]) if mod else "0.00", numeric=True)
        self.editor.toggle("active", "Show on order screen", mod["is_active"] if mod else True)

    def save_option(self):
        v = self.editor.values()
        try:
            price = formats.parse_money(v["price"], "Extra price")
            mod_id = menu.save_modifier(self.editing_id, self.group_id, v["name"], price,
                                        v["active"], self.app.current_user.id)
        except (ValueError, menu.MenuError) as err:
            messagebox.showerror("Cannot save", str(err))
            return
        self.load_options(select=mod_id)

    def move_option(self, mod_id, direction):
        menu.move_modifier(mod_id, direction)
        self.load_options(select=mod_id)
