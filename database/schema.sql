-- Restaurant POS database schema (version 1)
--
-- Conventions:
--   * Money is stored as INTEGER cents (RM 12.50 -> 1250) to avoid rounding errors.
--   * Percentages are stored as INTEGER basis points (6.00% -> 600).
--   * Orders are never deleted. They are marked 'void' or 'refunded' instead.
--   * Order lines copy the name and price at the moment of sale, so editing
--     the menu later never changes an old receipt.

-- ---------- Staff ----------
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    full_name     TEXT    NOT NULL,
    role          TEXT    NOT NULL CHECK (role IN ('admin', 'cashier')),
    password_hash TEXT    NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- ---------- Shop settings (key/value) ----------
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ---------- Menu ----------
CREATE TABLE IF NOT EXISTS categories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS menu_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id     INTEGER NOT NULL REFERENCES categories(id),
    name            TEXT    NOT NULL,
    price_cents     INTEGER NOT NULL CHECK (price_cents >= 0),
    track_stock     INTEGER NOT NULL DEFAULT 0,   -- 1 = count stock for this item
    stock_qty       INTEGER NOT NULL DEFAULT 0,
    low_stock_level INTEGER NOT NULL DEFAULT 0,   -- warn when stock_qty <= this
    send_to_kitchen INTEGER NOT NULL DEFAULT 1,   -- print on kitchen ticket?
    is_active       INTEGER NOT NULL DEFAULT 1,
    sort_order      INTEGER NOT NULL DEFAULT 0
);

-- Add-on groups, e.g. "Size" (pick 1) or "Extras" (pick any)
CREATE TABLE IF NOT EXISTS modifier_groups (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    min_select INTEGER NOT NULL DEFAULT 0,
    max_select INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS modifiers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id    INTEGER NOT NULL REFERENCES modifier_groups(id),
    name        TEXT    NOT NULL,
    price_cents INTEGER NOT NULL DEFAULT 0,
    is_active   INTEGER NOT NULL DEFAULT 1
);

-- Which add-on groups apply to which menu item
CREATE TABLE IF NOT EXISTS menu_item_modifier_groups (
    menu_item_id INTEGER NOT NULL REFERENCES menu_items(id),
    group_id     INTEGER NOT NULL REFERENCES modifier_groups(id),
    PRIMARY KEY (menu_item_id, group_id)
);

-- ---------- Tables ----------
CREATE TABLE IF NOT EXISTS dining_tables (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT    NOT NULL UNIQUE,     -- e.g. "T1", "Patio 2"
    seats     INTEGER NOT NULL DEFAULT 4,
    is_active INTEGER NOT NULL DEFAULT 1
);

-- ---------- Orders ----------
CREATE TABLE IF NOT EXISTS orders (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no            TEXT    NOT NULL UNIQUE,      -- human-friendly, e.g. 20261013-0001
    order_type          TEXT    NOT NULL CHECK (order_type IN ('dine_in', 'takeaway', 'delivery')),
    table_id            INTEGER REFERENCES dining_tables(id),
    delivery_ref        TEXT,                          -- e.g. Grab order number
    status              TEXT    NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'paid', 'void', 'refunded')),
    subtotal_cents      INTEGER NOT NULL DEFAULT 0,
    discount_cents      INTEGER NOT NULL DEFAULT 0,
    service_rate_bp     INTEGER NOT NULL DEFAULT 0,   -- rate used for this order
    service_cents       INTEGER NOT NULL DEFAULT 0,
    tax_rate_bp         INTEGER NOT NULL DEFAULT 0,   -- rate used for this order
    tax_cents           INTEGER NOT NULL DEFAULT 0,
    rounding_cents      INTEGER NOT NULL DEFAULT 0,   -- cash rounding adjustment
    total_cents         INTEGER NOT NULL DEFAULT 0,
    note                TEXT,
    created_by          INTEGER NOT NULL REFERENCES users(id),
    created_at          TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    closed_at           TEXT
);

CREATE TABLE IF NOT EXISTS order_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id         INTEGER NOT NULL REFERENCES orders(id),
    menu_item_id     INTEGER REFERENCES menu_items(id),
    item_name        TEXT    NOT NULL,           -- snapshot
    unit_price_cents INTEGER NOT NULL,           -- snapshot (base price)
    quantity         INTEGER NOT NULL CHECK (quantity > 0),
    discount_cents   INTEGER NOT NULL DEFAULT 0,
    line_total_cents INTEGER NOT NULL,           -- (base + add-ons) * qty - discount
    note             TEXT,                       -- e.g. "no ice"
    sent_to_kitchen  INTEGER NOT NULL DEFAULT 0,
    is_void          INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS order_item_modifiers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    order_item_id INTEGER NOT NULL REFERENCES order_items(id),
    modifier_id   INTEGER REFERENCES modifiers(id),
    name          TEXT    NOT NULL,             -- snapshot
    price_cents   INTEGER NOT NULL              -- snapshot
);

CREATE TABLE IF NOT EXISTS payments (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id       INTEGER NOT NULL REFERENCES orders(id),
    method         TEXT    NOT NULL CHECK (method IN ('cash', 'card', 'ewallet')),
    amount_cents   INTEGER NOT NULL,            -- amount applied to the bill
    tendered_cents INTEGER,                     -- cash handed over
    change_cents   INTEGER,
    reference      TEXT,                        -- card/e-wallet transaction ref
    received_by    INTEGER NOT NULL REFERENCES users(id),
    created_at     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- ---------- Stock & audit ----------
CREATE TABLE IF NOT EXISTS stock_movements (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    menu_item_id INTEGER NOT NULL REFERENCES menu_items(id),
    change_qty   INTEGER NOT NULL,              -- +10 restock, -1 sale
    reason       TEXT    NOT NULL CHECK (reason IN ('sale', 'restock', 'adjust', 'void')),
    order_id     INTEGER REFERENCES orders(id),
    user_id      INTEGER REFERENCES users(id),
    created_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER REFERENCES users(id),
    action     TEXT    NOT NULL,               -- e.g. 'login', 'void_order'
    details    TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_orders_status   ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_created  ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_order_items_ord ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_payments_order  ON payments(order_id);
