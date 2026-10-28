"""Review-3 F2/F3: no writer rounds a number on its way into the sheet.

`coerce_cell_value` turned the shared parser's Decimal into a float, so
123456789012345.67 reached the client's file as 123456789012345.7. Excel
holds a number as a double and shows at most 15 significant digits: up to
there the float IS the printed decimal; beyond it the number is written as the
printed TEXT and the cell is flagged with a comment saying why.

Every writer that can produce a downloaded sheet is run over a fixture holding
one long number (17 significant digits) and one that just fits (15). The long
one must never appear as a number and, where the writer would otherwise write
a number, must carry the precision note; the short one must be the exact value
whenever it is written as a number.
"""
from __future__ import annotations

import contextlib
import io
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

import openpyxl  # noqa: E402

from app.services.excel_cells import (PRECISION_NOTE, coerce_cell_value,  # noqa: E402
                                      excel_number)

LONG = "123456789012345.67"         # 17 significant digits
LONG_MONEY = "$123,456,789,012,345.67"
FITS = "9876543210987.65"            # 15 significant digits


def _numbers_ok(wb):
    """No numeric cell anywhere is a rounded LONG; a numeric FITS is exact."""
    found = {"long": [], "fits": []}
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if isinstance(v, bool) or not isinstance(v, (int, float, Decimal)):
                    if isinstance(v, str) and v.strip() in (LONG, LONG_MONEY):
                        found["long"].append(c)
                    continue
                assert abs(float(v) - 123456789012345.67) > 1, \
                    (ws.title, c.coordinate, v, "a long number was rounded")
                if abs(float(v) - float(FITS)) < 1:
                    assert Decimal(repr(float(v))) == Decimal(FITS), (c.coordinate, v)
                    found["fits"].append(c)
    return found


def _flagged(cells):
    assert cells, "the long number was not written at all"
    for c in cells:
        assert c.comment is not None and PRECISION_NOTE in c.comment.text, c.coordinate


def test_the_shared_coercion_never_rounds():
    assert coerce_cell_value(LONG) == LONG
    assert coerce_cell_value(LONG_MONEY) == LONG_MONEY
    assert coerce_cell_value("1.234.567.890.123.456,78", decimal_hint=",") \
        == "1.234.567.890.123.456,78"
    assert Decimal(repr(coerce_cell_value(FITS))) == Decimal(FITS)
    assert coerce_cell_value("$1,234.56") == 1234.56
    assert excel_number(Decimal("1E+20")) == 1e20          # 1 significant digit
    assert excel_number(Decimal("12345678901234567")) is None
    assert excel_number(Decimal("NaN")) is None


# ── fixtures ─────────────────────────────────────────────────────────────────

def _result(template_type="slot"):
    fields = [("Total", "B1", LONG), ("Subtotal", "B2", FITS), ("Fee", "B3", LONG_MONEY)]
    rows = [{"Item": "a", "Amount": LONG, "_confidence": "high"},
            {"Item": "b", "Amount": FITS, "_confidence": "high"}]
    return {
        "template_type": template_type,
        "options_requested": ["graphs"],
        "extracted_fields": {ref: v for _, ref, v in fields},
        "extracted_data": {lab: {"value": v, "confidence": "high", "ref": ref}
                           for lab, ref, v in fields},
        "field_provenance": {ref: {"source": v, "page": 1, "grounded": True}
                             for _, ref, v in fields},
        "validation": {"confidence_map": {ref: "high" for _, ref, _ in fields},
                       "flagged_fields": []},
        "slot_map": {"fields": [{"ref": ref, "row_label": lab, "row": i, "col": 1}
                                for i, (lab, ref, _) in enumerate(fields)],
                     "tables": []},
        "table_rows": rows,
    }


def _doc(ed, name="D.pdf"):
    s = json.dumps(ed)
    return SimpleNamespace(filename=name, document_type="invoice", id=1,
                           overall_confidence="high", needs_review=False,
                           get_extracted_data=lambda: json.loads(s))


def _grid(extract_target=False):
    cells = {}
    for i, lab in enumerate(["Total", "Subtotal", "Fee"]):
        cells[f"{i},0"] = {"value": lab}
        cells[f"{i},1"] = {"value": "", **({"extractTarget": True} if extract_target else {})}
    return {"cells": cells, "colWidths": [], "merges": {}}


def _excel(ed, grid, regions=None):
    from app.api.routes import extract as X
    wb = openpyxl.Workbook()
    docs = [_doc(ed)]
    with contextlib.redirect_stdout(io.StringIO()):
        X._write_excel(wb.active, docs, grid, regions, openpyxl)
        X._add_review_legend(wb, docs)
    return wb


def _roundtrip(wb):
    buf = io.BytesIO()
    wb.save(buf)
    return openpyxl.load_workbook(io.BytesIO(buf.getvalue()))


# ── writers that coerce to numbers: exact, and flagged when kept as text ────

def test_slot_writer():
    wb = _roundtrip(_excel(_result("slot"), _grid()))
    found = _numbers_ok(wb)
    _flagged(found["long"])
    assert found["fits"], "the 15-digit value should be a number"


def test_inferred_sheets():
    from app.api.routes import extract as X
    ed = _result("slot")
    ed["inferred_grid"] = _grid()
    ed["shape_signature"] = "s"
    wb = openpyxl.Workbook()
    with contextlib.redirect_stdout(io.StringIO()):
        assert X._write_inferred_sheets(wb, wb.active, [_doc(ed)], openpyxl)
    found = _numbers_ok(_roundtrip(wb))
    _flagged(found["long"])


def test_charts_sheet_never_rounds_a_total():
    from app.services.excel_cells import _add_charts_sheet
    wb = openpyxl.Workbook()
    _add_charts_sheet(wb, [_doc(_result("slot"))])
    ws = wb["Charts"]
    amounts = [c for row in ws.iter_rows() for c in row if c.column == 2
               and c.value not in (None, "") and not str(c.value).startswith("Amount")]
    assert amounts
    for c in amounts:
        assert not isinstance(c.value, float) or excel_number(Decimal(repr(c.value))) is not None
    long_total = [c for c in amounts if isinstance(c.value, str)]
    assert long_total and Decimal(long_total[0].value) == Decimal(LONG) + Decimal(FITS)
    _flagged(long_total)


# ── writers that write text: the text is the printed value, unrounded ───────

def test_flat_table():
    from app.api.routes import extract as X
    wb = openpyxl.Workbook()
    X._write_flat_table(wb.active, [_doc(_result("slot"))], openpyxl)
    assert _numbers_ok(_roundtrip(wb))["long"]


@pytest.mark.parametrize("per_file", [True, False])
def test_combined_and_per_file(per_file):
    from app.api.routes.export import _build_excel
    job = SimpleNamespace(id=1, total_docs=1, successful=1, failed=0,
                          needs_review=0, total_time_sec=1.0)
    data = _build_excel(job, [_doc(_result("slot"))], None, per_file=per_file)
    assert _numbers_ok(openpyxl.load_workbook(io.BytesIO(data)))["long"]
