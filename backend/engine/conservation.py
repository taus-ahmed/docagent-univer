"""Conservation: nothing printed at a structural position leaves the page
without a word (Run S, Stage 1a).

The general "printed but not extracted" check. A person copying a page into
a sheet copies every table-row cell, every group header, every subtotal and
total, every labelled field's value. This module lists those positions'
numbers off the engine's own page words (never the model's text), compares
them with every value of the output, and names every one that is neither
held by a value nor already named by an existing reason.

What is a STRUCTURAL token (deterministic, shape only, no vocabulary of any
document):

  row     every number on a table-row line: a line holding two or more
          amounts, or a date followed by an amount (`source_inventory.row_kind`,
          plus lines of two amounts and more)
  group   the identifier of a group line (`row_groups.detect`)
  total   the amounts of a total line (a total word, or a line of amounts
          only, under rows) and of a group's subtotal line
  field   a labelled field's value: the number after `Label:`, or the
          amounts closing a label line ("Deposits 9,500.00 25,950.75")

What is NOT, by design:

  * page furniture — a line printed on two or more pages (titles, column
    headings, footers), "Page n of m";
  * paragraph prose — 12+ words, or 8+ ending in a full stop;
  * form metadata — a line naming an OMB number, a revision, a catalogue
    number or a version;
  * phone numbers, percentages, and on a non-row line any number that is
    not its value (a street number, a ZIP code, "Section 897" in a label).

The verdict: a missing token on a NO-TEMPLATE document is an attention
reason (the engine designed the sheet, so the miss is the engine's). On a
TEMPLATED document it is an attention reason when it sits on a row, group or
total line of a page that prints one of the template's tables; anywhere
else the template chose not to ask for it, so it is a `not_captured`
sentence (written under the document in the Results sheet and on the
Legend) and the document is not called incomplete.

Nothing here calls a model and nothing here changes a value.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

# ── tokens ───────────────────────────────────────────────────────────────────

_AMOUNT = re.compile(
    r"^\(?[-+]?[$€£¥]?\s?\(?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2})\)?-?$"
    r"|^\(?[-+]?[$€£¥]\(?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2})?\)?-?$"
    r"|^\(?[-+]?(?:\d{1,3}(?:,\d{3})+)\)?-?$")
_DATE = re.compile(r"^\(?\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\)?$|^\d{4}-\d{2}-\d{2}$")
_PHONE = re.compile(r"^\(?\d{3}\)?[-. ]?\d{3}[-. ]\d{4}$|^1[-.]\d{3}[-.]\d{3}[-.]\d{4}$")
_PERCENT = re.compile(r"%$")
_TRIM = ".,;:"
_TOTAL_WORD = re.compile(r"\b(?:sub-?totals?|totals?|grand|balance\s+due|amount\s+due|net\s+pay)\b",
                         re.I)
_METADATA = re.compile(r"\bOMB\b|\bRev\.|\bCat\.?\s*No\b|\bVersion\b|\bForm\s+\d", re.I)
_PAGE_NO = re.compile(r"\bpage\s+\d+(\s+of\s+\d+)?\b", re.I)
_LABEL_COLON = re.compile(r"^(?P<label>[^:]{2,40}?):\s*(?P<value>\S.*)$")


@dataclass(frozen=True)
class Token:
    page: int
    text: str
    kind: str          # amount | date | id
    role: str          # row | group | total | field
    line: str


def _clean(tok) -> str:
    # a dotted leader printed against its value ("..........0.00")
    t = re.sub(r"^[.…_]{2,}", "", str(tok or "").strip())
    while t and t[-1] in _TRIM and not re.search(r"\.\d{2}$", t):
        t = t[:-1]
    return t


def _digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def amount_value(tok) -> Optional[Decimal]:
    t = _clean(tok)
    if not _AMOUNT.match(t):
        return None
    neg = t.startswith("(") or t.startswith("-") or t.endswith("-") or ")" in t
    try:
        v = Decimal(re.sub(r"[^\d.]", "", t))
    except InvalidOperation:
        return None
    return -v if neg else v


UNREADABLE = "�"


def kind_of(tok) -> Optional[str]:
    t = _clean(tok)
    if not t or _PHONE.match(t) or _PERCENT.search(t):
        return None
    if UNREADABLE in t and re.search(r"\d", t):
        # a figure whose first glyphs have no character in the text layer
        return "unreadable"
    if amount_value(t) is not None:
        return "amount"
    if _DATE.match(t):
        return "date"
    if len(_digits(t)) >= 3 and re.fullmatch(r"[A-Za-z0-9#\-/.*]+", t):
        return "id"
    return None


# ── lines ───────────────────────────────────────────────────────────────────

def _texts(line):
    """The line's words; an unreadable glyph printed against a figure is
    joined to it ("�" + "12" -> "�12"), so the figure is one token."""
    ws = [w for w in line or () if isinstance(w, dict)]
    out, prev = [], None
    for w in ws:
        t = str(w.get("text", ""))
        if prev is not None and out and out[-1].endswith(UNREADABLE) and re.match(r"\d", t)                 and float(w.get("x0", 0) or 0) - float(prev.get("x1", 0) or 0) < 2.0:
            out[-1] += t
        else:
            out.append(t)
        prev = w
    return out


def _shape(text):
    return re.sub(r"\d", "#", re.sub(r"\s+", " ", str(text).strip().casefold()))


def _paragraph(texts) -> bool:
    n = len(texts)
    joined = " ".join(texts).strip()
    return n >= 12 or (n >= 8 and joined.endswith((".", "?")))


def _page_height(lines) -> float:
    b = [float(w.get("bottom", 0) or 0) for ln in lines for w in ln if isinstance(w, dict)]
    return max(b) if b else 0.0


def _row_line(texts) -> bool:
    kinds = [kind_of(t) for t in texts]
    n_amt = kinds.count("amount")
    if n_amt >= 2:
        return True
    return n_amt >= 1 and bool(texts) and kinds[0] == "date"


def _bare_amounts(texts) -> bool:
    return bool(texts) and len(texts) <= 3 and all(kind_of(t) == "amount" for t in texts)


def structural_tokens(page_lines, page_numbers=None) -> list:
    """Every structural token of the document, in reading order."""
    pages = list(page_lines or [])
    numbers = list(page_numbers or range(1, len(pages) + 1))
    seen = {}
    for k, lines in enumerate(pages):
        for ln in lines or ():
            seen.setdefault(_shape(" ".join(_texts(ln))), set()).add(k)
    groups_ident = set()
    try:
        import row_groups as RG
        from text_layer import flatten_pages
        g = RG.detect(flatten_pages(pages))
        if g is not None:
            for grp in g.groups:
                sp = RG.split_group_label(grp.label)
                if sp["ident"]:
                    groups_ident.add((grp.label, sp["ident"]))
    except Exception:          # a helper failing never costs the document
        groups_ident = set()
    group_lines = {lab: ident for lab, ident in groups_ident}
    out = []
    for k, lines in enumerate(pages):
        n = numbers[k] if k < len(numbers) else k + 1
        prev_row = False
        for ln in lines or ():
            texts = _texts(ln)
            if not texts:
                continue
            text = " ".join(texts)
            if len(pages) > 1 and len(seen.get(_shape(text), ())) >= 2:
                continue
            if _paragraph(texts) or _METADATA.search(text):
                continue
            if _PAGE_NO.search(text) and len(texts) <= 8:
                continue
            if text.strip() in group_lines:
                ident = group_lines[text.strip()]
                out.append(Token(n, ident, kind_of(ident) or "id", "group", text))
                prev_row = False
                continue
            is_row = _row_line(texts)
            # a summary line: a count, then the amount it sums
            # ("Checks/withdrawals 54 $14,365.21")
            counted = (len(texts) >= 3 and kind_of(texts[-1]) == "amount"
                       and re.fullmatch(r"\d{1,4}", _clean(texts[-2]) or "")
                       and not any(kind_of(t) for t in texts[:-2]))
            total = (bool(_TOTAL_WORD.search(text)) or bool(counted)
                     or (_bare_amounts(texts) and prev_row))
            if is_row and not total:
                for t in texts:
                    kd = kind_of(t)
                    if kd:
                        out.append(Token(n, _clean(t), kd, "row", text))
                prev_row = True
                continue
            if total:
                for t in texts:
                    if kind_of(t) in ("amount", "unreadable"):
                        out.append(Token(n, _clean(t), kind_of(t), "total", text))
                prev_row = False
                continue
            m = _LABEL_COLON.match(text)
            if m:
                for t in m.group("value").split():
                    kd = kind_of(t)
                    if kd:
                        out.append(Token(n, _clean(t), kd, "field", text))
                prev_row = False
                continue
            # a label line closing in amounts: those amounts are its value
            tail = []
            for t in reversed(texts):
                if kind_of(t) == "amount":
                    tail.append(t)
                else:
                    break
            if tail and len(tail) < len(texts):
                for t in reversed(tail):
                    out.append(Token(n, _clean(t), "amount", "field", text))
            prev_row = False
    return out


# ── what the output holds ────────────────────────────────────────────────────

class Holder:
    """Every number of the output's values: amounts by value (notation
    aside), identifiers and dates by their digits inside any value."""

    def __init__(self, values: Iterable):
        self.amounts = set()
        self.digits = []
        for v in values:
            s = str(v if v is not None else "")
            if not s.strip():
                continue
            # a number is a WHOLE token of the value ("1,250.00", "$1250",
            # "(75.00)"), never digits inside a word ("REF016" is not 16)
            for t in s.split():
                t = _clean(t)
                a = amount_value(t)
                if a is not None:
                    self.amounts.add(abs(a))
                    continue
                if re.fullmatch(r"\(?-?[$€£¥]?\d[\d,]*(?:\.\d+)?\)?-?", t):
                    raw = re.sub(r"[^\d.]", "", t)
                    try:
                        self.amounts.add(abs(Decimal(raw)))
                    except InvalidOperation:
                        pass
            d = _digits(s)
            if d:
                self.digits.append(d)

    def holds(self, tok: Token) -> bool:
        if tok.kind == "unreadable":
            return False          # no value can hold a figure nobody can read
        if tok.kind == "amount":
            a = amount_value(tok.text)
            if a is not None and abs(a) in self.amounts:
                return True
        d = _digits(tok.text)
        return bool(d) and any(d in s for s in self.digits)


def output_values(extracted_fields=None, tables_out=None, subtotals=None) -> list:
    vals = list((extracted_fields or {}).values())
    for rows in (tables_out or {}).values():
        for r in rows or ():
            if isinstance(r, dict):
                vals += [v for k, v in r.items() if not str(k).startswith("_")]
    for rows in (subtotals or {}).values():
        for r in rows or ():
            if isinstance(r, dict):
                vals += [v for k, v in r.items() if not str(k).startswith("_")]
    return [v for v in vals if v is not None and str(v).strip()]


# ── the check ───────────────────────────────────────────────────────────────

_ROLE_WORDS = {"row": "table row", "group": "group header", "total": "total",
               "field": "labelled field"}
NAMED = 10


def _said(tok: Token, said) -> bool:
    t = tok.text
    return any(t in s for s in said)


def _list(tokens) -> str:
    uniq = list(dict.fromkeys(t.text for t in tokens))
    shown = ", ".join(uniq[:NAMED])
    return shown + (f" and {len(uniq) - NAMED} more" if len(uniq) > NAMED else "")


def _sentence(page, toks) -> str:
    roles = list(dict.fromkeys(_ROLE_WORDS[t.role] for t in toks))
    n = len(list(dict.fromkeys(t.text for t in toks)))
    return (f"Page {page} prints {n} figure{'s' if n != 1 else ''} at "
            f"{'/'.join(roles)} position{'s' if len(roles) > 1 else ''} that "
            f"{'are' if n != 1 else 'is'} in no cell: {_list(toks)}.")


def check(page_lines, page_numbers, values, said=(), *, templated=False,
          band_pages=None) -> dict:
    """{"attention": [sentences], "not_captured": [sentences],
    "missing": [Token], "tokens": n}.

    `values`: every value of the output. `said`: every sentence the result
    already carries (attention, not_captured, flags, notes) — a token one of
    them names is visible already and is not said again. `band_pages`: the
    pages printing one of a template's tables (templated documents only)."""
    toks = structural_tokens(page_lines, page_numbers)
    holder = Holder(values)
    said = [str(s) for s in said or () if s]
    missing = [t for t in toks if not holder.holds(t) and not _said(t, said)]
    attention, notes = [], []
    by_page = {}
    excluded = []
    for t in missing:
        if templated:
            on_table = t.role in ("row", "group", "total") and (
                band_pages is None or t.page in band_pages)
            if not on_table and t.kind != "amount":
                # a template is the user's own choice of what to copy: an
                # identifier or a date it does not ask for is deliberately
                # left out. Money it leaves out is still said.
                excluded.append(t)
                continue
            by_page.setdefault((t.page, "att" if on_table else "note"), []).append(t)
        else:
            by_page.setdefault((t.page, "att"), []).append(t)
    for (page, kind), ts in sorted(by_page.items()):
        if kind == "att":
            attention.append(_sentence(page, ts))
        else:
            notes.append(f"Page {page} prints {_list(ts)}, which this template has "
                         f"no cell for.")
    missing = [t for t in missing if t not in excluded]
    return {"attention": attention, "not_captured": notes, "missing": missing,
            "excluded": len(excluded), "tokens": len(toks)}
