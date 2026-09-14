import pytest

from domain import inventory
from domain.errors import AmbiguousMatchError, NotFoundError, ValidationError


def test_seed_catalog_loaded(seeded_conn):
    maggi = inventory.find_product(seeded_conn, "Maggi")
    assert maggi["gst_rate"] == 5
    surf = inventory.find_product(seeded_conn, "Surf Excel")
    assert surf["gst_rate"] == 18  # detergent did not move in GST 2.0
    salt = inventory.find_product(seeded_conn, "Tata Salt")
    assert salt["gst_rate"] == 0


def test_find_product_ambiguous_raises_with_candidates(seeded_conn):
    with pytest.raises(AmbiguousMatchError) as exc_info:
        inventory.find_product(seeded_conn, "atta")  # matches Loose Atta and Aashirvaad Atta 5kg
    assert len(exc_info.value.candidates) >= 2


def test_find_product_not_found(seeded_conn):
    with pytest.raises(NotFoundError):
        inventory.find_product(seeded_conn, "quinoa")


def test_receive_stock_increments_and_can_update_cost(seeded_conn):
    before = inventory.find_product(seeded_conn, "Maggi")
    after = inventory.receive_stock(seeded_conn, product_ref=before["id"], qty=50, cost_price=12, mrp=14)
    assert after["qty_on_hand"] == before["qty_on_hand"] + 50
    assert after["cost_price"] == 12


def test_adjust_stock_requires_reason(seeded_conn):
    product = inventory.find_product(seeded_conn, "Maggi")
    with pytest.raises(ValidationError):
        inventory.adjust_stock(seeded_conn, product_id=product["id"], delta=-1, reason="")


def test_adjust_stock_cannot_go_negative(seeded_conn):
    product = inventory.find_product(seeded_conn, "Maggi")
    with pytest.raises(ValidationError):
        inventory.adjust_stock(
            seeded_conn, product_id=product["id"], delta=-(product["qty_on_hand"] + 1), reason="breakage"
        )


def test_adjust_stock_applies_valid_correction(seeded_conn):
    product = inventory.find_product(seeded_conn, "Maggi")
    result = inventory.adjust_stock(seeded_conn, product_id=product["id"], delta=-1, reason="damaged packet")
    assert result["qty_on_hand"] == product["qty_on_hand"] - 1


def test_add_product_rejects_unknown_gst_slab(seeded_conn):
    with pytest.raises(ValidationError):
        inventory.add_product(
            seeded_conn, name="Weird Item", unit="piece", is_loose=False, hsn_code="9999",
            gst_rate=12, cost_price=10, mrp=15,
        )


def test_add_product_rejects_duplicate(seeded_conn):
    with pytest.raises(ValidationError):
        inventory.add_product(
            seeded_conn, name="Maggi 70g", unit="packet", is_loose=False, hsn_code="1902",
            gst_rate=5, cost_price=11, mrp=14,
        )


def test_low_stock_and_reorder_suggestions(seeded_conn):
    # Maggi seeded at qty 6 with reorder_level 20 -- already below reorder.
    low = inventory.list_low_stock(seeded_conn)
    names = {p["name"] for p in low}
    assert "Maggi 70g" in names

    suggestions = inventory.get_reorder_suggestions(seeded_conn)
    names = {s["name"] for s in suggestions}
    assert "Maggi 70g" in names
