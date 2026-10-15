"""Admin screen: categories (left), items in the chosen category (middle),
and the edit form (right)."""
import tkinter as tk
from tkinter import messagebox

from database import db
from services import formats, menu
from ui import theme
from ui.editor import EditorPanel, ListPanel
from ui.header import Header


class MenuPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=theme.BG)
        self.app = app
        self.currency = db.get_setting("currency")
        self.category_id = None      # category whose items are shown
        Header(self, app, "Menu", back_to="admin_home").pack(fill="x")

        body = tk.Frame(self, bg=theme.BG, padx=16, pady=16)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=2, uniform="col")
        body.columnconfigure(1, weight=3, uniform="col")
        body.columnconfigure(2, weight=3, uniform="col")
        body.rowconfigure(0, weight=1)

        self.categories = ListPanel(
            body, "Categories", [("name", "Name", 150), ("status", "", 70)],
            on_select=self.on_category_selected, on_new=self.new_category,
            on_move=self.move_category)
        self.categories.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        self.items = ListPanel(
            body, "Items", [("name", "Name", 170), ("price", "Price", 100), ("status", "", 70)],
            on_select=self.edit_item, on_new=self.new_item, on_move=self.move_item,
            new_text="+ New item")
        self.items.grid(row=0, column=1, sticky="nsew", padx=(0, 12))

        self.editor = EditorPanel(body)
        self.editor.grid(row=0, column=2, sticky="nsew")

        self.load_categories()
        if menu.is_menu_empty():
            self.editor.message(
                "Your menu is empty. Tap '+ New' under Categories to start, "
                "or load a sample cafe menu to try things out (you can edit it after).",
                "Load sample menu", self.load_sample)
        else:
            self.editor.message("Tap a category or item to edit it.")

    # ---------- loading lists ----------
    def load_categories(self, select=None):
        rows = [(c["id"], (c["name"], "" if c["is_active"] else "Hidden"), c["is_active"])
                for c in menu.list_categories()]
        self.categories.load(rows, select)

    def load_items(self, select=None):
        if self.category_id is None:
            self.items.load([])
            return
        rows = [(i["id"], (i["name"], formats.money(i["price_cents"], self.currency),
                           "" if i["is_active"] else "Hidden"), i["is_active"])
                for i in menu.list_items(self.category_id)]
        self.items.load(rows, select)

    def load_sample(self):
        menu.seed_sample_menu(self.app.current_user.id)
        self.load_categories()
        self.editor.message("Sample menu loaded. Tap a category or item to edit it. "
                            "Add-on options are on the Add-ons screen.")

    # ---------- categories ----------
    def on_category_selected(self, cat_id):
        if cat_id != self.category_id:
            self.category_id = cat_id
            self.items.title.config(text=f"Items in {self._category_name(cat_id)}")
            self.load_items()
        self.edit_category(cat_id)

    def _category_name(self, cat_id):
        return next((c["name"] for c in menu.list_categories() if c["id"] == cat_id), "")

    def new_category(self):
        self.categories.clear_selection()
        self._category_form(None)

    def edit_category(self, cat_id):
        cat = next((c for c in menu.list_categories() if c["id"] == cat_id), None)
        if cat is not None:
            self._category_form(cat)

    def _category_form(self, cat):
        self.editing_id = cat["id"] if cat else None
        self.editor.start("Edit category" if cat else "New category", self.save_category)
        self.editor.text("name", "Name", cat["name"] if cat else "")
        self.editor.swatches("color", "Tile colour", theme.CATEGORY_COLORS,
                             cat["color"] if cat else theme.CATEGORY_COLORS[0])
        self.editor.toggle("active", "Show on order screen", cat["is_active"] if cat else True)

    def save_category(self):
        v = self.editor.values()
        try:
            cat_id = menu.save_category(self.editing_id, v["name"], v["color"], v["active"],
                                        self.app.current_user.id)
        except menu.MenuError as err:
            messagebox.showerror("Cannot save", str(err))
            return
        self.load_categories(select=cat_id)
        self.items.title.config(text=f"Items in {v['name'].strip()}")

    def move_category(self, cat_id, direction):
        menu.move_category(cat_id, direction)
        self.load_categories(select=cat_id)

    # ---------- items ----------
    def new_item(self):
        if self.category_id is None:
            messagebox.showinfo("Choose a category", "Tap a category first.")
            return
        self.items.clear_selection()
        self._item_form(None, set())

    def edit_item(self, item_id):
        item, groups = menu.get_item(item_id)
        if item is not None:
            self._item_form(item, groups)

    def _item_form(self, item, group_ids):
        self.editing_id = item["id"] if item else None
        self.editor.start("Edit item" if item else "New item", self.save_item)
        self.editor.text("name", "Name", item["name"] if item else "")
        self.editor.text("price", f"Price ({self.currency})",
                         formats.money_plain(item["price_cents"]) if item else "", numeric=True)
        self.editor.choice("category", "Category",
                           [(c["id"], c["name"]) for c in menu.list_categories()],
                           item["category_id"] if item else self.category_id)
        self.editor.toggle("kitchen", "Print on kitchen ticket",
                           item["send_to_kitchen"] if item else True)
        self.editor.toggle("active", "Show on order screen", item["is_active"] if item else True)
        # Include hidden groups only if this item already uses them.
        groups = [(g["id"], g["name"]) for g in menu.list_groups()
                  if g["is_active"] or g["id"] in group_ids]
        self.editor.multi_toggle("groups", "Add-ons for this item", groups, group_ids)

    def save_item(self):
        v = self.editor.values()
        try:
            price = formats.parse_money(v["price"])
            item_id = menu.save_item(self.editing_id, v["category"], v["name"], price,
                                     v["kitchen"], v["active"], v["groups"],
                                     self.app.current_user.id)
        except (ValueError, menu.MenuError) as err:
            messagebox.showerror("Cannot save", str(err))
            return
        if v["category"] != self.category_id:      # moved to another category: follow it
            self.category_id = v["category"]
            self.items.title.config(text=f"Items in {self._category_name(self.category_id)}")
            self.load_categories(select=self.category_id)
        self.load_items(select=item_id)

    def move_item(self, item_id, direction):
        menu.move_item(item_id, direction)
        self.load_items(select=item_id)
