"""GST-correct invoice PDF rendering, using reportlab (pure-Python, no
system binary dependency -- unlike a headless-browser or wkhtmltopdf
renderer, this needs nothing beyond the pip package to run on a small
container).

This module is a pure rendering function: it takes already-fetched,
plain-dict data in and writes a PDF file out, with no DB access of its own
-- tools/document_tools.py is responsible for assembling that data (bill +
per-line HSN + shop preferences + customer name) from the domain layer.

Rupee amounts are printed as "Rs." rather than the unicode Rupee sign
(U+20B9): reportlab's base-14 fonts don't cover it, and correctly rendering
it would mean bundling a TrueType font -- not worth the portability risk
for a document that must open correctly on whatever machine a reviewer has."""

import datetime
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from domain.gst import amount_in_words

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "output"


def _money(x) -> str:
    return f"Rs. {float(x):,.2f}"


def render_invoice_pdf(bill: dict, shop: dict, customer_name: Optional[str]) -> str:
    """`bill` is a billing.get_bill_summary() result whose `lines` have been
    enriched with an `hsn_code` key per line. `shop` is preferences.get_preferences()."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"invoice_{bill['id']}.pdf"

    styles = getSampleStyleSheet()
    centered_title = ParagraphStyle("CenteredTitle", parent=styles["Title"], alignment=TA_CENTER, fontSize=14)
    normal = styles["Normal"]

    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        topMargin=15 * mm, bottomMargin=15 * mm, leftMargin=15 * mm, rightMargin=15 * mm,
    )
    elements = []

    elements.append(Paragraph(shop.get("shop_name") or "Kirana Store", styles["Title"]))
    if shop.get("shop_address"):
        elements.append(Paragraph(shop["shop_address"], normal))
    if shop.get("shop_gstin"):
        elements.append(Paragraph(f"GSTIN: {shop['shop_gstin']}", normal))
    elements.append(Spacer(1, 8))
    elements.append(Paragraph("TAX INVOICE", centered_title))
    elements.append(Spacer(1, 8))

    finalized_at = (bill.get("finalized_at") or datetime.datetime.utcnow().isoformat())[:19].replace("T", " ")
    meta = Table(
        [
            ["Invoice No:", f"INV-{bill['id']:06d}", "Date:", finalized_at],
            ["Payment Mode:", (bill.get("payment_mode") or "").upper(), "Bill To:", customer_name or "Walk-in Customer"],
        ],
        colWidths=[28 * mm, 55 * mm, 22 * mm, 65 * mm],
    )
    meta.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(meta)
    elements.append(Spacer(1, 10))

    header = ["#", "Item", "HSN", "Qty", "Rate", "Taxable", "CGST", "SGST", "Total"]
    rows = [header]
    for i, line in enumerate(bill["lines"], start=1):
        half_rate = line["gst_rate_snapshot"] / 2
        rows.append([
            str(i),
            line["description_snapshot"],
            line.get("hsn_code") or "-",
            f"{line['qty']:g} {line['unit']}",
            f"{line['unit_price_snapshot']:.2f}",
            f"{line['taxable_value']:.2f}",
            f"{line['cgst_amount']:.2f}\n({half_rate:g}%)",
            f"{line['sgst_amount']:.2f}\n({half_rate:g}%)",
            f"{line['line_total']:.2f}",
        ])

    items_table = Table(rows, colWidths=[8*mm, 40*mm, 16*mm, 20*mm, 18*mm, 20*mm, 18*mm, 18*mm, 20*mm], repeatRows=1)
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2b2b2b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 10))

    summary_rows = [
        ["Taxable Subtotal", _money(bill["subtotal"])],
        ["Total CGST", _money(bill["cgst_total"])],
        ["Total SGST", _money(bill["sgst_total"])],
        ["Round Off", _money(bill["round_off"])],
        ["Grand Total", _money(bill["grand_total"])],
    ]
    summary = Table(summary_rows, colWidths=[40 * mm, 30 * mm], hAlign="RIGHT")
    summary.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.75, colors.black),
    ]))
    elements.append(summary)
    elements.append(Spacer(1, 8))
    elements.append(Paragraph(f"<i>{amount_in_words(bill['grand_total'])}</i>", normal))
    elements.append(Spacer(1, 14))

    if shop.get("invoice_footer"):
        elements.append(Paragraph(shop["invoice_footer"], normal))

    doc.build(elements)
    return str(path)
