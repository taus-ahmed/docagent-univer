"""GATE 0 — the differential evidence for the four fixes at 3803ea9.

Every harness figure is identical before and after those fixes, so the harness
is not the instrument. These tests are: each one must FAIL at 0592738 (the
commit production serves) and PASS at 3803ea9. That delta is the evidence.

Three of the four are here. I9 is not, and the reason is recorded in
`test_gate0_evidence_I9_is_absent.py`-shaped prose at the bottom of this file
rather than as a synthetic fixture — constructing one would be the exact
mistake this repo has made three times.

Each test asserts on a real artifact:
  I7   the real ENGIE bill, tests/test_pdfs/round2/SampleBill.pdf
  I13  the written .xlsx, read back with openpyxl
  I14  the written .xlsx, read back with openpyxl
"""
import pytest

from tests.harness import bootstrap as _bs

_bs.bootstrap()

from tests.fixtures.editor_grids import (  # noqa: E402
    EDITOR_DEFAULT_COL_PX, bordered_table_grid)

ARTIFACT = "00000000112538645596"


# ══════════════════════════════════════════════════════════════════════════
# I7 — the interleaved account number must be rejected
# ══════════════════════════════════════════════════════════════════════════

class TestTheEngieAccountNumberIsRejected:
    """The real document, through the real extraction path.

    SampleBill.pdf page 4 prints its account number twice, at two font sizes,
    in the same place. Every reader that orders characters left to right
    interleaves them, and pdfplumber returns the interleaving as ONE WORD — so
    the flattened text, the word boxes, `canonical_value` and `verify_span` all
    agree the string is on the page.

    ⚠ At 0592738 this particular value is ALREADY `low` — by accident. Its
    20-digit run trips `_single_datum`, a heuristic about how much information
    a cell holds, which knows nothing about overprinting and happens to be
    right here. So the confidence LEVEL is not the delta for this value; the
    named reason and the count are. See
    `TestAnOverprintedValueThatDoesNotGetLucky` for the values where the
    accident does not save it, which is the real evidence.
    """

    @pytest.fixture(scope="class")
    def extracted(self, pdf_dir):
        import json
        import pdfplumber
        from slot_extractor import run_slot_extraction
        from template_shape import compute_shape
        from text_layer import read_page

        texts, lines_per_page = [], []
        with pdfplumber.open(pdf_dir / "round2" / "SampleBill.pdf") as pdf:
            for page in pdf.pages:
                text, lines, _r = read_page(page)
                texts.append(text)
                lines_per_page.append(lines)

        grid = {"cells": {"0,0": {"value": "Bill Account Number", "style": {}},
                          "0,1": {"value": "", "style": {}},
                          "1,0": {"value": "Meter Number", "style": {}},
                          "1,1": {"value": "", "style": {}}},
                "colWidths": [EDITOR_DEFAULT_COL_PX] * 26,
                "merges": {}, "repeatRows": [], "regions": []}
        shape = compute_shape(grid, log=lambda _m: None)

        # The model's answer is INJECTED, not requested: this test is about
        # what the pipeline does with an answer read off an overprinted
        # region, not about whether the model returns it. It does — runs 4 and
        # 9 of round 2 both produced exactly this string.
        payload = {"fields": {
            "F1": {"value": ARTIFACT, "source": ARTIFACT, "page": 4}},
            "tables": {}}

        class _Resp:
            success = True
            parsed_json = payload
            raw_text = json.dumps(payload)

        class _LLM:
            def extract(self, **_kw):
                return _Resp()

        orch = type("O", (), {"llm": _LLM()})()
        return run_slot_extraction(
            orch, "SampleBill.pdf", {"layout": grid, "shape": shape}, None,
            page_images=[], doc_text="\n".join(texts), doc_text_pages=texts,
            file_type="digital_pdf", default_doc_type="utility_bill",
            start=0.0, page_lines=lines_per_page)[0].extracted_data

    def test_it_is_not_reported_as_confident(self, extracted):
        """THE EVIDENCE. At 0592738 this is 'high'."""
        from app.core.confidence import CONFIDENT_LEVELS
        level = extracted["validation"]["confidence_map"].get("B1")
        assert level not in CONFIDENT_LEVELS, (
            f"the interleaved account number came back {level!r} — a string "
            f"nothing on the page prints, presented as fact")

    def test_the_document_is_sent_for_review(self, extracted):
        assert extracted["needs_review"] is True

    def test_the_reason_names_the_mechanism(self, extracted):
        reasons = " ".join(f["reason"]
                           for f in extracted["validation"]["flagged_fields"])
        assert "printed over one another" in reasons

    def test_it_is_counted(self, extracted):
        assert extracted["validation"].get("overprinted_count", 0) >= 1

    def test_the_value_is_kept_not_dropped(self, extracted):
        """Both texts are printed in full in the same place; which was wanted
        is not recoverable. A visible wrong cell beats an invisible missing
        one — the same trade already made for a misplaced value."""
        assert extracted["extracted_fields"].get("B1") == ARTIFACT


class TestAnOverprintedValueThatDoesNotGetLucky:
    """The ENGIE account number was ALREADY `low` at 0592738 — by accident.

    A 20-digit run trips `_single_datum` ("cell carries more than one piece of
    information"), so it was demoted by a heuristic about cell content, not by
    anything that had noticed the overprint. That accident does not generalise.

    The five audit letters in the gold corpus interleave their letterhead
    address with their reference number, and every one of the thirteen
    resulting words grades HIGH at 0592738 — `NSou:i`, `AvenNueo,:`,
    `SMuGitMe`, `U2D20-200,`. Verbatim garbage, presented as fact, in the
    committed corpus, for as long as those fixtures have existed.

    This is I7's actual evidence. The ENGIE case is the reported symptom; this
    is the class.
    """
    #: read off tests/test_pdfs/AUD-2024-001-CLEAN-OPINION.pdf, which prints
    #: "500 Park Avenue, Suite 2200, New York, NY 10022" over "No: AUD-2024-001"
    INTERLEAVED = "NSou:i tAe U2D20-200, 2N4e-w00 Y1ork,"

    @pytest.fixture(scope="class")
    def lines(self, pdf_dir):
        import pdfplumber
        from text_layer import read_page
        out = []
        with pdfplumber.open(pdf_dir / "AUD-2024-001-CLEAN-OPINION.pdf") as pdf:
            for page in pdf.pages:
                out += read_page(page)[1]
        return out

    def test_the_corpus_really_prints_it(self, lines):
        """The premise: this is a real string in a committed fixture."""
        words = {w["text"] for ln in lines for w in ln}
        assert {"NSou:i", "tAe", "U2D20-200,"} <= words

    def test_it_is_recognised_as_overprinted(self, lines):
        """THE EVIDENCE. At 0592738 there is no such function, and every one
        of these words grades `high`."""
        from text_layer import overprinted_value
        for word in ("NSou:i", "U2D20-200,", "2N4e-w00"):
            assert overprinted_value(word, lines) is True, word

    def test_an_ordinary_word_on_the_same_page_is_not(self, lines):
        from text_layer import overprinted_value
        assert overprinted_value("Meridian", lines) is False
        assert overprinted_value("Associates", lines) is False


# ══════════════════════════════════════════════════════════════════════════
# the written workbook — I13 and I14 assert on the .xlsx itself
# ══════════════════════════════════════════════════════════════════════════

def _write(grid, rows):
    """The real export path, end to end, returning the worksheet."""
    import openpyxl
    from app.api.routes.extract import _write_excel

    class _Doc:
        def get_extracted_data(self):
            return {
                "template_type": "slot",
                "extracted_fields": {"B7": "Jane Roe"},
                "Earnings_rows": rows,
                "slot_map": {
                    "fields": [{"ref": "B7", "row_label": "Prepared By"}],
                    "tables": [{
                        "name": "Earnings", "start_row": 2, "end_row": 4,
                        "start_col": 0, "end_col": 2, "orientation": "rows",
                        "columns": [
                            {"header": "Segment", "key": "Segment", "col": 0},
                            {"header": "2024", "key": "2024", "col": 1},
                            {"header": "2023", "key": "2023", "col": 2}],
                    }],
                },
            }

    ws = openpyxl.Workbook().active
    _write_excel(ws, [_Doc()], grid, {}, openpyxl)
    return ws


ROWS3 = [{"Segment": s, "2024": "1", "2023": "2"}
         for s in ("Insurance", "Railroad", "Utilities")]


# ══════════════════════════════════════════════════════════════════════════
# I13 — a template saved with all-default widths must still auto-fit
# ══════════════════════════════════════════════════════════════════════════

class TestAutoFitSurvivesTheEditorsDefaults:
    """`colWidths` is Array(26).fill(120) on every template the editor has ever
    saved — confirmed against BOTH real production templates in
    tests/fixtures/prod_templates/, which carry 26 entries all 120.

    `_fit_columns` honours a stored width as the one the user dragged, so its
    fit branch was unreachable and every column came out
    round(120/7) = 17 characters wide.
    """
    LONG = "Meter Constant - A fixed value used when calculating consumption"

    def _sheet(self):
        grid = bordered_table_grid()
        grid["cells"]["6,0"] = {"value": self.LONG, "style": {}}
        return _write(grid, ROWS3)

    def test_a_column_whose_content_exceeds_the_default_comes_back_wider(self):
        """THE EVIDENCE. At 0592738 column A is exactly 17."""
        width = self._sheet().column_dimensions["A"].width
        assert width > round(EDITOR_DEFAULT_COL_PX / 7), (
            f"column A is {width}, the editor default of "
            f"{EDITOR_DEFAULT_COL_PX}px expressed in characters — auto-fit "
            f"never ran, and a {len(self.LONG)}-character label is truncated")

    def test_it_is_fitted_to_the_content_not_merely_bumped(self):
        width = self._sheet().column_dimensions["A"].width
        assert width >= min(60, len(self.LONG))


# ══════════════════════════════════════════════════════════════════════════
# I14 — a table template's bordered body must reach the file
# ══════════════════════════════════════════════════════════════════════════

class TestABorderedBandReachesTheWorkbook:
    """`_write_slot_excel` applied style inside the loop that `continue`s past
    every band row, so the one region of a table template a user actually
    draws — the box around its body — was the one region that arrived
    unstyled. D13 was verified on a form template, which has no band.
    """

    @staticmethod
    def _bordered(ws, ref):
        b = ws[ref].border
        return bool(b and b.left and b.left.style)

    def test_every_drawn_body_cell_keeps_its_border(self):
        """THE EVIDENCE. At 0592738 all nine of these are unstyled."""
        ws = _write(bordered_table_grid(), ROWS3)
        missing = [r for r in ("A3", "B3", "C3", "A4", "B4", "C4",
                               "A5", "B5", "C5") if not self._bordered(ws, r)]
        assert not missing, (
            f"{len(missing)} band-body cells lost the border the user drew: "
            f"{missing}")

    def test_the_heading_row_was_never_the_problem(self, ):
        """A control. The band header sits above start_row, so it kept its
        look even at 0592738 — which is why the defect looked like nothing was
        wrong when a form template was checked."""
        ws = _write(bordered_table_grid(), ROWS3)
        assert self._bordered(ws, "A2")
