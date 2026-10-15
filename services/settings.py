"""Shop settings: reading them as proper Python values, and saving with checks.

The database stores every setting as text. load() converts them to the
right types (int / bool / str) so the rest of the app doesn't have to.
"""
from database import db
from services import formats

TEXT_KEYS = ("shop_name", "shop_address", "shop_phone", "tax_reg_no",
             "tax_name", "currency", "receipt_footer")
INT_KEYS = ("tax_rate_bp", "service_rate_bp", "cash_rounding_cents", "discount_limit_bp")
BOOL_KEYS = ("service_dine_in_only", "tax_on_service", "cashier_discounts")


def load():
    s = {}
    for key in TEXT_KEYS:
        s[key] = db.get_setting(key) or ""
    for key in INT_KEYS:
        s[key] = int(db.get_setting(key) or 0)
    for key in BOOL_KEYS:
        s[key] = db.get_setting(key) == "1"
    return s


def validate(raw):
    """raw = values straight from the form (strings and bools).
    Returns a clean dict, or raises ValueError with a message for the user."""
    clean = {}
    for key in TEXT_KEYS:
        if key in raw:
            clean[key] = " ".join(str(raw[key]).split())
    if not clean.get("shop_name"):
        raise ValueError("Shop name is required.")
    if "tax_name" in clean and not clean["tax_name"]:
        clean["tax_name"] = "Tax"
    clean["tax_rate_bp"] = formats.parse_percent(raw["tax_rate"], "Tax rate")
    clean["service_rate_bp"] = formats.parse_percent(raw["service_rate"], "Service charge")
    clean["cash_rounding_cents"] = 5 if raw["cash_rounding"] else 0
    if "discount_limit" in raw:
        clean["discount_limit_bp"] = formats.parse_percent(raw["discount_limit"],
                                                           "Discount limit")
    for key in BOOL_KEYS:
        if key in raw:            # on/off settings not on the form keep their value
            clean[key] = bool(raw[key])
    return clean


def save(raw, user_id):
    clean = validate(raw)
    for key, value in clean.items():
        if isinstance(value, bool):
            value = "1" if value else "0"
        db.set_setting(key, value)
    db.log_action(user_id, "update_settings",
                  f"tax={clean['tax_rate_bp']}bp service={clean['service_rate_bp']}bp")
    return clean
