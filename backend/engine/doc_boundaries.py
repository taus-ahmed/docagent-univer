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

TWO SIGNALS, BOTH DETERMINISTIC, NEITHER AN LLM CALL
----------------------------------------------------
    repeated title   a page whose first line also starts another page. This is
                     what a batch of the same document looks like: every
                     invoice opens with the same letterhead. Measured on the
                     corpus: five same-type merges, five exact matches,
                     including two-page payslips where page 2 is correctly NOT
                     a start.

    type change      a page that classifies as a different document type from
                     the page before it (`classify_by_hints`, keyword
                     pre-screening, no model call). This is what a MIXED batch
                     looks like, where nothing repeats and the first signal
                     finds nothing at all.

They are complementary: the first fires only on homogeneous batches, the second
only on heterogeneous ones, and neither fires on a single document.

WHY THIS IS ALLOWED TO BE WRONG IN ONE DIRECTION ONLY
-----------------------------------------------------
Splitting a document that should not have been split produces N stacked blocks,
most of them mostly empty — ugly, obvious, and fixable by the user in one look.
NOT splitting a file that should have been produces one plausible result and
silently discards the rest. The costs are not symmetric, so where the evidence
is weak this errs toward splitting — but it never splits on no evidence at all:
one signature and one document type means one document, exactly as before.

A running header repeated on every page of a long report is the shape that
would be split wrongly. No document in the 60-document corpus has one (all 17
multi-page documents have a different first line on page 2), and the failure is
visible rather than silent, so it is accepted and recorded in
docs/KNOWN-LIMITATIONS.md rather than guessed at.
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

    starts = sorted({0} | repeated | changed)

    # A candidate whose document would be page furniture is a CONTINUATION —
    # fold it into the document above rather than abandoning the whole split,
    # which is what discarding it wholesale used to do.
    kept = [0]
    for a, b in zip(starts, starts[1:] + [n]):
        if a == 0:
            continue
        lines = sum(len([l for l in str(page_texts[p] or "").split("\n")
                         if l.strip()])
                    for p in range(a, b))
        if lines >= _MIN_LINES_PER_DOC:
            kept.append(a)
    starts = kept
    if len(starts) < 2:
        return [0], ""

    why = []
    if repeated - {0}:
        why.append(f"{len(repeated)} pages open with their section's own "
                   f"title line")
    if changed:
        why.append("the document type changes at page(s) "
                   + ", ".join(str(i + 1) for i in sorted(changed)))
    return starts, "; ".join(why)


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
