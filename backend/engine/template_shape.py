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


def _col_letter(c):
    letter, n = "", c
    while True:
        letter = chr(65 + (n % 26)) + letter
        n = n // 26 - 1
        if n < 0:
            break
    return letter


def _ref(r, c):
    return f"{_col_letter(c)}{r + 1}"


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
        section = _section_for(m, static, hr)
        # Name the band after the section that titles it ("Earnings",
        # "Deductions"). That name is the band's address in the prompt, and a
        # real name extracts better than "table_2" — the model is being told
        # which part of the document to read. Falls back to a positional name
        # only when the template gives the band no title at all.
        if section:
            name = section
        elif len(header_candidates) == 1:
            name = "table"
        else:
            name = f"table_{len(bands) + 1}"
        # Each column needs a key that is UNIQUE within its band, because the
        # model answers with a dict keyed by it. A side-by-side layout headed
        # "Current Assets | Amount | Current Liabilities | Amount" has the same
        # header twice, and two identical keys collapse into one — silently
        # losing half the sheet. Duplicates are disambiguated by column letter.
        headers = [m[(hr, c)] for c in cols]
        columns = []
        for c, h in zip(cols, headers):
            key = h if headers.count(h) == 1 else f"{h} ({_col_letter(c)})"
            columns.append({"col": c, "header": h, "key": key})
        bands.append({
            "name": name,
            "header_row": hr,
            "start_row": hr + 1,
            "end_row": end,
            "columns": columns,
            "section": section,
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
        # EVERY label/slot pair across the row, not just the leftmost. Side-by-side
        # layouts put two pairs on one line — "Total Current Assets | _ | Total
        # Current Liabilities | _" — and taking only the first silently drops the
        # right-hand half of the sheet.
        c = 0
        while c <= max_col:
            if (r, c) not in static:
                c += 1
                continue
            cc = c + 1
            if (r, cc) in m and (r, cc) not in static:   # present and empty -> slot
                field_slots.append({
                    "slot_id": f"F{len(field_slots) + 1}",
                    "ref": _ref(r, cc), "row": r, "col": cc,
                    "row_label": m[(r, c)], "col_header": "",
                    "section": _section_for(m, static, r),
                })
                label_cols.add(c)
                value_cols.add(cc)
                c = cc + 1
            else:
                c += 1

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


# ══════════════════════════════════════════════════════════════════════════════
# PATH SELECTION (Phase 2b)
# ══════════════════════════════════════════════════════════════════════════════
#
# How many columns can each extraction path actually put on a sheet? This is a
# property of the path's own output format, not a guess:
#
#   layout  2   `_build_section_prompt` emits {label_col, value_col} rows and
#               nothing else, so a section can only ever be two columns wide.
#   field   -   table rows are keyed by column name; no ceiling.
#   slot    -   every cell is addressed by (row, column header); no ceiling.
#
# The router asks one question: how many columns does this template need, and
# can the chosen path serve that many. It replaces matching the user's column
# headers against a list of 16 English words, which silently misrouted any
# template whose value column was headed "2024", "USD", "Q4", a currency
# symbol, a non-English word, or nothing at all.

PATH_CAPACITY = {"layout": 2, "field": None, "slot": None, "cbm": None}


def choose_path(shape, doc_type="", slot_doc_types=()):
    """Return {path, required_columns, template_type, reason, error}.

    `error` is set when NO path can serve the template. The caller must fail
    the document with that message — never silently produce a blank or partial
    sheet, which is what the old router did.
    """
    if not is_usable(shape):
        return {"path": None, "required_columns": 0, "template_type": None,
                "reason": "",
                "error": ("This template has no slots to fill. Every cell "
                          "either contains text (a label) or is outside the "
                          "used area. Leave a cell empty next to a label, or "
                          "put column headings in a row with empty rows "
                          "beneath them.")}

    required = int(shape.get("required_columns") or 0)
    bands = shape.get("repeat_bands") or []
    field_slots = shape.get("field_slots") or []

    # Slot-directed extraction addresses every cell by (row label, column
    # header), so it serves any number of columns. Phase 2c routes every
    # templated document through it, which is what removes the 2-column
    # ceiling the layout path imposed. `slot_doc_types=None` means "all".
    if slot_doc_types is None or doc_type in slot_doc_types:
        return {"path": "slot", "required_columns": required,
                "template_type": "slot",
                "reason": f"slot-directed (serves {required} columns)",
                "error": None}

    # Structure of the template, from the shape alone — no keyword list.
    band_cells = sum(len(b["columns"]) * max(0, b["end_row"] - b["start_row"] + 1)
                     for b in bands)
    if not bands:
        template_type = "labeled"                      # pure key/value form
    elif not field_slots:
        template_type = "structural"                   # pure column layout
    elif len(field_slots) > band_cells * 0.5:
        template_type = "mixed"                        # labelled form + a table
    else:
        template_type = "structural"

    reason = f"{template_type} template needing {required} columns"

    # CAPACITY CHECK — the arithmetic. A path that cannot represent the
    # template's widest band must not be chosen, however the template looks.
    if template_type == "structural" and required > PATH_CAPACITY["layout"]:
        reason = (f"{template_type} by structure, but it needs {required} "
                  f"columns and the layout path serves only "
                  f"{PATH_CAPACITY['layout']} — routed to the field path instead")
        template_type = "mixed"

    path = "layout" if template_type == "structural" else "field"
    return {"path": path, "required_columns": required,
            "template_type": template_type, "reason": reason, "error": None}


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
