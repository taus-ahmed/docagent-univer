"""Reviewer structure edits (Run T2, Stage 6): a person corrects the layout
of a document without retyping it.

An edit is stored with the document's words (`perception["structure_edits"]`)
as one entry of an ordered list - {id, op, page, ..., by, when} - and the
layout is ALWAYS rebuilt from the stored words, the plan and the edits in
that order: the same three give the same sheet, every time.

Two kinds, applied at two points:

  PLAN edits change what the plan says, so they survive re-placement:
    ignore_line     {line_id, reason}   the line leaves its region; listed as
                                        ignored with "reviewer: <reason>"
    unignore_line   {line_id}           an ignored or excluded line comes back,
                                        as a label/value region of its own
    reassign_column {region, word_ids,  the words go to that column of that
                     column}            table (0-based), wherever they print

  CELL edits change the placed grid of one page (A1 addresses), and carry the
  WORD IDS of the cell they were made on:
    move_cell       {cell, to}          the cell moves to an EMPTY cell
    merge_cells     {cells: [a, b]}     b's words join a's, in reading order;
                                        b is emptied
    split_cell      {cell, at, to}      words [at:] go to `to` (default: the
                                        cell to the right), which must be empty

A cell edit whose cell no longer holds the words it was made on (an earlier
edit or a new plan moved them) is NOT applied - it is reported, never
guessed at. Nothing here changes a word's text: every cell is still the
page's own words.
"""
from __future__ import annotations

import copy
import re

PLAN_OPS = ("ignore_line", "unignore_line", "reassign_column")
CELL_OPS = ("move_cell", "merge_cells", "split_cell")
OPS = PLAN_OPS + CELL_OPS
REQUIRED = {"ignore_line": ("line_id",), "unignore_line": ("line_id",),
            "reassign_column": ("region", "word_ids", "column"),
            "move_cell": ("cell", "to"), "merge_cells": ("cells",),
            "split_cell": ("cell", "at")}


def check_shape(edit) -> list:
    """Problems with an edit's shape (before it is tried on a page)."""
    if not isinstance(edit, dict):
        return ["an edit is an object"]
    op = edit.get("op")
    if op not in OPS:
        return [f"op must be one of {', '.join(OPS)}"]
    errs = [f"{op} needs {k}" for k in REQUIRED[op] if edit.get(k) in (None, "", [])]
    if not isinstance(edit.get("page"), int) or edit["page"] < 1:
        errs.append("page must be a page number (1, 2, ...)")
    for k in ("cell", "to"):
        if edit.get(k) is not None and not _rc(edit[k]):
            errs.append(f"{k} must be a cell address like B7")
    if op == "merge_cells" and (not isinstance(edit.get("cells"), list) or len(edit["cells"]) != 2
                                or not all(_rc(c) for c in edit["cells"])):
        errs.append("merge_cells needs cells: two addresses like [\"B7\", \"C7\"]")
    if op == "split_cell" and not (isinstance(edit.get("at"), int) and edit["at"] >= 1):
        errs.append("split_cell needs at: the index of the first word that moves (1 or more)")
    if op == "reassign_column" and not (isinstance(edit.get("column"), int) and edit["column"] >= 0):
        errs.append("reassign_column needs column: a 0-based column of the table")
    return errs


def _rc(a1):
    m = re.fullmatch(r"([A-Za-z]{1,3})([1-9]\d*)", str(a1 or ""))
    if not m:
        return None
    col = 0
    for ch in m.group(1).upper():
        col = col * 26 + (ord(ch) - 64)
    return int(m.group(2)) - 1, col - 1


# ── plan edits ───────────────────────────────────────────────────────────────

def apply_plan_edits(plan, page, edits) -> tuple:
    """(plan', [result]) - the page's PLAN edits applied in order to a copy."""
    plan = copy.deepcopy(plan)
    lines = {ln["id"]: ln for ln in page["lines"]}
    words = {w["id"] for w in page["words"]}
    out = []
    for e in edits:
        if e.get("op") not in PLAN_OPS:
            continue
        why = None
        lid = e.get("line_id")
        if e["op"] == "ignore_line":
            if lid not in lines:
                why = f"line {lid} is not on page {page['page']}"
            else:
                for r in plan.get("regions") or []:
                    for key in ("line_ids", "header_line_ids", "group_header_line_ids",
                                "carried_line_ids"):
                        if lid in (r.get(key) or []):
                            r[key] = [x for x in r[key] if x != lid]
                plan["regions"] = [r for r in plan.get("regions") or [] if r.get("line_ids")]
                plan["ignored"] = [i for i in plan.get("ignored") or [] if i.get("line_id") != lid]
                plan["ignored"].append({"line_id": lid, "reason": "reviewer: " + str(
                    e.get("reason") or "ignored by a reviewer")})
        elif e["op"] == "unignore_line":
            if lid not in lines:
                why = f"line {lid} is not on page {page['page']}"
            else:
                was = any(i.get("line_id") == lid for i in plan.get("ignored") or [])
                excl = [r for r in plan.get("regions") or []
                        if r.get("kind") in ("note", "side", "furniture", "form_copy")
                        and lid in (r.get("line_ids") or [])]
                if not was and not excl:
                    why = f"line {lid} is not left out"
                else:
                    plan["ignored"] = [i for i in plan.get("ignored") or []
                                       if i.get("line_id") != lid]
                    for r in excl:
                        r["line_ids"] = [x for x in r["line_ids"] if x != lid]
                    plan["regions"] = [r for r in plan.get("regions") or [] if r.get("line_ids")]
                    plan["regions"].append({"id": f"e{e.get('id')}", "kind": "kv",
                                            "line_ids": [lid]})
        elif e["op"] == "reassign_column":
            reg = next((r for r in plan.get("regions") or [] if r.get("id") == e["region"]), None)
            if reg is None or reg.get("kind") != "table":
                why = f"region {e['region']} is not a table on page {page['page']}"
            elif not set(e["word_ids"]) <= words:
                why = "some of those words are not on this page"
            elif e["column"] >= len(reg.get("columns") or []):
                why = f"table {e['region']} has {len(reg.get('columns') or [])} columns"
            else:
                ov = reg.setdefault("column_overrides", {})
                for wid in e["word_ids"]:
                    ov[wid] = int(e["column"])
        out.append({"id": e.get("id"), "op": e["op"], "applied": why is None, "why": why})
    return plan, out


# ── cell edits ───────────────────────────────────────────────────────────────

def apply_cell_edits(cells, page, edits, rebuild) -> list:
    """The page's CELL edits applied in order to `cells` (changed in place);
    [result]. `rebuild(row, col, words, like)` makes a cell from words, typed
    and styled the way placement types them."""
    by_word = {w["id"]: w for w in page["words"]}
    line_of = {wid: i for i, ln in enumerate(page["lines"]) for wid in ln["word_ids"]}
    out = []

    def at(a1):
        rc = _rc(a1)
        return next((c for c in cells if (c["row"], c["col"]) == rc), None) if rc else None

    def same(c, ids):
        return c is not None and (not ids or list(c.get("word_ids") or []) == list(ids))

    for e in edits:
        if e.get("op") not in CELL_OPS:
            continue
        why = None
        if e["op"] == "move_cell":
            c, dst = at(e["cell"]), _rc(e["to"])
            if not same(c, e.get("word_ids")):
                why = f"{e['cell']} no longer holds the words this edit was made on"
            elif at(e["to"]) is not None:
                why = f"{e['to']} is not empty"
            else:
                c["row"], c["col"] = dst
                c["edited"] = True
        elif e["op"] == "merge_cells":
            a, b = at(e["cells"][0]), at(e["cells"][1])
            ids = e.get("word_ids") or [None, None]
            if a is None or b is None or a is b:
                why = "both cells must hold words, and be two different cells"
            elif not (same(a, ids[0]) and same(b, ids[1])):
                why = "the cells no longer hold the words this edit was made on"
            else:
                ws = [by_word[i] for i in list(a["word_ids"]) + list(b["word_ids"]) if i in by_word]
                ws.sort(key=lambda w: (line_of.get(w["id"], 0), w["x0"]))
                new = rebuild(a["row"], a["col"], ws, a)
                cells[cells.index(a)] = new
                cells.remove(b)
        elif e["op"] == "split_cell":
            c = at(e["cell"])
            dst = _rc(e.get("to")) if e.get("to") else (c["row"], c["col"] + 1) if c else None
            if not same(c, e.get("word_ids")):
                why = f"{e['cell']} no longer holds the words this edit was made on"
            elif not (1 <= e["at"] < len(c.get("word_ids") or [])):
                why = f"{e['cell']} has {len(c.get('word_ids') or [])} word(s); at must be 1.." \
                      f"{len(c.get('word_ids') or []) - 1}"
            elif any((x["row"], x["col"]) == dst for x in cells):
                why = "the cell the second part goes to is not empty"
            else:
                ws = [by_word[i] for i in c["word_ids"] if i in by_word]
                first, second = ws[:e["at"]], ws[e["at"]:]
                cells[cells.index(c)] = rebuild(c["row"], c["col"], first, c)
                cells.append(rebuild(dst[0], dst[1], second, c))
        out.append({"id": e.get("id"), "op": e["op"], "applied": why is None, "why": why})
    return out


def for_page(edits, page_no) -> list:
    return [e for e in edits or [] if e.get("page") == page_no]
