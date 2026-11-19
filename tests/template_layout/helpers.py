"""Test-only bridge from real XLSX fixtures to DocAgent's editor-grid contract."""

from __future__ import annotations

import contextlib
import io
import json
import re
from copy import copy
from pathlib import Path

import openpyxl
from openpyxl.cell import MergedCell
from openpyxl.utils import get_column_letter, column_index_from_string

from tests.harness import bootstrap as bs

bs.bootstrap()

from template_shape import compute_shape  # noqa: E402
from slot_extractor import (  # noqa: E402
    _table_map,
    build_prompt,
    run_slot_extraction,
    slots_from_shape,
    table_headers,
)


REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "templates"


def scenario_ids():
    return [f.stem.split(".")[0] for f in sorted(FIXTURES.glob("*.truth.json"))]


def load_truth(scenario: str):
    return json.loads((FIXTURES / f"{scenario}.truth.json").read_text(encoding="utf-8"))


def _rgb(color):
    if not color or color.type != "rgb" or not color.rgb:
        return None
    return "#" + str(color.rgb)[-6:]


def _style(cell):
    """Only properties the production editor-grid style can represent."""
    out = {}
    if cell.font:
        if cell.font.bold:
            out["bold"] = True
        if cell.font.italic:
            out["italic"] = True
        if cell.font.underline:
            out["underline"] = True
        if cell.font.sz:
            out["fontSize"] = cell.font.sz
        if cell.font.name:
            out["fontFamily"] = cell.font.name
        color = _rgb(cell.font.color)
        if color and color.upper() not in ("#000000", "#00000000"):
            out["fontColor"] = color
    fill = _rgb(cell.fill.fgColor) if cell.fill and cell.fill.fill_type else None
    if fill and fill.upper() not in ("#000000", "#00000000"):
        out["bgColor"] = fill
    if cell.alignment:
        if cell.alignment.horizontal in ("left", "center", "right"):
            out["align"] = cell.alignment.horizontal
        if cell.alignment.wrap_text:
            out["wrap"] = True
    if cell.border and any(getattr(cell.border, edge).style
                           for edge in ("left", "right", "top", "bottom")):
        out["borderAll"] = True
    return out


def workbook_to_grid(path: Path, sheet_name: str | None = None):
    """Represent one workbook sheet exactly as the production editor can.

    Excel-native tables, formulas-as-calculations, number formats, validation,
    hidden axes, and secondary sheets have no editor-grid keys and are therefore
    deliberately not smuggled into the application through test-only metadata.
    Formula *text* is a cell value and is retained, as it is by the editor.
    """
    wb = openpyxl.load_workbook(path, data_only=False)
    ws = wb[sheet_name] if sheet_name else wb.worksheets[0]
    merges = {}
    merge_parent = {}
    for rng in ws.merged_cells.ranges:
        r1, c1, r2, c2 = rng.min_row, rng.min_col, rng.max_row, rng.max_col
        merges[f"{r1 - 1},{c1 - 1}"] = {"rows": r2 - r1 + 1, "cols": c2 - c1 + 1}
        for row in range(r1, r2 + 1):
            for col in range(c1, c2 + 1):
                if (row, col) != (r1, c1):
                    merge_parent[(row, col)] = [r1 - 1, c1 - 1]

    cells = {}
    for row in ws.iter_rows(min_row=1, max_row=max(ws.max_row, 1),
                            min_col=1, max_col=max(ws.max_column, 1)):
        for cell in row:
            key = f"{cell.row - 1},{cell.column - 1}"
            if isinstance(cell, MergedCell):
                if (cell.row, cell.column) in merge_parent:
                    cells[key] = {"value": "", "mergeParent": merge_parent[(cell.row, cell.column)]}
                continue
            style = _style(cell)
            value = cell.value
            if value is None and not style and (cell.row, cell.column) not in merge_parent:
                continue
            entry = {"value": "" if value is None else value}
            if style:
                entry["style"] = style
            if (cell.row, cell.column) in merge_parent:
                entry["mergeParent"] = merge_parent[(cell.row, cell.column)]
            cells[key] = entry

    widths = []
    for col in range(1, ws.max_column + 1):
        widths.append(ws.column_dimensions[get_column_letter(col)].width)
    return {"cells": cells, "merges": merges, "regions": [],
            "colWidths": widths, "repeatRows": []}


def shape_for(scenario: str):
    grid = workbook_to_grid(FIXTURES / f"{scenario}.xlsx")
    return grid, compute_shape(grid, log=lambda _m: None)


def normalize_fields(shape):
    return sorted(
        ({"label": f.get("row_label", ""), "cell": f.get("ref", "")}
         for f in shape.get("field_slots") or []),
        key=lambda x: (x["cell"], x["label"]),
    )


def expected_fields(truth, first_sheet_only=True):
    first = truth["sheets"][0]
    return sorted(
        ({"label": f["label"], "cell": f["cell"]}
         for f in truth.get("fields") or []
         if not first_sheet_only or f.get("sheet", first) == first),
        key=lambda x: (x["cell"], x["label"]),
    )


def _start_col_of(band_data):
    if band_data.get("orientation") == "columns":
        return get_column_letter(int(band_data["header_col"]) + 1)
    cols = band_data.get("columns") or []
    return get_column_letter(min(int(c["col"]) for c in cols) + 1) if cols else "A"


def normalize_bands(shape):
    out = []
    for b in shape.get("repeat_bands") or []:
        orientation = b.get("orientation", "rows")
        if orientation == "columns":
            columns = [f["header"] for f in b.get("fields") or []]
            reserved = int(b["end_col"]) - int(b["start_col"]) + 1
        else:
            columns = [c["header"] for c in b.get("columns") or []]
            reserved = int(b["end_row"]) - int(b["start_row"]) + 1
        out.append({
            "name": b.get("name", ""),
            "orientation": orientation,
            "header_row": int(b.get("header_row", b.get("start_row", 0))) + 1,
            "first_data_row": int(b["start_row"]) + 1,
            "reserved_rows": reserved,
            "start_col": _start_col_of(b),
            "columns": columns,
        })
    return out


def expected_bands(truth, first_sheet_only=True):
    first = truth["sheets"][0]
    out = []
    for b in truth.get("bands") or []:
        if first_sheet_only and b.get("sheet", first) != first:
            continue
        out.append({k: b[k] for k in (
            "name", "orientation", "header_row", "first_data_row",
            "reserved_rows", "start_col", "columns")})
    return out


def prompt_capture(scenario: str):
    _grid, shape = shape_for(scenario)
    prompt = build_prompt(slots_from_shape(shape), ["audit fixture"], "audit")
    lines = []
    for line in prompt.splitlines():
        stripped = line.strip()
        if (re.match(r"F\d+: ", stripped) or stripped.startswith("TABLE \"")
                or stripped.startswith("section:") or stripped.startswith("columns (")):
            lines.append(stripped)
    return lines


def _field_value(f, doc_number):
    if f.get("empty"):
        return ""
    if "value" in f:
        return str(f["value"])
    return f"D{doc_number}:{f['cell']}"


def _truth_band_match(actual, truth_bands, used):
    keys = table_headers(actual)
    for i, b in enumerate(truth_bands):
        if i not in used and keys == b["columns"]:
            used.add(i)
            return i, b
    for i, b in enumerate(truth_bands):
        if i not in used:
            used.add(i)
            return i, b
    return None, None


def model_payload(shape, truth, doc_number=1, row_override=None):
    """Known answer for the *actual* prompt; never calls a model."""
    actual_slots = slots_from_shape(shape)
    truth_fields = {f["cell"]: f for f in truth.get("fields") or []
                    if f.get("sheet", truth["sheets"][0]) == truth["sheets"][0]}
    fields = {}
    source_lines = []
    for f in actual_slots["fields"]:
        expected = truth_fields.get(f["ref"])
        value = _field_value(expected, doc_number) if expected else f"UNEXPECTED:{f['ref']}"
        source = f"{f.get('row_label', 'field')} {value}" if value else ""
        fields[f["slot_id"]] = {"value": value, "source": source, "page": 1 if value else 0}
        if source:
            source_lines.append(source)

    tables = {}
    used = set()
    first_sheet = truth["sheets"][0]
    truth_bands = [b for b in truth.get("bands") or [] if b.get("sheet", first_sheet) == first_sheet]
    for actual in actual_slots["tables"]:
        bi, expected = _truth_band_match(actual, truth_bands, used)
        if expected:
            count = int(row_override if row_override is not None else expected.get("write_rows", expected["reserved_rows"]))
        else:
            count = int(row_override or 1)
        rows = []
        keys = table_headers(actual)
        omit = set((truth.get("write") or {}).get("model_omit_columns") or [])
        extras = list((truth.get("write") or {}).get("model_extra_columns") or [])
        for ri in range(count):
            cells = {}
            for ci, key in enumerate(keys):
                if key in omit:
                    continue
                value = "" if ri == count - 1 and ci == len(keys) - 1 else f"D{doc_number}:T{(bi or 0)+1}:R{ri+1}:C{ci+1}"
                cells[key] = value
            for extra in extras:
                cells[extra] = f"EXTRA:{doc_number}:{ri+1}"
            source = " ".join(v for v in cells.values() if v)
            rows.append({"cells": cells, "source": source, "page": 1})
            if source:
                source_lines.append(source)
        tables[actual["name"]] = rows
    return {"fields": fields, "tables": tables}, "\n".join(source_lines)


class MockLLM:
    def __init__(self, payload):
        self.payload = payload

    def extract(self, **_kwargs):
        payload = self.payload
        return type("Response", (), {
            "success": True,
            "parsed_json": payload,
            "raw_text": json.dumps(payload),
            "tokens_used": 0,
        })()


class StoredDoc:
    def __init__(self, data, filename):
        self._data = data
        self.filename = filename

    def get_extracted_data(self):
        return self._data


def extracted_doc(grid, shape, truth, doc_number=1, row_override=None):
    payload, text = model_payload(shape, truth, doc_number, row_override)
    orchestrator = type("Orchestrator", (), {"llm": MockLLM(payload)})()
    with contextlib.redirect_stdout(io.StringIO()):
        result = run_slot_extraction(
            orchestrator,
            f"scenario-{truth['scenario']}-{doc_number}.pdf",
            {"layout": grid, "shape": shape},
            None,
            page_images=[],
            doc_text=text,
            doc_text_pages=[text],
            file_type="digital_pdf",
            default_doc_type="other",
            start=0.0,
        )[0]
    return StoredDoc(result.extracted_data, f"scenario-{truth['scenario']}-{doc_number}.pdf")


def _row_count_for(truth, band_index, doc_index, override=None):
    if override is not None:
        return int(override)
    write = truth.get("write") or {}
    counts = write.get("document_row_counts")
    if counts:
        return int(counts[doc_index])
    return int(truth["bands"][band_index].get("write_rows",
                                               truth["bands"][band_index]["reserved_rows"]))


def desired_row(row_1based, truth, doc_index=0, override=None):
    """Good-design row: bands expand or contract; everything below moves."""
    shifted = int(row_1based)
    first_sheet = truth["sheets"][0]
    for bi, b in enumerate(truth.get("bands") or []):
        if b.get("sheet", first_sheet) != first_sheet or b.get("orientation") == "columns":
            continue
        end = int(b["first_data_row"]) + int(b["reserved_rows"]) - 1
        if row_1based > end:
            shifted += _row_count_for(truth, bi, doc_index, override) - int(b["reserved_rows"])
    return shifted


def desired_block_height(source_ws, truth, doc_index=0, override=None):
    return desired_row(source_ws.max_row, truth, doc_index, override)


def shift_cell(ref, truth, doc_index=0, override=None, doc_offset=0):
    m = re.fullmatch(r"([A-Z]+)(\d+)", ref)
    assert m, ref
    row = desired_row(int(m.group(2)), truth, doc_index, override) + doc_offset
    return f"{m.group(1)}{row}"


def write_workbook(scenario: str, output: Path, row_override=None):
    from app.api.routes.extract import _write_slot_excel

    truth = load_truth(scenario)
    grid, shape = shape_for(scenario)
    docs_n = int((truth.get("write") or {}).get("documents", 1))
    docs = []
    for di in range(docs_n):
        override = ((truth.get("write") or {}).get("document_row_counts") or [None] * docs_n)[di]
        if row_override is not None:
            override = row_override
        docs.append(extracted_doc(grid, shape, truth, di + 1, override))
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = truth["sheets"][0]
    with contextlib.redirect_stdout(io.StringIO()):
        _write_slot_excel(ws, docs, grid, grid["cells"], openpyxl,
                          provenance=False, marks=False)
    wb.save(output)
    return truth, shape


def col_index(letter: str):
    return column_index_from_string(letter)


def copy_cell_style(src, dst):
    """Used only by diagnostics that need an independent style comparison."""
    dst.font = copy(src.font)
    dst.fill = copy(src.fill)
    dst.border = copy(src.border)
    dst.alignment = copy(src.alignment)
    dst.number_format = src.number_format
