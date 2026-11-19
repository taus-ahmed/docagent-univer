"""Scoreboard: is "review only to approve" a number yet? (Run A, A9)

    python tools/score_runs.py <folder of job result JSON> \
        [--answers local_docs/DocAgent_templates_v2.xlsx] \
        [--extra local_docs/answers_extra.csv] [--out scoreboard.csv]

Input: job result files shaped like GET /api/jobs/{id}/results (a list of
document results, or one), and the verified values on the "Answers" sheet
(File | Field | Correct value), plus an optional CSV of the same three columns.
No model calls; reads nothing but those files and, for the lane, the local PDF.

Per run it reports: expected values, correct, wrong, missing, how many of the
wrong/missing were UNFLAGGED (silent), how many flagged values were actually
correct (false flags), whether the document would export with zero edits
("approve-only"), pages processed of total, and cost. Then totals by document
type and by lane (clean digital, fillable form, scan, photo, long).

Matching is tolerant of FORMAT ($, commas, case, punctuation, date order) and
exact on NUMBERS. An Answers field is matched to the template slot whose label
holds all of its words ("Box 1" -> "Box 1 Wages Tips Other Compensation");
among several, the one holding the expected value. A field no slot names is
counted as missing and listed as "no slot".
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "backend" / "engine")]

DEFAULT_ANSWERS = ROOT / "local_docs" / "DocAgent_templates_v2.xlsx"
DEFAULT_EXTRA = ROOT / "local_docs" / "answers_extra.csv"
DOCS = ROOT / "local_docs" / "DocAgent_testdocs"


# ── answers ──────────────────────────────────────────────────────────────────

def load_answers(xlsx: Path, extra: Path | None) -> dict:
    """{file basename: [(field, expected)]}"""
    out = defaultdict(list)
    if xlsx and xlsx.exists():
        import openpyxl
        ws = openpyxl.load_workbook(xlsx, data_only=True)["Answers"]
        for r in ws.iter_rows(min_row=2, values_only=True):
            if r and r[0] and r[1] is not None and r[2] is not None:
                out[Path(str(r[0])).name].append((str(r[1]), r[2], str(r[0])))
    if extra and extra.exists():
        with extra.open(encoding="utf-8", newline="") as f:
            for r in csv.reader(f):
                if len(r) >= 3 and r[0] and r[0] != "File":
                    out[Path(r[0]).name].append((r[1], r[2], r[0]))
    return out


# ── normalising ──────────────────────────────────────────────────────────────

def _strip_note(s: str) -> str:
    return re.sub(r"\s*\((?:fictional|sample|approx\.?|about)[^)]*\)\s*$", "",
                  str(s).strip(), flags=re.I)


def as_number(v):
    from amounts import parse_amount
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return Decimal(str(v)).normalize()
    s = str(v or "").strip()
    if not re.fullmatch(r"[-(]?\s*[$€£]?\s*[\d,]+(?:\.\d+)?\s*\)?%?", s):
        return None
    a = parse_amount(s, ".")
    return abs(a.value).normalize() if a.ok else None


def as_date(v):
    from dates import looks_like_a_date, parse_date
    s = str(v or "").strip()
    if not looks_like_a_date(s):
        return None
    d = parse_date(s, "MDY")
    return getattr(d, "value", None) or (getattr(d, "date", None)) or None


def text_key(v) -> str:
    return re.sub(r"[^a-z0-9]", "", _strip_note(str(v or "")).casefold())


def same(expected, got) -> bool:
    if got is None or str(got).strip() == "":
        return False
    e_num, g_num = as_number(expected), as_number(got)
    if e_num is not None and g_num is not None:
        return e_num == g_num
    e_d, g_d = as_date(expected), as_date(got)
    if e_d is not None and g_d is not None:
        return e_d == g_d
    return bool(text_key(expected)) and text_key(expected) == text_key(got)


# ── one result ───────────────────────────────────────────────────────────────

def _words(s):
    return [w for w in re.findall(r"[a-z0-9]+", str(s).casefold())]


def _covers(field, label) -> bool:
    lw = _words(label)
    for w in _words(field):
        if w.isdigit() or len(w) <= 2:
            if w not in lw:
                return False
        elif not any(x == w or (min(len(x), len(w)) >= 4
                                and (x.startswith(w) or w.startswith(x)))
                     for x in lw):
            return False
    return bool(_words(field))


def _values(ed):
    """[(label, value, status dict)] for every field slot of a result."""
    from app.core import review as R
    out = []
    for v in R.document_values(ed):
        if v["kind"] == "field":
            out.append((str(v["label"]), v["value"], v))
    return out


def _rows(ed):
    from app.core import review as R
    rows = []
    for _name, key in R.table_keys(ed):
        rows += [r for r in (ed.get(key) or []) if isinstance(r, dict)]
    return rows


def _flagged(st) -> bool:
    return st["status"] in ("low", "unverified", "empty_flagged", "unknown") \
        or bool(st.get("review_required"))


def score_field(field, expected, fields, rows):
    """('correct'|'wrong'|'missing', flagged, note)"""
    f = field.casefold()
    if f.startswith(("transaction count", "lines", "line count", "rows")):
        got = len(rows)
        ok = as_number(expected) == Decimal(got)
        return ("correct" if ok else "wrong" if got else "missing"), False, f"{got} rows"
    if f.startswith("row "):
        want = re.findall(r"[\d,]+\.\d{2}", str(expected))
        key = _words(field[4:])
        for r in rows:
            blob = " ".join(str(v) for k, v in r.items() if not str(k).startswith("_"))
            bw = _words(blob)
            if sum(1 for w in key if w in bw) * 2 >= len(key):
                have = {as_number(x) for x in re.findall(r"[\d,]+\.\d{2}", blob)}
                ok = all(as_number(x) in have for x in want)
                st = bool(r.get("_review_required")) or r.get("_confidence") in ("low", "unverified")
                return ("correct" if ok else "wrong"), st, ""
        return "missing", False, "row not found"
    cands = [(lab, val, st) for lab, val, st in fields if _covers(field, lab)]
    if not cands:
        return "missing", False, "no slot"
    parts = [p for p in re.split(r"\s+/\s+|\s+-\s+(?=\d)", _strip_note(str(expected))) if p]
    if len(parts) > 1:
        vals = [val for _l, val, _s in cands]
        ok = all(any(same(p, v) for v in vals) for p in parts)
        flag = any(_flagged(s) for _l, _v, s in cands)
        empty = all(str(v or "").strip() == "" for v in vals)
        return ("correct" if ok else "missing" if empty else "wrong"), flag, ""
    for lab, val, st in cands:
        if same(expected, val):
            return "correct", _flagged(st), lab
    filled = [(lab, val, st) for lab, val, st in cands if str(val or "").strip()]
    if filled:
        lab, val, st = filled[0]
        return "wrong", _flagged(st), f"{lab}={val!r}"
    return "missing", any(_flagged(s) for _l, _v, s in cands), cands[0][0]


def lane(path_hint: str, ed: dict) -> str:
    p = path_hint.replace("\\", "/").casefold()
    if "long_docs/" in p:
        return "long"
    name = Path(p).name
    if name.startswith("photo_") or "receipt_photo/" in p or name.endswith((".jpg", ".jpeg", ".png")):
        return "photo"
    if name.startswith("scan_") or "scans_made/" in p:
        return "scan"
    origins = set(((ed.get("validation") or {}).get("page_origins") or {}).values())
    if origins & {"ocr", "pre_ocr"}:
        return "scan"
    if ((ed.get("diagnostics") or {}).get("inventory") or {}).get("widget_values"):
        return "fillable form"
    local = DOCS / path_hint
    if local.exists() and local.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
            if PdfReader(str(local)).trailer["/Root"].get("/AcroForm"):
                return "fillable form"
        except Exception:
            pass
    return "clean digital"


def cost_of(doc) -> tuple:
    ed = doc.get("extracted_data") or {}
    usage = (ed.get("diagnostics") or {}).get("usage") or {}
    if usage.get("cost_estimate") is not None:
        return usage["cost_estimate"], "attempts"
    import llm_contract as C
    p = C.price_for(doc.get("model_used"))
    tok = doc.get("tokens_used")
    if p and tok:
        # tokens_used before Run A excluded thinking and did not split input
        # from output: priced as input, a LOWER bound.
        return round(tok / 1e6 * p["input"], 6), "lower bound (tokens_used, no thinking)"
    return None, "unknown"


def score_doc(doc, answers):
    ed = doc.get("extracted_data") or {}
    name = Path(str(doc.get("original_filename") or doc.get("filename") or "")).name
    name = re.sub(r" \[\d+ of \d+\]$", "", name)
    exp = answers.get(name) or []
    fields, rows = _values(ed), _rows(ed)
    out = {"file": name, "document_type": doc.get("document_type"),
           "expected": len(exp), "correct": 0, "wrong": 0, "missing": 0,
           "no_slot": 0, "silent": 0, "false_flags": 0, "details": []}
    rows_flagged = any("were extracted" in str(a.get("text", "")) and not a.get("disposition")
                       for a in ed.get("attention") or [] if isinstance(a, dict))
    for field, expected, _path in exp:
        f = field.casefold()
        if f.startswith(("document count", "page ranges", "total pages")):
            continue          # a property of the FILE, not of one record
        res, flagged, note = score_field(field, expected, fields, rows)
        if res == "missing" and note == "no slot":
            out["no_slot"] += 1          # the template cannot hold it
            out["details"].append((field, str(expected), "no slot", False, ""))
            continue
        if res == "missing" and (f.startswith(("row ", "transaction count", "lines"))):
            flagged = flagged or rows_flagged
        out[res] += 1
        if res in ("wrong", "missing") and not flagged:
            out["silent"] += 1
        if res == "correct" and flagged:
            out["false_flags"] += 1
        out["details"].append((field, str(expected), res, flagged, note))
    out["expected"] = out["correct"] + out["wrong"] + out["missing"]
    out["approve_only"] = (out["expected"] > 0 and out["wrong"] == 0
                           and out["missing"] == 0)
    pages = (ed.get("diagnostics") or {}).get("pages") or {}
    out["pages"] = (f"{sum(1 for v in pages.values() if v.startswith('processed'))}"
                    f" of {len(pages)}") if pages else "n/a (before page ledger)"
    out["cost"], out["cost_basis"] = cost_of(doc)
    out["lane"] = lane(exp[0][2] if exp else name, ed)
    out["state"] = ed.get("document_state") or "n/a"
    return out


def load_runs(folder: Path):
    for p in sorted(folder.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        for d in (data if isinstance(data, list) else [data]):
            if isinstance(d, dict) and "extracted_data" in d:
                yield p.stem, d


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", type=Path)
    ap.add_argument("--answers", type=Path, default=DEFAULT_ANSWERS)
    ap.add_argument("--extra", type=Path, default=DEFAULT_EXTRA)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--details", action="store_true")
    a = ap.parse_args(argv)
    answers = load_answers(a.answers, a.extra)
    rows = []
    for run, doc in load_runs(a.folder):
        s = score_doc(doc, answers)
        s["run"] = run
        rows.append(s)
    cols = ["run", "file", "document_type", "lane", "state", "expected", "correct",
            "wrong", "missing", "no_slot", "silent", "false_flags", "approve_only", "pages",
            "cost", "cost_basis"]
    print(" | ".join(cols))
    for s in rows:
        print(" | ".join(str(s[c]) for c in cols))
        if a.details:
            for d in s["details"]:
                print("     ", d)
    for key in ("document_type", "lane"):
        agg = defaultdict(lambda: defaultdict(float))
        for s in rows:
            g = agg[s[key] or "?"]
            for c in ("expected", "correct", "wrong", "missing", "no_slot", "silent", "false_flags"):
                g[c] += s[c]
            g["runs"] += 1
            g["approve_only"] += 1 if s["approve_only"] else 0
            g["cost"] += s["cost"] or 0
        print(f"\nTOTALS BY {key.upper()}")
        for k, g in sorted(agg.items()):
            print(f"  {k}: runs={int(g['runs'])} expected={int(g['expected'])} "
                  f"correct={int(g['correct'])} wrong={int(g['wrong'])} "
                  f"missing={int(g['missing'])} no_slot={int(g['no_slot'])} "
                  f"silent={int(g['silent'])} "
                  f"false_flags={int(g['false_flags'])} "
                  f"approve_only={int(g['approve_only'])}/{int(g['runs'])} "
                  f"cost=${g['cost']:.4f}")
    if a.out:
        with a.out.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for s in rows:
                w.writerow([s[c] for c in cols])
        print(f"\nwrote {a.out}")
    return rows


if __name__ == "__main__":
    main()
