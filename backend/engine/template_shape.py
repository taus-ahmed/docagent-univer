"""
DocAgent — Template Shape (Phase 2a)

A template carries its own shape instead of having it re-inferred from cell
text on every extraction. The shape says which rows are headers, which columns
hold labels, which hold values, and which bands repeat.

THE ONE RULE
    a cell with text in it is a STATIC label
    an empty cell is a SLOT

This replaces the separate "extract here" marker (`extractTarget`). The marker
was a second, independent way of saying the same thing, and the two could
disagree — a cell could be marked extractable and also contain text, and
nothing decided which won. Under the one rule there is nothing to disagree
about. `extractTarget` is still read for migration reporting only; it never
affects the shape.

Shape is computed once at template save and persisted on
`ColumnTemplate.shape_json`. Templates saved before this existed are inferred
at load and persisted then, so the inference happens once, not per extraction.

    {
      "version": 1,
      "header_rows":    [9],          # rows that title a repeating band
      "label_columns":  [0],          # columns holding row labels
      "value_columns":  [1],          # columns holding field values
      "repeat_bands":   [ {name, header_row, start_row, end_row, columns, section} ],
      "field_slots":    [ {slot_id, ref, row, col, row_label, col_header, section} ],
      "required_columns": 6,          # widest band — what a path must serve (2b)
      "inferred": true,
      "migration": {...}
    }
"""

import re

SHAPE_VERSION = 1


def _matrix(grid):
    """{(row, col): text} for every present cell; '' for present-but-empty."""
    out, marked, marked_with_text = {}, 0, 0
    for key, cell in (grid or {}).get("cells", {}).items():
        try:
            r, c = map(int, str(key).split(","))
        except (ValueError, AttributeError):
            continue
        if not isinstance(cell, dict):
            continue
        text = str(cell.get("value") or "").strip()
        out[(r, c)] = text
        if cell.get("extractTarget"):
            marked += 1
            if text:
                marked_with_text += 1
    return out, {"extract_target_cells": marked,
                 "extract_target_cells_with_text": marked_with_text}


def _ref(r, c):
    letter, n = "", c
    while True:
        letter = chr(65 + (n % 26)) + letter
        n = n // 26 - 1
        if n < 0:
            break
    return f"{letter}{r + 1}"


def _section_for(m, static, row):
    """Nearest lone static cell above `row` — a section title, not a label."""
    for r in range(row - 1, -1, -1):
        cols = [c for (rr, c) in static if rr == r]
        if not cols:
            continue
        present = [c for (rr, c) in m if rr == r]
        if len(cols) == 1 and len(present) == 1:
            return m[(r, cols[0])]
        return ""
    return ""


def compute_shape(grid, log=None):
    """Grid -> shape dict. Never raises; an unusable grid yields an empty shape."""
    def _say(msg):
        if log:
            log(msg)

    try:
        m, migration = _matrix(grid)
    except Exception:
        m, migration = {}, {}
    if not m:
        return _empty_shape(migration)

    rows = sorted({r for r, _ in m})
    max_col = max(c for _, c in m)
    static = {rc for rc, txt in m.items() if txt}

    # ── repeating bands: >= 2 adjacent static cells with empty rows beneath ──
    header_candidates = {}
    for r in rows:
        cols = sorted(c for c in range(max_col + 1) if (r, c) in static)
        if len(cols) < 2:
            continue
        if cols != list(range(cols[0], cols[0] + len(cols))):
            continue                                    # not adjacent
        if any((r + 1, c) in static for c in cols):
            continue                                    # a stack of labels
        header_candidates[r] = cols

    bands = []
    for hr, cols in sorted(header_candidates.items()):
        later = [r for r in rows
                 if r > hr and any((r, c) in static for c in range(max_col + 1))]
        end = (min(later) - 1) if later else max(rows)
        if end <= hr:
            _say(f"row {hr} looks like a band header "
                 f"({', '.join(m[(hr, c)] for c in cols)}) but has no empty rows "
                 f"beneath it — not treated as a repeating band")
            continue
        bands.append({
            "name": "table" if len(header_candidates) == 1 else f"table_{len(bands) + 1}",
            "header_row": hr,
            "start_row": hr + 1,
            "end_row": end,
            "columns": [{"col": c, "header": m[(hr, c)]} for c in cols],
            "section": _section_for(m, static, hr),
        })

    band_rows = set()
    for b in bands:
        band_rows.update(range(b["start_row"], b["end_row"] + 1))
    header_rows = [b["header_row"] for b in bands]

    # ── field slots: a static label with an empty cell beside it ──
    field_slots, label_cols, value_cols = [], set(), set()
    for r in rows:
        if r in band_rows or r in header_rows:
            continue
        for c in range(max_col + 1):
            if (r, c) not in static:
                continue
            for cc in range(c + 1, max_col + 2):
                if (r, cc) in static:
                    break
                if (r, cc) in m:                        # present and empty -> slot
                    field_slots.append({
                        "slot_id": f"F{len(field_slots) + 1}",
                        "ref": _ref(r, cc), "row": r, "col": cc,
                        "row_label": m[(r, c)], "col_header": "",
                        "section": _section_for(m, static, r),
                    })
                    label_cols.add(c)
                    value_cols.add(cc)
                    break
                break
            break                                       # leftmost pair per row

    for b in bands:
        label_cols.add(b["columns"][0]["col"])
        value_cols.update(c["col"] for c in b["columns"][1:])

    required = max([len(b["columns"]) for b in bands] + [2 if field_slots else 0])

    shape = {
        "version": SHAPE_VERSION,
        "header_rows": sorted(header_rows),
        "label_columns": sorted(label_cols),
        "value_columns": sorted(value_cols),
        "repeat_bands": bands,
        "field_slots": field_slots,
        "required_columns": required,
        "inferred": True,
        "migration": migration,
    }
    # Human summary computed HERE, not in the frontend: the rule has exactly one
    # implementation, and the editor displays what the engine actually decided
    # rather than a TypeScript re-derivation that could drift from it.
    shape["summary"] = describe(shape)
    return shape


def _empty_shape(migration=None):
    return {"version": SHAPE_VERSION, "header_rows": [], "label_columns": [],
            "value_columns": [], "repeat_bands": [], "field_slots": [],
            "required_columns": 0, "inferred": True, "migration": migration or {}}


def is_usable(shape):
    """A shape with nowhere to put anything cannot drive extraction."""
    return bool(shape) and bool(shape.get("field_slots") or shape.get("repeat_bands"))


def describe(shape):
    """One-line human summary, for logs and the UI."""
    if not shape:
        return "no shape"
    b = shape.get("repeat_bands") or []
    parts = [f"{len(shape.get('field_slots') or [])} field slots"]
    for band in b:
        cols = ", ".join(c["header"] for c in band["columns"])
        parts.append(f'band "{band["name"]}" rows {band["start_row"] + 1}-'
                     f'{band["end_row"] + 1} [{cols}]')
    parts.append(f"needs {shape.get('required_columns', 0)} columns")
    return "; ".join(parts)
