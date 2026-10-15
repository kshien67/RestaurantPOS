"""A big number pad for typing a PIN, with dots instead of numbers.

When the last digit is typed it calls on_complete(pin) straight away.
on_complete returns None if the PIN was accepted, or an error message to show.
It doesn't use a text box, so the on-screen keyboard doesn't pop up.
"""
import tkinter as tk

from ui import theme

KEY_BG = "#EEE9E1"


class PinPad(tk.Frame):
    def __init__(self, parent, title, on_complete, on_cancel=None, length=4,
                 cancel_text="Back"):
        super().__init__(parent, bg=theme.SURFACE, padx=28, pady=20,
                         highlightthickness=1, highlightbackground="#E2DED7")
        self.on_complete = on_complete
        self.length = length
        self.pin = ""

        theme.label(self, title, font=theme.F_HEADING).pack()
        self.dots = theme.label(self, "", font=(theme.FONT, 30))
        self.dots.pack(pady=(6, 0))
        self.message = theme.label(self, "", color=theme.DANGER, font=theme.F_BODY)
        self.message.pack(pady=(0, 8))

        grid = tk.Frame(self, bg=theme.SURFACE)
        grid.pack()
        keys = list("123456789") + ["Clear", "0", "⌫"]
        for i, key in enumerate(keys):
            if key == "Clear":
                command = self.clear
            elif key == "⌫":
                command = self.backspace
            else:
                command = lambda d=key: self.press(d)
            tk.Button(grid, text=key, command=command, width=5,
                      font=(theme.FONT, 22 if key.isdigit() else 16, "bold"),
                      bg=KEY_BG, fg=theme.TEXT, activebackground=theme.TOGGLE_ON,
                      relief="flat", bd=0, pady=10, cursor="hand2", takefocus=0
                      ).grid(row=i // 3, column=i % 3, padx=5, pady=5)

        if on_cancel:
            theme.button(self, cancel_text, on_cancel, color=theme.NEUTRAL
                         ).pack(fill="x", pady=(14, 0))
        self._render()

    def _render(self):
        self.dots.config(text="  ".join("●" if i < len(self.pin) else "○"
                                        for i in range(self.length)))

    def press(self, digit):
        if len(self.pin) >= self.length:
            return
        self.pin += digit
        self.message.config(text="")
        self._render()
        if len(self.pin) == self.length:
            self.update_idletasks()      # show the last dot before checking
            pin, self.pin = self.pin, ""
            error = self.on_complete(pin)
            if not self.winfo_exists():  # accepted: the screen has changed
                return
            if error:
                self.message.config(text=error)
            self._render()

    def backspace(self):
        self.pin = self.pin[:-1]
        self._render()

    def clear(self):
        self.pin = ""
        self._render()

    def type_key(self, event):
        """Lets a physical keyboard work too (handy when testing on a laptop)."""
        if event.char.isdigit():
            self.press(event.char)
        elif event.keysym == "BackSpace":
            self.backspace()
