"""Bill calculation: service charge, tax and cash rounding.

This is the ONE place that decides how a bill is added up. The settings
screen preview uses it now, and checkout will use it in Phase 5, so the
preview always matches the real receipt.

Order of calculation:
    1. subtotal - discount                         = net
    2. service charge = net x service rate         (dine-in only, if set)
    3. tax base = net (+ service, if "tax on service" is on)
    4. tax = tax base x tax rate
    5. total = net + service + tax
Cash payments can then be rounded to the nearest 5 sen with round_cash().
"""
from dataclasses import dataclass


@dataclass
class Bill:
    subtotal: int
    discount: int
    service_rate_bp: int
    service: int
    tax_rate_bp: int
    tax: int
    total: int


def percent_of(amount_cents, rate_bp):
    """amount x rate, rounded to the nearest cent (0.5 sen rounds up)."""
    return (amount_cents * rate_bp + 5_000) // 10_000


def calculate_bill(subtotal, order_type, settings, discount=0):
    """settings is the dict from services.settings.load()."""
    discount = max(0, min(discount, subtotal))
    net = subtotal - discount

    service_rate = settings["service_rate_bp"]
    if settings["service_dine_in_only"] and order_type != "dine_in":
        service_rate = 0
    service = percent_of(net, service_rate)

    tax_base = net + service if settings["tax_on_service"] else net
    tax_rate = settings["tax_rate_bp"]
    tax = percent_of(tax_base, tax_rate)

    return Bill(subtotal, discount, service_rate, service, tax_rate, tax, net + service + tax)


def round_cash(cents, step=5):
    """Round to the nearest `step` cents. With step=5 (Malaysian rounding):
    x.x1, x.x2 round down to x.x0; x.x3, x.x4 round up to x.x5;
    x.x6, x.x7 round down to x.x5; x.x8, x.x9 round up to the next x.x0."""
    if step <= 1:
        return cents
    remainder = cents % step
    if remainder * 2 < step:
        return cents - remainder
    return cents - remainder + step
