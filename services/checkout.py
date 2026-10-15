"""Checkout: discounts, working out what the customer pays, and taking payment.

How a bill is paid (all in ONE database transaction, so it either fully
happens or doesn't happen at all):
    1. Save any items not saved yet (creating the order if it's new).
    2. Add up the bill with the discount, service charge and tax.
    3. Cash only: round to the nearest 5 sen (if switched on in Shop Settings).
    4. Record the payment, mark the order 'paid', which frees its table.

The screen shows a quote() of the amount first. pay() works it out again from
the database and refuses if it no longer matches what the cashier saw
(e.g. an admin changed the tax rate in the meantime), so nobody is charged
an amount they weren't shown.
"""
from dataclasses import dataclass

import config
from database import db
from services import formats, orders, pricing
from services import settings as shop_settings
from services.orders import OrderError

# 'platform' = paid through a delivery app (GrabFood...), which collects the
# money from the customer. It is counted separately from the cash drawer.
METHOD_NAMES = {"cash": "Cash", "card": "Card", "ewallet": "E-wallet",
                "platform": "Delivery app"}
MAX_TENDER = 1_000_000           # RM 10,000: anything more is surely a typing mistake
MAX_REFERENCE = 40
MIN_REFERENCE = 4
# Card and e-wallet payments must have the terminal's approval code /
# the e-wallet's transaction ID, so each one can be matched against the
# bank's settlement report at the end of the day.
NEEDS_REFERENCE = ("card", "ewallet")


def methods_for(order_type, delivery_platform=None):
    """The payment methods to offer for an order. Orders from a delivery app
    get 'paid through the app' first, because that is how they are usually paid."""
    methods = ["cash", "card", "ewallet"]
    if order_type == "delivery" and delivery_platform in config.APP_PLATFORMS:
        methods.insert(0, "platform")
    return methods


def method_label(method, delivery_platform=None):
    """'Cash', 'Card', 'E-wallet', or the app's name (e.g. 'GrabFood')."""
    if method == "platform" and delivery_platform:
        return delivery_platform
    return METHOD_NAMES.get(method, method)


class BillChanged(OrderError):
    """The total worked out now differs from the one the cashier was shown."""


@dataclass(frozen=True)
class Discount:
    """A discount on the whole bill: kind 'percent' (value = basis points,
    1000 = 10%) or 'amount' (value = cents)."""
    kind: str
    value: int

    def __post_init__(self):
        if self.kind not in ("percent", "amount"):
            raise ValueError("Unknown discount type.")
        if self.value <= 0:
            raise ValueError("Discount must be more than 0.")
        if self.kind == "percent" and self.value > 10_000:
            raise ValueError("Discount cannot be more than 100%.")

    def cents(self, subtotal):
        """How much comes off a bill with this subtotal (never more than the subtotal)."""
        if self.kind == "percent":
            return min(subtotal, pricing.percent_of(subtotal, self.value))
        return min(subtotal, self.value)

    def label(self, currency="RM", taken=None):
        """'10%' or 'RM 5.00', printed on the receipt next to 'Discount'.
        `taken` = the discount actually given, so 'RM 50 off' a RM 12 bill
        shows as RM 12.00, not RM 50.00."""
        if self.kind == "percent":
            return f"{formats.percent(self.value)}%"
        return formats.money(self.value if taken is None else taken, currency)


@dataclass
class Quote:
    bill: pricing.Bill     # subtotal, discount, service, tax, total
    rounding: int          # cash rounding adjustment in cents (can be negative)
    due: int               # what the customer actually pays = total + rounding


def quote(subtotal, order_type, settings, discount=None, method="cash"):
    """Work out the amount to pay. Used by the screen AND by pay(), so they always agree."""
    off = discount.cents(subtotal) if discount else 0
    bill = pricing.calculate_bill(subtotal, order_type, settings, off)
    rounding = 0
    if method == "cash" and settings["cash_rounding_cents"]:
        rounding = pricing.round_cash(bill.total, settings["cash_rounding_cents"]) - bill.total
    return Quote(bill, rounding, bill.total + rounding)


def needs_discount_approval(discount_cents, subtotal, settings, user):
    """Does this discount need an admin's password?
    Yes if it is more than the shop's limit (20% of the bill by default), or if
    the user is a cashier and cashiers may not give discounts at all.
    Measured on the discount actually taken, so 'RM 10 off' counts too."""
    if discount_cents <= 0 or subtotal <= 0:
        return False
    if not user.is_admin and not settings["cashier_discounts"]:
        return True
    return discount_cents * 10_000 > subtotal * settings["discount_limit_bp"]


def suggested_notes(due):
    """Up to 3 amounts a customer is likely to hand over, for quick buttons:
    the bill rounded up to the next RM 5, RM 10, RM 50 and RM 100.
    e.g. due RM 32.45 -> RM 35, RM 40, RM 50."""
    amounts = []
    for step in (500, 1000, 5000, 10000):
        amount = -(-due // step) * step            # round UP to this note
        if amount > due and amount not in amounts:
            amounts.append(amount)
    return sorted(amounts)[:3]


@dataclass
class PaymentResult:
    order_id: int
    order_no: str
    bill: pricing.Bill
    rounding: int
    paid: int              # amount taken (total + rounding)
    method: str
    tendered: int = None   # cash handed over (cash only)
    change: int = None     # change to give back (cash only)


def pay(order_id, order_type, lines, user, method, expected_due, tendered=None,
        reference=None, discount=None, delivery_platform=None, delivery_ref=None,
        table_id=None, discount_approver=None):
    """Save any unsent lines and take payment, all at once. Returns a PaymentResult.
    `user` is the logged-in auth.User; `expected_due` is the amount shown on screen.
    `discount_approver` is the admin who typed their password for a big discount."""
    if method not in METHOD_NAMES:
        raise OrderError("Unknown payment method.")
    s = shop_settings.load()
    reference = " ".join(str(reference or "").split()) or None
    if reference and len(reference) > MAX_REFERENCE:
        raise OrderError(f"The reference is too long (max {MAX_REFERENCE} characters).")
    if method in NEEDS_REFERENCE and (not reference or len(reference) < MIN_REFERENCE):
        source = "card terminal slip" if method == "card" else "customer's e-wallet"
        raise OrderError(f"Enter the reference / approval code from the {source} "
                         f"(at least {MIN_REFERENCE} characters).")
    new_lines = [line for line in lines if not line.is_sent]

    with db.connect() as conn:
        order_id, order_no, new_ids = orders.write_new_lines(
            conn, order_id, order_type, new_lines, user.id, delivery_platform,
            delivery_ref, table_id)
        has_items = conn.execute("SELECT 1 FROM order_items WHERE order_id = ? AND is_void = 0",
                                 (order_id,)).fetchone()
        if not has_items:
            raise OrderError("There is nothing to pay. Void the order instead.")
        row = conn.execute("SELECT order_type, delivery_platform FROM orders WHERE id = ?",
                           (order_id,)).fetchone()
        if method not in methods_for(row["order_type"], row["delivery_platform"]):
            raise OrderError("That payment method can't be used for this order.")

        q = quote(orders.subtotal_of(conn, order_id), row["order_type"], s, discount, method)
        if q.due != expected_due:
            raise BillChanged("The bill has changed (prices or shop settings were updated). "
                              "Please check the new total and confirm again.")

        approved_by = None
        if needs_discount_approval(q.bill.discount, q.bill.subtotal, s, user):
            if discount_approver is None or not discount_approver.is_admin:
                if not user.is_admin and not s["cashier_discounts"]:
                    raise OrderError("Cashiers can't give discounts without an admin's approval.")
                raise OrderError(f"Discounts over {formats.percent(s['discount_limit_bp'])}% "
                                 "need an admin's approval.")
            approved_by = discount_approver

        change = None
        if method == "cash":
            if tendered is None or tendered < q.due:
                raise OrderError("The amount received is less than the amount to pay.")
            if tendered > MAX_TENDER:
                raise OrderError("The amount received is too large. Please check it.")
            change = tendered - q.due
        else:
            tendered = None            # card / e-wallet / app: the exact amount is taken

        orders.store_bill(conn, order_id, q.bill)
        label = (discount.label(s["currency"], q.bill.discount)
                 if discount and q.bill.discount else None)
        conn.execute(
            "UPDATE orders SET discount_label = ?, discount_approved_by = ?, rounding_cents = ?, "
            "status = 'paid', closed_at = datetime('now', 'localtime') WHERE id = ?",
            (label, approved_by.id if approved_by else None, q.rounding, order_id))
        conn.execute(
            "INSERT INTO payments (order_id, method, amount_cents, tendered_cents, change_cents, "
            "reference, received_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (order_id, method, q.due, tendered, change, reference, user.id))

    orders.mark_sent(new_lines, new_ids)
    details = (f"{order_no}: {method_label(method, row['delivery_platform'])} "
               f"{formats.money(q.due, s['currency'])}")
    if label:
        details += f", discount {label} (-{formats.money(q.bill.discount, s['currency'])})"
        if approved_by:
            details += f" approved by {approved_by.full_name}"
    db.log_action(user.id, "payment", details)
    return PaymentResult(order_id, order_no, q.bill, q.rounding, q.due, method, tendered, change)
