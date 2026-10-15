"""Top bar shown on every screen after login: shop name, clock, user, logout."""
import tkinter as tk
from datetime import datetime

from database import db
from ui import theme


class Header(tk.Frame):
    def __init__(self, parent, app, title="", back_to=None):
        super().__init__(parent, bg=theme.HEADER, padx=16, pady=10)
        self.app = app

        if back_to:
            theme.button(self, "< Back", lambda: app.show_page(back_to),
                         color=theme.NEUTRAL, font=(theme.FONT, 13, "bold")
                         ).pack(side="left", padx=(0, 16))

        shop = db.get_setting("shop_name")
        heading = f"{shop}  |  {title}" if title else shop
        tk.Label(self, text=heading, font=theme.F_HEADING, fg=theme.TEXT_ON_DARK,
                 bg=theme.HEADER).pack(side="left")
        if db.get_setting("demo_mode") == "1":
            # Make it obvious this is sample data, not a real shop.
            tk.Label(self, text=" DEMO ", font=(theme.FONT, 12, "bold"), fg=theme.TEXT,
                     bg="#F2C14E").pack(side="left", padx=12)

        theme.button(self, "Log out", app.logout, color=theme.DANGER,
                     font=(theme.FONT, 13, "bold")).pack(side="right")

        user = app.current_user
        tk.Label(self, text=f"{user.full_name} ({user.role})", font=theme.F_BODY,
                 fg=theme.TEXT_ON_DARK, bg=theme.HEADER).pack(side="right", padx=16)

        self.clock = tk.Label(self, font=theme.F_BODY, fg=theme.TEXT_ON_DARK, bg=theme.HEADER)
        self.clock.pack(side="right", padx=16)
        self._after_id = None
        self._tick()

    def _tick(self):
        self.clock.config(text=datetime.now().strftime("%d %b %Y  %I:%M %p"))
        self._after_id = self.after(10_000, self._tick)

    def destroy(self):
        # Stop the clock timer, otherwise it fires after the page is gone.
        if self._after_id:
            self.after_cancel(self._after_id)
        super().destroy()
