"""Run T metrics that corpus_metrics.py does not measure, for ONE code tree.

    backend\\.venv\\Scripts\\python.exe tools\\run_t_metrics.py --root <tree> --results <tag> --out <name>

`--root` is a checkout (the "before" one is a git worktree of the run's
starting commit), so the SAME measurement runs on the old and the new code.
`--results` names a corpus_metrics replay cache (local_docs/corpus_metrics/
<tag>_results) whose values feed the Regular-export checks.

Halves: corpus_metrics.half_of (a hash of the FILE name), as everywhere else.

ORGANIZED (every text-layer PDF in local_docs/DocAgent_testdocs):
  glued_cells       a cell holding two or more figures (dates, amounts,
                    identifiers of 3+ digits) that are not one range
                    ("08/01/2026 - 08/31/2026" is one value)
  column_order      a single-figure value cell whose sheet column's header
                    (the header row written above it, on any earlier page)
                    is not the heading printed over ANY occurrence of that
                    figure on its page (a figure printed twice is checked
                    against both)
  lost_zeros        a cell whose printed text is a zero-padded digit run
                    and whose value is a number
  tail_rows         a sheet row that is exactly a continuation line (no date,
                    no amount, directly under a dated/amount line, starting
                    right of that line's first word)
  amounts_missing   rule 17's own audit: a figure of a kept line in no cell
  trailing_shown_leading  a printed "26.08-" written as a number whose
                    format would show "-26.08"
REGULAR (the replayed results):
  rows_split        a table row with no date and no amount in a table whose
                    rows mostly carry them
  lost_zeros        a zero-padded digit run that the export would write as a
                    number (the writer's own typing, per value and column)
  trailing_shown_leading  a trailing-minus amount whose export format draws
                    the minus in front
"""
from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
DOCS = HERE / "local_docs" / "DocAgent_testdocs"
OUT = HERE / "local_docs" / "corpus_metrics"

_FIG = re.compile(r"^\(?-?\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})\)?-?$|^\d{1,2}/\d{1,2}/\d{2,4}$|^\d{3,}$")
_DATE = re.compile(r"^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$")
_MONEY = re.compile(r"^\(?-?\$?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}\)?-?$")


def half_of(name):
    """corpus_metrics.half_of, copied so no module of THIS tree is imported
    while another tree is being measured."""
    import hashlib
    h = hashlib.sha1(Path(str(name)).name.casefold().encode("utf-8")).hexdigest()
    return "dev" if int(h[:2], 16) % 2 == 0 else "report"


def load_root(root: Path):
    for p in (root / "backend" / "engine", root / "backend", root):
        sys.path.insert(0, str(p))
    for m in list(sys.modules):
        if m.split(".")[0] in ("organized_layout", "app", "dates", "text_layer",
                               "row_groups", "amounts"):
            del sys.modules[m]
    ol = importlib.import_module("organized_layout")
    ec = importlib.import_module("app.services.excel_cells")
    return ol, ec


def _figs(text):
    toks = [t.strip(",;:") for t in str(text or "").split()]
    figs = [t for t in toks if _FIG.match(t)]
    if len(figs) >= 2 and re.search(r"\d\s*(-|to)\s*\d", str(text)) and len(figs) == 2:
        return 1                                     # one range
    return len(figs)


def organized(ol, pdf):
    import pdfplumber
    m = {"glued_cells": 0, "column_order": 0, "lost_zeros": 0, "tail_rows": 0,
         "amounts_missing": 0, "trailing_shown_leading": 0, "cells": 0}
    try:
        lay = ol.layout(pdf)
    except Exception as e:                            # noqa: BLE001
        return {"error": f"{type(e).__name__}"}
    if not lay.get("pages"):
        return None
    a = ol.audit(pdf) or {}
    m["amounts_missing"] = len(a.get("lost") or [])
    with pdfplumber.open(str(pdf)) as doc:
        page_words = [p.extract_words() for p in doc.pages]
    tails = set()
    for ws in page_words:
        lines = {}
        for w in ws:
            lines.setdefault(round(w["top"]), []).append(w)
        keys = sorted(lines)
        for a_, b_ in zip(keys, keys[1:]):
            la, lb = sorted(lines[a_], key=lambda w: w["x0"]), sorted(lines[b_], key=lambda w: w["x0"])
            ta = [w["text"] for w in la]
            tb = [w["text"] for w in lb]
            strong_a = any(_DATE.match(t) or _MONEY.match(t) for t in ta)
            strong_b = any(_DATE.match(t) or _MONEY.match(t) for t in tb)
            h = max(w["bottom"] - w["top"] for w in la)
            if strong_a and not strong_b and 0 < b_ - a_ <= 1.25 * h and lb[0]["x0"] > la[0]["x1"] + 2 \
                    and len(tb) <= 6:
                tails.add(" ".join(tb))
    headers = {}                                      # col -> header text (latest)
    for pi, cells in enumerate(lay["pages"]):
        rows = {}
        for c in cells:
            rows.setdefault(c["row"], []).append(c)
        for r in sorted(rows):
            cs = sorted(rows[r], key=lambda c: c["col"])
            if [c["text"] for c in cs] and " ".join(c["text"] for c in cs) in tails:
                m["tail_rows"] += 1
            if any(c.get("kind") == "header" for c in cs):
                for c in cs:
                    headers[c["col"]] = c["text"]
            table_row = not any(c.get("kind") == "label" for c in cs)
            for c in cs:
                m["cells"] += 1
                t = str(c.get("text", "")).strip()
                if _figs(t) >= 2:
                    m["glued_cells"] += 1
                if re.fullmatch(r"0\d+", t) and not isinstance(c.get("value"), str):
                    m["lost_zeros"] += 1
                if re.fullmatch(r"\$?[\d,]+\.\d{2}-", t.replace(" ", "")) and isinstance(
                        c.get("value"), (int, float)) and not str(
                        c.get("number_format") or "").endswith("-"):
                    m["trailing_shown_leading"] += 1
                if table_row and c.get("kind") in ("value", "text") and _FIG.match(t) \
                        and _figs(t) == 1 \
                        and c["col"] in headers and pi < len(page_words):
                    wants = heading_over(t, page_words[pi], pi, page_words)
                    if wants and not any(_same(w, headers[c["col"]]) for w in wants):
                        m["column_order"] += 1
    return m


def _same(a, b):
    f = lambda s: re.sub(r"[^a-z0-9#]", "", str(s).casefold())  # noqa: E731
    return f(a) == f(b) or f(a) in f(b) or f(b) in f(a)


def heading_over(token, words, pi, all_pages):
    """The heading printed over `token` on its page: the nearest figure-free
    line above it with a word overlapping its x span (this page, else the
    first page that prints such a line). None when the token is not found
    or nothing is printed over it."""
    hits = [w for w in words if w["text"].strip(",;:") == token]
    if not hits:
        return None
    out = []
    for w in hits:
        x0, x1 = w["x0"], w["x1"]
        for ws in [words] + [all_pages[0]]:
            # heading lines only: 2+ words, no digit anywhere, no label colon
            lines = {}
            for v in ws:
                lines.setdefault(round(v["top"]), []).append(v)
            heads = [ln for k, ln in lines.items() if len(ln) >= 2
                     and not any(re.search(r"\d", v["text"]) or v["text"].endswith(":") for v in ln)
                     and (ws is not words or k <= w["top"])]
            above = [v for ln in heads for v in ln if min(x1, v["x1"]) - max(x0, v["x0"]) > -2]
            if above:
                top = max(v["top"] for v in above)
                line = sorted((v for ln in heads for v in ln if abs(v["top"] - top) < 2),
                              key=lambda v: v["x0"])
                # every heading word over this occurrence, each a candidate
                out += [v["text"] for v in line if min(x1, v["x1"]) - max(x0, v["x0"]) > -2]
                out.append(" ".join(v["text"] for v in line))
                break
    return out or None


def regular(ec, results_dir):
    out = {}
    for f in sorted(results_dir.glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        meta, ed = r["meta"], r["ed"]
        half = meta["half"]
        m = out.setdefault(half, {"rows_split": 0, "lost_zeros": 0,
                                  "trailing_shown_leading": 0, "rows": 0})
        labels = {f_["ref"]: f_["row_label"] for f_ in (ed.get("slot_map") or {}).get("fields") or []}
        vals = [(labels.get(ref, ""), v, None) for ref, v in (ed.get("extracted_fields") or {}).items()]
        for k, rows in ed.items():
            if not k.endswith("_rows") or not isinstance(rows, list):
                continue
            keys = [h for h in dict.fromkeys(x for row in rows for x in row) if not str(h).startswith("_")]
            dated = [row for row in rows if any(_DATE.match(str(row.get(h, "")).strip())
                                                or _MONEY.match(str(row.get(h, "")).strip())
                                                for h in keys)]
            m["rows"] += len(rows)
            if rows and len(dated) >= 0.6 * len(rows):
                m["rows_split"] += len(rows) - len(dated)
            colrule = getattr(ec, "column_keeps_text", None)
            for h in keys:
                col = [str(row.get(h, "") or "") for row in rows]
                as_text = bool(colrule and colrule(col))
                vals += [(h, v, as_text) for v in col]
        for label, v, as_text in vals:
            t = str(v or "").strip()
            if re.fullmatch(r"0\d+", t):
                if not as_text and not isinstance(ec.coerce_cell_value(t, label), str):
                    m["lost_zeros"] += 1
            if re.fullmatch(r"\$?[\d,]+\.\d{2}\s?-", t):
                fmt = ec.cell_format(t, label) or ""
                if not fmt.endswith("-"):
                    m["trailing_shown_leading"] += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--results", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    root = Path(a.root).resolve()
    ol, ec = load_root(root)
    org = {}
    for pdf in sorted(DOCS.rglob("*.pdf")):
        got = organized(ol, pdf)
        if got is None:
            continue
        half = half_of(pdf.name)
        tot = org.setdefault(half, {})
        for k, v in got.items():
            if isinstance(v, int):
                tot[k] = tot.get(k, 0) + v
        tot["documents"] = tot.get("documents", 0) + 1
    reg = regular(ec, OUT / f"{a.results}_results")
    res = {"root": str(root), "results": a.results, "organized": org, "regular": reg}
    (OUT / f"run_t_{a.out}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
