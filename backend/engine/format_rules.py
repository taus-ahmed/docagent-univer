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


def account_numbers(all_lines) -> list[tuple[str, str]]:
    """[(digits, line text)] for each account/card number printed right after
    a cue word (`Account 7301558842`, `Card ending 7421`, `Account: XXXX-0000`).
    The token must carry at least four digits; masks are allowed."""
    out, seen = [], set()
    for ln in all_lines or []:
        words = [str(w.get("text", "")) for w in ln]
        for i, w in enumerate(words):
            if not _CUE.match(w.strip()):
                continue
            j = i + 1
            while j < len(words) and j <= i + 3 and _SKIP.match(words[j].strip()):
                j += 1
            if j >= len(words):
                continue
            tok = words[j].strip().strip(".,;")
            digits = re.sub(r"\D", "", tok)
            if len(digits) >= 4 and _MASKED.match(tok) and digits not in seen:
                seen.add(digits)
                out.append((digits, " ".join(words)))
    return out


def check_last4(value, all_lines):
    """(status, value, source line).

    status: "ok" (the value is the suffix of a printed account number),
    "corrected" (it was not; the page offers exactly one suffix, returned),
    "ambiguous" (several different suffixes and none matches), "none" (the
    page prints no account number - nothing to check against)."""
    nums = account_numbers(all_lines)
    if not nums:
        return "none", value, ""
    v = re.sub(r"\D", "", str(value or ""))
    for digits, line in nums:
        if len(v) == 4 and digits.endswith(v):
            return "ok", v, line
    suffixes = {}
    for digits, line in nums:
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


def slot_type(label) -> str:
    """'money', 'date' or '' (no claim). Conservative on purpose: a label
    that names an identifier, a period, a rate or a count is not money even
    when it also says `payment` or `tax`."""
    s = str(label or "")
    if _DATE_LABEL.search(s) and not re.search(r"\b(range|period)\b", s, re.I):
        return "date"
    if _MONEY_LABEL.search(s) and not _NOT_MONEY.search(s):
        return "money"
    return ""


def check_type(value, label):
    """(ok, normalised or None, reason). Empty values are never checked."""
    v = str(value or "").strip()
    kind = slot_type(label)
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
