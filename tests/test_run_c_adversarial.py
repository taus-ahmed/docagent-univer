"""Independent adversarial review of Run C.

No test in this file calls a model or a hosted service.  Workbook assertions
load the bytes written by the real exporter with openpyxl; the layout checks do
not use ``tests.harness.sheet_reader`` except for the one strict xfail that
demonstrates the reader's own blind spot.
"""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
from numbers import Number
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

import openpyxl  # noqa: E402


PRE_RUN_C = "56e80ca"
TEMPLATE_BOOK = (
    bs.REPO_DIR / "tests" / "fixtures" / "acceptance" / "templates"
    / "DocAgent_templates_v2.xlsx"
)


def grid_of(values, *, merges=None):
    return {
        "cells": {
            f"{row},{col}": {"value": value}
            for (row, col), value in values.items()
        },
        "colWidths": [],
        "merges": merges or {},
    }


def stored(grid, *, fields=None, rows=None, confidence=None, extra=None):
    """Build the stored slot result consumed by the production writer."""
    from slot_extractor import _table_map, enumerate_slots

    slots = enumerate_slots(grid)
    fields = fields or {}
    rows = rows or {}
    confidence = confidence or {}
    extracted, provenance, confidence_map = {}, {}, {}
    for field in slots["fields"]:
        label = field["row_label"]
        if label not in fields:
            continue
        value = fields[label]
        ref = field["ref"]
        extracted[ref] = value
        provenance[ref] = {
            "source": f"{label} {value}",
            "page": 1,
            "grounded": True,
        }
        confidence_map[ref] = confidence.get(label, "high")

    result = {
        "template_type": "slot",
        "extracted_fields": extracted,
        "field_provenance": provenance,
        "validation": {"confidence_map": confidence_map, "flagged_fields": []},
        "slot_map": {
            "fields": [
                {
                    key: field[key]
                    for key in ("slot_id", "ref", "row_label", "section")
                }
                for field in slots["fields"]
            ],
            "tables": [_table_map(table) for table in slots["tables"]],
        },
        "table_rows": [],
    }
    for table in slots["tables"]:
        key = "table_rows" if table["name"] == "table" else f"{table['name']}_rows"
        records = []
        for raw in rows.get(table["name"], []):
            record = dict(raw)
            record.setdefault("_confidence", "high")
            record.setdefault(
                "_source",
                " ".join(str(value) for key, value in raw.items()
                         if not str(key).startswith("_")),
            )
            record.setdefault("_page", 1)
            records.append(record)
        result[key] = records
    result.update(extra or {})
    return result, slots


def document(result, filename="input.pdf"):
    payload = json.dumps(result, default=str)
    return SimpleNamespace(
        id=1,
        filename=filename,
        document_type="test",
        overall_confidence="high",
        needs_review=False,
        get_extracted_data=lambda: json.loads(payload),
    )


def workbook_bytes(docs, grid, *, audit=False):
    from app.api.routes.extract import _add_review_legend, _write_excel

    workbook = openpyxl.Workbook()
    workbook.active.title = "Results"
    with contextlib.redirect_stdout(io.StringIO()):
        _write_excel(
            workbook.active,
            docs,
            grid,
            None,
            openpyxl,
            provenance=True,
            marks=True,
            audit=audit,
        )
        _add_review_legend(workbook, docs)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def round_trip(docs, grid, *, audit=False):
    return openpyxl.load_workbook(io.BytesIO(workbook_bytes(docs, grid, audit=audit)))


def _logical_signature(workbook):
    """Workbook content/style signature excluding ZIP and core timestamps."""
    sheets = []
    for sheet in workbook.worksheets:
        cells = []
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value is None and not cell.has_style and cell.comment is None:
                    continue
                cells.append((
                    cell.coordinate,
                    cell.value,
                    cell.data_type,
                    cell.number_format,
                    cell.fill.fill_type,
                    cell.fill.fgColor.type,
                    cell.fill.fgColor.rgb,
                    cell.font.bold,
                    cell.border.top.style,
                    cell.border.bottom.style,
                    cell.comment.text if cell.comment else None,
                ))
        sheets.append((
            sheet.title,
            tuple(sorted(str(item) for item in sheet.merged_cells.ranges)),
            tuple(cells),
        ))
    return tuple(sheets)


# ---------------------------------------------------------------------------
# C1: direct openpyxl inspection, independent of sheet_reader


LAYOUT_GRID = grid_of({
    (0, 0): "REPORT",
    (1, 0): "Report ID",
    (3, 0): "Item",
    (3, 1): "Amount",
    # Rows 4..9 are the reserved band body.
    (10, 0): "Total",
    # Row 11 is an intentional blank immediately after the band/totals.
    (12, 0): "Note",
})


def layout_result(count, *, low_row=False):
    from slot_extractor import enumerate_slots

    table = enumerate_slots(LAYOUT_GRID)["tables"][0]["name"]
    records = [
        {"Item": f"row-{index + 1}", "Amount": f"{index + 1}.00"}
        for index in range(count)
    ]
    if records and low_row:
        records[-1]["_confidence"] = "low"
        records[-1]["_source"] = f"low source row-{count} {count}.00"
    result, _ = stored(
        LAYOUT_GRID,
        fields={"Report ID": "R-001", "Total": f"{count}.00", "Note": "kept"},
        rows={table: records},
        confidence={"Total": "low"},
    )
    return result


@pytest.mark.parametrize("count", [0, 1, 30, 300])
def test_c1_direct_openpyxl_sees_actual_rows_total_blank_and_border(count):
    """The compacted rows are in the XLSX, not manufactured by the reader."""
    result = layout_result(count, low_row=True)
    sheet = round_trip([document(result)], LAYOUT_GRID)["Results"]

    header = next(cell.row for cell in sheet["A"] if cell.value == "Item")
    total = next(cell.row for cell in sheet["A"] if cell.value == "Total")
    note = next(cell.row for cell in sheet["A"] if cell.value == "Note")
    body = [
        sheet.cell(header + 1 + index, 1).value
        for index in range(count)
    ]
    assert body == [f"row-{index + 1}" for index in range(count)]
    assert total == header + 1 + count
    assert sheet.cell(total, 2).value == float(count)
    assert all(sheet.cell(total + 1, col).value is None
               for col in range(1, sheet.max_column + 1))
    assert note == total + 2 and sheet.cell(note, 2).value == "kept"
    assert sheet.cell(note, 1).border.bottom.style == "thick"
    assert sheet.cell(note, 2).border.bottom.style == "thick"

    total_cell = sheet.cell(total, 2)
    assert total_cell.fill.fgColor.rgb == "FFFFC7CE"
    assert total_cell.comment and "Total" in total_cell.comment.text
    if count:
        moved = sheet.cell(header + count, 2)
        assert moved.fill.fgColor.rgb == "FFFFC7CE"
        assert moved.comment and f"row-{count}" in moved.comment.text


def test_c1_two_different_documents_and_three_documents_have_exact_gaps():
    for counts in ([1, 30], [0, 1, 30]):
        docs = [
            document(layout_result(count), f"doc-{index}-{count}.pdf")
            for index, count in enumerate(counts, 1)
        ]
        sheet = round_trip(docs, LAYOUT_GRID)["Results"]
        starts = [cell.row for cell in sheet["A"] if cell.value == "REPORT"]
        assert len(starts) == len(counts)
        for index, (start, count) in enumerate(zip(starts, counts)):
            header = start + 3
            total = header + 1 + count
            end = total + 2
            assert sheet.cell(total, 1).value == "Total"
            assert sheet.cell(total + 1, 1).value is None
            assert sheet.cell(end, 1).value == "Note"
            assert sheet.cell(end, 1).border.bottom.style == "thick"
            if index + 1 < len(starts):
                assert starts[index + 1] == end + 4
                assert all(
                    sheet.cell(row, col).value is None
                    for row in range(end + 1, starts[index + 1])
                    for col in range(1, sheet.max_column + 1)
                )


BOTTOM_BAND = grid_of({
    (0, 0): "BOTTOM BAND",
    # Row 1 is a template-authored blank before the bottom band.
    (2, 0): "Code",
    (2, 1): "Description",
    (2, 2): "Amount",
})


@pytest.mark.parametrize("count", [0, 1, 30, 300])
def test_c1_band_at_the_bottom_uses_only_its_actual_row_count(count):
    from slot_extractor import enumerate_slots

    table = enumerate_slots(BOTTOM_BAND)["tables"][0]["name"]
    rows = [
        {"Code": f"C{index}", "Description": f"item {index}", "Amount": "1.00"}
        for index in range(count)
    ]
    result, _ = stored(BOTTOM_BAND, rows={table: rows})
    sheet = round_trip([document(result)], BOTTOM_BAND)["Results"]
    assert sheet["A1"].value == "BOTTOM BAND"
    assert sheet["A2"].value is None
    assert sheet["A3"].value == "Code"
    assert [sheet.cell(4 + index, 1).value for index in range(count)] == [
        f"C{index}" for index in range(count)
    ]
    last = 3 + count
    assert sheet.cell(last, 1).border.bottom.style == "thick"
    assert sheet.max_row == last


BLANK_AFTER_DECLARED_BAND = grid_of({
    (0, 0): "DECLARED BAND",
    (2, 0): "Item",
    (2, 1): "Amount",
    # The declared body ends at row 6. Row 7 is an intentional section gap.
    (8, 0): "SECTION TWO",
    (9, 0): "Approved By",
})
BLANK_AFTER_DECLARED_BAND["regions"] = [{
    "type": "table", "r1": 2, "c1": 0, "r2": 6, "c2": 1,
    "orientation": "rows", "name": "Items",
}]


@pytest.mark.parametrize("count", [0, 1, 30])
def test_c1_template_blank_immediately_after_a_band_is_preserved(count):
    rows = [{"Item": f"row-{index}", "Amount": "1.00"}
            for index in range(count)]
    result, _ = stored(
        BLANK_AFTER_DECLARED_BAND,
        fields={"Approved By": "Ada"},
        rows={"Items": rows},
    )
    sheet = round_trip([document(result)], BLANK_AFTER_DECLARED_BAND)["Results"]
    header = next(cell.row for cell in sheet["A"] if cell.value == "Item")
    second = next(cell.row for cell in sheet["A"] if cell.value == "SECTION TWO")
    assert second == header + count + 2
    assert all(sheet.cell(second - 1, col).value is None
               for col in range(1, sheet.max_column + 1))
    assert sheet.cell(second + 1, 2).value == "Ada"


def test_c1_same_input_has_a_deterministic_logical_workbook():
    docs = [document(layout_result(1), "one.pdf"),
            document(layout_result(30), "thirty.pdf")]
    first = openpyxl.load_workbook(io.BytesIO(workbook_bytes(docs, LAYOUT_GRID)))
    second = openpyxl.load_workbook(io.BytesIO(workbook_bytes(docs, LAYOUT_GRID)))
    assert _logical_signature(first) == _logical_signature(second)


MERGED_BAND = grid_of(
    {
        (0, 0): "MERGED BAND",
        (2, 0): "Item",
        (2, 1): "Amount",
        (6, 0): "Total",
    },
    # B4:C4 widens the amount entry cell in the first reserved body row.
    merges={"3,1": {"rows": 1, "cols": 2}},
)


def test_c1_merge_inside_a_band_survives_the_export():
    from slot_extractor import enumerate_slots

    table = enumerate_slots(MERGED_BAND)["tables"][0]["name"]
    result, _ = stored(
        MERGED_BAND,
        fields={"Total": "10.00"},
        rows={table: [{"Item": "Widget", "Amount": "10.00"}]},
    )
    sheet = round_trip([document(result)], MERGED_BAND)["Results"]
    assert "B4:C4" in {str(item) for item in sheet.merged_cells.ranges}


DUPLICATE_TOTAL_GRID = grid_of({
    (0, 0): "INVOICE",
    (2, 0): "Description",
    (2, 1): "Amount",
    # Rows 3..5 are reserved table rows.
    (6, 0): "Total",
})


def test_harness_reader_does_not_hide_a_duplicate_total_row():
    """Direct XLSX evidence proves the new reader can hide an export defect.

    The second band row duplicates the Total slot with the same amount.  The
    old reader kept it because it lies inside the reserved band.  The Run C
    reader mistakes it for the shifted tail, stops early, and then reads that
    duplicate as the scalar Total; a scorer sees a clean one-row table.
    """
    from slot_extractor import enumerate_slots
    from template_shape import compute_shape
    from tests.harness.sheet_reader import read_sheet

    table = enumerate_slots(DUPLICATE_TOTAL_GRID)["tables"][0]["name"]
    result, _ = stored(
        DUPLICATE_TOTAL_GRID,
        fields={"Total": "15.00"},
        rows={table: [
            {"Description": "Widget", "Amount": "15.00"},
            {"Description": "Total", "Amount": "15.00"},
        ]},
    )
    sheet = round_trip([document(result)], DUPLICATE_TOTAL_GRID)["Results"]
    direct_totals = [cell.row for cell in sheet["A"] if cell.value == "Total"]
    assert direct_totals == [5, 6], "the XLSX holds both the bad row and slot"

    old_source = subprocess.check_output(
        ["git", "show", f"{PRE_RUN_C}:tests/harness/sheet_reader.py"],
        cwd=bs.REPO_DIR,
        text=True,
    )
    old_namespace = {"__name__": "_pre_run_c_sheet_reader"}
    exec(compile(old_source, "pre_run_c_sheet_reader.py", "exec"), old_namespace)
    old_read_back = old_namespace["read_sheet"](
        sheet, compute_shape(DUPLICATE_TOTAL_GRID)
    )
    assert [row["Description"] for row in old_read_back["tables"][table]] == [
        "Widget", "Total", "Total"
    ], ("the exact pre-Run C reader reports the duplicate band row (and, "
        "conservatively, the real scalar tail too)")

    read_back = read_sheet(sheet, compute_shape(DUPLICATE_TOTAL_GRID))
    assert [row["Description"] for row in read_back["tables"][table]] == [
        "Widget", "Total"
    ]


# ---------------------------------------------------------------------------
# C2 and C3: audit columns, identifiers, and numeric values


def _all_text(sheet):
    return [str(cell.value) for row in sheet.iter_rows() for cell in row
            if cell.value not in (None, "")]


def test_c2_writer_default_and_audit_both_keep_marks_comments_and_legend():
    result = layout_result(1)
    result["attention"] = [{"id": "missing-section", "text": "section missing"}]
    docs = [document(result)]
    clean = round_trip(docs, LAYOUT_GRID, audit=False)
    audit = round_trip(docs, LAYOUT_GRID, audit=True)

    clean_text = _all_text(clean["Results"])
    audit_text = _all_text(audit["Results"])
    assert not any(text.startswith("Review status") or " · p." in text
                   or text == "Source" for text in clean_text)
    assert any(text.startswith("Review status") for text in audit_text)
    assert any(" · p." in text for text in audit_text)
    for workbook in (clean, audit):
        sheet = workbook["Results"]
        assert any(cell.fill.fgColor.rgb == "FFFFC7CE"
                   for row in sheet.iter_rows() for cell in row)
        assert any(cell.comment for row in sheet.iter_rows() for cell in row)
        assert "Legend" in workbook.sheetnames
        assert str(workbook["Legend"]["A1"].value).startswith("DRAFT")


TYPING_GRID = grid_of({
    (index, 0): label
    for index, label in enumerate([
        "ZIP Code",
        "SSN",
        "Masked SSN",
        "EIN",
        "Masked EIN",
        "Phone Number",
        "Routing Number",
        "Account Number",
        "Cheque Number",
        "Check Number",
        "Invoice Number",
        "PO Number",
        "Date",
        "Last 4",
        "Customer ID",
        "Policy ID",
        "Parentheses Negative",
        "Trailing Minus",
        "USD Amount",
        "EUR Amount",
        "Percentage",
        "Thousands",
        "Indian Grouping",
        "Zero",
    ])
})


TYPING_VALUES = {
    "ZIP Code": "02134",
    "SSN": "123-45-6789",
    "Masked SSN": "XXX-XX-1234",
    "EIN": "12-3456789",
    "Masked EIN": "XX-XXX6789",
    "Phone Number": "(602) 555-1212",
    "Routing Number": "021000021",
    "Account Number": "000123456789",
    "Cheque Number": "000123",
    "Check Number": "123456",
    "Invoice Number": "0000042",
    "PO Number": "000077",
    "Date": "01/15/2024",
    "Last 4": "0042",
    "Customer ID": "AB12C",
    "Policy ID": "123456",
    "Parentheses Negative": "(1,234.50)",
    "Trailing Minus": "1,234.50-",
    "USD Amount": "$1,234.50",
    "EUR Amount": "€1.234,56",
    "Percentage": "12.5%",
    "Thousands": "12,345.67",
    "Indian Grouping": "1,23,456.78",
    "Zero": "0",
}


@pytest.fixture(scope="module")
def typed_cells():
    result, _ = stored(TYPING_GRID, fields=TYPING_VALUES)
    sheet = round_trip([document(result)], TYPING_GRID)["Results"]
    return {
        sheet.cell(row, 1).value: sheet.cell(row, 2)
        for row in range(1, sheet.max_row + 1)
        if sheet.cell(row, 1).value
    }


@pytest.mark.parametrize("label", [
    "ZIP Code", "SSN", "Masked SSN", "EIN", "Masked EIN", "Phone Number",
    "Routing Number", "Account Number", "Cheque Number", "Check Number",
    "Invoice Number", "PO Number", "Date", "Last 4", "Customer ID", "Policy ID",
])
def test_c3_identifiers_and_dates_stay_exact_text(typed_cells, label):
    cell = typed_cells[label]
    assert cell.value == TYPING_VALUES[label]
    assert cell.data_type == "s"


@pytest.mark.parametrize("label,expected", [
    ("Parentheses Negative", -1234.5),
    ("Trailing Minus", -1234.5),
    ("USD Amount", 1234.5),
    ("EUR Amount", 1234.56),
    ("Thousands", 12345.67),
    ("Indian Grouping", 123456.78),
    ("Zero", 0.0),
])
def test_c3_amounts_are_numeric(typed_cells, label, expected):
    cell = typed_cells[label]
    assert isinstance(cell.value, Number) and cell.value == expected
    assert cell.data_type == "n"


def test_c3_percentage_is_a_number_with_a_percent_format(typed_cells):
    cell = typed_cells["Percentage"]
    assert cell.value == pytest.approx(0.125)
    assert cell.data_type == "n"
    assert "%" in cell.number_format


def test_c3_money_is_numeric_in_every_review_state():
    labels = ["High", "Grounded", "Unverified", "Low", "Edited", "Reviewed"]
    grid = grid_of({(index, 0): label for index, label in enumerate(labels)})
    result, _ = stored(
        grid,
        fields={label: "$1,234.50" for label in labels},
        confidence={
            "Grounded": "grounded",
            "Unverified": "unverified",
            "Low": "low",
            "Edited": "edited",
            "Reviewed": "low",
        },
    )
    refs = {field["row_label"]: field["ref"] for field in result["slot_map"]["fields"]}
    result["field_provenance"][refs["Edited"]]["edited"] = True
    result["field_provenance"][refs["Reviewed"]]["reviewed"] = {
        "by": "reviewer", "at": "2026-11-19T00:00:00Z"
    }
    sheet = round_trip([document(result)], grid)["Results"]
    cells = {sheet.cell(row, 1).value: sheet.cell(row, 2)
             for row in range(1, sheet.max_row + 1) if sheet.cell(row, 1).value}
    assert all(isinstance(cells[label].value, Number) for label in labels)
    assert all(cells[label].data_type == "n" for label in labels)


# ---------------------------------------------------------------------------
# C4: all committed grids, reconstructed old rule, and synthetic boundaries


def _xlsx_grid(sheet):
    cells = {
        f"{cell.row - 1},{cell.column - 1}": {"value": str(cell.value)}
        for row in sheet.iter_rows()
        for cell in row
        if cell.value is not None and str(cell.value).strip()
    }
    merges = {
        f"{merged.min_row - 1},{merged.min_col - 1}": {
            "rows": merged.max_row - merged.min_row + 1,
            "cols": merged.max_col - merged.min_col + 1,
        }
        for merged in sheet.merged_cells.ranges
    }
    return {"cells": cells, "merges": merges, "colWidths": [], "repeatRows": []}


def _all_67_grids():
    workbook = openpyxl.load_workbook(TEMPLATE_BOOK, data_only=False)
    grids = [(f"DocAgent_templates_v2.xlsx::{sheet.title}", _xlsx_grid(sheet))
             for sheet in workbook.worksheets]
    patterns = (
        "tests/gold/templates/*.json",
        "tests/gold/hand_drawn/*.json",
        "tests/fixtures/prod_templates/*.json",
        "tests/fixtures/round2_templates/*.json",
    )
    for pattern in patterns:
        for path in sorted(bs.REPO_DIR.glob(pattern)):
            raw = json.loads(path.read_text(encoding="utf-8"))
            grids.append((path.relative_to(bs.REPO_DIR).as_posix(), raw.get("grid", raw)))
    assert len(grids) == 67
    return grids


def _old_compute_shape():
    source = subprocess.check_output(
        ["git", "show", f"{PRE_RUN_C}:backend/engine/template_shape.py"],
        cwd=bs.REPO_DIR,
        text=True,
        encoding="utf-8",
    )
    namespace = {"__name__": "template_shape_pre_run_c"}
    exec(compile(source, "template_shape_pre_run_c.py", "exec"), namespace)
    return namespace["compute_shape"]


EXPECTED_C4_DIFFS = {
    "DocAgent_templates_v2.xlsx::Pay_Full": {
        "fields": {
            "B27": "Total Gross Pay",
            "B28": "YTD Gross Pay",
            "B38": "Total Taxes",
            "B56": "Total Deductions",
        },
        "ends": {
            ("Earnings", 17): (28, 25),
            ("Taxes", 30): (38, 36),
            ("After-Tax Deductions", 49): (56, 54),
        },
    },
    "DocAgent_templates_v2.xlsx::Invest_Stmt": {
        "fields": {"B38": "Total Holdings Value"},
        "ends": {("Holdings", 11): (38, 36)},
    },
    "DocAgent_templates_v2.xlsx::AP_Inv_Full": {
        "fields": {
            "B35": "Subtotal",
            "B36": "Discount",
            "B37": "Shipping or Handling",
            "B38": "Tax Total",
            "B39": "Invoice Total",
        },
        "ends": {("table", 13): (39, 33)},
    },
    "DocAgent_templates_v2.xlsx::Rcpt_SalesTicket": {
        "fields": {
            "B14": "Total Taxable",
            "B15": "Tax",
            "B16": "Non-Taxable",
            "B17": "Total",
            "B18": "Paid",
            "B19": "Balance Due",
        },
        "ends": {("table_1", 6): (19, 12)},
    },
}


def _field_map(shape):
    return {
        field["ref"]: {
            key: field.get(key)
            for key in ("ref", "row", "col", "row_label", "col_header", "section")
        }
        for field in shape.get("field_slots", [])
    }


def _table_map(shape):
    return {
        (table["name"], table["header_row"]): table
        for table in shape.get("repeat_bands", [])
    }


def test_c4_all_67_templates_have_only_the_four_exact_slot_map_differences():
    from template_shape import compute_shape

    old_compute = _old_compute_shape()
    changed = {}
    counts = {"old_fields": 0, "new_fields": 0, "old_tables": 0, "new_tables": 0}
    for name, grid in _all_67_grids():
        old, new = old_compute(grid), compute_shape(grid)
        old_fields, new_fields = _field_map(old), _field_map(new)
        old_tables, new_tables = _table_map(old), _table_map(new)
        counts["old_fields"] += len(old_fields)
        counts["new_fields"] += len(new_fields)
        counts["old_tables"] += len(old_tables)
        counts["new_tables"] += len(new_tables)

        added = {
            ref: new_fields[ref]["row_label"]
            for ref in sorted(new_fields.keys() - old_fields.keys())
        }
        removed = old_fields.keys() - new_fields.keys()
        modified_fields = {
            ref for ref in old_fields.keys() & new_fields.keys()
            if old_fields[ref] != new_fields[ref]
        }
        changed_ends = {
            key: (old_tables[key]["end_row"], new_tables[key]["end_row"])
            for key in old_tables.keys() & new_tables.keys()
            if old_tables[key] != new_tables[key]
        }
        # An end-row change is the only allowed mutation to an existing table.
        for key in changed_ends:
            old_without_end = {k: v for k, v in old_tables[key].items() if k != "end_row"}
            new_without_end = {k: v for k, v in new_tables[key].items() if k != "end_row"}
            assert old_without_end == new_without_end
        assert not removed and not modified_fields
        assert old_tables.keys() == new_tables.keys()
        if added or changed_ends:
            changed[name] = {"fields": added, "ends": changed_ends}

    assert counts == {
        "old_fields": 561,
        "new_fields": 577,
        "old_tables": 71,
        "new_tables": 71,
    }
    assert changed == EXPECTED_C4_DIFFS


def _shape_grid(rows):
    return grid_of(rows)


@pytest.mark.parametrize("name,grid,expected", [
    (
        "totals",
        _shape_grid({
            (0, 0): "Item", (0, 1): "Qty", (0, 2): "Amount",
            (4, 0): "Subtotal", (5, 0): "Total",
            (7, 0): "Prepared By",
        }),
        3,
    ),
    (
        "notes",
        _shape_grid({
            (0, 0): "Item", (0, 1): "Qty", (0, 2): "Amount",
            (4, 0): "Notes", (6, 0): "Prepared By",
        }),
        3,
    ),
    (
        "second table",
        _shape_grid({
            (0, 0): "Item", (0, 1): "Qty", (0, 2): "Amount",
            (4, 0): "Code", (4, 1): "Description", (4, 2): "Value",
            (7, 0): "Total",
        }),
        3,
    ),
    (
        "non-total text",
        _shape_grid({
            (0, 0): "Item", (0, 1): "Qty", (0, 2): "Amount",
            (4, 0): "Approved By", (6, 0): "Footer",
        }),
        3,
    ),
])
def test_c4_rule_ends_before_totals_notes_second_table_and_other_text(
        name, grid, expected):
    from template_shape import compute_shape

    shape = compute_shape(grid)
    first = min(shape["repeat_bands"], key=lambda table: table["header_row"])
    assert first["end_row"] == expected, name


def test_c4_notes_still_end_the_table_when_two_blank_rows_follow_them():
    from template_shape import compute_shape

    grid = _shape_grid({
        (0, 0): "Item", (0, 1): "Qty", (0, 2): "Amount",
        (4, 0): "Notes",
        # Rows 5 and 6 are blank before the footer.
        (7, 0): "Prepared By",
    })
    first = min(compute_shape(grid)["repeat_bands"],
                key=lambda table: table["header_row"])
    assert first["end_row"] == 3


# ---------------------------------------------------------------------------
# C6, C7, C8 adversarial checks


def _word(text, x0, top):
    return {"text": text, "x0": x0, "x1": x0 + 40, "top": top, "bottom": top + 10}


def test_c6_unique_quote_without_value_does_not_box_the_wrong_line():
    from app.api.routes.review import find_box

    lines = [
        [_word("Invoice", 10, 10), _word("total", 60, 10)],
        [_word("$123.45", 200, 40)],
    ]
    box, how = find_box(lines, "Invoice total", "$123.45", near=["Invoice total"])
    assert box == [200.0, 40.0, 240.0, 50.0]
    assert how == "value"


def _bottom_reasons(fields, values, pages=None):
    import cheque_validators as cheque
    from validators import CheckContext

    return {
        result.reason
        for result in cheque.bottom_line(CheckContext(fields, values, pages or []))
        if result.reason
    }


def test_c7_european_figure_notation_cross_checks_against_words():
    import cheque_validators as cheque
    from validators import CheckContext

    fields = [
        {"ref": "B1", "row_label": "Amount in Figures"},
        {"ref": "B2", "row_label": "Amount in Words"},
    ]
    values = {
        "B1": "1.234,56",
        "B2": "One thousand two hundred thirty-four and 56/100",
    }
    result = cheque.amount_cross_check(CheckContext(fields, values, []))
    assert len(result) == 1 and result[0].status == "pass"


@pytest.mark.xfail(
    strict=True,
    reason="C7: a legitimate non-US transit number is falsely required to be ABA",
)
def test_c7_non_us_transit_number_is_not_failed_as_an_aba_routing_number():
    fields = [{"ref": "B1", "row_label": "Transit Number"}]
    assert "routing_checksum_failed" not in _bottom_reasons(
        fields, {"B1": "12345"}
    )


@pytest.mark.xfail(
    strict=True,
    reason="C7: checksum alone accepts the all-zero value as a routing number",
)
def test_c7_nine_digits_that_are_not_a_routing_number_are_rejected():
    fields = [{"ref": "B1", "row_label": "Routing Number"}]
    assert "routing_checksum_failed" in _bottom_reasons(
        fields, {"B1": "000000000"}
    )


@pytest.mark.xfail(
    strict=True,
    reason=("C7: a routing/account swap is missed when the account number "
            "happens to pass the ABA checksum"),
)
def test_c7_checksum_valid_account_number_does_not_hide_a_swap():
    fields = [
        {"ref": "B1", "row_label": "Routing Number"},
        {"ref": "B2", "row_label": "Account Number"},
    ]
    # The MICR sentinels identify 021000021 as the transit/routing field.
    pages = ["A021000021A C011401533C 1234D"]
    swapped = {"B1": "011401533", "B2": "021000021"}
    assert "possible_swap" in _bottom_reasons(fields, swapped, pages)


def _balance(a=None, b=None):
    import balance_sheet_validators as balance
    from validators import CheckContext

    fields = [
        {"ref": "B1", "row_label": "TOTAL ASSETS"},
        {"ref": "B2", "row_label": "TOTAL LIABILITIES & EQUITY"},
    ]
    values = {}
    if a is not None:
        values["B1"] = a
    if b is not None:
        values["B2"] = b
    return balance.balance_identity(CheckContext(fields, values, []))


@pytest.mark.parametrize("assets,liabilities", [
    ("1,000.00", "1,000.01"),  # one cent: last printed place
    ("1000", "1001"),          # one whole unit: last printed place
])
def test_c8_one_printed_unit_is_treated_as_rounding(assets, liabilities):
    result = _balance(assets, liabilities)
    assert len(result) == 1 and result[0].status == "pass"


def test_c8_two_printed_units_and_a_sign_flip_fail():
    for assets, liabilities in (("1,000.00", "1,000.02"),
                                ("1000", "(1000)")):
        result = _balance(assets, liabilities)
        assert len(result) == 1
        assert result[0].status == "fail"
        assert result[0].reason == "assets_not_equal_liabilities_plus_equity"


@pytest.mark.parametrize("assets,liabilities", [
    (None, None), ("1,000", None), (None, "1,000"),
])
def test_c8_missing_totals_do_not_manufacture_an_identity_result(assets, liabilities):
    assert _balance(assets, liabilities) == []
