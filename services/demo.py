"""Demo mode: a ready-made sample cafe, so anyone can try the POS in a minute.

Start it with:   py main.py --demo

It uses its OWN database (data/demo/pos.db), never the shop's real one. The
first time, it is filled with staff logins, the sample menu, 10 tables, some
of today's paid orders (cash, card, e-wallet, GrabFood, foodpanda), a voided
order, and tables that are still eating.
"""
from datetime import date, datetime, time, timedelta

import config
from database import db
from services import auth, checkout, menu, orders, settings, tables

PASSWORD = "demo1234"
STAFF = [                        # username, full name, role, PIN
    ("owner", "Owner", config.ROLE_ADMIN, "1111"),
    ("amy", "Amy Tan", config.ROLE_CASHIER, "2468"),
    ("raj", "Raj Kumar", config.ROLE_CASHIER, "1357"),
]
LOGIN_HINT = ("Demo: tap a name, then the PIN  -  Owner 1111 · Amy Tan 2468 · Raj Kumar 1357  "
              f"(password for all: {PASSWORD})")
SHOP = {"shop_name": "Kopi Corner", "shop_address": "12 Lebuh Chulia, 10200 George Town, Penang",
        "shop_phone": "04-261 2345", "tax_reg_no": "DEMO-0000-00000000",
        "receipt_footer": "Thank you! Please come again.", "tax_name": "SST",
        "tax_rate": "6", "service_rate": "10", "service_dine_in_only": True,
        "tax_on_service": True, "cash_rounding": True, "cashier_discounts": True,
        "discount_limit": "20"}


def is_demo():
    return db.get_setting("demo_mode") == "1"


def ensure_demo_data():
    """Fill an empty demo database. Does nothing if it already has staff.
    Returns True if it filled it."""
    if auth.has_any_admin():
        return False
    ids = {username: auth.create_user(username, name, PASSWORD, role, pin=pin)
           for username, name, role, pin in STAFF}
    users = {username: auth.authenticate(username, PASSWORD) for username in ids}
    owner = users["owner"]
    settings.save(SHOP, owner.id)
    db.set_setting("demo_mode", "1")
    menu.seed_sample_menu(owner.id)
    tables.add_tables(10, 4, owner.id)
    _sample_orders(users)
    return True


# ---------------- sample orders ----------------

def _items():
    found = {}
    for cat in menu.list_categories():
        for item in menu.list_items(cat["id"]):
            found[item["name"]] = item
    return found


def _line(item, qty=1, options=(), note=""):
    """A cart line with the given add-on options (by name). Required choices
    that aren't given get their first option (e.g. Regular, Hot, 100%)."""
    groups = menu.item_addon_groups(item["id"])
    by_name = {m["name"]: m["id"] for _g, opts in groups for m in opts}
    chosen = {by_name[name] for name in options}
    for group, opts in groups:
        if group["min_select"] >= 1 and not chosen & {m["id"] for m in opts}:
            chosen.add(opts[0]["id"])
    return orders.CartLine(item["id"], item["name"], item["price_cents"],
                           orders.validate_choices(groups, chosen), qty, note)


def _table_id(name):
    return next(t["id"] for t in tables.list_tables() if t["name"] == name)


def _backdate(order_id, minutes_ago, closed=False):
    """Make an order look like it happened earlier today."""
    start_of_day = datetime.combine(date.today(), time(0, 5))
    when = max(datetime.now() - timedelta(minutes=minutes_ago), start_of_day)
    stamp = when.strftime("%Y-%m-%d %H:%M:%S")
    with db.connect() as conn:
        conn.execute("UPDATE orders SET created_at = ? WHERE id = ?", (stamp, order_id))
        if closed:
            later = (when + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("UPDATE orders SET closed_at = ? WHERE id = ?", (later, order_id))
            conn.execute("UPDATE payments SET created_at = ? WHERE order_id = ?",
                         (later, order_id))


def _pay(lines, user, method, order_type="takeaway", order_id=None, reference=None,
         platform=None, ref=None, discount=None):
    s = settings.load()
    due = checkout.quote(sum(line.total for line in lines), order_type, s, discount,
                         method).due
    tendered = -(-due // 1000) * 1000 if method == "cash" else None   # rounded up to RM 10
    return checkout.pay(order_id, order_type, lines, user, method, due, tendered=tendered,
                        reference=reference, discount=discount, delivery_platform=platform,
                        delivery_ref=ref).order_id


def _sample_orders(users):
    it = _items()
    amy, raj, owner = users["amy"], users["raj"], users["owner"]

    # Paid earlier today (oldest first, so the order numbers follow the clock).
    oid = _pay([_line(it["Latte"], 2, ["Large", "Iced", "50%"]), _line(it["Nasi Lemak"])],
               amy, "cash")
    _backdate(oid, 175, closed=True)

    lines = [_line(it["Carbonara"]), _line(it["Cappuccino"], 1, ["Oat milk"]),
             _line(it["Cheesecake"])]
    oid, _ = orders.save_order(None, "dine_in", lines, raj.id, table_id=_table_id("T3"))
    _pay(lines, raj, "card", "dine_in", oid, reference="APPR 104552")
    _backdate(oid, 150, closed=True)

    oid = _pay([_line(it["Chicken Sandwich"], 2, ["Fried egg"]), _line(it["Lemon Tea"])],
               amy, "platform", "delivery", platform="GrabFood", ref="GF-2207")
    _backdate(oid, 128, closed=True)

    oid = _pay([_line(it["Americano"]), _line(it["Brownie"])], amy, "ewallet",
               reference="TNG 8812 0451")
    _backdate(oid, 105, closed=True)

    lines = [_line(it["Nasi Lemak"], 2, ["Fried egg", "Extra sambal"]),
             _line(it["Matcha Latte"], 2, ["Iced"])]
    oid, _ = orders.save_order(None, "dine_in", lines, raj.id, table_id=_table_id("T6"))
    _pay(lines, raj, "cash", "dine_in", oid, discount=checkout.Discount("percent", 1000))
    _backdate(oid, 80, closed=True)

    # A table that left without paying: voided with a reason + admin approval.
    lines = [_line(it["Carbonara"]), _line(it["Lemon Tea"], 1, ["Iced"])]
    oid, _ = orders.save_order(None, "dine_in", lines, amy.id, table_id=_table_id("T8"))
    orders.void_order(oid, owner, "Customer left without paying", requested_by=amy.id)
    _backdate(oid, 65, closed=True)

    oid = _pay([_line(it["Mocha"], 3, ["Large"])], amy, "card", reference="APPR 220917")
    _backdate(oid, 55, closed=True)

    oid = _pay([_line(it["Carbonara"]), _line(it["Matcha Latte"], 1, ["Oat milk"])], raj,
               "platform", "delivery", platform="foodpanda", ref="FP-5531")
    _backdate(oid, 35, closed=True)

    # Still open: two tables eating, and a GrabFood order waiting for its rider.
    oid, _ = orders.save_order(
        None, "dine_in", [_line(it["Latte"], 2), _line(it["Nasi Lemak"], 1, note="less spicy")],
        amy.id, table_id=_table_id("T2"))
    _backdate(oid, 25)
    oid, _ = orders.save_order(
        None, "dine_in", [_line(it["Carbonara"]), _line(it["Chicken Sandwich"]),
                          _line(it["Lemon Tea"], 2, ["Iced", "No sugar"])],
        raj.id, table_id=_table_id("T5"))
    _backdate(oid, 10)
    oid, _ = orders.save_order(None, "delivery", [_line(it["Nasi Lemak"], 2)], amy.id,
                               delivery_platform="GrabFood", delivery_ref="GF-2231")
    _backdate(oid, 5)
