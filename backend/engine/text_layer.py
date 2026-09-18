#: A column gutter is derived from the PAGE, not fixed and not per line.
#:
#: A fixed threshold cannot work: INV-2024-0031's two note columns sit 122pt
#: apart, while the Closing Disclosure's five-party contact matrix packs its
#: columns 10-26pt apart. A constant of 24pt read that matrix as one
#: continuous line, so an email in the third column ran on into the fourth
#: column's and matched nothing.
#:
#: Per LINE does not work either, and the way it fails is instructive: on a
#: line that is nothing but one-word cells — a row of five email addresses —
#: EVERY gap is a gutter, so the line's median gap is itself a gutter and the
#: threshold lands above all of them.
#:
#: The page is the right scale. The ordinary gap between two words of the same
#: phrase is a property of the font and is remarkably stable (1.5-2.6pt on both
#: documents), and most gaps on a page are of that kind, so the page's median
#: gap measures word spacing while the line's may not.
GUTTER_MULTIPLE = 4.0

#: Never call a gap this small a gutter, however tight the spacing.
GUTTER_FLOOR = 6.0

#: Below this many gaps there is no reliable median; fall back.
_MIN_GAPS_FOR_MEDIAN = 8

#: The fallback, and the value used before this was derived.
GUTTER = 24.0


def gutter_for_page(lines):
    """The gap width that separates COLUMNS on this page."""
    gaps = []
    for line in lines:
        xs = sorted(line, key=lambda w: float(w["x0"]))
        gaps += [float(b["x0"]) - float(a["x1"]) for a, b in zip(xs, xs[1:])]
    gaps = sorted(g for g in gaps if g >= 0)
    if len(gaps) < _MIN_GAPS_FOR_MEDIAN:
        return GUTTER
    mid = len(gaps) // 2
    median = gaps[mid] if len(gaps) % 2 else (gaps[mid - 1] + gaps[mid]) / 2.0
    return max(GUTTER_FLOOR, median * GUTTER_MULTIPLE)


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




# ── text that keeps its columns (I5, mode 1) ───────────────────────
#
# `text_from_lines` joins every word of a line with one space, so two blocks
# printed SIDE BY SIDE arrive as one sentence. On INV-2024-0047 that turns
#
#     Payment Instructions            Notes
#     Wire: First National Bank ...   Balance due March 4, 2024. Late ...
#
# into two flat lines, and shape inference — which is asked to prefix a block's
# heading onto each field under it — then has to guess which of the two
# headings owns "Balance due". It produced `Notes Balance Due` (right, here)
# and the round-2 report records the same mechanism producing `Oncor Customer
# Charge` from a sidebar callout (wrong, there). The model is not choosing
# badly; it is choosing without the evidence, because the columns were thrown
# away before it saw the page.
#
# This is deliberately NOT a change to the document text. `doc_text_pages` is
# what `verify_span` grounds against and what slot extraction is prompted with,
# and rewriting it would change every span check and every cached answer in the
# project. This builds a SECOND rendering, for inference only.
#
# The gutter is the page's own (`gutter_for_page`), never a constant: a fixed
# 24pt threshold reading a five-party contact matrix as one line is already
# recorded as a failure in this file. A line with no gutter comes back
# byte-identical to `text_from_lines`, so a document with no side-by-side
# blocks is asked exactly what it was asked before.

#: What a column break looks like in the inference prompt. Visible, because an
#: invisible one (a run of spaces) is what the model already fails to notice.
COLUMN_MARK = "   |   "


def split_at_gutters(line, gutter):
    """[[word, ...], ...] — one segment per column this line spans."""
    xs = sorted(line or (), key=lambda w: float(w["x0"]))
    if not xs:
        return []
    segs, cur = [], [xs[0]]
    for a, b in zip(xs, xs[1:]):
        if float(b["x0"]) - float(a["x1"]) >= gutter:
            segs.append(cur)
            cur = [b]
        else:
            cur.append(b)
    segs.append(cur)
    return segs


#: A segment that is only digits and punctuation is a VALUE, not a block.
_NOT_PROSE = re.compile(r"^[\s\d.,:;$£€¥%()+\-/*#]*$")


def _is_prose(seg) -> bool:
    t = " ".join(str(w["text"]) for w in seg)
    return bool(re.search(r"[A-Za-z]{2}", t)) and not _NOT_PROSE.match(t)


def column_text(lines, prose_only=True) -> str:
    """One page's text with its BLOCK breaks kept, for inference only.

    Not every gutter is a block boundary, and marking all of them was measured
    and rejected: it marked 63% of the corpus's lines, including the gap
    between a label and its own amount, and the no-template harness fell
    96.7% -> 95.2% with 10 misfilings where there had been none. STMT-2024-01
    is the clearest instance — marking `Opening Balance | $184,320.55` as two
    columns made inference model the summary box as a TABLE, and three fields
    gold expects went missing.

    A break is a block boundary when the text on BOTH sides of it is prose. A
    label beside its amount is one thing in two columns; two runs of words side
    by side are two blocks. That drops the marked share to 34% and leaves the
    label/value case exactly as it was.
    """
    if not lines:
        return ""
    gutter = gutter_for_page(lines)
    out = []
    for ln in lines:
        if not ln:
            continue
        segs = split_at_gutters(ln, gutter)
        if prose_only and sum(1 for sg in segs if _is_prose(sg)) < 2:
            segs = [[w for sg in segs for w in sg]]
        out.append(COLUMN_MARK.join(
            " ".join(str(w["text"]) for w in seg) for seg in segs))
    return "\n".join(out)


def column_text_pages(page_lines, fallback_pages=()):
    """(texts, pages_carrying_a_column_break).

    A page with no geometry — an image, a hand-built fixture — falls back to
    the flat text it already had, so a caller never loses a page by asking for
    columns.
    """
    fallback = list(fallback_pages or [])
    texts, marked = [], 0
    for i, lines in enumerate(page_lines or []):
        if not lines:
            texts.append(str(fallback[i]) if i < len(fallback) else "")
            continue
        t = column_text(lines)
        if COLUMN_MARK in t:
            marked += 1
        texts.append(t)
    if not texts:
        return [str(t or "") for t in fallback], 0
    return texts, marked


# ── multi-line values ───────────────────────────────────────────────────────

#: A column gutter is derived PER LINE, not fixed. A single threshold cannot
#: work: INV-2024-0031's two note columns are 122pt apart, while the Closing
#: Disclosure's five-party contact matrix packs its columns 10-26pt apart. A
#: constant of 24pt read that matrix as one continuous line, so an email in
#: the third column ran on into the fourth column's and matched nothing.
#:
#: Within a line the ordinary word gap is remarkably stable (1.5-2.6pt on both
#: documents) and a gutter is a large multiple of it, so the line's own median
#: gap is the scale to measure against.
GUTTER_MULTIPLE = 4.0

#: Never call a gap this small a gutter, however tight the line's spacing.
GUTTER_FLOOR = 6.0

#: A line with fewer gaps than this has no reliable median; fall back.
_MIN_GAPS_FOR_MEDIAN = 3

#: The fallback, and the value used before this was derived per line.
GUTTER = 24.0


def gutter_for(line):
    """The gap width that separates COLUMNS on this particular line."""
    xs = sorted(line, key=lambda w: float(w["x0"]))
    gaps = [float(b["x0"]) - float(a["x1"]) for a, b in zip(xs, xs[1:])]
    gaps = [g for g in gaps if g >= 0]
    if len(gaps) < _MIN_GAPS_FOR_MEDIAN:
        return GUTTER
    gaps.sort()
    mid = len(gaps) // 2
    median = gaps[mid] if len(gaps) % 2 else (gaps[mid - 1] + gaps[mid]) / 2.0
    return max(GUTTER_FLOOR, median * GUTTER_MULTIPLE)

#: How far a value may run. A field value is a phrase, not a page.
MAX_VALUE_WORDS = 60


#: Characters that end a fragment mid-token, so a line break after one is a
#: WRAP rather than a space. `joesmith@` + `ficusbank.com` is one address.
_MID_TOKEN_END = "@/-\\_"


def _joiner(prev_word, next_word, same_line):
    """The character between two words of one value: " " or nothing.

    Joining everything with a space is right within a line and wrong across
    one. A PDF wraps `joesmith@ficusbank.com` into `joesmith@` and
    `ficusbank.com`, and gluing those with a space produces
    `sarah@ epsilontitle.com` — an address that looks perfectly ordinary in a
    spreadsheet and bounces when anyone uses it. That is exactly the failure
    this module exists to remove, reintroduced by its own repair.

    Within a line the PDF really did put whitespace there, so a space is
    always right. Across a line break it depends on the characters at the
    seam, and only these say "mid-token":

        the fragment ends with @ / - \ _        joesmith@ + ficusbank.com
        the next fragment starts with @          joesmith + @ficusbank.com
        it ends with "." and the next is lower   ficusbank. + com

    A "." before a capital is a sentence or an abbreviation and keeps its
    space, so `123 Commerce Pl.` + `Somecity, ST` does not become
    `Pl.Somecity`. Everything else is ordinary wrapped prose:
    `Omega Real Estate` + `Broker Inc.` keeps its space.
    """
    if same_line:
        return " "
    prev, nxt = str(prev_word or ""), str(next_word or "")
    p, n = prev[-1:], nxt[:1]
    if p and p in _MID_TOKEN_END:
        return ""
    if n == "@":
        return ""
    if p == "." and n.islower():
        return ""
    return " "


def _walk(flat, target, cross_gutters, gutter):
    """(joined text, crossed) for the first run of words spelling `target`.

    Run TWICE by the caller. The first pass stays inside the value's own
    column: a same-line word beyond a gutter belongs to a different column and
    is stepped over, which is what lets an email in the third column of a
    contact matrix find its own continuation on the next line rather than
    swallowing the fourth column's address.

    The second pass allows the crossing, and is how a value that really did
    merge two side-by-side blocks is still detected and reported. Trying the
    in-column reading first means the merge flag now means what it says
    instead of firing on any multi-column page.
    """
    for i in range(len(flat)):
        acc, crossed, taken = "", False, []
        lo = hi = None
        prev_line, prev_x1 = None, None
        for j in range(i, min(i + MAX_VALUE_WORDS * 3, len(flat))):
            w, li = flat[j]
            x0, x1 = float(w["x0"]), float(w["x1"])
            if lo is not None and li != prev_line:
                # A NEW LINE continues this value only inside its own column
                # block. Reading order interleaves side-by-side columns, so a
                # value's own continuation is never simply the next word.
                if x1 < lo - 2.0 or x0 > hi + 2.0:
                    continue
            gutter_here = False
            if lo is not None and li == prev_line and prev_x1 is not None:
                gutter_here = (x0 - prev_x1) > gutter
                if gutter_here and not cross_gutters:
                    continue
            if taken:
                acc_sep = _joiner(taken[-1]["text"], w["text"],
                                  same_line=(li == prev_line))
            else:
                acc_sep = ""
            acc += re.sub(r"\s+", "", str(w["text"])).casefold()
            taken.append(w)
            crossed = crossed or gutter_here
            lo = x0 if lo is None else min(lo, x0)
            hi = x1 if hi is None else max(hi, x1)
            prev_line, prev_x1 = li, x1
            if len(acc) > len(target):
                break
            if acc == target:
                return _join(taken, flat), crossed
    return None


def _join(taken, flat):
    """The words as the document would read them, joined by one rule."""
    line_of = {id(w): li for w, li in flat}
    out = str(taken[0]["text"])
    for prev, w in zip(taken, taken[1:]):
        out += _joiner(prev["text"], w["text"],
                       same_line=line_of.get(id(prev)) == line_of.get(id(w)))
        out += str(w["text"])
    return out


def canonical_value(value, lines):
    """(the document's own text for `value`, crossed_a_gutter), or None.

    THE RULE: a field's value is the document's own words, in reading order,
    joined the way the page joins them — a space within a line, and across a
    line break a space unless the seam is mid-token.

    The join was previously whatever the model returned, and it returned three
    different things for one field on one document — `INV-2024-0031`'s Notes
    came back truncated at the first line, joined with a literal newline, and
    joined with a space, across cached runs of the same document. Adjacent
    fields in one run disagreed too. There is no reason for that to be a model
    decision: the words are at known positions, so the join can be re-derived.

    Nothing is added and nothing is dropped — the run of words has to spell
    exactly what the model claimed, ignoring whitespace. A value that matches
    no run of words is returned unchanged rather than guessed at, which is what
    happens to anything the model normalised or derived (a MICR field, a
    reformatted number).

    `crossed_a_gutter` says the run had to jump a column boundary to spell the
    value, which means two side-by-side blocks were merged into one answer.
    The in-column reading is tried first, so this now fires only when there is
    no in-column reading at all.
    """
    target = re.sub(r"\s+", "", str(value or "")).casefold()
    if len(target) < 4:
        return None
    flat = [(w, li) for li, ln in enumerate(lines) for w in ln]
    if not flat:
        return None
    gutter = gutter_for_page(lines)
    return _walk(flat, target, False, gutter) or \
        _walk(flat, target, True, gutter)


# ── two texts printed over one another ──────────────────────────────────────

# A fraction of the NARROWER character's width. Adjacent characters in ordinary
# text are contiguous or gapped; kerning can make a pair overlap slightly, so
# the threshold is half a character rather than any overlap at all.
OVERPRINT_FRAC = 0.5
# An ISOLATED overlap is kerning — "'s" set tight in a serif face. A RUN of
# them is two texts printed over one another, because the second text's
# characters interleave with the first's all the way along.
OVERPRINT_MIN_RUN = 3
# Two characters printed over one another sit on the SAME BASELINE, give or
# take the two texts' own offset — SampleBill's two account numbers are 0.267pt
# apart. Two characters a whole printed line apart are not over one another
# however the char clustering grouped them; the audit letters' spurious span was
# tops 81.556 and 83.656. 1.0pt is comfortably above the first and below the
# second, and below the tightest line spacing in the corpus (2.4pt).
OVERPRINT_TOP_TOL = 1.0


def overprinted_spans(page):
    """[(x0, x1, top)] for every region where two texts are printed over each other.

    THE DEFECT. `SampleBill.pdf` page 4 prints its account number twice, in two
    font sizes, at the same place:

        size 11.00, top 100.183   0 0 0 0 1 2 3 4 5 6   ->  0000123456
        size 10.21, top  99.916   0 0 0 0 1 5 8 6 5 9   ->  0000158659

    The two runs overlap in x by about 2.7pt per character. Every reader that
    orders characters left to right — pdfplumber's `extract_text` AND its
    `extract_words` — interleaves them into `00000000112538645596`, and
    `extract_words` returns that as ONE word. So the contamination is in the
    word box itself, below everything built on top of it: the flattened text,
    `canonical_value`'s re-derivation, and `verify_span`'s grounding all agree
    the string is on the page, because by the time they look, it is.

    That is why this is measured on CHARACTERS. It is the only level at which
    the two texts are still separable, and the geometry says plainly what
    happened even though neither string can be recovered from it.

    Measured over all 70 PDFs in the repo: 9 documents carry overprinted
    regions and every one of them is genuine — including five gold-corpus
    audit letters whose letterhead has been interleaving
    (`NSou:i tAe U2D20-200`) since the day they were committed, unnoticed
    because no slot ever asked for that line.

    NOTHING IS REPAIRED. Which of the two texts was wanted is not recoverable
    from the page — both are printed, in full, in the same place. A caller is
    told the region is contaminated and keeps the value; the alternative is
    inventing one of the two readings.
    """
    try:
        raw_chars = page.chars
    except Exception:
        return []
    return overprinted_spans_from_chars(raw_chars)


def overprinted_spans_from_chars(raw_chars):
    """`overprinted_spans` against characters already obtained.

    Split out for the reader seam: `read_page` asks its source for characters
    and passes them here, while `overprinted_spans(page)` above keeps taking a
    pdfplumber page so its five existing call sites need no edit. The detection
    itself is unchanged and lives here.
    """
    try:
        chars = [c for c in raw_chars if str(c.get("text", "")).strip()]
    except Exception:
        return []
    if not chars:
        return []
    out = []
    for ln in group_lines(chars):
        # ⚠ WITHIN ONE FONT SIZE (I10). Two characters that overlap but are set
        # at DIFFERENT SIZES are two separable texts, not an interleaving: the
        # size-aware grouping in `read_page` now pulls them apart and recovers
        # both. On this page's own example it recovers `0000123456` AND
        # `0000158659`, so the docstring above — "which of the two was wanted is
        # not recoverable" — is true of the size-BLIND reading and false now.
        #
        # Comparing across sizes made the detector fire on the repaired values:
        # 910 words on `round2/HTR-043235.pdf` and 13 on `SampleBill.pdf`,
        # including both correct account numbers, every one of them demoted to
        # `low` and flagged. A detector that condemns the value the fix just
        # rescued is worse than no detector.
        #
        # What survives is the case that is still genuinely unrecoverable: two
        # texts overlapping AT THE SAME SIZE, which nothing separates.
        by_size = {}
        for c in ln:
            try:
                by_size.setdefault(round(float(c.get("size", 0)), 1),
                                   []).append(c)
            except (TypeError, ValueError):
                continue
        for run in by_size.values():
            hits = []
            for a, b in zip(run, run[1:]):
                try:
                    narrow = min(float(a["x1"]) - float(a["x0"]),
                                 float(b["x1"]) - float(b["x0"]))
                    if narrow <= 0:
                        continue
                    # ...AND IN THE SAME PLACE. `group_lines` clusters on
                    # LINE_TOL=3.0, so on a densely set page two characters from
                    # DIFFERENT printed lines land in one cluster, and once the
                    # cluster is sorted by x they sit next to each other and
                    # their boxes trivially overlap. That is two lines, not two
                    # texts over one another. The five audit letters are the
                    # case: tops 81.556 and 83.656, both at 8.0pt, which
                    # condemned the very words the size-aware reading had just
                    # recovered — `AUD-2024-001`, `Suite`, `New`, `York,`.
                    if abs(float(a["top"]) - float(b["top"])) > OVERPRINT_TOP_TOL:
                        continue
                    if float(a["x1"]) - float(b["x0"]) > OVERPRINT_FRAC * narrow:
                        hits.append((a, b))
                except (KeyError, TypeError, ValueError):
                    continue
            if len(hits) >= OVERPRINT_MIN_RUN:
                out.append((min(float(a["x0"]) for a, _ in hits),
                            max(float(b["x1"]) for _, b in hits),
                            float(run[0]["top"])))
    return out


def mark_overprints(lines, spans):
    """Tag every word sitting in an overprinted region. Returns how many."""
    if not spans:
        return 0
    n = 0
    for ln in lines:
        for w in ln:
            try:
                wx0, wx1, wt = float(w["x0"]), float(w["x1"]), float(w["top"])
            except (KeyError, TypeError, ValueError):
                continue
            for x0, x1, top in spans:
                if wx0 < x1 and x0 < wx1 and abs(wt - top) <= LINE_TOL:
                    w["overprinted"] = True
                    n += 1
                    break
    return n


def matches_loosely(value, lines):
    """True when some run of words spells `value` once punctuation is ignored.

    `canonical_value` demands an exact spelling, which is right for the join it
    re-derives and too strict for deciding whether the page witnesses a value
    at all. A number the model renotated (`$7,750.00` against a printed
    `7,750.00`) is still read off the page; a string assembled from words that
    are not adjacent is not, and that is the distinction this draws.
    """
    target = re.sub(r"[^0-9a-z]+", "", str(value or "").casefold())
    if len(target) < 4:
        return True                      # too short to conclude anything
    for ln in lines:
        toks = [re.sub(r"[^0-9a-z]+", "", str(w.get("text", "")).casefold())
                for w in ln]
        for i in range(len(toks)):
            if not toks[i]:
                continue
            run = ""
            for j in range(i, min(i + MAX_VALUE_WORDS, len(toks))):
                run += toks[j]
                if run == target:
                    return True
                if len(run) > len(target):
                    break
    return False


def unprinted_headers(lines, headers):
    """The template headings this document does not print anywhere.

    `column_bands` answers a narrower question — where on the page a heading
    sits — and returns nothing at all when it cannot find two of them on one
    line. That "nothing" was read downstream as "no verdict", which is right
    for a placement check and wrong as a report to the user: a template whose
    column means `Variance` against a document that never says `Variance` is
    not an unchecked template, it is a template describing something the
    document does not contain, and its columns can only have been filled
    positionally.

    A heading counts as printed when EVERY significant word of it appears
    somewhere on the page. Neither a per-line match nor a reading-order match
    survives contact with a real column heading: the CFPB Closing Disclosure
    sets `Paid by Others` stacked in a narrow column, and prints `Paid by` on
    one line with `Others` at the far END of the next, after `Before Closing`.
    Both stricter rules called it missing.

    Erring loose is deliberate. This warning exists to be read, and one that
    fires on a heading the document plainly does print is one the user learns
    to scroll past — the same reason rule G was rejected from the save gate.
    Words shorter than three characters (`of`, `by`, `at`) carry no evidence
    either way and are not required.
    """
    hay = " ".join(re.sub(r"[^0-9a-z]+", " ", str(w.get("text", "")).casefold())
                   for ln in lines for w in ln)
    out = []
    for h in dict.fromkeys(headers):
        words = [w for w in re.split(r"[^0-9a-z]+", str(h or "").casefold())
                 if len(w) >= 3]
        if words and not all(w in hay for w in words):
            out.append(h)
    return out


def overprinted_value(value, lines):
    """True when `value` is spelled by a word carrying overprinted characters.

    Matched both ways round — the word may be the whole value, or the value
    may be one word of a longer overprinted run.
    """
    flat = _flat(value).replace(" ", "")
    if len(flat) < 4:
        return False
    for ln in lines:
        for w in ln:
            if not w.get("overprinted"):
                continue
            t = _flat(w.get("text", "")).replace(" ", "")
            if len(t) >= 4 and (t in flat or flat in t):
                return True
    return False


# ── selection state that is not in the text at all ──────────────────────────

def acroform_widgets(path):
    """{page index: [{x0, x1, top, bottom, on}]} for every checkbox widget.

    A real fillable form's checkbox is a WIDGET ANNOTATION, not a printed
    character. It carries no text, so the text layer shows every option and no
    marker, and the selection state — which is the entire content of the field
    — is invisible to anything reading text. Measured on a fixture modelling
    FORM CT-3: four option fields, all four filled from thin air at HIGH
    confidence with `needs_review` false, and "Services" answered where the
    form says "Wholesale trade". Every option string is printed on the page, so
    grounding confirms whichever one was picked.

    The state is in the file the whole time, in `/AS` (the widget's appearance
    state) falling back to `/V` (the field value). Anything that is not `/Off`
    is on.

    Rects are PDF user space, origin bottom-left; pdfplumber measures `top`
    from the top of the page, so y is flipped here and nowhere else.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        return {}
    try:
        reader = PdfReader(str(path))
    except Exception:
        return {}

    out = {}
    for i, page in enumerate(reader.pages):
        try:
            height = float(page.mediabox.height)
        except Exception:
            continue
        items = []
        for ref in (page.get("/Annots") or []):
            try:
                obj = ref.get_object()
                if str(obj.get("/Subtype")) != "/Widget":
                    continue
                ft = obj.get("/FT")
                if ft is None and obj.get("/Parent") is not None:
                    ft = obj.get("/Parent").get_object().get("/FT")
                if str(ft) != "/Btn":
                    continue
                rect = [float(v) for v in obj.get("/Rect")]
                state = obj.get("/AS")
                if state is None:
                    state = obj.get("/V")
            except Exception:
                continue
            x0, x1 = min(rect[0], rect[2]), max(rect[0], rect[2])
            y0, y1 = min(rect[1], rect[3]), max(rect[1], rect[3])
            items.append({"x0": x0, "x1": x1,
                          "top": height - y1, "bottom": height - y0,
                          "on": str(state) not in ("/Off", "None", "")})
        if items:
            out[i] = items
    return out


def inject_markers(lines, widgets):
    """Put a `[X]` / `[ ]` word where each checkbox actually sits.

    Written into the text at the widget's own x, so it lands immediately
    before the option it belongs to once the line is sorted left to right —
    the same thing a form that PRINTS its boxes would have given us, and a
    shape the model already reads correctly (9 of 9 on the printed-marker
    fixture).
    """
    if not widgets:
        return lines, 0
    out = [list(ln) for ln in lines]
    placed = 0
    for w in widgets:
        mid = (w["top"] + w["bottom"]) / 2.0
        word = {"text": "[X]" if w["on"] else "[ ]",
                "x0": w["x0"], "x1": w["x1"],
                "top": w["top"], "bottom": w["bottom"]}
        target = None
        for ln in out:
            if not ln:
                continue
            top = min(float(x["top"]) for x in ln)
            bottom = max(float(x.get("bottom", x["top"] + 10)) for x in ln)
            if top - LINE_TOL <= mid <= bottom + LINE_TOL:
                target = ln
                break
        if target is None:
            out.append([word])
        else:
            target.append(word)
            target.sort(key=lambda x: float(x["x0"]))
        placed += 1
    out.sort(key=lambda ln: min(float(x["top"]) for x in ln) if ln else 0.0)
    return out, placed


#: Attributes a word may not span. A word is a run of characters printed in one
#: go; two characters at DIFFERENT FONT SIZES were printed by different runs,
#: whatever their boxes do.
#:
#: I10 — SIZE-AWARE WORD GROUPING. `extract_words()` groups characters on
#: horizontal adjacency alone. Where a page prints several texts at different
#: scales over the same band of y — a statement at 5.5pt with a 2.4pt legal
#: layer and callouts over it — their characters interleave in x, and the
#: size-blind grouping SHATTERS every one of them into shards. One 12pt-tall
#: band of `round2/HTR-043235.pdf` page 3 holds 718 characters at five sizes:
#:
#:     extract_words()                 265 words: 'A' 'AM' 'n' 'T' 'on' 'M' 'nu'
#:     extract_words(extra_attrs=size) 116 words: 'For' 'consumer' 'accounts'
#:
#: Across that file it is 5 date-shaped words against 133, and the PROMPT —
#: `extract_text()`, which groups the same way — carried 3 transaction lines out
#: of about 130. Round 2 run 12 returned two rows that summed correctly and hid
#: 128; the model never had the others to return. The text layer was never
#: degraded. It was read by something that could not see a font change.
#:
#: ⚠ THIS IS THE SAME ROOT AS I7, from the other axis. Both are the text layer
#: handing the pipeline characters in an order the page does not print them in —
#: I7 stacks two texts vertically and clusters them into one line, I10 lays them
#: side by side and groups them into one word. Neither is a model defect, and
#: neither is visible in the model's answer.
_WORD_ATTRS = ["size"]

#: How far the size-blind reading must run above the size-aware one before this
#: page's TEXT is rebuilt rather than returned verbatim. Measured per page over
#: all 98 pages of `tests/test_pdfs/` carrying ≥40 words:
#:
#:     HTR-043235 p3   2.513      the shredded page
#:     HTR-043235 p2   1.140      the same damage, milder
#:     ---------------------      every other page in the corpus is below here
#:     CFPB H25B  p1   1.013      the highest clean page
#:
#: 1.05 sits in that gap. It is not tuned to a document: it says "the two
#: readings disagree about more than one word in twenty", and one in twenty is
#: already far outside anything a well-formed page produces.
SHARD_SHRED = 1.05


# ── THE READER SEAM ─────────────────────────────────────────────────────────
#
# `read_page` used to BE the pdfplumber reader: it called `extract_text()`,
# `extract_words(extra_attrs=…)`, `page.chars` and `page.page_number` directly,
# so "the same word-list contract" had nothing to attach to — there was no
# interface a second reader could implement. See docs/OCR-CONTRACT-SCOPING.md
# and docs/OCR-READER-SEAM-DESIGN.md.
#
# What is pluggable is OBTAINING a page's words and text. What is not is the
# policy above them — repair, markers, page stamping, overprint marking, the
# rebuild decision. The seam therefore sits BELOW `read_page`, which keeps its
# orchestration and its signature.
#
# TWO DECLARATIONS, because assuming either one is how a second reader fails
# silently rather than loudly:
#
#   a COORDINATE SPACE  so that pixels are never mistaken for points and a
#                       bottom-left origin is never mistaken for a top-left one
#   a CAPABILITY SET    so that "this reader cannot check" is never recorded as
#                       "this page is clean"


class Capability:
    """What a reader can do. A claim about the READER, not about the document.

    `overprinted` absent has meant two different things — "checked, clean" and
    "never checked" — and nothing could tell them apart. A capability is how
    the difference gets recorded.
    """

    #: Per-character boxes and per-character font size, i.e. `page.chars`.
    #: Without it `overprinted_spans` has no input and the overprint check does
    #: not run. NOT a claim that the page is clean — see
    #: `unchecked_overprint_pages`.
    CHARACTER_GEOMETRY = "character_geometry"

    #: The reader can tokenise the SAME page twice, once respecting font size
    #: and once blind to it. `shard_ratio` is the ratio between those two
    #: readings, so a reader that segments once cannot produce it at all — this
    #: is a mechanism, not a field (OCR-CONTRACT-SCOPING §2.5).
    SIZE_AWARE_TOKENISATION = "size_aware_tokenisation"

    #: `size` on a word is a real font size rather than a surrogate. Reserved:
    #: nothing reads `w["size"]` today, and a bbox-height stand-in would agree
    #: 97% of the time and disagree on exactly the pages that matter.
    TRUE_FONT_SIZE = "true_font_size"


#: The space everything downstream of the seam is expressed in. Every tolerance
#: in this module — LINE_TOL, EDGE_TOL, COLUMN_TOL, OVERPRINT_TOP_TOL — is in
#: POINTS measured from the TOP of the page, and each of them is a bare
#: inequality, so a reader in another space misaligns quietly instead of
#: raising.
ENGINE_UNIT = "pt"
ENGINE_ORIGIN = "top-left"


class CoordinateSpace:
    """What space a reader's coordinates are in. Declared, never inferred.

    A pixel coordinate and a point coordinate are both plausible floats and
    nothing about a value distinguishes them, which is exactly why the existing
    failure mode is silent. Only a declaration makes it detectable.

    THREE AXES ARE COVERED, and they fail independently:

      unit      points vs pixels — a scale error. Coordinates come out wrong by
                a constant factor, so things land far away.
      origin    top-left/y-down vs bottom-left/y-up — a MIRROR. A checkbox near
                the top of the page lands near the bottom, on a line that
                genuinely exists, at a plausible x. Worse than the scale error
                because the output looks more reasonable.
      height    needed to perform the origin flip at all; a flip against a
                disagreeing height is off by a constant and equally quiet.

    ⚠ ROTATION AND SKEW ARE OUT OF SCOPE (design §10.7). A `/Rotate 90` page
    and a scan fed in at an angle are two further ways two sources can disagree.
    All 114 pages of `tests/test_pdfs/` are unrotated, so nothing here would
    catch a regression in that, and deskew is a property of scanning equipment
    this repo has never seen. Declaring it handled would be the same kind of
    false assurance the shredded-layer warning refuses to give about scans.
    """

    __slots__ = ("unit", "origin", "height", "width", "dpi")

    def __init__(self, unit=ENGINE_UNIT, origin=ENGINE_ORIGIN, height=0.0,
                 width=0.0, dpi=None):
        self.unit = str(unit)
        self.origin = str(origin)
        self.height = float(height or 0.0)
        self.width = float(width or 0.0)
        self.dpi = float(dpi) if dpi else None

    def __repr__(self):
        return (f"CoordinateSpace(unit={self.unit!r}, origin={self.origin!r}, "
                f"height={self.height!r}, width={self.width!r}, "
                f"dpi={self.dpi!r})")

    @property
    def is_engine_space(self):
        return self.unit == ENGINE_UNIT and self.origin == ENGINE_ORIGIN

    def scale_to_points(self):
        if self.unit == "pt":
            return 1.0
        if self.unit == "px":
            return 72.0 / self.dpi
        raise CoordinateSpaceError(f"unit {self.unit!r} cannot be converted")

    def validate(self):
        """Refuse a declaration the seam cannot convert. Loudly.

        A failure here is a failure — it does not fall back to "assume points",
        because assuming is the bug. Same rule as the engine's refusal to wrap
        extraction in a bare `except`.
        """
        if self.unit not in ("pt", "px"):
            raise CoordinateSpaceError(
                f"unknown unit {self.unit!r}; expected 'pt' or 'px'")
        if self.unit == "px" and not self.dpi:
            raise CoordinateSpaceError(
                "a reader declaring pixels must declare its dpi, or its "
                "coordinates cannot be converted to points")
        if self.origin not in ("top-left", "bottom-left"):
            raise CoordinateSpaceError(
                f"unknown origin {self.origin!r}; expected 'top-left' or "
                f"'bottom-left'")
        if self.origin == "bottom-left" and self.height <= 0:
            raise CoordinateSpaceError(
                "a reader declaring a bottom-left origin must declare the page "
                "height, or the flip to top-down cannot be performed")
        return self


class CoordinateSpaceError(ValueError):
    """A reader declared a space the seam cannot convert to the engine's."""


_XY_KEYS = ("x0", "x1")
_Y_KEYS = ("top", "bottom", "doctop")


def normalise_words(words, space):
    """Words in `space` -> words in the engine's space (points, top-left).

    Converts IN PLACE and returns the list: a reader hands its words over, and
    nothing downstream ever sees a coordinate in any other space. That is the
    whole point — `LINE_TOL <= 3.0` means three points from the top of the page
    everywhere, for every reader, without a single call site knowing which
    reader ran.

    A source already in the engine's space is returned untouched, so the
    pdfplumber path costs nothing and its floats are bit-identical to before.
    """
    space.validate()
    if space.is_engine_space:
        return words
    scale = space.scale_to_points()
    height_pt = space.height * scale
    flip = space.origin == "bottom-left"
    for w in words or ():
        for k in _XY_KEYS:
            if k in w:
                w[k] = float(w[k]) * scale
        for k in _Y_KEYS:
            if k in w:
                y = float(w[k]) * scale
                w[k] = (height_pt - y) if flip else y
        if flip and "top" in w and "bottom" in w and w["top"] > w["bottom"]:
            # The flip reverses which edge is nearer the top of the page.
            w["top"], w["bottom"] = w["bottom"], w["top"]
        for k in ("height", "width", "size"):
            if k in w:
                try:
                    w[k] = float(w[k]) * scale
                except (TypeError, ValueError):
                    pass
    return words


class PageSource:
    """One page, from some reader. The interface `read_page` talks to.

    Implementations supply:

        page_number             1-based FILE page, or None
        space                   CoordinateSpace, declared not inferred
        capabilities            frozenset of Capability values
        raw_text()              the page's text as the reader flattens it
        words(size_aware=bool)  word dicts in `space`
        chars()                 character dicts, only with CHARACTER_GEOMETRY

    A word must carry `text`, `x0`, `x1`, `top` and `bottom`. `page` and
    `overprinted` are ANNOTATIONS the engine adds and a reader must not set;
    `size` is optional and gated on TRUE_FONT_SIZE; `doctop`, `height`,
    `width`, `upright` and `direction` are pdfplumber passthroughs that nothing
    reads and no reader is required to supply.
    """

    page_number = None
    space = None
    capabilities = frozenset()

    def raw_text(self):
        raise NotImplementedError

    def words(self, size_aware=True):
        raise NotImplementedError

    def chars(self):
        return []

    def can(self, capability):
        return capability in (self.capabilities or frozenset())


class PdfplumberSource(PageSource):
    """The default reader: today's behaviour, unchanged, behind the seam.

    Every number this produces is the number `read_page` produced before the
    seam existed, because it makes the same three calls in the same order. The
    only thing that is new is that it SAYS what it can do.

    ⚠ `SIZE_AWARE_TOKENISATION` is discovered, not assumed. A pdfplumber old
    enough to reject `extra_attrs` used to fall into a `TypeError` branch that
    silently produced a shard ratio of 1.0 — a clean reading, from a reader that
    could not perform the comparison. That branch is now what DROPS the
    capability, so the same reader reports "not checked" instead.
    """

    def __init__(self, page):
        self._page = page
        self._size_aware = None          # unknown until first asked
        self._caps = None

    @property
    def page_number(self):
        return getattr(self._page, "page_number", None)

    @property
    def space(self):
        # pdfplumber reports x0/top in POINTS from the TOP-LEFT of the page.
        # `height`/`width` are declared even though no conversion needs them
        # here, because the declaration is what a second source is checked
        # against.
        return CoordinateSpace(
            unit="pt", origin="top-left",
            height=float(getattr(self._page, "height", 0.0) or 0.0),
            width=float(getattr(self._page, "width", 0.0) or 0.0))

    @property
    def capabilities(self):
        if self._caps is None:
            caps = set()
            if self._probe_size_aware():
                caps.add(Capability.SIZE_AWARE_TOKENISATION)
                caps.add(Capability.TRUE_FONT_SIZE)
            try:
                if getattr(self._page, "chars", None) is not None:
                    caps.add(Capability.CHARACTER_GEOMETRY)
            except Exception:
                pass
            self._caps = frozenset(caps)
        return self._caps

    def _probe_size_aware(self):
        if self._size_aware is None:
            try:
                self._page.extract_words(extra_attrs=_WORD_ATTRS)
                self._size_aware = True
            except TypeError:
                self._size_aware = False
            except Exception:
                self._size_aware = False
        return self._size_aware

    def raw_text(self):
        return self._page.extract_text() or ""

    def words(self, size_aware=True):
        if size_aware and self._probe_size_aware():
            return self._page.extract_words(extra_attrs=_WORD_ATTRS)
        return self._page.extract_words()

    def chars(self):
        try:
            return self._page.chars
        except Exception:
            return []


def as_page_source(page_or_source):
    """The backward-compatibility hinge.

    All 31 existing `read_page(...)` call sites pass a pdfplumber page
    positionally. They keep working, unedited, because anything that is not
    already a `PageSource` is wrapped in the default one. Rewriting thirty test
    call sites in the same change as a structural refactor would have destroyed
    the evidence that tells us the refactor was safe.
    """
    if isinstance(page_or_source, PageSource):
        return page_or_source
    return PdfplumberSource(page_or_source)


def read_page(page, widgets=(), stats=None):
    """(text, lines, repairs) for one pdfplumber page.

    `text` is `extract_text()` VERBATIM when the page needed no repair — see
    the module docstring for why that matters — and rebuilt from the repaired
    words when it did.

    `stats`, when a dict is passed in, is filled with what was measured about
    this page — `shard_ratio` today. An out-parameter rather than a fourth
    return value because a dozen callers unpack the triple.
    """
    source = as_page_source(page)
    raw = source.raw_text()
    try:
        words = normalise_words(source.words(size_aware=True), source.space)
    except CoordinateSpaceError:
        raise
    except Exception:
        return raw, [], []

    # THE SHREDDED-LAYER CHECK IS A MECHANISM, NOT A FIELD. `shard_ratio` is
    # the ratio between two tokenisations of ONE page by ONE reader, one
    # respecting font size and one blind to it. A reader that segments a page
    # once cannot produce the second reading, so it cannot produce the ratio —
    # and a surrogate derived from its own segmentation would be a diff against
    # itself, which measures nothing.
    #
    # So the check is CAPABILITY-GATED and its absence is recorded. It is not
    # defaulted to 1.0: that is the value a clean page scores, and reporting a
    # clean score for a check that never ran is the failure this whole seam
    # exists to prevent.
    if source.can(Capability.SIZE_AWARE_TOKENISATION):
        try:
            plain = source.words(size_aware=False)
        except Exception:
            plain = words
        shard = len(plain) / max(len(words), 1)
        if stats is not None:
            stats["shard_ratio"] = shard
    else:
        shard = None
        if stats is not None:
            stats["shard_checked"] = False

    lines, repairs = repair_wrapped(words)
    lines, placed = inject_markers(lines, widgets)
    stamp_page(lines, source.page_number)
    # Marked on the FINAL word list and by geometry, so a fused fragment or an
    # injected marker cannot lose the tag.
    #
    # ⚠ WITHOUT CHARACTER GEOMETRY THIS DOES NOT RUN, and `overprinted` is left
    # absent on every word — which is what it already means for a clean page.
    # The per-word flag stays TWO-VALUED on purpose: `overprinted_value` reads
    # it through `if not w.get("overprinted")`, and `slot_extractor` reads THAT
    # through `if overprinted_value(...)`, so a third per-word value would
    # either be swallowed by the negation or fire the demotion on every value in
    # the document. The fact that the check did not run is carried at DOCUMENT
    # level instead — `stats["overprint_checked"]`, and from there
    # `unchecked_overprint_pages`.
    if source.can(Capability.CHARACTER_GEOMETRY):
        mark_overprints(lines, overprinted_spans_from_chars(source.chars()))
    elif stats is not None:
        stats["overprint_checked"] = False
    # THE PROMPT HAS TO BE FIXED TOO, or nothing is. `extract_text()` groups
    # characters exactly as the size-blind `extract_words()` did, so the change
    # above repairs the GEOMETRY and leaves the MODEL reading the shards: on
    # HTR-043235 page 3 the returned text still carried 5 dates and 3
    # transaction lines while `lines` already held 133 and 70.
    #
    # A shredded page is therefore rebuilt from its words — and ONLY a shredded
    # one. Rebuilding is not byte-identical (30 of the corpus's 77 pages differ
    # from `extract_text()` in whitespace alone) and the text is part of the
    # prompt, so rewriting an undamaged page changes what the model is asked and
    # throws away its cached answer for nothing. That is the rule `repairs` and
    # `placed` already follow; this is the third case of it.
    #
    # The test is the RATIO, not a comparison of the two texts. Comparing them
    # was tried: flattened for whitespace it still fired on 36 of 114 pages,
    # including SampleBill and feb2225, which differ from the size-aware reading
    # by four and one token respectively — rewriting a whole page, and every
    # cached answer for it, over one word.
    # `shard is None` means the ratio could not be MEASURED, not that it came
    # back clean. The two are kept apart deliberately and land in different
    # places: the rebuild decision here takes the conservative branch (return
    # the reader's own text verbatim, exactly as an unshredded page does,
    # because nothing has been shown to be wrong with it), while the fact that
    # the check never ran travels out through `stats` and is reported. Folding
    # the unmeasured case into `shard = 1.0` would have made both decisions at
    # once and reported a clean page.
    not_shredded = shard is None or shard < SHARD_SHRED
    if not repairs and not placed and not_shredded \
            and not _recovered_words_missing(raw, lines):
        return raw, lines, []
    return text_from_lines(lines), lines, repairs


def _recovered_words_missing(raw, lines) -> bool:
    """Did the size-aware reading recover a word the PROMPT does not contain?

    The shard ratio catches a page that is shredded wholesale. It does not catch
    a page with ONE overprinted region, because four words out of four hundred
    do not move a ratio: `SampleBill.pdf` page 4 sits at 1.00 and prints its
    account number twice, at 11.0pt and 10.2pt, in the same place.

    Leaving it there made the prompt and the geometry disagree — the word boxes
    held `0000123456` and `0000158659` while `extract_text()`, which is still
    size-blind, still held `00000000112538645596`. The model would still be
    offered the interleaving, `verify_span` would still ground it against the
    same text, and the overprint flag that used to catch it is correctly gone,
    because at the word level there is no longer anything wrong. Recovering a
    value and then not telling the model is the worst of the three states.

    So: a word of four characters or more that the page's own flattened text
    does not contain is a word this reading recovered and that reading lost.
    Four, because shorter tokens collide by chance.
    """
    flat = _flat(raw).replace(" ", "")
    if not flat:
        return False
    for ln in lines:
        for w in ln:
            t = _flat(w.get("text", "")).replace(" ", "")
            if len(t) >= 4 and t not in flat:
                return True
    return False


# ── which page a line is on ──────────────────────────────────────────────────
#
# Every consumer of positional evidence flattens the pages into one list of
# lines, and the flattening threw the page away: `top` restarts at zero on each
# page, so nothing downstream could tell the last line of page 1 from the first
# line of page 2. Region binding needs the page (round 2, I1: a band bound a
# table on page 1 AND its lookalike on page 2), and so does every other check
# that must not reach across a page — a record span, a wrapped value, an
# overprint.
#
# The page is stamped on the WORD, at the moment the word is read, as the
# page's number IN THE FILE. It is not derived from a list index later, because
# the lists get sliced — `selected_pages`, and one file split into several
# documents — and an index into a slice names the wrong page in a warning the
# user reads. A word read without a pdfplumber page (a hand-built fixture)
# carries no stamp, and every caller treats that as "no verdict".

def stamp_page(lines, page_number):
    """Record the 1-based file page on every word of `lines`, in place."""
    if page_number is None:
        return
    for ln in lines:
        for w in ln:
            w["page"] = int(page_number)


def line_page(line):
    """The 1-based file page `line` was read from, or None if unstamped."""
    for w in line or ():
        p = w.get("page") if isinstance(w, dict) else None
        if p is not None:
            return int(p)
    return None


def flatten_pages(page_lines):
    """Every line of every page, in reading order — one list, pages stamped."""
    return [ln for pg in (page_lines or []) for ln in (pg or [])]


def page_for_prompt_page(page_lines, n):
    """The file page behind prompt page `n` (1-based position in `page_lines`).

    The model numbers pages by their position in the prompt, which is not the
    file's numbering once pages have been selected or the file split.
    """
    try:
        i = int(n) - 1
    except (TypeError, ValueError):
        return None
    if not (0 <= i < len(page_lines or [])):
        return None
    for ln in page_lines[i] or ():
        p = line_page(ln)
        if p is not None:
            return p
    return None


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


def source_occurrences(lines, source):
    """Indices of every document line the quoted `source` could be read from.

    This is what makes a row's IDENTITY positional rather than textual. Two
    rows quoting the same words are only the same row if the document prints
    those words once; if it prints them twice they are two rows, and dropping
    the second deletes real data. That is not an edge case — in a file holding
    twenty invoices the identifying lines repeat by construction.

    Matching is on the source's FIRST line, because a record spanning several
    printed lines is quoted as several lines and no single line contains the
    whole span. An exact line match wins outright; only if there is none does a
    source that is a FRAGMENT of a line count, so a short quote cannot claim
    half the document.
    """
    first = next((p for p in str(source or "").splitlines() if p.strip()), "")
    src = _flat(first)
    if not src:
        return []
    exact, partial = [], []
    for i, ln in enumerate(lines):
        t = _flat(" ".join(str(w["text"]) for w in ln))
        if not t:
            continue
        if t == src:
            exact.append(i)
        elif src in t:
            partial.append(i)
    return exact or partial


#: A record may span this many printed lines before we stop believing the two
#: belong together. Eight covers a boxed tax form; a runaway span would let a
#: value from further down the page ground a cell it has nothing to do with.
MAX_RECORD_LINES = 8


def record_span(lines, start, stop=None):
    """The text of the lines one record actually occupies.

    A row's cells are verified against the ONE line the model quoted, which is
    right for a table and wrong for a form: FORM-W2-2023 lays each employee out
    across four printed lines, the model quotes the first two, and the values on
    the other two are reported as ungrounded even though they are correct and
    printed inches away. That is not a grounding failure, it is a
    misidentification of what the record IS.

    The span runs from the line this record was read from to the line the NEXT
    record was read from, so it can never reach into a neighbouring record —
    which is what keeps the check meaningful. A record with no successor is
    capped at `MAX_RECORD_LINES`.
    """
    if start is None or not lines:
        return ""
    end = stop if stop is not None else start + MAX_RECORD_LINES
    end = min(max(end, start + 1), start + MAX_RECORD_LINES, len(lines))
    return "\n".join(" ".join(str(w["text"]) for w in ln)
                     for ln in lines[start:end])


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
