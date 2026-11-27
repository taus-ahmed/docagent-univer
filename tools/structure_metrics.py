"""Run T1, Stage 4: the structure engine against the old Organized layout.

    backend\\.venv\\Scripts\\python.exe tools\\structure_metrics.py [--corpus]

SYNTHETIC (tests/fixtures/synthetic_layouts, ground truth known):
  right_column   share of truth table values whose cell sits under its own
                 printed heading (the header cell above it in its column)
  row_order      share of consecutive truth rows found in order
  coverage       share of truth values (tables and pairs) found in a cell
  glued          cells holding two or more figures
  empty_columns  sheet columns with no cell inside a page's used width
  lost_zeros     truth identifiers not kept as text with their zeros
  absent_hits    texts that must never reach a cell and did
  header_repeats a heading printed once in truth written more than once
  wrong_dates    a date cell holding another day than the truth says
CORPUS (local_docs/DocAgent_testdocs, by half, no truth): glued,
  empty_columns, lost_zeros, column_order and amounts_missing through
  tools/run_t_metrics.organized - one instrument for both layouts.

The structure engine runs with NO model (geometry plans only): that is
what the export produces when no plan was stored.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "backend" / "engine", ROOT / "backend", ROOT):
    sys.path.insert(0, str(p))

SYN = ROOT / "tests" / "fixtures" / "synthetic_layouts"
OUT = ROOT / "local_docs" / "corpus_metrics"
_FIG = re.compile(r"^\(?-?\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})\)?-?$|^\d{1,2}/\d{1,2}/\d{2,4}$")


def _n(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().casefold()


def new_layout(pdf):
    import perception as P
    import structure_engine as S
    return S.layout_document(P.read_document(pdf))


def old_layout(pdf):
    import organized_layout as OL
    return OL.layout(pdf)


class NewShim:
    """organized_layout's interface over the structure engine, so
    run_t_metrics.organized measures both the same way."""

    @staticmethod
    def layout(pdf):
        return new_layout(pdf)

    @staticmethod
    def audit(pdf):
        lay = new_layout(pdf)
        return {"lost": [t for t in lay.get("unplaced") or [] if _FIG.match(t)]}


def _text(c):
    return c.get("text") if c.get("text") is not None else c.get("value")


def _headers_above(cells, heads=None):
    """(row, col) -> the nearest header cell's text above it in its column;
    `heads` carries the headings of earlier pages (a table's header row is
    written once, above its first rows)."""
    heads = heads if heads is not None else {}
    out = {}
    for c in sorted(cells, key=lambda c: (c["row"], c["col"])):
        if c.get("kind") == "header" or c.get("header"):
            heads[c["col"]] = _text(c)
        else:
            out[(c["row"], c["col"])] = heads.get(c["col"])
    return out


def score(lay, truth) -> dict:
    m = {"values": 0, "right_column": 0, "found": 0, "row_pairs": 0, "rows_in_order": 0,
         "glued": 0, "empty_columns": 0, "lost_zeros": 0, "absent_hits": 0,
         "header_repeats": 0, "wrong_dates": 0, "cells": 0}
    pages = lay.get("pages") or []
    allc = [(pi, c) for pi, cells in enumerate(pages) for c in cells]
    m["cells"] = len(allc)
    by_text = {}
    for pi, c in allc:
        by_text.setdefault(_n(_text(c)), []).append((pi, c))
    carried = {}
    above = [_headers_above(cells, carried) for cells in pages]
    for pi, cells in enumerate(pages):
        if not cells:
            continue
        used = {c["col"] for c in cells}
        m["empty_columns"] += sum(1 for k in range(max(used) + 1) if k not in used)
        for c in cells:
            t = str(_text(c) or "")
            if sum(1 for tok in t.split() if _FIG.match(tok)) >= 2:
                m["glued"] += 1
    for tbl in truth.get("tables") or []:
        prev_pos = None
        for row in tbl["rows"]:
            pos = None
            for h, v in zip(tbl["header"], row):
                if not v:
                    continue
                m["values"] += 1
                hits = by_text.get(_n(v)) or []
                if hits:
                    m["found"] += 1
                if not h:
                    m["right_column"] += bool(hits)
                elif any(_n(above[pi].get((c["row"], c["col"]))) == _n(h) for pi, c in hits):
                    m["right_column"] += 1
                # a row's position: where its most DISTINCTIVE value is (a
                # group identifier repeats on every row of its group)
                if hits and (pos is None or len(hits) < pos[1]):
                    pos = (min((pi, c["row"]) for pi, c in hits), len(hits))
            pos = pos[0] if pos else None
            if prev_pos is not None and pos is not None:
                m["row_pairs"] += 1
                m["rows_in_order"] += pos > prev_pos
            prev_pos = pos or prev_pos
    for lab, val in truth.get("pairs") or []:
        for v in (lab, val):
            m["values"] += 1
            m["found"] += bool(by_text.get(_n(v)))
            m["right_column"] += bool(by_text.get(_n(v)))
    for z in truth.get("zeros") or []:
        if not any(isinstance(c.get("value"), str) and str(c["value"]).strip() == z or
                   isinstance(c.get("value"), str) and str(c["value"]).endswith(": " + z)
                   for _pi, c in allc):
            m["lost_zeros"] += 1
    for a in truth.get("absent") or []:
        if any(_n(a) in _n(_text(c)) for _pi, c in allc):
            m["absent_hits"] += 1
    for h in truth.get("once") or []:
        n = sum(1 for _pi, c in allc if _n(_text(c)) == _n(h))
        m["header_repeats"] += max(0, n - 1)
    for printed, (y, mo, d) in (truth.get("dates") or {}).items():
        for _pi, c in by_text.get(_n(printed)) or []:
            v = c.get("value")
            if isinstance(v, datetime) and (v.year, v.month, v.day) != (y, mo, d):
                m["wrong_dates"] += 1
    return m


def rates(m) -> dict:
    out = dict(m)
    out["right_column_rate"] = round(m["right_column"] / m["values"], 3) if m["values"] else None
    out["coverage"] = round(m["found"] / m["values"], 3) if m["values"] else None
    out["row_order"] = round(m["rows_in_order"] / m["row_pairs"], 3) if m["row_pairs"] else None
    return out


def synthetic() -> dict:
    res = {"old": {}, "new": {}, "per_case": {}}
    for tf in sorted(SYN.glob("*.truth.json")):
        truth = json.loads(tf.read_text(encoding="utf-8"))
        pdf = tf.with_name(truth["name"] + ".pdf")
        case = {}
        for tag, fn in (("old", old_layout), ("new", new_layout)):
            try:
                m = score(fn(pdf), truth)
            except Exception as e:                    # noqa: BLE001
                m = {"error": type(e).__name__}
            case[tag] = rates(m) if "error" not in m else m
            tot = res[tag]
            for k, v in m.items():
                if isinstance(v, int):
                    tot[k] = tot.get(k, 0) + v
        res["per_case"][truth["name"]] = case
    res["old"], res["new"] = rates(res["old"]), rates(res["new"])
    return res


def corpus() -> dict:
    sys.path.insert(0, str(ROOT / "tools"))
    import organized_layout as OL
    import run_t_metrics as RT
    out = {}
    for pdf in sorted(RT.DOCS.rglob("*.pdf")):
        half = RT.half_of(pdf.name)
        for tag, ol in (("old", OL), ("new", NewShim)):
            got = RT.organized(ol, pdf)
            if not got or "error" in got:
                continue
            try:
                lay = ol.layout(pdf)
                empty = 0
                for cells in lay.get("pages") or []:
                    used = {c["col"] for c in cells}
                    if used:
                        empty += sum(1 for k in range(max(used) + 1) if k not in used)
                got["empty_columns"] = empty
                got["max_columns"] = max([max([c["col"] for c in cells] or [0]) + 1
                                          for cells in lay.get("pages") or []] or [0])
            except Exception:                         # noqa: BLE001
                pass
            tot = out.setdefault(half, {}).setdefault(tag, {})
            for k, v in got.items():
                if isinstance(v, int):
                    tot[k] = tot.get(k, 0) + v
            tot["documents"] = tot.get("documents", 0) + 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", action="store_true")
    a = ap.parse_args()
    res = {"synthetic": synthetic()}
    if a.corpus:
        res["corpus"] = corpus()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "structure_metrics.json").write_text(json.dumps(res, indent=1, default=str),
                                                encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items()}, indent=1, default=str)[:6000])


if __name__ == "__main__":
    main()
