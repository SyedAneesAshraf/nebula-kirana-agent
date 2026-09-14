"""Daily close and range analytics. All figures are computed here from
finalized bills only -- draft/cancelled bills never contribute, so a deck
or summary can't be thrown off by an abandoned cart."""

import datetime
import sqlite3
from typing import Optional


def _today() -> str:
    return datetime.date.today().isoformat()


def get_daily_summary(conn: sqlite3.Connection, date: Optional[str] = None) -> dict:
    date = date or _today()
    bills = [dict(r) for r in conn.execute(
        "SELECT * FROM bills WHERE status = 'finalized' AND date(finalized_at) = date(?)", (date,)
    ).fetchall()]

    by_mode: dict[str, float] = {}
    for b in bills:
        by_mode[b["payment_mode"]] = by_mode.get(b["payment_mode"], 0) + b["grand_total"]

    top_items = conn.execute(
        """
        SELECT p.name, SUM(bl.qty) AS qty_sold, SUM(bl.line_total) AS revenue
        FROM bill_lines bl
        JOIN bills b ON b.id = bl.bill_id
        JOIN products p ON p.id = bl.product_id
        WHERE b.status = 'finalized' AND date(b.finalized_at) = date(?)
        GROUP BY p.id ORDER BY revenue DESC LIMIT 5
        """,
        (date,),
    ).fetchall()

    cgst = sum(b["cgst_total"] for b in bills)
    sgst = sum(b["sgst_total"] for b in bills)

    return {
        "date": date,
        "bill_count": len(bills),
        "total_sales": round(sum(b["grand_total"] for b in bills), 2),
        "cgst_collected": round(cgst, 2),
        "sgst_collected": round(sgst, 2),
        "tax_collected": round(cgst + sgst, 2),
        "payment_mode_split": {k: round(v, 2) for k, v in by_mode.items()},
        "top_items": [dict(r) for r in top_items],
        "is_closed": is_day_closed(conn, date),
    }


def close_day(conn: sqlite3.Connection, date: Optional[str] = None) -> dict:
    date = date or _today()
    summary = get_daily_summary(conn, date)
    conn.execute(
        "INSERT OR REPLACE INTO preferences (key, value) VALUES (?, '1')", (f"day_closed:{date}",)
    )
    summary["is_closed"] = True
    return summary


def is_day_closed(conn: sqlite3.Connection, date: str) -> bool:
    row = conn.execute("SELECT value FROM preferences WHERE key = ?", (f"day_closed:{date}",)).fetchone()
    return bool(row and row["value"] == "1")


def get_sales_range_summary(conn: sqlite3.Connection, start_date: str, end_date: str) -> dict:
    bills = [dict(r) for r in conn.execute(
        "SELECT * FROM bills WHERE status = 'finalized' AND date(finalized_at) BETWEEN date(?) AND date(?)",
        (start_date, end_date),
    ).fetchall()]

    by_mode: dict[str, float] = {}
    for b in bills:
        by_mode[b["payment_mode"]] = by_mode.get(b["payment_mode"], 0) + b["grand_total"]

    daily = conn.execute(
        "SELECT date(finalized_at) AS d, SUM(grand_total) AS total FROM bills "
        "WHERE status = 'finalized' AND date(finalized_at) BETWEEN date(?) AND date(?) "
        "GROUP BY d ORDER BY d",
        (start_date, end_date),
    ).fetchall()

    top_items = conn.execute(
        """
        SELECT p.name, SUM(bl.qty) AS qty_sold, SUM(bl.line_total) AS revenue
        FROM bill_lines bl
        JOIN bills b ON b.id = bl.bill_id
        JOIN products p ON p.id = bl.product_id
        WHERE b.status = 'finalized' AND date(b.finalized_at) BETWEEN date(?) AND date(?)
        GROUP BY p.id ORDER BY revenue DESC LIMIT 10
        """,
        (start_date, end_date),
    ).fetchall()

    cgst = sum(b["cgst_total"] for b in bills)
    sgst = sum(b["sgst_total"] for b in bills)

    return {
        "start_date": start_date,
        "end_date": end_date,
        "bill_count": len(bills),
        "total_sales": round(sum(b["grand_total"] for b in bills), 2),
        "tax_collected": round(cgst + sgst, 2),
        "payment_mode_split": {k: round(v, 2) for k, v in by_mode.items()},
        "daily_trend": [dict(r) for r in daily],
        "top_items": [dict(r) for r in top_items],
    }
