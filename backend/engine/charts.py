"""Chart data, aggregated exactly (Decimal) and one currency at a time (Part A5).

    aggregate(eds) -> {"currencies": {CUR: {"by_category", "by_month",
                       "top_items", "distribution"}}, "values": n, "message"}

Built from the CURRENT values of each stored result (a person's edits
included). Amounts in different currencies are never added: every chart is
per currency, and an amount whose currency is not stated is grouped as
"unstated" rather than assumed. An amount whose notation is ambiguous is left
out and counted. Too little data gives a message, never a misleading chart.
"""
from __future__ import annotations

import re
from decimal import Decimal

from amounts import document_hint, parse_amount
from dates import document_order, parse_date

MIN_POINTS = 2

_AMOUNT_COL = re.compile(r"amount|total|debit|price|value|net|paid|charge|spend|cost", re.I)
_TEXT_COL = re.compile(r"desc|narration|particular|payee|merchant|item|detail|vendor|name", re.I)
_DATE_COL = re.compile(r"date|posted", re.I)


def _rows(ed):
    for k, rows in ed.items():
        if isinstance(rows, list) and (k == "table_rows" or k.endswith("_rows")):
            yield ("table" if k == "table_rows" else k[:-5]), [r for r in rows if isinstance(r, dict)]


def _first(row_keys, pattern):
    return next((k for k in row_keys if not str(k).startswith("_") and pattern.search(str(k))), None)


def aggregate(eds) -> dict:
    cur: dict = {}
    used = skipped = 0
    for ed in eds or []:
        if not isinstance(ed, dict):
            continue
        texts = [v for _n, rows in _rows(ed) for r in rows for k, v in r.items() if not str(k).startswith("_")]
        hint = document_hint(texts, ed.get("locale"))
        order, _ = document_order(texts, ed.get("locale"))
        cats = {(n, e["row"]): e.get("category")
                for n, es in (ed.get("categories") or {}).items() for e in es or []
                if isinstance(e, dict) and isinstance(e.get("row"), int)}
        for name, rows in _rows(ed):
            keys = list(dict.fromkeys(k for r in rows for k in r))
            acol, tcol, dcol = _first(keys, _AMOUNT_COL), _first(keys, _TEXT_COL), _first(keys, _DATE_COL)
            if not acol:
                continue
            for i, r in enumerate(rows):
                raw = r.get(acol)
                if raw is None or not str(raw).strip():
                    continue
                a = parse_amount(raw, hint)
                if a.value is None or a.percent:
                    skipped += 1
                    continue
                used += 1
                c = a.currency or ("/".join(a.currencies) if a.currencies else "unstated")
                g = cur.setdefault(c, {"by_category": {}, "by_month": {}, "items": {}, "values": []})
                cat = cats.get((name, i)) or "Uncategorized"
                g["by_category"][cat] = g["by_category"].get(cat, Decimal(0)) + a.value
                d = parse_date(r.get(dcol), order).value if dcol else None
                if d:
                    m = f"{d.year:04d}-{d.month:02d}"
                    g["by_month"][m] = g["by_month"].get(m, Decimal(0)) + a.value
                item = str(r.get(tcol) or "").strip() if tcol else ""
                if item:
                    g["items"][item] = g["items"].get(item, Decimal(0)) + a.value
                g["values"].append(a.value)
    out = {}
    for c, g in cur.items():
        vals = sorted(g["values"])
        out[c] = {
            "by_category": [[k, str(v)] for k, v in sorted(g["by_category"].items(), key=lambda x: -x[1])],
            "by_month": [[k, str(v)] for k, v in sorted(g["by_month"].items())],
            "top_items": [[k, str(v)] for k, v in sorted(g["items"].items(), key=lambda x: -abs(x[1]))[:10]],
            "distribution": _bins(vals),
            "count": len(vals),
        }
    msg = None
    if used < MIN_POINTS:
        msg = "Not enough amounts to chart (at least two are needed)."
    elif len(out) > 1:
        msg = (f"Amounts are in {len(out)} currencies ({', '.join(sorted(out))}); each has its own "
               f"charts and none are added together.")
    return {"currencies": out, "values": used, "left_out_ambiguous": skipped, "message": msg}


def _bins(vals, n=6):
    if len(vals) < MIN_POINTS or vals[0] == vals[-1]:
        return []
    lo, hi = vals[0], vals[-1]
    width = (hi - lo) / n
    edges = [lo + width * k for k in range(n)] + [hi]
    counts = [0] * n
    for v in vals:
        k = min(int((v - lo) / width), n - 1) if width else 0
        counts[k] += 1
    return [[f"{edges[k]:.2f} to {edges[k + 1]:.2f}", counts[k]] for k in range(n)]


__all__ = ["MIN_POINTS", "aggregate"]
