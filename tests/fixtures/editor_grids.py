"""Grids shaped the way the EDITOR saves them — not the way fixtures do.

THE THIRD TIME. R1 was the first: every template in the committed corpus had
its empty value cells materialised, by the old `extractTarget` tool or by
someone dragging a border, so the harness read 98.5% while everything a person
actually drew scored zero slots. `tests/gold/hand_drawn/` was the answer to
that one.

The hand-drawn set fixed the CELLS and left two other preconditions in place,
and both hid a defect that only real use could reach:

  colWidths   Every fixture in the repo saves `colWidths: []`. The editor
              initialises the array to `Array(26).fill(120)` and persists it
              verbatim, so a real template declares an explicit width for all
              26 columns. `_fit_columns` honours a stored width as the one the
              user dragged — so auto-fit never ran on any real template, every
              column came out 17 characters wide, and long labels were cut off.

  bands       D13's export-styling test used a form template, which has no
              band. `_write_slot_excel` skipped styling for every band row, so
              a TABLE template — the kind whose body a user draws a box around
              — lost exactly the part that was drawn.

Anything asserting how a saved template behaves should build it through
`as_editor_saves`, so a fixture cannot go on being easier than the product.
"""

#: DocAgentSpreadsheet.tsx — ROWS, COLS, DCW.
EDITOR_COLS = 26
EDITOR_DEFAULT_COL_PX = 120

BORDER = {"borderAll": True}
HEADING = {"bold": True, "align": "center", "bgColor": "#DDDDDD",
           "borderAll": True}


def as_editor_saves(grid, sized=None):
    """A grid carrying the dense `colWidths` array the editor writes.

    `sized` maps a column index to the width the user dragged it to; every
    other column gets the editor's untouched default, which is the state that
    made auto-fit unreachable.
    """
    widths = [EDITOR_DEFAULT_COL_PX] * EDITOR_COLS
    for c, px in (sized or {}).items():
        widths[c] = px
    out = dict(grid)
    out["colWidths"] = widths
    out.setdefault("merges", {})
    out.setdefault("repeatRows", [])
    out.setdefault("regions", [])
    return out


def bordered_table_grid():
    """A table template drawn the way a person draws one.

    A merged, centred title across the width; a shaded bordered heading row;
    three bordered body rows left empty for the slots to fill. The band is
    rows 2-4 and the borders on it are the ones D13 dropped.
    """
    cells = {
        "0,0": {"value": "QUARTERLY EARNINGS", "style": dict(HEADING)},
        "1,0": {"value": "Segment", "style": dict(HEADING)},
        "1,1": {"value": "2024", "style": dict(HEADING)},
        "1,2": {"value": "2023", "style": dict(HEADING)},
        "6,0": {"value": "Prepared By", "style": dict(BORDER)},
        "6,1": {"value": "", "style": dict(BORDER)},
    }
    for r in (2, 3, 4):
        for c in (0, 1, 2):
            cells[f"{r},{c}"] = {"value": "", "style": dict(BORDER)}
    return as_editor_saves({"cells": cells,
                            "merges": {"0,0": {"rows": 1, "cols": 3}}})


def long_label_grid():
    """A form template whose labels are longer than the editor's default width."""
    return as_editor_saves({"cells": {
        "0,0": {"value": "Meter Constant - A fixed value used when calculating"},
        "0,1": {"value": ""},
        "1,0": {"value": "Bill Account Number"},
        "1,1": {"value": ""},
    }})
