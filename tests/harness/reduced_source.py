# -*- coding: utf-8 -*-
"""A deliberately capability-poor PageSource, for validating the reader seam.

docs/OCR-READER-SEAM-DESIGN.md §9. The seam cannot be tested by the reader it
already has, and testing it with OCR first would confound two unknowns — is the
seam right, and does OCR meet it. So the first second reader is a pdfplumber
one with capabilities REMOVED:

    no CHARACTER_GEOMETRY        -> it cannot see overprints
    no SIZE_AWARE_TOKENISATION   -> it cannot perform the two-pass shard diff

That is the capability profile an OCR source would have, without any of OCR's
uncertainty and without a new dependency. Its words are still pdfplumber's, so
every other number it produces must match the default reader EXACTLY — which is
what makes a difference anywhere else a bug in the seam rather than a property
of the reader.

⚠ NOT a production reader and not an OCR simulator. It reads the same text
layer; it simply declines to declare what it can do with it.
"""
from __future__ import annotations

from tests.harness import bootstrap as bs

bs.bootstrap()

from text_layer import (Capability, CoordinateSpace,  # noqa: E402
                        PageSource)


class ReducedPdfplumberSource(PageSource):
    """pdfplumber's words, declared as a reader that can do neither check."""

    #: Empty on purpose. Every capability-gated check must skip and say so.
    capabilities = frozenset()

    def __init__(self, page):
        self._page = page

    @property
    def page_number(self):
        return getattr(self._page, "page_number", None)

    @property
    def space(self):
        return CoordinateSpace(
            unit="pt", origin="top-left",
            height=float(getattr(self._page, "height", 0.0) or 0.0),
            width=float(getattr(self._page, "width", 0.0) or 0.0))

    def raw_text(self):
        return self._page.extract_text() or ""

    def words(self, size_aware=True):
        # `size_aware` is IGNORED — the reader does not have that ability, and
        # honouring it anyway is exactly the silent surrogate the design
        # forbids. It always returns its one and only segmentation.
        return self._page.extract_words()

    def chars(self):
        # Declaring no CHARACTER_GEOMETRY and then supplying characters would
        # let a caller work around the declaration. The declaration is the
        # contract.
        return []


class PixelSource(ReducedPdfplumberSource):
    """The same words, declared in PIXELS at 300dpi, to exercise §6.1.

    Used to prove the coordinate declaration does real work: the words are
    pdfplumber points multiplied by 300/72, declared as pixels, and the seam
    must divide them back so every downstream tolerance lands where it did.
    A reader that got this wrong today would misalign silently.
    """

    DPI = 300.0

    @property
    def space(self):
        s = super().space
        return CoordinateSpace(unit="px", origin="top-left",
                               height=s.height * self.DPI / 72.0,
                               width=s.width * self.DPI / 72.0, dpi=self.DPI)

    def words(self, size_aware=True):
        k = self.DPI / 72.0
        out = []
        for w in self._page.extract_words():
            w = dict(w)
            for key in ("x0", "x1", "top", "bottom", "doctop"):
                if key in w:
                    w[key] = float(w[key]) * k
            out.append(w)
        return out


class FlippedSource(ReducedPdfplumberSource):
    """The same words, declared BOTTOM-LEFT origin, to exercise the mirror.

    The failure this guards against is worse than a unit error: a flipped
    origin mirrors the page, so a value near the top lands near the bottom on a
    line that genuinely exists, at a plausible x. It looks reasonable and is
    wrong.
    """

    @property
    def space(self):
        s = super().space
        return CoordinateSpace(unit="pt", origin="bottom-left",
                               height=s.height, width=s.width)

    def words(self, size_aware=True):
        h = float(getattr(self._page, "height", 0.0) or 0.0)
        out = []
        for w in self._page.extract_words():
            w = dict(w)
            top, bottom = float(w["top"]), float(w["bottom"])
            # express the same word in a y-up space
            w["top"], w["bottom"] = h - top, h - bottom
            w.pop("doctop", None)
            out.append(w)
        return out
