"""Shows receipt text on screen in a fixed-width font, like the printed slip."""
import tkinter as tk
from tkinter import ttk

from services import receipts
from ui import theme

PAPER = "#FFFDF7"


class ReceiptView(tk.Frame):
    def __init__(self, parent, height=20, width=receipts.WIDTH):
        """width = characters per line (48 for 80mm paper, 32 for 58mm)."""
        super().__init__(parent, bg=PAPER, highlightthickness=1, highlightbackground="#E2DED7")
        self.text = tk.Text(self, font=("Consolas", 10), width=width + 1,
                            height=height, bg=PAPER, fg=theme.TEXT, relief="flat",
                            padx=10, pady=10, wrap="none", cursor="arrow")
        bar = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.show([])

    def show(self, lines):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", "\n".join(lines))
        self.text.config(state="disabled")       # read-only
