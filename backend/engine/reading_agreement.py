"""When the OCR reading and the model's reading disagree, say so (Run S, 4d).

On a machine-read page (a scan, a photo) the model reads the IMAGE and the
engine grounds its answer against the OCR reader's WORDS. Two readers of one
picture disagree in a characteristic way: one character apart (`1,284.56`
against `1,234.56`, `0` against `O`). Grounding then fails and the value is
Low or unverified - but nothing says which figure the page's own reading
has, so a reviewer has to find it. This names it.

    near_reading(value, lines) -> the OCR text standing where the value
                                  should be, or None

A near reading is a run of the page's words with the same number of tokens
as the value, every token of the same shape (digit-bearing where the value's
is), and at most two character edits in all - never the value itself.
Nothing is rewritten: the flag carries both readings.
"""
from __future__ import annotations

import re
from typing import Optional


def _edits(a: str, b: str, cap: int = 3) -> int:
    """Levenshtein distance, stopped early past `cap`."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def _norm(tok: str) -> str:
    return re.sub(r"[\s$€£]", "", str(tok or "")).casefold()


def near_reading(value, lines, max_edits: int = 2) -> Optional[str]:
    toks = [t for t in str(value or "").split() if t]
    if not toks or not any(re.search(r"\d", t) for t in toks):
        return None                       # figures only: names have no near-miss rule
    want = [_norm(t) for t in toks]
    best, best_d = None, max_edits + 1
    for ln in lines or ():
        words = [str(w.get("text", "")) for w in ln if isinstance(w, dict)]
        for i in range(len(words) - len(toks) + 1):
            run = words[i:i + len(toks)]
            got = [_norm(t) for t in run]
            if got == want:
                return None               # the reading holds the value itself
            if any(bool(re.search(r"\d", a)) != bool(re.search(r"\d", b))
                   for a, b in zip(want, got) if re.search(r"\d", a)):
                continue
            d = sum(_edits(a, b) for a, b in zip(want, got))
            if 0 < d < best_d:
                best, best_d = " ".join(run), d
    return best
