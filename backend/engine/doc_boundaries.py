"""
DocAgent — Document boundaries
==============================

One file was one document, unconditionally. `preprocess_file` returned a single
`ProcessedDocument`, `compute_shape` enumerated one set of slots for the whole
file, and `build_prompt` embedded every page in one prompt and never mentioned
documents at all. Three invoices merged into one PDF produced **13 field slots
where 3 x 13 were needed**: one slot addressed "Invoice Number" against three
distinct invoice numbers in the text. The model returned one, and the other two
invoices were lost with no error, no flag and no note.

That is the product's own core use case — twenty invoices in one file, a
statement run, a batch of cheques — so it is worth splitting the file rather
than teaching one prompt to answer for many documents at once. Splitting keeps
slot addressing exactly as it is: each document gets the full slot set, its own
grounding, its own confidence, and its own result. The Excel writer already
stacks a list of results, so nothing downstream changes.

WHAT DECIDES A BOUNDARY, AND WHAT MERELY SUGGESTS ONE
-----------------------------------------------------
The first version had two signals and treated either as sufficient. That was
wrong in a way no amount of tuning could fix, and it cost a real document:

    A REPEATED TITLE MEANS "A NEW DOCUMENT" IN A CONCATENATION AND "A
    CONTINUATION" IN A FORM, AND IT IS THE SAME OBSERVATION IN BOTH.

A six-page Closing Disclosure whose contact page reopens with the form's title
was cut in two. Page 1 extracted correctly; the second block came back nearly
empty, carrying only the lender, the title company and the loan ID — the three
values that page restates. The whole Contact Information matrix, five parties
by nine rows, was never extracted at all, because the second block was asked
for the FIRST page's slots. Restating the parties and the reference on later
pages is what the later pages of a form are FOR, so every multi-page form was
at risk and none had ever been tested: the corpus's 17 multi-page documents are
two-page statements whose page 2 opens with a different line entirely.

    SUGGESTS A BOUNDARY (a candidate, never a verdict on its own)

    repeated title   within a run of same-type pages, a page whose first line
                     is that run's title — the run's first line, or a line
                     printed on two CONSECUTIVE pages.

    DECIDES

    type change      a page classifying as a different document type from the
                     last page that classified as anything (`classify_by_hints`,
                     keyword pre-screening, no model call). Measured: NO
                     multi-page document in the corpus changes type between its
                     own pages (0 of 17), so this needs no corroboration —
                     and requiring it cost a real boundary, because an invoice
                     and the cheque that pays it share the PO number they both
                     quote.

    CORROBORATES      the REFERENCE must change. Recurrence of a reference means
                     CONTINUATION: a Closing Disclosure repeats
                     `Loan ID # 123456789` on every page, while twenty
                     concatenated invoices carry twenty different numbers. The
                     old rule had this exactly backwards.

    VETOES            "page 3 of 5" after "page 2 of 5" — the document stating
                     its own extent. Applied PER RUN, so a stack of five-page
                     forms still splits between them. On the real Closing
                     Disclosure this is load-bearing rather than decorative:
                     its page 4 reads as a bank statement and its page 6 as a
                     tax form, and only the page count keeps them together.

    OVERRIDES         a "page 1 of N" directly after a later page of a run. The
                     one boundary allowed on no other evidence, because two
                     copies of ONE form concatenated share every reference and
                     every heading.

WHICH DIRECTION IT IS ALLOWED TO BE WRONG IN
--------------------------------------------
Over-splitting loses everything on the split pages, silently: the slots asked
for belong to a different page. Under-splitting returns one document where
there were several, which is visible in the output. So the rule under-splits by
construction, and the one case it gives up is recorded in
docs/KNOWN-LIMITATIONS.md: a concatenation whose documents carry NO readable
reference is treated as one document. Falling back to the title rule there was
considered and rejected — it would reintroduce guessing exactly where there is
least information to justify it.
"""

import re

#: A split must leave each document with at least this much text, or the
#: "documents" are page furniture rather than records.
_MIN_LINES_PER_DOC = 2


def _signature(text):
    """The page's first non-empty line, normalised."""
    for line in str(text or "").split("\n"):
        t = re.sub(r"\s+", " ", line).strip()
        if t:
            return t.casefold()
    return ""


def _doc_type(text):
    """Keyword pre-screening only — no model call. None when unsure."""
    try:
        from app.api.routes.prompt_registry import classify_by_hints
    except Exception:
        return None
    try:
        return classify_by_hints(str(text or ""))
    except Exception:
        return None


#: A document REFERENCE — the number a document is known by. Two shapes cover
#: everything measured: a typed code (INV-2024-0031, EMP-0012, PO-2024-0018)
#: and a long bare number introduced by a label (Loan ID # 123456789).
#:
#: The word boundaries are load-bearing: without the one before `id`, "Paid
#: 1234567" matches, and one stray reference is enough to make a page look
#: like a different document from the page before it.
_REFERENCE = re.compile(
    r"\b([A-Z]{2,6}-[0-9][0-9A-Za-z-]{2,})\b"
    r"|\b(?:id|no|number|ref)\b\.?\s*#?\s*([0-9]{6,})\b"
    r"|#\s*([0-9]{6,})\b",
    re.I)

_PAGE_OF = re.compile(r"page\s+(\d{1,3})\s*(?:of|/)\s*(\d{1,3})", re.I)


def references(text):
    """Every document reference printed on this page.

    RECURRENCE OF A REFERENCE MEANS CONTINUATION, NOT A BOUNDARY — which is
    the whole correction. A Closing Disclosure repeats `Loan ID # 123456789`
    on all five pages, because restating the parties and the reference is what
    the later pages of a form are FOR. Twenty concatenated invoices carry
    twenty DIFFERENT numbers. The old rule read repetition as evidence of a new
    document and so had the two cases exactly backwards.

    Two shapes cover everything measured: a typed code (INV-2024-0031,
    EMP-0012) and a long bare number introduced by a label (Loan ID #
    123456789).
    """
    out = set()
    for groups in _REFERENCE.findall(str(text or "")):
        token = next((g for g in groups if g), "")
        if token:
            out.add(token.strip().upper())
    return out


def page_of(text):
    """(n, total) if the page says which of how many it is, else None."""
    m = _PAGE_OF.search(str(text or ""))
    if not m:
        return None
    n, total = int(m.group(1)), int(m.group(2))
    return (n, total) if 1 <= n <= total else None


def find_starts(page_texts):
    """Indices of the pages that BEGIN a document, and why.

    Always includes page 0. Returns ([0]) — a single document — when neither
    signal fires, which is the behaviour every caller had before this existed.
    """
    n = len(page_texts or [])
    if n <= 1:
        return [0], ""

    sigs = [_signature(t) for t in page_texts]
    types = [_doc_type(t) for t in page_texts]

    # SIGNAL 2 first: where the document TYPE changes, a document certainly
    # begins. A page the classifier is unsure about (None) continues whatever
    # came before rather than starting something.
    # Compared against the last KNOWN type, not the previous page's. A
    # continuation page often classifies as nothing at all — an income
    # statement's second page is a sentence of small print — and letting that
    # None erase the segment's type hid the next document's start completely.
    changed, prev_known = set(), None
    for i, t in enumerate(types):
        if t and prev_known and t != prev_known:
            changed.add(i)
        if t:
            prev_known = t

    # SIGNAL 1, applied WITHIN each type-homogeneous segment: a document start
    # looks like that segment's FIRST page.
    #
    # Anchoring to the segment rather than to page 0 is what finds a run of
    # the same document in the middle of a mixed batch — two cheques after two
    # invoices open with a bank letterhead, which matches neither the file's
    # first line nor a type change, and were silently merged into one.
    #
    # Anchoring to a first page at all, rather than counting any repeated
    # line, is what separates a title from a continuation: two income
    # statements give first lines [title, "Prepared by…", title, "Prepared
    # by…"] and BOTH repeat, so counting repetition made all four pages
    # starts.
    # A signature is a TITLE within its segment when it either opens that
    # segment, or appears on TWO CONSECUTIVE pages — because a run of
    # single-page documents prints its title on adjacent pages, and a
    # continuation line never can.
    #
    # Adjacency is what tells a title from a repeated footer. Two income
    # statements give [title, "Prepared by…", title, "Prepared by…"]: both
    # lines repeat, but only the title opens the segment and neither is ever
    # adjacent to itself, so the footer is correctly read as a continuation.
    # Two receipts in the middle of a mixed batch give the same letterhead on
    # adjacent pages, which no other rule here could see — receipts classify
    # as None, so the type never changes and the segment never breaks.
    seg_bounds = sorted({0} | changed) + [n]
    repeated = set()
    for a, b in zip(seg_bounds, seg_bounds[1:]):
        titles = {sigs[a]} if sigs[a] else set()
        titles |= {sigs[i] for i in range(a + 1, b)
                   if sigs[i] and sigs[i] == sigs[i - 1]}
        hits = {i for i in range(a, b) if sigs[i] in titles}
        if len(hits) > 1:
            repeated |= hits

    # ══════════════════════════════════════════════════════════════════
    # A CANDIDATE IS NOT YET A BOUNDARY
    # ══════════════════════════════════════════════════════════════════
    #
    # Everything above is a candidate, and candidates alone used to be the
    # whole rule. They cannot be. A repeated title means "a new document" in a
    # concatenation and "a continuation" in a form, and it is the SAME
    # observation in both — so no threshold on it can separate the two. A
    # Closing Disclosure whose contact page reopens with the form's title was
    # split in two, and the ~30 values on that page were never extracted,
    # because the second block was asked for the first page's slots.
    #
    # A candidate now has to be CORROBORATED by the reference changing, and
    # can be VETOED by the document stating its own extent. Both make the
    # split strictly more conservative than it was: neither can create a
    # boundary the old rule would not also have created, except the one case
    # marked below where the document restarts its own page numbering.
    refs = [references(t) for t in page_texts]
    pages_of = [page_of(t) for t in page_texts]

    starts, carried = [0], set(refs[0])
    for i in range(1, n):
        if _restarts_its_own_numbering(pages_of, i):
            # The document says so itself: a "page 1 of N" directly after a
            # later page of a numbered run. This is the one boundary allowed
            # on no other evidence, because two copies of ONE form
            # concatenated share every reference and every heading, and
            # nothing else can see the seam between them.
            starts.append(i)
            carried = set(refs[i])
            continue
        if i not in repeated and i not in changed:
            carried |= refs[i]
            continue
        if _continues_a_numbered_run(pages_of, i):
            # "Page 3 of 5" after "page 2 of 5" outranks every other signal.
            carried |= refs[i]
            continue
        if i in changed:
            # A TYPE CHANGE NEEDS NO CORROBORATION. It is a far narrower claim
            # than a repeated title — a page reading as a cheque directly after
            # one reading as an invoice — and measured across the corpus, NO
            # multi-page document changes type between its own pages (0 of 17),
            # nor does the Closing Disclosure. Requiring corroboration here
            # cost a real boundary instead: an invoice followed by the cheque
            # that pays it share the PO number they both quote, so a
            # cross-reference looked like continuity and a mixed batch stopped
            # splitting. Forms that print a page count are still protected by
            # the veto above.
            starts.append(i)
            carried = set(refs[i])
            continue
        # CORROBORATION, for a repeated title only. That signal means "a new
        # document" in a concatenation and "a continuation" in a form and is
        # the SAME observation in both, so on its own it decides nothing. The
        # page must carry references and share NONE with the document so far;
        # sharing one — the same loan, the same invoice — is the page saying
        # it belongs to what came before.
        if refs[i] and carried and not (refs[i] & carried):
            starts.append(i)
            carried = set(refs[i])
        else:
            carried |= refs[i]

    # A candidate whose document would be page furniture is a CONTINUATION —
    # fold it into the document above rather than abandoning the whole split,
    # which is what discarding it wholesale used to do.
    kept = [0]
    for a, b in zip(starts, starts[1:] + [n]):
        if a == 0:
            continue
        lines_in = sum(len([l for l in str(page_texts[p] or "").split(chr(10))
                            if l.strip()])
                       for p in range(a, b))
        if lines_in >= _MIN_LINES_PER_DOC:
            kept.append(a)
    starts = kept
    if len(starts) < 2:
        return [0], ""

    why = []
    if repeated - {0}:
        why.append("pages reopen with their section's title line")
    if changed:
        why.append("the document type changes at page(s) "
                   + ", ".join(str(i + 1) for i in sorted(changed)))
    why.append("the reference changes at page(s) "
               + ", ".join(str(i + 1) for i in starts[1:]))
    return starts, "; ".join(why)


def _continues_a_numbered_run(pages_of, i):
    """Page i is page n+1 of the same run page i-1 was page n of.

    "Page 3 of 5" after "page 2 of 5" is the document stating outright that
    these are one document, which nothing else here can see. It VETOES a
    boundary rather than creating one, so it can only make the split more
    conservative.
    """
    a, b = pages_of[i - 1], pages_of[i]
    return bool(a and b and a[1] == b[1] and b[0] == a[0] + 1)


def _restarts_its_own_numbering(pages_of, i):
    """Page i is a "page 1 of N" directly after a later page of a run.

    Applied PER RUN, not per file. A stack of five-page forms each opening at
    "page 1 of 5" splits between them — which a per-file reading of the same
    marker would have missed, treating the whole stack as one document.
    """
    a, b = pages_of[i - 1], pages_of[i]
    return bool(a and b and b[0] == 1 and a[0] > 1)


def split(page_texts, page_lines=None, page_images=None):
    """[(pages, lines, images, first_page_number)] — one entry per document.

    Slices are handed to the ordinary pipeline unchanged, one per document, so
    each gets the full slot set and its own grounding. A file with one document
    yields exactly one slice identical to the whole input.
    """
    starts, why = find_starts(page_texts)
    n = len(page_texts or [])
    out = []
    for a, b in zip(starts, starts[1:] + [n]):
        out.append((
            list(page_texts[a:b]),
            list((page_lines or [])[a:b]) if page_lines else [],
            list((page_images or [])[a:b]) if page_images else [],
            a + 1,
        ))
    return out, why
