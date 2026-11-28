"""Positional checker (Run T2, Stage 1): each sheet cell against an answer
key - expected cell text, its column header, its row label.

    backend\\.venv\\Scripts\\python.exe tools\\position_check.py [--half dev|heldout|all]
                                       [--engine old|new|both] [--fails 10] [--json out.json]

The old "wrong header" and "two figures in one cell" measures read the
sheet alone, so a date range counted as two figures and an explainer page
counted as glue. This one reads a KEY written by a person from the printed
page (tests/fixtures/answer_keys/*.key; drafted by tools/draft_answer_key.py
from pdfplumber's words, then corrected by hand) and asks of every keyed
item where it landed.

KEY FORMAT (UTF-8, one item per line, `|` between cells)

    # file: bank_statement/mammoth_2pg.pdf     path under local_docs/DocAgent_testdocs
    # half: dev | heldout
    ## page 1                                   items below belong to file page 1
    text: EXAMPLE COMMUNITY BANK                one cell of its own
    kv: Opening balance: | $4,210.55           a label and its value (value right of label)
    table: Date | Description | Debit          a table's column headers (each its own cell)
    continued: Date | Description | Debit      the same table carried on from an earlier page:
                                                sets the headers, adds NO item (a heading
                                                reprinted on every page is written once)
    row: 08/02/2026 | UTILITY ELECTRIC | 124.82   one row; an empty field is no item;
                                                the FIRST non-empty field is the row label
    section: Taxes                              a section line inside a table: its own cell
    group: 300055                               a group identifier or name: its own cell, and
                                                it MAY repeat on every row of its group (in
                                                the same sheet column) without counting extra
    exclude: Lorem ipsum                        must appear in no cell

Text is compared with whitespace collapsed and case folded; a trailing `:`
on a label is ignored (one layout keeps it, one strips it). A header is
compared alphanumerics only, and a stacked header (two header cells one
over the other) is read joined top to bottom.

MEASURES (per document, summed per half)

  right_header   a table value whose nearest header cell above it in its
                 sheet column (carried across page blocks) is the key's
                 header; a kv value whose cell directly left is its label
  right_row      a table value in the same sheet row as its row label; a kv
                 value in the same row as its label
  glued          a cell holding two or more separate key items (each item in
                 it is counted under `glued_items`)
  split          a key item written across two or more adjacent cells
  missing        a key item in no cell, whole, split or glued
  extra          a cell holding text no key item accounts for, or an
                 `exclude:` text
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEYS = ROOT / "tests" / "fixtures" / "answer_keys"
DOCS = ROOT / "local_docs" / "DocAgent_testdocs"


# ── the key ──────────────────────────────────────────────────────────────────

def norm(s) -> str:
    t = re.sub(r"\s+", " ", str(s if s is not None else "")).strip().casefold()
    t = t.replace("’", "'").replace("‘", "'").replace("�", "")
    t = re.sub(r"([$€£¥₹])\s+(?=[\d.,]*\d)", r"\1", t)     # "$ 1,000" is "$1,000"
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"[‐-―−]", "-", t)
    return t[:-1].rstrip() if t.endswith(":") else t


def hkey(s) -> str:
    return "".join(ch for ch in norm(s) if ch.isalnum())


def _toks(s) -> list:
    """Tokens for glue matching: a label's colon is not part of its words."""
    return [t.rstrip(":") for t in norm(s).split() if t.rstrip(":")]


def parse_key(text: str) -> dict:
    """{"file", "half", "pages": {n: [item]}}; an item is {"text", "kind",
    "header", "label", "row", "page", "n"}."""
    key = {"file": None, "half": None, "pages": {}}
    page, headers, row_no, n = None, [], 0, 0
    for raw in text.splitlines():
        line = raw.rstrip()
        m = re.match(r"#\s*(file|half):\s*(.+)$", line)
        if m:
            key[m.group(1)] = m.group(2).strip()
            continue
        m = re.match(r"##\s*page\s+(\d+)", line)
        if m:
            page = int(m.group(1))
            key["pages"].setdefault(page, [])
            headers = []
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"(text|kv|table|continued|row|section|group|exclude):\s?(.*)$", line)
        if not m or page is None:
            raise ValueError(f"bad key line: {line!r}")
        kind, body = m.group(1), m.group(2)
        fields = [f.strip() for f in body.split("|")] if kind in ("kv", "table", "continued", "row") \
            else [body.strip()]
        items = key["pages"][page]

        def add(**kw):
            nonlocal n
            n += 1
            items.append({"page": page, "n": n, **kw})
        if kind == "text":
            add(text=fields[0], kind="text")
        elif kind == "section":
            add(text=fields[0], kind="section")
        elif kind == "group":
            add(text=fields[0], kind="group")
        elif kind == "exclude":
            add(text=fields[0], kind="exclude")
        elif kind == "kv":
            for i in range(0, len(fields) - 1, 2):
                lab, val = fields[i], fields[i + 1]
                add(text=lab, kind="label")
                if val:
                    add(text=val, kind="kv_value", label=lab)
        elif kind == "table":
            headers = fields
            for h in fields:
                if h:
                    add(text=h, kind="header")
        elif kind == "continued":
            headers = fields
        elif kind == "row":
            row_no += 1
            label = next((f for f in fields if f), None)
            for i, f in enumerate(fields):
                if f:
                    add(text=f, kind="row_label" if f is label and i == fields.index(label)
                        else "value", header=headers[i] if i < len(headers) else "",
                        label=label, row=row_no)
    return key


def load_keys(half="all") -> list:
    out = []
    for p in sorted(KEYS.glob("*.key")):
        k = parse_key(p.read_text(encoding="utf-8"))
        k["name"] = p.stem
        if half in ("all", None) or k["half"] == half:
            out.append(k)
    return out


# ── the sheet ────────────────────────────────────────────────────────────────

def _ctext(c):
    t = c.get("text")
    if t is None:
        t = c.get("value")
    return "" if t is None else str(t)


def _page_of_cell(c):
    for i in c.get("word_ids") or []:
        m = re.match(r"p(\d+)w", str(i))
        if m:
            return int(m.group(1))
    return None


def block_pages(lay, key) -> dict:
    """page block index -> file page. From the cells' word ids where the
    layout keeps them; else the keyed page whose items the block's cells
    share most text with."""
    out = {}
    blocks = lay.get("pages") or []
    n_pages = lay.get("_n_pages")
    if n_pages and not any(_page_of_cell(c) for cs in blocks for c in cs):
        # a layout that keeps no word ids writes one block per page that has
        # cells and names the others in `skipped` ("page n: why")
        gone = {int(m.group(1)) for s in lay.get("skipped") or []
                for m in [re.match(r"page (\d+):", str(s))] if m}
        have = [n for n in range(1, n_pages + 1) if n not in gone]
        if len(have) == len(blocks):
            return {bi: have[bi] for bi in range(len(blocks))}
    for bi, cells in enumerate(blocks):
        pages = [p for p in (_page_of_cell(c) for c in cells) if p]
        if pages:
            out[bi] = max(set(pages), key=pages.count)
            continue
        texts = {norm(_ctext(c)) for c in cells}
        best, score = None, 0
        for pg, items in key["pages"].items():
            s = sum(1 for it in items if norm(it["text"]) in texts)
            if s > score:
                best, score = pg, s
        if best is not None and score >= 0.3 * max(1, len(texts)):
            out[bi] = best
    return out


def _is_header(c) -> bool:
    return c.get("kind") == "header" or bool(c.get("header"))


def _headers_above(blocks, header_pos) -> dict:
    """(block, row, col) -> (joined, nearest) header text above the cell in
    its sheet column, carried across blocks in order. A header cell is one
    the layout marks as a header, or one the key's header items matched
    (a layout may write a heading row without marking it). Two header
    cells one directly over the other are one stacked heading."""
    carried, out = {}, {}
    for bi, cs in enumerate(blocks):
        stack_row = {}
        head_rows = {}
        for c in cs:
            if _is_header(c) or (bi, c["row"], c["col"]) in header_pos:
                head_rows.setdefault(c["row"], set()).add(c["col"])
        for c in sorted(cs, key=lambda c: (c["row"], c["col"])):
            pos = (bi, c["row"], c["col"])
            r = c["row"]
            if r in head_rows and r - 1 not in head_rows and c["col"] == min(head_rows[r]):
                # a new header row: a column it leaves blank has NO header
                # below it (never one carried from an earlier table)
                for col in list(carried):
                    if col not in head_rows[r]:
                        carried[col] = (bi, "", "")
            if _is_header(c) or pos in header_pos:
                prev = carried.get(c["col"])
                if prev and stack_row.get(c["col"]) == c["row"] - 1 and prev[0] == bi:
                    carried[c["col"]] = (bi, prev[1] + " " + _ctext(c), _ctext(c))
                else:
                    carried[c["col"]] = (bi, _ctext(c), _ctext(c))
                stack_row[c["col"]] = c["row"]
            else:
                h = carried.get(c["col"])
                out[pos] = (h[1], h[2]) if h else ("", "")
    return out


# ── scoring one document ─────────────────────────────────────────────────────

def score(lay, key) -> dict:
    """Every measure for one layout against one key, plus the failing items
    with where they landed."""
    bp = block_pages(lay, key)
    blocks = lay.get("pages") or []
    cells = [(bi, c) for bi, cs in enumerate(blocks) for c in cs
             if bi in bp and bp[bi] in key["pages"]]
    by_pos = {(bi, c["row"], c["col"]): c for bi, c in cells}
    m = {"items": 0, "values": 0, "right_header": 0, "right_row": 0, "glued": 0,
         "glued_items": 0, "split": 0, "missing": 0, "extra": 0, "excluded_placed": 0,
         "cells": len(cells),
         # T3 S6: reading-order metric — how many placed items appear in a
         # different top-to-bottom order in the sheet vs in the key.  An
         # "order pair" is an ordered pair (a, b) where a comes before b in
         # the key (same page, same section-type) and a is placed strictly
         # below b in the sheet.  `order_pairs` is the total possible pairs;
         # `order_violations` is the count that are inverted.
         "order_pairs": 0, "order_violations": 0}
    fails = []
    used = set()                       # (bi,row,col) consumed
    matched = {}                       # item n -> (bi,row,col)
    items_all = [it for pg in sorted(key["pages"]) for it in key["pages"][pg]]
    items = [it for it in items_all if it["kind"] != "exclude"]
    m["items"] = len(items)
    m["values"] = sum(1 for it in items if it["kind"] in ("value", "kv_value", "row_label"))
    cell_index = {}
    for bi, c in cells:
        if bp.get(bi) is None:
            continue
        cell_index.setdefault((bp[bi], norm(_ctext(c))), []).append((bi, c["row"], c["col"]))

    def take(pos):
        used.add(pos)
        return pos

    # 1) table rows: choose the sheet row holding most of a key row's items
    rows = {}
    for it in items:
        if it.get("row"):
            rows.setdefault((it["page"], it["row"]), []).append(it)
    last_pos = {}
    for (pg, rno), its in sorted(rows.items()):
        cand = {}
        for it in its:
            for pos in cell_index.get((pg, norm(it["text"])), []):
                if pos not in used:
                    cand.setdefault(pos[:2], set()).add(it["n"])
        if not cand:
            continue
        lp = last_pos.get(pg, (-1, -1))
        best = max(cand, key=lambda r: (len(cand[r]), r > lp, -abs(r[0] - lp[0]) * 1000
                                        - abs(r[1] - lp[1])))
        last_pos[pg] = best
        for it in its:
            if it["n"] not in cand[best]:
                continue
            for pos in cell_index[(pg, norm(it["text"]))]:
                if pos[:2] == best and pos not in used:
                    matched[it["n"]] = take(pos)
                    break
    # 2) kv pairs: the label, then its value preferring the label's row
    # (then any table item its row did not take, wherever it is: present,
    # but in the wrong row)
    for it in sorted(items, key=lambda it: bool(it.get("row"))):
        if it["n"] in matched:
            continue
        cands = [p for p in cell_index.get((it["page"], norm(it["text"])), []) if p not in used]
        if not cands:
            continue
        if it.get("row"):
            lab = next((x for x in items if x.get("row") == it["row"] and x["page"] == it["page"]
                        and x["kind"] == "row_label"), None)
            lp = matched.get(lab["n"]) if lab else None
            if lp:
                cands.sort(key=lambda p: (p[0] != lp[0], abs(p[1] - lp[1])))
        if it["kind"] == "kv_value":
            lab = next((x for x in items if x["page"] == it["page"] and x["kind"] == "label"
                        and x["n"] == it["n"] - 1), None)
            lp = matched.get(lab["n"]) if lab else None
            if lp:
                cands.sort(key=lambda p: (p[:2] != lp[:2], abs(p[2] - lp[2] - 1)))
        matched[it["n"]] = take(cands[0])
    head_above = _headers_above(blocks, {matched[it["n"]] for it in items
                                         if it["kind"] == "header" and it["n"] in matched})
    # 3) glued and split, for what is left
    toks = {}
    for it in items:
        toks[it["n"]] = _toks(it["text"])
    left = [it for it in items if it["n"] not in matched]
    glued_cells = {}
    for bi, c in cells:
        pos = (bi, c["row"], c["col"])
        if pos in used or not _ctext(c).strip():
            continue
        ct = _toks(_ctext(c))
        pg = bp.get(bi)
        found, covered = [], [False] * len(ct)
        pool = sorted([it for it in items if it["page"] == pg and toks[it["n"]]],
                      key=lambda it: -len(toks[it["n"]]))
        for it in pool:
            t = toks[it["n"]]
            for s in range(len(ct) - len(t) + 1):
                if ct[s:s + len(t)] == t and not any(covered[s:s + len(t)]):
                    found.append(it)
                    for k in range(s, s + len(t)):
                        covered[k] = True
                    break
        if len(found) >= 2 and sum(covered) >= 0.7 * len(ct):
            glued_cells[pos] = found
            used.add(pos)
    glued_n = set()
    for pos, found in glued_cells.items():
        m["glued"] += 1
        for it in found:
            if it["n"] not in matched:
                glued_n.add(it["n"])
    m["glued_items"] = len(glued_n)
    split_n = set()
    # reading order within each block, for a value wrapped onto the next row
    order = {}
    for bi, cs in enumerate(blocks):
        seq = sorted(((c["row"], c["col"]) for c in cs if _ctext(c).strip()))
        for i, rc in enumerate(seq):
            order[(bi,) + rc] = (bi,) + seq[i + 1] if i + 1 < len(seq) else None
    for it in left:
        if it["n"] in glued_n:
            continue
        t = norm(it["text"]).replace(" ", "")
        if len(t) < 2:
            continue
        hit = None
        for bi, c in cells:
            if bp.get(bi) != it["page"]:
                continue
            start = (bi, c["row"], c["col"])
            if start in used or not t.startswith(norm(_ctext(c)).replace(" ", "")):
                continue
            for step in ("right", "down", "reading"):
                acc, path, pos = "", [], start
                while pos in by_pos and pos not in used and len(path) < 4:
                    acc += norm(_ctext(by_pos[pos])).replace(" ", "")
                    path.append(pos)
                    if acc == t and len(path) >= 2:
                        hit = path
                        break
                    if not t.startswith(acc):
                        break
                    if step == "right":
                        pos = (pos[0], pos[1], pos[2] + 1)
                    elif step == "down":
                        pos = (pos[0], pos[1] + 1, pos[2])
                    else:
                        pos = order.get(pos)
                if hit:
                    break
            if hit:
                break
        if hit:
            split_n.add(it["n"])
            used.update(hit)
    m["split"] = len(split_n)
    # T3 S6 — reading-order metric: items that are placed in the sheet,
    # ordered pairs within the same page, check that sheet order matches key order.
    # Only "value" items (row values + kv values) with a placement are checked;
    # headers and section labels move around legitimately (reprints, grouping).
    placed_values = [(it, matched[it["n"]]) for it in items
                     if it["n"] in matched and it["kind"] in ("value", "kv_value", "row_label")]
    # group by page; within each page iterate all pairs in key order
    by_pg: dict = {}
    for it, pos in placed_values:
        by_pg.setdefault(it["page"], []).append((it, pos))
    for pg, pg_its in by_pg.items():
        # already in key order (items_all is sorted by page, then insertion order)
        for i in range(len(pg_its)):
            for j in range(i + 1, len(pg_its)):
                ita, posa = pg_its[i]
                itb, posb = pg_its[j]
                # compare sheet position: (block, row) is enough — column does not matter
                block_row_a = (posa[0], posa[1])
                block_row_b = (posb[0], posb[1])
                if block_row_a == block_row_b:
                    continue    # same sheet row: no order signal
                m["order_pairs"] += 1
                if block_row_a > block_row_b:
                    m["order_violations"] += 1
    # 4) the measures
    for it in items:
        n = it["n"]
        pos = matched.get(n)
        status = "ok"
        if pos is None:
            status = "glued" if n in glued_n else "split" if n in split_n else "missing"
            if status == "missing":
                m["missing"] += 1
        if it["kind"] not in ("value", "kv_value", "row_label"):
            if status != "ok":
                fails.append(_fail(it, status, None, by_pos, head_above))
            continue
        rh = rr = False
        if pos is not None:
            if it["kind"] == "kv_value":
                lab = next((x for x in items if x["kind"] == "label" and x["n"] == n - 1), None)
                lp = matched.get(lab["n"]) if lab else None
                rr = bool(lp) and lp[:2] == pos[:2]
                rh = rr and lp[2] < pos[2] and not any(
                    (pos[0], pos[1], k) in by_pos and _ctext(by_pos[(pos[0], pos[1], k)]).strip()
                    for k in range(lp[2] + 1, pos[2]))
            else:
                lab = next((x for x in items if x.get("row") == it["row"] and x["page"] == it["page"]
                            and x["kind"] == "row_label"), None)
                lp = matched.get(lab["n"]) if lab else None
                rr = bool(lp) and lp[:2] == pos[:2]
                want = hkey(it.get("header"))
                joined, single = head_above.get(pos, ("", ""))
                rh = (not want and not hkey(single)) or want in (hkey(joined), hkey(single)) \
                    if want else True
        m["right_header"] += rh
        m["right_row"] += rr
        if status != "ok" or not rh or not rr:
            fails.append(_fail(it, status if status != "ok" else
                               ("wrong header" if not rh else "wrong row"), pos, by_pos,
                               head_above))
    # extras: cells no item accounts for, and excluded text placed
    excl = [it for it in items_all if it["kind"] == "exclude"]
    for bi, c in cells:
        pos = (bi, c["row"], c["col"])
        t = norm(_ctext(c))
        if not t:
            continue
        hit_ex = next((e for e in excl if e["page"] == bp.get(bi) and norm(e["text"])
                       and (norm(e["text"]) in t or (t in norm(e["text"]) and
                                                     len(t) >= 0.5 * len(norm(e["text"]))))),
                      None)
        if hit_ex:
            m["excluded_placed"] += 1
            m["extra"] += 1
            fails.append({"page": bp.get(bi), "item": hit_ex["text"], "kind": "exclude",
                          "status": "excluded text placed", "cell": _a1(pos),
                          "cell_text": _ctext(c)[:120], "header_found": ""})
            continue
        if pos not in used and any(
                it["kind"] == "group" and norm(it["text"]) == t and it["page"] == bp.get(bi)
                and matched.get(it["n"]) and matched[it["n"]][0] == bi
                and matched[it["n"]][2] == c["col"] for it in items):
            continue                       # a group label repeated on its rows
        if pos not in used:
            m["extra"] += 1
            fails.append({"page": bp.get(bi), "item": None, "kind": "extra",
                          "status": "extra", "cell": _a1(pos), "cell_text": _ctext(c)[:120],
                          "header_found": head_above.get(pos, ("", ""))[0]})
    m["fails"] = fails
    return m


def _a1(pos):
    if pos is None:
        return None
    from openpyxl.utils import get_column_letter
    bi, r, c = pos
    return f"b{bi + 1}!{get_column_letter(c + 1)}{r + 1}"


def _fail(it, status, pos, by_pos, head_above):
    c = by_pos.get(pos) if pos else None
    return {"page": it["page"], "item": it["text"], "kind": it["kind"], "status": status,
            "want_header": it.get("header") or (it.get("label") if it["kind"] == "kv_value"
                                                else None),
            "row_label": it.get("label") if it["kind"] != "kv_value" else None,
            "cell": _a1(pos), "cell_text": _ctext(c)[:120] if c else None,
            "header_found": head_above.get(pos, ("", ""))[0] if pos else None}


# ── the layouts ──────────────────────────────────────────────────────────────

def _paths():
    for p in (ROOT / "backend" / "engine", ROOT / "backend", ROOT):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))


def layout_new(pdf):
    _paths()
    import perception as P
    import structure_engine as S
    return S.layout_document(P.read_document(pdf))


def layout_old(pdf):
    _paths()
    import organized_layout as OL
    return OL.layout(pdf)


def page_lines(pdf, page):
    """The printed lines of a page as pdfplumber reads them (for showing a
    failing cell beside its page text)."""
    import pdfplumber
    with pdfplumber.open(str(pdf)) as d:
        if not 1 <= page <= len(d.pages):
            return []
        ws = d.pages[page - 1].extract_words()
    ws.sort(key=lambda w: (round(w["top"]), w["x0"]))
    lines = []
    for w in ws:
        if lines and abs(w["top"] - lines[-1][0]["top"]) <= 2.0:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [" ".join(x["text"] for x in sorted(ln, key=lambda w: w["x0"])) for ln in lines]


def context(pdf, f, cache):
    """The printed line holding a failing item (or cell text)."""
    key = (str(pdf), f["page"])
    if key not in cache:
        cache[key] = page_lines(pdf, f["page"]) if f["page"] else []
    probe = norm(f.get("item") or f.get("cell_text") or "")
    lab = norm(f.get("row_label") or "")
    if lab and lab != probe:
        for ln in cache[key]:
            if lab in norm(ln) and probe in norm(ln):
                return ln[:160]
    for ln in cache[key]:
        if probe and (probe in norm(ln) or norm(ln) in probe and len(norm(ln)) > 8):
            return ln[:160]
    first = probe.split()[:2]
    for ln in cache[key]:
        if first and all(t in norm(ln) for t in first):
            return ln[:160]
    return ""


SUMS = ("items", "values", "right_header", "right_row", "glued", "glued_items", "split",
        "missing", "extra", "excluded_placed", "cells",
        "order_pairs", "order_violations")


def run(half="all", engines=("old", "new"), n_fails=10, doc="") -> dict:
    out = {}
    for eng in engines:
        fn = layout_new if eng == "new" else layout_old
        for k in load_keys(half):
            if doc and doc not in k["name"]:
                continue
            pdf = DOCS / k["file"]
            if not pdf.exists():
                out.setdefault(eng, {})[k["name"]] = {"error": "pdf not present"}
                continue
            lay = fn(pdf)
            import pdfplumber
            with pdfplumber.open(str(pdf)) as d:
                lay["_n_pages"] = len(d.pages)
            m = score(lay, k)
            m["half"] = k["half"]
            out.setdefault(eng, {})[k["name"]] = m
    return out


def summarise(res) -> dict:
    tab = {}
    for eng, docs in res.items():
        for name, m in docs.items():
            if "error" in m:
                continue
            t = tab.setdefault(eng, {}).setdefault(m["half"], {s: 0 for s in SUMS})
            for s in SUMS:
                t[s] += m[s]
    return tab


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--half", default="all")
    ap.add_argument("--engine", default="both")
    ap.add_argument("--fails", type=int, default=10)
    ap.add_argument("--json", default="")
    ap.add_argument("--doc", default="")
    a = ap.parse_args()
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    engines = ("old", "new") if a.engine == "both" else (a.engine,)
    res = run(a.half, engines, doc=a.doc)
    print(f"{'engine':6} {'doc':34} {'half':8} items  hdr%  row%  glued split miss extra order%")
    for eng, docs in res.items():
        for name, m in sorted(docs.items(), key=lambda kv: (kv[1].get("half", ""), kv[0])):
            if "error" in m:
                print(f"{eng:6} {name:34} {m['error']}")
                continue
            v = m["values"] or 1
            op = m.get("order_pairs") or 1
            ov = m.get("order_violations", 0)
            print(f"{eng:6} {name:34} {m['half']:8} {m['items']:5d} {100*m['right_header']/v:5.1f} "
                  f"{100*m['right_row']/v:5.1f} {m['glued']:5d} {m['split']:5d} {m['missing']:4d} "
                  f"{m['extra']:5d} {100*(1 - ov/op):5.1f}")
    print()
    for eng, halves in summarise(res).items():
        for h, t in sorted(halves.items()):
            v = t["values"] or 1
            op = t.get("order_pairs") or 1
            ov = t.get("order_violations", 0)
            print(f"TOTAL {eng:4} {h:8} items={t['items']} values={t['values']} "
                  f"right_header={t['right_header']} ({100*t['right_header']/v:.1f}%) "
                  f"right_row={t['right_row']} ({100*t['right_row']/v:.1f}%) glued={t['glued']} "
                  f"split={t['split']} missing={t['missing']} extra={t['extra']} "
                  f"order={100*(1-ov/op):.1f}% (viol={ov}/{op})")
    if a.fails:
        cache = {}
        for eng, docs in res.items():
            for h in sorted({m.get("half") for m in docs.values() if "half" in m}):
                fs = [(name, f) for name, m in docs.items() if m.get("half") == h
                      for f in m["fails"]]
                print(f"\n--- {eng} {h}: {len(fs)} failing items/cells; first {a.fails} spread over documents")
                picked, seen = [], {}
                for name, f in fs:
                    if seen.get(name, 0) < max(1, a.fails // max(1, len(docs))):
                        picked.append((name, f))
                        seen[name] = seen.get(name, 0) + 1
                for name, f in (picked + [x for x in fs if x not in picked])[:a.fails]:
                    k = next(k for k in load_keys() if k["name"] == name)
                    ctx = context(DOCS / k["file"], f, cache)
                    print(f"  {name} p{f['page']} [{f['status']}] item={f.get('item')!r} "
                          f"want_header={f.get('want_header')!r} cell={f.get('cell')} "
                          f"text={f.get('cell_text')!r} header_found={f.get('header_found')!r}"
                          f"\n      page: {ctx}")
    if a.json:
        Path(a.json).write_text(json.dumps({"results": res, "summary": summarise(res)},
                                           indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
