"""Simulates Telegram-style redelivery: the same logical call arriving twice
with the same idempotency_key must only take effect once."""

from domain import billing, inventory, khata


def test_receive_stock_is_idempotent(seeded_conn):
    conn = seeded_conn
    product = inventory.find_product(conn, "Maggi")
    before = product["qty_on_hand"]

    r1 = inventory.receive_stock(conn, product_ref=product["id"], qty=50, idempotency_key="stockin-1")
    r2 = inventory.receive_stock(conn, product_ref=product["id"], qty=50, idempotency_key="stockin-1")

    assert r1 == r2
    after = inventory.get_product(conn, product["id"])["qty_on_hand"]
    assert after == before + 50  # not +100


def test_finalize_bill_is_idempotent_by_key(seeded_conn):
    conn = seeded_conn
    bill = billing.start_bill(conn, 4001)
    billing.add_bill_item(conn, bill["id"], "Maggi", 2, "packet")
    billing.set_bill_payment(conn, bill["id"], "upi")

    maggi_before = inventory.find_product(conn, "Maggi")["qty_on_hand"]

    r1 = billing.finalize_bill(conn, bill["id"], idempotency_key="dup-update-42")
    r2 = billing.finalize_bill(conn, bill["id"], idempotency_key="dup-update-42")

    assert r1 == r2
    maggi_after = inventory.find_product(conn, "Maggi")["qty_on_hand"]
    assert maggi_after == maggi_before - 2  # decremented exactly once


def test_finalize_bill_retried_with_different_key_is_still_a_noop_once_finalized(seeded_conn):
    """Covers the case where the model itself retries finalize with a new
    key (rather than Telegram redelivering the same update) -- bill.status
    alone must still make this safe."""
    conn = seeded_conn
    bill = billing.start_bill(conn, 4002)
    billing.add_bill_item(conn, bill["id"], "Maggi", 1, "packet")
    billing.set_bill_payment(conn, bill["id"], "cash")

    billing.finalize_bill(conn, bill["id"], idempotency_key="first-attempt")
    maggi_after_first = inventory.find_product(conn, "Maggi")["qty_on_hand"]

    result = billing.finalize_bill(conn, bill["id"], idempotency_key="second-attempt-different-key")
    maggi_after_second = inventory.find_product(conn, "Maggi")["qty_on_hand"]

    assert result["status"] == "finalized"
    assert maggi_after_second == maggi_after_first  # no second decrement


def test_charge_to_credit_is_idempotent(seeded_conn):
    conn = seeded_conn
    r1 = khata.charge_to_credit(conn, customer_ref="Ramesh", amount=500, idempotency_key="charge-1")
    r2 = khata.charge_to_credit(conn, customer_ref="Ramesh", amount=500, idempotency_key="charge-1")
    assert r1["balance"] == r2["balance"] == 500


def test_record_khata_payment_is_idempotent(seeded_conn):
    conn = seeded_conn
    khata.charge_to_credit(conn, customer_ref="Ramesh", amount=500, idempotency_key="charge-setup")
    r1 = khata.record_khata_payment(conn, customer_ref="Ramesh", amount=300, mode="cash", idempotency_key="pay-1")
    r2 = khata.record_khata_payment(conn, customer_ref="Ramesh", amount=300, mode="cash", idempotency_key="pay-1")
    assert r1["balance"] == r2["balance"] == 200
