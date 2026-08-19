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

# Rows a bottom-of-grid band starts with; the writer expands it as needed.
_EDGE_BAND_ROWS = 10


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


def _declared_bands(grid, m, say):
    """Read `grid["regions"]` — the template declaring its own tables.

    A declared region is the table AS THE USER SEES IT, heading line included,
    so what is selected on screen is exactly what is declared. `orientation`
    says which way the records run:

        "rows"     headings across the region's FIRST ROW; one record per row.
        "columns"  headings down the region's FIRST COLUMN; one record per
                   column — a transposed table. Detection cannot express this
                   shape at all: it looks for headings with empty rows beneath,
                   finds none, and silently reads the headings as unrelated
                   single fields.

    Detection still runs for everything not declared, so the 19 templates in
    production are unaffected.

    ┌──────────────────────────────────────────────────────────────────────────┐
    │ COORDINATE STALENESS — READ BEFORE ADDING ROW OR COLUMN INSERTION.       │
    │                                                                          │
    │ A region is stored as absolute coordinates (r1,c1,r2,c2). Today the      │
    │ editor can only edit cells in place, so those coordinates cannot move    │
    │ and a declaration cannot go stale.                                       │
    │                                                                          │
    │ Insert/delete row or column ends that, and a stale declaration is worse  │
    │ than none: it points confidently at the wrong cells. Whoever adds        │
    │ insertion MUST shift declarations in the SAME commit:                    │
    │                                                                          │
    │   insert row at R  ->  r1 += 1 if r1 >= R ;  r2 += 1 if r2 >= R          │
    │   delete row at R  ->  r1 -= 1 if r1 >  R ;  r2 -= 1 if r2 >  R          │
    │                        then DROP the region if r2 <= r1                  │
    │   columns: the same against c1/c2                                        │
    │                                                                          │
    │ Note this is unlike `shape`, which is deliberately never stored because  │
    │ it can be recomputed from the grid. A declaration is user INTENT — it    │
    │ CANNOT be recomputed, so it has to be maintained instead.                │
    └──────────────────────────────────────────────────────────────────────────┘
    """
    out = []
    regions = (grid or {}).get("regions")
    if not isinstance(regions, list):
        return out

    for i, reg in enumerate(regions):
        if not isinstance(reg, dict) or reg.get("type") != "table":
            continue
        try:
            r1, r2 = int(reg["r1"]), int(reg["r2"])
            c1, c2 = int(reg["c1"]), int(reg["c2"])
        except (KeyError, TypeError, ValueError):
            say(f"declared region {i + 1} is malformed — ignored")
            continue
        r1, r2 = min(r1, r2), max(r1, r2)
        c1, c2 = min(c1, c2), max(c1, c2)
        orient = "columns" if str(reg.get("orientation")) == "columns" else "rows"
        name = str(reg.get("name") or "").strip()

        if orient == "rows":
            if r2 <= r1 or c2 < c1:
                say(f"declared region {i + 1} has no data rows beneath its "
                    f"heading row — ignored")
                continue
            heads = [str(m.get((r1, c), "") or "").strip()
                     for c in range(c1, c2 + 1)]
            columns = []
            for c, h in zip(range(c1, c2 + 1), heads):
                label = h or f"Column {_col_letter(c)}"
                key = label if heads.count(h) == 1 else f"{label} ({_col_letter(c)})"
                columns.append({
                    "col": c, "header": label, "key": key,
                    # A two-column table is a label/value pair by construction.
                    "role": "label" if (c == c1 and len(heads) == 2) else "value",
                })
            out.append({
                "name": name or (heads[0] if len(heads) == 2 and heads[0]
                                 else f"Table {len(out) + 1}"),
                "orientation": "rows", "declared": True,
                "header_row": r1, "start_row": r1 + 1, "end_row": r2,
                "columns": columns, "section": name,
            })
            say(f"declared table: rows {r1 + 2}-{r2 + 1}, "
                f"{len(columns)} columns, one record per row")
        else:
            if c2 <= c1 or r2 < r1:
                say(f"declared region {i + 1} has no data columns beside its "
                    f"heading column — ignored")
                continue
            fields = []
            for r in range(r1, r2 + 1):
                h = str(m.get((r, c1), "") or "").strip()
                if h:
                    fields.append({"row": r, "header": h, "key": h})
            if not fields:
                say(f"declared region {i + 1} has no headings down its first "
                    f"column — ignored")
                continue
            out.append({
                "name": name or f"Table {len(out) + 1}",
                "orientation": "columns", "declared": True,
                "header_col": c1, "start_col": c1 + 1, "end_col": c2,
                "start_row": r1, "end_row": r2,
                "fields": fields,
                "columns": [],          # row-oriented callers see no columns
                "header_row": r1, "section": name,
            })
            say(f"declared TRANSPOSED table: headings down column "
                f"{_col_letter(c1)}, records in columns "
                f"{_col_letter(c1 + 1)}-{_col_letter(c2)}, {len(fields)} fields")
    return out


def _band_width(band):
    """How many columns a band needs from the writer."""
    if band.get("orientation") == "columns":
        # heading column + one column per record
        return band["end_col"] - band["header_col"] + 1
    return len(band.get("columns") or [])


def declared_cells(band):
    """Every grid cell a declared band owns, heading line included."""
    if band.get("orientation") == "columns":
        return {(r, c)
                for r in range(band["start_row"], band["end_row"] + 1)
                for c in range(band["header_col"], band["end_col"] + 1)}
    return {(r, col["col"])
            for r in range(band["header_row"], band["end_row"] + 1)
            for col in band["columns"]}


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

    # ── what the template DECLARES comes first ────────────────────────────────
    # Detection stays — it is what every template in production relies on — but
    # it is no longer the only answer available for a shape it cannot express.
    bands = _declared_bands(grid, m, _say)
    claimed = set()
    for b in bands:
        claimed |= declared_cells(b)
    claimed_rows = {r for r, _ in claimed}

    # ── repeating bands: >= 2 adjacent static cells with empty rows beneath ──
    header_candidates = {}
    for r in rows:
        if r in claimed_rows:
            continue                                    # inside a declared table
        cols = sorted(c for c in range(max_col + 1) if (r, c) in static)
        if len(cols) < 2:
            continue
        if cols != list(range(cols[0], cols[0] + len(cols))):
            continue                                    # not adjacent
        if any((r + 1, c) in static for c in cols):
            continue                                    # a stack of labels
        header_candidates[r] = cols

    for hr, cols in sorted(header_candidates.items()):
        later = [r for r in rows
                 if r > hr and any((r, c) in static for c in range(max_col + 1))]
        end = (min(later) - 1) if later else max(rows)
        if end <= hr:
            # A header row at the very bottom of the grid, with nothing drawn
            # beneath it. Three or more adjacent headings can only be a table —
            # nobody writes a three-cell label/value pair — so it becomes a
            # band and the writer expands it to the document's row count. Two
            # cells stay ambiguous ("Date | Amount" could be a pair) and are
            # skipped out loud rather than guessed at.
            if len(cols) >= 3:
                end = hr + _EDGE_BAND_ROWS
                _say(f"row {hr} is a band header at the bottom of the grid "
                     f"({len(cols)} columns, no rows beneath) — treated as a "
                     f"band; the writer expands it to the document's rows")
            else:
                _say(f"row {hr} looks like a band header "
                     f"({', '.join(m[(hr, c)] for c in cols)}) but has no empty "
                     f"rows beneath it — not treated as a repeating band")
                continue
        section = _section_for(m, static, hr)
        headers_raw = [m[(hr, c)] for c in cols]

        # A TWO-column band is a label/value pair by construction — there is
        # nothing else two columns can be — so its first column is the label
        # column and its heading is the band's own identity ("CURRENT ASSETS").
        # A band of three or more columns has real column headings and no
        # label column, so its identity has to come from a section title.
        is_label_value = len(cols) == 2

        # Name the band after the section that titles it ("Earnings"), else —
        # for a label/value band — after its label column ("CURRENT ASSETS").
        # A real name is the band's address in the prompt and tells the model
        # which part of the document to read; "table_2" tells it nothing.
        if section:
            name = section
        elif is_label_value and headers_raw[0]:
            name = headers_raw[0]
        elif len(header_candidates) == 1:
            name = "table"
        else:
            name = f"table_{len(bands) + 1}"
        # Each column needs a key that is UNIQUE within its band, because the
        # model answers with a dict keyed by it. A side-by-side layout headed
        # "Current Assets | Amount | Current Liabilities | Amount" has the same
        # header twice, and two identical keys collapse into one — silently
        # losing half the sheet. Duplicates are disambiguated by column letter.
        headers = headers_raw
        columns = []
        for i, (c, h) in enumerate(zip(cols, headers)):
            key = h if headers.count(h) == 1 else f"{h} ({_col_letter(c)})"
            # Say which column holds the row's label rather than leaving it to
            # be inferred from position downstream.
            role = "label" if (is_label_value and i == 0) else "value"
            columns.append({"col": c, "header": h, "key": key, "role": role})
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
    header_rows = sorted({b["header_row"] for b in bands})

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
            if (r, c) not in static or (r, c) in claimed:
                c += 1
                continue
            cc = c + 1
            if (r, cc) in claimed:      # the slot belongs to a declared table
                c += 1
                continue
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
        if b.get("orientation") == "columns":
            label_cols.add(b["header_col"])
            value_cols.update(range(b["start_col"], b["end_col"] + 1))
        elif b["columns"]:
            label_cols.add(b["columns"][0]["col"])
            value_cols.update(c["col"] for c in b["columns"][1:])

    required = max([_band_width(b) for b in bands] + [2 if field_slots else 0])

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
        kind = "declared " if band.get("declared") else ""
        if band.get("orientation") == "columns":
            fields = ", ".join(f["header"] for f in band.get("fields") or [])
            parts.append(f'{kind}transposed band "{band["name"]}" columns '
                         f'{_col_letter(band["start_col"])}-'
                         f'{_col_letter(band["end_col"])} [{fields}]')
        else:
            cols = ", ".join(c["header"] for c in band["columns"])
            parts.append(f'{kind}band "{band["name"]}" rows '
                         f'{band["start_row"] + 1}-{band["end_row"] + 1} [{cols}]')
    parts.append(f"needs {shape.get('required_columns', 0)} columns")
    return "; ".join(parts)
