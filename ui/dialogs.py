"""Pop-up windows that work with the on-screen keyboard.

Tkinter's built-in simpledialog can't show our keyboard, so we use this instead.
"""
import tkinter as tk

from ui import theme


def ask_choice(parent, title, prompt, options, columns=2, width=14):
    """Show one big button per option. Returns the chosen option, or None if cancelled."""
    root = parent.winfo_toplevel()
    win = tk.Toplevel(root)
    win.title(title)
    win.configure(bg=theme.SURFACE)
    win.transient(root)
    win.resizable(False, False)
    result = {"value": None}

    box = tk.Frame(win, bg=theme.SURFACE, padx=30, pady=24)
    box.pack(fill="both", expand=True)
    theme.label(box, prompt, font=theme.F_HEADING).pack(anchor="w", pady=(0, 12))

    def pick(option):
        result["value"] = option
        win.destroy()

    grid = tk.Frame(box, bg=theme.SURFACE)
    grid.pack()
    for i, option in enumerate(options):
        btn = theme.button(grid, option, lambda o=option: pick(o), width=width)
        btn.configure(pady=22)
        btn.grid(row=i // columns, column=i % columns, padx=6, pady=6)
    theme.button(box, "Cancel", win.destroy, color=theme.NEUTRAL).pack(fill="x", pady=(12, 0))

    win.bind("<Escape>", lambda _e: win.destroy())
    win.update_idletasks()
    x = root.winfo_rootx() + max(0, (root.winfo_width() - win.winfo_reqwidth()) // 2)
    win.geometry(f"+{x}+{root.winfo_rooty() + 80}")
    win.grab_set()
    win.wait_window()
    return result["value"]


def ask_text(parent, title, prompt, show=None, numeric=False, initial=""):
    """Ask the user to type something. Returns the text, or None if cancelled."""
    root = parent.winfo_toplevel()
    win = tk.Toplevel(root)
    win.title(title)
    win.configure(bg=theme.SURFACE)
    win.transient(root)
    win.resizable(False, False)
    result = {"value": None}

    box = tk.Frame(win, bg=theme.SURFACE, padx=30, pady=24)
    box.pack(fill="both", expand=True)
    theme.label(box, prompt, font=theme.F_HEADING).pack(anchor="w")
    field = theme.entry(box, show=show, width=32, numeric=numeric)
    field.insert(0, initial)
    field.pack(fill="x", ipady=8, pady=12)

    def ok():
        result["value"] = field.get()
        win.destroy()

    buttons = tk.Frame(box, bg=theme.SURFACE)
    buttons.pack(fill="x")
    theme.button(buttons, "OK", ok, color=theme.SUCCESS, width=10).pack(side="right")
    theme.button(buttons, "Cancel", win.destroy, color=theme.NEUTRAL, width=10
                 ).pack(side="right", padx=10)

    win.bind("<Return>", lambda _e: ok())
    win.bind("<Escape>", lambda _e: win.destroy())

    # Place near the top of the main window, leaving room for the keyboard below.
    win.update_idletasks()
    x = root.winfo_rootx() + max(0, (root.winfo_width() - 980) // 2)
    win.geometry(f"+{x}+{root.winfo_rooty() + 60}")

    win.grab_set()        # block the rest of the app until this closes
    field.focus_set()
    win.wait_window()
    return result["value"]
