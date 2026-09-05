"""
The five shapes the gold corpus cannot see, scored.

`tests/gold/labels/` measures how well the engine does the things it already
did. These measure whether it does five things at all — four of them named by
the defect analysis, one of them the product's own core use case. See
`tests/harness/scenarios.py` for why they are scored separately rather than
folded into the headline accuracy number.

Model answers come from the recorded cache, so these run offline and for free.
That makes them a regression test on the PIPELINE, not a live measurement of
the model: they will catch the engine losing a row, misplacing a value or
inventing a cell, and they will not notice the model getting better or worse.
Re-record with `--mode record` when a prompt changes.

One scenario is expected to fail and is marked `known_bug` AND
`xfail(strict=True)`: `selection_no_marker_in_text`, where a selection state
that is not in the text layer at all is invented at high confidence. Strict
xfail is chosen over a plain failure so the default suite stays green AND the
marker cannot go stale — the day the fix lands, the unexpected pass is reported
as a FAILURE and forces the marker off. That is exactly how `multi_document`
came off this list.
"""
import json
import tempfile

import pytest

from tests.harness import bootstrap as _bs

_bs.bootstrap()

from tests.harness import scenarios as S  # noqa: E402


def _orchestrator():
    from connectors.llm_router import LLMRouter
    return type("O", (), {"llm": LLMRouter()})()


@pytest.fixture(scope="module")
def results(replay_cache):
    """Every scenario, run once, from the recorded cache."""
    import contextlib
    import io

    _bs.chdir_backend()
    tmp = tempfile.mkdtemp()
    orch = _orchestrator()
    out = {}
    for sc in S.load():
        replay_cache.context = sc["name"]
        with contextlib.redirect_stdout(io.StringIO()):
            out[sc["name"]] = (sc, S.run(sc, tmp, orch))
    return out


def _report(sc, ed):
    pct, checks = S.score(sc, ed)
    misses = [f"{w}: want {e!r} got {g!r}" for w, e, g, ok in checks if not ok]
    return pct, misses


class TestGroupedRowsInOneBand:
    """D1/D2's trigger: group headers, line items, section totals and the
    grand total in ONE band. No gold template has this shape, and it is the
    shape of nearly every financial document."""

    def test_every_figure_is_right(self, results):
        sc, ed = results["grouped_one_band"]
        pct, misses = _report(sc, ed)
        assert pct == 100.0, misses

    def test_the_structure_rows_are_not_discarded(self, results):
        """D2 said totals and group headers are dropped, leaving a reviewer
        unable to check any figure against its subtotal."""
        sc, ed = results["grouped_one_band"]
        for what, ok, detail in S.extras(sc, ed):
            assert ok, what

    def test_nothing_was_dropped_or_misplaced(self, results):
        _sc, ed = results["grouped_one_band"]
        assert ed["validation"]["dropped_row_count"] == 0
        assert ed["validation"]["misplaced_count"] == 0


class TestWrappedCellValues:
    def test_every_figure_is_right(self, results):
        sc, ed = results["wrapped_values"]
        pct, misses = _report(sc, ed)
        assert pct == 100.0, misses

    def test_a_multi_line_record_is_confident_as_well_as_correct(self, results):
        """A W-2 lays each employee across four printed lines and the model
        quotes the first two, so the values on the others used to be reported
        ungrounded — correct, and marked low. A record is not a line: cells are
        now checked against the lines between this row's and the next row's,
        which cannot reach into a neighbouring record."""
        _sc, ed = results["wrapped_values"]
        assert ed["validation"]["ungrounded_count"] == 0
        assert ed["needs_review"] is False
        assert all(r["_confidence"] == "high" for r in ed["W2_rows"])


class TestSelectionMarkersPrintedInTheText:
    """A form whose ticked and unticked boxes are both in the text layer as
    `[X]` / `[ ]`."""

    def test_the_selected_option_is_the_one_reported(self, results):
        sc, ed = results["selection_markers"]
        pct, misses = _report(sc, ed)
        assert pct == 100.0, misses

    def test_no_unselected_option_is_reported_as_fact(self, results):
        """D7's core claim. An unselected option's text IS on the page, so it
        grounds perfectly — nothing but reading the marker can reject it."""
        sc, ed = results["selection_markers"]
        for what, ok, _detail in S.extras(sc, ed):
            assert ok, what


class TestARealFillableForm:
    """`FORM-CT3-FILLABLE.pdf` — checkboxes that are WIDGET ANNOTATIONS.

    A widget carries no text, so the text layer shows every option and no
    marker at all: the selection state, which is the entire content of the
    field, never reached the model. It invented one for every option field at
    `high` confidence and answered "Services" where the form says "Wholesale
    trade".

    The state was in the file the whole time, in the widget's `/AS`. It is now
    read and written into the text as `[X]` / `[ ]` — the same shape a form
    that PRINTS its boxes gives, which the model already reads correctly.

    Zero of the 60 corpus PDFs carry AcroForm fields, so the fixture is built
    by `tests/fixtures/make_fillable_form.py`.
    """

    def test_every_field_is_right_including_all_four_choices(self, results):
        sc, ed = results["selection_acroform"]
        pct, misses = _report(sc, ed)
        assert pct == 100.0, misses

    def test_not_one_unselected_option_is_reported_as_a_value(self, results):
        sc, ed = results["selection_acroform"]
        for what, ok, detail in S.extras(sc, ed):
            assert ok, f"{what} — got {detail}"

    def test_the_state_is_recovered_from_the_file_not_guessed(self, repo_dir):
        """Deterministic, and the reason this one is a fix rather than a
        mitigation: it reads the answer out of the PDF."""
        from text_layer import acroform_widgets
        widgets = acroform_widgets(
            repo_dir / "tests/fixtures/FORM-CT3-FILLABLE.pdf")
        assert sum(len(v) for v in widgets.values()) == 12
        assert sum(1 for v in widgets.values() for w in v if w["on"]) == 4

    def test_the_markers_land_in_the_text(self, repo_dir):
        import pdfplumber
        from text_layer import acroform_widgets, read_page
        path = repo_dir / "tests/fixtures/FORM-CT3-FILLABLE.pdf"
        widgets = acroform_widgets(path)
        with pdfplumber.open(path) as pdf:
            text, _lines, _r = read_page(pdf.pages[0], widgets.get(0) or [])
        assert "[X] Limited liability company" in text
        assert "[ ] Sole proprietor" in text
        assert "[X] Wholesale trade" in text


@pytest.mark.known_bug
@pytest.mark.xfail(strict=True, reason="a selection state that is in NEITHER "
                                       "the text nor a form widget cannot be "
                                       "recovered; the prompt rule is a "
                                       "mitigation, not a guarantee")
class TestSelectionStateInNeitherTextNorWidget:
    """EXPECTED TO FAIL — the residual, and it is a real one.

    A form that neither prints its markers nor stores them as widgets — a
    flattened or scanned one, where the tick is vector graphics — has put the
    selection state somewhere nothing here reads. Every option is printed and
    grounds perfectly, so any answer passes every check.

    A prompt rule ("a line offering several options and marking none has no
    answer") took this fixture from 3/7 cells to 6/7 and costs nothing
    elsewhere — the gold harness is unchanged and no-template improved. But a
    prompt rule is a request, not a guarantee: `Accounting method` still comes
    back "Accrual" out of "Accrual Cash". The deterministic fix would be to
    read ticks out of the page's vector graphics, which is a different piece of
    work.
    """

    def test_it_does_not_invent_a_selection(self, results):
        sc, ed = results["selection_no_marker_in_text"]
        for what, ok, detail in S.extras(sc, ed):
            assert ok, f"{what} — got {detail}"


class TestNoInventionAndSemanticMatchingTogether:
    """The same mechanism pointing both ways, in one document — the case the
    defect analysis flags as untested."""

    def test_a_differently_worded_label_is_still_matched(self, results):
        """The template says Shipping; the document says Freight. Flexible
        matching is what makes one template work across form variants."""
        _sc, ed = results["no_invention_vs_semantic_match"]
        got = (ed["extracted_data"].get("Shipping") or {}).get("value", "")
        assert got.replace(",", "").endswith("480.00"), got

    def test_an_absent_field_is_not_filled_from_a_plausible_neighbour(
            self, results):
        """The page carries a Subtotal, a Freight, a Tax of $0.00 and a Total.
        Any of them would look entirely reasonable in Discount, Deposit Paid
        or Retainage, none of which the document has."""
        sc, ed = results["no_invention_vs_semantic_match"]
        for what, ok, detail in S.extras(sc, ed):
            assert ok, f"{what} — got {detail}"

    def test_the_unanswered_slots_are_reported(self, results):
        _sc, ed = results["no_invention_vs_semantic_match"]
        assert any("returned no value" in n for n in ed["validation_notes"])


class TestSeveralDocumentsInOneFile:
    """The core use case. Three invoices in one PDF.

    One file was one document unconditionally: 13 field slots where 3 x 13 were
    needed, one slot addressed "Invoice Number" against three distinct invoice
    numbers, and the two the model did not answer for were lost with no error
    and no note. This scenario runs through `run_extraction` (`via: pipeline`)
    rather than calling slot extraction directly, because the split happens
    before slot extraction and nothing else would exercise it.
    """

    def test_the_file_is_read_as_three_documents(self, results):
        _sc, ed = results["multi_document"]
        assert isinstance(ed, list) and len(ed) == 3

    def test_every_document_in_the_file_is_represented(self, results):
        sc, ed = results["multi_document"]
        for what, ok, detail in S.extras(sc, ed):
            assert ok, f"{what} — found only [{detail}]"

    def test_each_one_says_which_pages_it_came_from(self, results):
        _sc, ed = results["multi_document"]
        assert [d["document_index"] for d in ed] == [1, 2, 3]
        assert all(d["document_count"] == 3 for d in ed)
        assert [d["source_pages"] for d in ed] == [[1, 1], [2, 2], [3, 3]]

    def test_the_invoice_numbers_are_all_different(self, results):
        """The failure this replaces returned ONE invoice number three times
        over, or once and nothing else."""
        _sc, ed = results["multi_document"]
        got = [(d["extracted_data"].get("Invoice Number") or {}).get("value")
               for d in ed]
        assert len(set(got)) == 3, got


class TestTheScenariosThemselves:
    def test_all_seven_are_present(self):
        assert {s["name"] for s in S.load()} == {
            "grouped_one_band", "wrapped_values", "selection_markers",
            "selection_acroform", "selection_no_marker_in_text",
            "no_invention_vs_semantic_match", "multi_document"}

    def test_each_one_says_what_it_is_for(self):
        for s in S.load():
            assert len(s.get("what", "")) > 80, s["name"]
