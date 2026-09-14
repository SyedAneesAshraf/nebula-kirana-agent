"""Real file-backed DB, real OS threads, real connections -- exercises the
actual SQLite WAL + BEGIN IMMEDIATE locking path rather than mocking it."""

import threading

import pytest

from db.connection import get_connection, init_db
from db.seed import seed as seed_db
from domain import billing, inventory
from domain.errors import OversellError


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "concurrency_test.db")
    setup_conn = get_connection(path)
    init_db(setup_conn)
    seed_db(setup_conn)
    setup_conn.close()
    return path


def test_two_concurrent_finalize_calls_never_oversell(db_path):
    probe = get_connection(db_path)
    stock = inventory.find_product(probe, "Maggi")["qty_on_hand"]
    probe.close()
    assert stock == 6  # seed data: deliberately low so two 4-unit bills can't both fit

    qty_per_bill = 4
    results, errors = {}, {}
    barrier = threading.Barrier(2)

    def run(chat_id: int, label: str):
        conn = get_connection(db_path)
        try:
            bill = billing.start_bill(conn, chat_id)
            billing.add_bill_item(conn, bill["id"], "Maggi", qty_per_bill, "packet")
            billing.set_bill_payment(conn, bill["id"], "cash")
            barrier.wait(timeout=5)  # line both threads up to hit finalize at the same instant
            results[label] = billing.finalize_bill(conn, bill["id"], idempotency_key=f"race-{label}")
        except Exception as e:  # noqa: BLE001 -- deliberately broad, asserted on below
            errors[label] = e
        finally:
            conn.close()

    threads = [
        threading.Thread(target=run, args=(9001, "a")),
        threading.Thread(target=run, args=(9002, "b")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(results) == 1, f"expected exactly one success; results={results} errors={errors}"
    assert len(errors) == 1, f"expected exactly one refusal; results={results} errors={errors}"
    assert isinstance(next(iter(errors.values())), OversellError)

    check = get_connection(db_path)
    final_stock = inventory.find_product(check, "Maggi")["qty_on_hand"]
    check.close()
    assert final_stock == stock - qty_per_bill  # decremented exactly once, never negative


def test_sale_and_stock_in_racing_do_not_corrupt_quantity(db_path):
    """A sale finalize and a stock receipt landing at the same instant must
    both apply, in some serialized order, without a lost update."""
    probe = get_connection(db_path)
    start_qty = inventory.find_product(probe, "Aashirvaad Atta 5kg")["qty_on_hand"]
    probe.close()

    barrier = threading.Barrier(2)
    done = {}

    def sell():
        conn = get_connection(db_path)
        try:
            bill = billing.start_bill(conn, 9101)
            billing.add_bill_item(conn, bill["id"], "Aashirvaad Atta 5kg", 2, "packet")
            billing.set_bill_payment(conn, bill["id"], "upi")
            barrier.wait(timeout=5)
            billing.finalize_bill(conn, bill["id"], idempotency_key="race-sale")
            done["sale"] = True
        finally:
            conn.close()

    def receive():
        conn = get_connection(db_path)
        try:
            barrier.wait(timeout=5)
            inventory.receive_stock(
                conn, product_ref="Aashirvaad Atta 5kg", qty=10, idempotency_key="race-receive"
            )
            done["receive"] = True
        finally:
            conn.close()

    threads = [threading.Thread(target=sell), threading.Thread(target=receive)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert done.get("sale") and done.get("receive"), done

    check = get_connection(db_path)
    end_qty = inventory.find_product(check, "Aashirvaad Atta 5kg")["qty_on_hand"]
    check.close()
    assert end_qty == start_qty - 2 + 10  # both effects landed, neither lost
