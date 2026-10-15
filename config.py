"""App-wide settings and file locations.

Every path is built from this file's own location, so the app works no matter
which folder you launch it from.
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "pos.db"
BACKUP_DIR = DATA_DIR / "backups"
DEMO_DB_PATH = DATA_DIR / "demo" / "pos.db"     # py main.py --demo (never the real data)

APP_TITLE = "Restaurant POS"
WINDOW_SIZE = "1280x800"

# Roles a user account can have.
ROLE_ADMIN = "admin"
ROLE_CASHIER = "cashier"
ROLES = (ROLE_ADMIN, ROLE_CASHIER)

# Shown when starting a delivery order. Edit this list to match your shop.
DELIVERY_PLATFORMS = ("GrabFood", "foodpanda", "ShopeeFood", "Phone order")

# Delivery apps that collect the money from the customer and pay the shop later.
# Their orders can be closed as "Paid by GrabFood" etc., which is counted
# separately from the cash drawer. ("Phone order" is not here: the rider
# collects cash or e-wallet, so those orders are paid the normal way.)
APP_PLATFORMS = ("GrabFood", "foodpanda", "ShopeeFood")

# Reasons offered when voiding an order or an item already sent to the
# kitchen. Staff can also type another reason. Every void also needs an
# admin's password.
VOID_REASONS = (
    "Customer left without paying",
    "Wrong item / order entered",
    "Customer changed their mind",
    "Item not available",
    "Food / drink problem",
    "Duplicate order",
)
