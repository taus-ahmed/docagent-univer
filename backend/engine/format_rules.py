"""Format rules for slot values (Run B, B3).

1. LAST 4. A slot named "Last 4" (or "... ending") holds exactly four digits,
   and they must be the last four of an account / card number the page
   actually prints. Job 15 answered `58842` for an account printed
   `7301558842` - a collapsed repeated digit - and grounding could not catch
   it, because every digit of it is on the page. The page is the authority:
   a value that is not such a suffix is replaced by the one suffix the page
   offers (machine-corrected), or flagged when it offers several.

2. TYPE CHECKS. A slot whose label says it is money or a date must hold a
   value that parses as one. A value that does not is FLAGGED - never
   dropped, never coerced. A value that does gets its normalised form
   recorded beside it (money as a plain decimal, a date as ISO) while the
   cell keeps the document's own notation, so grounding and the export are
   unchanged. Identifiers, ZIP codes and masked tax ids (`36-8XXXXXXX`) are
   text and are left exactly as printed; zero is a value.
"""
from __future__ import annotations

import re

# "Ending" alone is NOT a last-4 label: "Ending Balance" is money (found live
# in B2.3, where it turned a closing balance into the account suffix).
_LAST4 = re.compile(r"\blast\s*(?:4|four)\b|\b(?:card|account|acct)\s+ending\b"
                    r"|\bending\s+in\b|\blast\s*digits\b", re.I)
_CUE = re.compile(r"^(?:account|acct|card|ending|number|no|#)[.:#]*$", re.I)
_SKIP = re.compile(r"^(?:in|is|number|no|#|:|·|-)$", re.I)
_MASKED = re.compile(r"^[\dXx*•.\-]{4,}$")


def is_last4_slot(label) -> bool:
    return bool(_LAST4.search(str(label or "")))


#: what a cue's own word, or the word before a generic cue, says the number is
_KIND_WORD = {"account": "account", "acct": "account", "checking": "account",
              "savings": "account", "card": "card", "credit": "card",
              "debit": "card", "routing": "routing", "aba": "routing",
              "rtn": "routing", "transit": "routing"}


def _kind_of(words, i) -> str:
    """'account' | 'card' | 'routing' | '' for the cue at words[i]."""
    w = re.sub(r"[.:#]+$", "", words[i].strip().casefold())
    if w in _KIND_WORD:
        return _KIND_WORD[w]
    if i > 0:            # `Account Number`, `Card ending`, `Routing Number`
        prev = re.sub(r"[^a-z]", "", words[i - 1].casefold())
        return _KIND_WORD.get(prev, "")
    return ""


def _aba_valid(d: str) -> bool:
    if len(d) != 9 or not d.isdigit():
        return False
    n = [int(c) for c in d]
    return (3 * (n[0] + n[3] + n[6]) + 7 * (n[1] + n[4] + n[7])
            + (n[2] + n[5] + n[8])) % 10 == 0


def _candidates(all_lines) -> list[tuple[str, str, str]]:
    """[(digits, line text, kind)] for each account/card number printed right
    after a cue word (`Account 7301558842`, `Card ending 7421`, `Account:
    XXXX-0000`). The token must carry at least four digits; masks are allowed.

    Run D, D2: a ROUTING number is never a candidate — one named so
    (`Routing Number 071000505`, `ABA`, `RTN`, `Transit`), or nine digits that
    pass the ABA checksum behind a cue that names no kind (`Number 0710…`).
    The generic word `Number` otherwise made `Routing Number` an account
    number and blocked the one unique correction."""
    out, seen = [], set()
    for ln in all_lines or []:
        words = [str(w.get("text", "")) for w in ln]
        for i, w in enumerate(words):
            if not _CUE.match(w.strip()):
                continue
            kind = _kind_of(words, i)
            if kind == "routing":
                continue
            j = i + 1
            while j < len(words) and j <= i + 3 and _SKIP.match(words[j].strip()):
                j += 1
            if j >= len(words):
                continue
            tok = words[j].strip().strip(".,;")
            digits = re.sub(r"\D", "", tok)
            if not (len(digits) >= 4 and _MASKED.match(tok)) or digits in seen:
                continue
            if not kind and _aba_valid(digits):
                continue                      # an unnamed 9-digit routing number
            seen.add(digits)
            out.append((digits, " ".join(words), kind))
    return out


def account_numbers(all_lines) -> list[tuple[str, str]]:
    """[(digits, line text)] — see `_candidates`."""
    return [(d, line) for d, line, _k in _candidates(all_lines)]


def slot_kind(label) -> str:
    """'account' | 'card' | '' — which kind of number a last-4 slot asks for."""
    words = set(re.sub(r"[^a-z ]+", " ", str(label or "").casefold()).split())
    kinds = {_KIND_WORD[w] for w in words if _KIND_WORD.get(w) in ("account", "card")}
    return kinds.pop() if len(kinds) == 1 else ""


def check_last4(value, all_lines, label=""):
    """(status, value, source line).

    status: "ok" (the value is the suffix of a printed account number),
    "corrected" (it was not; the page offers exactly one suffix, returned),
    "ambiguous" (the page offers several and nothing decides which), "none"
    (the page prints no account number - nothing to check against).

    Run D, D1 — the slot's LABEL chooses the candidates: an account-like label
    (`Account`, `Checking`) considers only account numbers, a card-like one
    (`Card`, `Credit`) only card numbers. When that leaves two or more
    different FULL numbers (more than four digits) the value is AMBIGUOUS
    even when it matches one of them: the model may simply have picked one,
    and nothing on the page says it picked the right one. A printed four-digit
    `ending 7421` display is the page's own suffix and does not compete."""
    nums = _candidates(all_lines)
    if not nums:
        return "none", value, ""
    want = slot_kind(label)
    pool = [n for n in nums if n[2] == want] if want else nums
    pool = pool or nums
    full = {d for d, _l, _k in pool if len(d) > 4}
    v = re.sub(r"\D", "", str(value or ""))
    for digits, line, _k in pool:
        if len(v) == 4 and digits.endswith(v):
            if len(full) > 1:
                return "ambiguous", value, ""
            return "ok", v, line
    suffixes = {}
    for digits, line, _k in pool:
        suffixes.setdefault(digits[-4:], line)
    if len(suffixes) == 1:
        (s, line), = suffixes.items()
        return "corrected", s, line
    return "ambiguous", value, ""


# ── type checks ──────────────────────────────────────────────────────────────

_MONEY_LABEL = re.compile(
    r"\b(amount|total|subtotal|balance|wages|tax|withheld|compensation|interest|"
    r"price|cost|fee|fees|charge|charges|payment|payments|deposit|deposits|"
    r"withdrawal|withdrawals|credit|debit|income|dividends|premiums|principal|"
    r"due|paid|tips|benefits|gross|net)\b", re.I)
_NOT_MONEY = re.compile(
    r"\b(date|number|no|id|code|name|address|type|status|method|terms|"
    r"description|period|percent|rate|apr|%|count|qty|quantity|units|year|"
    r"state|locality|plan|employee|employer|account)\b", re.I)
_DATE_LABEL = re.compile(r"\bdate\b", re.I)
#: Run G review (batch 1, item 10): a period's START or END is one date —
#: "Statement Period Start" — while "Statement Period" alone is a range.
_PERIOD_BOUND = re.compile(
    r"\b(?:period|statement|billing|coverage)\s+(?:start|end|begin|beginning|ending|from|to)\b"
    r"|\b(?:start|end|beginning|ending)\s+of\s+(?:the\s+)?period\b", re.I)
#: Run G review (batch 1, item 7): a slot naming a PARTY ("Payer Name",
#: "Vendor", "Employee Name") never holds a bare figure.
_PARTY_NAME = re.compile(
    r"\b(?:name|payer|payee|recipient|vendor|supplier|customer|employer|employee"
    r"|bank|company|merchant|holder)\b", re.I)
_BARE_FIGURE = re.compile(r"^[$£€]?\s*-?\(?\d[\d,]*(?:\.\d+)?\)?-?$")
#: ...unless the label also names an identifier — or a W-2 LOCALITY, whose
#: "name" is printed as a number (pitt_sample_w2: Locality Name 700102)
_ID_WORDS = re.compile(r"\b(?:id|no|number|tin|ein|ssn|code|account|acct|locality|#)\b", re.I)


def slot_type(label) -> str:
    """'money', 'date' or '' (no claim). Conservative on purpose: a label
    that names an identifier, a period, a rate or a count is not money even
    when it also says `payment` or `tax`."""
    s = str(label or "")
    if _DATE_LABEL.search(s) and not re.search(r"\b(range|period)\b", s, re.I):
        return "date"
    if _PERIOD_BOUND.search(s):
        return "date"
    if _MONEY_LABEL.search(s) and not _NOT_MONEY.search(s):
        return "money"
    return ""


def check_type(value, label):
    """(ok, normalised or None, reason). Empty values are never checked."""
    v = str(value or "").strip()
    kind = slot_type(label)
    words = re.findall(r"[a-z]+", str(label or "").casefold())
    # the label's HEAD NOUN names a party ("Payer Name", "Vendor"), not a
    # property of one ("Employer ZIP", "Employee SSN")
    if v and words and _PARTY_NAME.fullmatch(words[-1]) and _BARE_FIGURE.match(v) \
            and not _ID_WORDS.search(str(label or "")):
        return False, None, "a name field holds a figure, not a name"
    if not v or not kind:
        return True, None, ""
    if kind == "money":
        from amounts import parse_amount
        cleaned = v.replace("−", "-")
        if not re.search(r"\d", cleaned):
            return False, None, "a money field holds no amount"
        a = parse_amount(cleaned, ".")
        if a.ok:
            return True, str(a.value), ""
        m = re.search(r"-?\(?[$€£]?\s*\d[\d,]*(?:\.\d+)?\)?", cleaned)
        if m:
            b = parse_amount(m.group(0), ".")
            if b.ok:
                return True, str(b.value), ""
        return False, None, "a money field holds a value that is not an amount"
    if kind == "date":
        from dates import parse_date
        d = parse_date(v)
        if d.ok:
            return True, d.value.isoformat(), ""
        if getattr(d, "ambiguous", False):
            return True, None, ""          # day/month order: the date rules decide
        if not re.search(r"\d", v):
            return False, None, "a date field holds no date"
        return True, None, ""              # a written date the parser cannot read
    return True, None, ""
