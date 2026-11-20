"""Run E: pins for the review fixes that the strict xfails alone do not cover.

Offline only: editor grids, stored results and synthetic page lines.
"""
from __future__ import annotations

from tests.harness import bootstrap as bs

bs.bootstrap()


def _grid(values, merges=None):
    return {"cells": {f"{r},{c}": {"value": v} for (r, c), v in values.items()},
            "merges": merges or {}, "colWidths": [], "repeatRows": []}


# ---------------------------------------------------------------------------
# E0: can the application itself write `Total | 15` as a band row above the
# Total slot? Not through extraction: `split_duplicate_totals` drops that row
# before the result is stored. Only a human edit or a job stored before Run C
# can hand the writer such a row, which is why the reader must expose it.

DUPLICATE_TOTAL_GRID = _grid({
    (0, 0): "INVOICE",
    (2, 0): "Description", (2, 1): "Amount",
    (6, 0): "Total",
})


def test_e0_extraction_drops_a_band_row_equal_to_its_total_slot():
    from slot_extractor import enumerate_slots
    from total_row_validators import split_duplicate_totals

    slots = enumerate_slots(DUPLICATE_TOTAL_GRID)
    table = slots["tables"][0]
    total_ref = next(f["ref"] for f in slots["fields"] if f["row_label"] == "Total")
    rows = [{"Description": "Widget", "Amount": "15.00"},
            {"Description": "Total", "Amount": "15.00"}]
    kept, dropped = split_duplicate_totals(
        table, rows, slots["tables"], slots["fields"], {total_ref: "15.00"})
    assert [r["Description"] for r in kept] == ["Widget"]
    assert [r["Description"] for r in dropped] == ["Total"]


def test_e0_a_disagreeing_duplicate_is_kept_and_both_are_low():
    from slot_extractor import enumerate_slots
    from total_row_validators import split_duplicate_totals, total_row_mismatch
    from validators import CheckContext

    slots = enumerate_slots(DUPLICATE_TOTAL_GRID)
    table = slots["tables"][0]
    total_ref = next(f["ref"] for f in slots["fields"] if f["row_label"] == "Total")
    rows = [{"Description": "Widget", "Amount": "15.00"},
            {"Description": "Total", "Amount": "16.00"}]
    values = {total_ref: "15.00"}
    kept, dropped = split_duplicate_totals(
        table, rows, slots["tables"], slots["fields"], values)
    assert len(kept) == 2 and dropped == []
    ctx = CheckContext(slots["fields"], values, [], tables=slots["tables"],
                       rows={table["name"]: kept})
    result = total_row_mismatch(ctx)
    assert len(result) == 1 and set(result[0].slots) == {
        total_ref, f'{table["name"]}_rows[1]'}
