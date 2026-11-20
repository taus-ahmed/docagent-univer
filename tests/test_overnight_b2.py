"""B2 — "sits under a different column" is decided by the value's own
position, never by words in the row.

Job 46 (mammoth_2pg): 28 red cells on correct rows. `Description` is printed
centred over x 212-278 while every description starts at x 100, so a short
one (ATM WITHDRAWAL, MOBILE DEPOSIT) overlapped no heading. Job 50
(McGuire): a name whose quote includes the neighbouring box label — pinned
here; it does not reproduce on the current pipeline. The check must still
fire when a value really sits under another column.
"""

from __future__ import annotations

from tests import overnight_helpers as H
from tests.test_overnight_a4 import MAMMOTH, mammoth_fields, mammoth_grid, mammoth_rows


def _placement_flags(data):
    return [f for f in H.flags(data) if "column" in str(f.get("reason", ""))]


def test_job46_short_descriptions_are_not_misplaced():
    g = mammoth_grid()
    name = H.table_name(g, "Transactions")
    answer = {"fields": mammoth_fields(g),
              "tables": {name: mammoth_rows(1) + mammoth_rows(2)}}
    data, _ = H.run(MAMMOTH, g, answer, doc_type="bank_statement")
    assert _placement_flags(data) == []
    rows = data[f"{name}_rows"]
    assert all(r.get("_confidence") == "high" for r in rows
               if r.get("Description") in ("ATM WITHDRAWAL", "MOBILE DEPOSIT"))


def test_a_description_written_into_the_date_column_still_fires():
    g = mammoth_grid()
    name = H.table_name(g, "Transactions")
    rows = mammoth_rows(1)
    bad = next(i for i, r in enumerate(rows)
               if r["cells"]["Description"] == "ATM WITHDRAWAL")
    cells = rows[bad]["cells"]
    cells["Date"], cells["Description"] = cells["Description"], cells["Date"]
    answer = {"fields": mammoth_fields(g), "tables": {name: rows + mammoth_rows(2)}}
    data, _ = H.run(MAMMOTH, g, answer, doc_type="bank_statement")
    refs = {f["ref"] for f in _placement_flags(data)}
    assert f"{name}[{bad}].Date" in refs or f"{name}[{bad}].Description" in refs, refs


def test_job50_a_name_beside_a_box_label_is_not_misplaced():
    from tests.contract import run_a_driver as D

    g = D.template_grid("W2_Full")
    slot = next(f for f in H.slots(g)["fields"] if f["row_label"] == "Box e Employee Name")
    for quote in ("e Employee’s first name and initial Last name Suff.Kim McGuire",
                  "Kim McGuire 13 Statutory Retirement Third-party de DD $2,500"):
        answer = {"fields": {slot["slot_id"]: H.ans("Kim McGuire", quote)}, "tables": {}}
        data, _ = H.run("w2/irs6744_w2_mcguire.pdf", g, answer, doc_type="w2")
        assert H.level(data, "Box e Employee Name") == "high", (quote, H.flags(data))
