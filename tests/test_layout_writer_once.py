"""The legacy layout writer writes each extracted section ONCE (Part 3.2).

With no column groups (a legacy job whose template had no detected bands) the
writer places every section at the model's row numbers — and then, because no
section matched a group, wrote every one of them AGAIN in the A/B overflow
area below the template. Rows the fallback could not place (no row number or
no column) still go to the overflow, so nothing is dropped either.
"""
from collections import Counter

from tests.test_every_export_marks import _excel, _result


def _labels(wb):
    return Counter(c.value for row in wb.active.iter_rows() for c in row
                   if isinstance(c.value, str))


def _ed(sections):
    ed = _result("structural")
    ed["extracted_fields"] = {}
    ed["layout_sections"] = sections
    return ed


GRID = {"cells": {"0,0": {"value": "Assets"}, "5,0": {"value": "Liabilities"}},
        "colWidths": [], "merges": {}}


def test_each_section_row_is_written_once_without_column_groups():
    ed = _ed({
        "Assets": {"rows": [
            {"label": "Cash", "value": "100", "row": 2, "label_col": "A", "value_col": "B"},
            {"label": "Bank", "value": "200", "row": 3, "label_col": "A", "value_col": "B"}]},
        "Liabilities": {"rows": [
            {"label": "Loan", "value": "300", "row": 7, "label_col": "A", "value_col": "B"}]}})
    seen = _labels(_excel(ed, GRID))
    for lab in ("Cash", "Bank", "Loan"):
        assert seen[lab] == 1, (lab, seen[lab])


def test_a_row_the_fallback_cannot_place_still_reaches_the_overflow():
    ed = _ed({"Assets": {"rows": [
        {"label": "Cash", "value": "100", "row": 2, "label_col": "A", "value_col": "B"},
        {"label": "Goodwill", "value": "900"}]}})            # no row, no columns
    seen = _labels(_excel(ed, GRID))
    assert seen["Cash"] == 1 and seen["Goodwill"] == 1, seen


def test_an_identical_duplicate_section_is_written_once():
    rows = [{"label": "Cash", "value": "100", "row": 2, "label_col": "A", "value_col": "B"}]
    ed = _ed({"Assets": {"rows": rows}, "Assets (repeat)": {"rows": [dict(r) for r in rows]}})
    assert _labels(_excel(ed, GRID))["Cash"] == 1
