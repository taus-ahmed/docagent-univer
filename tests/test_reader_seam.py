# -*- coding: utf-8 -*-
"""The reader seam: capability gating, coordinate declarations, compatibility.

`read_page` used to BE the pdfplumber reader — it called `extract_text()`,
`extract_words(extra_attrs=…)`, `page.chars` and `page.page_number` directly, so
there was no interface a second reader could implement
(docs/OCR-CONTRACT-SCOPING.md). The seam below it is built to
docs/OCR-READER-SEAM-DESIGN.md.

These tests pin what the design's §9 validation showed by hand. The distinction
they exist to protect is one the engine could not previously express:

    "this page is clean"          a check ran and found nothing
    "this reader cannot check"    the check never ran

Collapsing the second into the first is the silent degradation the whole seam
exists to prevent, and nothing but these tests would notice it coming back.

⚠ The reduced-capability reader lives in `tests/harness/reduced_source.py`. It
reads the SAME pdfplumber text layer and simply declines to declare what it can
do with it, so any difference it produces outside the two gated checks is a bug
in the seam rather than a property of a reader.
"""
import pytest

from tests.harness import bootstrap as _bs

_bs.bootstrap()
_bs.chdir_backend()

from text_layer import (Capability, CoordinateSpace,  # noqa: E402
                        CoordinateSpaceError, EDGE_TOL, PageSource,
                        PdfplumberSource, SHARD_SHRED, normalise_words,
                        read_page)

from tests.harness.reduced_source import (FlippedSource,  # noqa: E402
                                          PixelSource,
                                          ReducedPdfplumberSource)

HTR = "round2/HTR-043235.pdf"
CHQ = "CHQ-001847.pdf"

#: Measured 2026-09-18 at the seam commit. HTR page 3 is the corpus's one
#: genuinely shredded page (DECISION-LOG §21); page 2 is the same damage,
#: milder. These are the numbers the size-aware reading has produced since I10
#: and they must not move when a reader is added.
HTR_SHARD = {1: 0.9779735682819384, 2: 1.1400375939849625,
             3: 2.5126682501979416, 4: 1.0}
HTR_MARKED = {1: 0, 2: 260, 3: 2647, 4: 0}


#: pdfplumber pages are views on an OPEN file — abandoning the handle makes
#: every later `extract_words()` raise "seek of closed file". These fixtures
#: therefore hold the document open for the module rather than yielding a page
#: out of a `with` block.
@pytest.fixture(scope="module")
def _open_pdf(pdf_dir):
    import contextlib
    import pdfplumber
    stack = contextlib.ExitStack()

    def _open(name):
        return stack.enter_context(pdfplumber.open(pdf_dir / name))

    try:
        yield _open
    finally:
        stack.close()


@pytest.fixture(scope="module")
def htr_pages(_open_pdf):
    return list(_open_pdf(HTR).pages)


@pytest.fixture(scope="module")
def chq_page(_open_pdf):
    return _open_pdf(CHQ).pages[0]


@pytest.fixture(scope="module")
def htr_full(htr_pages):
    """(stats, lines) per 1-based page, read by the DEFAULT reader."""
    out = {}
    for i, page in enumerate(htr_pages, 1):
        stats = {}
        _text, lines, _r = read_page(PdfplumberSource(page), stats=stats)
        out[i] = (stats, lines)
    return out


@pytest.fixture(scope="module")
def htr_reduced(htr_pages):
    """The same pages read by a reader declaring NO capabilities."""
    out = {}
    for i, page in enumerate(htr_pages, 1):
        stats = {}
        _text, lines, _r = read_page(ReducedPdfplumberSource(page), stats=stats)
        out[i] = (stats, lines)
    return out


def _marked(lines):
    return sum(1 for ln in lines for w in ln if w.get("overprinted"))


# ══════════════════════════════════════════════════════════════════════════
# 1. THE CAPABILITY PROBE
# ══════════════════════════════════════════════════════════════════════════

class TestSizeAwareTokenisationGatesTheShardRatio:
    """`shard_ratio` is the ratio between two tokenisations of ONE page by ONE
    reader. A reader that segments once cannot produce it — it is a mechanism,
    not a field (OCR-CONTRACT-SCOPING §2.5)."""

    def test_the_default_reader_declares_it(self, chq_page):
        page = chq_page
        assert PdfplumberSource(page).can(Capability.SIZE_AWARE_TOKENISATION)

    def test_the_reduced_reader_does_not(self, chq_page):
        page = chq_page
        assert not ReducedPdfplumberSource(page).can(
            Capability.SIZE_AWARE_TOKENISATION)

    @pytest.mark.parametrize("page_no", [1, 2, 3, 4])
    def test_with_the_capability_the_real_ratio_is_unchanged(self, htr_full,
                                                             page_no):
        """THE VALUES DO NOT MOVE. Adding a seam must not change what the
        existing reader measures."""
        stats, _lines = htr_full[page_no]
        assert stats["shard_ratio"] == pytest.approx(HTR_SHARD[page_no],
                                                     rel=1e-9)

    def test_a_gold_document_still_reads_exactly_1_0(self, chq_page):
        """A clean page scores exactly 1.0 — the two readings agree token for
        token. Pinned so that "not run" can never be mistaken for it."""
        stats = {}
        read_page(PdfplumberSource(chq_page), stats=stats)
        assert stats["shard_ratio"] == 1.0

    @pytest.mark.parametrize("page_no", [1, 2, 3, 4])
    def test_without_the_capability_the_ratio_is_ABSENT_not_1_0(
            self, htr_reduced, page_no):
        """NOT-RUN is not a clean score. 1.0 is what a clean page reads, so
        defaulting to it would report every page of an unreadable document as
        perfect."""
        stats, _lines = htr_reduced[page_no]
        assert "shard_ratio" not in stats
        assert stats["shard_checked"] is False

    def test_the_shredded_pages_are_found_only_by_the_capable_reader(
            self, htr_full, htr_reduced):
        shredded_full = [p for p in (1, 2, 3, 4)
                         if htr_full[p][0]["shard_ratio"] >= SHARD_SHRED]
        assert shredded_full == [2, 3]
        for p in (1, 2, 3, 4):
            assert "shard_ratio" not in htr_reduced[p][0]


class TestTheDocumentRecordsWhichPagesWereNotChecked:
    """End to end: `read_page` stats -> ProcessedDocument -> the two lists."""

    @pytest.fixture(scope="class")
    def docs(self, pdf_dir):
        import text_layer
        from core.preprocessor import preprocess_file

        path = str(pdf_dir / HTR)
        full = preprocess_file(path)

        original = text_layer.as_page_source
        text_layer.as_page_source = lambda p: (
            p if isinstance(p, PageSource) else ReducedPdfplumberSource(p))
        try:
            reduced = preprocess_file(path)
        finally:
            text_layer.as_page_source = original
        return full, reduced

    def test_the_capable_reader_finds_the_shredded_pages(self, docs):
        full, _reduced = docs
        assert full.shredded_pages == [2, 3]

    def test_the_capable_reader_leaves_both_unchecked_lists_empty(self, docs):
        """An empty list means EVERY page was checked — which is what makes
        the field safe to read on documents processed before it existed."""
        full, _reduced = docs
        assert full.unchecked_shred_pages == []
        assert full.unchecked_overprint_pages == []

    def test_the_reduced_reader_reports_no_shredded_pages(self, docs):
        """Not a finding of cleanliness: it could not look."""
        _full, reduced = docs
        assert reduced.shredded_pages == []

    def test_the_reduced_reader_records_every_page_as_unchecked(self, docs):
        _full, reduced = docs
        assert reduced.unchecked_shred_pages == [1, 2, 3, 4]

    def test_the_pages_that_really_are_shredded_are_in_the_unchecked_list(
            self, docs):
        """The point of the record. Pages 2 and 3 ARE damaged; a reader that
        cannot see that must say so rather than stay silent."""
        _full, reduced = docs
        assert 2 in reduced.unchecked_shred_pages
        assert 3 in reduced.unchecked_shred_pages


# ══════════════════════════════════════════════════════════════════════════
# 2. unchecked_overprint_pages
# ══════════════════════════════════════════════════════════════════════════

class TestCharacterGeometryGatesOverprintDetection:
    def test_the_default_reader_declares_it(self, chq_page):
        page = chq_page
        assert PdfplumberSource(page).can(Capability.CHARACTER_GEOMETRY)

    def test_the_reduced_reader_does_not(self, chq_page):
        page = chq_page
        assert not ReducedPdfplumberSource(page).can(
            Capability.CHARACTER_GEOMETRY)

    @pytest.mark.parametrize("page_no", [1, 2, 3, 4])
    def test_the_capable_reader_marks_the_same_words_as_before(
            self, htr_full, page_no):
        """44% of this document carries the flag (2,907 of 6,659 words) and it
        is what demotes those values to `low`. The numbers must not move."""
        _stats, lines = htr_full[page_no]
        assert _marked(lines) == HTR_MARKED[page_no]

    def test_the_capable_reader_does_not_record_the_check_as_skipped(
            self, htr_full):
        for page_no in (1, 2, 3, 4):
            assert "overprint_checked" not in htr_full[page_no][0]

    @pytest.mark.parametrize("page_no", [1, 2, 3, 4])
    def test_the_reduced_reader_marks_nothing_and_says_so(self, htr_reduced,
                                                          page_no):
        stats, lines = htr_reduced[page_no]
        assert _marked(lines) == 0
        assert stats["overprint_checked"] is False

    def test_the_reduced_reader_lists_every_page_it_could_not_check(self, docs_):
        reduced = docs_
        assert reduced.unchecked_overprint_pages == [1, 2, 3, 4]

    def test_the_pages_carrying_real_overprints_are_in_that_list(self, docs_):
        """Pages 2 and 3 carry 260 and 2,647 marked words under the capable
        reader. Under the reduced one they are not clean — they are unchecked,
        and the list is where that is said."""
        reduced = docs_
        assert 2 in reduced.unchecked_overprint_pages
        assert 3 in reduced.unchecked_overprint_pages

    @pytest.fixture(scope="class")
    def docs_(self, pdf_dir):
        import text_layer
        from core.preprocessor import preprocess_file

        original = text_layer.as_page_source
        text_layer.as_page_source = lambda p: (
            p if isinstance(p, PageSource) else ReducedPdfplumberSource(p))
        try:
            return preprocess_file(str(pdf_dir / HTR))
        finally:
            text_layer.as_page_source = original


# ══════════════════════════════════════════════════════════════════════════
# 3. COORDINATE ROUND-TRIPS
# ══════════════════════════════════════════════════════════════════════════

class TestAReadersCoordinatesAreNormalisedToTheEnginesSpace:
    """Every tolerance in `text_layer` is a bare inequality in POINTS from the
    top of the page, so a reader in another space misaligns quietly. The seam
    converts once, at the boundary."""

    KEYS = ("x0", "x1", "top", "bottom")

    def _coords(self, lines):
        return [(w["text"], k, float(w[k])) for ln in lines for w in ln
                for k in self.KEYS if k in w]

    @pytest.fixture(scope="class")
    def three_readings(self, chq_page):
        page = chq_page
        base = read_page(ReducedPdfplumberSource(page))[1]
        pixels = read_page(PixelSource(page))[1]
        flipped = read_page(FlippedSource(page))[1]
        return base, pixels, flipped

    def test_the_readings_cover_the_same_words(self, three_readings):
        base, pixels, flipped = three_readings
        assert len(self._coords(base)) == len(self._coords(pixels))
        assert len(self._coords(base)) == len(self._coords(flipped))
        assert len(self._coords(base)) > 100

    def test_a_pixel_reader_lands_inside_EDGE_TOL(self, three_readings):
        """EDGE_TOL is the tightest bound in the engine — 1.0pt, guarding
        `repair_wrapped`, the one place coordinate noise rewrites a VALUE."""
        base, pixels, _flipped = three_readings
        worst = max(abs(b[2] - p[2])
                    for b, p in zip(self._coords(base), self._coords(pixels)))
        assert worst <= EDGE_TOL

    def test_the_pixel_round_trip_is_float_noise_not_approximation(
            self, three_readings):
        """Measured at 1.14e-13 pt. Asserted a thousand times looser than that
        and still twelve orders inside EDGE_TOL, so this pins "exact
        conversion" rather than "close enough"."""
        base, pixels, _flipped = three_readings
        worst = max(abs(b[2] - p[2])
                    for b, p in zip(self._coords(base), self._coords(pixels)))
        assert worst < 1e-9

    def test_a_bottom_left_reader_lands_inside_EDGE_TOL(self, three_readings):
        """An origin mismatch MIRRORS the page — a value near the top lands
        near the bottom, on a line that genuinely exists, at a plausible x. It
        looks more reasonable than a unit error and is just as wrong."""
        base, _pixels, flipped = three_readings
        worst = max(abs(b[2] - f[2])
                    for b, f in zip(self._coords(base), self._coords(flipped)))
        assert worst <= EDGE_TOL

    def test_the_flip_is_exact(self, three_readings):
        base, _pixels, flipped = three_readings
        assert self._coords(base) == self._coords(flipped)

    def test_the_default_reader_needs_no_conversion_at_all(self, chq_page):
        """A source already in the engine's space is returned untouched, so the
        pdfplumber path costs nothing and its floats stay bit-identical."""
        space = PdfplumberSource(chq_page).space
        assert space.is_engine_space
        words = [{"x0": 1.5, "x1": 2.5, "top": 3.5, "bottom": 4.5}]
        assert normalise_words(words, space)[0]["top"] == 3.5


# ══════════════════════════════════════════════════════════════════════════
# 4. THE BOUNDARY REFUSES WHAT IT CANNOT CONVERT — one case per test
# ══════════════════════════════════════════════════════════════════════════

class TestAnUnconvertibleDeclarationIsRefusedLoudly:
    """A failure here is a failure. It does not fall back to "assume points",
    because assuming is the bug — the same rule as the engine's refusal to wrap
    extraction in a bare `except`."""

    def test_pixels_without_a_dpi(self):
        space = CoordinateSpace(unit="px", origin="top-left", height=10,
                                width=10)
        with pytest.raises(CoordinateSpaceError) as e:
            normalise_words([], space)
        assert "dpi" in str(e.value)

    def test_an_unknown_unit(self):
        space = CoordinateSpace(unit="furlong", height=10, width=10)
        with pytest.raises(CoordinateSpaceError) as e:
            normalise_words([], space)
        assert "furlong" in str(e.value)
        assert "unit" in str(e.value)

    def test_an_unknown_origin(self):
        space = CoordinateSpace(origin="middle", height=10, width=10)
        with pytest.raises(CoordinateSpaceError) as e:
            normalise_words([], space)
        assert "middle" in str(e.value)
        assert "origin" in str(e.value)

    def test_a_bottom_left_origin_without_a_page_height(self):
        """The flip is `height - y`. Without a height there is nothing to
        subtract from, and a flip against a wrong height is off by a constant
        and equally silent."""
        space = CoordinateSpace(origin="bottom-left", height=0, width=10)
        with pytest.raises(CoordinateSpaceError) as e:
            normalise_words([], space)
        assert "height" in str(e.value)


# ══════════════════════════════════════════════════════════════════════════
# 5. BACKWARD COMPATIBILITY
# ══════════════════════════════════════════════════════════════════════════

class TestEveryExistingCallSiteKeepsWorking:
    """31 invocations pass a pdfplumber page positionally — 1 in production
    (core/preprocessor.py:164) and 30 across 16 test and harness files. All of
    them keep working unedited, because anything that is not already a
    PageSource is wrapped in the default one.

    Rewriting thirty test call sites in the same change as a structural
    refactor would have destroyed the evidence that tells us the refactor was
    safe, so this is a property of the design and not a convenience.
    """

    def test_the_one_argument_form(self, chq_page):
        page = chq_page
        got = read_page(page)
        assert isinstance(got, tuple) and len(got) == 3
        text, lines, repairs = got
        assert isinstance(text, str) and text.strip()
        assert isinstance(lines, list) and lines and isinstance(lines[0], list)
        assert isinstance(repairs, list)

    def test_the_three_argument_form_with_stats(self, chq_page):
        stats = {}
        text, lines, repairs = read_page(chq_page, [], stats=stats)
        assert isinstance(text, str) and text.strip()
        assert isinstance(lines, list) and lines
        assert isinstance(repairs, list)
        assert stats["shard_ratio"] == 1.0

    def test_a_raw_page_and_an_explicit_source_agree_exactly(self, chq_page):
        """The wrap is the identity: `read_page(page)` and
        `read_page(PdfplumberSource(page))` are the same call."""
        page = chq_page
        a_stats, b_stats = {}, {}
        a = read_page(page, stats=a_stats)
        b = read_page(PdfplumberSource(page), stats=b_stats)
        assert a[0] == b[0]
        assert [[w["text"] for w in ln] for ln in a[1]] == \
               [[w["text"] for w in ln] for ln in b[1]]
        assert a_stats == b_stats

    def test_words_still_carry_the_keys_the_engine_reads(self, chq_page):
        """text, x0, x1, top, bottom are required of every reader; `page` is
        stamped by the engine. `size` is capability-gated and `doctop`,
        `height`, `width`, `upright`, `direction` are pdfplumber passthroughs
        nothing reads."""
        word = read_page(chq_page)[1][0][0]
        for key in ("text", "x0", "x1", "top", "bottom", "page"):
            assert key in word, key
