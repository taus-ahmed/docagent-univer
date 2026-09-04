"""
DocAgent — Text Layer (positional evidence)
===========================================

Until now the pipeline read a PDF with `page.extract_text()` and kept a flat
string per page. Everything downstream — the prompt, the grounding check, the
confidence vocabulary — saw text with no geometry in it at all. Two whole
classes of defect follow directly from that, and neither is visible to a
reader of the output:

WRAPPED VALUES. A PDF that renders a number inside a narrow table cell wraps
it like any other text, so the page really does print

        Box 2 - Federal income tax   $1,268.7
        withheld                            5

`extract_text` returns those as two lines, and `extract_words` agrees — the
split is in the FILE, not in the reader. The model is handed `$1,268.7`,
answers `5` for the next slot, and both halves ground perfectly, because both
halves are genuinely printed on the page. On FORM-W2-2023 this produced 11
wrong values out of 12, every one of them marked HIGH, while the single
correct value was the only one marked LOW — the confidence signal exactly
inverted. The fragments are recoverable because they share a right edge with
their parent to within a rounding error and sit on the next line down.

PLACEMENT. Grounding asks "does this value appear in the document". It cannot
ask "does this value belong in THIS column", because a flattened line carries
no column information: a Debit moved into the Credit column is quoted from the
same source line and passes every check. In a multi-column financial table
placement is most of the meaning — which column an amount sits in decides who
owes it. Column bands read off the document's own heading line answer that
question directly.

Both come from one signal, which pdfplumber has had all along and nothing
asked it for: `extract_words()`, with x0/x1/top per word. It costs ~70 ms on a
typical page.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
-----------------------------------------
It does not rebuild the text of pages it did not have to touch. Rebuilding
word lists into text is NOT byte-identical to `extract_text()` — measured
across the 60-document corpus, 30 pages of 77 differ in whitespace — and the
document text is part of the prompt, so rewriting every page would invalidate
the recorded LLM cache wholesale and change what the model is asked on
documents that had nothing wrong with them. A page with no repair is returned
exactly as `extract_text` produced it. Only the 4 pages in that corpus which
genuinely need repair are rebuilt.
"""

import re
from collections import Counter

# Currency marks a number may carry. Stripped only to inspect the digits; the
# value keeps its notation everywhere else.
_CURRENCY = "$£€₹¥"

#: Two words are on the same line if their tops differ by less than this.
LINE_TOL = 3.0

#: A continuation fragment must share its parent's right edge this closely.
#: Measured on FORM-W2-2023, every genuine fragment matched to 0.0pt; the
#: tolerance is for rounding, not for guessing.
EDGE_TOL = 1.0

#: How far apart a value's right edge may sit from its column's before the
#: placement is called wrong. A right-aligned money column holds to well under
#: a point; a point of slack costs nothing and avoids arguing with rounding.
COLUMN_TOL = 2.0


def _bare(token: str) -> str:
    return str(token or "").lstrip(_CURRENCY).strip()


# ── wrapped values ───────────────────────────────────────────────────────────

def _shortfall(parent: str):
    """(kind, digits_missing) if `parent` is an INCOMPLETE number, else None.

    The whole safety of the repair rests here. A complete number is never
    repaired, so two right-aligned figures stacked in the same column — a
    Balance of 199,320.55 above one of 180,870.55, sharing a right edge to the
    point — cannot be fused into each other. Only these three shapes are
    incomplete, and each says exactly how many digits it is missing:

        "14,210."   a bare decimal point, missing its 2 cents
        "1,268.7"   one decimal digit, missing the second
        "144,58"    a final comma group of 1-2 digits, missing the rest

    A bare integer is never incomplete: without a comma or a decimal point
    there is nothing in the token that says it was cut short, so "18" followed
    by "000" is left alone. That is deliberately conservative — a false repair
    invents a number, which is the worst thing this codebase can do.
    """
    b = _bare(parent)
    if re.fullmatch(r"[\d,]+\.", b):
        return ("decimal", 2)
    if re.fullmatch(r"[\d,]+\.\d", b):
        return ("decimal", 1)
    m = re.fullmatch(r"\d{1,3}(?:,\d{3})*,(\d{1,2})", b)
    if m:
        return ("group", 3 - len(m.group(1)))
    return None


def _completes(kind: str, missing: int, cont: str) -> bool:
    """Does `cont` supply exactly the digits `parent` was missing?

    Exactly — not "at least". A fragment that is the wrong length is not this
    value's tail, and fusing it would produce a plausible wrong number.
    """
    c = str(cont or "").strip()
    if kind == "decimal":
        return bool(re.fullmatch(rf"\d{{{missing}}}", c))
    # A cut comma group may be completed by its digits alone ("144,58" + "3")
    # or by its digits and the cents that followed them ("144,58" + "3.00").
    return bool(re.fullmatch(rf"\d{{{missing}}}(?:\.\d{{2}})?", c))


def group_lines(words, tol: float = LINE_TOL):
    """Words grouped into visual lines, each sorted left to right.

    Clustered on the GAP between successive tops, not by bucketing `top / tol`.
    Bucketing splits any line that happens to straddle a bucket edge — two
    words 0.7pt apart landing either side of a boundary become two lines — and
    on FORM-W2-2023 that broke one printed line into two, which put a value's
    continuation fragment two lines below its parent instead of one and lost
    four of the twelve repairs.
    """
    out, cur, top = [], [], None
    for w in sorted(words, key=lambda x: (float(x["top"]), float(x["x0"]))):
        t = float(w["top"])
        if top is None or abs(t - top) <= tol:
            cur.append(w)
            top = t if top is None else top
        else:
            out.append(sorted(cur, key=lambda x: float(x["x0"])))
            cur, top = [w], t
    if cur:
        out.append(sorted(cur, key=lambda x: float(x["x0"])))
    return out


def repair_wrapped(words):
    """(repaired_lines, repairs) — fuse values the PDF wrapped inside a cell.

    A fragment qualifies only if it is on the IMMEDIATELY following line, sits
    within its parent's horizontal span, shares the parent's right edge to
    within `EDGE_TOL`, and completes the parent exactly. Each fragment is
    consumed once.

    `repairs` is [(parent, fragment, fused)] so the caller can report what it
    changed — a silent rewrite of a number is not something this pipeline is
    allowed to do.
    """
    lines = group_lines(words)
    repairs = []
    fused_ids, fragment_ids = set(), set()

    for i, line in enumerate(lines[:-1]):
        for w in line:
            if id(w) in fused_ids or id(w) in fragment_ids:
                continue
            need = _shortfall(w["text"])
            if not need:
                continue
            for c in lines[i + 1]:
                if id(c) in fragment_ids or id(c) in fused_ids:
                    continue
                # inside the parent's span, flush with its right edge
                if abs(float(c["x1"]) - float(w["x1"])) > EDGE_TOL:
                    continue
                if float(c["x0"]) < float(w["x0"]) - 0.5:
                    continue
                if not _completes(need[0], need[1], c["text"]):
                    continue
                fused = str(w["text"]) + str(c["text"]).strip()
                repairs.append((str(w["text"]), str(c["text"]), fused))
                w["text"] = fused
                w["x0"] = min(float(w["x0"]), float(c["x0"]))
                fused_ids.add(id(w))
                fragment_ids.add(id(c))
                break

    if fragment_ids:
        # The fragment is now part of its parent; leaving it on its own line
        # would put a stray "5" in the document text for the model to answer
        # some other slot with.
        lines = [[w for w in ln if id(w) not in fragment_ids] for ln in lines]
    return lines, repairs


def text_from_lines(lines) -> str:
    return "\n".join(" ".join(str(w["text"]) for w in ln) for ln in lines if ln)


def read_page(page):
    """(text, lines, repairs) for one pdfplumber page.

    `text` is `extract_text()` VERBATIM when the page needed no repair — see
    the module docstring for why that matters — and rebuilt from the repaired
    words when it did.
    """
    raw = page.extract_text() or ""
    try:
        words = page.extract_words()
    except Exception:
        return raw, [], []
    lines, repairs = repair_wrapped(words)
    if not repairs:
        return raw, lines, []
    return text_from_lines(lines), lines, repairs


# ── column bands and placement ───────────────────────────────────────────────

def _flat(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().casefold()


def find_line(lines, source):
    """The document line a row's quoted `source` was read from, or None.

    Matched on flattened text so spacing and case cannot decide it. A source
    spanning more than one line matches the first line it starts on, which is
    the line the row's values sit on.
    """
    src = _flat(source)
    if not src:
        return None
    best = None
    for ln in lines:
        t = _flat(" ".join(str(w["text"]) for w in ln))
        if not t:
            continue
        if src == t or src in t:
            return ln
        if t in src and (best is None or len(t) > len(_flat(
                " ".join(str(w["text"]) for w in best)))):
            best = ln
    return best


def column_bands(lines, headers):
    """{header: (x0, x1)} for the headers this document actually prints.

    Read off the document's OWN heading line, not the template's. A template
    column whose heading the document does not print gets no band and is not
    placement-checked — the check is opportunistic on purpose. Claiming a
    placement is wrong on a guessed band would flag correct values, which is
    worse than not checking.
    """
    want = {_flat(h): h for h in headers if _flat(h)}
    if not want:
        return {}
    best, best_hits = {}, 0
    for ln in lines:
        hits = {}
        for w in ln:
            key = _flat(w["text"])
            if key in want:
                hits.setdefault(want[key], (float(w["x0"]), float(w["x1"])))
        # a heading line for a multi-column band names at least two of them
        if len(hits) > best_hits and len(hits) >= 2:
            best, best_hits = hits, len(hits)
    return best


def locate(value, line, after_x=None):
    """(x0, x1) of `value` within `line`, or None.

    Numbers are matched as a single word. A multi-word value is matched as a
    run of consecutive words. `after_x` restricts the search to words starting
    at or after that x, which is how a value appearing twice on one line is
    assigned to the right occurrence.
    """
    val = _flat(value)
    if not val or not line:
        return None
    ws = [w for w in line
          if after_x is None or float(w["x0"]) >= float(after_x) - 0.5]
    for n in range(1, min(len(ws), 12) + 1):
        for i in range(0, len(ws) - n + 1):
            run = ws[i:i + n]
            if _flat(" ".join(str(w["text"]) for w in run)) == val:
                return (float(run[0]["x0"]), float(run[-1]["x1"]))
    # a value printed as part of a larger token (rare, but a bare number
    # inside "Qty:40" should still be locatable)
    for w in ws:
        if val and val in _flat(w["text"]):
            return (float(w["x0"]), float(w["x1"]))
    return None


def check_placement(row, columns, line, bands):
    """[(key, reason)] for every cell whose value sits in the wrong column.

    A value is in the right place when its right edge lines up with its
    column's — money columns are right-aligned, and hold to well under a point
    — or, failing that, when its horizontal span overlaps the column's band at
    all. Left-aligned text columns satisfy the second test and not the first,
    which is why both are here and why overlap alone is not enough for a
    number: two money columns never overlap, so a swapped amount fails.

    A cell is only judged when its column has a band AND its value can be
    located on the line. Anything else returns no verdict rather than a
    guess.
    """
    out = []
    if not line or not bands:
        return out
    cursor = None
    for col in columns:
        key = col.get("key") or col.get("header")
        value = row.get(key, "")
        if str(value or "").strip() == "":
            continue
        span = locate(value, line, after_x=cursor)
        if span is None:
            span = locate(value, line)
        if span is None:
            continue
        cursor = span[0]
        band = bands.get(col.get("header")) or bands.get(key)
        if not band:
            continue
        if abs(span[1] - band[1]) <= COLUMN_TOL:
            continue                                   # flush right: correct
        if span[0] < band[1] and band[0] < span[1]:
            continue                                   # overlaps its column
        near = _nearest(span, bands)
        why = (f"value sits under the {near!r} column, not {col.get('header')!r}"
               if near and near != col.get("header")
               else f"value does not sit under the {col.get('header')!r} column")
        out.append((key, why))
    return out


def _nearest(span, bands):
    if not bands:
        return None
    return min(bands.items(), key=lambda kv: abs(span[1] - kv[1][1]))[0]
