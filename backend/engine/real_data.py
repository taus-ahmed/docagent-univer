"""Is an answer DATA? (Run F, Batch 2 failure classes.)

Grounding proves a string is printed on the page. It cannot tell a filled
value from the furniture around it, and on real documents the model's answer
was printed and still was not data:

  F1  a BLANK FORM — labels and underscores only — answered with the
      underscores, or with invented names that ground nowhere

Every rule here REFUSES or FLAGS; none of them invents a value. A refused value
is not written. When nothing the model offered survives, the document says so
once ("No data found") instead of carrying a flag per slot.
"""
from __future__ import annotations

import re

# ── F1: placeholders and blank forms ────────────────────────────────────────

_FILL_RUN = re.compile(r"_{5,}")
_ONLY_FILL = re.compile(r"^[\s_.\-–—]*$")


def is_fill_in(value) -> bool:
    """A value that is nothing but fill-in marks (`_____`, `....`)."""
    v = str(value or "")
    return bool(v.strip()) and bool(_ONLY_FILL.match(v))


def blank_form_pages(page_texts) -> bool:
    """A form with a page of labels and blanks: on some page at least five
    lines carry a run of five or more underscores, and they are at least a
    quarter of that page's printed lines (a form's terms pages do not dilute
    its form page). A filled form still prints its lines, but its values then
    ground — the caller only acts when none does."""
    for t in page_texts or []:
        lines = [ln for ln in str(t or "").splitlines() if ln.strip()]
        blanks = sum(1 for ln in lines if _FILL_RUN.search(ln))
        if blanks >= 5 and blanks * 4 >= len(lines):
            return True
    return False


def refusal(value, source, label, *, family, page_texts, specimen) -> str:
    """Why this answer is not data, or ''. `specimen` is
    `specimen_document(page_texts)`, computed once by the caller."""
    if is_fill_in(value):
        return "a fill-in blank, not a value"
    return ""


def specimen_document(page_texts) -> bool:
    return False
