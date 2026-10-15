"""Admin screen: set up the dining tables (list on the left, form on the right).
The order here (▲▼) is the order of tiles on the cashier's table map."""
import tkinter as tk
from tkinter import messagebox

from services import formats, tables
from ui import dialogs, theme
from ui.editor import EditorPanel, ListPanel
from ui.header import Header


class TablesAdminPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=theme.BG)
        self.app = app
        self.editing_id = None
        Header(self, app, "Tables", back_to="admin_home").pack(fill="x")

        body = tk.Frame(self, bg=theme.BG, padx=16, pady=16)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1, uniform="col")
        body.columnconfigure(1, weight=1, uniform="col")
        body.rowconfigure(0, weight=1)

        self.list = ListPanel(body, "Tables", [("name", "Table", 160), ("seats", "Seats", 90),
                                               ("status", "", 90)],
                              on_select=self.edit_table, on_new=self.new_table,
                              on_move=self.move_table)
        self.list.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        self.editor = EditorPanel(body)
        self.editor.grid(row=0, column=1, sticky="nsew")
        self.show_help()
        self.load()

    def show_help(self):
        self.editor.message(
            "Tap a table to edit it, or '+ New' to add one.\n\n"
            "Setting up for the first time? Add several tables at once, named "
            "T1, T2, T3... You can rename them afterwards (e.g. 'Patio 1').",
            "+ Add several tables", self.add_several)

    def load(self, select=None):
        rows = [(t["id"], (t["name"], t["seats"], "" if t["is_active"] else "Hidden"),
                 t["is_active"]) for t in tables.list_tables()]
        self.list.load(rows, select)

    def new_table(self):
        self.list.clear_selection()
        self._form(None)

    def edit_table(self, table_id):
        table = next((t for t in tables.list_tables() if t["id"] == table_id), None)
        if table is not None:
            self._form(table)

    def _form(self, table):
        self.editing_id = table["id"] if table else None
        self.editor.start("Edit table" if table else "New table", self.save)
        self.editor.text("name", f"Name (max {tables.MAX_NAME} characters)",
                         table["name"] if table else "")
        self.editor.text("seats", "Seats", str(table["seats"]) if table else "4", numeric=True)
        self.editor.toggle("active", "Show on table map", table["is_active"] if table else True)

    def save(self):
        v = self.editor.values()
        try:
            seats = formats.parse_count(v["seats"], "Seats", 1, tables.MAX_SEATS)
            table_id = tables.save_table(self.editing_id, v["name"], seats, v["active"],
                                         self.app.current_user.id)
        except (ValueError, tables.TableError) as err:
            messagebox.showerror("Cannot save", str(err))
            return
        self.load(select=table_id)

    def move_table(self, table_id, direction):
        tables.move_table(table_id, direction)
        self.load(select=table_id)

    def add_several(self):
        count = dialogs.ask_text(self, "Add tables", "How many tables to add?", numeric=True)
        if count is None:
            return
        seats = dialogs.ask_text(self, "Add tables", "Seats per table?", numeric=True,
                                 initial="4")
        if seats is None:
            return
        try:
            names = tables.add_tables(formats.parse_count(count, "Number of tables", 1, 50),
                                      formats.parse_count(seats, "Seats", 1, tables.MAX_SEATS),
                                      self.app.current_user.id)
        except (ValueError, tables.TableError) as err:
            messagebox.showerror("Cannot add tables", str(err))
            return
        self.load()
        messagebox.showinfo("Tables added", f"Added {names[0]} to {names[-1]}.")
