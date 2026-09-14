"""GST computation, kept deliberately separate from the billing lifecycle so
the tax math can be unit-tested in isolation. Slabs reflect the GST 2.0 rate
rationalisation effective 2025-09-22 (nil / 5% / 18% / 3% gold-silver / 40%
demerit) -- see README for the illustrative HSN-to-slab mapping used in seed
data. Rates live on each product row, not here; this module only computes.

All money math uses Decimal to avoid float drift on currency, and MRP is
treated as tax-inclusive (the correct convention for Indian retail: the
printed MRP already contains GST, so tax is backed out of the line total
rather than added on top of it)."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

ALLOWED_GST_RATES = (0, 3, 5, 18, 40)

TWO_PLACES = Decimal("0.01")
ONE_PLACE = Decimal("1")


def q2(x) -> Decimal:
    return Decimal(str(x)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class LineTax:
    taxable_value: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    line_total: Decimal


def compute_line_tax(unit_price, qty, gst_rate, price_includes_tax: bool = True) -> LineTax:
    unit_price = Decimal(str(unit_price))
    qty = Decimal(str(qty))
    rate = Decimal(str(gst_rate))

    gross = q2(unit_price * qty)
    if price_includes_tax:
        taxable = gross / (Decimal("1") + rate / Decimal("100"))
    else:
        taxable = gross
        gross = q2(taxable * (Decimal("1") + rate / Decimal("100")))

    tax = gross - taxable
    cgst = q2(tax / 2)
    sgst = q2(tax - cgst)  # any odd paise from the /2 split is absorbed here
    # Define taxable as the remainder so the three figures always sum to
    # exactly `gross`, regardless of rounding upstream.
    taxable_q = q2(gross - cgst - sgst)

    return LineTax(taxable_value=taxable_q, cgst_amount=cgst, sgst_amount=sgst, line_total=gross)


@dataclass(frozen=True)
class BillTotals:
    subtotal: Decimal
    cgst_total: Decimal
    sgst_total: Decimal
    round_off: Decimal
    grand_total: Decimal


def compute_bill_totals(lines: list[LineTax]) -> BillTotals:
    subtotal = sum((line.taxable_value for line in lines), Decimal("0"))
    cgst_total = sum((line.cgst_amount for line in lines), Decimal("0"))
    sgst_total = sum((line.sgst_amount for line in lines), Decimal("0"))
    raw_total = subtotal + cgst_total + sgst_total
    rounded_total = raw_total.quantize(ONE_PLACE, rounding=ROUND_HALF_UP)
    round_off = q2(rounded_total - raw_total)
    return BillTotals(
        subtotal=q2(subtotal),
        cgst_total=q2(cgst_total),
        sgst_total=q2(sgst_total),
        round_off=round_off,
        grand_total=rounded_total,
    )


_ONES = [
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen",
]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two_digit_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return (_TENS[tens] + (f" {_ONES[ones]}" if ones else "")).strip()


def _three_digit_words(n: int) -> str:
    if n >= 100:
        hundreds, rest = divmod(n, 100)
        return f"{_ONES[hundreds]} Hundred" + (f" {_two_digit_words(rest)}" if rest else "")
    return _two_digit_words(n)


def number_to_indian_words(n: int) -> str:
    """Indian numbering (lakh = 1e5, crore = 1e7), used for invoice 'amount in words'."""
    if n == 0:
        return "Zero"
    parts = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1_000)
    hundred = n
    if crore:
        parts.append(f"{_three_digit_words(crore)} Crore")
    if lakh:
        parts.append(f"{_three_digit_words(lakh)} Lakh")
    if thousand:
        parts.append(f"{_three_digit_words(thousand)} Thousand")
    if hundred:
        parts.append(_three_digit_words(hundred))
    return " ".join(parts)


def amount_in_words(rupees) -> str:
    whole = int(Decimal(str(rupees)).to_integral_value(rounding=ROUND_HALF_UP))
    return f"Rupees {number_to_indian_words(whole)} Only"
