"""Standing owner preferences -- the mechanism that satisfies 'memory across
sessions'. Stored in SQLite, independent of any conversation transcript, so
it survives a /new chat and a process restart alike. Keys are a fixed enum
so the model can't invent a preference nobody ever reads back."""

import sqlite3

from domain.errors import ValidationError

ALLOWED_KEYS = {
    "shop_name",
    "shop_gstin",
    "shop_address",
    "invoice_footer",
    "default_payment_mode",
    "default_atta",
    "default_rice",
    "default_dal",
}

DEFAULTS = {
    "shop_name": "Nebula Kirana Store",
    "shop_gstin": "",
    "shop_address": "",
    "invoice_footer": "Thank you for shopping with us!",
    "default_payment_mode": "",
    "default_atta": "",
    "default_rice": "",
    "default_dal": "",
}


def get_preferences(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT key, value FROM preferences WHERE key NOT LIKE 'day_closed:%'").fetchall()
    prefs = dict(DEFAULTS)
    prefs.update({r["key"]: r["value"] for r in rows if r["key"] in ALLOWED_KEYS})
    return prefs


def set_preference(conn: sqlite3.Connection, key: str, value: str) -> dict:
    if key not in ALLOWED_KEYS:
        raise ValidationError(f"Unknown preference key '{key}'. Allowed: {sorted(ALLOWED_KEYS)}.")
    conn.execute(
        "INSERT INTO preferences (key, value, updated_at) "
        "VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, str(value)),
    )
    return get_preferences(conn)
