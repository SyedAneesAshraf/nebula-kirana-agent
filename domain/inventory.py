"""Catalog and stock management. Every mutating function here is the sole,
authoritative place stock changes -- billing.py calls back into the same
UPDATE ... WHERE qty_on_hand >= ? pattern for sale decrements, so there is
exactly one code path that can take stock negative, and it can't."""

import sqlite3
from typing import Optional

from db.connection import immediate_transaction
from domain.errors import AmbiguousMatchError, NotFoundError, ValidationError
from domain.gst import ALLOWED_GST_RATES
from domain.idempotency import get_cached, store_cached


def find_product(conn: sqlite3.Connection, query: str) -> dict:
    query = query.strip()
    rows = conn.execute(
        "SELECT * FROM products WHERE is_active = 1 AND (name LIKE ? OR aliases LIKE ?) ORDER BY name",
        (f"%{query}%", f"%{query}%"),
    ).fetchall()
    if not rows:
        raise NotFoundError(f"No product matching '{query}'.")
    if len(rows) > 1:
        exact = [r for r in rows if r["name"].lower() == query.lower()]
        if len(exact) == 1:
            return dict(exact[0])
        raise AmbiguousMatchError([dict(r) for r in rows])
    return dict(rows[0])


def get_product(conn: sqlite3.Connection, product_id: int) -> dict:
    row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if not row:
        raise NotFoundError(f"No product with id {product_id}.")
    return dict(row)


def resolve_product(conn: sqlite3.Connection, product_ref) -> dict:
    """product_ref may be a product id (int, or a digit-only string) or free text."""
    if isinstance(product_ref, int) or (isinstance(product_ref, str) and product_ref.isdigit()):
        return get_product(conn, int(product_ref))
    return find_product(conn, product_ref)


def add_product(
    conn: sqlite3.Connection,
    *,
    name: str,
    unit: str,
    is_loose: bool,
    hsn_code: str,
    gst_rate: float,
    cost_price: float,
    mrp: float,
    reorder_level: float = 0,
    opening_qty: float = 0,
    aliases: str = "",
) -> dict:
    if gst_rate not in ALLOWED_GST_RATES:
        raise ValidationError(f"gst_rate must be one of {ALLOWED_GST_RATES}, got {gst_rate}.")
    if cost_price < 0 or mrp < 0:
        raise ValidationError("cost_price and mrp must be non-negative.")
    if mrp < cost_price:
        raise ValidationError("mrp cannot be below cost_price.")
    existing = conn.execute(
        "SELECT id FROM products WHERE lower(name) = lower(?) AND unit = ?", (name, unit)
    ).fetchone()
    if existing:
        raise ValidationError(f"Product '{name}' ({unit}) already exists (id={existing['id']}).")
    cur = conn.execute(
        "INSERT INTO products "
        "(name, aliases, unit, is_loose, hsn_code, gst_rate, price_includes_tax, "
        " cost_price, sell_price, qty_on_hand, reorder_level) "
        "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
        (name, aliases, unit, int(bool(is_loose)), hsn_code, gst_rate, cost_price, mrp,
         opening_qty, reorder_level),
    )
    return get_product(conn, cur.lastrowid)


def receive_stock(
    conn: sqlite3.Connection,
    *,
    product_ref,
    qty: float,
    cost_price: Optional[float] = None,
    mrp: Optional[float] = None,
    idempotency_key: Optional[str] = None,
) -> dict:
    if qty <= 0:
        raise ValidationError("qty must be positive.")
    if idempotency_key:
        cached = get_cached(conn, "receive_stock", idempotency_key)
        if cached is not None:
            return cached

    product = resolve_product(conn, product_ref)
    with immediate_transaction(conn):
        updates, params = ["qty_on_hand = qty_on_hand + ?"], [qty]
        if cost_price is not None:
            updates.append("cost_price = ?")
            params.append(cost_price)
        if mrp is not None:
            updates.append("sell_price = ?")
            params.append(mrp)
        updates.append("updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
        params.append(product["id"])
        conn.execute(f"UPDATE products SET {', '.join(updates)} WHERE id = ?", params)
        conn.execute(
            "INSERT INTO stock_movements (product_id, delta, reason, ref_type, idempotency_key) "
            "VALUES (?, ?, 'receive', 'receive', ?)",
            (product["id"], qty, idempotency_key),
        )
        result = get_product(conn, product["id"])
        if idempotency_key:
            store_cached(conn, "receive_stock", idempotency_key, result)
    return result


def adjust_stock(conn: sqlite3.Connection, *, product_id: int, delta: float, reason: str) -> dict:
    if not reason or not reason.strip():
        raise ValidationError("A reason is required for a manual stock adjustment.")
    product = get_product(conn, product_id)
    with immediate_transaction(conn):
        cur = conn.execute(
            "UPDATE products SET qty_on_hand = qty_on_hand + ?, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
            "WHERE id = ? AND qty_on_hand + ? >= 0",
            (delta, product_id, delta),
        )
        if cur.rowcount == 0:
            raise ValidationError(
                f"Adjustment would take '{product['name']}' negative "
                f"(have {product['qty_on_hand']}, delta {delta})."
            )
        conn.execute(
            "INSERT INTO stock_movements (product_id, delta, reason, ref_type) VALUES (?, ?, ?, 'manual')",
            (product_id, delta, reason),
        )
        result = get_product(conn, product_id)
    return result


def list_low_stock(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM products WHERE is_active = 1 AND qty_on_hand <= reorder_level ORDER BY name"
    ).fetchall()
    return [dict(r) for r in rows]


def get_reorder_suggestions(conn: sqlite3.Connection, lookback_days: int = 14, horizon_days: int = 5) -> list[dict]:
    rows = conn.execute(
        """
        SELECT p.id, p.name, p.unit, p.qty_on_hand, p.reorder_level,
               COALESCE(SUM(bl.qty), 0) AS sold_qty
        FROM products p
        LEFT JOIN bill_lines bl ON bl.product_id = p.id
        LEFT JOIN bills b ON b.id = bl.bill_id
            AND b.status = 'finalized'
            AND b.finalized_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?)
        WHERE p.is_active = 1
        GROUP BY p.id
        ORDER BY p.name
        """,
        (f"-{lookback_days} days",),
    ).fetchall()

    suggestions = []
    for r in rows:
        avg_daily = r["sold_qty"] / lookback_days if lookback_days else 0
        days_left = (r["qty_on_hand"] / avg_daily) if avg_daily > 0 else None
        below_reorder = r["qty_on_hand"] <= r["reorder_level"]
        low_runway = days_left is not None and days_left <= horizon_days
        if below_reorder or low_runway:
            suggestions.append({
                "product_id": r["id"],
                "name": r["name"],
                "unit": r["unit"],
                "qty_on_hand": r["qty_on_hand"],
                "reorder_level": r["reorder_level"],
                "avg_daily_sales": round(avg_daily, 2),
                "estimated_days_left": round(days_left, 1) if days_left is not None else None,
            })
    return suggestions
