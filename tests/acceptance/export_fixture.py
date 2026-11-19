"""Small deterministic workbook fixture for export acceptance tests."""
from __future__ import annotations

import io
import json
from types import SimpleNamespace


def grid(reserved_rows=4):
    start = 6
    end = start + reserved_rows - 1
    totals = end + 1
    cells = {
        "0,0": {"value": "ACCEPTANCE EXPORT", "style": {"bold": True, "bgColor": "#D9EAF7"}},
        "1,0": {"value": "Amount"},
        "1,1": {"value": ""},
        "2,0": {"value": "ZIP"},
        "2,1": {"value": ""},
        "3,0": {"value": "Last 4"},
        "3,1": {"value": ""},
        "5,0": {"value": "Description", "style": {"bold": True}},
        "5,1": {"value": "Line Amount", "style": {"bold": True}},
        f"{totals},0": {"value": "Subtotal"},
        f"{totals},1": {"value": ""},
        f"{totals + 1},0": {"value": "Tax"},
        f"{totals + 1},1": {"value": ""},
        f"{totals + 2},0": {"value": "Total"},
        f"{totals + 2},1": {"value": ""},
        f"{totals + 4},0": {"value": "Template-kept blank row follows"},
    }
    return {
        "cells": cells,
        "colWidths": [],
        "merges": {},
        "regions": [{
            "type": "table",
            "name": "Items",
            "orientation": "rows",
            "r1": start,
            "c1": 0,
            "r2": end,
            "c2": 1,
        }],
    }


def extracted(rows=None, state="READY"):
    rows = rows if rows is not None else [
        {"Description": "A", "Line Amount": "$10.00", "_confidence": "high", "_source": "A $10.00", "_page": 1},
        {"Description": "B", "Line Amount": "$20.00", "_confidence": "low", "_source": "B $20.00", "_page": 1},
    ]
    reserved_rows = 4
    totals = 6 + reserved_rows
    return {
        "document_state": state,
        # app/core/review.py:489-505 derives NEEDS_ATTENTION from open
        # ``attention`` items; the stored state string alone is not the gate.
        "attention": ([{
            "id": "att-1",
            "text": "A required section is missing from the extraction.",
            "disposition": None,
        }] if state == "NEEDS_ATTENTION" else []),
        "diagnostics": {"coverage": {"reasons": (
            ["A required section is missing from the extraction."]
            if state == "NEEDS_ATTENTION" else []
        )}},
        "template_type": "slot",
        "extracted_fields": {
            "B2": "$30.00",
            "B3": "00501",
            "B4": "0042",
            f"B{totals + 1}": "$30.00",
            f"B{totals + 2}": "$2.40",
            f"B{totals + 3}": "$32.40",
        },
        "extracted_data": {
            "Amount": {"value": "$30.00", "confidence": "high", "ref": "B2"},
            "ZIP": {"value": "00501", "confidence": "high", "ref": "B3"},
            "Last 4": {"value": "0042", "confidence": "high", "ref": "B4"},
        },
        "field_provenance": {
            "B2": {"source": "Total $30.00", "page": 1, "grounded": True},
            "B3": {"source": "ZIP 00501", "page": 1, "grounded": True},
            "B4": {"source": "ending 0042", "page": 1, "grounded": True},
            f"B{totals + 1}": {"source": "Subtotal $30.00", "page": 1, "grounded": True},
            f"B{totals + 2}": {"source": "Tax $2.40", "page": 1, "grounded": True},
            f"B{totals + 3}": {"source": "Total $32.40", "page": 1, "grounded": True},
        },
        "validation": {
            "confidence_map": {
                "B2": "high", "B3": "high", "B4": "high",
                f"B{totals + 1}": "low", f"B{totals + 2}": "unverified",
                f"B{totals + 3}": "edited",
            },
            "flagged_fields": [],
        },
        "slot_map": {
            "fields": [
                {"ref": "B2", "row_label": "Amount"},
                {"ref": "B3", "row_label": "ZIP"},
                {"ref": "B4", "row_label": "Last 4"},
                {"ref": f"B{totals + 1}", "row_label": "Subtotal"},
                {"ref": f"B{totals + 2}", "row_label": "Tax"},
                {"ref": f"B{totals + 3}", "row_label": "Total"},
            ],
            "tables": [{
                "name": "Items",
                "orientation": "rows",
                "header_row": 5,
                "start_row": 6,
                "end_row": 9,
                "start_col": 0,
                "end_col": 1,
                "columns": [
                    {"header": "Description", "key": "Description", "col": 0},
                    {"header": "Line Amount", "key": "Line Amount", "col": 1},
                ],
            }],
        },
        "Items_rows": rows,
        "review": {"document_reviewed": False},
    }


def document(ed=None, filename="invoice.pdf", needs_review=False):
    payload = json.dumps(ed or extracted())
    return SimpleNamespace(
        id=1,
        filename=filename,
        document_type="invoice",
        overall_confidence="high",
        needs_review=needs_review,
        get_extracted_data=lambda: json.loads(payload),
    )


def workbook(*, docs=None, provenance=False, marks=False, use_defaults=False):
    import openpyxl
    from app.api.routes.extract import _add_review_legend, _write_slot_excel

    docs = docs or [document()]
    layout = grid()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Results"
    if use_defaults:
        _write_slot_excel(ws, docs, layout, layout["cells"], openpyxl)
    else:
        _write_slot_excel(
            ws, docs, layout, layout["cells"], openpyxl,
            provenance=provenance, marks=marks,
        )
    _add_review_legend(wb, docs)
    buffer = io.BytesIO()
    wb.save(buffer)
    return openpyxl.load_workbook(io.BytesIO(buffer.getvalue()))
