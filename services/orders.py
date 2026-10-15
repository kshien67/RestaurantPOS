"""Orders: the cart, saving orders, re-opening them, and voiding.

Key ideas:
  * A CartLine copies the item's name and prices when it's added, so editing
    the menu later never changes an order that was already taken.
  * A line is "sent" once its order has been saved. (In Phase 6 that's the
    moment the kitchen ticket prints.) Sent lines can't be edited any more;
    voiding them needs a reason and an admin's password, and every void is
    written to the audit log.
  * Orders are never deleted. A cancelled order gets status 'void'.
"""
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from database import db
from services import formats, pricing
from services import settings as shop_settings

ORDER_TYPES = ("dine_in", "takeaway", "delivery")
TYPE_NAMES = {"dine_in": "Dine-in", "takeaway": "Takeaway", "delivery": "Delivery"}
MAX_QTY = 99
MAX_NOTE = 60
MAX_REASON = 100


class OrderError(Exception):
    """Raised with a message that is safe to show to the user."""


@dataclass(frozen=True)
class Modifier:
    id: int
    name: str
    price: int          # cents


@dataclass(eq=False)       # eq=False: two lines are only "equal" if they're the same object
class CartLine:
    menu_item_id: int
    name: str
    base_price: int                     # cents, without add-ons
    modifiers: list = field(default_factory=list)
    qty: int = 1
    note: str = ""
    order_item_id: int = None           # set once saved in the database

    @property
    def unit_price(self):
        return self.base_price + sum(m.price for m in self.modifiers)

    @property
    def total(self):
        return self.unit_price * self.qty

    @property
    def is_sent(self):
        return self.order_item_id is not None

    def same_choice(self, other):
        """True if both lines are the same item with the same add-ons and note."""
        return (not self.is_sent and not other.is_sent
                and self.menu_item_id == other.menu_item_id
                and [m.id for m in self.modifiers] == [m.id for m in other.modifiers]
                and self.note == other.note)


# ---------------- Cart helpers (no database) ----------------

def add_line(lines, new_line):
    """Put new_line in the cart. If an identical unsent line exists, just raise
    its quantity instead. Returns the line that now holds the item."""
    for line in lines:
        if line.same_choice(new_line):
            line.qty = min(MAX_QTY, line.qty + new_line.qty)
            return line
    lines.append(new_line)
    return new_line


def validate_choices(groups, chosen_ids):
    """Check the add-ons picked for one item against each group's rules.
    groups = menu.item_addon_groups(item_id). Returns [Modifier, ...] in menu order."""
    chosen_ids = set(chosen_ids)
    all_ids = set()
    result = []
    for group, options in groups:
        all_ids.update(m["id"] for m in options)
        picked = [m for m in options if m["id"] in chosen_ids]
        lowest, highest = group["min_select"], group["max_select"]
        if len(picked) < lowest:
            what = "one option" if lowest == 1 else f"at least {lowest} options"
            raise OrderError(f"{group['name']}: please choose {what}.")
        if len(picked) > highest:
            raise OrderError(f"{group['name']}: choose at most {highest}.")
        result += [Modifier(m["id"], m["name"], m["price_cents"]) for m in picked]
    if chosen_ids - all_ids:
        raise OrderError("One of the chosen options is no longer available.")
    return result


def clean_note(note):
    note = " ".join(str(note).split())
    if len(note) > MAX_NOTE:
        raise OrderError(f"Note is too long (max {MAX_NOTE} characters).")
    return note


def short_number(order_no):
    """'20261013-0012' -> '#12' (the number staff call out)."""
    return "#" + str(int(order_no.split("-")[1]))


def describe(order_type, order_no=None, platform=None, table_name=None):
    """'Takeaway #12', 'GrabFood #13', 'Table T3 #14',
    or before saving: 'New takeaway order', 'Table T3 (new order)'."""
    if order_type == "dine_in" and table_name:
        name = f"Table {table_name}"
        return f"{name} {short_number(order_no)}" if order_no else f"{name} (new order)"
    name = platform if order_type == "delivery" and platform else TYPE_NAMES[order_type]
    if order_no:
        return f"{name} {short_number(order_no)}"
    return f"New {name} order" if platform else f"New {name.lower()} order"


# ---------------- Database ----------------

def _next_order_no(conn):
    prefix = datetime.now().strftime("%Y%m%d")
    count = conn.execute("SELECT COUNT(*) FROM orders WHERE order_no LIKE ?",
                         (prefix + "-%",)).fetchone()[0]
    return f"{prefix}-{count + 1:04d}"


def subtotal_of(conn, order_id):
    """Sum of the order's (non-void) lines, in cents."""
    return conn.execute(
        "SELECT COALESCE(SUM(line_total_cents), 0) FROM order_items "
        "WHERE order_id = ? AND is_void = 0", (order_id,)).fetchone()[0]


def store_bill(conn, order_id, bill):
    """Write a pricing.Bill's numbers (and the rates used) onto the order."""
    conn.execute(
        "UPDATE orders SET subtotal_cents = ?, discount_cents = ?, service_rate_bp = ?, "
        "service_cents = ?, tax_rate_bp = ?, tax_cents = ?, total_cents = ? WHERE id = ?",
        (bill.subtotal, bill.discount, bill.service_rate_bp, bill.service,
         bill.tax_rate_bp, bill.tax, bill.total, order_id))


def recalculate(conn, order_id, settings=None):
    """Add up the order again from its lines and store the totals. Returns the Bill."""
    order = conn.execute("SELECT order_type, discount_cents FROM orders WHERE id = ?",
                         (order_id,)).fetchone()
    bill = pricing.calculate_bill(subtotal_of(conn, order_id), order["order_type"],
                                  settings or shop_settings.load(), order["discount_cents"])
    store_bill(conn, order_id, bill)
    return bill


def _check_table_free(conn, table_id):
    table = conn.execute("SELECT name, is_active FROM dining_tables WHERE id = ?",
                         (table_id,)).fetchone()
    if table is None or not table["is_active"]:
        raise OrderError("That table is not available.")
    busy = conn.execute("SELECT 1 FROM orders WHERE table_id = ? AND status = 'open'",
                        (table_id,)).fetchone()
    if busy:
        raise OrderError(f"Table {table['name']} already has an open order. "
                         "Go back to the table map and tap it to add items.")
    return table


def write_new_lines(conn, order_id, order_type, new_lines, user_id, delivery_platform=None,
                    delivery_ref=None, table_id=None):
    """For use INSIDE a database transaction (by save_order and checkout.pay).
    Creates the order first if order_id is None, then inserts the new lines.
    Returns (order_id, order_no, [ids of the new order_items rows])."""
    if order_type not in ORDER_TYPES:
        raise OrderError("Unknown order type.")
    for line in new_lines:
        if not 1 <= line.qty <= MAX_QTY:
            raise OrderError(f"Quantity for {line.name} must be 1 to {MAX_QTY}.")

    if order_id is None:
        if not new_lines:
            raise OrderError("Tap items on the left to add them first.")
        if order_type == "dine_in" and table_id is None:
            raise OrderError("Choose a table for this dine-in order.")
        if table_id is not None:
            _check_table_free(conn, table_id)
        order_no = _next_order_no(conn)
        try:
            cur = conn.execute(
                "INSERT INTO orders (order_no, order_type, table_id, delivery_platform, "
                "delivery_ref, created_by) VALUES (?, ?, ?, ?, ?, ?)",
                (order_no, order_type, table_id, delivery_platform, delivery_ref, user_id))
        except sqlite3.IntegrityError:
            # The database's own safety net (one open order per table).
            raise OrderError("That table already has an open order.")
        order_id = cur.lastrowid
    else:
        row = conn.execute("SELECT order_no, status FROM orders WHERE id = ?",
                           (order_id,)).fetchone()
        if row is None or row["status"] != "open":
            raise OrderError("This order is already closed.")
        order_no = row["order_no"]

    new_ids = []
    for line in new_lines:
        cur = conn.execute(
            "INSERT INTO order_items (order_id, menu_item_id, item_name, unit_price_cents, "
            "quantity, line_total_cents, note, sent_to_kitchen) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
            (order_id, line.menu_item_id, line.name, line.base_price, line.qty,
             line.total, line.note or None))
        new_ids.append(cur.lastrowid)
        conn.executemany(
            "INSERT INTO order_item_modifiers (order_item_id, modifier_id, name, price_cents) "
            "VALUES (?, ?, ?, ?)",
            [(cur.lastrowid, m.id, m.name, m.price) for m in line.modifiers])
    return order_id, order_no, new_ids


def save_order(order_id, order_type, lines, user_id, delivery_platform=None,
               delivery_ref=None, table_id=None):
    """Save the unsent lines. Creates the order first if order_id is None.
    Dine-in orders need a table_id. Returns (order_id, order_no).
    The saved lines become 'sent'."""
    new_lines = [line for line in lines if not line.is_sent]
    if not new_lines:
        raise OrderError("There are no new items to save.")
    with db.connect() as conn:
        order_id, order_no, new_ids = write_new_lines(
            conn, order_id, order_type, new_lines, user_id, delivery_platform,
            delivery_ref, table_id)
        recalculate(conn, order_id)

    mark_sent(new_lines, new_ids)
    db.log_action(user_id, "save_order", f"{order_no}: {len(new_lines)} new line(s)")
    return order_id, order_no


def mark_sent(new_lines, new_ids):
    """Call only AFTER the transaction has committed, so a failed save
    never leaves lines looking 'sent' on screen."""
    for line, new_id in zip(new_lines, new_ids):
        line.order_item_id = new_id


def load_order(order_id):
    """Returns (order row, [CartLine, ...]) without voided lines."""
    with db.connect() as conn:
        order = conn.execute(
            "SELECT o.*, t.name AS table_name FROM orders o "
            "LEFT JOIN dining_tables t ON t.id = o.table_id WHERE o.id = ?",
            (order_id,)).fetchone()
        if order is None:
            raise OrderError("Order not found.")
        items = conn.execute("SELECT * FROM order_items WHERE order_id = ? AND is_void = 0 "
                             "ORDER BY id", (order_id,)).fetchall()
        mods = conn.execute(
            "SELECT m.* FROM order_item_modifiers m JOIN order_items i ON i.id = m.order_item_id "
            "WHERE i.order_id = ? ORDER BY m.id", (order_id,)).fetchall()

    mods_by_line = {}
    for m in mods:
        mods_by_line.setdefault(m["order_item_id"], []).append(
            Modifier(m["modifier_id"], m["name"], m["price_cents"]))
    lines = [CartLine(i["menu_item_id"], i["item_name"], i["unit_price_cents"],
                      mods_by_line.get(i["id"], []), i["quantity"], i["note"] or "", i["id"])
             for i in items]
    return order, lines


# ---------------- Voids ----------------
# Voiding something that was already saved (sent to the kitchen) needs:
#   * a reason (e.g. "Customer left without paying"), and
#   * an admin's approval: the screen asks an admin for their password
#     (auth.approve_as_admin) and passes that admin in as `approver`.
# The reason and the approving admin are stored on the order / item, and
# written to the audit log together with who asked for the void.

def clean_reason(reason):
    reason = " ".join(str(reason or "").split())
    if not reason:
        raise OrderError("Choose or type a reason for the void.")
    if len(reason) > MAX_REASON:
        raise OrderError(f"Reason is too long (max {MAX_REASON} characters).")
    return reason


def _check_approver(approver):
    if approver is None or not approver.is_admin:
        raise OrderError("An admin must approve this void.")


def _void_details(conn, what, reason, approver, requested_by):
    details = f"{what}. Reason: {reason}. Approved by {approver.full_name}"
    if requested_by and requested_by != approver.id:
        name = conn.execute("SELECT full_name FROM users WHERE id = ?",
                            (requested_by,)).fetchone()
        details += f", requested by {name['full_name'] if name else requested_by}"
    return details


def void_line(order_item_id, approver, reason, requested_by=None):
    """Cancel a line that was already sent. `approver` = the admin who approved it."""
    _check_approver(approver)
    reason = clean_reason(reason)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT i.*, o.status, o.order_no FROM order_items i "
            "JOIN orders o ON o.id = i.order_id WHERE i.id = ?", (order_item_id,)).fetchone()
        if row is None or row["is_void"]:
            raise OrderError("That item was not found or is already void.")
        if row["status"] != "open":
            raise OrderError("This order is already closed.")
        conn.execute("UPDATE order_items SET is_void = 1, void_reason = ?, voided_by = ? "
                     "WHERE id = ?", (reason, approver.id, order_item_id))
        recalculate(conn, row["order_id"])
        details = _void_details(conn, f"{row['order_no']}: {row['quantity']} x {row['item_name']}",
                                reason, approver, requested_by)
    db.log_action(approver.id, "void_item", details)


def void_order(order_id, approver, reason, requested_by=None):
    """Cancel a whole saved order. `approver` = the admin who approved it."""
    _check_approver(approver)
    reason = clean_reason(reason)
    with db.connect() as conn:
        row = conn.execute("SELECT order_no, status, total_cents FROM orders WHERE id = ?",
                           (order_id,)).fetchone()
        if row is None or row["status"] != "open":
            raise OrderError("Only open orders can be voided.")
        conn.execute("UPDATE orders SET status = 'void', void_reason = ?, voided_by = ?, "
                     "closed_at = datetime('now', 'localtime') WHERE id = ?",
                     (reason, approver.id, order_id))
        details = _void_details(conn, f"{row['order_no']} ({formats.money(row['total_cents'])})",
                                reason, approver, requested_by)
    db.log_action(approver.id, "void_order", details)


def move_to_table(order_id, new_table_id, user_id):
    """Move an open dine-in order to another (free) table."""
    with db.connect() as conn:
        order = conn.execute(
            "SELECT o.order_no, o.order_type, o.status, t.name AS table_name FROM orders o "
            "LEFT JOIN dining_tables t ON t.id = o.table_id WHERE o.id = ?",
            (order_id,)).fetchone()
        if order is None or order["status"] != "open":
            raise OrderError("Only open orders can be moved.")
        if order["order_type"] != "dine_in":
            raise OrderError("Only dine-in orders have a table.")
        new_table = _check_table_free(conn, new_table_id)
        try:
            conn.execute("UPDATE orders SET table_id = ? WHERE id = ?", (new_table_id, order_id))
        except sqlite3.IntegrityError:
            raise OrderError("That table already has an open order.")
    db.log_action(user_id, "move_table",
                  f"{order['order_no']}: {order['table_name']} -> {new_table['name']}")


def list_open_orders():
    with db.connect() as conn:
        return conn.execute(
            "SELECT o.*, u.full_name AS staff_name, t.name AS table_name, "
            "(SELECT COALESCE(SUM(quantity), 0) FROM order_items "
            " WHERE order_id = o.id AND is_void = 0) AS item_count "
            "FROM orders o JOIN users u ON u.id = o.created_by "
            "LEFT JOIN dining_tables t ON t.id = o.table_id "
            "WHERE o.status = 'open' ORDER BY o.created_at, o.id").fetchall()
