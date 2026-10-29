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
#: a word in any script: letters, joined by an apostrophe, hyphen or &
_WORD = re.compile(r"[^\W\d_][^\W_]*(?:['’&-][^\W\d_][^\W_]*)*")
#: words a sentence may START with in an ordinary summary. Only at the start
#: of a sentence does a capital say nothing; anywhere else it marks a name.
#: A starter outside this list is treated as a name — failing closed costs a
#: plainer summary, failing open shows an invented person as fact.
_STARTERS = frozenset("""
a about across after all almost also although among an and another any are
as at because before between both but by during each either every few for
from given here however if in including it its last less many more most
much neither no nor not of on one only other otherwise our over overall
several since so some such than that the their then there these they this
those though through throughout to two three four five under until up was
were what when where whereas which while with within without yet you your
we
account accounts activity amount amounts balance balances charge charges
cost costs credit credits debit debits deposit deposits document documents
entries entry expense expenses fee fees figures income invoice invoices
item items line lines payment payments purchase purchases receipt receipts
rent revenue row rows sale sales spending spend statement statements sum
summary tax taxes total totals transaction transactions transfer transfers
value values withdrawal withdrawals largest smallest highest lowest biggest
date dates dated period categories category field fields
""".split())
_MONTHS = ["january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december"]
_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_DATEISH = re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b|"
                      r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b|\b[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}\b")


def _norm_num(s):
    return re.sub(r"[,'’\s]", "", s).rstrip(".")


def verify_narrative(text: str, f: dict) -> tuple:
    """(ok, problems): every date, number and name-like word in `text` must
    appear in the facts. Dates are read whole (a date is not three numbers).
    A check that cannot run fails CLOSED: the plain facts summary is shown."""
    try:
        return _verify(text, f)
    except Exception as e:                       # never show unchecked prose
        return False, [f"the summary could not be checked ({type(e).__name__})"]


def _verify(text: str, f: dict) -> tuple:
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
    problems += _number_words(rest, blob, nums)
    problems += _unknown_names(rest, blob, known_dates)
    problems += _unknown_after_triggers(rest, blob)
    return (not problems), problems


#: number words and what they stand for (Recheck R2). English only, as the
#: amount-in-words parser is. A run of them is read as one figure where it
#: parses ("twelve thousand" = 12000); either the figure or every word of the
#: run must be in the facts.
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
             "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}
_MULTIPLES = {"half": "0.5", "halves": "0.5", "quarter": "0.25", "quarters": "0.25",
              "dozen": "12", "dozens": "12", "double": "2", "doubled": "2",
              "twice": "2", "thrice": "3", "triple": "3", "tripled": "3",
              "once": "1", "percent": None, "per": None}
#: fraction denominators: "two-thirds" / "two thirds" is ONE figure (Recheck 2 S2)
_DENOMINATORS = {"half": 2, "halves": 2, "third": 3, "thirds": 3, "quarter": 4,
                 "quarters": 4, "fourth": 4, "fourths": 4, "fifth": 5, "fifths": 5,
                 "sixth": 6, "sixths": 6, "seventh": 7, "sevenths": 7, "eighth": 8,
                 "eighths": 8, "ninth": 9, "ninths": 9, "tenth": 10, "tenths": 10,
                 "hundredth": 100, "hundredths": 100}


def _number_word_value(run):
    from cheque_amounts import _words_to_int
    if len(run) == 1 and run[0] in _ORDINALS:
        return str(_ORDINALS[run[0]])
    if len(run) == 1 and run[0] in _MULTIPLES:
        return _MULTIPLES[run[0]]
    try:
        n = _words_to_int([w for w in run if w != "and"])
    except Exception:
        n = None
    return None if n is None else str(n)


def _is_number_word(w):
    from cheque_amounts import _CRORE, _INDIAN, _SCALES, _TENS, _UNITS
    return (w in _UNITS or w in _TENS or w == "hundred" or w in _SCALES
            or w in _INDIAN or w in _CRORE or w == "trillion"
            or w in _ORDINALS or (w in _MULTIPLES and _MULTIPLES[w]))


def _number_words(text: str, blob: str, nums) -> list:
    """Every spelled-out number not grounded by the facts (Recheck R2):
    "Courier cost twelve thousand dollars." passed because only digits were
    read as numbers."""
    low = blob.casefold()
    words = [w.casefold() for w in re.findall(r"[A-Za-z]+(?:-[A-Za-z]+)*", text)]
    out, run = [], []

    def whole(w):
        return re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", low)

    def fraction(num_words, denom, shown):
        """'two-thirds', 'two thirds', 'one quarter': grounded only as a
        whole — the facts hold n/d, or its percentage with a % (Recheck 2
        S2: "two-thirds" passed because "two" was)."""
        n = _number_word_value(num_words)
        d = _DENOMINATORS[denom]
        ok = False
        if n is not None and n.isdigit():
            ok = bool(re.search(rf"(?<![\d.]){n}\s*/\s*{d}(?![\d])", low))
            p = Decimal(int(n) * 100) / d
            for q in {p.quantize(Decimal(1)), p.quantize(Decimal("0.1")), p.quantize(Decimal("0.01"))}:
                s = format(q.normalize(), "f")
                ok = ok or bool(re.search(rf"(?<![\d.]){re.escape(s)}0*\s*(?:%|percent)", low))
        if not ok and not whole(shown):
            out.append(f"the number {shown!r} is not in the data")

    def close():
        if not run:
            return
        val = _number_word_value(run)
        grounded = (val is not None and (val in nums or f"{val}.00" in nums)) or all(
            re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", low)
            for w in run if w != "and")
        if not grounded:
            out.append(f"the number {' '.join(run)!r} is not in the data")
        run.clear()

    for w in words:
        parts = w.split("-")
        if len(parts) > 1 and any(_is_number_word(p) or p in _DENOMINATORS for p in parts):
            if all(_is_number_word(p) and p not in _ORDINALS for p in parts):
                run.extend(parts)                  # 'twenty-five', read with its run
                continue
            if run and run[-1] == "and":
                run.pop()
            close()
            if parts[-1] in _DENOMINATORS and all(_is_number_word(p) for p in parts[:-1]):
                fraction(parts[:-1], parts[-1], w)
            elif not whole(w):                     # 'two-day': whole, or not at all
                out.append(f"the number {w!r} is not in the data")
            continue
        if w in _DENOMINATORS and run:
            if run[-1] == "and":
                run.pop()
            num, shown = list(run), " ".join(run + [w])
            run.clear()
            fraction(num, w, shown)
            continue
        if _is_number_word(w) or w in _DENOMINATORS or (w == "and" and run):
            run.append(w)
        else:
            if run and run[-1] == "and":
                run.pop()
            close()
    if run and run[-1] == "and":
        run.pop()
    close()
    return list(dict.fromkeys(out))


#: words after which a summary names someone or something (Recheck R2);
#: "on behalf of" is matched as one trigger
_TRIGGERS = frozenset("to by from for with at signed approved paid issued".split())
#: words that may follow a trigger without being a name
_DETERMINERS = frozenset("the a an his her their its this that these those each "
                         "every all our your my some any no".split())


def _unknown_after_triggers(text: str, blob: str) -> list:
    """A lowercase name — "the rent went to alice" — has no capital to mark it.
    The word after a trigger (past any determiner) must be in the facts, a
    common summary word, or a number/date the other checks have read. A word
    that is itself a trigger is checked at its own turn ("approved by jsmith")."""
    low = blob.casefold()
    words = [re.sub(r"['’][sS]$", "", w) for w in _WORD.findall(text)]
    keys = [w.casefold() for w in words]
    out = []
    for i, k in enumerate(keys):
        if keys[i:i + 3] == ["on", "behalf", "of"]:
            j = i + 3
        elif k in _TRIGGERS:
            j = i + 1
        else:
            continue
        while j < len(keys) and keys[j] in _DETERMINERS:
            j += 1
        if j >= len(keys):
            continue
        key = keys[j]
        if (key in _TRIGGERS or key in _STARTERS or key in _MONTHS or key in _DAYS
                or _is_number_word(key) or key == "on"):
            continue
        parts = [p for p in re.split(r"[-&]", key) if p]
        if all(re.search(r"(?<!\w)" + re.escape(p) + r"(?!\w)", low) for p in parts):
            continue
        out.append(f"the name {words[j]!r} is not in the data")
    return list(dict.fromkeys(out))


def _name_like(word: str) -> bool:
    """Capitalised (any cased script), an acronym, or in a script with no
    case at all (Devanagari, CJK, Arabic …) — where nothing marks a name, so
    every word is treated as one."""
    c = word[0]
    return c.isupper() or (c.isalpha() and c.lower() == c.upper())


def _sentence_start(text: str, at: int) -> bool:
    before = text[:at].rstrip(" \t\"'“‘(«")
    return not before.strip() or before[-1] in ".!?:;\n"


def _unknown_names(text: str, blob: str, known_dates) -> list:
    """Every name-like word that is not in the facts (Review-3 F7).

    The old rule looked only at RUNS of two or more capitalised words, so
    "Alice approved the payment" passed with no Alice anywhere in the data. A
    word passes only if the facts hold it as a whole word (case ignored), or
    it starts a sentence and is a common word, or it is the month or weekday
    of a date the facts hold. A possessive is checked without its "'s", and a
    hyphenated name part by part."""
    from datetime import date
    low = blob.casefold()
    calendar = set()
    for iso in known_dates:
        try:
            d = date.fromisoformat(iso)
        except (TypeError, ValueError):
            continue
        calendar |= {_MONTHS[d.month - 1], _DAYS[d.weekday()]}
    from common_words import is_common
    out = []
    for m in _WORD.finditer(text):
        word = re.sub(r"['’][sS]$", "", m.group(0))
        if not word:
            continue
        key = word.casefold()
        if key == "i" or key in calendar:
            continue
        parts = [p for p in re.split(r"[-&]", word) if p]
        if all(re.search(r"(?<!\w)" + re.escape(p.casefold()) + r"(?!\w)", low)
               for p in parts):
            continue
        # Recheck 2 S2: a capital mid-sentence marks a name. Anywhere else —
        # lowercase, or the first word of a sentence ("Paid to …") — the word
        # must be a common word or a number word, so an uncapitalised
        # "alice approved the payment." is a name like any other.
        if _name_like(word) and not _sentence_start(text, m.start()):
            out.append(f"the name {word!r} is not in the data")
            continue
        if all(p.casefold() in _STARTERS or is_common(p) or _is_number_word(p.casefold())
               or p.casefold() in _DENOMINATORS for p in parts):
            continue
        out.append(f"the name {word!r} is not in the data")
    return list(dict.fromkeys(out))


def narrative_prompt(f: dict) -> str:
    return ("Write a 2-3 sentence plain English summary of this document using ONLY the "
            "facts below. Do not add any number, date or name that is not in the facts. "
            "Do not calculate anything new.\n\nFACTS:\n" + json.dumps(f, ensure_ascii=False)
            + '\n\nReturn ONLY a JSON object: {"summary": "..."}')


__all__ = ["LABEL", "deterministic_text", "facts", "narrative_prompt", "verify_narrative"]
