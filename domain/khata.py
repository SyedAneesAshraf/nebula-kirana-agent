"""Customer credit ledger (khata). find_customer/resolve_customer never
auto-create a customer on a miss -- charging or settling a khata for an
unknown name raises NotFoundError, which the tool layer turns into a
'confirm or refuse' prompt back to the owner rather than silently guessing."""

import sqlite3
from typing import Optional

from db.connection import immediate_transaction
from domain.errors import AmbiguousMatchError, NotFoundError, ValidationError
from domain.idempotency import get_cached, store_cached

VALID_PAYMENT_MODES = ("cash", "upi", "card")


def find_customer(conn: sqlite3.Connection, name: str) -> dict:
    name = name.strip()
    rows = conn.execute(
        "SELECT * FROM customers WHERE name LIKE ? OR aliases LIKE ? ORDER BY name",
        (f"%{name}%", f"%{name}%"),
    ).fetchall()
    if not rows:
        raise NotFoundError(f"No customer matching '{name}'. Ask the owner whether to add them first.")
    if len(rows) > 1:
        exact = [r for r in rows if r["name"].lower() == name.lower()]
        if len(exact) == 1:
            return dict(exact[0])
        raise AmbiguousMatchError([dict(r) for r in rows])
    return dict(rows[0])


def resolve_customer(conn: sqlite3.Connection, customer_ref) -> dict:
    if isinstance(customer_ref, int) or (isinstance(customer_ref, str) and customer_ref.isdigit()):
        row = conn.execute("SELECT * FROM customers WHERE id = ?", (int(customer_ref),)).fetchone()
        if not row:
            raise NotFoundError(f"No customer with id {customer_ref}.")
        return dict(row)
    return find_customer(conn, customer_ref)


def add_customer(conn: sqlite3.Connection, name: str, phone: Optional[str] = None, aliases: str = "") -> dict:
    existing = conn.execute("SELECT id FROM customers WHERE lower(name) = lower(?)", (name,)).fetchone()
    if existing:
        raise ValidationError(f"Customer '{name}' already exists (id={existing['id']}).")
    cur = conn.execute("INSERT INTO customers (name, aliases, phone) VALUES (?, ?, ?)", (name, aliases, phone))
    return resolve_customer(conn, cur.lastrowid)


def get_khata_balance(conn: sqlite3.Connection, customer_ref) -> dict:
    return resolve_customer(conn, customer_ref)


def list_khata_customers(conn: sqlite3.Connection, min_balance: float = 0) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM customers WHERE balance > ? ORDER BY balance DESC", (min_balance,)
    ).fetchall()
    return [dict(r) for r in rows]


def charge_to_credit(
    conn: sqlite3.Connection,
    *,
    customer_ref,
    amount: float,
    bill_id: Optional[int] = None,
    idempotency_key: Optional[str] = None,
) -> dict:
    if amount <= 0:
        raise ValidationError("amount must be positive.")
    if idempotency_key:
        cached = get_cached(conn, "charge_to_credit", idempotency_key)
        if cached is not None:
            return cached

    customer = resolve_customer(conn, customer_ref)
    with immediate_transaction(conn):
        conn.execute("UPDATE customers SET balance = balance + ? WHERE id = ?", (amount, customer["id"]))
        conn.execute(
            "INSERT INTO khata_transactions (customer_id, type, amount, bill_id, idempotency_key) "
            "VALUES (?, 'charge', ?, ?, ?)",
            (customer["id"], amount, bill_id, idempotency_key),
        )
        result = resolve_customer(conn, customer["id"])
        if idempotency_key:
            store_cached(conn, "charge_to_credit", idempotency_key, result)
    return result


def record_khata_payment(
    conn: sqlite3.Connection,
    *,
    customer_ref,
    amount: float,
    mode: str,
    reference: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> dict:
    if amount <= 0:
        raise ValidationError("amount must be positive.")
    mode = mode.lower()
    if mode not in VALID_PAYMENT_MODES:
        raise ValidationError(f"mode must be one of {VALID_PAYMENT_MODES}.")
    if idempotency_key:
        cached = get_cached(conn, "record_khata_payment", idempotency_key)
        if cached is not None:
            return cached

    customer = resolve_customer(conn, customer_ref)
    with immediate_transaction(conn):
        conn.execute("UPDATE customers SET balance = balance - ? WHERE id = ?", (amount, customer["id"]))
        conn.execute(
            "INSERT INTO khata_transactions (customer_id, type, amount, mode, reference, idempotency_key) "
            "VALUES (?, 'payment', ?, ?, ?, ?)",
            (customer["id"], amount, mode, reference, idempotency_key),
        )
        result = resolve_customer(conn, customer["id"])
        if result["balance"] < 0:
            result = {**result, "note": (
                f"Payment exceeds outstanding balance; {customer['name']} now has a "
                f"credit of {abs(result['balance']):.2f} with the shop."
            )}
        if idempotency_key:
            store_cached(conn, "record_khata_payment", idempotency_key, result)
    return result
