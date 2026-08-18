"""
Type-aware scoring of extracted values against gold labels.

Every gold-valued field lands in exactly one of four outcomes:

  correct       — matches the gold value (type-aware, not string equality)
  wrong         — a value was extracted and it is incorrect
  missed        — gold has a value, extraction returned nothing
  hallucinated  — gold has nothing, extraction invented a value

plus one refinement reported separately:

  near          — almost-correct (string similarity, sign-only money flips,
                  same day/month different year). Near counts AGAINST headline
                  accuracy — it is a sub-class of wrong that a human should
                  eyeball, not a pass.

Hallucination rate = hallucinated / all non-empty extracted values. It is the
metric that decides whether a client can trust the product, and it is reported
separately from accuracy everywhere.

Tables are scored by aligning predicted rows to gold rows (greedy best-match),
then reporting row precision, row recall, per-cell accuracy over matched rows,
and — as its own metric, never averaged away — the row count mismatch.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any, Optional

# ── emptiness ────────────────────────────────────────────────────────────────

_NULLISH = {"", "null", "none", "n/a", "na", "nil", "not found", "-", "--"}


def is_empty(v: Any) -> bool:
    if v is None:
        return True
    s = str(v).strip().casefold()
    return s in _NULLISH


# ── normalizers ──────────────────────────────────────────────────────────────

_CURRENCY = "$£€₹¥"
_DASHES = {"–": "-", "—": "-", "−": "-", "‐": "-", "‑": "-"}


def _clean_dashes(s: str) -> str:
    for k, v in _DASHES.items():
        s = s.replace(k, v)
    return s


def parse_money(v: Any) -> Optional[float]:
    """'$1,234.50' -> 1234.5, '(500)' -> -500.0, 1234.5 -> 1234.5."""
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = _clean_dashes(str(v).strip())
    if not s:
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    s = s.strip()
    if s.startswith("-"):
        neg, s = True, s[1:]
    for ch in _CURRENCY:
        s = s.replace(ch, "")
    s = s.replace(",", "").replace(" ", "").strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([kKmM])?", s)
    if not m:
        return None
    val = float(m.group(1))
    if m.group(2):
        val *= 1000.0 if m.group(2).lower() == "k" else 1_000_000.0
    return -val if neg else val


def parse_number(v: Any) -> Optional[float]:
    return parse_money(v)  # same tolerance: separators, parens, suffixes


_MONTHS = {m.casefold(): i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})


def parse_date_candidates(v: Any) -> set:
    """Return the set of (year|None, month, day) readings of a date string.

    Ambiguous numeric dates (14/03/2024 vs 03/14/2024) contribute BOTH
    readings, so either interpretation matches. Yearless dates (03/15) get
    year=None and match any year.
    """
    if v is None:
        return set()
    s = _clean_dashes(str(v).strip())
    s = re.sub(r"[T ]\d{2}:\d{2}.*$", "", s)  # drop time component
    out = set()

    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        out.add((int(m.group(1)), int(m.group(2)), int(m.group(3))))

    # "January 15, 2024" / "15 January 2024" / "Jan 15 2024"
    m = re.fullmatch(r"([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", s)
    if m and m.group(1).casefold()[:3] in _MONTHS:
        out.add((int(m.group(3)), _MONTHS[m.group(1).casefold()[:3]], int(m.group(2))))
    m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\.?,?\s+(\d{4})", s)
    if m and m.group(2).casefold()[:3] in _MONTHS:
        out.add((int(m.group(3)), _MONTHS[m.group(2).casefold()[:3]], int(m.group(1))))

    # numeric d/m/y and m/d/y (both readings when ambiguous)
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})", s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        if 1 <= b <= 12 and 1 <= a <= 31:
            out.add((y, b, a))
        if 1 <= a <= 12 and 1 <= b <= 31:
            out.add((y, a, b))

    # yearless m/d (or d/m): year=None
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})", s)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if 1 <= a <= 12 and 1 <= b <= 31:
            out.add((None, a, b))
        if 1 <= b <= 12 and 1 <= a <= 31:
            out.add((None, b, a))
    return out


def normalize_string(v: Any) -> str:
    s = unicodedata.normalize("NFKC", str(v))
    s = _clean_dashes(s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip(" .,:;*'\"")
    return s.casefold()


# ── comparison ───────────────────────────────────────────────────────────────

def compare_values(expected: Any, actual: Any, ftype: str) -> str:
    """Both sides non-empty. Return 'correct' | 'near' | 'wrong'."""
    if ftype in ("money", "number"):
        e = parse_money(expected) if ftype == "money" else parse_number(expected)
        a = parse_money(actual) if ftype == "money" else parse_number(actual)
        if e is None or a is None:
            # unparseable side: fall back to string comparison
            return compare_values(expected, actual, "string")
        if round(e, 2) == round(a, 2):
            return "correct"
        if round(abs(e), 2) == round(abs(a), 2):
            return "near"  # sign-only difference (accounting-parens convention)
        return "wrong"

    if ftype == "date":
        e, a = parse_date_candidates(expected), parse_date_candidates(actual)
        if not e or not a:
            return compare_values(expected, actual, "string")
        for (ey, em, ed) in e:
            for (ay, am, ad) in a:
                if em == am and ed == ad and (ey is None or ay is None or ey == ay):
                    return "correct"
        for (ey, em, ed) in e:
            for (ay, am, ad) in a:
                if em == am and ed == ad:
                    return "near"  # same day+month, different year
        return "wrong"

    # string
    e, a = normalize_string(expected), normalize_string(actual)
    if e == a:
        return "correct"
    if len(e) >= 4 and len(a) >= 4 and (e in a or a in e):
        return "near"
    if difflib.SequenceMatcher(None, e, a).ratio() >= 0.85:
        return "near"
    return "wrong"


def value_in_text(value: Any, doc_text: str, ftype: str = "string") -> bool:
    """Is this extracted value present in the source document at all?

    Grounding check for hallucinations. A value the document never contains is
    an INVENTION (the model made it up). A value that is in the document but
    landed in a slot gold leaves empty is a MISPLACEMENT — damaging, but a
    different defect with a different fix. Both are counted as hallucinated
    per the required contract; this flag is what lets a reader tell them apart.
    """
    if is_empty(value) or not doc_text:
        return False

    # Numeric grounding is attempted whenever the value READS as a number,
    # not only when it is typed as one: cells in predicted tables that matched
    # no gold table carry no column types, and comparing 7750.0 to a printed
    # "$7,750.00" as strings fails on the thousands separator alone.
    n = parse_money(value)
    if n is not None:
        clean = doc_text
        for ch in _CURRENCY:
            clean = clean.replace(ch, "")  # "($1,245.00)" -> "(1,245.00)"
        for tok in re.findall(r"\(?-?[\d,]*\.?\d+\)?", clean):
            t = parse_money(tok)
            if t is not None and round(abs(t), 2) == round(abs(n), 2):
                return True
        if ftype in ("money", "number"):
            return False

    v = normalize_string(value)
    if len(v) < 2:
        return False
    t = normalize_string(doc_text)
    if v in t:
        return True
    # tolerate line-wrap/word-order noise: all words of the value present
    words = [w for w in re.findall(r"[a-z0-9]+", v) if len(w) > 2]
    return bool(words) and all(w in t for w in words)


def classify_field(expected: Any, actual: Any, ftype: str) -> str:
    """Full 4(+1) outcome classification for one field.

    Returns 'correct' | 'near' | 'wrong' | 'missed' | 'hallucinated' |
    'empty_ok' (gold empty, extraction empty — not an extraction event).
    """
    if is_empty(expected):
        return "empty_ok" if is_empty(actual) else "hallucinated"
    if is_empty(actual):
        return "missed"
    return compare_values(expected, actual, ftype or "string")


# ── field scoring ────────────────────────────────────────────────────────────

def score_fields(gold_fields: dict, field_types: dict, pred_fields: dict) -> dict:
    """Score every gold field plus every predicted field not in gold
    (a prediction for a field gold knows nothing about is a hallucination)."""
    results = {}
    for name, expected in gold_fields.items():
        ftype = field_types.get(name, "string")
        actual = pred_fields.get(name)
        results[name] = {
            "outcome": classify_field(expected, actual, ftype),
            "expected": expected,
            "actual": actual,
            "type": ftype,
        }
    for name, actual in pred_fields.items():
        if name in results or is_empty(actual):
            continue
        results[name] = {
            "outcome": "hallucinated",
            "expected": None,
            "actual": actual,
            "type": field_types.get(name, "string"),
        }
    return results


# ── table scoring ────────────────────────────────────────────────────────────

def _row_score(gold_row: dict, pred_row: dict, col_types: dict) -> float:
    """Fraction of gold-valued cells the predicted row gets right or near."""
    cols = [c for c in gold_row if not is_empty(gold_row.get(c))]
    if not cols:
        return 0.0
    hits = 0.0
    for c in cols:
        a = pred_row.get(c)
        if is_empty(a):
            continue
        cmp = compare_values(gold_row[c], a, col_types.get(c, "string"))
        if cmp == "correct":
            hits += 1.0
        elif cmp == "near":
            hits += 0.75
    return hits / len(cols)


def align_rows(gold_rows: list, pred_rows: list, col_types: dict,
               min_score: float = 0.35) -> list:
    """Greedy best-match alignment. Returns list of (gold_idx, pred_idx)."""
    candidates = []
    for gi, g in enumerate(gold_rows):
        for pi, p in enumerate(pred_rows):
            s = _row_score(g, p, col_types)
            if s >= min_score:
                # prefer higher score; break ties by diagonal proximity
                candidates.append((-s, abs(gi - pi), gi, pi))
    candidates.sort()
    used_g, used_p, pairs = set(), set(), []
    for _negs, _d, gi, pi in candidates:
        if gi in used_g or pi in used_p:
            continue
        used_g.add(gi)
        used_p.add(pi)
        pairs.append((gi, pi))
    return sorted(pairs)


def score_table(gold_rows: list, pred_rows: list, col_types: dict,
                table_name: str = "") -> dict:
    pairs = align_rows(gold_rows, pred_rows, col_types)
    matched_g = {gi for gi, _ in pairs}
    matched_p = {pi for _, pi in pairs}

    cells = []  # every scored cell: outcome + context
    for gi, pi in pairs:
        g, p = gold_rows[gi], pred_rows[pi]
        for col in g:
            out = classify_field(g.get(col), p.get(col), col_types.get(col, "string"))
            cells.append({"row": gi, "pred_row": pi, "column": col,
                          "type": col_types.get(col, "string"),
                          "outcome": out, "expected": g.get(col),
                          "actual": p.get(col)})
        for col in p:
            if col in g or is_empty(p.get(col)):
                continue
            cells.append({"row": gi, "pred_row": pi, "column": col,
                          "type": col_types.get(col, "string"),
                          "outcome": "hallucinated", "expected": None,
                          "actual": p.get(col)})

    missed_rows = []
    for gi, g in enumerate(gold_rows):
        if gi in matched_g:
            continue
        missed_rows.append({"row": gi, "gold": g})
        for col, v in g.items():
            if not is_empty(v):
                cells.append({"row": gi, "pred_row": None, "column": col,
                              "type": col_types.get(col, "string"),
                              "outcome": "missed", "expected": v, "actual": None})

    hallucinated_rows = []
    for pi, p in enumerate(pred_rows):
        if pi in matched_p:
            continue
        hallucinated_rows.append({"pred_row": pi, "pred": p})
        for col, v in p.items():
            if not is_empty(v):
                cells.append({"row": None, "pred_row": pi, "column": col,
                              "type": col_types.get(col, "string"),
                              "outcome": "hallucinated", "expected": None,
                              "actual": v})

    matched_cells = [c for c in cells if c["row"] is not None and c["pred_row"] is not None]
    gold_valued = [c for c in matched_cells if c["outcome"] in
                   ("correct", "near", "wrong", "missed")]
    correct = sum(1 for c in gold_valued if c["outcome"] == "correct")

    return {
        "table": table_name,
        "gold_row_count": len(gold_rows),
        "pred_row_count": len(pred_rows),
        "row_count_mismatch": len(pred_rows) - len(gold_rows),
        "matched_rows": len(pairs),
        "row_precision": (len(pairs) / len(pred_rows)) if pred_rows else None,
        "row_recall": (len(pairs) / len(gold_rows)) if gold_rows else None,
        "cell_accuracy": (correct / len(gold_valued)) if gold_valued else None,
        "missed_rows": missed_rows,
        "hallucinated_rows": hallucinated_rows,
        "cells": cells,
    }


# ── document + suite aggregation ─────────────────────────────────────────────

OUTCOME_KEYS = ("correct", "near", "wrong", "missed", "hallucinated", "empty_ok")


def _tally(counter: dict, outcome: str):
    counter[outcome] = counter.get(outcome, 0) + 1


def score_document(label: dict, adapted: dict, doc_text: str = "") -> dict:
    """label: gold label dict. adapted: {'fields': {...}, 'tables': {...}} from
    the adapter. doc_text: the source document's text (pdfplumber), used only
    to split hallucinations into inventions vs misplacements."""
    field_results = score_fields(label.get("fields", {}),
                                 label.get("field_types", {}),
                                 adapted.get("fields", {}))

    table_results = {}
    gold_tables = label.get("tables", {}) or {}
    pred_tables = dict(adapted.get("tables", {}) or {})
    for tname, gold_rows in gold_tables.items():
        col_types = (label.get("table_types", {}) or {}).get(tname, {})
        pred_rows = pred_tables.pop(tname, [])
        table_results[tname] = score_table(gold_rows, pred_rows, col_types, tname)
    # predicted tables with no gold counterpart: every row is hallucinated
    for tname, pred_rows in pred_tables.items():
        table_results[tname] = score_table([], pred_rows, {}, tname)

    # grounding: split hallucinations into inventions and misplacements
    def ground(entry):
        if entry.get("outcome") != "hallucinated":
            return
        entry["grounded"] = value_in_text(entry.get("actual"), doc_text,
                                          entry.get("type", "string"))

    for r in field_results.values():
        ground(r)
    for t in table_results.values():
        for c in t["cells"]:
            ground(c)

    counts = {}
    ungrounded = 0
    for r in field_results.values():
        _tally(counts, r["outcome"])
        if r.get("outcome") == "hallucinated" and not r.get("grounded"):
            ungrounded += 1
    for t in table_results.values():
        for c in t["cells"]:
            _tally(counts, c["outcome"])
            if c.get("outcome") == "hallucinated" and not c.get("grounded"):
                ungrounded += 1

    gold_valued = sum(counts.get(k, 0) for k in ("correct", "near", "wrong", "missed"))
    extracted = sum(counts.get(k, 0) for k in ("correct", "near", "wrong", "hallucinated"))
    return {
        "document_id": label.get("document_id"),
        "document_type": label.get("document_type"),
        "fields": field_results,
        "tables": table_results,
        "counts": counts,
        "hallucinated_ungrounded": ungrounded,
        "accuracy": (counts.get("correct", 0) / gold_valued) if gold_valued else None,
        "hallucination_rate": (counts.get("hallucinated", 0) / extracted) if extracted else None,
        "invention_rate": (ungrounded / extracted) if extracted else None,
    }


def summarize(doc_results: list) -> dict:
    """Aggregate across documents: overall, per document type, per field type."""
    total = {}
    by_type = {}
    by_ftype = {}

    def add(counter, outcome, n=1):
        counter[outcome] = counter.get(outcome, 0) + n

    def add_entry(counters, e):
        for c in counters:
            add(c, e["outcome"])
            if e.get("outcome") == "hallucinated" and not e.get("grounded"):
                add(c, "_ungrounded")

    for d in doc_results:
        dt = d.get("document_type") or "unknown"
        bt = by_type.setdefault(dt, {})
        for r in d["fields"].values():
            add_entry([total, bt, by_ftype.setdefault(r.get("type", "string"), {})], r)
        for t in d["tables"].values():
            for c in t["cells"]:
                add_entry([total, bt, by_ftype.setdefault(c.get("type", "string"), {})], c)

    def rates(c):
        c = dict(c)
        ungrounded = c.pop("_ungrounded", 0)
        gold_valued = sum(c.get(k, 0) for k in ("correct", "near", "wrong", "missed"))
        extracted = sum(c.get(k, 0) for k in ("correct", "near", "wrong", "hallucinated"))
        return {
            "counts": c,
            "gold_valued": gold_valued,
            "accuracy": (c.get("correct", 0) / gold_valued) if gold_valued else None,
            "near_rate": (c.get("near", 0) / gold_valued) if gold_valued else None,
            "hallucinated": c.get("hallucinated", 0),
            "hallucination_rate": (c.get("hallucinated", 0) / extracted) if extracted else None,
            "hallucinated_ungrounded": ungrounded,
            "invention_rate": (ungrounded / extracted) if extracted else None,
        }

    return {
        "overall": rates(total),
        "by_document_type": {k: rates(v) for k, v in sorted(by_type.items())},
        "by_field_type": {k: rates(v) for k, v in sorted(by_ftype.items())},
    }
