"""One place for colours, fonts and touch-friendly widgets.

Change a colour or font here and every screen updates. Buttons are made big
on purpose so they are easy to tap on a touchscreen.
"""
import tkinter as tk
from tkinter import ttk

# ---------- Colours ----------
BG = "#F4F1EC"          # page background
SURFACE = "#FFFFFF"     # cards / panels
HEADER = "#2F3E46"      # top bar
TEXT = "#1F2328"
TEXT_MUTED = "#6B7280"
TEXT_ON_DARK = "#FFFFFF"
PRIMARY = "#D9822B"     # main action (orange)
PRIMARY_DARK = "#B86A1E"
SUCCESS = "#2E8B57"
DANGER = "#C0392B"
NEUTRAL = "#8A939B"
DISABLED = "#C9CDD1"
TOGGLE_ON = "#BFE3CC"   # background of a toggle that is switched on

# Colours the admin can pick for menu categories (shown as tiles on the order screen).
CATEGORY_COLORS = ["#D9822B", "#8B5E3C", "#2E8B57", "#3A7CA5",
                   "#7B4B94", "#C0392B", "#D4A017", "#5A6872"]

# ---------- Fonts ----------
FONT = "Segoe UI"
F_TITLE = (FONT, 26, "bold")
F_HEADING = (FONT, 18, "bold")
F_BODY = (FONT, 14)
F_BUTTON = (FONT, 15, "bold")
F_SMALL = (FONT, 11)

BUTTON_PADY = 14
BUTTON_PADX = 18


def apply_ttk_styles(root):
    """Style ttk widgets (tables, combo boxes) to match the theme."""
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("Treeview", font=F_BODY, rowheight=44, background=SURFACE,
                    fieldbackground=SURFACE, foreground=TEXT)
    style.configure("Treeview.Heading", font=(FONT, 13, "bold"))
    style.map("Treeview", background=[("selected", PRIMARY)],
              foreground=[("selected", TEXT_ON_DARK)])
    style.configure("TCombobox", padding=8, arrowsize=24)
    root.option_add("*TCombobox*Listbox.font", F_BODY)
    # The cart on the order screen: shorter rows so more lines fit.
    style.configure("Cart.Treeview", font=F_BODY, rowheight=34, background=SURFACE,
                    fieldbackground=SURFACE, foreground=TEXT, borderwidth=0)
    style.configure("Vertical.TScrollbar", arrowsize=26)   # wide enough to drag with a finger


def tint(color, amount=0.6):
    """Mix a colour with white. amount=0 -> same colour, 1 -> white."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    r, g, b = (round(c + (255 - c) * amount) for c in (r, g, b))
    return f"#{r:02X}{g:02X}{b:02X}"


def button(parent, text, command, color=PRIMARY, width=None, font=F_BUTTON, **kw):
    """A big, flat, touch-friendly button."""
    btn = tk.Button(
        parent, text=text, command=command, font=font, width=width,
        bg=color, fg=TEXT_ON_DARK, activebackground=PRIMARY_DARK,
        activeforeground=TEXT_ON_DARK, disabledforeground=TEXT_ON_DARK,
        relief="flat", bd=0, cursor="hand2",
        padx=BUTTON_PADX, pady=BUTTON_PADY, **kw,
    )
    if kw.get("state") == "disabled":
        btn.configure(bg=DISABLED, cursor="arrow")
    return btn


def small_button(parent, text, command, color=NEUTRAL, width=None):
    """A smaller button for toolbars (still big enough to tap)."""
    btn = button(parent, text, command, color=color, width=width, font=(FONT, 13, "bold"))
    btn.configure(pady=10, padx=12)
    return btn


def label(parent, text="", font=F_BODY, color=TEXT, bg=SURFACE, **kw):
    return tk.Label(parent, text=text, font=font, fg=color, bg=bg, **kw)


def entry(parent, show=None, width=24, numeric=False, **kw):
    """A text box. numeric=True makes the on-screen keyboard show a number pad."""
    e = tk.Entry(parent, font=F_BODY, width=width, show=show, relief="solid", bd=1, **kw)
    e.numeric = numeric
    return e


def toggle(parent, text, variable):
    """An on/off button. Green background = on. `variable` is a tk.BooleanVar."""
    return tk.Checkbutton(
        parent, text=text, variable=variable, indicatoron=False,
        font=F_BODY, bg=SURFACE, selectcolor=TOGGLE_ON, activebackground=TOGGLE_ON,
        relief="raised", offrelief="raised", bd=2, padx=14, pady=8, cursor="hand2",
    )


def card(parent, padx=32, pady=28, **kw):
    """A white panel with padding, used to group things on a page."""
    return tk.Frame(parent, bg=SURFACE, padx=padx, pady=pady,
                    highlightthickness=1, highlightbackground="#E2DED7", **kw)


def tree(parent, columns, height=8):
    """A table. columns = [(key, heading, width), ...]."""
    t = ttk.Treeview(parent, columns=[c[0] for c in columns], show="headings",
                     selectmode="browse", height=height)
    for key, heading, width in columns:
        t.heading(key, text=heading)
        t.column(key, width=width, anchor="w")
    t.tag_configure("inactive", foreground=TEXT_MUTED)
    return t
