"""Document summaries that cannot invent numbers (Part A4).

    facts(ed)                  -> the summary's raw material, computed here
    deterministic_text(facts)  -> a plain summary built from the facts alone
    verify_narrative(text, facts) -> (ok, problems)

A model may write PROSE from the facts (the job worker decides whether it is
allowed and counts the call). The prose is then checked: every number, date
and capitalised name in it must exist in the facts; otherwise it is thrown
away and the deterministic summary is shown with a notice. A summary is never
a verified value: it is labelled "generated, verify against the data".
"""
from __future__ import annotations

import json
import re
from decimal import Decimal

from amounts import document_hint, parse_amount
from dates import document_order, parse_date

LABEL = "generated, verify against the data"

_AMOUNT_COL = re.compile(r"amount|total|debit|credit|price|value|net|gross|paid|charge", re.I)
_TEXT_COL = re.compile(r"desc|narration|particular|payee|merchant|item|detail|memo|vendor|name", re.I)


def _money(d: Decimal) -> str:
    return f"{d:,.2f}" if d != d.to_integral_value() or d.as_tuple().exponent < 0 else f"{d:,}"


def facts(ed: dict) -> dict:
    ed = ed if isinstance(ed, dict) else {}
    fields = ed.get("extracted_fields") or {}
    labels = {f.get("ref"): f.get("row_label") for f in ((ed.get("slot_map") or {}).get("fields") or [])}
    texts = list(fields.values())
    tables = {}
    for k, rows in ed.items():
        if isinstance(rows, list) and (k == "table_rows" or k.endswith("_rows")) and rows:
            tables["table" if k == "table_rows" else k[:-5]] = [r for r in rows if isinstance(r, dict)]
    for rows in tables.values():
        texts += [v for r in rows for c, v in r.items() if not str(c).startswith("_")]
    hint = document_hint(texts, ed.get("locale"))
    order, _ = document_order(texts, ed.get("locale"))
    totals, items, dates = {}, [], []
    for name, rows in tables.items():
        acol = next((c for r in rows for c in r if not str(c).startswith("_") and _AMOUNT_COL.search(str(c))), None)
        tcol = next((c for r in rows for c in r if not str(c).startswith("_") and _TEXT_COL.search(str(c))), None)
        for r in rows:
            for c, v in r.items():
                if not str(c).startswith("_"):
                    d = parse_date(v, order).value
                    if d:
                        dates.append(d)
            if not acol:
                continue
            a = parse_amount(r.get(acol), hint)
            if a.value is None:
                continue
            cur = a.currency or ("/".join(a.currencies) if a.currencies else "unstated")
            key = f"{name}:{acol}:{cur}"
            totals[key] = totals.get(key, Decimal(0)) + a.value
            items.append((a.value, cur, str(r.get(tcol) or "").strip()))
    for v in fields.values():
        d = parse_date(v, order).value
        if d:
            dates.append(d)
    cats = {}
    for es in (ed.get("categories") or {}).values():
        for e in es or []:
            if isinstance(e, dict):
                cats[e.get("category")] = cats.get(e.get("category"), 0) + 1
    items.sort(key=lambda x: -abs(x[0]))
    return {
        "document_type": ed.get("document_type") or "",
        "fields": {str(labels.get(r) or r): str(v) for r, v in fields.items() if str(v).strip()},
        "tables": {n: len(rows) for n, rows in tables.items()},
        "totals": {k: _money(v) for k, v in totals.items()},
        "date_range": [min(dates).isoformat(), max(dates).isoformat()] if dates else [],
        "top_items": [{"amount": _money(a), "currency": c, "item": t} for a, c, t in items[:3]],
        "categories": cats,
    }


def deterministic_text(f: dict) -> str:
    parts = []
    if f["tables"]:
        parts.append("; ".join(f"{n}: {k} row{'s' if k != 1 else ''}" for n, k in f["tables"].items()))
    for key, v in f["totals"].items():
        name, col, cur = key.split(":", 2)
        parts.append(f"{col} in {name} adds up to {v} ({cur})")
    if f["date_range"]:
        a, b = f["date_range"]
        parts.append(f"dates from {a} to {b}" if a != b else f"dated {a}")
    if f["top_items"]:
        t = f["top_items"][0]
        parts.append(f"largest item {t['item'] or '(no description)'}: {t['amount']} ({t['currency']})")
    if f["categories"]:
        parts.append("categories: " + ", ".join(f"{c} {n}" for c, n in sorted(f["categories"].items())))
    if not parts:
        parts.append(f"{len(f['fields'])} field value(s) extracted")
    return ". ".join(p[0].upper() + p[1:] for p in parts) + "."


_NUM = re.compile(r"\d[\d,.'’]*\d|\d")
_NAME = re.compile(r"\b([A-Z][a-zA-Z&'-]+(?:\s+[A-Z][a-zA-Z&'-]+)+)")
_DATEISH = re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b|"
                      r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b|\b[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}\b")


def _norm_num(s):
    return re.sub(r"[,'’\s]", "", s).rstrip(".")


def verify_narrative(text: str, f: dict) -> tuple:
    """(ok, problems): every date, number and multi-word capitalised name in
    `text` must appear in the facts. Dates are read whole (a date is not
    three numbers)."""
    blob = json.dumps(f, ensure_ascii=False)
    known_dates = set(f.get("date_range") or [])
    known_dates |= {d.isoformat() for v in (f.get("fields") or {}).values()
                    for d in [parse_date(v).value] if d}
    lo, hi = (f.get("date_range") or [None, None])[:2]
    problems = []
    rest = text or ""
    for m in _DATEISH.findall(rest):
        d = parse_date(m).value
        iso = d.isoformat() if d else None
        if not iso or (iso not in known_dates and not (lo and hi and iso in (lo, hi))):
            problems.append(f"the date {m} is not in the data")
    rest = _DATEISH.sub(" ", rest)
    nums = {_norm_num(m) for m in _NUM.findall(blob)}
    nums |= {n.split(".")[0] for n in nums if n.endswith(".00")}
    for m in _NUM.findall(rest):
        n = _norm_num(m)
        if n and n not in nums and n.rstrip("0").rstrip(".") not in nums:
            problems.append(f"the number {m} is not in the data")
    low = blob.lower()
    for m in _NAME.findall(rest):
        if m.lower() not in low:
            problems.append(f"the name {m!r} is not in the data")
    return (not problems), problems


def narrative_prompt(f: dict) -> str:
    return ("Write a 2-3 sentence plain English summary of this document using ONLY the "
            "facts below. Do not add any number, date or name that is not in the facts. "
            "Do not calculate anything new.\n\nFACTS:\n" + json.dumps(f, ensure_ascii=False)
            + '\n\nReturn ONLY a JSON object: {"summary": "..."}')


__all__ = ["LABEL", "deterministic_text", "facts", "narrative_prompt", "verify_narrative"]
