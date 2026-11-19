"""A document's total line written twice (Run C, C4.1).

The model returns a table's own total line ("Subtotal  $3,280.00") as a table
row, and the template ALSO has a Subtotal slot in the totals block directly
under that table, which it fills from the same line. The export then shows the
total twice: once as the band's last row, once in its slot.

`split_duplicate_totals` (called by slot extraction, beside the opening-row
gate) drops the band row when its normalised label equals the label of a slot
in the block under that table AND its amount equals that slot's value — the
slot keeps the value, so nothing the reader needs leaves the sheet, and the
drop is said in a note and counted (`validation.duplicate_total_row_count`).

When the labels match and the amounts DIFFER, both are kept and
`total_row_mismatch` (this module's validator) makes both exactly low: one of
the two readings is wrong and nothing says which.
"""
from __future__ import annotations

import re

from validators import ANY, FAIL, CheckResult, register

TOTAL_ROW_MISMATCH = "total_row_mismatch"

#: how many rows below a band its totals block may reach, when no other band
#: starts first
_BLOCK_DEPTH = 10


def norm_label(text) -> str:
    t = str(text or "").casefold().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def _amount(text):
    from amounts import parse_amount
    t = str(text or "").strip()
    if not t:
        return None
    a = parse_amount(t)
    return a.value if (a.ok and not a.percent) else None


def totals_below(table, tables, fields) -> dict:
    """{normalised label: field slot} for the field slots directly under a
    row band: below its last row, above the next band's heading, at most
    `_BLOCK_DEPTH` rows down."""
    if table.get("orientation") == "columns":
        return {}
    end = int(table.get("end_row", -1))
    nxt = [int(t.get("header_row", t.get("start_row", 0))) for t in tables
           if int(t.get("header_row", t.get("start_row", 0))) > end]
    limit = min(nxt + [end + _BLOCK_DEPTH + 1])
    out = {}
    for f in fields:
        row = f.get("row")
        if row is None or not (end < int(row) < limit):
            continue
        key = norm_label(f.get("row_label"))
        if key:
            out.setdefault(key, f)
    return out


def match_row(row, below) -> tuple:
    """(slot, row amounts) when one of the row's text cells is a totals label
    under the band, else (None, [])."""
    cells = [(k, v) for k, v in row.items() if not str(k).startswith("_")]
    slot = None
    for _k, v in cells:
        if _amount(v) is None and norm_label(v) in below:
            slot = below[norm_label(v)]
            break
    if slot is None:
        return None, []
    return slot, [a for _k, v in cells if (a := _amount(v)) is not None]


def split_duplicate_totals(table, rows, tables, fields, values):
    """(kept rows, dropped rows): a row dropped only when its label is a
    totals label under this band and one of its amounts EQUALS that slot's
    filled value."""
    below = totals_below(table, tables, fields)
    if not below or not rows:
        return rows, []
    kept, dropped = [], []
    for row in rows:
        slot, amounts = match_row(row, below)
        have = _amount(values.get(slot["ref"])) if slot else None
        if slot and have is not None and any(abs(a) == abs(have) for a in amounts):
            dropped.append(row)
        else:
            kept.append(row)
    return kept, dropped


def total_row_mismatch(ctx):
    """Labels match, amounts differ: both kept, both exactly low."""
    out = []
    for t in ctx.tables or []:
        below = totals_below(t, ctx.tables, ctx.fields)
        if not below:
            continue
        for i, row in enumerate((ctx.rows or {}).get(t["name"]) or []):
            if not isinstance(row, dict):
                continue
            slot, amounts = match_row(row, below)
            if slot is None or not amounts:
                continue
            have = _amount(ctx.values.get(slot["ref"]))
            if have is None or any(abs(a) == abs(have) for a in amounts):
                continue
            ref = f'{t["name"]}_rows[{i}]'
            shown = ", ".join(str(row.get(k)) for k in row
                              if not str(k).startswith("_") and _amount(row.get(k)) is not None)
            said = (f"{TOTAL_ROW_MISMATCH}: the table's line "
                    f"{slot['row_label']!r} reads {shown}, the "
                    f"{slot['row_label']!r} slot below the table reads "
                    f"{ctx.values.get(slot['ref'])} — both kept")
            out.append(CheckResult(
                "total_row_mismatch", FAIL, [slot["ref"], ref], TOTAL_ROW_MISMATCH,
                flags=[(slot["row_label"], ctx.values.get(slot["ref"]), said),
                       (f'{t["name"]}[{i}]', shown, said)],
                notes=[said]))
    return out


register(ANY, total_row_mismatch)
