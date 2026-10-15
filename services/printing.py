"""Printing: receipts, bills, kitchen tickets, test prints and the cash drawer.

Printer types (set in Admin -> Printers):
  virtual  - no printer needed. Each slip is saved as a PDF + a text file in
             the 'printouts' folder next to the database (data/printouts).
             Ideal for demos.
  network  - a thermal printer on the shop's network (LAN), reached by its IP
             address, port 9100.
  windows  - a printer installed in Windows (usually USB). Raw ESC/POS commands
             are sent through the Windows print spooler.
  none     - (kitchen only) don't print kitchen tickets.
Almost every thermal printer sold in Malaysia (Epson, Xprinter, POSMAC,
Rongta, HPRT...) understands ESC/POS, so one code path covers them all.

Printing NEVER stops a sale: these functions are only called after the order
is safely saved, and they return a PrintResult instead of raising. If a real
printer fails, a copy is saved as a file and the message says where.
"""
import re
import socket
import sys
import textwrap
from dataclasses import dataclass
from datetime import date, datetime

from database import db
from services import escpos, pdf, receipts
from services import settings as shop_settings

KINDS = {"receipt": ("virtual", "network", "windows"),
         "kitchen": ("none", "virtual", "network", "windows")}
KIND_NAMES = {"none": "None", "virtual": "Virtual (PDF)", "network": "Network (LAN)",
              "windows": "Windows / USB"}
PAPERS = (80, 58)
NETWORK_TIMEOUT = 3          # seconds: a switched-off printer freezes the screen this long
HOST_PATTERN = re.compile(r"^[A-Za-z0-9.\-]{1,64}$")
# Windows' built-in "printers" that are really files/apps, never receipt printers.
NOT_RECEIPT_PRINTERS = re.compile(r"\b(fax|pdf|xps|onenote)\b", re.IGNORECASE)


class PrintError(Exception):
    """Something went wrong talking to the printer (message is for the screen)."""


@dataclass
class PrinterConfig:
    role: str                  # "receipt" or "kitchen"
    kind: str                  # see KINDS
    host: str = ""
    port: int = 9100
    windows_name: str = ""
    paper: int = 80            # mm
    auto_print: bool = True    # receipt printer: print automatically after payment
    cash_drawer: bool = True   # receipt printer: open the drawer on cash payments

    @property
    def chars(self):
        return receipts.WIDTHS[self.paper]

    def describe(self):
        if self.kind == "network":
            where = f"network printer {self.host}:{self.port}"
        elif self.kind == "windows":
            where = f"Windows printer '{self.windows_name}'"
        else:
            where = KIND_NAMES[self.kind].lower()
        return f"{where}, {self.paper}mm paper ({self.chars} characters per line)"


@dataclass
class PrintResult:
    ok: bool
    message: str


# ---------------- settings ----------------

def load_config(role):
    def get(key, default=""):
        value = db.get_setting(f"{role}_{key}")
        return default if value is None else value
    return PrinterConfig(
        role=role,
        kind=get("printer", "virtual"),
        host=get("host"),
        port=int(get("port", "9100") or 9100),
        windows_name=get("windows_name"),
        paper=int(get("paper", "80") or 80),
        auto_print=db.get_setting("receipt_auto_print") != "0",
        cash_drawer=db.get_setting("cash_drawer") != "0",
    )


def validate_config(role, raw):
    """raw = values from the Printers screen. Returns a PrinterConfig or raises ValueError."""
    kind = raw.get("kind", "virtual")
    if kind not in KINDS[role]:
        raise ValueError("Choose a printer type.")
    try:
        paper = int(raw.get("paper", 80))
    except ValueError:
        paper = 0
    if paper not in PAPERS:
        raise ValueError("Paper must be 80mm or 58mm.")
    host = str(raw.get("host", "")).strip()
    windows_name = str(raw.get("windows_name", "")).strip()
    try:
        port = int(str(raw.get("port", "9100")).strip() or 9100)
    except ValueError:
        port = 0
    name = "Receipt printer" if role == "receipt" else "Kitchen printer"
    if kind == "network":
        if not HOST_PATTERN.match(host):
            raise ValueError(f"{name}: enter the printer's IP address, e.g. 192.168.1.50")
        if not 1 <= port <= 65535:
            raise ValueError(f"{name}: the port must be a number (usually 9100).")
    if kind == "windows" and not windows_name:
        raise ValueError(f"{name}: choose the Windows printer.")
    return PrinterConfig(role, kind, host, port, windows_name, paper,
                         bool(raw.get("auto_print", True)), bool(raw.get("cash_drawer", True)))


def save_config(role, raw, user_id):
    cfg = validate_config(role, raw)
    values = {"printer": cfg.kind, "host": cfg.host, "port": cfg.port,
              "windows_name": cfg.windows_name, "paper": cfg.paper}
    for key, value in values.items():
        db.set_setting(f"{role}_{key}", value)
    if role == "receipt":
        db.set_setting("receipt_auto_print", "1" if cfg.auto_print else "0")
        db.set_setting("cash_drawer", "1" if cfg.cash_drawer else "0")
    db.log_action(user_id, "printer_settings", f"{role}: {cfg.describe()}")
    return cfg


# ---------------- sending ----------------

def printouts_dir():
    return db.data_folder() / "printouts"


def _safe(label):
    return re.sub(r"[^A-Za-z0-9_-]+", "-", label).strip("-") or "slip"


def _save_copy(lines, cfg, label):
    """Virtual printer: save the slip as PDF + text. Returns the PDF's path."""
    folder = printouts_dir() / date.today().isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now():%H%M%S}_{_safe(label)}"
    path, n = folder / f"{stem}.pdf", 2
    while path.exists():
        path, n = folder / f"{stem}_{n}.pdf", n + 1
    pdf.write(lines, path, cfg.chars, cfg.paper)
    path.with_suffix(".txt").write_text("\n".join(receipts.to_text(lines, cfg.chars)) + "\n",
                                        encoding="utf-8")
    return path


def _send_network(host, port, data):
    try:
        with socket.create_connection((host, port), timeout=NETWORK_TIMEOUT) as conn:
            conn.sendall(data)
    except OSError:
        raise PrintError(f"can't reach the printer at {host}:{port}. "
                         "Is it switched on, with paper, on the same network?")


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _DocInfo1(ctypes.Structure):
        _fields_ = [("pDocName", wintypes.LPWSTR), ("pOutputFile", wintypes.LPWSTR),
                    ("pDatatype", wintypes.LPWSTR)]

    class _PrinterInfo4(ctypes.Structure):
        _fields_ = [("pPrinterName", wintypes.LPWSTR), ("pServerName", wintypes.LPWSTR),
                    ("Attributes", wintypes.DWORD)]

    def _winspool():
        """The Windows print spooler functions, with their exact argument types
        (needed so printer handles aren't cut short on 64-bit Windows)."""
        ws = ctypes.WinDLL("winspool.drv", use_last_error=True)
        handle_p = ctypes.POINTER(wintypes.HANDLE)
        dword_p = ctypes.POINTER(wintypes.DWORD)
        ws.OpenPrinterW.argtypes = [wintypes.LPWSTR, handle_p, ctypes.c_void_p]
        ws.OpenPrinterW.restype = wintypes.BOOL
        ws.ClosePrinter.argtypes = [wintypes.HANDLE]
        ws.ClosePrinter.restype = wintypes.BOOL
        ws.StartDocPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                        ctypes.POINTER(_DocInfo1)]
        ws.StartDocPrinterW.restype = wintypes.DWORD
        ws.EndDocPrinter.argtypes = [wintypes.HANDLE]
        ws.EndDocPrinter.restype = wintypes.BOOL
        ws.StartPagePrinter.argtypes = [wintypes.HANDLE]
        ws.StartPagePrinter.restype = wintypes.BOOL
        ws.EndPagePrinter.argtypes = [wintypes.HANDLE]
        ws.EndPagePrinter.restype = wintypes.BOOL
        ws.WritePrinter.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, dword_p]
        ws.WritePrinter.restype = wintypes.BOOL
        ws.EnumPrintersW.argtypes = [wintypes.DWORD, wintypes.LPWSTR, wintypes.DWORD,
                                     ctypes.c_void_p, wintypes.DWORD, dword_p, dword_p]
        ws.EnumPrintersW.restype = wintypes.BOOL
        return ws


def list_windows_printers():
    """Names of the printers installed in Windows (only reads the list),
    leaving out Fax / PDF / XPS / OneNote, which can't print receipts."""
    if sys.platform != "win32":
        return []
    ws = _winspool()
    flags = 0x2 | 0x4                       # local printers + network connections
    needed, count = wintypes.DWORD(), wintypes.DWORD()
    ws.EnumPrintersW(flags, None, 4, None, 0, ctypes.byref(needed), ctypes.byref(count))
    if not needed.value:
        return []
    buffer = ctypes.create_string_buffer(needed.value)
    if not ws.EnumPrintersW(flags, None, 4, buffer, needed, ctypes.byref(needed),
                            ctypes.byref(count)):
        return []
    infos = ctypes.cast(buffer, ctypes.POINTER(_PrinterInfo4))
    names = (infos[i].pPrinterName for i in range(count.value))
    return sorted(name for name in names if not NOT_RECEIPT_PRINTERS.search(name))


def _send_windows(printer_name, data, title):
    if sys.platform != "win32":
        raise PrintError("Windows printers only work on Windows.")
    ws = _winspool()
    handle = wintypes.HANDLE()
    if not ws.OpenPrinterW(printer_name, ctypes.byref(handle), None):
        raise PrintError(f"the Windows printer '{printer_name}' was not found.")
    try:
        doc = _DocInfo1(title, None, "RAW")          # RAW = send our bytes as they are
        if not ws.StartDocPrinterW(handle, 1, ctypes.byref(doc)):
            raise PrintError(f"Windows refused the print job for '{printer_name}'.")
        try:
            ws.StartPagePrinter(handle)
            written = wintypes.DWORD()
            buf = ctypes.create_string_buffer(data, len(data))
            ok = ws.WritePrinter(handle, buf, len(data), ctypes.byref(written))
            ws.EndPagePrinter(handle)
            if not ok or written.value != len(data):
                raise PrintError(f"could not send the slip to '{printer_name}'.")
        finally:
            ws.EndDocPrinter(handle)
    finally:
        ws.ClosePrinter(handle)


def _send(cfg, data, title):
    if cfg.kind == "network":
        _send_network(cfg.host, cfg.port, data)
    elif cfg.kind == "windows":
        _send_windows(cfg.windows_name, data, title)


def _deliver(cfg, lines, what, label, open_drawer=False):
    """Print one slip on the given printer. Never raises: returns a PrintResult."""
    if cfg.kind == "virtual":
        try:
            path = _save_copy(lines, cfg, label)
        except OSError as err:                  # e.g. the printouts folder can't be written
            return PrintResult(False, f"{what} could not be saved: {err}")
        drawer = " (The cash drawer would open now.)" if open_drawer else ""
        return PrintResult(True, f"{what} saved as {path.name}.{drawer}")

    try:
        _send(cfg, escpos.encode(lines, open_drawer=open_drawer), f"{what} {label}")
        return PrintResult(True, f"{what} printed.")
    except (PrintError, OSError) as err:
        failure = f"{what} was NOT printed: {err}"
    # The printer failed: keep a copy as a file so nothing is lost.
    try:
        path = _save_copy(lines, cfg, label)
        return PrintResult(False, f"{failure}\nA copy was saved as {path.name} "
                                  "in the printouts folder.")
    except OSError:
        return PrintResult(False, failure)


# ---------------- what gets printed ----------------

def _order_no(order_id):
    with db.connect() as conn:
        row = conn.execute("SELECT order_no, receipt_prints FROM orders WHERE id = ?",
                           (order_id,)).fetchone()
    return row["order_no"], row["receipt_prints"]


def _staff_name(user_id):
    with db.connect() as conn:
        row = conn.execute("SELECT full_name FROM users WHERE id = ?", (user_id,)).fetchone()
    return row["full_name"] if row else ""


def print_receipt(order_id, user_id, open_drawer=False):
    """The customer's receipt. The first one that actually prints is the
    original; every later print is marked COPY (and written to the audit log)."""
    cfg = load_config("receipt")
    order_no, prints = _order_no(order_id)
    copy = prints > 0
    lines = receipts.build_styled(order_id, cfg.chars, copy=copy)
    result = _deliver(cfg, lines, "Receipt copy" if copy else "Receipt",
                      f"receipt-{order_no}", open_drawer)
    if result.ok:
        with db.connect() as conn:
            conn.execute("UPDATE orders SET receipt_prints = receipt_prints + 1 WHERE id = ?",
                         (order_id,))
        if copy:
            db.log_action(user_id, "reprint_receipt", order_no)
    return result


def print_bill(order_id, user_id):
    """The bill for an open (unpaid) order, e.g. when a table asks for it."""
    cfg = load_config("receipt")
    order_no, _prints = _order_no(order_id)
    return _deliver(cfg, receipts.build_styled(order_id, cfg.chars), "Bill", f"bill-{order_no}")


def print_kitchen(order_id, item_ids, user_id, void=False, reason=None):
    """Kitchen ticket for some items (just saved, or voided). Returns None if
    there is nothing for the kitchen (no kitchen printer, or e.g. only desserts)."""
    cfg = load_config("kitchen")
    if cfg.kind == "none":
        return None
    lines = receipts.kitchen_ticket(order_id, item_ids, cfg.chars, void, reason,
                                    _staff_name(user_id))
    if not lines:
        return None
    order_no, _prints = _order_no(order_id)
    what = "Kitchen VOID ticket" if void else "Kitchen ticket"
    return _deliver(cfg, lines, what, f"kitchen{'-void' if void else ''}-{order_no}")


def open_drawer():
    """Open the cash drawer (plugged into the receipt printer) without printing."""
    cfg = load_config("receipt")
    if cfg.kind == "virtual":
        return PrintResult(True, "Cash drawer opened (virtual printer).")
    try:
        _send(cfg, escpos.drawer_only(), "Open cash drawer")
    except PrintError as err:
        return PrintResult(False, f"The cash drawer did not open: {err}")
    return PrintResult(True, "Cash drawer opened.")


def after_payment(order_id, method, new_item_ids, user_id):
    """Everything that prints after a payment, in this order:
      1. the kitchen ticket for items saved at the moment of paying,
      2. the receipt (if 'print automatically' is on),
      3. the cash drawer for cash payments.
    Returns a list of PrintResults to show on screen."""
    results = []
    kitchen = print_kitchen(order_id, new_item_ids, user_id)
    if kitchen:
        results.append(kitchen)
    cfg = load_config("receipt")
    drawer = method == "cash" and cfg.cash_drawer
    if cfg.auto_print:
        results.append(print_receipt(order_id, user_id, open_drawer=drawer))
    elif drawer:
        results.append(open_drawer())
    return results


def test_print(cfg):
    """A short test slip, so the admin can check the printer and paper width."""
    width = cfg.chars
    s = shop_settings.load()
    ruler = ("1234567890" * 10)[:width]
    lines = [(s["shop_name"].upper()[:width // 2], "big", "center"),
             ("TEST PRINT", "bold", "center"),
             ("-" * width, "normal", "left"),
             (f"{cfg.role.title()} printer", "normal", "left")]
    lines += [(part, "normal", "left") for part in textwrap.wrap(cfg.describe(), width)]
    lines += [(datetime.now().strftime("%d/%m/%Y %H:%M:%S"), "normal", "left"),
              ("-" * width, "normal", "left"),
              ("This ruler should fit on ONE line:", "normal", "left"),
              (ruler, "normal", "left"),
              ("Big text", "big", "left"),
              ("Tall text", "tall", "left"),
              ("Bold text", "bold", "left")]
    return _deliver(cfg, lines, "Test print", f"test-{cfg.role}")
