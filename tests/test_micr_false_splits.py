"""A MICR-SHAPED line is not a cheque (Run 15, item 9).

The cheque segmenter is registered for ANY family, because a no-template
upload has no family when it is split. Its signal — a band naming a
different cheque from every band carried — was read off any line shaped
like `#123456789# 123456789012`, and invoices, payslips, receipts and bank
statements print reference lines of exactly that shape (a payment reference,
a sort code and account, a remittance line). Two pages of ONE invoice whose
reference lines differ were cut into two documents, and the second was asked
for the whole template.

A band now counts as a cheque boundary only with genuine MICR evidence (a
MICR glyph or its ASCII stand-in as the sentinel, or a routing number that
passes the ABA checksum) AND a cheque context on the same page ("pay to the
order of", "dollars", "memo", ...). For a KNOWN non-cheque family the cheque
segmenter does not run at all. The cheque fixtures still split exactly as
before (tests/test_multi_cheque.py).
"""
from __future__ import annotations

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from doc_boundaries import find_starts  # noqa: E402

REF_A = "#123456789# 123456789012"
REF_B = "#987654321# 210987654321"

FAMILIES = {
    "invoice": ("INVOICE\nInvoice No: INV-2024-0099\nBill To: Acme Ltd\n"
                "Item Qty Amount\nWidgets 4 $40.00\nPayment reference:\n{ref}"),
    "payslip": ("PAYSLIP\nEmployee: J. Smith  Employee ID 4471\nPay Period April 2024\n"
                "Gross Pay $4,000.00\nNet Pay $3,100.00\nPaid to account\n{ref}"),
    "receipt": ("RECEIPT\nCorner Store\nReceipt 55120\nMilk $3.20\nTotal $3.20\n"
                "Card ref\n{ref}"),
    "bank_statement": ("STATEMENT OF ACCOUNT\nAccount 0042-118\nOpening Balance $1,000.00\n"
                       "01/03 Bill Pay electric $80.00\nClosing Balance $920.00\n{ref}"),
}


#: Page 2 of the same document: no repeated title, no type change, so no
#: GENERIC candidate fires — only the cheque segmenter could cut here.
CONTINUED = "{ref}"


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_differing_reference_lines_do_not_start_a_document(family):
    page = FAMILIES[family]
    pages = [page.format(ref=REF_A), CONTINUED.format(ref=REF_B)]
    assert find_starts(pages)[0] == [0]
    assert find_starts(pages, family=family)[0] == [0]


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_an_aba_valid_band_without_a_cheque_on_the_page_does_not_split(family):
    """Real MICR glyphs and checksum-valid routing numbers, but no cheque."""
    page = FAMILIES[family]
    pages = [page.format(ref="⑆021000021⑆ 123456789012⑈"),
             CONTINUED.format(ref="⑆011000015⑆ 210987654321⑈")]
    assert find_starts(pages)[0] == [0]


def test_a_known_non_cheque_family_never_runs_the_cheque_segmenter():
    import segmenters
    assert "cheque" not in [s.name for s in segmenters.for_family("invoice")]
    assert "cheque" in [s.name for s in segmenters.for_family("cheque")]
    assert "cheque" in [s.name for s in segmenters.for_family(None)]
    assert "cheque" in [s.name for s in segmenters.for_family("other")]


def test_a_known_non_cheque_family_skips_it_even_on_real_cheques():
    a = "Golden Plains Credit Union\nPay to the order of Ann Lee\nA423511613A C559407816184C 001002D"
    b = "Rosewood Federal\nPay to the order of Bo Chan\nA316475251A C534192832764C 001003D"
    assert find_starts([a, b], family="invoice")[0] == [0]
    assert find_starts([a, b], family="cheque")[0] == [0, 1]
    assert find_starts([a, b])[0] == [0, 1]


def test_a_band_with_a_non_micr_sentinel_on_a_cheque_page_needs_the_checksum():
    """`#` is not an E-13B symbol nor a stand-in: only a checksum-valid
    routing number can make such a band count, even on a cheque page."""
    one = "Pay to the order of Ann Lee\nOne hundred DOLLARS\n{ref}"
    two = "Memo: rent\nPay to the order of Bo Chan\nTwo hundred DOLLARS\n{ref}"
    bad = [one.format(ref=REF_A), two.format(ref=REF_B)]
    assert find_starts(bad)[0] == [0]
    good = [one.format(ref="#021000021# 123456789012"),
            two.format(ref="#011000015# 210987654321")]
    assert find_starts(good)[0] == [0, 1]


def test_the_record_flag_needs_the_same_evidence():
    """`possible_multiple_documents` is not raised on an invoice either."""
    from cheque_segmenter import ChequeSegmenter
    page = FAMILIES["invoice"]
    texts = [page.format(ref=REF_A) + "\n" + REF_B]
    assert ChequeSegmenter().multiple_in_record(texts) is None
