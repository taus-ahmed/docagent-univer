"""Real-world template-layout audit (offline; no model or hosted service).

Every scenario is a real XLSX fixture.  A test-only adapter exposes only the
features the production editor grid can carry, then the tests call the real
shape builder, prompt builder, mocked extraction parser, and slot writer.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

import openpyxl
import pytest
from openpyxl.utils import get_column_letter, range_boundaries

from tests.template_layout.helpers import (
    FIXTURES,
    desired_block_height,
    desired_row,
    expected_bands,
    expected_fields,
    load_truth,
    normalize_bands,
    normalize_fields,
    prompt_capture,
    scenario_ids,
    shape_for,
    shift_cell,
    write_workbook,
)


PARSE_XFAIL = {
    "F3": "F3: separator columns do not extend the text-defined used range",
    "F10": "F10: formula cells participate in label geometry",
    "T12": "T12: transposed bands require an editor declaration",
    "T14": "T14: Excel Table metadata is ignored and ten rows are invented",
    "T18": "T18: only the first worksheet enters the template grid",
}


WRITE_XFAIL = {
    "F3": "F3: values are written in adjacent cells instead of separated slots",
    "F9": "F9: number formats and dropdown validation are not in the grid contract",
    "F10": "F10: formula geometry creates wrong slots and misses intended values",
    "F12": "F12: hidden rows and columns are not preserved",
    "T12": "T12: an undeclared transposed table is written as scalar fields",
    "T14": "T14: the Excel Table object is not recreated",
    "T18": "T18: secondary worksheets are not written",
}


@pytest.mark.xfail(
    strict=True,
    reason=("F2: true label-above/value-below intent needs an explicit "
            "'value below' setting in the editor"),
)
def test_f2_true_label_above_needs_an_explicit_editor_setting():
    grid, _shape = shape_for("F2")
    # Conceptual future declaration: production deliberately ignores unknown
    # keys today and keeps the usable right-hand cells, exactly as F4 does.
    grid["valueDirections"] = {"A1": "below", "C1": "below"}
    from template_shape import compute_shape
    shape = compute_shape(grid, log=lambda _m: None)
    assert normalize_fields(shape) == [
        {"label": "Invoice Date", "cell": "A2"},
        {"label": "Approval Code", "cell": "C2"},
    ]


DECLARED_TABLE_INTENT = {
    "T6": {
        "fields": [],
        "bands": [("left", 2), ("right", 2)],
    },
    "T10": {
        "fields": [("Total direct", "B5"), ("Total after blank", "B11"),
                   ("Total right", "F14"), ("Total above", "B18")],
        "bands": [("table_1", 2), ("table_2", 2),
                  ("table_3", 2), ("table_4", 2)],
    },
    "T15": {
        "fields": [("Owner", "F2"), ("Reviewed", "F3")],
        "bands": [("table", 3)],
    },
}


@pytest.mark.parametrize(
    "scenario",
    [pytest.param(s, id=s, marks=pytest.mark.xfail(
        strict=True, reason=f"{s}: needs declared tables"))
     for s in DECLARED_TABLE_INTENT],
)
def test_owner_table_intent_needs_declared_tables(scenario):
    _grid, shape = shape_for(scenario)
    want = DECLARED_TABLE_INTENT[scenario]
    got_fields = sorted((f["label"], f["cell"]) for f in normalize_fields(shape))
    got_bands = [(b["name"], b["reserved_rows"]) for b in normalize_bands(shape)]
    assert got_fields == sorted(want["fields"])
    assert got_bands == want["bands"]


def _params(xfails):
    params = []
    for scenario in scenario_ids():
        marks = []
        if scenario in xfails:
            marks.append(pytest.mark.xfail(strict=True, reason=xfails[scenario]))
        params.append(pytest.param(scenario, id=scenario, marks=marks))
    return params


@pytest.mark.parametrize("scenario", _params(PARSE_XFAIL))
def test_scenario_slot_map_matches_hand_written_truth(scenario):
    truth = load_truth(scenario)
    _grid, shape = shape_for(scenario)
    assert normalize_fields(shape) == expected_fields(truth)
    assert normalize_bands(shape) == expected_bands(truth)
    # The production grid is singular. A workbook truth with more sheets must
    # fail rather than quietly proving only its first sheet.
    assert len(truth["sheets"]) == 1
    field_pairs = {(f["label"], f["cell"]) for f in expected_fields(truth)}
    for b in truth.get("bands") or []:
        for total in b.get("totals_cells") or []:
            assert (total["label"], total["cell"]) in field_pairs


def _expected_field_value(f, doc_number):
    if f.get("empty"):
        return None
    value = f.get("value", f"D{doc_number}:{f['cell']}")
    if value == "$1,234.50":
        return 1234.5
    if value == "11/19/2026":
        return datetime(2026, 11, 19)
    if value == "12.5%":
        return 0.125
    return value


def _doc_counts(truth, doc_index, override):
    if override is not None:
        return [int(override) for _ in truth.get("bands") or []]
    explicit = (truth.get("write") or {}).get("document_row_counts")
    if explicit:
        return [int(explicit[doc_index]) for _ in truth.get("bands") or []]
    return [int(b.get("write_rows", b["reserved_rows"])) for b in truth.get("bands") or []]


def _assert_labels_and_fields(out_ws, truth, doc_index, doc_offset, override):
    first = truth["sheets"][0]
    for f in truth.get("fields") or []:
        if f.get("sheet", first) != first:
            continue
        label_ref = shift_cell(f["label_cell"], truth, doc_index, override, doc_offset)
        value_ref = shift_cell(f["cell"], truth, doc_index, override, doc_offset)
        assert out_ws[label_ref].value == f["label"]
        got = out_ws[value_ref].value
        expected = _expected_field_value(f, doc_index + 1)
        if isinstance(expected, datetime):
            assert isinstance(got, datetime) and got.date() == expected.date()
        else:
            assert got == expected


def _assert_band_values(out_ws, truth, doc_index, doc_offset, override):
    first = truth["sheets"][0]
    bands = [b for b in truth.get("bands") or [] if b.get("sheet", first) == first]
    counts = _doc_counts(truth, doc_index, override)
    omitted = set((truth.get("write") or {}).get("model_omit_columns") or [])
    for bi, b in enumerate(bands):
        count = counts[bi]
        start_col = openpyxl.utils.column_index_from_string(b["start_col"])
        header_row = desired_row(b["header_row"], truth, doc_index, override) + doc_offset
        if b.get("orientation") == "columns":
            for ri, heading in enumerate(b["columns"]):
                assert out_ws.cell(row=b["first_data_row"] + ri + doc_offset,
                                   column=start_col).value == heading
            for rec in range(count):
                for ci, _heading in enumerate(b["columns"]):
                    expected = (None if rec == count - 1 and ci == len(b["columns"]) - 1
                                else f"D{doc_index+1}:T{bi+1}:R{rec+1}:C{ci+1}")
                    assert out_ws.cell(row=b["first_data_row"] + ci + doc_offset,
                                       column=start_col + 1 + rec).value == expected
            continue
        header_cells = b.get("header_cells") or []
        for ci, heading in enumerate(b["columns"]):
            if header_cells:
                ref = shift_cell(header_cells[ci], truth, doc_index, override, doc_offset)
                assert out_ws[ref].value == heading
            else:
                assert out_ws.cell(row=header_row, column=start_col + ci).value == heading
        # The band's own growth starts immediately below its header.  Applying
        # its delta to first_data_row would incorrectly move a zero-reserved
        # header-only band below the rows it just created.
        first_row = header_row + 1
        interior_rows = {
            desired_row(int(re.search(r"\d+", item["label_cell"]).group()),
                        truth, doc_index, override) + doc_offset
            for item in b.get("interior_rows") or []
        }
        record_rows = []
        row = first_row
        while len(record_rows) < count:
            if row not in interior_rows:
                record_rows.append(row)
            row += 1
        for ri, record_row in enumerate(record_rows):
            for ci, heading in enumerate(b["columns"]):
                if heading in omitted:
                    expected = None
                else:
                    expected = (None if ri == count - 1 and ci == len(b["columns"]) - 1
                                else f"D{doc_index+1}:T{bi+1}:R{ri+1}:C{ci+1}")
                assert out_ws.cell(row=record_row, column=start_col + ci).value == expected


def _shift_range(ref, truth, doc_index, override, doc_offset):
    min_col, min_row, max_col, max_row = range_boundaries(ref)
    new_min = desired_row(min_row, truth, doc_index, override) + doc_offset
    new_max = desired_row(max_row, truth, doc_index, override) + doc_offset
    return f"{get_column_letter(min_col)}{new_min}:{get_column_letter(max_col)}{new_max}"


def _assert_formulas_and_native(out_wb, truth, doc_index, doc_offset, override):
    ws = out_wb[truth["sheets"][0]]
    for item in truth.get("formulas") or []:
        ref = shift_cell(item["cell"], truth, doc_index, override, doc_offset)
        assert ws[ref].value == item["formula"]

    native = truth.get("native_features") or {}
    merged = {str(r) for r in ws.merged_cells.ranges}
    for ref in native.get("merged_ranges") or []:
        assert _shift_range(ref, truth, doc_index, override, doc_offset) in merged
    for ref in native.get("bordered_ranges") or []:
        min_col, min_row, max_col, max_row = range_boundaries(
            _shift_range(ref, truth, doc_index, override, doc_offset))
        for row in range(min_row, max_row + 1):
            for col in range(min_col, max_col + 1):
                cell = ws.cell(row=row, column=col)
                assert any(getattr(cell.border, edge).style
                           for edge in ("left", "right", "top", "bottom"))
    for ref, fmt in (native.get("number_formats") or {}).items():
        shifted = shift_cell(ref, truth, doc_index, override, doc_offset)
        assert ws[shifted].number_format == fmt
    validations = " ".join(str(dv.sqref) for dv in ws.data_validations.dataValidation)
    for ref in native.get("validations") or []:
        shifted = shift_cell(ref, truth, doc_index, override, doc_offset)
        assert shifted in validations
    for table in native.get("tables") or []:
        assert table["name"] in ws.tables
        assert ws.tables[table["name"]].ref == _shift_range(
            table["ref"], truth, doc_index, override, doc_offset)
    for row in native.get("hidden_rows") or []:
        shifted = desired_row(row, truth, doc_index, override) + doc_offset
        assert ws.row_dimensions[shifted].hidden is True
    for col in native.get("hidden_columns") or []:
        assert ws.column_dimensions[col].hidden is True


def _check_written_scenario(scenario, tmp_path, override=None):
    target = tmp_path / f"{scenario}-{override if override is not None else 'default'}.xlsx"
    truth, _shape = write_workbook(scenario, target, row_override=override)
    out = openpyxl.load_workbook(target, data_only=False)
    assert out.sheetnames == truth["sheets"]
    source = openpyxl.load_workbook(FIXTURES / f"{scenario}.xlsx", data_only=False)
    source_ws = source[truth["sheets"][0]]
    docs = int((truth.get("write") or {}).get("documents", 1))
    doc_offset = 0
    for di in range(docs):
        doc_override = override
        counts = (truth.get("write") or {}).get("document_row_counts")
        if counts and override is None:
            doc_override = counts[di]
        _assert_labels_and_fields(out[truth["sheets"][0]], truth, di, doc_offset, doc_override)
        _assert_band_values(out[truth["sheets"][0]], truth, di, doc_offset, doc_override)
        _assert_formulas_and_native(out, truth, di, doc_offset, doc_override)
        doc_offset += desired_block_height(source_ws, truth, di, doc_override) + 3


@pytest.mark.parametrize("scenario", _params(WRITE_XFAIL))
def test_mocked_model_answers_round_trip_through_real_writer(scenario, tmp_path):
    truth = load_truth(scenario)
    variants = (truth.get("write") or {}).get("row_variants") or [None]
    for variant in variants:
        _check_written_scenario(scenario, tmp_path, variant)


def test_prompt_slot_descriptions_match_committed_capture():
    captured = json.loads((FIXTURES / "prompt_capture.json").read_text(encoding="utf-8"))
    assert set(captured) == set(scenario_ids())
    for scenario in scenario_ids():
        truth = load_truth(scenario)
        assert captured[scenario]["slot_descriptions"] == prompt_capture(scenario)
        assert captured[scenario]["ambiguities"] == truth.get("prompt_ambiguities", [])


def test_duplicate_scalar_labels_are_reported_as_ambiguous():
    for scenario in scenario_ids():
        _grid, shape = shape_for(scenario)
        labels = [f.get("row_label", "") for f in shape.get("field_slots") or []]
        duplicates = {label for label in labels if labels.count(label) > 1}
        if duplicates and all(not f.get("section") for f in shape.get("field_slots") or []
                              if f.get("row_label") in duplicates):
            assert load_truth(scenario).get("prompt_ambiguities"), scenario
