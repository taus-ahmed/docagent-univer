"""Run S, Stage 3b and 3c.

3b — jobs 61 and 65: utah_paystub_1 extracted with a Purchase Order
template, and no wrong-template warning. The type-hint rule needs two hits
for ANOTHER type; the garbled OCR layer gave payslip 1 and tax_form 1 and
purchase_order 0, so it stayed silent. The template's OWN labels are a
second, independent signal: a document that prints almost none of them is
very likely the wrong one for it (template_fit.label_mismatch). The
threshold was chosen on the corpus (tools/template_label_fit.py).

3c — job 62: utah_paystub_2 prints two columns of fields side by side,
values wrapping inside their own column ("Position/Title: Marketing
Operations" / "Specialist"). The model's value is right and was Low: the
quote is the flattened line, which interleaves the other column, so the
value is not contiguous inside it; the in-column reading (D9,
`canonical_value`) spells it exactly, but that fallback only ran when the
quote was missing from the page altogether.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from tests.harness import bootstrap as bs  # noqa: E402

bs.bootstrap()

import template_fit as TF  # noqa: E402

PO_LABELS = ["PO Number", "Order Date", "Vendor Name", "Vendor Address", "Ship To",
             "Bill To", "Payment Terms", "Item Description", "Quantity", "Unit Price",
             "Line Total", "Subtotal", "Shipping", "Grand Total"]
PAYSTUB = ("University of Georgia 424 E. Broad St. Pay Begin Date: 08/01/2018 "
           "Pay End Date: 0831/2018 Advice Date: 08/31/2018 Employee ID Department "
           "HOURS AND EARNINGS Regular 8,449.50 184.00 TAXES Fed Withholdng "
           "FedMED/EE Net Pay Federal Marital Status Allowances")
PO_TEXT = ("PURCHASE ORDER PO Number: PO-2024-0018 Order Date: 2024-03-01 Vendor: Acme "
           "Ship To: Warehouse 2 Bill To: HQ Payment Terms: Net 30 Item Description "
           "Qty Unit Price Line Total Subtotal Shipping Grand Total")


def test_label_fraction_counts_significant_words():
    # "PO Number" and "Line Total" carry no significant word (number, total
    # and two-letter words are not evidence), so 12 of the 14 labels count
    frac, n, hit = TF.label_fraction(PO_TEXT, PO_LABELS)
    assert n == 12 and frac >= 0.8


def test_a_pay_stub_under_a_purchase_order_template_is_named():
    say = TF.label_mismatch(PAYSTUB, PO_LABELS, "PO - Purchase Order Full")
    assert say and "may be the wrong template" in say
    assert TF.label_mismatch(PO_TEXT, PO_LABELS) is None


def test_too_few_labels_says_nothing():
    assert TF.label_mismatch(PAYSTUB, PO_LABELS[:3]) is None


def _replay(job):
    import replay_raw
    if not replay_raw.has_raw(job):
        pytest.skip(f"local_docs/raw/{job} not present (git-ignored real data)")
    rep = replay_raw.replay_job(job)
    if not rep["docs"]:
        pytest.skip(f"job {job}: {rep['skipped']}")
    return rep["docs"]


@pytest.mark.parametrize("job", [61, 65])
def test_real_jobs_61_and_65_get_the_wrong_template_item(job):
    ed = _replay(job)[0][1]
    texts = [a["text"] for a in ed["attention"]]
    assert any("may be the wrong template" in t or "does not look like" in t
               for t in texts), texts
    assert ed["document_state"] == "NEEDS_ATTENTION"


def test_real_corpus_no_right_template_is_called_wrong():
    """Every templated job whose template was the document's own kind: no
    wrong-template item from the label rule."""
    import replay_raw
    if not replay_raw.has_raw(40):
        pytest.skip("local_docs/raw not present (git-ignored real data)")
    # the right-template jobs that print the FEWEST of their labels are the
    # ones that matter (tools/template_label_fit.py): the outlined ADP W-2
    # (82, 2 of 30), the cafe receipt (47, 4 of 12), the Wells statement
    # (75, 8 of 23), the invoices (42, 74: 11 of 24)
    right = [40, 41, 42, 43, 44, 46, 47, 49, 52, 55, 74, 75, 82]
    hit = {}
    for job in right:
        if not replay_raw.has_raw(job):
            continue
        for _m, ed, _x in _replay(job):
            t = [a["text"] for a in ed.get("attention") or []
                 if "may be the wrong template" in a["text"]]
            if t:
                hit[job] = t
    assert hit == {}


# ── 3c ─────────────────────────────────────────────────────────────────────

def test_real_job_62_two_column_fields_are_not_low():
    docs = _replay(62)
    ed = next(e for m, e, _x in docs if m.get("original_filename") == "utah_paystub_2.pdf")
    lab = {f["ref"]: f["row_label"] for f in ed["slot_map"]["fields"]}
    cm = ed["validation"]["confidence_map"]
    got = {lab[r]: (v, cm.get(r)) for r, v in ed["extracted_fields"].items()}
    assert got["Position/Title"] == ("Marketing Operations Specialist", "unverified")
    assert got["Employee Address"][1] != "low", got["Employee Address"]


def test_a_value_wrapped_in_its_own_column_is_grounded(tmp_path):
    """Invented text; the layout of job 62 (see test_s3c_wrapped_columns.py
    for more labels and the negative cases)."""
    from tests import run_q_support as Q
    items = [(56, 760, "Employee Name: Pat Example"), (330, 760, "Employee ID: E-0001"),
             (56, 740, "Title: Senior Example"), (330, 740, "Address: 12 Example Road"),
             (86, 726, "Analyst"), (378, 726, "Sampletown, ST 00000")]
    pdf = Q.make_pdf(tmp_path / "s.pdf", [items], size=9)
    tpl = Q.template(fields=["Employee Name", "Title"], doc_type="payslip")

    def answer(prompt):
        ids = Q.slot_ids(prompt)
        return {"fields": {
            ids["Employee Name"]: {"value": "Pat Example",
                                   "source": "Employee Name: Pat Example", "page": 1},
            ids["Title"]: {
                "value": "Senior Example Analyst",
                "source": "Title: Senior Example Address: 12 Example Road Analyst",
                "page": 1}}, "tables": {}}

    ed = Q.run(pdf, tpl, answer)[0].extracted_data
    ref = next(f["ref"] for f in ed["slot_map"]["fields"] if f["row_label"] == "Title")
    assert ed["validation"]["confidence_map"][ref] != "low"
