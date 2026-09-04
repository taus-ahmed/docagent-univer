"""
The behaviours that were already CORRECT, pinned before anything else moves.

The defect analysis ends with a table of nine things the system got right, and
a warning: fixing D1/D2 touches row classification, which is exactly the logic
producing those results. This file is that table, as tests.

They are written against the CONTRACT AS IT NOW IS — after positional evidence
and after row identity became positional — not against the behaviour as it was
observed. Pinning the old behaviour would have frozen two defects in place.

Where a behaviour is the MODEL's rather than the pipeline's — refusing to
invent, matching a label across a wording change — the pipeline half is pinned
here deterministically and the model half is measured by a scenario fixture
(`tests/test_scenarios.py`), because a test that cannot fail without a network
call protects nothing in CI.
"""
import json

import pytest

from tests.harness import bootstrap as _bs

_bs.bootstrap()

from slot_extractor import run_slot_extraction  # noqa: E402
from template_shape import compute_shape  # noqa: E402
from text_layer import read_page  # noqa: E402


def _stub(payload):
    class _Resp:
        success = True
        parsed_json = payload
        raw_text = json.dumps(payload)

    class _LLM:
        def extract(self, **kw):
            return _Resp()

    return type("O", (), {"llm": _LLM()})()


def _cells(d):
    return {f"{r},{c}": {"value": v} for (r, c), v in d.items()}


def _run(grid, payload, texts, lines=None, doc_type="other"):
    shape = compute_shape(grid, log=lambda _m: None)
    return run_slot_extraction(
        _stub(payload), "DOC.pdf", {"layout": grid, "shape": shape}, None,
        page_images=[], doc_text="\n\n".join(texts), doc_text_pages=texts,
        file_type="digital_pdf", default_doc_type=doc_type, start=0.0,
        page_lines=lines)[0].extracted_data


def _sheet(grid, ed):
    import openpyxl
    from openpyxl import Workbook
    from app.api.routes.extract import _write_slot_excel

    class _Doc:
        def get_extracted_data(self):
            return ed

    ws = Workbook().active
    _write_slot_excel(ws, [_Doc()], grid, grid["cells"], openpyxl)
    return [[("" if c.value is None else c.value) for c in row]
            for row in ws.iter_rows()]


# ══════════════════════════════════════════════════════════════════════════
# 1. No unrequested content forced into a grid
# ══════════════════════════════════════════════════════════════════════════

PO_TEXT = """PURCHASE ORDER PO-2024-0018
Item / Description Qty Unit Cost Total
Steel Wire Coils Grade A 500m (SW-500A) 50 $155.00 $7,750.00
Steel Sheet 2mm 1200x2400 (SS-2MM) 30 $88.00 $2,640.00
Subtotal: $10,390.00
A neighbouring line the template did not ask for $999.99
"""

WIDE_BAND = {
    "cells": _cells({(0, 0): "Item / Description", (0, 1): "Qty",
                     (0, 2): "Unit Cost", (0, 3): "Total"}),
    "colWidths": [], "merges": {}, "repeatRows": [],
    "regions": [{"type": "table", "r1": 0, "c1": 0, "r2": 30, "c2": 3,
                 "orientation": "rows", "name": "Items"}],
}


class TestNothingIsPulledInToFillTheGrid:
    def test_a_band_with_thirty_blank_rows_writes_only_the_rows_there_are(self):
        """The template reserves 30 rows; the document has 2 line items. The
        band must not be padded from whatever is nearby to fill the space."""
        rows = [{"cells": {"Item / Description": "Steel Wire Coils Grade A 500m (SW-500A)",
                           "Qty": "50", "Unit Cost": "$155.00", "Total": "$7,750.00"},
                 "source": PO_TEXT.splitlines()[2], "page": 1},
                {"cells": {"Item / Description": "Steel Sheet 2mm 1200x2400 (SS-2MM)",
                           "Qty": "30", "Unit Cost": "$88.00", "Total": "$2,640.00"},
                 "source": PO_TEXT.splitlines()[3], "page": 1}]
        ed = _run(WIDE_BAND, {"fields": {}, "tables": {"Items": rows}}, [PO_TEXT])
        assert len(ed["Items_rows"]) == 2
        body = [r for r in _sheet(WIDE_BAND, ed)[1:] if any(str(c).strip() for c in r)]
        assert len(body) == 2, body

    def test_a_neighbouring_line_is_not_written_just_because_a_row_is_free(self):
        ed = _run(WIDE_BAND, {"fields": {}, "tables": {"Items": []}}, [PO_TEXT])
        assert ed["Items_rows"] == []
        assert "999.99" not in json.dumps(ed)


# ══════════════════════════════════════════════════════════════════════════
# 2. Multi-column placement on a declared band
# ══════════════════════════════════════════════════════════════════════════

class TestEveryValueColumnIsPopulatedInOrder:
    def test_a_row_carrying_four_values_keeps_all_four(self):
        """T5's subtotal row: the capability D3 said was being bypassed."""
        line = PO_TEXT.splitlines()[2]
        rows = [{"cells": {"Item / Description": "Steel Wire Coils Grade A 500m (SW-500A)",
                           "Qty": "50", "Unit Cost": "$155.00", "Total": "$7,750.00"},
                 "source": line, "page": 1}]
        ed = _run(WIDE_BAND, {"fields": {}, "tables": {"Items": rows}}, [PO_TEXT])
        got = ed["Items_rows"][0]
        assert [got["Qty"], got["Unit Cost"], got["Total"]] == \
               ["50", "$155.00", "$7,750.00"]

    def test_a_totals_row_with_only_the_last_column_filled_survives(self):
        """The other half of the same shape — a row that legitimately has
        three empty value columns must not be discarded as empty."""
        rows = [{"cells": {"Item / Description": "Subtotal:", "Qty": "",
                           "Unit Cost": "", "Total": "$10,390.00"},
                 "source": "Subtotal: $10,390.00", "page": 1}]
        ed = _run(WIDE_BAND, {"fields": {}, "tables": {"Items": rows}}, [PO_TEXT])
        assert len(ed["Items_rows"]) == 1
        assert ed["Items_rows"][0]["Total"] == "$10,390.00"
        assert ed["Items_rows"][0]["Qty"] == ""

    def test_the_columns_reach_the_sheet_in_template_order(self):
        rows = [{"cells": {"Item / Description": "Steel Sheet 2mm 1200x2400 (SS-2MM)",
                           "Qty": "30", "Unit Cost": "$88.00", "Total": "$2,640.00"},
                 "source": PO_TEXT.splitlines()[3], "page": 1}]
        ed = _run(WIDE_BAND, {"fields": {}, "tables": {"Items": rows}}, [PO_TEXT])
        body = [r for r in _sheet(WIDE_BAND, ed)[1:] if any(str(c).strip() for c in r)]
        assert body[0][:4] == ["Steel Sheet 2mm 1200x2400 (SS-2MM)", 30.0, 88.0, 2640.0]


# ══════════════════════════════════════════════════════════════════════════
# 3. Side-by-side key/value blocks do not contaminate each other
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def side_by_side(repo_dir):
    grid = json.loads(
        (repo_dir / "tests/fixtures/prod_templates/bs_luq.json").read_text())
    return grid.get("cells") and grid or grid.get("grid")


class TestIndependentBlocksStayIndependent:
    def test_the_shape_finds_two_label_columns_and_two_value_columns(
            self, side_by_side):
        shape = compute_shape(side_by_side, log=lambda _m: None)
        assert 0 in shape["label_columns"] and 2 in shape["label_columns"]
        assert 1 in shape["value_columns"] and 3 in shape["value_columns"]

    def test_each_label_owns_the_column_to_its_own_right(self, side_by_side):
        """The left block's answers land in B, the right block's in D. The
        failure this guards is a value crossing from one block to the other,
        which reads as perfectly plausible and is simply another company's
        number."""
        shape = compute_shape(side_by_side, log=lambda _m: None)
        for slot in shape["field_slots"]:
            col = slot["ref"][0]
            assert col in ("B", "D"), slot
            # a slot in B is owned by a label in A; a slot in D by a label in C
            assert slot["col"] in (1, 3)

    def test_answers_are_written_to_the_address_they_were_asked_for(
            self, side_by_side):
        shape = compute_shape(side_by_side, log=lambda _m: None)
        text = "\n".join(f'{s["row_label"]} {i * 1000}'
                         for i, s in enumerate(shape["field_slots"], 1))
        answers = {s["slot_id"]: {"value": str(i * 1000),
                                  "source": f'{s["row_label"]} {i * 1000}',
                                  "page": 1}
                   for i, s in enumerate(shape["field_slots"], 1)}
        ed = _run(side_by_side, {"fields": answers, "tables": {}}, [text])
        for i, s in enumerate(shape["field_slots"], 1):
            assert ed["extracted_fields"][s["ref"]] == str(i * 1000)


# ══════════════════════════════════════════════════════════════════════════
# 4. Identifiers keep their leading zeros
# ══════════════════════════════════════════════════════════════════════════

class TestIdentifiersAreNotQuantities:
    @pytest.mark.parametrize("identifier", [
        "021000021",        # ABA routing number
        "007743882201",     # account number
        "00123",            # a short padded code
    ])
    def test_a_leading_zero_survives_the_export(self, identifier):
        from app.api.routes.extract import coerce_cell_value
        assert coerce_cell_value(identifier) == identifier

    def test_a_real_quantity_is_still_a_number(self):
        from app.api.routes.extract import coerce_cell_value
        assert coerce_cell_value("40") == 40.0
        assert coerce_cell_value("$1,234.50") == 1234.5


# ══════════════════════════════════════════════════════════════════════════
# 5. Label text arrives intact
# ══════════════════════════════════════════════════════════════════════════

class TestLabelsAreNotTrimmedOrMerged:
    @pytest.mark.parametrize("label", [
        "Cheque #001831 — National Office Supplies",   # inline detail
        "1010  Product Sales",                          # a leading line number
        "Steel Wire Coils Grade A 500m (SW-500A)",      # an inline part code
        "Less: Accum. Depreciation",                    # leading qualifier
    ])
    def test_a_row_label_reaches_the_sheet_verbatim(self, label):
        text = f"{label} $1,234.00\n"
        grid = {"cells": _cells({(0, 0): "Description", (0, 1): "Amount"}),
                "colWidths": [], "merges": {}, "repeatRows": [],
                "regions": [{"type": "table", "r1": 0, "c1": 0, "r2": 10,
                             "c2": 1, "orientation": "rows", "name": "T"}]}
        rows = [{"cells": {"Description": label, "Amount": "$1,234.00"},
                 "source": text.strip(), "page": 1}]
        ed = _run(grid, {"fields": {}, "tables": {"T": rows}}, [text])
        assert ed["T_rows"][0]["Description"] == label
        body = [r for r in _sheet(grid, ed)[1:] if any(str(c).strip() for c in r)]
        assert body[0][0] == label


# ══════════════════════════════════════════════════════════════════════════
# 6. Blank spacer rows and section headings survive into the output
# ══════════════════════════════════════════════════════════════════════════

SECTIONED = {
    "cells": _cells({(0, 0): "EARNINGS",
                     (1, 0): "Basic Salary", (1, 1): "",
                     (2, 0): "Overtime", (2, 1): "",
                     # row 3 is a deliberate spacer
                     (4, 0): "DEDUCTIONS",
                     (5, 0): "Federal Tax", (5, 1): "",
                     (6, 0): "State Tax", (6, 1): ""}),
    "colWidths": [], "merges": {}, "repeatRows": [], "regions": [],
}


class TestTheSheetKeepsTheShapeTheUserDrew:
    def test_section_headings_are_written(self):
        text = ("EARNINGS\nBasic Salary $8,300.00\nOvertime $420.00\n"
                "DEDUCTIONS\nFederal Tax $1,245.00\nState Tax $515.00\n")
        shape = compute_shape(SECTIONED, log=lambda _m: None)
        answers = {}
        for s in shape["field_slots"]:
            line = next((l for l in text.splitlines()
                         if l.startswith(s["row_label"]) and "$" in l), "")
            if line:
                answers[s["slot_id"]] = {
                    "value": "$" + line.split("$")[1].strip(),
                    "source": line, "page": 1}
        ed = _run(SECTIONED, {"fields": answers, "tables": {}}, [text])
        rows = _sheet(SECTIONED, ed)
        flat = [str(c) for r in rows for c in r]
        assert "EARNINGS" in flat and "DEDUCTIONS" in flat

    def test_the_spacer_row_stays_blank(self):
        ed = _run(SECTIONED, {"fields": {}, "tables": {}}, ["nothing here\n"])
        rows = _sheet(SECTIONED, ed)
        assert not any(str(c).strip() for c in rows[3]), rows[3]

    def test_a_field_the_document_has_no_value_for_is_left_empty(self):
        """An empty cell is a real answer. Filling it from a neighbour is the
        failure the whole slot design exists to prevent."""
        ed = _run(SECTIONED, {"fields": {}, "tables": {}}, ["nothing here\n"])
        assert ed["extracted_fields"] == {}
        assert any("returned no value" in n for n in ed["validation_notes"])


# ══════════════════════════════════════════════════════════════════════════
# 7. A misplaced value is demoted, never silently corrected or deleted
# ══════════════════════════════════════════════════════════════════════════

class TestTheNewChecksDoNotEatCorrectData:
    def test_placement_passes_every_row_of_a_real_statement(self, pdf_dir,
                                                            templates_dir):
        """The whole bank statement, correctly placed, must draw no verdict.
        A placement check that fires on correct data is worse than none."""
        import pdfplumber
        with pdfplumber.open(pdf_dir / "STMT-2024-01.pdf") as pdf:
            text, lines, _ = read_page(pdf.pages[0])
        grid = json.loads((templates_dir / "bank_statement.json").read_text())
        shape = compute_shape(grid, log=lambda _m: None)
        band = shape["repeat_bands"][0]

        rows = []
        for line in text.split("\n"):
            parts = line.split()
            if len(parts) > 4 and parts[0].count("/") == 1 and parts[1].isupper():
                money = [p for p in parts if p.startswith("$")]
                if len(money) == 2:
                    debit = money[0] if parts[1] in ("ACH", "CHQ", "FEE") else ""
                    credit = money[0] if not debit else ""
                    rows.append({"cells": {
                        "Date": parts[0], "Type": parts[1],
                        "Description": " ".join(parts[2:parts.index(money[0])]),
                        "Debit": debit, "Credit": credit,
                        "Balance": money[1]}, "source": line, "page": 1})
        assert len(rows) >= 10, "fixture stopped producing rows"
        ed = _run(grid, {"fields": {}, "tables": {band["name"]: rows}},
                  [text], [lines], "bank_statement")
        assert ed["validation"]["misplaced_count"] == 0
        assert ed["validation"]["dropped_row_count"] == 0
        assert len(ed[f'{band["name"]}_rows']) == len(rows)
