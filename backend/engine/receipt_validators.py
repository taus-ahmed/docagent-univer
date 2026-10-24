"""Receipt-family checks, behind the validator registry (validators.py).

  receipt_lines_total   the items' amounts sum to the subtotal, within one
                        cent per line
  receipt_grand_total   subtotal + tax + tip / fees - discount equals the
                        total, within one cent

The same two sums as an invoice (invoice_validators.sum_checks), with a
receipt's own roles: a tip, gratuity or service charge is an addition; a
coupon or savings line is a discount; and what was TENDERED — cash, card,
change — is not part of the sum at all, so it never takes the total's role.
A check runs only when every value it needs was extracted, never guesses a
number from a value that is not a plain amount (UNREADABLE), and does not run
when a role is ambiguous or a gate dropped rows from the items table.

Reason codes: receipt_mismatch, receipt_unreadable (OCR-READER-SEAM-DESIGN §12).
"""
from __future__ import annotations

from invoice_validators import _NOT_AN_AMOUNT, _words, sum_checks
from validators import register

RECEIPT_MISMATCH = "receipt_mismatch"
RECEIPT_UNREADABLE = "receipt_unreadable"

_ADDITION = {"tip", "tips", "gratuity", "service", "fee", "fees", "surcharge",
             "delivery", "bag", "deposit", "shipping", "handling"}
_DISCOUNT = {"discount", "coupon", "savings", "saved", "promo", "promotion"}
#: Lines about PAYMENT, not about the sale: never part of the sum.
_TENDERED = {"tendered", "change", "cash", "card", "visa", "mastercard", "amex",
             "debit", "credit", "paid", "payment", "auth", "approved"}


def role(label):
    """'subtotal' | 'tax' | 'discount' | 'charge' | 'total' | ''."""
    w = _words(label)
    if not w or w & _NOT_AN_AMOUNT or w & _TENDERED:
        return ""
    if "subtotal" in w:
        return "subtotal"
    if w & {"tax", "vat", "gst", "hst", "pst"}:
        return "tax"
    if w & _DISCOUNT:
        return "discount"
    if w & _ADDITION:
        return "charge"
    if "total" in w or {"amount", "due"} <= w or {"balance", "due"} <= w:
        return "total"
    return ""


def receipt_totals(ctx):
    return sum_checks(ctx, kind="receipt", role_of=role,
                      mismatch=RECEIPT_MISMATCH, unreadable=RECEIPT_UNREADABLE)


register("receipt", receipt_totals)
