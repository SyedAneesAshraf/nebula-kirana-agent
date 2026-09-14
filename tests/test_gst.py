from decimal import Decimal

from domain.gst import amount_in_words, compute_bill_totals, compute_line_tax, number_to_indian_words


def test_line_tax_splits_evenly_for_even_tax():
    # Aashirvaad Atta 5kg at MRP 249, 5% GST, qty 1
    line = compute_line_tax(249, 1, 5, price_includes_tax=True)
    assert line.line_total == Decimal("249.00")
    # taxable + cgst + sgst must reconstruct the gross exactly
    assert line.taxable_value + line.cgst_amount + line.sgst_amount == line.line_total
    assert line.cgst_amount == line.sgst_amount


def test_line_tax_reconciles_odd_paise_without_losing_a_paisa():
    # Pick a price/rate combination that produces an odd total-tax paisa,
    # forcing the cgst/sgst split to be asymmetric by exactly 0.01.
    line = compute_line_tax(58, 1, 18, price_includes_tax=True)
    assert line.taxable_value + line.cgst_amount + line.sgst_amount == line.line_total
    assert abs(line.cgst_amount - line.sgst_amount) <= Decimal("0.01")


def test_line_tax_scales_with_quantity():
    single = compute_line_tax(14, 1, 5, price_includes_tax=True)
    quad = compute_line_tax(14, 4, 5, price_includes_tax=True)
    assert quad.line_total == single.line_total * 4


def test_zero_rated_product_has_no_tax():
    line = compute_line_tax(45, 2, 0, price_includes_tax=True)
    assert line.cgst_amount == Decimal("0.00")
    assert line.sgst_amount == Decimal("0.00")
    assert line.taxable_value == line.line_total


def test_bill_totals_sum_lines_and_round_to_nearest_rupee():
    lines = [
        compute_line_tax(249, 1, 5, True),   # Aashirvaad Atta 5kg
        compute_line_tax(58, 1, 18, True),   # Surf Excel
        compute_line_tax(14, 4, 5, True),    # 4x Maggi
    ]
    totals = compute_bill_totals(lines)
    raw = sum((l.line_total for l in lines), Decimal("0"))
    # grand_total must be an integer number of rupees, off from the raw
    # (unrounded) sum by no more than 50 paise in either direction.
    assert totals.grand_total == totals.grand_total.to_integral_value()
    assert abs(totals.grand_total - raw) <= Decimal("0.5")
    assert totals.subtotal + totals.cgst_total + totals.sgst_total + totals.round_off == totals.grand_total


def test_number_to_indian_words_lakh_crore_grouping():
    assert number_to_indian_words(0) == "Zero"
    assert number_to_indian_words(7) == "Seven"
    assert number_to_indian_words(342) == "Three Hundred Forty Two"
    assert number_to_indian_words(1_240) == "One Thousand Two Hundred Forty"
    assert number_to_indian_words(1_00_000) == "One Lakh"
    assert number_to_indian_words(12_34_567) == "Twelve Lakh Thirty Four Thousand Five Hundred Sixty Seven"
    assert number_to_indian_words(1_00_00_000) == "One Crore"


def test_amount_in_words_format():
    assert amount_in_words(342) == "Rupees Three Hundred Forty Two Only"
    assert amount_in_words(Decimal("99.60")) == "Rupees One Hundred Only"  # rounds to nearest rupee
