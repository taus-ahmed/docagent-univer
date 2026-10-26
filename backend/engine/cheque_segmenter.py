"""The cheque segmenter: MICR bands as the document boundary signal.

Moved here unchanged from doc_boundaries.py (the split signal),
extractor.py (several cheques on one page; a record that may hold several)
and kept beside micr.py and cheque_regions.py, which it calls.

Registered for `ANY` family (segmenters.py says why): the signal is the band
printed on the page, and a no-template upload has no family when it is split.
It does NOT run for a known non-cheque family (`families`), and a band counts
only on a page with a cheque context and genuine MICR evidence
(`micr.cheque_bands`): invoices, payslips and statements print reference lines
shaped exactly like a band (Run 15, item 9).
"""
from __future__ import annotations

from segmenters import ANY, Segmenter, register


class ChequeSegmenter(Segmenter):
    name = "cheque"
    start_reason = "a new cheque's MICR band begins at page(s) "
    unit = "cheque"
    #: a template of a KNOWN other family never runs this (segmenters.py)
    families = frozenset({"cheque", "check", "cheques", "checks"})

    # A CHEQUE'S REFERENCE IS ITS MICR BAND (Gate 4b). A scanned cheque has no
    # title the next one repeats, no type change and no page numbering, so no
    # generic candidate ever fires between two of them, and ten cheques were
    # one document. A band is the one thing every cheque prints and no two
    # cheques share (routing + account + serial), so a band naming a
    # DIFFERENT cheque from every band the document has carried so far is
    # both the candidate and its corroboration. A page with no band (a
    # continuation, a remittance slip) never starts anything.
    def page_marks(self, text) -> list:
        # Only a CHEQUE's band (micr.cheque_bands): genuine MICR evidence AND
        # a cheque context on the page. A reference line on an invoice is
        # shaped like a band and is not one.
        from micr import cheque_bands
        return cheque_bands(text)

    def starts_new(self, marks, carried) -> bool:
        """Every band on the page is a DIFFERENT cheque from every band carried.

        "Cannot tell" (no part in common) is not different: a boundary needs
        evidence, and under-splitting is the visible direction — the record
        keeps both bands and is flagged `possible_multiple_documents`
        downstream.
        """
        from micr import same_band
        return bool(marks and carried) and all(
            same_band(b, c) is False for b in marks for c in carried)

    def cut_page(self, lines):
        from cheque_regions import cut_regions
        from micr import cheque_context
        text = "\n".join(" ".join(str(w.get("text", "")) for w in ln)
                         for ln in lines or [])
        if not cheque_context(text):
            return None, "no cheque context on the page"
        return cut_regions(lines)

    def multiple_in_record(self, texts):
        """{"micr_bands", "readable"} when the record carries a readable band
        and, besides it, another band (readable or band-shaped), else None."""
        from micr import band_count, cheque_context
        if not any(cheque_context(t) for t in texts):
            return None
        counts = [band_count(t) for t in texts]
        readable = sum(c[0] for c in counts)
        total = readable + sum(c[1] for c in counts)
        if total < 2:
            return None
        return {"micr_bands": total, "readable": readable}


register(ANY, ChequeSegmenter())
