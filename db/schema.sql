PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS products (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    aliases             TEXT NOT NULL DEFAULT '',
    unit                TEXT NOT NULL,
    is_loose            INTEGER NOT NULL DEFAULT 0,
    hsn_code            TEXT NOT NULL DEFAULT '',
    gst_rate            REAL NOT NULL,
    price_includes_tax  INTEGER NOT NULL DEFAULT 1,
    cost_price          REAL NOT NULL,
    sell_price          REAL NOT NULL,
    qty_on_hand         REAL NOT NULL DEFAULT 0,
    reorder_level       REAL NOT NULL DEFAULT 0,
    is_active           INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (name, unit)
);

CREATE TABLE IF NOT EXISTS customers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    aliases     TEXT NOT NULL DEFAULT '',
    phone       TEXT,
    balance     REAL NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS bills (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id         INTEGER NOT NULL,
    customer_id     INTEGER REFERENCES customers(id),
    status          TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'finalized', 'cancelled')),
    payment_mode    TEXT CHECK (payment_mode IN ('cash', 'upi', 'card', 'credit')),
    payment_ref     TEXT,
    subtotal        REAL NOT NULL DEFAULT 0,
    cgst_total      REAL NOT NULL DEFAULT 0,
    sgst_total      REAL NOT NULL DEFAULT 0,
    round_off       REAL NOT NULL DEFAULT 0,
    grand_total     REAL NOT NULL DEFAULT 0,
    idempotency_key TEXT UNIQUE,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finalized_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_bills_chat_status ON bills(chat_id, status);

CREATE TABLE IF NOT EXISTS bill_lines (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id                 INTEGER NOT NULL REFERENCES bills(id),
    product_id              INTEGER NOT NULL REFERENCES products(id),
    description_snapshot    TEXT NOT NULL,
    unit                    TEXT NOT NULL,
    qty                     REAL NOT NULL CHECK (qty > 0),
    unit_price_snapshot     REAL NOT NULL,
    gst_rate_snapshot       REAL NOT NULL,
    taxable_value           REAL NOT NULL,
    cgst_amount             REAL NOT NULL,
    sgst_amount             REAL NOT NULL,
    line_total              REAL NOT NULL,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_bill_lines_bill ON bill_lines(bill_id);

CREATE TABLE IF NOT EXISTS stock_movements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    delta           REAL NOT NULL,
    reason          TEXT NOT NULL,
    ref_type        TEXT,
    ref_id          INTEGER,
    idempotency_key TEXT UNIQUE,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_stock_movements_product ON stock_movements(product_id);

CREATE TABLE IF NOT EXISTS khata_transactions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id     INTEGER NOT NULL REFERENCES customers(id),
    type            TEXT NOT NULL CHECK (type IN ('charge', 'payment')),
    amount          REAL NOT NULL CHECK (amount > 0),
    mode            TEXT,
    reference       TEXT,
    bill_id         INTEGER REFERENCES bills(id),
    idempotency_key TEXT UNIQUE,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_khata_customer ON khata_transactions(customer_id);

CREATE TABLE IF NOT EXISTS preferences (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS telegram_processed_updates (
    update_id   INTEGER PRIMARY KEY,
    chat_id     INTEGER,
    processed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    tool_name   TEXT NOT NULL,
    key         TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (tool_name, key)
);

CREATE TABLE IF NOT EXISTS agent_sessions (
    chat_id         INTEGER PRIMARY KEY,
    sdk_session_id  TEXT,
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id         INTEGER,
    tool_name       TEXT NOT NULL,
    tool_input_json TEXT,
    decision        TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
