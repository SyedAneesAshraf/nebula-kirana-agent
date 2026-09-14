import pytest

from domain import khata
from domain.errors import AmbiguousMatchError, NotFoundError, ValidationError


def test_charge_and_balance(seeded_conn):
    conn = seeded_conn
    khata.charge_to_credit(conn, customer_ref="Ramesh", amount=500)
    balance = khata.get_khata_balance(conn, "Ramesh")
    assert balance["balance"] == 500


def test_full_khata_cycle_matches_brief_example(seeded_conn):
    conn = seeded_conn
    khata.charge_to_credit(conn, customer_ref="Ramesh", amount=500)
    khata.record_khata_payment(conn, customer_ref="Ramesh", amount=300, mode="cash")
    balance = khata.get_khata_balance(conn, "Ramesh")
    assert balance["balance"] == 200


def test_cannot_charge_an_unknown_customer(seeded_conn):
    conn = seeded_conn
    with pytest.raises(NotFoundError):
        khata.charge_to_credit(conn, customer_ref="Suresh", amount=100)


def test_cannot_settle_an_unknown_customer(seeded_conn):
    conn = seeded_conn
    with pytest.raises(NotFoundError):
        khata.record_khata_payment(conn, customer_ref="Suresh", amount=50, mode="cash")


def test_overpayment_is_flagged_not_silently_allowed(seeded_conn):
    conn = seeded_conn
    khata.charge_to_credit(conn, customer_ref="Ramesh", amount=100)
    result = khata.record_khata_payment(conn, customer_ref="Ramesh", amount=300, mode="upi")
    assert result["balance"] == -200
    assert "note" in result  # surfaced back to the model, not silently accepted


def test_invalid_payment_mode_rejected(seeded_conn):
    conn = seeded_conn
    khata.charge_to_credit(conn, customer_ref="Ramesh", amount=100)
    with pytest.raises(ValidationError):
        khata.record_khata_payment(conn, customer_ref="Ramesh", amount=50, mode="bitcoin")


def test_ambiguous_customer_name_surfaces_candidates_not_a_guess(conn):
    khata.add_customer(conn, "Ramesh Kumar")
    khata.add_customer(conn, "Ramesh Yadav")
    with pytest.raises(AmbiguousMatchError) as exc_info:
        khata.find_customer(conn, "Ramesh")
    assert len(exc_info.value.candidates) == 2
