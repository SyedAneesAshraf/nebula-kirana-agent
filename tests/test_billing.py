import pytest

from domain import billing
from domain.errors import BelowCostError, NotFoundError, OversellError, ValidationError


def _maggi_id(conn):
    return conn.execute("SELECT id FROM products WHERE name = 'Maggi 70g'").fetchone()["id"]


def _atta_id(conn):
    return conn.execute("SELECT id FROM products WHERE name = 'Aashirvaad Atta 5kg'").fetchone()["id"]


def test_multi_turn_bill_with_edit_then_finalize_decrements_stock(seeded_conn):
    conn = seeded_conn
    chat_id = 111
    bill = billing.start_bill(conn, chat_id)
    billing.add_bill_item(conn, bill["id"], "Maggi", 4, "packet")
    # oops, meant 6 -- edit mid-build like the brief's "drop the butter, make it 6 Maggi"
    summary = billing.update_bill_item_qty(conn, bill["id"], "Maggi", 6)
    assert summary["lines"][0]["qty"] == 6
    billing.set_bill_payment(conn, bill["id"], "upi")

    before = conn.execute("SELECT qty_on_hand FROM products WHERE id = ?", (_maggi_id(conn),)).fetchone()[0]
    final = billing.finalize_bill(conn, bill["id"], idempotency_key="test-key-1")
    after = conn.execute("SELECT qty_on_hand FROM products WHERE id = ?", (_maggi_id(conn),)).fetchone()[0]

    assert final["status"] == "finalized"
    assert after == before - 6
    assert final["grand_total"] > 0


def test_finalize_is_atomic_all_or_nothing_across_lines(seeded_conn):
    conn = seeded_conn
    chat_id = 222
    bill = billing.start_bill(conn, chat_id)
    billing.add_bill_item(conn, bill["id"], "Aashirvaad Atta 5kg", 2, "packet")  # plenty in stock
    billing.add_bill_item(conn, bill["id"], "Maggi", 999, "packet")              # nowhere near enough
    billing.set_bill_payment(conn, bill["id"], "cash")

    atta_before = conn.execute("SELECT qty_on_hand FROM products WHERE id = ?", (_atta_id(conn),)).fetchone()[0]

    with pytest.raises(OversellError):
        billing.finalize_bill(conn, bill["id"], idempotency_key="test-key-2")

    atta_after = conn.execute("SELECT qty_on_hand FROM products WHERE id = ?", (_atta_id(conn),)).fetchone()[0]
    bill_after = billing.get_bill(conn, bill["id"])
    assert atta_after == atta_before  # the good line must NOT have been partially applied
    assert bill_after["status"] == "draft"  # bill stays open so the owner can fix the qty


def test_oversell_guard_blocks_exact_boundary_correctly(seeded_conn):
    conn = seeded_conn
    stock = conn.execute("SELECT qty_on_hand FROM products WHERE id = ?", (_maggi_id(conn),)).fetchone()[0]
    bill = billing.start_bill(conn, 333)
    billing.add_bill_item(conn, bill["id"], "Maggi", stock, "packet")  # exactly all remaining stock
    billing.set_bill_payment(conn, bill["id"], "cash")
    final = billing.finalize_bill(conn, bill["id"], idempotency_key="boundary-key")
    assert final["status"] == "finalized"
    left = conn.execute("SELECT qty_on_hand FROM products WHERE id = ?", (_maggi_id(conn),)).fetchone()[0]
    assert left == 0


def test_below_cost_sale_is_refused_unless_explicitly_confirmed(seeded_conn):
    conn = seeded_conn
    bill = billing.start_bill(conn, 444)
    billing.add_bill_item(conn, bill["id"], "Aashirvaad Atta 5kg", 1, "packet")
    # force the line below cost directly to simulate a manual discount scenario
    conn.execute("UPDATE bill_lines SET unit_price_snapshot = 50 WHERE bill_id = ?", (bill["id"],))
    billing.set_bill_payment(conn, bill["id"], "cash")

    with pytest.raises(BelowCostError):
        billing.finalize_bill(conn, bill["id"], idempotency_key="below-cost-1")

    # owner confirms -> explicit override, second call with a fresh key succeeds
    result = billing.finalize_bill(conn, bill["id"], idempotency_key="below-cost-2", allow_below_cost=True)
    assert result["status"] == "finalized"


def test_finalize_requires_payment_mode(seeded_conn):
    conn = seeded_conn
    bill = billing.start_bill(conn, 555)
    billing.add_bill_item(conn, bill["id"], "Maggi", 1, "packet")
    with pytest.raises(ValidationError):
        billing.finalize_bill(conn, bill["id"], idempotency_key="no-payment-key")


def test_cannot_finalize_empty_bill(seeded_conn):
    conn = seeded_conn
    bill = billing.start_bill(conn, 666)
    with pytest.raises(ValidationError):
        billing.finalize_bill(conn, bill["id"], idempotency_key="empty-bill-key")


def test_cannot_mutate_a_finalized_bill(seeded_conn):
    conn = seeded_conn
    bill = billing.start_bill(conn, 777)
    billing.add_bill_item(conn, bill["id"], "Maggi", 1, "packet")
    billing.set_bill_payment(conn, bill["id"], "cash")
    billing.finalize_bill(conn, bill["id"], idempotency_key="finalized-lock-key")
    with pytest.raises(ValidationError):
        billing.add_bill_item(conn, bill["id"], "Parle-G", 1, "packet")


def test_get_open_bill_returns_current_draft_per_chat(seeded_conn):
    conn = seeded_conn
    assert billing.get_open_bill(conn, 888) is None
    started = billing.start_bill(conn, 888)
    again = billing.start_bill(conn, 888)  # implicit chat_id binding: same chat -> same draft
    assert started["id"] == again["id"]
    assert billing.get_open_bill(conn, 888)["id"] == started["id"]


def test_credit_payment_requires_a_customer(seeded_conn):
    conn = seeded_conn
    bill = billing.start_bill(conn, 999)  # no customer_ref given
    billing.add_bill_item(conn, bill["id"], "Maggi", 1, "packet")
    with pytest.raises(ValidationError):
        billing.set_bill_payment(conn, bill["id"], "credit")


def test_credit_finalize_charges_khata(seeded_conn):
    conn = seeded_conn
    bill = billing.start_bill(conn, 1010, customer_ref="Ramesh")
    billing.add_bill_item(conn, bill["id"], "Aashirvaad Atta 5kg", 1, "packet")
    billing.set_bill_payment(conn, bill["id"], "credit")
    final = billing.finalize_bill(conn, bill["id"], idempotency_key="credit-bill-1")

    from domain.khata import get_khata_balance
    ramesh = get_khata_balance(conn, "Ramesh")
    assert ramesh["balance"] == pytest.approx(final["grand_total"])
