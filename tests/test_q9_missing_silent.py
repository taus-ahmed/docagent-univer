"""Run Q, Q9 — a total printed beside its label is never left empty silently.

Job 58 (tcnj_financials): "Total liabilities and owners' equity 13,060" and
"10,700" came back empty and unflagged; the same figures were placed as
Total assets, so the evidence was discarded as "already placed".
"""
from __future__ import annotations

from tests import run_q_support as Q

LABELS = ["Total assets", "Total liabilities and owners' equity", "Cash"]


def _pdf(tmp_path):
    return Q.make_pdf(tmp_path / "bs.pdf", [[
        (72, 740, "BALANCE SHEET DECEMBER 31"),
        (72, 700, "Cash 2,750"),
        (72, 680, "Total assets 13,060"),
        (72, 650, "Total liabilities and owners' equity 13,060"),
    ]])


def _answer(prompt):
    ids = Q.slot_ids(prompt)
    return {"fields": {ids["Total assets"]: {"value": "13,060", "source": "Total assets 13,060", "page": 1},
                       ids["Cash"]: {"value": "2,750", "source": "Cash 2,750", "page": 1},
                       ids["Total liabilities and owners' equity"]: {"value": "", "source": "",
                                                                     "page": 1}},
            "tables": {}}


def test_an_empty_total_whose_line_prints_a_figure_is_flagged_reconstructed(tmp_path):
    (r,) = Q.run(_pdf(tmp_path), Q.template(fields=LABELS, doc_type="balance_sheet"), _answer)
    ed = r.extracted_data
    flags = {str(f.get("ref")): str(f.get("reason", "")) for f in ed["validation"]["flagged_fields"]}
    assert "Total liabilities and owners' equity" in flags, flags
    assert "13,060" in flags["Total liabilities and owners' equity"]


def test_an_ordinary_label_is_not_charged_with_a_figure_placed_elsewhere(tmp_path):
    pdf = Q.make_pdf(tmp_path / "x.pdf", [[(72, 700, "Cash 2,750"), (72, 680, "Petty cash 2,750")]])

    def ans(prompt):
        ids = Q.slot_ids(prompt)
        return {"fields": {ids["Cash"]: {"value": "2,750", "source": "Cash 2,750", "page": 1},
                           ids["Petty cash"]: {"value": "", "source": "", "page": 1}}, "tables": {}}
    (r,) = Q.run(pdf, Q.template(fields=["Cash", "Petty cash"], doc_type="balance_sheet"), ans)
    flags = {str(f.get("ref")) for f in r.extracted_data["validation"]["flagged_fields"]}
    # unchanged behaviour for a non-total label: the equal figure counts as placed
    assert "Petty cash" not in flags
