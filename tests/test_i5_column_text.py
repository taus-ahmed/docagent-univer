"""I5 mode 1 — a side-by-side block is not one sentence.

`text_from_lines` joins every word of a line with one space, so INV-2024-0047's
two note columns arrive as

    Payment Instructions Notes
    Wire: First National Bank of New York Balance due March 4, 2024. Late ...

Shape inference is asked to prefix a block's heading onto each field under it
(`shape_inference.py`, the "Bill To Company / Bill To Address" rule), and with
the columns thrown away it has to GUESS which of the two headings owns "Balance
due". It answered `Notes Balance Due`, which is right on this document; the
round-2 report records the same mechanism answering `Oncor Customer Charge`
from a sidebar callout, which is wrong on that one. The model is not choosing
badly — it is choosing without the evidence.

`column_text` is a SECOND rendering, for inference only. `doc_text_pages` is
what `verify_span` grounds against and what slot extraction is prompted with,
and rewriting that would change every span check and every cached answer in the
project.
"""
import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from text_layer import (COLUMN_MARK, column_text, column_text_pages,  # noqa: E402
                        read_page, text_from_lines)

PDF = bs.PDF_DIR / "INV-2024-0047.pdf"


@pytest.fixture(scope="module")
def page():
    import pdfplumber
    with pdfplumber.open(str(PDF)) as pdf:
        return read_page(pdf.pages[0])[1]


class TestTheNoteColumnsAreNotOneLine:
    def test_the_heading_line_keeps_its_two_headings_apart(self, page):
        line = column_text(page).split("\n")[19]
        assert line == f"Payment Instructions{COLUMN_MARK}Notes"

    def test_line_20_no_longer_flattens_notes_onto_payment_instructions(self, page):
        """The line the defect was read from."""
        flat = text_from_lines(page).split("\n")[20]
        col = column_text(page).split("\n")[20]
        assert flat == ("Wire: First National Bank of New York Balance due "
                        "March 4, 2024. Late payments subject to 1.5%")
        left, right = col.split(COLUMN_MARK)
        assert left == "Wire: First National Bank of New York"
        assert right.startswith("Balance due March 4, 2024.")

    def test_every_word_survives_the_split(self, page):
        """Nothing is added and nothing is dropped — only the join changes."""
        flat = text_from_lines(page).replace("\n", " ").split()
        col = column_text(page).replace(COLUMN_MARK, " ").replace("\n", " ").split()
        assert flat == col


class TestAPageWithNoGuttersIsUnchanged:
    """A document with no side-by-side blocks must be asked exactly what it was
    asked before, or every cached answer is invalidated for nothing."""

    def test_a_single_column_line_is_byte_identical(self):
        line = [{"text": "Invoice", "x0": 10.0, "x1": 40.0},
                {"text": "Number", "x0": 42.0, "x1": 80.0},
                {"text": "INV-1", "x0": 82.0, "x1": 110.0}]
        assert column_text([line]) == text_from_lines([line])
        assert COLUMN_MARK not in column_text([line])

    def test_no_geometry_falls_back_to_the_flat_text(self):
        texts, marked = column_text_pages([[], []], ["page one", "page two"])
        assert texts == ["page one", "page two"]
        assert marked == 0

    def test_no_lines_at_all_falls_back(self):
        texts, marked = column_text_pages([], ["only page"])
        assert texts == ["only page"]
        assert marked == 0


class TestTheGutterIsThePages:
    """A fixed threshold is already recorded in text_layer as a failure: 24pt
    read the Closing Disclosure's five-party contact matrix as one line."""

    def test_a_tight_matrix_is_not_one_column(self):
        # columns 12pt apart, words 2pt apart — a gutter by the page's own
        # scale, not by any constant.
        line = [{"text": "Ann", "x0": 0.0, "x1": 8.0},
                {"text": "Lee", "x0": 10.0, "x1": 18.0},
                {"text": "Sam", "x0": 30.0, "x1": 38.0},
                {"text": "Roe", "x0": 40.0, "x1": 48.0}]
        assert COLUMN_MARK in column_text([line, line, line])


class TestNotEveryGutterIsABlockBoundary:
    """Measured, not assumed: marking every gutter marked 63% of the corpus's
    lines and cost the no-template harness 96.7% -> 95.2% with 10 misfilings.
    A label beside its own amount is one thing in two columns."""

    #: Ordinary prose lines, so the PAGE's median word gap is ~2pt and a 220pt
    #: gap is a gutter by the page's own scale — the same way a real page works.
    FILLER = [[{"text": w, "x0": 20.0 * i, "x1": 20.0 * i + 18.0}
               for i, w in enumerate(("Nexus", "Global", "Trading", "LLC",
                                      "New", "York"))]]

    LABEL_AND_AMOUNT = [{"text": "Opening", "x0": 0.0, "x1": 40.0},
                        {"text": "Balance", "x0": 42.0, "x1": 80.0},
                        {"text": "$184,320.55", "x0": 300.0, "x1": 380.0}]

    TWO_BLOCKS = [{"text": "Wire:", "x0": 0.0, "x1": 30.0},
                  {"text": "First", "x0": 32.0, "x1": 60.0},
                  {"text": "Balance", "x0": 300.0, "x1": 340.0},
                  {"text": "due", "x0": 342.0, "x1": 360.0}]

    def _page(self, line):
        return self.FILLER * 4 + [line]

    def test_a_label_beside_its_amount_is_not_split(self):
        assert COLUMN_MARK not in column_text(self._page(self.LABEL_AND_AMOUNT))

    def test_two_runs_of_prose_are_split(self):
        assert COLUMN_MARK in column_text(self._page(self.TWO_BLOCKS))

    def test_the_blunt_rule_would_have_split_both(self):
        """The control for the narrowing: geometry alone cannot tell them
        apart, which is why the rule is about what the segments CONTAIN."""
        assert COLUMN_MARK in column_text(self._page(self.LABEL_AND_AMOUNT),
                                          prose_only=False)


class TestTheLabelProvenanceSidecar:
    """I5 mode 2 — where an inferred label is printed, WHERE it is printed.

    Recorded, never required. An inferred label does not have to be the
    document's own word: CLAUDE.md's naming policy takes the name from the
    canonical list when the page prints no label at all (a letterhead company
    name) and prefers the precise term when the printed one is ambiguous. Of
    2,858 inference labels in the recorded corpus 1,259 are not printed
    verbatim, and until this existed nothing could tell which of those were
    policy and which were contamination, because a label carried no location.
    """

    GRID = {"cells": {"0,0": {"value": "Closing Balance"},
                      "0,1": {"value": ""},
                      "1,0": {"value": "Relationship Manager"}},
            "colWidths": [120, 120], "merges": {}, "repeatRows": [],
            "regions": []}

    @staticmethod
    def _lines(*texts):
        return [[[{"text": w, "x0": 10.0 * i, "x1": 10.0 * i + 8.0, "page": 1}
                  for i, w in enumerate(t.split())] for t in texts]]

    def test_a_printed_label_carries_its_line_and_page(self):
        from extractor import _label_provenance
        prov = _label_provenance(self.GRID,
                                 self._lines("Closing Balance 125,357.26"))
        assert prov["A1"]["source"] == "Closing Balance 125,357.26"
        assert prov["A1"]["page"] == 1

    def test_a_label_the_page_does_not_print_has_no_entry(self):
        """Requires nothing, rejects nothing, renames nothing."""
        from extractor import _label_provenance
        prov = _label_provenance(self.GRID,
                                 self._lines("Closing Balance 125,357.26"))
        assert "A2" not in prov

    def test_no_geometry_means_no_claims(self):
        from extractor import _label_provenance
        assert _label_provenance(self.GRID, None) == {}

    def test_provenance_is_bound_to_the_document_not_the_schema(self):
        """The defect this nearly shipped with. A batch-reused schema is shared
        by every document of its kind, so provenance stored ON it handed the
        second statement the FIRST one's quoted lines."""
        from extractor import _with_label_provenance
        schema = {"inferred": {"fields": []}, "layout": self.GRID}
        one = _with_label_provenance(schema, self._lines("Closing Balance 1.00"))
        two = _with_label_provenance(schema, self._lines("Closing Balance 2.00"))
        assert one["inferred_label_provenance"]["A1"]["source"].endswith("1.00")
        assert two["inferred_label_provenance"]["A1"]["source"].endswith("2.00")
        assert "inferred_label_provenance" not in schema

    def test_a_user_template_gets_no_sidecar(self):
        """Only an INFERRED label needs one; a user's label is their own word
        by definition and was never the document's."""
        from extractor import _with_label_provenance
        td = {"layout": self.GRID}
        assert _with_label_provenance(td, self._lines("Closing Balance 1.00")) is td
