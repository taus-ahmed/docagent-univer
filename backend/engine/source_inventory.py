"""
What the PAGE holds, counted without the model (Run A, A3).

The completeness gate needs facts that do not come from the answer it is
checking. This module reads the engine's own page words — the pdfplumber
text layer, the OCR words of a scanned page, and the AcroForm values
`read_page` wrote into them — and counts three things per page:

  (a) filled form-field (widget) values;
  (b) candidate table rows: a line that starts with a date and carries an
      amount (statement-style tables), or a line ending in an amount with a
      second amount or a quantity before it (line-item tables);
  (c) currency-like amounts: a number with two decimals or a currency
      symbol. Dates, years, phone numbers, percentages and long digit runs
      are not amounts.

`coverage()` then compares the extraction with the inventory. Every rule is
CONSERVATIVE on purpose: a gate that lights up on correct documents is the
same failure as the silence it replaces. Each rule says below what it does
NOT count, and why.

Nothing here calls a model and nothing here changes a value.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Optional

from amounts import parse_amount
from dates import looks_like_a_date

# ── tokens ───────────────────────────────────────────────────────────────────

_MONEY = re.compile(
    r"^\(?[-+]?(?:[$€£¥₹]|USD|EUR|GBP|CAD|AUD)?\s?\(?"
    r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2})?\)?-?$")
_HAS_SYMBOL = re.compile(r"[$€£¥₹]|USD|EUR|GBP|CAD|AUD")
_TRAIL = ".,;:"


def _clean(tok: str) -> str:
    t = str(tok or "").strip()
    while t and t[-1] in _TRAIL and not re.search(r"\.\d{2}$", t):
        t = t[:-1]
    return t


def amount_of(tok: str) -> Optional[Decimal]:
    """The value of a currency-like token, or None.

    Two decimals OR a currency symbol is required: a bare integer is a
    count, a box number, a year or an identifier far more often than an
    amount, and calling it one would light up every form."""
    t = _clean(tok)
    if not t or len(t) > 24 or "%" in t:
        return None
    if not _MONEY.match(t):
        return None
    if not (re.search(r"\.\d{2}\)?-?$", t) or _HAS_SYMBOL.search(t)):
        return None
    digits = re.sub(r"\D", "", t)
    if len(digits) >= 12 or not digits:
        return None
    if looks_like_a_date(t):
        return None
    a = parse_amount(t, ".")
    if not a.ok or a.percent:
        return None
    v = abs(a.value)
    return v if v != 0 or "." in t else None


def _is_int(tok: str) -> bool:
    return bool(re.fullmatch(r"\d{1,4}", _clean(tok)))


#: a line naming one of these is a summary line, never a line item
_SUMMARY = re.compile(
    r"\b(sub-?total|total|balance|tax|vat|gst|hst|amount due|due|paid|"
    r"payment|discount|shipping|freight|tip|change|cash|credit|deposit|"
    r"previous|minimum|limit|apr|interest|fee|fees)\b", re.I)


_BALANCE_LINE = re.compile(
    r"\b(?:beginning|opening|previous|starting|ending|closing|new)\s+balance\b"
    r"|\bbalance\s+(?:forward|brought|carried)\b", re.I)


def _words(line):
    return [w for w in line if str(w.get("text", "")).strip()]


def _line_text(line) -> str:
    return " ".join(str(w.get("text", "")) for w in _words(line))


#: OCR's usual misreads of digits in a date ("O7/09/2019", "o7/12/2019",
#: "07/l5/2019"). Applied ONLY to the question "is this token date-shaped",
#: never to a value.
_OCR_DIGIT = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0",
                            "l": "1", "I": "1", "|": "1", "i": "1"})


def _date_led(line) -> bool:
    ws = _words(line)
    if not ws:
        return False
    first = _clean(ws[0]["text"])
    if looks_like_a_date(first):
        return True
    if re.fullmatch(r"[\dOoDQlI|i]{1,4}[/.-][\dOoDQlI|i]{1,2}([/.-][\dOoDQlI|i]{2,4})?",
                    first) and looks_like_a_date(first.translate(_OCR_DIGIT)):
        return True
    if len(ws) > 1:
        two = f"{_clean(ws[0]['text'])} {_clean(ws[1]['text'])}"
        return looks_like_a_date(two)
    return False


def row_kind(line) -> Optional[str]:
    """'dated' / 'item' / None for one visual line."""
    ws = _words(line)
    amts = [amount_of(w["text"]) for w in ws]
    n_amt = sum(1 for a in amts if a is not None)
    if not n_amt:
        return None
    if _date_led(line):
        # A dated balance line is the statement's running total, not a
        # transaction ("09/01 BEGINNING BALANCE 18,240.12").
        if _BALANCE_LINE.search(_line_text(line)):
            return None
        return "dated"
    if amts[-1] is None or len(ws) < 3:
        return None
    if _SUMMARY.search(_line_text(line)):
        return None
    if n_amt >= 2 or any(_is_int(w["text"]) for w in ws[:-1]):
        return "item"
    return None


# ── the inventory ────────────────────────────────────────────────────────────

def _context(line, i, n=6) -> str:
    ws = _words(line)
    lo = max(0, i - n + 1)
    return " ".join(str(w["text"]) for w in ws[lo:i + 1])[:80]


def build(page_lines, page_numbers=None, widget_values=None, origins=None,
          ocr_failed=(), ocr_zero=()) -> dict:
    """{"pages": {file page: {...}}, "totals": {...}} for one document.

    `page_lines` is one list of visual lines per page (words with x0/x1/top);
    `page_numbers` gives each entry's FILE page; `widget_values` is
    {file page: [value, ...]} from the preprocessor."""
    numbers = list(page_numbers or range(1, len(page_lines or []) + 1))
    pages = {}
    for k, n in enumerate(numbers):
        lines = (page_lines or [])[k] if k < len(page_lines or []) else []
        amounts, dated, item = [], 0, 0
        words = 0
        for li, line in enumerate(lines or []):
            ws = _words(line)
            words += len(ws)
            kind = row_kind(line)
            if kind == "dated":
                dated += 1
            elif kind == "item":
                item += 1
            for wi, w in enumerate(ws):
                v = amount_of(w["text"])
                if v is not None:
                    amounts.append({"value": _clean(w["text"]), "norm": str(v),
                                    "line": li, "row_kind": kind,
                                    "context": _context(line, wi)})
        state = None
        if n in set(ocr_failed or ()):
            state = "ocr_failed"
        elif n in set(ocr_zero or ()) or (words == 0 and (origins or {}).get(n) == "ocr"):
            state = "ocr_zero_words"
        pages[n] = {
            "origin": (origins or {}).get(n),
            "words": words,
            "widget_values": list((widget_values or {}).get(n) or []),
            "dated_rows": dated,
            "item_rows": item,
            "amounts": amounts,
            "unreadable": state,
        }
    return {"pages": pages, "totals": {
        "pages": len(pages),
        "words": sum(p["words"] for p in pages.values()),
        "widget_values": sum(len(p["widget_values"]) for p in pages.values()),
        "dated_rows": sum(p["dated_rows"] for p in pages.values()),
        "item_rows": sum(p["item_rows"] for p in pages.values()),
        "amounts": sum(len(p["amounts"]) for p in pages.values()),
    }}


# ── template ↔ page ──────────────────────────────────────────────────────────

#: words too common in labels to say a label is printed
_GENERIC = {"total", "totals", "amount", "amounts", "balance", "number", "date",
            "name", "value", "listed", "other", "from", "with", "this", "that",
            "page", "line", "code", "type", "and", "the", "for", "per", "box",
            "item", "items", "description", "details", "info", "information",
            "current", "period", "year", "month", "address", "first", "last"}


def _stems(text) -> list:
    return [w for w in re.findall(r"[a-z]{4,}", str(text or "").lower())
            if w not in _GENERIC]


_STOP = {"and", "the", "for", "per", "of", "no", "to", "in", "on", "at"}


def _head_stems(text) -> list:
    """A table HEADING's words. Unlike a label's, generic words count: a
    heading row is made of Date, Description, Amount, Balance."""
    return [w for w in re.findall(r"[a-z]{3,}", str(text or "").lower())
            if w not in _STOP]


def _word_matches(stem: str, word: str) -> bool:
    w = re.sub(r"[^a-z]", "", str(word or "").lower())
    if len(w) < 4:
        return False
    k = min(len(stem), len(w), 6)
    return w[:k] == stem[:k] and abs(len(w) - len(stem)) <= 4


def band_kind(table) -> str:
    heads = " ".join(str(c.get("header", "")) for c in table.get("columns") or [])
    return "dated" if re.search(r"\bdate\b", heads, re.I) else "item"


def page_has_band(lines, table) -> bool:
    """Does this page print the band's headings? At least half of them, and
    at least two (one for a band of two columns or fewer). A page that does not
    is "no matching table", and its lines are never counted as rows the band
    missed — the guard that keeps a bank-transactions template quiet on a
    vendor list or a receipts guide."""
    heads = [h for h in (c.get("header", "") for c in table.get("columns") or [])
             if _head_stems(h)]
    if not heads:
        return False
    words = [w.get("text", "") for ln in lines or [] for w in _words(ln)]
    hit = 0
    for h in heads:
        if any(_word_matches(s, w) for s in _head_stems(h) for w in words):
            hit += 1
    need = 1 if len(heads) <= 2 else max(2, (len(heads) + 1) // 2)
    return hit >= need


def label_lines(lines, label):
    """[(line index, word index)] where a distinctive word of `label` is
    printed. Empty when the label has no distinctive word or the page does
    not print one."""
    stems = _stems(label)
    out = []
    for li, ln in enumerate(lines or []):
        for wi, w in enumerate(_words(ln)):
            if any(_word_matches(s, w.get("text", "")) for s in stems):
                out.append((li, wi))
                break
    return out


def slot_area_amounts(lines, label) -> list:
    """Amounts that sit where `label`'s value would: the first amount to the
    right of a label word on its own line, else the amount on the NEXT line
    whose centre is nearest the label word's (within 40 pt) — the
    column-heading layout, `Withdrawals` over `$10,309.62`."""
    out = []
    for li, wi in label_lines(lines, label):
        ws = _words(lines[li])
        anchor = ws[wi]
        # Same line: the first amount within three words of the label, and
        # nothing but the label's own words, `$` or a colon before it. "Payer
        # made direct sales totaling $5,000" is a sentence, not a value.
        right = None
        for k, w in enumerate(ws[wi + 1:wi + 5]):
            if amount_of(w["text"]) is not None:
                right = w
                break
        if right is not None:
            out.append((li, right))
            continue
        if li + 1 < len(lines):
            cx = (float(anchor["x0"]) + float(anchor["x1"])) / 2
            below = [w for w in _words(lines[li + 1])
                     if amount_of(w["text"]) is not None]
            if below:
                best = min(below, key=lambda w: abs(
                    (float(w["x0"]) + float(w["x1"])) / 2 - cx))
                if abs((float(best["x0"]) + float(best["x1"])) / 2 - cx) <= 40:
                    out.append((li + 1, best))
    return out


# ── coverage ─────────────────────────────────────────────────────────────────

def _placed_numbers(values) -> set:
    out = set()
    for v in values:
        s = str(v or "")
        for tok in re.findall(r"[-(]?[$€£¥₹]?\s?[\d,]+(?:\.\d+)?\)?", s):
            a = parse_amount(tok.strip(), ".")
            if a.ok and not a.percent:
                out.add(abs(a.value))
    return out


def _norm_text(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def coverage(inventory, slots, extracted_fields, tables_out, raw_fields=None,
             page_lines=None, page_numbers=None) -> dict:
    """Compare the extraction with the inventory.

    Returns {"reasons": [plain sentences], "flag_slots": {ref: why},
    "absent": [labels], "widget_unplaced": [...], "unplaced_amounts": [...],
    "unplaced_other": n, "rows": {...}} — `reasons` non-empty means the
    document NEEDS ATTENTION.

    `raw_fields` is the model's answer per slot id ({F1: {value, source}}),
    used for one signal: an empty value WITH a source quote means the model
    found the label and no value (job 25)."""
    pages = (inventory or {}).get("pages") or {}
    numbers = list(page_numbers or sorted(pages))
    lines_of = {n: ((page_lines or [])[k] if k < len(page_lines or []) else [])
                for k, n in enumerate(numbers)}
    values = list((extracted_fields or {}).values())
    for rows in (tables_out or {}).values():
        for r in rows:
            values += [v for k, v in r.items() if not str(k).startswith("_")]
    placed = _placed_numbers(values)
    placed_text = [_norm_text(v) for v in values if str(v or "").strip()]

    reasons, flag_slots, absent = [], {}, []

    # ── unreadable pages (scans) ──
    for n, p in sorted(pages.items()):
        if p.get("unreadable"):
            reasons.append(f"Page {n} could not be read "
                           f"({'OCR failed' if p['unreadable'] == 'ocr_failed' else 'OCR found no words'}), "
                           f"so nothing on it was extracted.")

    # ── widget values ──
    widget_all = [(n, v) for n, p in sorted(pages.items())
                  for v in p.get("widget_values") or []]

    def widget_placed(v):
        for part in re.split(r"[\r\n]+", str(v)):
            t = _norm_text(part)
            if len(t) >= 2 and any(t in x or (len(x) >= 4 and x in t)
                                   for x in placed_text):
                return True
        return False

    widget_unplaced = [(n, v) for n, v in widget_all if not widget_placed(v)]
    widgets_missing = (len(widget_unplaced) >= 3
                       and len(widget_unplaced) * 2 >= len(widget_all))
    if widgets_missing:
        reasons.append(
            f"{len(widget_unplaced)} of {len(widget_all)} filled form field(s) on "
            f"the page are not in any cell (e.g. "
            f"{', '.join(repr(str(v).splitlines()[0][:30]) for _n, v in widget_unplaced[:3])}).")

    # ── table rows ──
    rows_report = {}
    for t in slots.get("tables") or []:
        kind = band_kind(t)
        matching = [n for n in numbers if page_has_band(lines_of.get(n), t)]
        cand = sum(pages.get(n, {}).get(f"{kind}_rows", 0) for n in matching)
        rows = (tables_out or {}).get(t["name"]) or []
        got = len(rows)
        rows_report[t["name"]] = {"kind": kind, "matching_pages": matching,
                                  "candidates": cand, "extracted": got,
                                  "no_matching_table": [n for n in numbers
                                                        if n not in matching]}
    # Several bands of one kind share a page's candidates (a pay stub's
    # earnings and deductions are both line items), so the shortfall is
    # judged per kind, against all bands of that kind together.
    by_kind = {}
    for name, r in rows_report.items():
        k = by_kind.setdefault(r["kind"], {"cand_pages": set(), "got": 0,
                                           "names": []})
        k["cand_pages"] |= set(r["matching_pages"])
        k["got"] += r["extracted"]
        k["names"].append(name)
    for kind, k in by_kind.items():
        cand = sum(pages.get(n, {}).get(f"{kind}_rows", 0) for n in k["cand_pages"])
        got = k["got"]
        what = "transaction lines" if kind == "dated" else "line items"
        if cand >= 2 and got == 0:
            reasons.append(f"The page has about {cand} {what} but 0 were "
                           f"extracted (table {', '.join(repr(x) for x in k['names'])}).")
        elif cand - got >= 3 and got * 4 < cand * 3:
            reasons.append(f"The page has about {cand} {what} but only {got} "
                           f"were extracted (table {', '.join(repr(x) for x in k['names'])}).")
    empty_band = {name for name, r in rows_report.items()
                  if r["extracted"] == 0 and r["candidates"] >= 2}

    # ── field slots: absent / empty-flagged ──
    fields = slots.get("fields") or []
    raw_fields = raw_fields if isinstance(raw_fields, dict) else {}
    empty = [f for f in fields if f["ref"] not in (extracted_fields or {})]
    printed_empty = 0
    flagged_amounts = []
    for f in empty:
        label = f.get("row_label", "")
        area_vals = []
        printed = False
        for n in numbers:
            lines = lines_of.get(n) or []
            if label_lines(lines, label):
                printed = True
            for li, w in slot_area_amounts(lines, label):
                v = amount_of(w["text"])
                if v is not None and v not in placed:
                    area_vals.append((n, _clean(w["text"]),
                                      _context(lines[li], _words(lines[li]).index(w))))
        ans = raw_fields.get(f.get("slot_id")) if f.get("slot_id") else None
        quoted = isinstance(ans, dict) and str(ans.get("source") or "").strip() \
            and not str(ans.get("value") or "").strip()
        why = None
        if area_vals:
            n, val, ctx = area_vals[0]
            why = f"amount {val} printed near this label (page {n}) is not in any cell"
            flagged_amounts.append({"page": n, "value": val, "context": ctx,
                                    "slot": label})
        elif quoted:
            why = "the model quoted this label from the page but returned no value"
        elif printed and widgets_missing:
            why = "the label is printed and the form's filled values were not placed"
        if why:
            flag_slots[f["ref"]] = why
        if printed:
            printed_empty += 1
        elif not why:
            absent.append(label)

    seen = {}
    for a in flagged_amounts:
        seen.setdefault((a["page"], a["value"]), []).append(a["slot"])
    for (page, value), labels in seen.items():
        names = ", ".join(f'"{x}"' for x in labels[:3])
        reasons.append(f"Amount {value} appears on page {page} next to {names} "
                       f"but is not in any cell.")

    if fields and len(empty) * 2 > len(fields) and printed_empty * 2 > len(empty) \
            and (inventory or {}).get("totals", {}).get("words", 0) > 0:
        reasons.append(f"{len(empty)} of {len(fields)} field slots are empty while "
                       f"the labels of {printed_empty} of them are printed on the "
                       f"page.")

    # ── unplaced amounts (information; only slot-area ones are reasons) ──
    unplaced = []
    for n, p in sorted(pages.items()):
        for a in p.get("amounts") or []:
            if Decimal(a["norm"]) not in placed:
                unplaced.append({"page": n, "value": a["value"],
                                 "context": a["context"],
                                 "on_candidate_row": bool(a.get("row_kind"))})

    return {"reasons": reasons, "flag_slots": flag_slots, "absent": absent,
            "empty_bands": sorted(empty_band),
            "widget_values": len(widget_all),
            "widget_unplaced": [{"page": n, "value": str(v)[:60]}
                                for n, v in widget_unplaced],
            "unplaced_amounts": unplaced[:40],
            "unplaced_amount_count": len(unplaced),
            "rows": rows_report}


def expected_rows(inventory, slots, page_lines=None, page_numbers=None) -> dict:
    """{table name: candidate rows on its matching pages} — what
    `llm_contract.check_answer` compares an empty table against."""
    pages = (inventory or {}).get("pages") or {}
    numbers = list(page_numbers or sorted(pages))
    out = {}
    for t in slots.get("tables") or []:
        kind = band_kind(t)
        out[t["name"]] = sum(
            pages.get(n, {}).get(f"{kind}_rows", 0)
            for k, n in enumerate(numbers)
            if page_has_band((page_lines or [])[k] if k < len(page_lines or []) else [], t))
    return out
