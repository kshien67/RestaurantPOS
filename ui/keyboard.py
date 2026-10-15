"""On-screen keyboard for the touchscreen counter (it has no physical keyboard).

How it works:
  * install(root) listens for "a text box got focus" anywhere in the app.
  * When any tk.Entry is tapped, a keyboard slides in at the bottom of that
    window, and the rest of the screen shrinks to make room.
  * Text boxes created with theme.entry(..., numeric=True) get a number pad.
  * Tapping a key types into the text box that was tapped last.

Keys use takefocus=0 and Tk buttons never take focus on click, so tapping a
key does not take focus away from the text box.
"""
import tkinter as tk

from ui import theme

KB_BG = "#222B31"
KEY_BG = "#3A4750"
SPECIAL_BG = "#5A6872"
KEY_FONT = (theme.FONT, 16, "bold")

LETTER_ROWS = ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm"]

_keyboards = {}   # window path -> OnScreenKeyboard (one per window)


class OnScreenKeyboard(tk.Frame):
    def __init__(self, window):
        super().__init__(window, bg=KB_BG, pady=6)
        self.window = window
        self.target = None
        self.shift = False
        self.letter_keys = []

        # Shows what's in the text box, because the keyboard may cover the box itself.
        self.echo = tk.Label(self, bg="#FFFFFF", fg=theme.TEXT, font=(theme.FONT, 16),
                             anchor="w", padx=12, pady=4, width=60)
        self.echo.pack(pady=(0, 4))

        self.full = tk.Frame(self, bg=KB_BG)
        self.numpad = tk.Frame(self, bg=KB_BG)
        self._build_full()
        self._build_numpad()

    # ---------- building the keys ----------
    def _key(self, parent, text, command, width=4, color=KEY_BG):
        return tk.Button(parent, text=text, command=command, width=width, font=KEY_FONT,
                         bg=color, fg="white", activebackground=theme.PRIMARY,
                         activeforeground="white", relief="flat", bd=0, pady=8,
                         takefocus=0)

    def _row(self, parent):
        row = tk.Frame(parent, bg=KB_BG)
        row.pack(pady=3)
        return row

    def _char(self, parent, ch):
        btn = self._key(parent, ch, lambda: self._type(ch))
        btn.pack(side="left", padx=3)
        if ch.isalpha():
            self.letter_keys.append((btn, ch))

    def _build_full(self):
        row = self._row(self.full)
        for ch in LETTER_ROWS[0]:
            self._char(row, ch)
        self._key(row, "⌫", self.backspace, width=6, color=SPECIAL_BG).pack(side="left", padx=3)

        row = self._row(self.full)
        for ch in LETTER_ROWS[1]:
            self._char(row, ch)

        row = self._row(self.full)
        for ch in LETTER_ROWS[2]:
            self._char(row, ch)
        self._key(row, "Enter", self.enter, width=7, color=theme.PRIMARY).pack(side="left", padx=3)

        row = self._row(self.full)
        self.shift_btn = self._key(row, "⇧ Shift", self.toggle_shift, width=7, color=SPECIAL_BG)
        self.shift_btn.pack(side="left", padx=3)
        for ch in LETTER_ROWS[3] + ",.-":
            self._char(row, ch)

        row = self._row(self.full)
        for ch in "@&'/":
            self._char(row, ch)
        self._key(row, "space", lambda: self._insert(" "), width=24).pack(side="left", padx=3)
        for ch in "()":
            self._char(row, ch)
        self._key(row, "Hide ▼", self.hide, width=7, color=SPECIAL_BG).pack(side="left", padx=3)

    def _build_numpad(self):
        grid = tk.Frame(self.numpad, bg=KB_BG)
        grid.pack()
        for i, ch in enumerate("789456123.0"):
            self._key(grid, ch, lambda c=ch: self._insert(c), width=6
                      ).grid(row=i // 3, column=i % 3, padx=3, pady=3)
        self._key(grid, "⌫", self.backspace, width=6, color=SPECIAL_BG
                  ).grid(row=3, column=2, padx=3, pady=3)
        self._key(grid, "Clear", self.clear, width=7, color=SPECIAL_BG
                  ).grid(row=0, column=3, padx=3, pady=3)
        self._key(grid, "Enter", self.enter, width=7, color=theme.PRIMARY
                  ).grid(row=1, column=3, padx=3, pady=3)
        self._key(grid, "Hide ▼", self.hide, width=7, color=SPECIAL_BG
                  ).grid(row=2, column=3, rowspan=2, padx=3, pady=3, sticky="ns")

    # ---------- showing / hiding ----------
    def show(self, entry):
        self.target = entry
        if not getattr(entry, "_kb_watched", False):
            # If this text box disappears (e.g. the form is rebuilt after Save),
            # hide the keyboard instead of leaving keys that type into nothing.
            entry.bind("<Destroy>", lambda _e, ent=entry: self._target_gone(ent), add="+")
            entry._kb_watched = True
        self._refresh_echo()
        if getattr(entry, "numeric", False):
            self.full.pack_forget()
            self.numpad.pack()
        else:
            self.numpad.pack_forget()
            self.full.pack()
        if not self.winfo_manager():          # not on screen yet
            others = [w for w in self.window.pack_slaves() if w is not self]
            # Pack it first so it always gets its full height; the page shrinks instead.
            if others:
                self.pack(side="bottom", fill="x", before=others[0])
            else:
                self.pack(side="bottom", fill="x")

    def hide(self, refocus=True):
        if not self.winfo_exists():
            return
        self.pack_forget()
        self.target = None
        if refocus and self.window.winfo_exists():
            # Move focus off the text box, so tapping it again shows the keyboard again.
            self.window.focus_set()

    def _target_gone(self, entry):
        if self.target is entry:
            self.hide(refocus=False)

    def _refresh_echo(self):
        t = self.target
        if t is None or not t.winfo_exists():
            return
        text = t.get()
        if t.cget("show"):                 # password box: don't reveal it
            text = t.cget("show") * len(text)
        self.echo.config(text=text + "▏")

    # ---------- typing ----------
    def _ready(self):
        t = self.target
        return t is not None and t.winfo_exists() and str(t.cget("state")) == "normal"

    def _insert(self, text):
        if not self._ready():
            return
        t = self.target
        if t.selection_present():
            t.delete("sel.first", "sel.last")
        t.insert("insert", text)
        t.xview("insert")
        self._refresh_echo()

    def _type(self, ch):
        if ch.isalpha() and self.shift:
            self._insert(ch.upper())
            self.set_shift(False)     # shift works for one letter, like a phone
        else:
            self._insert(ch)

    def backspace(self):
        if not self._ready():
            return
        t = self.target
        if t.selection_present():
            t.delete("sel.first", "sel.last")
        else:
            pos = t.index("insert")
            if pos > 0:
                t.delete(pos - 1)
        self._refresh_echo()

    def clear(self):
        if self._ready():
            self.target.delete(0, "end")
            self._refresh_echo()

    def enter(self):
        if self._ready():
            self.target.event_generate("<Return>")

    def toggle_shift(self):
        self.set_shift(not self.shift)

    def set_shift(self, on):
        self.shift = on
        for btn, ch in self.letter_keys:
            btn.config(text=ch.upper() if on else ch)
        self.shift_btn.config(bg=theme.PRIMARY if on else SPECIAL_BG)


def keyboard_for(window):
    kb = _keyboards.get(str(window))
    if kb is None or not kb.winfo_exists():
        kb = OnScreenKeyboard(window)
        _keyboards[str(window)] = kb
    return kb


def _on_focus_in(event):
    w = event.widget
    if isinstance(w, str) or isinstance(w, (tk.Tk, tk.Toplevel)):
        return
    if isinstance(w, tk.Entry) and str(w.cget("state")) == "normal":
        keyboard_for(w.winfo_toplevel()).show(w)
    else:
        # Focus moved to something that isn't a text box (e.g. a list): hide it.
        kb = _keyboards.get(str(w.winfo_toplevel()))
        if kb is not None and kb.winfo_exists():
            kb.hide(refocus=False)


def install(root):
    root.bind_all("<FocusIn>", _on_focus_in, add="+")


def hide_all():
    for kb in list(_keyboards.values()):
        if kb.winfo_exists():
            kb.hide(refocus=False)
