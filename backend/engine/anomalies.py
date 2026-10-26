"""Anomaly detection by rules, with evidence, and no model (Part A3).

Each anomaly states the RULE, the ROWS it involves and the NUMBERS behind
it, with a severity. Anomalies are informational: they never change a value's
level. They are counted in the review summary, listed on the review screen and
exported on their own sheet.

    detect(ed) -> [{rule, severity, rows, numbers, message}]

Rules (each with a false-positive control — the clean fixtures give none):

  duplicate_row        same description, amount and date (exact) — high
  near_duplicate_row   same amount and date, or same description and amount
                       within 3 days — medium
  outlier_amount       |x - median| > 5 MAD within ONE category the rules
                       assigned, at least 8 values — medium. Never over the
                       whole column: rent beside stationery is not an outlier
  round_amounts        >= 40% of >= 8 amounts are multiples of 100 — low
  weekend_date         a row dated Saturday or Sunday, when <= 20% of the
                       table's rows are — low
  out_of_period_date   a row dated outside the document's own from/to dates — high
  sequence_gap / sequence_repeat   in a column of document/cheque numbers — medium
  unusual_non_positive a zero or negative amount in a column >= 90% positive
                       (>= 5 values) — low
  totals_mismatch      a total check failed (from the validators) — high
  currency_mix         amounts in more than one currency — medium

At most CAP anomalies, sorted by severity then rule.
"""
from __future__ import annotations

import re
import statistics
from decimal import Decimal

from amounts import currency_agreement, document_hint, parse_amount
from dates import document_order, parse_date

CAP = 50
_SEV = {"high": 0, "medium": 1, "low": 2}

_AMOUNT_COL = re.compile(r"amount|total|debit|credit|price|value|net|gross|paid|charge|sum", re.I)
_DATE_COL = re.compile(r"date|posted|day", re.I)
_TEXT_COL = re.compile(r"desc|narration|particular|payee|merchant|item|detail|memo|vendor|name", re.I)
_SEQ_COL = re.compile(r"(cheque|check|invoice|receipt|voucher|doc(ument)?|serial|ref)\s*(no|num|number|#)|^(no|#)$", re.I)


def _tables(ed):
    for k, rows in ed.items():
        if isinstance(rows, list) and (k == "table_rows" or k.endswith("_rows")) and rows:
            yield ("table" if k == "table_rows" else k[:-5]), [r for r in rows if isinstance(r, dict)]


def _cols(rows, pattern):
    keys = []
    for r in rows:
        for k in r:
            if not str(k).startswith("_") and pattern.search(str(k)) and k not in keys:
                keys.append(k)
    return keys


def detect(ed: dict) -> list:
    if not isinstance(ed, dict):
        return []
    texts = list((ed.get("extracted_fields") or {}).values())
    for _n, rows in _tables(ed):
        texts += [v for r in rows for k, v in r.items() if not str(k).startswith("_")]
    hint = document_hint(texts, ed.get("locale"))
    order, _how = document_order(texts, ed.get("locale"))
    cats = {(name, e["row"]): e.get("category")
            for name, es in (ed.get("categories") or {}).items() for e in es or []
            if isinstance(e, dict) and e.get("level") == "grounded"}
    out = []

    def add(rule, sev, rows, numbers, message):
        out.append({"rule": rule, "severity": sev, "rows": rows,
                    "numbers": {k: str(v) for k, v in numbers.items()}, "message": message})

    period = _period(ed, order)
    for name, rows in _tables(ed):
        acol = next(iter(_cols(rows, _AMOUNT_COL)), None)
        dcol = next(iter(_cols(rows, _DATE_COL)), None)
        tcol = next(iter(_cols(rows, _TEXT_COL)), None)
        amt = {i: parse_amount(r.get(acol), hint).value if acol else None for i, r in enumerate(rows)}
        dts = {i: parse_date(r.get(dcol), order).value if dcol else None for i, r in enumerate(rows)}
        txt = {i: re.sub(r"\s+", " ", str(r.get(tcol) or "")).strip().lower() if tcol else ""
               for i, r in enumerate(rows)}
        ref = lambda i: f"{name}_rows[{i}]"  # noqa: E731
        # duplicates
        seen, flagged = {}, set()
        for i in range(len(rows)):
            if amt[i] is None or not txt[i]:
                continue
            k = (txt[i], amt[i], dts[i])
            if k in seen:
                add("duplicate_row", "high", [ref(seen[k]), ref(i)], {"amount": amt[i]},
                    f"{name}: rows {seen[k] + 1} and {i + 1} have the same description, amount and date")
                flagged |= {seen[k], i}
            else:
                seen[k] = i
        idx = [i for i in range(len(rows)) if amt[i] is not None]
        for a in idx:
            for b in idx:
                if b <= a or {a, b} <= flagged or amt[a] != amt[b]:
                    continue
                same_day = dts[a] and dts[a] == dts[b] and txt[a] != txt[b]
                near_day = (txt[a] and txt[a] == txt[b] and dts[a] and dts[b]
                            and dts[a] != dts[b] and abs((dts[a] - dts[b]).days) <= 3)
                if same_day or near_day:
                    add("near_duplicate_row", "medium", [ref(a), ref(b)], {"amount": amt[a]},
                        f"{name}: rows {a + 1} and {b + 1} have the same amount and "
                        + ("date" if same_day else "description within 3 days"))
                    flagged |= {a, b}
        # outliers per category (else the whole column)
        groups = {}
        for i in idx:
            groups.setdefault(cats.get((name, i), "*"), []).append(i)
        for cat, members in groups.items():
            vals = [float(amt[i]) for i in members]
            if cat == "*" or len(vals) < 8:
                continue
            med = statistics.median(vals)
            mad = statistics.median([abs(v - med) for v in vals])
            if not mad:
                continue
            for i in members:
                z = abs(float(amt[i]) - med) / mad
                if z > 5:
                    add("outlier_amount", "medium", [ref(i)],
                        {"amount": amt[i], "median": round(med, 2), "mad": round(mad, 2)},
                        f"{name}: row {i + 1}'s amount is far from the others in {cat} "
                        f"({z:.1f} MADs from the median)")
        # round numbers
        nz = [i for i in idx if amt[i] != 0]
        rnd = [i for i in nz if amt[i] % 100 == 0]
        if len(nz) >= 8 and len(rnd) / len(nz) >= 0.4:
            add("round_amounts", "low", [ref(i) for i in rnd], {"round": len(rnd), "of": len(nz)},
                f"{name}: {len(rnd)} of {len(nz)} amounts are whole hundreds")
        # dates
        dated = [i for i in range(len(rows)) if dts[i]]
        wk = [i for i in dated if dts[i].weekday() >= 5]
        if dated and wk and len(wk) / len(dated) <= 0.2:
            for i in wk:
                add("weekend_date", "low", [ref(i)], {"date": dts[i].isoformat()},
                    f"{name}: row {i + 1} is dated on a {dts[i].strftime('%A')}")
        if period:
            for i in dated:
                if not (period[0] <= dts[i] <= period[1]):
                    add("out_of_period_date", "high", [ref(i)],
                        {"date": dts[i].isoformat(), "from": period[0].isoformat(), "to": period[1].isoformat()},
                        f"{name}: row {i + 1}'s date is outside the document's period")
        # sequences
        for scol in _cols(rows, _SEQ_COL):
            nums = [(i, int(re.sub(r"\D", "", str(rows[i].get(scol) or ""))))
                    for i in range(len(rows)) if re.fullmatch(r"\D{0,4}\d{1,9}", str(rows[i].get(scol) or "").strip())]
            if len(nums) < 3:
                continue
            counts = {}
            for i, n in nums:
                counts.setdefault(n, []).append(i)
            for n, where in counts.items():
                if len(where) > 1:
                    add("sequence_repeat", "medium", [ref(i) for i in where], {"number": n},
                        f"{name}: {scol} {n} appears {len(where)} times")
            ordered = sorted(set(n for _i, n in nums))
            gaps = [(a, b) for a, b in zip(ordered, ordered[1:]) if 1 < b - a <= 50]
            for a, b in gaps[:5]:
                add("sequence_gap", "medium", [], {"after": a, "before": b},
                    f"{name}: {scol} jumps from {a} to {b} ({b - a - 1} missing)")
        # non-positive amounts in a positive column
        if len(idx) >= 5:
            pos = [i for i in idx if amt[i] > 0]
            if len(pos) / len(idx) >= 0.9:
                for i in idx:
                    if amt[i] <= 0:
                        add("unusual_non_positive", "low", [ref(i)], {"amount": amt[i]},
                            f"{name}: row {i + 1} is {amt[i]} in a column that is otherwise positive")
    # totals the validators already failed
    prov = ed.get("field_provenance") or {}
    bad = sorted(r for r, p in prov.items()
                 if any(str(x).endswith("_mismatch") and x != "minor_units_mismatch"
                        for x in (p or {}).get("review_reasons") or []))
    if bad:
        add("totals_mismatch", "high", bad, {"values": len(bad)},
            "a total, balance or amount check failed — see the values marked for review")
    verdict, named = currency_agreement(texts)
    if verdict != "ok":
        add("currency_mix", "medium", [], {"currencies": ", ".join(named)},
            f"amounts in more than one currency ({', '.join(named)})")
    out.sort(key=lambda a: (_SEV[a["severity"]], a["rule"]))
    if len(out) > CAP:
        more = len(out) - CAP
        out = out[:CAP] + [{"rule": "more", "severity": "low", "rows": [], "numbers": {"more": str(more)},
                            "message": f"{more} more anomalies not listed"}]
    return out


def _period(ed, order):
    """(from, to) from the document's own fields labelled as a period's ends."""
    fields = {f.get("ref"): str(f.get("row_label") or "").lower()
              for f in ((ed.get("slot_map") or {}).get("fields") or [])}
    vals = ed.get("extracted_fields") or {}
    start = end = None
    for ref, lab in fields.items():
        d = parse_date(vals.get(ref), order).value if vals.get(ref) else None
        if not d:
            continue
        if re.search(r"\b(from|start|begin|opening)\b", lab):
            start = d
        elif re.search(r"\b(to|end|through|until|closing)\b", lab) and "due" not in lab:
            end = d
    return (start, end) if start and end and start <= end else None


__all__ = ["CAP", "detect"]
