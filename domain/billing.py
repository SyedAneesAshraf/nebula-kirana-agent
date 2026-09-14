"""Multi-turn bill lifecycle. A bill is a 'draft' row that add/remove/update
tools mutate freely; stock is only ever touched inside finalize_bill, in one
atomic transaction that either fully applies or fully rolls back.

Concurrency: finalize_bill takes SQLite's write lock immediately (BEGIN
IMMEDIATE) and decrements each line with `UPDATE ... WHERE qty_on_hand >= ?`,
checking rowcount. Two finalize_bill calls racing on the same product
serialize on the write lock; whichever commits second re-reads the
already-decremented row and correctly fails if stock is now insufficient.

Idempotency: every finalize_bill call carries an idempotency_key. A repeat
call with the same key returns the cached result without re-decrementing.
finalize_bill is additionally idempotent by bill state alone -- finalizing
an already-finalized bill is a no-op read, not a re-execution.
"""

import sqlite3
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from db.connection import immediate_transaction
from domain.errors import (
    BelowCostError,
    NotFoundError,
    OversellError,
    ValidationError,
)
from domain.gst import compute_line_tax, q2
from domain.idempotency import get_cached, store_cached
from domain.inventory import get_product, resolve_product

VALID_PAYMENT_MODES = ("cash", "upi", "card", "credit")


def get_open_bill(conn: sqlite3.Connection, chat_id: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM bills WHERE chat_id = ? AND status = 'draft' ORDER BY id DESC LIMIT 1",
        (chat_id,),
    ).fetchone()
    return dict(row) if row else None


def get_bill(conn: sqlite3.Connection, bill_id: int) -> dict:
    row = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
    if not row:
        raise NotFoundError(f"No bill with id {bill_id}.")
    return dict(row)


def _require_draft(bill: dict) -> None:
    if bill["status"] != "draft":
        raise ValidationError(f"Bill {bill['id']} is {bill['status']}, not draft.")


def start_bill(conn: sqlite3.Connection, chat_id: int, customer_ref=None) -> dict:
    existing = get_open_bill(conn, chat_id)
    if existing:
        return existing
    customer_id = None
    if customer_ref is not None:
        from domain.khata import resolve_customer  # local import: avoids a khata<->billing cycle
        customer_id = resolve_customer(conn, customer_ref)["id"]
    cur = conn.execute(
        "INSERT INTO bills (chat_id, customer_id, status) VALUES (?, ?, 'draft')",
        (chat_id, customer_id),
    )
    return get_bill(conn, cur.lastrowid)


def _resolve_line(conn: sqlite3.Connection, bill_id: int, line_ref) -> dict:
    if isinstance(line_ref, int) or (isinstance(line_ref, str) and line_ref.isdigit()):
        row = conn.execute(
            "SELECT * FROM bill_lines WHERE id = ? AND bill_id = ?", (int(line_ref), bill_id)
        ).fetchone()
        if not row:
            raise NotFoundError(f"No line {line_ref} on bill {bill_id}.")
        return dict(row)
    rows = conn.execute(
        "SELECT * FROM bill_lines WHERE bill_id = ? AND description_snapshot LIKE ?",
        (bill_id, f"%{line_ref}%"),
    ).fetchall()
    if not rows:
        raise NotFoundError(f"No line matching '{line_ref}' on bill {bill_id}.")
    if len(rows) > 1:
        from domain.errors import AmbiguousMatchError
        raise AmbiguousMatchError([dict(r) for r in rows])
    return dict(rows[0])


def add_bill_item(conn: sqlite3.Connection, bill_id: int, product_ref, qty: float, unit: Optional[str] = None) -> dict:
    if qty <= 0:
        raise ValidationError("qty must be positive.")
    bill = get_bill(conn, bill_id)
    _require_draft(bill)
    product = resolve_product(conn, product_ref)
    line_tax = compute_line_tax(
        product["sell_price"], qty, product["gst_rate"], bool(product["price_includes_tax"])
    )
    conn.execute(
        "INSERT INTO bill_lines "
        "(bill_id, product_id, description_snapshot, unit, qty, unit_price_snapshot, "
        " gst_rate_snapshot, taxable_value, cgst_amount, sgst_amount, line_total) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (bill_id, product["id"], product["name"], unit or product["unit"], qty,
         product["sell_price"], product["gst_rate"], float(line_tax.taxable_value),
         float(line_tax.cgst_amount), float(line_tax.sgst_amount), float(line_tax.line_total)),
    )
    summary = get_bill_summary(conn, bill_id)
    if qty > product["qty_on_hand"]:
        summary["warning"] = (
            f"Only {product['qty_on_hand']} {product['unit']} of {product['name']} in stock "
            f"right now; this will be re-checked when the bill is finalized."
        )
    return summary


def update_bill_item_qty(conn: sqlite3.Connection, bill_id: int, line_ref, new_qty: float) -> dict:
    if new_qty <= 0:
        raise ValidationError("new_qty must be positive; use remove_bill_item to drop a line.")
    bill = get_bill(conn, bill_id)
    _require_draft(bill)
    line = _resolve_line(conn, bill_id, line_ref)
    product = get_product(conn, line["product_id"])
    line_tax = compute_line_tax(
        line["unit_price_snapshot"], new_qty, line["gst_rate_snapshot"], bool(product["price_includes_tax"])
    )
    conn.execute(
        "UPDATE bill_lines SET qty = ?, taxable_value = ?, cgst_amount = ?, sgst_amount = ?, line_total = ? "
        "WHERE id = ?",
        (new_qty, float(line_tax.taxable_value), float(line_tax.cgst_amount),
         float(line_tax.sgst_amount), float(line_tax.line_total), line["id"]),
    )
    return get_bill_summary(conn, bill_id)


def remove_bill_item(conn: sqlite3.Connection, bill_id: int, line_ref) -> dict:
    bill = get_bill(conn, bill_id)
    _require_draft(bill)
    line = _resolve_line(conn, bill_id, line_ref)
    conn.execute("DELETE FROM bill_lines WHERE id = ?", (line["id"],))
    return get_bill_summary(conn, bill_id)


def set_bill_payment(conn: sqlite3.Connection, bill_id: int, mode: str, reference: Optional[str] = None) -> dict:
    mode = mode.lower()
    if mode not in VALID_PAYMENT_MODES:
        raise ValidationError(f"mode must be one of {VALID_PAYMENT_MODES}.")
    bill = get_bill(conn, bill_id)
    _require_draft(bill)
    if mode == "credit" and bill["customer_id"] is None:
        raise ValidationError("Credit payment requires a customer on the bill -- resolve the customer first.")
    conn.execute("UPDATE bills SET payment_mode = ?, payment_ref = ? WHERE id = ?", (mode, reference, bill_id))
    return get_bill_summary(conn, bill_id)


def cancel_bill(conn: sqlite3.Connection, bill_id: int) -> dict:
    bill = get_bill(conn, bill_id)
    _require_draft(bill)
    conn.execute("UPDATE bills SET status = 'cancelled' WHERE id = ?", (bill_id,))
    return get_bill(conn, bill_id)


def get_bill_summary(conn: sqlite3.Connection, bill_id: int) -> dict:
    bill = get_bill(conn, bill_id)
    lines = [dict(r) for r in conn.execute(
        "SELECT * FROM bill_lines WHERE bill_id = ? ORDER BY id", (bill_id,)
    ).fetchall()]

    subtotal = sum((Decimal(str(l["taxable_value"])) for l in lines), Decimal("0"))
    cgst_total = sum((Decimal(str(l["cgst_amount"])) for l in lines), Decimal("0"))
    sgst_total = sum((Decimal(str(l["sgst_amount"])) for l in lines), Decimal("0"))
    raw_total = subtotal + cgst_total + sgst_total
    rounded_total = raw_total.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    round_off = q2(rounded_total - raw_total)

    return {
        **bill,
        "lines": lines,
        "subtotal": float(q2(subtotal)),
        "cgst_total": float(q2(cgst_total)),
        "sgst_total": float(q2(sgst_total)),
        "round_off": float(round_off),
        "grand_total": float(rounded_total),
    }


def finalize_bill(
    conn: sqlite3.Connection,
    bill_id: int,
    idempotency_key: str,
    allow_below_cost: bool = False,
) -> dict:
    if not idempotency_key:
        raise ValidationError("idempotency_key is required.")
    cached = get_cached(conn, "finalize_bill", idempotency_key)
    if cached is not None:
        return cached

    bill = get_bill(conn, bill_id)
    if bill["status"] == "finalized":
        result = get_bill_summary(conn, bill_id)
        store_cached(conn, "finalize_bill", idempotency_key, result)
        return result
    if bill["status"] == "cancelled":
        raise ValidationError(f"Bill {bill_id} was cancelled and cannot be finalized.")
    if not bill["payment_mode"]:
        raise ValidationError("Set a payment mode before finalizing.")

    lines = conn.execute("SELECT * FROM bill_lines WHERE bill_id = ?", (bill_id,)).fetchall()
    if not lines:
        raise ValidationError("Cannot finalize an empty bill.")

    with immediate_transaction(conn):
        shortfalls, below_cost = [], []
        for line in lines:
            product = conn.execute("SELECT * FROM products WHERE id = ?", (line["product_id"],)).fetchone()
            cur = conn.execute(
                "UPDATE products SET qty_on_hand = qty_on_hand - ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE id = ? AND qty_on_hand >= ?",
                (line["qty"], line["product_id"], line["qty"]),
            )
            if cur.rowcount == 0:
                shortfalls.append({
                    "product": product["name"], "requested": line["qty"], "available": product["qty_on_hand"],
                })
                continue
            if not allow_below_cost and line["unit_price_snapshot"] < product["cost_price"]:
                below_cost.append({
                    "product": product["name"],
                    "sell_price": line["unit_price_snapshot"],
                    "cost_price": product["cost_price"],
                })
            conn.execute(
                "INSERT INTO stock_movements (product_id, delta, reason, ref_type, ref_id) "
                "VALUES (?, ?, 'sale', 'bill', ?)",
                (line["product_id"], -line["qty"], bill_id),
            )

        if shortfalls:
            raise OversellError(shortfalls)
        if below_cost:
            raise BelowCostError(below_cost)

        summary = get_bill_summary(conn, bill_id)
        conn.execute(
            "UPDATE bills SET status = 'finalized', subtotal = ?, cgst_total = ?, sgst_total = ?, "
            "round_off = ?, grand_total = ?, idempotency_key = ?, "
            "finalized_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
            (summary["subtotal"], summary["cgst_total"], summary["sgst_total"],
             summary["round_off"], summary["grand_total"], idempotency_key, bill_id),
        )

        if bill["payment_mode"] == "credit":
            from domain.khata import charge_to_credit
            charge_to_credit(
                conn, customer_ref=bill["customer_id"], amount=summary["grand_total"],
                bill_id=bill_id, idempotency_key=f"{idempotency_key}:khata",
            )

        result = get_bill_summary(conn, bill_id)
        store_cached(conn, "finalize_bill", idempotency_key, result)

    return result
