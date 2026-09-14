"""Seed catalog for local dev and demos. GST rates reflect the GST 2.0
rationalisation effective 2025-09-22 (see domain/gst.py). HSN-to-slab
mapping here is illustrative, sourced from public reporting on the reform
at plan time -- not a certified tax reference. Re-verify against the
current CBIC notification before using this for a real store."""

import sqlite3

from domain import inventory, khata, preferences

CATALOG = [
    dict(name="Loose Atta", unit="kg", is_loose=True, hsn_code="1101", gst_rate=0,
         cost_price=28, mrp=32, reorder_level=10, opening_qty=100,
         aliases="atta,wheat flour,loose atta"),
    dict(name="Loose Rice", unit="kg", is_loose=True, hsn_code="1006", gst_rate=0,
         cost_price=38, mrp=45, reorder_level=15, opening_qty=120,
         aliases="rice,chawal"),
    dict(name="Toor Dal", unit="kg", is_loose=True, hsn_code="0713", gst_rate=0,
         cost_price=110, mrp=130, reorder_level=8, opening_qty=40,
         aliases="dal,arhar dal,toor dal"),
    dict(name="Tata Salt 1kg", unit="packet", is_loose=False, hsn_code="2501", gst_rate=0,
         cost_price=18, mrp=22, reorder_level=10, opening_qty=50,
         aliases="salt,namak,tata salt"),
    dict(name="Aashirvaad Atta 5kg", unit="packet", is_loose=False, hsn_code="1101", gst_rate=5,
         cost_price=210, mrp=249, reorder_level=8, opening_qty=30,
         aliases="aashirvaad,atta 5kg,branded atta,aashirvaad atta"),
    dict(name="Amul Butter 100g", unit="packet", is_loose=False, hsn_code="0405", gst_rate=5,
         cost_price=52, mrp=62, reorder_level=10, opening_qty=40,
         aliases="butter,amul butter"),
    dict(name="Fortune Sunflower Oil 1L", unit="bottle", is_loose=False, hsn_code="1512", gst_rate=5,
         cost_price=118, mrp=139, reorder_level=10, opening_qty=35,
         aliases="oil,sunflower oil,fortune oil,fortune"),
    dict(name="Maggi 70g", unit="packet", is_loose=False, hsn_code="1902", gst_rate=5,
         cost_price=11, mrp=14, reorder_level=20, opening_qty=6,
         aliases="maggi,noodles,maggi noodles"),
    dict(name="Parle-G", unit="packet", is_loose=False, hsn_code="1905", gst_rate=5,
         cost_price=8, mrp=10, reorder_level=20, opening_qty=60,
         aliases="parle g,parle-g,biscuit,parle"),
    dict(name="Surf Excel", unit="packet", is_loose=False, hsn_code="3402", gst_rate=18,
         cost_price=45, mrp=58, reorder_level=10, opening_qty=25,
         aliases="surf,surf excel,detergent,washing powder"),
]

CUSTOMERS = [
    dict(name="Ramesh", phone="9800000001", aliases="ramesh bhai"),
]

DEFAULT_PREFS = {
    "shop_name": "Nebula Kirana Store",
    "shop_gstin": "27AAAAA0000A1Z5",
    "shop_address": "Shop No. 12, MG Road, Pune, Maharashtra - 411001",
    "invoice_footer": "Thank you for shopping with us! Visit again.",
    "default_payment_mode": "upi",
}


def seed(conn: sqlite3.Connection) -> None:
    already_seeded = conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"] > 0
    if already_seeded:
        return
    for item in CATALOG:
        inventory.add_product(conn, **item)
    for c in CUSTOMERS:
        khata.add_customer(conn, **c)
    for k, v in DEFAULT_PREFS.items():
        preferences.set_preference(conn, k, v)


if __name__ == "__main__":
    import config
    from db.connection import get_connection, init_db

    conn = get_connection(config.DB_PATH)
    init_db(conn)
    seed(conn)
    count = conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
    print(f"Seeded. {count} products in {config.DB_PATH}")
