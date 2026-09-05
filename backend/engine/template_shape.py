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


# The largest grid we will densify. The editor is 50x26 = 1300 cells; this is
# a guard against a malformed grid with a stray coordinate, not a real limit.
_MAX_DENSE_CELLS = 20000


def _merge_cover(grid, cells):
    """{(row, col)} covered by a merge but not its own anchor.

    A covered cell is not a label and not a slot — it is part of its parent,
    and the only cell that means anything is the anchor. `grid["merges"]` is
    the authority: `{"r,c": {rows, cols}}` keyed by the anchor. Cells saved by
    older editors also carry a `mergeParent` of their own, which is read here
    so grids saved before the editor stopped writing it still resolve.
    """
    cover = set()
    for key, span in (grid.get("merges") or {}).items():
        try:
            r, c = map(int, str(key).split(","))
            rows = int((span or {}).get("rows") or 1)
            cols = int((span or {}).get("cols") or 1)
        except (ValueError, AttributeError, TypeError):
            continue
        if rows < 1 or cols < 1:
            continue
        for rr in range(r, r + rows):
            for cc in range(c, c + cols):
                if (rr, cc) != (r, c):
                    cover.add((rr, cc))
    for key, cell in (cells or {}).items():           # legacy grids
        if not isinstance(cell, dict) or not cell.get("mergeParent"):
            continue
        try:
            r, c = map(int, str(key).split(","))
            pr, pc = (int(x) for x in cell["mergeParent"])
        except (ValueError, AttributeError, TypeError):
            continue
        if (r, c) != (pr, pc):
            cover.add((r, c))
    return cover


def _used_range(raw, grid, cover):
    """(r1, c1, r2, c2) — the rectangle the template actually occupies.

    The box is the bounding box of every cell carrying TEXT, widened to cover
    any declared region and any merge. STYLING DELIBERATELY DOES NOT EXTEND
    IT, and that is the whole point of computing a box at all: presence in
    `grid["cells"]` is an artefact of editor bookkeeping — `applyStyle` writes
    an entry for every cell in the selection, so drawing a border used to be
    what made a template extractable. Inside the box, absent and empty mean
    the same thing, and formatting stops being load-bearing.
    """
    rs, cs = [], []
    for (r, c), text in raw.items():
        if text and (r, c) not in cover:
            rs.append(r)
            cs.append(c)
    for reg in (grid.get("regions") or []):
        if not isinstance(reg, dict):
            continue
        try:
            rs += [int(reg["r1"]), int(reg["r2"])]
            cs += [int(reg["c1"]), int(reg["c2"])]
        except (KeyError, TypeError, ValueError):
            continue
    for key, span in (grid.get("merges") or {}).items():
        try:
            r, c = map(int, str(key).split(","))
            rs += [r, r + int((span or {}).get("rows") or 1) - 1]
            cs += [c, c + int((span or {}).get("cols") or 1) - 1]
        except (ValueError, AttributeError, TypeError):
            continue
    if not rs:
        return None
    r1, r2 = max(0, min(rs)), max(rs)
    c1, c2 = max(0, min(cs)), max(cs)
    # A template one column wide is a column of labels with nowhere to put an
    # answer — the single most ordinary thing a user draws, and it scored zero
    # slots. A label column implies a value column beside it.
    #
    # The widening stops here rather than applying to every grid, because a
    # fully populated row is not a label waiting for a value: under THE ONE
    # RULE "Total | 999" is two labels, and always reaching a column further
    # would turn the second into a label with a slot beside it. A right-edge
    # label column that DOES need a value column — the side-by-side layout
    # "Bank Name | _ | ABA | _" — is handled in R2, where the block's own
    # label/value alternation is known.
    if c2 == c1:
        c2 = c1 + 1
    return r1, c1, r2, c2


def _matrix(grid):
    """{(row, col): text} for every cell in the used range; '' for empty.

    A cell that was never touched in the editor and a cell that was touched
    and left empty are the SAME THING to a template, so both appear here as
    ''. See `_used_range` for why that is not merely a convenience.
    """
    grid = grid or {}
    cells = grid.get("cells") or {}
    raw, marked, marked_with_text = {}, 0, 0
    for key, cell in cells.items():
        try:
            r, c = map(int, str(key).split(","))
        except (ValueError, AttributeError):
            continue
        if not isinstance(cell, dict):
            continue
        text = str(cell.get("value") or "").strip()
        raw[(r, c)] = text
        if cell.get("extractTarget"):
            marked += 1
            if text:
                marked_with_text += 1

    cover = _merge_cover(grid, cells)
    out = {rc: txt for rc, txt in raw.items() if rc not in cover}

    box = _used_range(raw, grid, cover)
    if box:
        r1, c1, r2, c2 = box
        if (r2 - r1 + 1) * (c2 - c1 + 1) <= _MAX_DENSE_CELLS:
            for r in range(r1, r2 + 1):
                for c in range(c1, c2 + 1):
                    if (r, c) not in cover:
                        out.setdefault((r, c), "")

    return out, {"extract_target_cells": marked,
                 "extract_target_cells_with_text": marked_with_text,
                 "merged_cells": len(cover),
                 "used_range": list(box) if box else []}


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


def _wide_headings(grid):
    """{(row, col)} of merge anchors spanning 2+ COLUMNS.

    A cell merged across columns and carrying text is a heading and nothing
    else — no user merges four cells together to make a label for a value in
    the fifth. That makes it the one section title that needs no adjacency
    test to be believed.
    """
    out = set()
    for key, span in (grid.get("merges") or {}).items():
        try:
            r, c = map(int, str(key).split(","))
            if int((span or {}).get("cols") or 1) >= 2:
                out.add((r, c))
        except (ValueError, AttributeError, TypeError):
            continue
    return out


def _section_for(m, static, row, wide=()):
    """The section title above `row`, or "".

    Two ways to be a title, because there are two kinds of certainty:

    1. A cell MERGED ACROSS COLUMNS. Unambiguous — it is a heading by its own
       geometry — so blank rows between it and the table it titles do not
       matter. This is the ordinary "merged section heading across A1:E1 with
       the table starting at row 3".

    2. A lone static on the line IMMEDIATELY above. A title sits on the line
       directly above the thing it titles; a blank line in between means the
       label belongs to what came before it, not to what follows.

    That adjacency is doing work the old test did by accident. This used to
    scan upward past blank rows and accept the first lone static that ALSO had
    no other cell present in its row — and "no other cell present" is exactly
    the editor-bookkeeping artefact R1 removes. On the gold payslip it worked:

        row  9  Earnings                    <- one static, column 1 ABSENT
        row 10  Description | Amount        <- the band header it titles

    and on the gold balance sheet it correctly declined:

        row  6  Total Current Assets | ''   <- one static, column 1 EMPTY
        row  7  (blank)
        row  8  NON-CURRENT ASSETS | Amount

    Under a dense used range those two rows are identical — both are a lone
    static with an empty cell beside it — so presence can no longer separate
    them and the balance sheet's bands would have been named after the running
    totals above them ("Total Current Assets" instead of "NON-CURRENT
    ASSETS"). Adjacency separates them for a reason that survives: row 9 is
    against its header, row 6 is a blank line away from one.

    A merged heading reads as one static here because the cells it covers are
    not in `m` at all (see `_merge_cover`).
    """
    # (1) the nearest non-blank row above, if it is a merged heading
    for r in range(row - 1, -1, -1):
        cols = [c for (rr, c) in static if rr == r]
        if not cols:
            continue
        if len(cols) == 1 and (r, cols[0]) in wide:
            return m[(r, cols[0])]
        break                        # a real row, and not a wide heading
    # (2) otherwise only the line directly above counts
    r = row - 1
    if r < 0:
        return ""
    cols = [c for (rr, c) in static if rr == r]
    if len(cols) == 1:
        return m[(r, cols[0])]
    return ""


def _declared_bands(grid, m, say, skip):
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
            skip(f"declared region {i + 1} is malformed — ignored")
            continue
        r1, r2 = min(r1, r2), max(r1, r2)
        c1, c2 = min(c1, c2), max(c1, c2)
        orient = "columns" if str(reg.get("orientation")) == "columns" else "rows"
        name = str(reg.get("name") or "").strip()

        if orient == "rows":
            # R5 — a table needs a heading row AND data rows beneath it, and a
            # label column AND at least one value column beside it. The column
            # test used to be `c2 < c1`, which is only false for a region with
            # NEGATIVE width: a single-column region passed, built one unnamed
            # value column with no label column to anchor it, and asked the
            # model for one value per row with nothing to say what the value
            # was. It came back filled with cover-page text. The transposed
            # branch below has always checked `c2 <= c1`; the two disagreed
            # about what a degenerate region is.
            if r2 <= r1:
                skip(f"declared region {i + 1} has no data rows beneath its "
                    f"heading row — ignored")
                continue
            if c2 <= c1:
                skip(f"declared region {i + 1} is one column wide — a table "
                    f"needs a label column and at least one value column "
                    f"beside it — ignored")
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
                skip(f"declared region {i + 1} has no data columns beside its "
                    f"heading column — ignored")
                continue
            fields = []
            for r in range(r1, r2 + 1):
                h = str(m.get((r, c1), "") or "").strip()
                if h:
                    fields.append({"row": r, "header": h, "key": h})
            if not fields:
                skip(f"declared region {i + 1} has no headings down its first "
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


def _gate_findings(grid, m, bands):
    """(warnings, blocking) — what the save gate should say about this grid.

    `coverage` measures LABELS that should have slots, which is the right
    question for a form and no question at all for a pure table: a template
    that is only a declared band has no such labels, so it reported
    `labels: 0, complete: True` and the gate had nothing to say however wrong
    the table was. Measured across the 23 real templates in the repo, all 23
    report complete — and so did four deliberately broken ones, which is the
    hole these rules fill.

    Each rule was chosen on its FALSE-POSITIVE rate against those 23, because
    a gate that fires on a legitimate template is the same class of bug as the
    silent failures it is meant to replace:

        A  a band column with no heading          0/23   WARN
        D  a band with no headings at all         0/23   BLOCK
        E  two declared regions overlapping       0/23   WARN
        G  duplicate headings inside one band     1/23   REJECTED — it fires
                                                         on bs_luq, a real
                                                         production template
                                                         laying two label/value
                                                         pairs side by side,
                                                         which the engine
                                                         already handles by
                                                         disambiguating the key
                                                         with a column letter

    A is the one that earns its place: it is the only rule that catches a table
    whose top-left cell was left blank, where the engine synthesises a name
    ("Column A") and asks the model to fill a column it cannot describe. A user
    has no way to see that from the editor.

    D is a severity split on A rather than a separate detector — every column
    unnamed cannot be anything but a mistake, so it blocks where A warns.

    23 templates is evidence, not proof, and every one of them was drawn by us.
    That is why A warns instead of blocking: the shapes a real user draws are
    exactly the ones not in this sample.
    """
    warnings, blocking = [], []

    for b in bands:
        if b.get("orientation") == "columns":
            # A transposed band's headings run down its first column, and a
            # region with none is already refused by R5 before it gets here.
            continue
        cols = b.get("columns") or []
        unnamed = [c for c in cols
                   if not str(m.get((b["header_row"], c["col"]), "") or "").strip()]
        if not cols:
            continue
        if len(unnamed) == len(cols):
            blocking.append(
                f'the table at row {b["header_row"] + 1} has no column headings '
                f"— the engine would ask the model to fill {len(cols)} columns "
                f"it cannot name. Put a heading in each column of that row.")
        elif unnamed:
            where = ", ".join(_col_letter(c["col"]) for c in unnamed)
            warnings.append(
                f'the table at row {b["header_row"] + 1} has no heading in '
                f'column {where} — the engine will ask for a column it can '
                f'only call "{unnamed[0]["header"]}", and the model has nothing '
                f"to go on. Type a heading there.")

    regions = [r for r in ((grid or {}).get("regions") or [])
               if isinstance(r, dict) and r.get("type") == "table"]
    for i, a in enumerate(regions):
        for b in regions[i + 1:]:
            try:
                ar = (min(a["r1"], a["r2"]), max(a["r1"], a["r2"]),
                      min(a["c1"], a["c2"]), max(a["c1"], a["c2"]))
                br = (min(b["r1"], b["r2"]), max(b["r1"], b["r2"]),
                      min(b["c1"], b["c2"]), max(b["c1"], b["c2"]))
            except (KeyError, TypeError, ValueError):
                continue
            if ar[0] <= br[1] and br[0] <= ar[1] and ar[2] <= br[3] and br[2] <= ar[3]:
                warnings.append(
                    f'two declared tables overlap ("{a.get("name") or "?"}" and '
                    f'"{b.get("name") or "?"}") — the same cells belong to both, '
                    f"and which one claims them is not defined.")
    return warnings, blocking


def _coverage(m, static, wide, bands, field_slots, band_rows,
              header_rows, section_rows, heading_rows, skipped,
              warnings=(), blocking=()):
    """What the engine understood, and what it had to leave behind (R6).

    `is_usable` answers one bit — is there anywhere at all to put anything —
    and a template can be badly wrong while passing it. The reported matrix
    had four slots where eight were drawn: not "0 slots", but "half of this
    is not being read", and the shape had no vocabulary for that. Nothing
    downstream could tell a template it fully understood from one it had
    understood half of.

    The measure is LABELS, not empty cells. Counting unclaimed cells reads
    alarm into ordinary templates — the gold invoice's key/value block spans
    columns A-E because the table below it is five wide, so three of its
    columns are legitimately blank forever. A label the user wrote and the
    engine could not give a slot to is the thing that is actually wrong.

    Band headers, band interiors, section titles and a block's own heading row
    are excluded: they are labels doing a different job — naming a column,
    titling a table — and they are not waiting for a value. Counting a
    matrix's "Years 1-7" as an unfilled label reported three orphans on a
    template the engine had read perfectly.
    """
    owned = {f["row"] for f in field_slots}
    skip_rows = (set(band_rows) | set(header_rows) | set(section_rows)
                 | set(heading_rows))

    labels, orphans = 0, []
    for (r, c) in sorted(static):
        if r in skip_rows or (r, c) in wide:
            continue
        labels += 1
        if r not in owned:
            orphans.append({"ref": _ref(r, c), "label": m[(r, c)]})

    band_cells = 0
    for b in bands:
        if b.get("orientation") == "columns":
            band_cells += (len(b.get("fields") or [])
                           * max(0, b["end_col"] - b["start_col"] + 1))
        else:
            band_cells += (len(b.get("columns") or [])
                           * max(0, b["end_row"] - b["start_row"] + 1))

    return {
        "labels": labels,
        "labels_with_slots": labels - len(orphans),
        "orphan_labels": orphans[:20],
        "orphan_count": len(orphans),
        "field_slots": len(field_slots),
        "band_cells": band_cells,
        "skipped": skipped,
        # A: the user should look at it. E: the user should look at it.
        "warnings": list(warnings),
        # D: the engine would ask for something it cannot describe.
        "blocking": list(blocking),
        "complete": not orphans and not skipped and not warnings and not blocking,
    }


def compute_shape(grid, log=None):
    """Grid -> shape dict. Never raises; an unusable grid yields an empty shape."""
    skipped = []

    def _say(msg):
        if log:
            log(msg)

    def _skip(msg):
        """Something the engine DECLINED to read, kept on the shape (R6).

        Distinct from `_say`, which also narrates what the engine DID —
        "declared TRANSPOSED table: ..." is a success. Recording every message
        made a correct transposed template report two skipped structures.
        These messages used to reach a server log only, where the person
        drawing the template would never see them.
        """
        skipped.append(msg)
        _say(msg)

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
    wide = _wide_headings(grid)
    bands = _declared_bands(grid, m, _say, _skip)
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

    def _static_count(r):
        return sum(1 for c in range(max_col + 1) if (r, c) in static)

    for hr, cols in sorted(header_candidates.items()):
        # ── WHERE THE BAND ENDS (R3) ──────────────────────────────────────
        # This used to be "the first row below the header holding ANY static
        # cell, minus one". One typed cell anywhere inside a table therefore
        # ended it there: a `Subtotal` in A5 turned a ten-row table into a
        # three-row band, kept all five columns, and left `Subtotal` as a
        # stray field competing with the table for the same data.
        #
        # A static row inside a band's span is a ROW LABEL unless it is really
        # the start of what comes after the table. Two things say it is:
        #
        #   FULL     it fills the band's own shape — statics in at least half
        #            its columns. On a two-column label/value band that is a
        #            single label, which is why the balance sheet's "Total
        #            Current Assets" still closes CURRENT ASSETS and stays a
        #            field slot. On a five-column table one label is 1 of 5,
        #            and closes nothing.
        #
        #            HALF, not "all but one", because a band can be several
        #            label/value pairs side by side: the production BS Luq
        #            template heads four columns "Current assets | Amount |
        #            Non current assets | Amount", and its totals row fills
        #            exactly two of them — one per pair. Requiring three left
        #            that band running to row 49 and swallowing all six of its
        #            field slots.
        #
        #   TRAILING no blank row follows it before the span ends — it is part
        #            of the block of summary lines beneath the table. This is
        #            what keeps the gold bank statement's `Total Credits /
        #            Total Debits / Closing Balance` out of its transactions
        #            band, which FULL alone would have swallowed.
        #
        # Anything else — an isolated label with the table continuing blank
        # beneath it — is inside the band.
        nxt = [r for r in sorted(header_candidates) if r > hr]
        span_end = (min(nxt) - 1) if nxt else max(rows)
        span = [r for r in rows if hr < r <= span_end]
        need = max(1, (len(cols) + 1) // 2)

        end = span_end
        for r in span:
            if not _static_count(r):
                continue
            full = _static_count(r) >= need
            trailing = not any(rr > r and not _static_count(rr) for rr in span)
            if full or trailing:
                end = r - 1
                break
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
                _skip(f"row {hr} looks like a band header "
                     f"({', '.join(m[(hr, c)] for c in cols)}) but has no empty "
                     f"rows beneath it — not treated as a repeating band")
                continue
        section = _section_for(m, static, hr, wide)
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

    # A row that TITLES a band is not also a field in it. "Earnings" names the
    # band beneath it; it is not a label waiting for a value. Under a sparse
    # grid this never came up, because a lone heading had no cell beside it to
    # become a slot — R1 gives it one, so the exclusion has to be said out
    # loud. Only rows an actual band took its name from are excluded, so a
    # lone label that titles nothing is still an ordinary field.
    section_rows = {b["header_row"] - 1 for b in bands if b.get("section")}

    # ══════════════════════════════════════════════════════════════════════
    # FIELD SLOTS — COLUMN ROLES, NOT A LEFT-TO-RIGHT SCAN (R2)
    # ══════════════════════════════════════════════════════════════════════
    #
    # This used to walk each row left to right, make a slot in the cell
    # immediately right of a static one, and then step PAST that slot. So a
    # matrix — one label column and two headed value columns — lost its second
    # value column entirely:
    #
    #        A                     B            C
    #   1    Payment Calculation   Years 1-7    Years 8-30
    #   2    Principal             <slot>       (never considered)
    #
    # At column C the scan asked "is C static?", found a slot rather than a
    # label, and moved on. The rule could express "a label with AN empty cell
    # beside it" and had no way to say "with N empty cells beside it". Four
    # slots came back where eight were drawn, and because `is_usable` was true
    # and nothing held an expectation, the document exported a half-filled
    # sheet that looked like it had worked.
    #
    # Columns now get a ROLE within a block of consecutive rows:
    #
    #   label column   some row in the block's body has text in it
    #   value column   no body row has text in it, AND it is justified — see
    #                  below. It is a slot on every row whose label has text.
    #
    # A VALUE COLUMN HAS TO BE JUSTIFIED, or every blank column inside the
    # used range becomes a slot. The gold invoice's key/value block spans
    # columns A-E, because its line-item table below is five columns wide;
    # without justification each of its nine labels would sprout four slots
    # across C, D and E. Two things justify one:
    #
    #   headed    the block's heading row names it ("Years 8-30") — the user
    #             wrote a column and expects it filled
    #   beside    it sits immediately right of a label column — the ordinary
    #             label/value pair, and what the old scan could see
    #
    # A block's HEADING ROW is its first row when that row has text in strictly
    # more columns than any row beneath it in the block. That is the matrix
    # signature (3 texts, then rows of 1) and it does not fire on a plain
    # key/value list (1 text, then rows of 1), so those blocks have no headings
    # and their slots carry `col_header: ""` exactly as before.
    field_slots, label_cols, value_cols = [], set(), set()
    heading_rows = set()

    skip_rows = band_rows | set(header_rows) | section_rows
    all_cols = range(max_col + 1)

    def _text_cols(r):
        return [c for c in all_cols if (r, c) in static and (r, c) not in claimed]

    # blocks = maximal runs of CONSECUTIVE candidate rows. Roles are local to a
    # block so a key/value header area and a wide table lower down cannot pool
    # their columns and misclassify each other.
    blocks, run = [], []
    for r in rows:
        if r in skip_rows:
            if run:
                blocks.append(run)
                run = []
            continue
        if run and r != run[-1] + 1:
            blocks.append(run)
            run = []
        run.append(r)
    if run:
        blocks.append(run)

    def _open(r, c):
        """Empty and available: inside the box, or the implied column."""
        if c > max_col:
            return True                         # only max_col + 1 reaches here
        return (r, c) in m and (r, c) not in static

    for block in blocks:
        non_blank = [r for r in block if _text_cols(r)]
        if not non_blank:
            continue

        head, rest = None, non_blank[1:]
        if rest and len(_text_cols(non_blank[0])) > max(len(_text_cols(r))
                                                        for r in rest):
            head = non_blank[0]
            heading_rows.add(head)
        body = [r for r in non_blank if r != head]
        if not body:
            continue

        block_labels = sorted({c for r in body for c in _text_cols(r)})
        if not block_labels:
            continue
        headed = set(_text_cols(head)) if head is not None else set()
        beside = {c + 1 for c in block_labels}
        block_values = sorted((headed | beside) - set(block_labels))

        # A LABEL COLUMN AT THE RIGHT EDGE still needs its value column, and
        # that column lies outside the bounding box of the text — nothing was
        # ever written in it. "Bank Name | _ | ABA | _" is the case: the value
        # for `ABA` belongs in column D, and D holds nothing anywhere.
        #
        # Only granted when the block ALREADY has a value column inside the
        # box, which is what says these are label/value pairs at all. Without
        # that test a fully populated row would qualify, and "Total | 999" —
        # two labels under THE ONE RULE — would sprout a slot in column C.
        in_box = [c for c in block_values if c <= max_col]
        block_values = ([c for c in block_values if c <= max_col + 1]
                        if in_box else in_box)

        for r in body:
            for vc in block_values:
                if (r, vc) in claimed:
                    continue
                # Not in `m` means covered by a merge or outside the box;
                # static means the user typed something there.
                if not _open(r, vc):
                    continue
                # The label that owns this slot is fixed by GEOMETRY — the
                # nearest label column to its left — and then that cell must
                # actually hold text. Searching leftward for the nearest label
                # that happens to be filled is wrong: in the side-by-side
                # layout "Bank Name | _ | ABA | _", a row carrying only
                # `Acct Type` in column A would hand column D to `Acct Type`
                # as well, inventing a second slot for a value the row does
                # not have. The right-hand pair is simply absent on that row.
                owners = [c for c in block_labels if c < vc]
                if not owners:
                    continue
                lc = max(owners)
                if (r, lc) not in static:
                    continue
                field_slots.append({
                    "slot_id": f"F{len(field_slots) + 1}",
                    "ref": _ref(r, vc), "row": r, "col": vc,
                    "row_label": m[(r, lc)],
                    "col_header": m.get((head, vc), "") if head is not None else "",
                    # A FIELD SLOT HAS NO DETECTABLE SECTION, and saying so is
                    # more honest than guessing. `_section_for` answers "is the
                    # line above a title", which is only meaningful when the
                    # line below is a band header — the case it is called for.
                    # Asked about an ordinary field it returns the PREVIOUS
                    # FIELD'S LABEL ("Statement No" in section "Account
                    # Holder"), because in a dense grid a lone label and a
                    # section title are the same shape. That answer reached the
                    # model in every slot prompt. It was empty for every field
                    # slot in all 11 committed templates before R1, so this
                    # keeps the prompts identical rather than inventing
                    # sections the grid cannot support.
                    "section": "",
                })
                label_cols.add(lc)
                value_cols.add(vc)

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
        "coverage": _coverage(m, static, wide, bands, field_slots, band_rows,
                              header_rows, section_rows, heading_rows, skipped,
                              *_gate_findings(grid, m, bands)),
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
