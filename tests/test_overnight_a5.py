"""A5 — a slot whose value is printed on the page (a form title) never stays
empty and unflagged.

Job 54 (two 1099s in one job): the second block's Form Type came back empty
with no flag, while the brokerage statement prints Form 1099-DIV, 1099-MISC
and 1099-INT. Alone, the same document gave "Form 1099-DIV".
"""

from __future__ import annotations

from tests import overnight_helpers as H

BROKERAGE = "1099/irs6744_brokerage_1099DIV_MISC_INT_B.pdf"
INT_MOD3 = "1099/irs_1099int_mod3.pdf"
LABELS = ["Form Type", "Tax Year", "Payer Name", "Payer TIN", "Recipient Name",
          "Recipient TIN", "Account Number", "Box 1 Interest Income"]


def _empty_form_type(path):
    g = H.column_grid(LABELS)
    fields = {H.field_id(g, "Form Type"): H.ans("", "")}
    return H.run(path, g, {"fields": fields, "tables": {}}, doc_type="1099")[0]


def test_several_printed_titles_flag_the_empty_slot_with_evidence():
    data = _empty_form_type(BROKERAGE)
    assert H.value(data, "Form Type") == ""
    hits = [f for f in H.flags(data) if f.get("ref") == "Form Type"]
    assert hits, H.flags(data)
    why = hits[0]["reason"]
    assert "1099-DIV" in why and "1099-INT" in why, why


def test_one_printed_title_fills_the_empty_slot():
    data = _empty_form_type(INT_MOD3)
    assert H.value(data, "Form Type") == "1099-INT"
    assert "Form Type" not in H.flagged_refs(data)
