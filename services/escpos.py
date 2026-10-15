"""ESC/POS: the command language of almost every thermal receipt printer
(Epson, Xprinter, POSMAC, Rongta, HPRT, Bixolon...).

A printout is just bytes: plain text, mixed with short commands that start
with ESC (0x1B) or GS (0x1D), e.g. "ESC a 1" = centre the next lines.
encode() turns the styled lines from services/receipts.py into those bytes.
"""

ESC = b"\x1b"
GS = b"\x1d"

INIT = ESC + b"@"                       # reset the printer to its defaults
CODE_PAGE_PC437 = ESC + b"t\x00"        # standard character set
ALIGN = {"left": ESC + b"a\x00", "center": ESC + b"a\x01"}
BOLD = {True: ESC + b"E\x01", False: ESC + b"E\x00"}
# GS ! n: character size. 0x01 = double height, 0x10 = double width.
SIZE = {"normal": GS + b"!\x00", "bold": GS + b"!\x00",
        "tall": GS + b"!\x01", "big": GS + b"!\x11"}
FEED_AND_CUT = GS + b"V\x42\x04"        # feed 4 lines, then cut the paper
# Pulse pin 2 of the drawer port for 50ms: opens a cash drawer plugged into
# the printer's RJ11 "DK" socket.
OPEN_DRAWER = ESC + b"p\x00\x19\xfa"


def _text(text):
    # Characters the printer doesn't have (e.g. Chinese) become '?' instead of crashing.
    return text.encode("cp437", errors="replace")


def encode(lines, cut=True, open_drawer=False):
    """Styled lines -> ESC/POS bytes, ready to send to the printer."""
    out = bytearray(INIT + CODE_PAGE_PC437)
    if open_drawer:
        out += OPEN_DRAWER                   # open it straight away, before printing
    for text, style, align in lines:
        out += ALIGN[align] + SIZE[style] + BOLD[style != "normal"]
        out += _text(text) + b"\n"
    out += SIZE["normal"] + BOLD[False] + ALIGN["left"]
    if cut:
        out += FEED_AND_CUT
    return bytes(out)


def drawer_only():
    """Just open the cash drawer (no paper)."""
    return INIT + OPEN_DRAWER
