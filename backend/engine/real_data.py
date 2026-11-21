"""Is an answer DATA? (Run F, Batch 2 failure classes.)

Grounding proves a string is printed on the page. It cannot tell a filled
value from the furniture around it, and on real documents the model's answer
was printed and still was not data:

  F1  a BLANK FORM — labels and underscores only — answered with the
      underscores, or with invented names that ground nowhere
  F2  an EXPLAINER page about a pay stub — `8. Net pay is total amount of
      pay check.`, `... will always balance to $0.00 ...` — answered with the
      list number or the example figure
  F3  a SPECIMEN — `SAMPLE 2024 TAX FORM`, `MR A SAMPLE`, `ADD 1` ... `ADD 5`,
      `FULL COMPANY NAME` — answered with the placeholders
  F4  a numbered DIAGRAM CALLOUT — `1 Your Account Value: $125,310.49` —
      answered with the callout number
  F5  two STATEMENTS on one page sharing a label (`Net income` in the income
      statement and again in the retained-earnings statement)

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
    if not (len(toks) > 1 and toks[0] == v + "."):
        return False
    # Run F review: "8. Overtime 12.50" is a labelled line of figures, and its
    # 8 can be real hours; an enumerator leads a line of PROSE, with no other
    # figure on it ("8. Net pay is total amount of pay check.")
    return not any(re.search(r"\d", t) for t in toks[1:])


def callout_number(value, source, label) -> bool:
    """A bare one- or two-digit number printed IMMEDIATELY BEFORE the slot's
    own label (`1 Your Account Value: $125,310.49`): a diagram callout
    numbering the label, not the label's value."""
    v = str(value or "").strip()
    if not re.fullmatch(r"\d{1,2}", v):
        return False
    toks = [t.rstrip(":.,") for t in _words(source)]
    lab = [w.rstrip(":.,") for w in _words(label) if w]
    for i, t in enumerate(toks):
        if t == v and toks[i + 1:i + 1 + len(lab)] == lab and lab:
            # Run F review: a callout numbers a label whose VALUE is printed
            # after it ("1 Your Account Value: $125,310.49"). With no figure
            # after the label, the small number before it IS the value
            # ("5 Qty Stainless bolts").
            rest = toks[i + 1 + len(lab):]
            return any(re.search(r"\d", x) for x in rest)
    return False


_FUNCTION = {"the", "a", "an", "is", "are", "will", "be", "for", "of", "to", "in",
             "your", "you", "this", "that", "and", "or", "on", "only", "always",
             "if", "it", "its", "as", "by", "with", "which", "when"}


def prose_sentence(source) -> bool:
    """The quote is a SENTENCE (ten or more words, three or more of them
    function words), not a labelled line of figures."""
    words = re.findall(r"[A-Za-z']+", str(source or ""))
    return len(words) >= 10 and sum(1 for w in words if w.casefold() in _FUNCTION) >= 3


def explanatory_page(source, page_texts) -> bool:
    """Run F review: the page the quote was read from is EXPLANATORY prose —
    at least 60 words, a fifth of them function words — rather than a pay
    advice that happens to state one figure in a sentence ("Your net pay for
    this period is $1,842.73 ..."). A quote found on no page is judged by
    the document's prose as a whole."""
    src = re.sub(r"\s+", " ", str(source or "")).strip().casefold()
    pages = [str(t or "") for t in page_texts or []]
    if not any(p.strip() for p in pages):
        return True       # no page to judge: the original F2 rule stands
    mine =[t for t in pages if src and src[:40] in re.sub(r"\s+", " ", t).casefold()]
    for t in (mine or pages):
        words = re.findall(r"[A-Za-z']+", t)
        if len(words) >= 60 and sum(1 for w in words if w.casefold() in _FUNCTION) * 5 >= len(words):
            return True
    return False


def refusal(value, source, label, *, family, page_texts, specimen) -> str:
    """Why this answer is not data, or ''. `specimen` is
    `specimen_document(page_texts)`, computed once by the caller."""
    if is_fill_in(value):
        return "a fill-in blank, not a value"
    if specimen and specimen_value(value):
        return "a specimen placeholder (this is a sample form), not real data"
    if list_number(value, source):
        return "a list number on an explanatory line, not a value"
    if callout_number(value, source, label):
        return "a callout number printed before the label, not its value"
    # A pay document's figures are printed against labels; a figure inside a
    # SENTENCE is an example in the explanatory text ("the amounts will always
    # balance to $0.00"). Scoped to pay documents: a bill or a letter states
    # real amounts in sentences ("your payment of $500.00 is due").
    if family == "payslip" and prose_sentence(source) and re.search(r"\d", str(value or "")) \
            and explanatory_page(source, page_texts):
        return "a figure quoted from explanatory text, not pay data"
    return ""


# ── F5: one label, several statements on one page ───────────────────────────

_STATEMENT_TITLE = re.compile(
    r"^\s*(?:income\s+statement|balance\s+sheet|statement\s+of\s+[a-z ,']+"
    r"|cash\s+flow\s+statement)\b", re.I)


def _line_text(ln):
    return " ".join(str(w.get("text", "")) for w in ln)


def statements_printing(label, page_lines) -> list:
    """The statement titles under which `label` begins a line, on a page that
    prints two or more statement titles. [] when the page is one statement or
    the label appears under at most one of them."""
    want = " ".join(_words(label))
    if not want:
        return []
    out = []
    for lines in page_lines or []:
        titles, current, under = 0, None, []
        for ln in lines or []:
            t = _line_text(ln)
            if _STATEMENT_TITLE.match(t):
                titles += 1
                current = t.strip()
                continue
            if current and " ".join(_words(t)).startswith(want + " ") \
                    and current not in under:
                under.append(current)
        if titles >= 2 and len(under) >= 2:
            out.extend(under)
    return out


def value_under_statement(label, value, statement, page_lines) -> bool:
    """Run F review: is `value` printed on a line beginning with `label`
    inside the statement whose title matches `statement` (the slot's column
    heading)? Titles match by their words, either containing the other."""
    want = " ".join(_words(label))
    head = " ".join(_words(statement))
    val = re.sub(r"[^\d.]", "", str(value or ""))
    if not want or not head or not val:
        return False
    for lines in page_lines or []:
        inside = False
        for ln in lines or []:
            t = _line_text(ln)
            if _STATEMENT_TITLE.match(t):
                title = " ".join(_words(t))
                inside = head in title or title in head
                continue
            if inside and " ".join(_words(t)).startswith(want + " ") and \
                    any(re.sub(r"[^\d.]", "", w) == val for w in _words(t)):
                return True
    return False


# ── F3: specimen placeholders ───────────────────────────────────────────────

_SPECIMEN_MARKERS = (
    re.compile(r"\bADD\s?[1-9]\b"),
    re.compile(r"\bFULL\s+COMPANY\s+NAME\b", re.I),
    re.compile(r"\b(?:MR|MRS|MS|DR)\.?\s+A\s+SAMPLE\b", re.I),
)
_SAMPLE_WORD = re.compile(r"\bSAMPLE\b")
_SPECIMEN_VALUE = (
    re.compile(r"^\s*ADD\s?\d{1,2}\s*$", re.I),
    re.compile(r"\bFULL\s+COMPANY\s+NAME\b", re.I),
    re.compile(r"\bSAMPLE\b", re.I),
)


def specimen_document(page_texts) -> bool:
    """A specimen prints `SAMPLE` AND at least one placeholder of its own kind
    (`ADD 1`, `FULL COMPANY NAME`, `MR A SAMPLE`). `SAMPLE` alone is a stamp
    (FlowParse's `SAMPLE DOCUMENT`), and a document carrying only that still
    holds real values — so the word alone never decides."""
    text = "\n".join(str(t or "") for t in page_texts or [])
    return bool(_SAMPLE_WORD.search(text)) and any(p.search(text) for p in _SPECIMEN_MARKERS)


def specimen_value(value) -> bool:
    return any(p.search(str(value or "")) for p in _SPECIMEN_VALUE)


# ── Run Q, Q6: placeholder text is not a value ──────────────────────────────
#
# ONE RULE FOR ALL: dummy text printed on a form or a sample is not a value.
# The answer is treated as EMPTY - no value, no flag, a note only - because
# the document shows nothing was filled there (jobs 64, 74, 75, 79, 81, 84).
# A real masked number keeps its digits (XXX-XX-1234, 40-200XXXX) and STAYS;
# a bare "X" is a tick in a box and stays.
_PLACEHOLDER_VALUE = (
    re.compile(r"^\$?\s*X{1,3}(?:,X{3})*\.(?:XX|00)$", re.I),       # XX,XXX.00
    re.compile(r"^\$?\s*X{1,3}(?:,X{3})+$", re.I),                    # X,XXX
    re.compile(r"^\$?\s*9{4,}\.9{2}$"),                               # 9999.99
    re.compile(r"^9{6,}$"),                                           # 99999999
    re.compile(r"^0{1,2}/0{1,2}/(?:0{2}|0{4})$"),                     # 00/00/00
    re.compile(r"^(?:19|20)XX$", re.I),                               # 20XX
    re.compile(r"^<[^<>]{1,80}>$"),                                   # <Company Name>
    re.compile(r"^\s*your\s+(?:city|state|zip|phone|name|address|company|e-?mail|"
               r"message|street|title|website|fax|logo)\b[\w ,.]*$", re.I),
    re.compile(r"^\s*city\s*,?\s*state\s*,?\s*(?:and\s+)?zip(?:\s*code)?\s*$", re.I),
    re.compile(r"^\s*designation\s*\(if\s+any\)\s*$", re.I),
    re.compile(r"^[X*#]{3,}(?:[-\s][X*#]{2,})*$", re.I),              # XXXX, XXX-XX-XXXX
    re.compile(r"^\s*(?:_\s*){3,}$"),                                 # _ _ _ _
)


def placeholder_value(value) -> bool:
    v = str(value or "").strip()
    if not v:
        return False
    return any(p.match(v) for p in _PLACEHOLDER_VALUE)


def printed_label_as_value(value, page_texts) -> bool:
    """The value is a LABEL the page prints - followed by its own colon -
    used as a value (job 60: Pay Group = "Business Unit", printed
    "Business Unit:"). Text only: a value with a digit is never a label."""
    v = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(v.split()) < 2 or re.search(r"\d", v):
        return False
    # EVERY place the page prints this text, it is followed by a colon - it
    # is only ever a label there. One plain occurrence and it may be a value.
    rx = re.compile(r"(?<![\w])" + re.escape(v).replace(r"\ ", r"\s+") + r"(?![\w])(\s*:)?", re.I)
    hits = [m for t in page_texts or [] for m in rx.finditer(str(t or ""))]
    return bool(hits) and all(m.group(1) for m in hits)
