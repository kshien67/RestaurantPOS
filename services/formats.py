"""Turning what the user types into numbers, and numbers back into text.

Money is kept as whole cents everywhere in the app:
    parse_money("12.50") -> 1250        money(1250) -> "RM 12.50"
Percentages are kept as basis points (hundredths of a percent):
    parse_percent("6")   -> 600         percent(600) -> "6"
"""
from decimal import Decimal, InvalidOperation


def _to_decimal(text, field):
    cleaned = str(text).strip().upper().replace("RM", "").replace("%", "").replace(",", "").strip()
    if not cleaned:
        raise ValueError(f"{field} is required.")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"{field} must be a number, e.g. 12.50")
    if not value.is_finite():
        raise ValueError(f"{field} must be a number, e.g. 12.50")
    if value < 0:
        raise ValueError(f"{field} cannot be negative.")
    hundredths = value * 100
    if hundredths != hundredths.to_integral_value():
        raise ValueError(f"{field} can have at most 2 decimal places.")
    return int(hundredths)


def parse_money(text, field="Price", maximum_cents=1_000_000):
    cents = _to_decimal(text, field)
    if cents > maximum_cents:
        raise ValueError(f"{field} is too large.")
    return cents


def parse_percent(text, field="Rate"):
    bp = _to_decimal(text, field)
    if bp > 10_000:
        raise ValueError(f"{field} cannot be more than 100%.")
    return bp


def parse_count(text, field, minimum=0, maximum=99):
    try:
        n = int(str(text).strip())
    except ValueError:
        raise ValueError(f"{field} must be a whole number.")
    if not minimum <= n <= maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}.")
    return n


def money(cents, currency="RM"):
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{currency} {cents // 100:,}.{cents % 100:02d}"


def money_plain(cents):
    """For filling a text box: 1250 -> '12.50'."""
    return f"{cents // 100}.{cents % 100:02d}"


def percent(bp):
    """600 -> '6', 650 -> '6.5', 1000 -> '10'."""
    return f"{bp / 100:.2f}".rstrip("0").rstrip(".")
