"""Reusable pieces for "list on the left, edit form on the right" screens.

ListPanel   - a titled table with  + New / ▲ / ▼  buttons.
EditorPanel - a form with a Save button at the TOP (so it stays visible when
              the on-screen keyboard covers the bottom of the screen).

The Menu and Add-ons screens are both built from these.
"""
import tkinter as tk
from tkinter import ttk

from ui import theme


class ListPanel(tk.Frame):
    def __init__(self, parent, title, columns, on_select, on_new, on_move, new_text="+ New"):
        super().__init__(parent, bg=theme.SURFACE, padx=16, pady=14,
                         highlightthickness=1, highlightbackground="#E2DED7")
        self.on_select = on_select

        top = tk.Frame(self, bg=theme.SURFACE)
        top.pack(fill="x", pady=(0, 8))
        self.title = theme.label(top, title, font=theme.F_HEADING)
        self.title.pack(side="left")

        # Buttons are packed before the list so they always stay visible.
        buttons = tk.Frame(self, bg=theme.SURFACE)
        buttons.pack(side="bottom", fill="x", pady=(10, 0))

        box = tk.Frame(self, bg=theme.SURFACE)
        box.pack(fill="both", expand=True)
        self.table = theme.tree(box, columns)
        bar = ttk.Scrollbar(box, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")      # wide enough to drag with a finger
        self.table.pack(side="left", fill="both", expand=True)
        self.table.bind("<<TreeviewSelect>>", self._selected)

        theme.small_button(buttons, new_text, on_new, color=theme.SUCCESS).pack(side="left")
        theme.small_button(buttons, "▼", lambda: self._move(on_move, 1), width=3
                           ).pack(side="right")
        theme.small_button(buttons, "▲", lambda: self._move(on_move, -1), width=3
                           ).pack(side="right", padx=8)

    def load(self, rows, select=None):
        """rows = [(id, (column values...), is_active), ...]"""
        if select is None:
            select = self.selected_id()
        self.table.delete(*self.table.get_children())
        for row_id, values, active in rows:
            self.table.insert("", "end", iid=str(row_id), values=values,
                              tags=() if active else ("inactive",))
        if select is not None and self.table.exists(str(select)):
            self.table.selection_set(str(select))
            self.table.see(str(select))

    def selected_id(self):
        sel = self.table.selection()
        return int(sel[0]) if sel else None

    def clear_selection(self):
        self.table.selection_remove(self.table.selection())

    def _selected(self, _event):
        row_id = self.selected_id()
        if row_id is not None:
            self.on_select(row_id)

    def _move(self, on_move, direction):
        row_id = self.selected_id()
        if row_id is not None:
            on_move(row_id, direction)


class EditorPanel(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=theme.SURFACE, padx=20, pady=14,
                         highlightthickness=1, highlightbackground="#E2DED7")
        self.fields = {}

    def _clear(self):
        for child in self.winfo_children():
            child.destroy()
        self.fields = {}

    def message(self, text, button_text=None, command=None):
        """Show a hint instead of a form (e.g. 'Tap an item to edit it')."""
        self._clear()
        theme.label(self, text, color=theme.TEXT_MUTED, wraplength=360, justify="left"
                    ).pack(anchor="w", pady=(10, 16))
        if button_text:
            theme.button(self, button_text, command, color=theme.SUCCESS).pack(anchor="w")

    def start(self, title, on_save):
        """Clear the panel and start a new form. Returns nothing; add fields after."""
        self._clear()
        top = tk.Frame(self, bg=theme.SURFACE)
        top.pack(fill="x", pady=(0, 12))
        theme.label(top, title, font=theme.F_HEADING).pack(side="left")
        theme.small_button(top, "Save", on_save, color=theme.SUCCESS, width=8).pack(side="right")

    def text(self, key, label, value="", numeric=False):
        theme.label(self, label, anchor="w").pack(fill="x")
        e = theme.entry(self, numeric=numeric, width=28)
        e.insert(0, value)
        e.pack(fill="x", ipady=6, pady=(2, 10))
        self.fields[key] = e.get
        return e

    def toggle(self, key, label, value, parent=None):
        var = tk.BooleanVar(value=bool(value))
        theme.toggle(parent or self, label, var).pack(anchor="w", pady=(0, 8))
        self.fields[key] = var.get

    def choice(self, key, label, options, value):
        """A drop-down. options = [(value, text), ...]."""
        theme.label(self, label, anchor="w").pack(fill="x")
        texts = [t for _v, t in options]
        box = ttk.Combobox(self, values=texts, state="readonly", font=theme.F_BODY)
        for v, t in options:
            if v == value:
                box.set(t)
        box.pack(fill="x", pady=(2, 10))
        lookup = dict((t, v) for v, t in options)
        self.fields[key] = lambda: lookup.get(box.get())

    def swatches(self, key, label, colors, value):
        """A row of colour buttons; the chosen one shows a tick."""
        theme.label(self, label, anchor="w").pack(fill="x")
        row = tk.Frame(self, bg=theme.SURFACE)
        row.pack(anchor="w", pady=(2, 10))
        var = tk.StringVar(value=value if value in colors else colors[0])
        buttons = []

        def refresh(*_):
            for b, c in buttons:
                b.config(text="✓" if var.get() == c else "")

        for c in colors:
            b = tk.Radiobutton(row, variable=var, value=c, indicatoron=False, bg=c,
                               selectcolor=c, activebackground=c, fg="white",
                               font=theme.F_HEADING, width=2, bd=0, cursor="hand2",
                               command=refresh)
            b.pack(side="left", padx=3)
            buttons.append((b, c))
        refresh()
        self.fields[key] = var.get

    def multi_toggle(self, key, label, options, selected):
        """A grid of on/off buttons. options = [(id, text), ...]. Returns a set of ids."""
        theme.label(self, label, anchor="w").pack(fill="x")
        grid = tk.Frame(self, bg=theme.SURFACE)
        grid.pack(anchor="w", pady=(2, 10))
        variables = {}
        for i, (opt_id, text) in enumerate(options):
            var = tk.BooleanVar(value=opt_id in selected)
            theme.toggle(grid, text, var).grid(row=i // 2, column=i % 2, sticky="ew",
                                               padx=(0, 6), pady=3)
            variables[opt_id] = var
        if not options:
            theme.label(grid, "(none yet)", color=theme.TEXT_MUTED).grid(row=0, column=0)
        self.fields[key] = lambda: {i for i, v in variables.items() if v.get()}

    def values(self):
        return {key: getter() for key, getter in self.fields.items()}
