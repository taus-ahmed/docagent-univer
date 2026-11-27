"""Structure engine (Run T1, Stage 3): a page laid out as a careful person
would type it - compact grids per region, one header row per table, every
value under its own heading, real types, nothing invented, nothing printed
lost, no background text.

The old Organized layout made every distinct left edge on the PAGE a sheet
column, so a statement page became nine columns with empty rows and values
under the wrong heading. Here each REGION gets its own compact grid, and
regions are stacked in page order one blank row apart.

    perception (Stage 2)   words, lines, removed background
          │
    geometry proposal      structure_geometry.proposal: candidate rows,
          │                blocks, candidate column boundaries (code)
    PLAN                   the model CONFIRMS / MERGES / LABELS the proposal
          │                (3b), or code builds it (3d fallback)
    validate (3c)          ids, overlaps, every line accounted for, and no
          │                boundary the geometry does not support unless the
          │                plan names the contradiction
    place (3e)             compact grids, formats, types, formula-safe text
          │
    verify (3f)            every kept word placed exactly once; plan vs
                           fallback agreement; table arithmetic

The model never supplies page TEXT: every cell's text is the perception's
words. The plan says only which lines form which region and where columns
fall, and the plan is small.
"""
from __future__ import annotations

import hashlib
import re
import statistics
from typing import Callable, Optional

import structure_geometry as G

PLAN_VERSION = 1
PROMPT_VERSION = "t1-structure-1"

KINDS = ("title", "kv", "table", "note", "side", "furniture", "form_copy")
EXCLUDED_KINDS = {"note": "note text (not copied)",
                  "side": "chart or side panel (not copied)",
                  "furniture": "page header/footer (not copied)",
                  "form_copy": "a duplicate copy of the form (not copied)"}
#: a geometry boundary and a plan boundary agree within this many points
BOUNDARY_TOL = 4.0
#: a page with more lines than this is planned in line-range pieces
MAX_LINES_PER_CALL = 160
EXCEL_CELL_MAX = 32767

REASON_NO_PERCEPTION = "no_perception"
REASON_NO_TEXT = "no_text_layer"
REASON_PLAN_INVALID = "plan_invalid_fallback_used"
REASON_NO_PLAN = "no_stored_plan_fallback_used"


# ══════════════════════════════════════════════════════════════════════════
# 3a — the plan schema
# ══════════════════════════════════════════════════════════════════════════
#
# {"version": 1, "page": n, "source": "model" | "fallback",
#  "regions": [{"id", "kind" (KINDS), "line_ids": [...],
#               "anchor": "A12"                       (set by placement),
#               # tables only:
#               "header_line_ids": [...],
#               "columns": [{"x0", "x1", "align"?}], "labels": [...],
#               "column_groups": k,      # one table printed k times across
#               "stacked_header": bool,  # a second heading line (sub-fields)
#               "group_header_line_ids": [...],  # ID + name lines, carried
#               "carried_line_ids": [...],       # running / carried-over lines
#               "continued": bool,       # headers printed on an earlier page
#              }],
#  "ignored": [{"line_id", "reason"}],
#  "contradictions": [{"region", "x", "why"}]}   # named breaks with geometry

def plan_schema_doc() -> str:
    """The plan format as the model is told it."""
    return (
        '{"regions": [{"id": "r1", "kind": "title|kv|table|note|side|furniture|form_copy", '
        '"line_ids": ["L1", ...], "header_line_ids": ["L5"], '
        '"columns": [{"x0": 40.0, "x1": 120.0}], "column_groups": 1, '
        '"stacked_header": false, "group_header_line_ids": [], '
        '"carried_line_ids": [], "continued": false}], '
        '"ignored": [{"line_id": "L9", "reason": "..."}], '
        '"contradictions": [{"region": "r3", "x": 212.0, "why": "..."}]}')


# ══════════════════════════════════════════════════════════════════════════
# 3c — the validator
# ══════════════════════════════════════════════════════════════════════════

def validate(plan, page, prop=None) -> list:
    """Every problem with `plan` for `page`, as sentences; [] when valid.

    Checked: every id exists; no line in two regions; every line assigned
    or ignored with a reason; regions do not overlap on the page; a table
    has columns; and every boundary between two of a table's columns is a
    boundary the GEOMETRY proposes (an alley or a shared right edge), or a
    column edge of the proposal - a boundary the page does not support is
    a contradiction, and allowed only when the plan names it."""
    errs = []
    if not isinstance(plan, dict) or not isinstance(plan.get("regions"), list):
        return ["the plan is not an object with a regions list"]
    ids = {ln["id"] for ln in page["lines"]}
    by = {ln["id"]: ln for ln in page["lines"]}
    seen = {}
    rids = set()
    for r in plan["regions"]:
        if not isinstance(r, dict):
            errs.append("a region is not an object")
            continue
        rid = r.get("id")
        if rid in rids:
            errs.append(f"region id {rid} is used twice")
        rids.add(rid)
        if r.get("kind") not in KINDS:
            errs.append(f"region {rid} has unknown kind {r.get('kind')!r}")
        for lid in r.get("line_ids") or []:
            if lid not in ids:
                errs.append(f"region {rid} names line {lid}, which does not exist")
            elif lid in seen:
                errs.append(f"line {lid} is in two regions ({seen[lid]} and {rid})")
            else:
                seen[lid] = rid
        for key in ("header_line_ids", "group_header_line_ids", "carried_line_ids"):
            for lid in r.get(key) or []:
                if lid not in (r.get("line_ids") or []):
                    errs.append(f"region {rid}: {key} names {lid}, not one of its lines")
        if r.get("kind") == "table":
            cols = r.get("columns") or []
            if not cols:
                errs.append(f"table {rid} has no columns")
            elif any(not isinstance(c, dict) or "x0" not in c or "x1" not in c
                     for c in cols):
                errs.append(f"table {rid}: every column needs x0 and x1")
    ign = {}
    for it in plan.get("ignored") or []:
        lid = (it or {}).get("line_id")
        if lid not in ids:
            errs.append(f"ignored line {lid} does not exist")
        elif not str((it or {}).get("reason") or "").strip():
            errs.append(f"ignored line {lid} has no reason")
        elif lid in seen:
            errs.append(f"line {lid} is both ignored and in region {seen[lid]}")
        else:
            ign[lid] = it["reason"]
    missing = [lid for lid in ids if lid not in seen and lid not in ign]
    if missing:
        errs.append("lines not assigned or ignored: " + ", ".join(sorted(missing, key=_lnum)[:20]))
    # regions must not overlap: two regions' boxes may share y only when
    # they are side by side
    boxes = []
    for r in plan["regions"]:
        ls = [by[i] for i in r.get("line_ids") or [] if i in by]
        if ls:
            boxes.append((r.get("id"), min(l["x0"] for l in ls), max(l["x1"] for l in ls),
                          min(l["top"] for l in ls), max(l["bottom"] for l in ls)))
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if a[1] < b[2] - 1 and b[1] < a[2] - 1 and a[3] < b[4] - 1 and b[3] < a[4] - 1:
                errs.append(f"regions {a[0]} and {b[0]} overlap on the page")
    errs += geometry_contradictions(plan, page, prop)["unnamed"]
    return errs


def _lnum(lid):
    m = re.search(r"(\d+)$", str(lid))
    return int(m.group(1)) if m else 0


def geometry_contradictions(plan, page, prop=None) -> dict:
    """{"named": [...], "unnamed": [...]}: table column boundaries the
    geometry does not support. A boundary is supported when it lies within
    BOUNDARY_TOL of a proposed boundary or proposed column edge of a block
    sharing the table's lines. Named = the plan lists it in
    `contradictions` (accepted, and flagged); unnamed = invalid."""
    prop = prop or G.proposal(page)
    named, unnamed = [], []
    said = [(c.get("region"), float(c.get("x") or 0)) for c in plan.get("contradictions") or []
            if isinstance(c, dict)]
    for r in plan.get("regions") or []:
        if not isinstance(r, dict) or r.get("kind") != "table":
            continue
        cols = [c for c in r.get("columns") or [] if isinstance(c, dict) and "x0" in c]
        if len(cols) < 2:
            continue
        lids = set(r.get("line_ids") or [])
        support = []
        for b in prop["blocks"]:
            if lids & set(b["line_ids"]) and b.get("columns"):
                support += [bd["x"] for bd in b["columns"]["boundaries"]]
                for c in b["columns"]["columns"]:
                    support += [c["x0"], c["x1"]]
        if not support:
            # the page proposes no columns for these lines at all; recompute
            # from the region's own row lines
            by = {ln["id"]: ln for ln in page["lines"]}
            dws = [G._words_of(page, by[i]) for i in lids if i in by]
            geo = G.columns_for(dws, (), G.gutter(page), G.word_gap(page))
            support = [bd["x"] for bd in geo["boundaries"]] + \
                [e for c in geo["columns"] for e in (c["x0"], c["x1"])]
        cols = sorted(cols, key=lambda c: float(c["x0"]))
        for a, b in zip(cols, cols[1:]):
            x = (float(a["x1"]) + float(b["x0"])) / 2
            if any(abs(x - s) <= BOUNDARY_TOL or float(a["x1"]) - BOUNDARY_TOL <= s <=
                   float(b["x0"]) + BOUNDARY_TOL for s in support):
                continue
            hit = any(rid == r.get("id") and abs(sx - x) <= BOUNDARY_TOL * 2
                      for rid, sx in said)
            msg = (f"table {r.get('id')}: a column boundary at x={x:.1f} that no "
                   f"alley or right edge on the page supports")
            (named if hit else unnamed).append(msg)
    return {"named": named, "unnamed": unnamed}


# ══════════════════════════════════════════════════════════════════════════
# 3b — the request
# ══════════════════════════════════════════════════════════════════════════

SYSTEM = ("You describe the STRUCTURE of one document page. You never copy or "
          "rewrite its text. Answer with JSON only.")


def build_request(page, prop, line_ids=None, carry=None) -> str:
    """The prompt: the numbered lines with coordinates, the geometry's own
    proposal (blocks, candidate column boundaries), and the plan format.
    The model confirms, merges or labels; it does not invent boundaries."""
    want = set(line_ids) if line_ids else None
    out = [f"Page {page['page']} ({page.get('width', 0):.0f} x "
           f"{page.get('height', 0):.0f} pt). Its printed lines, top to bottom, as "
           "id [x0-x1, top] text:"]
    for ln in page["lines"]:
        if want is not None and ln["id"] not in want:
            continue
        out.append(f"{ln['id']} [{ln['x0']:.0f}-{ln['x1']:.0f}, {ln['top']:.0f}] {ln['text']}")
    out.append("")
    out.append("PROPOSAL computed from the geometry (blocks separated by white "
               "space; candidate column boundaries are x positions no row's ink "
               "crosses, or shared right edges of right-aligned numbers):")
    for b in prop["blocks"]:
        if want is not None and not (set(b["line_ids"]) & want):
            continue
        s = f"{b['id']}: lines {b['line_ids'][0]}..{b['line_ids'][-1]}"
        if b.get("columns"):
            cols = "; ".join(f"[{c['x0']:.0f}-{c['x1']:.0f}{' right' if c['align'] == 'right' else ''}]"
                             for c in b["columns"]["columns"])
            s += f"; table-like, candidate columns {cols}"
            if b.get("header_line_ids"):
                s += f"; heading line {b['header_line_ids'][0]}"
        out.append(s)
    if prop.get("side_split"):
        out.append(f"A vertical alley at x={prop['side_split']:.0f} separates a side zone.")
    if carry:
        out.append(f"Context from the previous part of this page: {carry}")
    out.append("")
    out.append("RULES")
    out.append("- Put EVERY line id in exactly one region, or in 'ignored' with a reason.")
    out.append("- Table columns must be candidate columns, or adjacent candidates MERGED "
               "(x0 of the first, x1 of the last). Do not invent a boundary. If the "
               "page truly needs one the proposal lacks, list it in 'contradictions' "
               "with its x and why.")
    out.append("- Exclude note/paragraph text (kind note), charts and side panels "
               "(side), page headers/footers (furniture), duplicate form copies (form_copy).")
    out.append("- A heading printed several times across one table (the same headings "
               "repeated side by side) is ONE table: give column_groups = the repeat count.")
    out.append("- Lines that only carry a group identifier and name go in "
               "group_header_line_ids; a second heading line under the first sets "
               "stacked_header; a table whose headings were printed on an earlier "
               "page is continued.")
    out.append("Answer with exactly this JSON shape:")
    out.append(plan_schema_doc())
    return "\n".join(out)


def plan_key(file_hash, model, page_no) -> str:
    return hashlib.sha256(f"{file_hash}|{model}|{PROMPT_VERSION}|{PLAN_VERSION}|{page_no}"
                          .encode()).hexdigest()


def ask_plan(ask: Callable, page, prop=None, log=lambda s: None) -> dict:
    """{"plan", "source", "errors", "attempts"} for one page.

    ``ask(prompt, line_ids)`` makes ONE model call and returns
    ``(parsed, resp)``. A page with more than MAX_LINES_PER_CALL lines is
    planned in line-range pieces through call_sizing.ask_adaptive (halved
    on a size failure) and the pieces' regions merged. An invalid plan is
    asked ONCE more with its errors named; still invalid -> the
    deterministic fallback, with the errors kept."""
    import call_sizing as CS
    prop = prop or G.proposal(page)
    ids = [ln["id"] for ln in page["lines"]]
    chunks = [ids[i:i + MAX_LINES_PER_CALL] for i in range(0, len(ids), MAX_LINES_PER_CALL)] \
        or [[]]
    calls = {"n": 0}

    by_line = {ln["id"]: ln for ln in page["lines"]}

    def chunk_text(k):
        # the piece as its printed lines, so a row-range split cuts at a
        # line that starts a row (call_sizing.row_cut reads dates/amounts)
        return "\n".join(f"{lid} {by_line[lid]['text']}" for lid in chunks[k])

    def ids_of(pg, text):
        if text is None:
            return [lid for k in pg for lid in chunks[k]]
        return [ln.split(" ", 1)[0] for ln in text.splitlines() if ln.strip()]

    def plan_of(extra=""):
        pieces, failed = [], {}
        for k in range(len(chunks)):
            def one(pg, text=None, carry=None, part=None):
                calls["n"] += 1
                lids = ids_of(pg, text)
                return ask(build_request(page, prop, lids, carry=carry) + extra, lids)
            res = CS.ask_adaptive(one, [k], page_text=chunk_text)
            pieces += res["pieces"]
            failed.update(res["failed"])
        if failed:
            return None, f"pieces failed: {sorted(failed)}"
        merged = {"regions": [], "ignored": [], "contradictions": []}
        single = len(pieces) == 1
        for n, (_pg, _part, parsed) in enumerate(pieces):
            pre = "" if single else f"p{n + 1}"
            for r in parsed.get("regions") or []:
                if isinstance(r, dict):
                    merged["regions"].append({**r, "id": f"{pre}{r.get('id')}"})
            merged["ignored"] += [i for i in parsed.get("ignored") or [] if isinstance(i, dict)]
            merged["contradictions"] += [
                {**c, "region": f"{pre}{c.get('region')}"}
                for c in parsed.get("contradictions") or [] if isinstance(c, dict)]
        return merged, None

    plan, why = plan_of()
    errors = validate(plan, page, prop) if plan is not None else [why or "no plan"]
    if errors:
        log(f"page {page['page']}: plan invalid ({len(errors)} problem(s)); asked once more")
        extra = ("\n\nYOUR PREVIOUS PLAN WAS INVALID:\n- " + "\n- ".join(errors[:30]) +
                 "\nFix every problem and answer the whole plan again.")
        plan, why = plan_of(extra)
        errors2 = validate(plan, page, prop) if plan is not None else [why or "no plan"]
        if errors2:
            log(f"page {page['page']}: plan still invalid; deterministic fallback used")
            return {"plan": G.fallback_plan(page), "source": "fallback",
                    "errors": errors2, "first_errors": errors, "calls": calls["n"]}
        errors = []
    plan = {"version": PLAN_VERSION, "page": page["page"], "source": "model", **plan}
    return {"plan": plan, "source": "model", "errors": [], "calls": calls["n"],
            "named": geometry_contradictions(plan, page, prop)["named"]}


# ══════════════════════════════════════════════════════════════════════════
# 3e — placement
# ══════════════════════════════════════════════════════════════════════════

def _a1(row, col) -> str:
    from openpyxl.utils import get_column_letter
    return f"{get_column_letter(col + 1)}{row + 1}"


def safe_text(v):
    """Text a spreadsheet must never read as a formula: = + - @ at the start
    of a TEXT value. The cell is marked `text` for the writer, never
    altered. Over-long text is cut at Excel's cell limit (and said)."""
    if not isinstance(v, str):
        return v, False, False
    cut = len(v) > EXCEL_CELL_MAX
    if cut:
        v = v[:EXCEL_CELL_MAX]
    return v, v[:1] in ("=", "+", "-", "@"), cut


def _style(words, body):
    import organized_layout as OL
    sizes = [w.get("size") or body for w in words]
    return {"bold": any(w.get("bold") for w in words) and all(
                w.get("bold") for w in words if w["text"].strip()),
            "italic": all(w.get("italic") for w in words) if words else False,
            "size": OL.sheet_size(statistics.median(sizes) if sizes else body, body)}


def _cell(row, col, words, body, order, label=None, text=None, **kw):
    import organized_layout as OL
    t = " ".join(w["text"] for w in words) if text is None else text
    val, fmt = OL.typed(t, order, label)
    val, as_text, cut = safe_text(val)
    c = {"row": row, "col": col, "value": val, "text": t, **_style(words, body),
         "word_ids": [w["id"] for w in words]}
    if fmt:
        c["number_format"] = fmt
    if as_text:
        c["as_text"] = True
    if cut:
        c["truncated"] = True
    c.update(kw)
    # the old layout's cell vocabulary, so one instrument measures both
    c["kind"] = {"header": "header", "label": "label", "group": "value",
                 "value": "value"}.get(c.get("role"), "text")
    return c


def split_pairs(seg) -> list:
    """[(words, role)] for one segment: EVERY `Label:` in it starts a pair,
    not only the first (`Ref: AB-12 Date: 01/02/2030 - 01/03/2030`
    is two pairs). A later label runs back from its colon word to just after
    the last word of the value before it that carries a digit; with no digit
    to stop at, the label is the colon word alone (`Blue Ltd Phone:`
    keeps `Blue Ltd` as the value)."""
    colons = [i for i, w in enumerate(seg) if w["text"].endswith(":") and len(w["text"]) > 1]
    if not colons:
        return [(seg, "text")]
    out = []
    start = 0
    for n, k in enumerate(colons):
        lab0 = start
        if n:
            prev = colons[n - 1]
            digits = [i for i in range(prev + 1, k) if any(ch.isdigit() for ch in seg[i]["text"])]
            lab0 = digits[-1] + 1 if digits else k
            if lab0 > prev + 1:
                out.append((seg[prev + 1:lab0], "value"))
        out.append((seg[lab0:k + 1], "label"))
        start = k + 1
    if start < len(seg):
        out.append((seg[start:], "value"))
    return out


def _kv_rows(page, lines, by_word, gut, dropped=None):
    """A label/value region: each printed line one row, pairs side by side,
    the label exactly as printed WITH its colon, its value in the next
    cell. A segment that is page furniture on its own (`Page 2 of 5`
    printed beside a field) is left out and put in `dropped`."""
    rows = []
    for ln in lines:
        segs = G.segments(page, ln, gut)
        cells = []
        for seg in segs:
            if len(segs) > 1 and G.is_furniture(" ".join(w["text"] for w in seg)):
                if dropped is not None:
                    dropped.append(seg)
                continue
            cells += split_pairs(seg)
        if cells:
            rows.append((ln, cells))
    return rows


def place_region(region, page, row0, order, body, gut, prev_tables):
    """[cells] for one region starting at sheet row `row0`, column A, and
    the number of rows it used."""
    by_line = {ln["id"]: ln for ln in page["lines"]}
    by_word = {w["id"]: w for w in page["words"]}
    lines = [by_line[i] for i in region.get("line_ids") or [] if i in by_line]
    cells = []
    kind = region.get("kind")
    if kind == "title":
        ws = [by_word[i] for ln in lines for i in ln["word_ids"]]
        cells.append(_cell(row0, 0, ws, body, order, bold=True))
        return cells, 1
    if kind == "kv":
        r = row0
        open_vals = []          # [(x0, words list, label)] values the next line may continue
        prev_ln = None
        dropped = region.setdefault("_dropped", [])
        for ln, segcells in _kv_rows(page, lines, by_word, gut, dropped):
            # rule 5: a label-free piece directly under a value, starting at
            # that value's left edge, is the value wrapped onto the next line
            size = ln.get("size") or body
            near = prev_ln is not None and ln["baseline"] - prev_ln["baseline"] <= 1.6 * size                 and not any(role == "label" for _ws, role in segcells)
            rest, cont = [], []
            for ws, role in segcells:
                hit = next((ov for ov in open_vals if near
                            and abs(ws[0]["x0"] - ov[0]) <= 3.0), None)
                if hit is not None:
                    hit[1].extend(ws)
                    cont.append(hit)
                else:
                    rest.append((ws, role))
            prev_ln = ln
            if not rest:
                open_vals = cont
                continue
            new_open = list(cont)
            for col, (ws, role) in enumerate(rest):
                lab = " ".join(w["text"] for w in rest[col - 1][0]) if col and role == "value" \
                    else None
                vws = list(ws)
                cells.append({"_ws": vws, "_r": r, "_col": col, "_label": lab, "_role": role})
                if role == "value":
                    new_open.append((ws[0]["x0"], vws, lab))
            open_vals = new_open
            r += 1
        cells = [_cell(c["_r"], c["_col"], c["_ws"], body, order, label=c["_label"],
                       role=c["_role"]) for c in cells]
        return cells, r - row0
    if kind == "table":
        return _place_table(region, page, lines, row0, order, body, prev_tables)
    return [], 0


def _same_labels(a, b) -> bool:
    import perception as P
    ka = [P.loose_key(x) for x in a or []]
    kb = [P.loose_key(x) for x in b or []]
    return bool(ka) and any(ka) and ka == kb


def _is_tail(ln, prev_line, parts, n, groups_rows, pitch) -> bool:
    """A line with no date and no amount continues the row above it only
    when it sits closer to that row than rows sit to each other (under
    0.85 of the table's row pitch, and under 1.5x its own text size), and
    only in columns where that row already has text: `REF 77` under a
    description is its tail; `Fees` one blank line lower is a section, and
    a footnote under the amount columns is neither."""
    size = ln.get("size") or 10.0
    gap = ln["baseline"] - prev_line["baseline"]
    for ci in parts:
        g = ci // n
        if not groups_rows[g] or not groups_rows[g][-1].get(ci % n):
            return False
    limit = 1.5 * size if pitch is None else min(1.5 * size, 0.85 * pitch)
    if gap <= limit:
        return True
    # printed at the row pitch itself (a statement setting every line on one
    # grid): still a tail when it starts RIGHT of the table's first column
    # (it holds no date or amount, or it would be a row) - a section title
    # starts at the left margin
    return pitch is not None and gap <= 1.1 * pitch and 0 not in parts


_RANGE_END = re.compile(r"(?:^|\s)(?:-|\u2013|\u2014|to|through|thru)$", re.I)


def _range_continues(parts, n, groups_rows, ln, prev_line) -> bool:
    """The line's words sit in ONE column, directly under a row whose cell
    in that column ends with a range connector (`-`, `to`): the rest of
    that value, wrapped (a pay period printed over two lines)."""
    if len(parts) != 1:
        return False
    ci = next(iter(parts))
    g = ci // n
    if not groups_rows[g]:
        return False
    prev = groups_rows[g][-1].get(ci % n)
    if not prev:
        return False
    size = ln.get("size") or 10.0
    if ln["baseline"] - prev_line["baseline"] > 1.5 * size:
        return False
    return bool(_RANGE_END.search(" ".join(w["text"] for w in prev)))


def _place_table(region, page, lines, row0, order, body, prev_tables):
    line_of = {wid: li for li, ln in enumerate(page["lines"]) for wid in ln["word_ids"]}
    cols = sorted([dict(c) for c in region.get("columns") or []], key=lambda c: c["x0"])
    if region.get("continued") and prev_tables and not region.get("labels"):
        prev = prev_tables[-1]
        cols = [dict(c) for c in prev["columns"]]
        region = {**region, "labels": prev.get("labels"),
                  "column_groups": prev.get("column_groups", 1)}
    for c in cols:
        c.setdefault("align", "left")
    head_ids = set(region.get("header_line_ids") or [])
    group_ids = set(region.get("group_header_line_ids") or [])
    k = max(1, int(region.get("column_groups") or 1))
    n = len(cols) // k if len(cols) % k == 0 else len(cols)
    if n == len(cols):
        k = 1
    labels = list(region.get("labels") or [])
    if not labels and head_ids:
        labels = G.header_labels([G._words_of(page, ln) for ln in lines
                                  if ln["id"] in head_ids][:1], cols)
        for h2 in [ln for ln in lines if ln["id"] in head_ids][1:]:
            sub = G.header_labels([G._words_of(page, h2)], cols)
            labels = [f"{a} {b}".strip() if b else a for a, b in zip(labels, sub)]
    labels = (labels + [""] * len(cols))[:len(cols)]
    groups_rows = [[] for _ in range(k)]          # per column group: [row cells]
    group_cur = None
    has_groups = bool(group_ids)
    prev_line = None
    feats = {}
    body_lines = [ln for ln in lines if ln["id"] not in head_ids and ln["id"] not in group_ids]
    row_bases = [ln["baseline"] for ln in body_lines if G.is_row_line(G.features(page, ln))]
    pitches = [b - a for a, b in zip(row_bases, row_bases[1:]) if b - a > 0.5]
    pitch = statistics.median(pitches) if pitches else None
    for ln in lines:
        if ln["id"] in head_ids:
            continue
        ws = G._words_of(page, ln)
        f = G.features(page, ln)
        feats[ln["id"]] = f
        if ln["id"] in group_ids:
            group_cur = (ws[:1], ws[1:])
            prev_line = None
            continue
        parts = {}
        if f["pair"]:
            # a `Label: value` line inside a table is placed by PAIRS: a label
            # stays whole in the column of its first word, its value goes to
            # the column of the value's first word (the next free column when
            # that is the label's own)
            for chunk, _role in split_pairs(ws):
                ci = G.column_of(chunk[0], cols)
                while ci in parts and ci + 1 < len(cols):
                    ci += 1
                parts.setdefault(ci, []).extend(chunk)
        else:
            for w in ws:
                ci = G.column_of(w, cols)
                parts.setdefault(ci, []).append(w)
        row_line = G.is_row_line(f)
        if prev_line is not None and _range_continues(parts, n, groups_rows, ln, prev_line):
            # `01/02/30 -` over `01/03/30`: the second half of a range
            for ci, cws in parts.items():
                groups_rows[ci // n][-1].setdefault(ci % n, []).extend(cws)
            prev_line = ln
            continue
        if not row_line and prev_line is not None and _is_tail(ln, prev_line, parts, n,
                                                               groups_rows, pitch):
            # a wrapped line: no date, no amount, directly under a row (closer
            # than rows are to each other) and only in columns that row has
            # text in -> joins that row, cell by cell
            for ci, cws in parts.items():
                g = ci // n
                if groups_rows[g]:
                    groups_rows[g][-1].setdefault(ci % n, []).extend(cws)
            prev_line = ln
            continue
        if not row_line and not f["pair"]:
            # a section line inside the table (`Fees`, `Other Items`): its
            # own row, never glued onto the row above
            row = {ci: cws for ci, cws in parts.items()}
            row["_section"] = True
            groups_rows[0].append(row)
            prev_line = None
            continue
        for g in range(k):
            sub = {ci % n: cws for ci, cws in parts.items() if ci // n == g}
            if sub:
                row = dict(sub)
                if group_cur is not None:
                    row["_group"] = group_cur
                groups_rows[g].append(row)
        prev_line = ln
    rows = [r for g in groups_rows for r in g]     # group-major reading order
    lead = 2 if has_groups else 0
    cells = []
    r = row0
    prev = prev_tables[-1] if prev_tables else None
    # a heading reprinted over a CONTINUATION: the same headings, this the
    # first table of its page, and the earlier table the last thing placed
    # on the page before (an explainer page showing the same table is not
    # continued by the statement after it)
    reprinted = bool(prev) and _same_labels(labels, prev.get("labels")) and         prev.get("page") == page["page"] - 1 and bool(prev.get("last_on_page"))
    if reprinted:
        # the same heading printed again over a continuation (every page of
        # a statement reprints it): written once, above the first rows
        region["reprinted_header"] = True
    if (not region.get("continued") or not prev_tables) and not reprinted:
        hw = {}
        for ln in lines:
            if ln["id"] in head_ids:
                for w in G._words_of(page, ln):
                    ci = G.column_of(w, [dict(c, align="left") for c in cols])
                    hw.setdefault(ci % n, []).append(w)
        for ci in range(n):
            ws = sorted(hw.get(ci, []), key=lambda w: (w["top"], w["x0"]))
            c = _cell(r, lead + ci, ws, body, order, text=labels[ci],
                      bold=True, align="center", role="header", header=True)
            cells.append(c)
        if k > 1:
            # the heading words of the repeated groups are the same headings:
            # placed once, counted once
            for c in cells:
                c["counted_ids"] = c["word_ids"]
        r += 1
    for row in rows:
        if has_groups and row.get("_group"):
            gid, gname = row["_group"]
            # a group line's identifier is an IDENTIFIER: its printed text,
            # never a number
            if gid:
                cells.append(_cell(r, 0, gid, body, None, bold=True, role="group",
                                   text=None, label="#"))
                cells[-1]["value"] = " ".join(w["text"] for w in gid)
                cells[-1].pop("number_format", None)
            if gname:
                cells.append(_cell(r, 1, gname, body, order, bold=True, role="group"))
        for ci in range(n):
            ws = row.get(ci)
            if not ws:
                continue
            ws = sorted(ws, key=lambda w: (line_of.get(w["id"], 0), w["x0"]))
            align = "right" if cols[ci].get("align") == "right" else None
            c = _cell(r, lead + ci, ws, body, order, label=labels[ci], role="value")
            if align:
                c["align"] = align
            cells.append(c)
        r += 1
    # group lines' words are placed in the group cells of EVERY row they
    # head; for verification they count once, on their first appearance
    seen = set()
    for c in cells:
        if c.get("role") == "group":
            ids = [i for i in c["word_ids"] if i not in seen]
            seen.update(c["word_ids"])
            c["counted_ids"] = ids
    region["_placed_columns"] = cols
    region["_labels"] = labels
    region["_rows"] = rows
    region["_n"] = n
    return cells, r - row0


def place_page(page, plan, order=None, prev_tables=None) -> dict:
    """{"cells", "excluded": [{text, reason}], "regions": [region + anchor]}
    for one page: regions in page order, each its own compact grid starting
    in column A, one blank row between regions."""
    prev_tables = prev_tables if prev_tables is not None else []
    by_line = {ln["id"]: ln for ln in page["lines"]}
    sizes = [ln["size"] for ln in page["lines"] if ln.get("size")]
    body = statistics.median(sizes) if sizes else 10.0
    gut = G.gutter(page)
    regions = sorted([dict(r) for r in plan.get("regions") or []],
                     key=lambda r: min((by_line[i]["top"] for i in r.get("line_ids") or []
                                        if i in by_line), default=1e9))
    cells, excluded, placed = [], [], []
    row = 0
    for reg in regions:
        if reg.get("kind") in EXCLUDED_KINDS:
            for lid in reg.get("line_ids") or []:
                if lid in by_line:
                    excluded.append({"line_id": lid, "text": by_line[lid]["text"],
                                     "reason": EXCLUDED_KINDS[reg["kind"]]})
            continue
        cs, used = place_region(reg, page, row, order, body, gut, prev_tables)
        for seg in reg.pop("_dropped", None) or []:
            excluded.append({"word_ids": [w["id"] for w in seg],
                             "text": " ".join(w["text"] for w in seg),
                             "reason": "page furniture (a page number beside a field)"})
        if not cs:
            continue
        reg["anchor"] = _a1(row, 0)
        cells += cs
        placed.append(reg)
        if reg.get("kind") == "table":
            prev_tables.append({"columns": reg.get("_placed_columns") or reg.get("columns"),
                                "labels": reg.get("_labels"),
                                "column_groups": reg.get("column_groups", 1),
                                "page": page["page"]})
        row += used + 1
    if prev_tables and prev_tables[-1].get("page") == page["page"]:
        # whether this page ENDS with its last table (nothing placed after
        # it): only then can the next page's first table continue it
        prev_tables[-1]["last_on_page"] = bool(placed) and placed[-1].get("kind") == "table"
    for it in plan.get("ignored") or []:
        lid = it.get("line_id")
        if lid in by_line:
            excluded.append({"line_id": lid, "text": by_line[lid]["text"],
                             "reason": it.get("reason")})
    for rm in page.get("removed") or []:
        excluded.append({"word_id": rm["id"], "text": rm["text"],
                         "reason": "background: " + ", ".join(rm["reasons"])})
    _rules_to_cells(page, plan, cells)
    return {"cells": cells, "excluded": excluded, "regions": placed}


def _rules_to_cells(page, plan, cells):
    """Underline (a stroke just under a cell's words, 80% of their width)
    and thick rules (1.5 pt+, 30% of the page) on the row printed above."""
    rules = page.get("rules") or []
    if not rules:
        return
    by_word = {w["id"]: w for w in page["words"]}
    width = float(page.get("width") or 612)
    rows_bottom = {}
    for c in cells:
        ws = [by_word[i] for i in c.get("word_ids") or [] if i in by_word]
        if not ws:
            continue
        x0, x1 = min(w["x0"] for w in ws), max(w["x1"] for w in ws)
        bot = max(w["bottom"] for w in ws)
        rows_bottom.setdefault(c["row"], []).append(bot)
        for rx0, rx1, y, th in rules:
            if th < 1.5 and 0 <= y - bot <= 3 and \
                    min(rx1, x1) - max(rx0, x0) >= 0.8 * (x1 - x0):
                c["underline"] = True
    for rx0, rx1, y, th in rules:
        if th >= 1.5 and rx1 - rx0 >= 0.3 * width:
            above = [(r, max(b)) for r, b in rows_bottom.items() if max(b) <= y]
            if above:
                r = max(above, key=lambda t: t[1])[0]
                for c in cells:
                    if c["row"] == r:
                        c["border_bottom"] = "thick"


# ══════════════════════════════════════════════════════════════════════════
# 3f — verification, independent of the plan
# ══════════════════════════════════════════════════════════════════════════

def verify(page, plan, placed, fallback=None) -> list:
    """Flags (sentences) about a placed page. Never changes a value and
    never marks one Low: what it finds is said, for a person to look at."""
    flags = []
    kept = set()
    excl_lines = {e["line_id"] for e in placed["excluded"] if e.get("line_id")}
    excl_words = {i for e in placed["excluded"] for i in e.get("word_ids") or []}
    for ln in page["lines"]:
        if ln["id"] not in excl_lines:
            kept.update(i for i in ln["word_ids"] if i not in excl_words)
    count = {}
    for c in placed["cells"]:
        for i in c.get("counted_ids", c.get("word_ids") or []):
            count[i] = count.get(i, 0) + 1
    by_word = {w["id"]: w for w in page["words"]}
    lost = [i for i in kept if count.get(i, 0) == 0]
    placed["unplaced"] = [by_word[i]["text"] for i in sorted(lost) if i in by_word]
    twice = [i for i, n in count.items() if n > 1]
    if lost:
        flags.append(f"page {page['page']}: {len(lost)} printed word(s) not placed: "
                     + " ".join(by_word[i]["text"] for i in sorted(lost)[:12] if i in by_word))
    if twice:
        flags.append(f"page {page['page']}: {len(twice)} word(s) placed more than once: "
                     + " ".join(by_word[i]["text"] for i in sorted(twice)[:12] if i in by_word))
    for c in placed["cells"]:
        if isinstance(c.get("value"), str) and sum(
                1 for t in c["value"].split() if G.is_amount(t)) >= 2:
            flags.append(f"page {page['page']} {_a1(c['row'], c['col'])}: two figures in one "
                         f"cell ({c['value']})")
        if c.get("truncated"):
            flags.append(f"page {page['page']} {_a1(c['row'], c['col'])}: text longer than "
                         f"a spreadsheet cell holds; cut at {EXCEL_CELL_MAX} characters")
    if fallback is not None and plan.get("source") == "model":
        flags += disagreement(page, plan, fallback)
    for reg in placed["regions"]:
        if reg.get("kind") == "table":
            flags += arithmetic(page, reg)
    return flags


def _assign(page, plan):
    """word id -> (table id, column index, row line id) for every table."""
    out = {}
    by_line = {ln["id"]: ln for ln in page["lines"]}
    for r in plan.get("regions") or []:
        if r.get("kind") != "table":
            continue
        cols = sorted([c for c in r.get("columns") or [] if "x0" in c], key=lambda c: c["x0"])
        heads = set(r.get("header_line_ids") or []) | set(r.get("group_header_line_ids") or [])
        for lid in r.get("line_ids") or []:
            if lid in heads or lid not in by_line:
                continue
            for w in G._words_of(page, by_line[lid]):
                out[w["id"]] = (r.get("id"), G.column_of(w, cols) if cols else 0, lid)
    return out


def disagreement(page, plan, fallback) -> list:
    """The model's plan and the geometry's own plan, compared on what a
    reader would notice: a word in a different COLUMN (by position among
    the table's columns), or a word in a table under one plan and not the
    other. Each disagreement names both readings."""
    a, b = _assign(page, plan), _assign(page, fallback)
    by_word = {w["id"]: w for w in page["words"]}
    col_diff = [i for i in set(a) & set(b) if a[i][1] != b[i][1]]
    only_a = [i for i in set(a) - set(b)]
    only_b = [i for i in set(b) - set(a)]
    flags = []
    if col_diff:
        ex = col_diff[0]
        flags.append(f"page {page['page']}: the plan and the geometry put {len(col_diff)} "
                     f"word(s) in different columns (e.g. '{by_word[ex]['text']}': plan "
                     f"column {a[ex][1] + 1}, geometry column {b[ex][1] + 1})")
    if only_a or only_b:
        flags.append(f"page {page['page']}: table membership differs - {len(only_a)} word(s) "
                     f"in a table only under the plan, {len(only_b)} only under the geometry")
    return flags


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def arithmetic(page, region) -> list:
    """Table arithmetic, found by structure not by name: a column B that is
    a RUNNING balance of another column A (B[i] = B[i-1] +/- A[i] on most
    rows) is checked on every row, and a row that breaks it is named."""
    rows = region.get("_rows") or []
    n = region.get("_n") or 0
    labels = region.get("_labels") or []
    if len(rows) < 3 or n < 2:
        return []
    import organized_layout as OL

    def val(row, ci):
        ws = row.get(ci)
        if not ws:
            return None
        v, _f = OL.typed(" ".join(w["text"] for w in ws))
        return _num(v)
    table = [[val(r, ci) for ci in range(n)] for r in rows]
    flags = []
    for bi in range(n):
        for ai in range(n):
            if ai == bi:
                continue
            ok = bad = 0
            bad_rows = []
            for i in range(1, len(table)):
                p, cur, d = table[i - 1][bi], table[i][bi], table[i][ai]
                if p is None or cur is None or d is None:
                    continue
                if abs(p + d - cur) < 0.005 or abs(p - d - cur) < 0.005:
                    ok += 1
                else:
                    bad += 1
                    bad_rows.append(i + 1)
            if ok >= 3 and ok > bad and bad:
                flags.append(f"page {page['page']}: running total in column "
                             f"'{labels[bi] or bi + 1}' does not follow on row(s) "
                             f"{bad_rows[:5]} of the table")
    return flags


# ══════════════════════════════════════════════════════════════════════════
# 3g/3h — the document
# ══════════════════════════════════════════════════════════════════════════

def layout_document(perc, plans=None, order=None) -> dict:
    """The structure layout of a perception (`perception.read_document` or a
    stored one): {"pages": [cells], "skipped", "flags", "excluded",
    "plans": {page: plan}, "plan_source": {page: source}, "anchors"} - the
    `pages` list is what `excel_organized.write_layout` writes.

    `plans` maps page number -> a stored model plan; a page without one is
    laid out from the deterministic fallback and says so."""
    out = {"pages": [], "skipped": [], "flags": [], "excluded": [], "plans": {},
           "plan_source": {}, "anchors": {}, "version": PLAN_VERSION}
    if not perc or not perc.get("pages"):
        out["skipped"].append(REASON_NO_PERCEPTION)
        return out
    if order is None:
        order = _order(perc)
    prev_fb = None
    prev_tables = []
    for page in perc["pages"]:
        if not page.get("lines"):
            out["skipped"].append(f"page {page['page']}: {REASON_NO_TEXT}")
            continue
        if (page.get("quality") or {}).get("source") == "ocr" and \
                not any(w.get("origin") == "widget" for w in page["words"]):
            out["skipped"].append(f"page {page['page']}: {REASON_NO_TEXT} (the text layer "
                                  f"is unreadable; OCR is not connected to this layout)")
            continue
        fb = G.fallback_plan(page, prev_fb)
        stored = (plans or {}).get(page["page"]) or (plans or {}).get(str(page["page"]))
        plan, source = fb, "fallback"
        if stored:
            errs = validate(stored, page)
            if errs:
                out["flags"].append(f"page {page['page']}: stored plan invalid "
                                    f"({errs[0]}); {REASON_PLAN_INVALID}")
            else:
                plan, source = stored, "model"
                for msg in geometry_contradictions(stored, page)["named"]:
                    out["flags"].append(f"page {page['page']}: the plan departs from the "
                                        f"geometry and says why - {msg}")
        placed = place_page(page, plan, order, prev_tables)
        out["flags"] += verify(page, plan, placed, fb if source == "model" else None)
        out["excluded"] += [{**e, "page": page["page"]} for e in placed["excluded"]]
        out.setdefault("unplaced", []).extend(placed.get("unplaced") or [])
        out["plans"][page["page"]] = plan
        out["plan_source"][page["page"]] = source
        out["anchors"][page["page"]] = {r["id"]: r.get("anchor") for r in placed["regions"]}
        if placed["cells"]:
            out["pages"].append(placed["cells"])
        last = [r for r in fb["regions"] if r["kind"] == "table"]
        prev_fb = last[-1] if last else prev_fb
    if not out["pages"] and not out["skipped"]:
        out["skipped"].append(REASON_NO_TEXT)
    return out


def _order(perc):
    import dates as D
    texts = [w["text"] for p in perc.get("pages") or [] for w in p.get("words") or []
             if re.match(r"^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$", w["text"])]
    try:
        return D.document_order(texts)[0]
    except Exception:
        return None


def file_hash(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def make_plans(perc, ask_page: Callable, file_sha: str, model: str,
               cache: Optional[dict] = None, log=lambda s: None) -> dict:
    """Model plans for every page of a perception, one call per page (more
    for a long page, through ask_plan), cached by file hash + model + prompt
    version + page: the same input gives the same plan and is never asked
    twice. `ask_page(page)` returns an `ask(prompt, line_ids)` for that page
    (it carries the page image). Stored on the perception as `plans`, with
    the key and source, so a regenerated export lays out identically."""
    cache = cache if cache is not None else {}
    plans = perc.setdefault("plans", {})
    for page in perc.get("pages") or []:
        if not page.get("lines"):
            continue
        key = plan_key(file_sha, model, page["page"])
        hit = cache.get(key) or (plans.get(str(page["page"])) or {})
        if hit.get("key") == key and hit.get("plan"):
            plans[str(page["page"])] = hit
            continue
        res = ask_plan(ask_page(page), page, log=log)
        entry = {"key": key, "plan": res["plan"], "source": res["source"],
                 "errors": res.get("errors") or [], "version": PLAN_VERSION,
                 "prompt_version": PROMPT_VERSION, "model": model}
        plans[str(page["page"])] = entry
        cache[key] = entry
    return plans


def stored_plans(perc) -> dict:
    """page number -> MODEL plan, from a perception's stored `plans` (a
    fallback plan stored there is not a model plan and is recomputed)."""
    out = {}
    for k, e in ((perc or {}).get("plans") or {}).items():
        if isinstance(e, dict) and e.get("source") == "model" and e.get("plan"):
            try:
                out[int(k)] = e["plan"]
            except (TypeError, ValueError):
                continue
    return out
