"""Per-family segmentation — where one document ends and the next begins.

The generic boundary rules (doc_boundaries.py) read titles, references and
page numbering. Some families carry a stronger, family-specific signal: a
cheque prints a MICR band that names exactly one cheque. Such signals live
behind this interface, registered next to the validator registry, so the
generic engine asks "does any segmenter see a new document here?" and never
knows what a MICR band is.

A segmenter offers three things, each optional:

  page_marks(text) / starts_new(marks, carried)
        per-page identity marks, and whether a page's marks name a document
        different from every mark carried so far (a split signal ranked where
        a changed reference is; the page-numbering vetoes still outrank it)
  cut_page(lines) -> (regions | None, why)
        several documents on ONE page, cut by geometry into regions
        ({box, text, lines}); only asked for an OCR'd page
  multiple_in_record(texts) -> dict | None
        evidence that one record may still hold several documents, kept as
        one and flagged (`possible_multiple_documents`)

Registration is by family. `ANY` holds segmenters whose signal is evidence on
the PAGE rather than a property of the declared family — the cheque's MICR
band is one, and it is registered there because a no-template upload has no
family yet when the file is split. A family with no segmenter of its own
therefore runs exactly what runs today: the `ANY` ones.
"""
from __future__ import annotations

ANY = "*"

#: family -> [segmenter], in registration order.
REGISTRY: dict = {}


class Segmenter:
    """Base: a segmenter that sees nothing. Override what the family has."""
    name = ""
    #: the reason given when this segmenter starts a document
    start_reason = ""
    #: what one cut region is called in logs and notes ("cheque")
    unit = "document"

    def page_marks(self, text) -> list:
        return []

    def starts_new(self, marks, carried) -> bool:
        return False

    def cut_page(self, lines):
        return None, ""

    def multiple_in_record(self, texts):
        return None


def register(family, segmenter):
    REGISTRY.setdefault(family, []).append(segmenter)
    return segmenter


def for_family(family=None) -> list:
    """The `ANY` segmenters, then the family's own."""
    _load()
    fam = str(family or "").strip().lower()
    return list(REGISTRY.get(ANY, [])) + (list(REGISTRY.get(fam, [])) if fam and fam != ANY else [])


_loaded = False


def _load():
    global _loaded
    if not _loaded:
        _loaded = True
        import cheque_segmenter  # noqa: F401
