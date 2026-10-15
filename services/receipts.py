"""Receipts, bills and kitchen tickets - and the list of a day's receipts.

Every slip is built as STYLED lines: (text, style, align)
    style: "normal", "bold", "big" (double width + height) or "tall" (double height)
    align: "left" or "center"
The same lines are shown on screen (build() turns them into plain text), saved
as a PDF by the virtual printer, and sent to a real thermal printer as ESC/POS
commands - so what you see is what prints.

WIDTH is characters per line: 48 on 80mm paper, 32 on 58mm (see WIDTHS).
"""
import textwrap
from datetime import datetime

from database import db
from services import formats, orders
from services import settings as shop_settings
from services.checkout import METHOD_NAMES, method_label

WIDTHS = {80: 48, 58: 32}      # paper width (mm) -> characters per line
WIDTH = WIDTHS[80]


# ---------------- building blocks ----------------

def _amount(cents):
    """1234 -> '12.34', -500 -> '-5.00' (no currency, for the right-hand column)."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100:,}.{cents % 100:02d}"


def _row(left, right="", width=WIDTH, style="normal"):
    """Text on the left, an amount on the right. Long text wraps onto more lines."""
    room = width - len(right) - 1 if right else width
    parts = textwrap.wrap(left, room) or [""]
    last = parts[-1].ljust(room) + (" " + right if right else "")
    return [(p.rstrip(), style, "left") for p in parts[:-1] + [last]]


def _indented(text, width=WIDTH, style="normal", indent="    "):
    """Text under an item, indented (also on wrapped lines)."""
    return [(part, style, "left")
            for part in textwrap.wrap(text, width, initial_indent=indent,
                                      subsequent_indent=indent)]


def _centered(text, width=WIDTH, style="normal"):
    # Double-width letters take two places, so only half as many fit.
    room = width // 2 if style == "big" else width
    return [(part, style, "center") for part in textwrap.wrap(text, room)]


def _heading(text, width=WIDTH):
    """Big if it fits on one line, otherwise bold."""
    return _centered(text, width, "big" if len(text) <= width // 2 else "bold")


def _rule(width=WIDTH):
    return [("-" * width, "normal", "left")]


def to_text(lines, width=WIDTH):
    """Styled lines -> plain text lines (for the screen and .txt files)."""
    return [text.center(width).rstrip() if align == "center" else text.rstrip()
            for text, _style, align in lines]


def _when(timestamp):
    return datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M")


def _shop_header(s, width):
    out = _heading(s["shop_name"].upper(), width)
    for extra in (s["shop_address"],
                  s["shop_phone"] and f"Tel: {s['shop_phone']}",
                  s["tax_reg_no"] and f"{s['tax_name']} Reg No: {s['tax_reg_no']}"):
        if extra:
            out += _centered(extra, width)
    return out


# ---------------- receipt / bill ----------------

def build_styled(order_id, width=WIDTH, copy=False):
    """The receipt for a paid order (or the BILL for an order not paid yet,
    or the VOID slip). copy=True marks a reprint as 'COPY'."""
    s = shop_settings.load()
    currency = s["currency"]
    order, lines = orders.load_order(order_id)
    with db.connect() as conn:
        payment = conn.execute(
            "SELECT p.*, u.full_name AS staff FROM payments p "
            "JOIN users u ON u.id = p.received_by WHERE p.order_id = ? "
            "ORDER BY p.id DESC LIMIT 1", (order_id,)).fetchone()
        creator = conn.execute("SELECT full_name FROM users WHERE id = ?",
                               (order["created_by"],)).fetchone()
        approver = conn.execute("SELECT full_name FROM users WHERE id = ?",
                                (order["voided_by"],)).fetchone()
    paid = order["status"] == "paid"
    out = _shop_header(s, width) + _rule(width)

    title = {"paid": "RECEIPT", "open": "BILL"}.get(order["status"], "VOID")
    out += _heading(f"{title} (COPY)" if copy else title, width)
    name = orders.describe(order["order_type"], order["order_no"], order["delivery_platform"],
                           order["table_name"])
    out += _row(order["order_no"], name, width)
    out += _row(f"Date: {_when(order['closed_at'] if paid else order['created_at'])}", "", width)
    staff = payment["staff"] if paid and payment else (creator["full_name"] if creator else "")
    out += _row(f"Cashier: {staff}", "", width)
    if order["delivery_ref"]:
        out += _row(f"Ref: {order['delivery_ref']}", "", width)
    if order["status"] == "void":
        if order["closed_at"]:
            out += _row(f"Voided: {_when(order['closed_at'])}", "", width)
        out += _row(f"Reason: {order['void_reason'] or '-'}", "", width)
        out += _row(f"Approved by: {approver['full_name'] if approver else '-'}", "", width)
    out += _rule(width)

    for line in lines:
        out += _row(f"{line.qty} x {line.name}", _amount(line.total), width)
        # All of an item's options on one (wrapped) line, to save paper:
        #     Large (+1.50), Iced (+0.50), 70%
        if line.modifiers:
            options = ", ".join(m.name + (f" (+{_amount(m.price)})" if m.price else "")
                                for m in line.modifiers)
            out += _indented(options, width)
        if line.note:
            out += _indented(f"Note: {line.note}", width)
    out += _rule(width)

    out += _row("Subtotal", _amount(order["subtotal_cents"]), width)
    if order["discount_cents"]:
        label = f"Discount ({order['discount_label']})" if order["discount_label"] else "Discount"
        out += _row(label, _amount(-order["discount_cents"]), width)
    if order["service_rate_bp"]:
        out += _row(f"Service charge {formats.percent(order['service_rate_bp'])}%",
                    _amount(order["service_cents"]), width)
    if order["tax_rate_bp"]:
        out += _row(f"{s['tax_name']} {formats.percent(order['tax_rate_bp'])}%",
                    _amount(order["tax_cents"]), width)
    out += _rule(width)
    out += _row("TOTAL", f"{currency} {_amount(order['total_cents'])}", width, "bold")

    if paid and payment:
        if order["rounding_cents"]:
            out += _row("Rounding adjustment", _amount(order["rounding_cents"]), width)
            out += _row("TOTAL PAID", f"{currency} {_amount(payment['amount_cents'])}", width,
                        "bold")
        method = method_label(payment["method"], order["delivery_platform"])
        if payment["method"] == "platform":
            method = f"Paid via {method}"
        if payment["tendered_cents"] is not None:
            out += _row(method, _amount(payment["tendered_cents"]), width)
            out += _row("Change", _amount(payment["change_cents"]), width)
        else:
            out += _row(method, _amount(payment["amount_cents"]), width)
        if payment["reference"]:
            out += _row(f"Ref: {payment['reference']}", "", width)
    out += _rule(width)
    if s["receipt_footer"]:
        out += _centered(s["receipt_footer"], width)
    return out


def build(order_id, width=WIDTH, copy=False):
    """The receipt as plain text lines (for the screen)."""
    return to_text(build_styled(order_id, width, copy), width)


# ---------------- kitchen ticket ----------------

def kitchen_ticket(order_id, item_ids, width=WIDTH, void=False, reason=None, staff=None):
    """The kitchen's slip for some items of an order: the items just saved,
    or (void=True) items that were cancelled, so the kitchen stops making them.
    Only items whose menu item is set to 'Print on kitchen ticket'.
    Returns [] if none of the items go to the kitchen."""
    item_ids = list(item_ids)
    if not item_ids:
        return []
    marks = ",".join("?" * len(item_ids))
    with db.connect() as conn:
        order = conn.execute(
            "SELECT o.*, t.name AS table_name FROM orders o "
            "LEFT JOIN dining_tables t ON t.id = o.table_id WHERE o.id = ?",
            (order_id,)).fetchone()
        # Read the items directly (not through load_order, which skips voided ones).
        items = conn.execute(
            "SELECT i.* FROM order_items i LEFT JOIN menu_items m ON m.id = i.menu_item_id "
            f"WHERE i.order_id = ? AND i.id IN ({marks}) "
            "AND COALESCE(m.send_to_kitchen, 1) = 1 ORDER BY i.id",
            (order_id, *item_ids)).fetchall()
        mods = conn.execute(
            f"SELECT * FROM order_item_modifiers WHERE order_item_id IN ({marks}) ORDER BY id",
            item_ids).fetchall()
    if order is None or not items:
        return []

    out = _centered("*** VOID ***" if void else "KITCHEN", width, "big")
    out += _heading(orders.describe(order["order_type"], order["order_no"],
                                    order["delivery_platform"], order["table_name"]), width)
    if order["delivery_ref"]:
        out += _centered(f"Ref: {order['delivery_ref']}", width)
    when = datetime.now().strftime("%d/%m/%Y %H:%M")
    out += _centered(f"{when}  {staff}" if staff else when, width)
    if void and reason:
        out += _centered(f"Reason: {reason}", width, "bold")
    out += _rule(width)
    for item in items:
        out += [(part, "tall", "left")
                for part in textwrap.wrap(f"{item['quantity']} x {item['item_name']}", width)]
        for m in mods:
            if m["order_item_id"] == item["id"]:
                out += _indented(f"+ {m['name']}", width, indent="   ")
        if item["note"]:
            out += _indented(f"NOTE: {item['note']}", width, "bold", indent="   ")
    out += _rule(width)
    count = sum(item["quantity"] for item in items)
    out += _row(f"{count} item{'' if count == 1 else 's'}" + ("  - DO NOT MAKE" if void else ""),
                "", width, "bold" if void else "normal")
    return out


# ---------------- a day's receipts ----------------

def list_receipts(day):
    """Orders paid OR voided on `day` (a datetime.date), newest first.
    Voided orders are included so the owner can review them; they have
    status 'void', no payment, and staff_name = the admin who approved it."""
    with db.connect() as conn:
        return conn.execute(
            "SELECT o.id, o.order_no, o.order_type, o.delivery_platform, o.closed_at, "
            "o.status, o.total_cents, o.void_reason, t.name AS table_name, "
            "p.method, p.amount_cents, p.reference, "
            "COALESCE(payer.full_name, approver.full_name, '') AS staff_name "
            "FROM orders o "
            "LEFT JOIN payments p ON p.order_id = o.id "
            "LEFT JOIN users payer ON payer.id = p.received_by "
            "LEFT JOIN users approver ON approver.id = o.voided_by "
            "LEFT JOIN dining_tables t ON t.id = o.table_id "
            "WHERE o.status IN ('paid', 'void') AND date(o.closed_at) = ? "
            "ORDER BY o.closed_at DESC, o.id DESC", (day.isoformat(),)).fetchall()


def day_totals(rows):
    """Takings per payment method for list_receipts rows, in cents:
    {'cash', 'card', 'ewallet', 'platform', 'total', 'void_count', 'void_total'}.
    'cash' is what should be in the drawer (plus any starting float);
    'platform' is money the delivery apps will pay out later.
    Voided orders are NOT takings; they are only counted in void_count/void_total."""
    totals = {key: 0 for key in METHOD_NAMES}
    paid = [r for r in rows if r["status"] == "paid"]
    voids = [r for r in rows if r["status"] == "void"]
    for r in paid:
        totals[r["method"]] = totals.get(r["method"], 0) + r["amount_cents"]
    totals["total"] = sum(r["amount_cents"] for r in paid)
    totals["void_count"] = len(voids)
    totals["void_total"] = sum(r["total_cents"] for r in voids)
    return totals
