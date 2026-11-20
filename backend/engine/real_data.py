"""Is an answer DATA? (Run F, Batch 2 failure classes.)

Grounding proves a string is printed on the page. It cannot tell a filled
value from the furniture around it, and on real documents the model's answer
was printed and still was not data:

  F1  a BLANK FORM — labels and underscores only — answered with the
      underscores, or with invented names that ground nowhere
  F2  an EXPLAINER page about a pay stub — `8. Net pay is total amount of
      pay check.`, `... will always balance to $0.00 ...` — answered with the
      list number or the example figure

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


# ── F2: list numbers and explanatory prose ──────────────────────────────────

def _words(s):
    return re.findall(r"[0-9a-z$£€.,%#]+", str(s or "").casefold())


def list_number(value, source) -> bool:
    """A bare one- or two-digit number that is its line's leading list
    enumerator (`8. Net pay is total amount of pay check.`), not a value."""
    v = str(value or "").strip()
    if not re.fullmatch(r"\d{1,2}", v):
        return False
    toks = _words(source)
    return len(toks) > 1 and toks[0] == v + "."


_FUNCTION = {"the", "a", "an", "is", "are", "will", "be", "for", "of", "to", "in",
             "your", "you", "this", "that", "and", "or", "on", "only", "always",
             "if", "it", "its", "as", "by", "with", "which", "when"}


def prose_sentence(source) -> bool:
    """The quote is a SENTENCE (ten or more words, three or more of them
    function words), not a labelled line of figures."""
    words = re.findall(r"[A-Za-z']+", str(source or ""))
    return len(words) >= 10 and sum(1 for w in words if w.casefold() in _FUNCTION) >= 3


def refusal(value, source, label, *, family, page_texts, specimen) -> str:
    """Why this answer is not data, or ''. `specimen` is
    `specimen_document(page_texts)`, computed once by the caller."""
    if is_fill_in(value):
        return "a fill-in blank, not a value"
    if list_number(value, source):
        return "a list number on an explanatory line, not a value"
    # A pay document's figures are printed against labels; a figure inside a
    # SENTENCE is an example in the explanatory text ("the amounts will always
    # balance to $0.00"). Scoped to pay documents: a bill or a letter states
    # real amounts in sentences ("your payment of $500.00 is due").
    if family == "payslip" and prose_sentence(source) and re.search(r"\d", str(value or "")):
        return "a figure quoted from explanatory text, not pay data"
    return ""


def specimen_document(page_texts) -> bool:
    return False
