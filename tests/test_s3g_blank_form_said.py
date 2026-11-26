"""Run S, Stage 3g — job 130 (smartsheet_mileage) "finished with no values".

Why: the file IS a blank fillable form - 268 AcroForm widgets, none filled,
no figure on either page (page 2 is the publisher's disclaimer). The engine
already decides that (Run Q, Q5): READY, every slot empty, and
`blank_form_note` "This form is blank: every slot is empty and the page
prints only its labels." But no writer showed that note, so the export was
a sheet of empty labels and a Legend saying nothing needs review - which
reads exactly like a failed extraction. The verdict is now written under the
document's block and on the Legend.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

NOTE = "This form is blank: every slot is empty and the page prints only its labels."


def _texts(wb):
    out = {}
    for ws in wb.worksheets:
        out[ws.title] = " ".join(str(c.value) for r in ws.iter_rows() for c in r
                                 if c.value is not None)
    return out


def _write(job, docs, tpl, tmp_path):
    import openpyxl
    import replay_raw
    replay_raw._setup()
    p = replay_raw.write_workbook(job, {"docs": docs, "template": tpl},
                                  tmp_path / f"job_{job}.xlsx")
    return openpyxl.load_workbook(p)


def _blank_ed():
    from shape_inference import build_grid
    inf = {"document_type": "expense_report", "title": "EXPENSE REPORT",
           "fields": ["NAME", "EMPLOYEE ID"], "totals": [], "tables": []}
    grid = build_grid(inf)
    from template_shape import compute_shape
    shape = compute_shape(grid)
    return {"template_type": "slot", "inferred_template": inf, "inferred_grid": grid,
            "shape_signature": "blank1", "extracted_fields": {},
            "slot_map": {"fields": [{"ref": f["ref"], "row_label": f["row_label"]}
                                    for f in shape["field_slots"]], "tables": []},
            "validation": {}, "blank_form": True, "blank_form_note": NOTE,
            "document_state": "READY", "attention": []}


def test_a_blank_forms_verdict_is_written_in_its_block_and_on_the_legend(tmp_path):
    from tests.harness import bootstrap as bs
    bs.bootstrap()
    wb = _write(1, [({"id": 1, "filename": "blank.pdf", "original_filename": "blank.pdf"},
                     _blank_ed(), [])], None, tmp_path)
    t = _texts(wb)
    sheet = next(k for k in t if k != "Legend")
    assert NOTE in t[sheet]
    assert NOTE in t["Legend"] and "blank.pdf" in t["Legend"]


def test_job_130_real_stored_result(tmp_path):
    d = ROOT / "local_docs" / "raw" / "130" / "docs"
    if not d.is_dir():
        pytest.skip("local_docs/raw/130 not present (git-ignored real data)")
    doc = json.loads(next(d.glob("*.json")).read_text(encoding="utf-8"))
    ed = doc["extraction_json"]
    if isinstance(ed, str):
        ed = json.loads(ed)
    assert ed.get("blank_form") is True
    wb = _write(130, [(doc, ed, [])], None, tmp_path)
    t = _texts(wb)
    assert any(NOTE in v for k, v in t.items() if k != "Legend")
    assert NOTE in t["Legend"]
