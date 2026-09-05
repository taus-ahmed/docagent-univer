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


def read_page(page, widgets=()):
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
    lines, placed = inject_markers(lines, widgets)
    if not repairs and not placed:
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
