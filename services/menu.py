"""Menu rules: categories, menu items, and add-ons (modifier groups + options).

Nothing on the menu is ever deleted, only hidden (is_active = 0), because old
orders still point at these rows. Hidden things don't appear on the order screen.

Every list has a sort_order so the admin can choose the order of tiles on the
order screen with the Up / Down buttons.
"""
import sqlite3

from database import db

MAX_NAME = 40          # long names don't fit on a 58/80mm receipt
DEFAULT_COLOR = "#D9822B"


class MenuError(Exception):
    """Raised with a message that is safe to show to the user."""


def _clean_name(name, what):
    name = " ".join(str(name).split())
    if not name:
        raise MenuError(f"{what} name is required.")
    if len(name) > MAX_NAME:
        raise MenuError(f"{what} name is too long (max {MAX_NAME} characters).")
    return name


# ---------------- Categories ----------------

def list_categories(active_only=False):
    sql = "SELECT * FROM categories"
    if active_only:
        sql += " WHERE is_active = 1"
    with db.connect() as conn:
        return conn.execute(sql + " ORDER BY sort_order, id").fetchall()


def save_category(cat_id, name, color, is_active, user_id):
    """Create (cat_id=None) or update a category. Returns its id."""
    name = _clean_name(name, "Category")
    try:
        with db.connect() as conn:
            if cat_id is None:
                cur = conn.execute(
                    "INSERT INTO categories (name, color, is_active, sort_order) "
                    "VALUES (?, ?, ?, ?)",
                    (name, color or DEFAULT_COLOR, int(is_active),
                     db.next_sort_order(conn, "categories")))
                cat_id = cur.lastrowid
            else:
                conn.execute("UPDATE categories SET name = ?, color = ?, is_active = ? "
                             "WHERE id = ?", (name, color or DEFAULT_COLOR, int(is_active), cat_id))
    except sqlite3.IntegrityError:
        raise MenuError(f"There is already a category called '{name}'.")
    db.log_action(user_id, "save_category", name)
    return cat_id


def move_category(cat_id, direction):
    db.reorder("categories", cat_id, direction)


# ---------------- Menu items ----------------

def list_items(category_id, active_only=False):
    sql = "SELECT * FROM menu_items WHERE category_id = ?"
    if active_only:
        sql += " AND is_active = 1"
    with db.connect() as conn:
        return conn.execute(sql + " ORDER BY sort_order, id", (category_id,)).fetchall()


def get_item(item_id):
    """Returns (item row, set of add-on group ids linked to it)."""
    with db.connect() as conn:
        item = conn.execute("SELECT * FROM menu_items WHERE id = ?", (item_id,)).fetchone()
        groups = {r["group_id"] for r in conn.execute(
            "SELECT group_id FROM menu_item_modifier_groups WHERE menu_item_id = ?",
            (item_id,))}
    return item, groups


def save_item(item_id, category_id, name, price_cents, send_to_kitchen, is_active,
              group_ids, user_id):
    """Create (item_id=None) or update a menu item. Returns its id."""
    name = _clean_name(name, "Item")
    if category_id is None:
        raise MenuError("Choose a category for this item.")
    if price_cents < 0:
        raise MenuError("Price cannot be negative.")

    with db.connect() as conn:
        clash = conn.execute(
            "SELECT 1 FROM menu_items WHERE category_id = ? AND name = ? COLLATE NOCASE "
            "AND id IS NOT ?", (category_id, name, item_id)).fetchone()
        if clash:
            raise MenuError(f"'{name}' already exists in this category.")

        if item_id is None:
            cur = conn.execute(
                "INSERT INTO menu_items (category_id, name, price_cents, send_to_kitchen, "
                "is_active, sort_order) VALUES (?, ?, ?, ?, ?, ?)",
                (category_id, name, price_cents, int(send_to_kitchen), int(is_active),
                 db.next_sort_order(conn, "menu_items", "WHERE category_id = ?", (category_id,))))
            item_id = cur.lastrowid
        else:
            old_cat = conn.execute("SELECT category_id FROM menu_items WHERE id = ?",
                                   (item_id,)).fetchone()["category_id"]
            sort_sql = ""
            params = [category_id, name, price_cents, int(send_to_kitchen), int(is_active)]
            if old_cat != category_id:   # moved to another category: put it last there
                sort_sql = ", sort_order = ?"
                params.append(db.next_sort_order(conn, "menu_items", "WHERE category_id = ?",
                                         (category_id,)))
            conn.execute(
                "UPDATE menu_items SET category_id = ?, name = ?, price_cents = ?, "
                f"send_to_kitchen = ?, is_active = ?{sort_sql} WHERE id = ?",
                (*params, item_id))

        conn.execute("DELETE FROM menu_item_modifier_groups WHERE menu_item_id = ?", (item_id,))
        conn.executemany(
            "INSERT INTO menu_item_modifier_groups (menu_item_id, group_id) VALUES (?, ?)",
            [(item_id, g) for g in sorted(group_ids)])

    db.log_action(user_id, "save_item", f"{name} @ {price_cents}")
    return item_id


def move_item(item_id, direction):
    db.reorder("menu_items", item_id, direction, scope_col="category_id")


# ---------------- Add-ons ----------------

def group_rule_text(min_select, max_select):
    """Plain-English rule shown to staff, e.g. 'Pick 1 (required)'."""
    if min_select >= 1:
        if max_select == min_select:
            return f"Pick {min_select} (required)"
        return f"Pick {min_select}-{max_select} (required)"
    return "Optional, pick 1" if max_select == 1 else f"Optional, up to {max_select}"


def list_groups(active_only=False):
    sql = "SELECT * FROM modifier_groups"
    if active_only:
        sql += " WHERE is_active = 1"
    with db.connect() as conn:
        return conn.execute(sql + " ORDER BY sort_order, id").fetchall()


def save_group(group_id, name, required, max_select, is_active, user_id):
    name = _clean_name(name, "Add-on group")
    min_select = 1 if required else 0
    if max_select < 1:
        raise MenuError("Max choices must be at least 1.")
    with db.connect() as conn:
        if group_id is None:
            cur = conn.execute(
                "INSERT INTO modifier_groups (name, min_select, max_select, is_active, sort_order) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, min_select, max_select, int(is_active), db.next_sort_order(conn, "modifier_groups")))
            group_id = cur.lastrowid
        else:
            conn.execute("UPDATE modifier_groups SET name = ?, min_select = ?, max_select = ?, "
                         "is_active = ? WHERE id = ?",
                         (name, min_select, max_select, int(is_active), group_id))
    db.log_action(user_id, "save_addon_group", name)
    return group_id


def move_group(group_id, direction):
    db.reorder("modifier_groups", group_id, direction)


def list_modifiers(group_id, active_only=False):
    sql = "SELECT * FROM modifiers WHERE group_id = ?"
    if active_only:
        sql += " AND is_active = 1"
    with db.connect() as conn:
        return conn.execute(sql + " ORDER BY sort_order, id", (group_id,)).fetchall()


def save_modifier(mod_id, group_id, name, price_cents, is_active, user_id):
    name = _clean_name(name, "Option")
    if group_id is None:
        raise MenuError("Choose an add-on group first.")
    if price_cents < 0:
        raise MenuError("Price cannot be negative.")
    with db.connect() as conn:
        clash = conn.execute(
            "SELECT 1 FROM modifiers WHERE group_id = ? AND name = ? COLLATE NOCASE "
            "AND id IS NOT ?", (group_id, name, mod_id)).fetchone()
        if clash:
            raise MenuError(f"'{name}' already exists in this group.")
        if mod_id is None:
            cur = conn.execute(
                "INSERT INTO modifiers (group_id, name, price_cents, is_active, sort_order) "
                "VALUES (?, ?, ?, ?, ?)",
                (group_id, name, price_cents, int(is_active),
                 db.next_sort_order(conn, "modifiers", "WHERE group_id = ?", (group_id,))))
            mod_id = cur.lastrowid
        else:
            conn.execute("UPDATE modifiers SET name = ?, price_cents = ?, is_active = ? "
                         "WHERE id = ?", (name, price_cents, int(is_active), mod_id))
    db.log_action(user_id, "save_addon_option", f"{name} @ {price_cents}")
    return mod_id


def move_modifier(mod_id, direction):
    db.reorder("modifiers", mod_id, direction, scope_col="group_id")


def item_addon_groups(item_id):
    """The add-on choices to offer for one item on the order screen:
    [(group row, [option rows]), ...]. Hidden groups/options are left out."""
    result = []
    with db.connect() as conn:
        groups = conn.execute(
            "SELECT g.* FROM modifier_groups g "
            "JOIN menu_item_modifier_groups link ON link.group_id = g.id "
            "WHERE link.menu_item_id = ? AND g.is_active = 1 "
            "ORDER BY g.sort_order, g.id", (item_id,)).fetchall()
        for g in groups:
            options = conn.execute(
                "SELECT * FROM modifiers WHERE group_id = ? AND is_active = 1 "
                "ORDER BY sort_order, id", (g["id"],)).fetchall()
            if options:
                result.append((g, options))
    return result


# ---------------- Sample data ----------------

def is_menu_empty():
    with db.connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0


def seed_sample_menu(user_id):
    """Fill an empty menu with a small cafe menu, so you can try things out.
    Edit or hide anything you don't need."""
    if not is_menu_empty():
        raise MenuError("The menu already has categories.")

    groups = {}
    for name, required, max_select, options in [
        ("Size", True, 1, [("Regular", 0), ("Large", 150)]),
        ("Temperature", True, 1, [("Hot", 0), ("Iced", 50)]),
        ("Milk", False, 1, [("Oat milk", 200), ("Skim milk", 0), ("Low fat milk", 0),
                            ("Less milk", 0)]),
        # Required, so 100% is pre-selected and the barista always sees the sugar level.
        ("Sweetness", True, 1, [("100%", 0), ("70%", 0), ("50%", 0), ("30%", 0),
                                ("No sugar", 0)]),
        ("Coffee extras", False, 2, [("Extra shot", 200), ("Vanilla syrup", 150)]),
        ("Food extras", False, 3, [("Fried egg", 200), ("Extra cheese", 250),
                                   ("Extra sambal", 100)]),
    ]:
        gid = save_group(None, name, required, max_select, True, user_id)
        groups[name] = gid
        for opt_name, price in options:
            save_modifier(None, gid, opt_name, price, True, user_id)

    drink = ["Size", "Temperature", "Sweetness"]
    coffee = drink + ["Milk", "Coffee extras"]
    menu = [
        ("Coffee", "#8B5E3C", [("Americano", 800, coffee), ("Latte", 1100, coffee),
                               ("Cappuccino", 1100, coffee), ("Mocha", 1250, coffee)]),
        ("Non-Coffee", "#2E8B57", [("Matcha Latte", 1300, drink + ["Milk"]),
                                   ("Chocolate", 1000, drink + ["Milk"]),
                                   ("Lemon Tea", 700, drink)]),
        ("Food", "#D9822B", [("Nasi Lemak", 1290, ["Food extras"]),
                             ("Chicken Sandwich", 1450, ["Food extras"]),
                             ("Carbonara", 1890, ["Food extras"])]),
        ("Dessert", "#7B4B94", [("Cheesecake", 1200, []), ("Brownie", 850, [])]),
    ]
    for cat_name, color, items in menu:
        cid = save_category(None, cat_name, color, True, user_id)
        for item_name, price, group_names in items:
            # Desserts are served from the counter, so they skip the kitchen ticket.
            to_kitchen = cat_name != "Dessert"
            save_item(None, cid, item_name, price, to_kitchen, True,
                      {groups[g] for g in group_names}, user_id)
