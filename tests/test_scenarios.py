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

Two scenarios are expected to fail and are marked `known_bug` AND
`xfail(strict=True)`: `multi_document` (three invoices go in, one comes out,
nothing says so) and `selection_no_marker_in_text` (a selection state that is
not in the text layer is invented at high confidence). Strict xfail is chosen
over a plain failure so the default suite stays green AND the marker cannot go
stale — the day the fix lands, the unexpected pass is reported as a FAILURE and
forces the marker off.
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

    def test_a_partially_quoted_record_is_reported_not_hidden(self, results):
        """The residual limitation, pinned so it cannot quietly change: a
        record spanning several printed lines is verified against the ONE line
        the model quoted, so correct values on its other lines come back low.
        Conservative, not wrong — and it must stay conservative."""
        _sc, ed = results["wrapped_values"]
        assert ed["needs_review"] is True


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


@pytest.mark.known_bug
@pytest.mark.xfail(strict=True, reason="D7: selection state absent from the "
                                       "text layer is invented, at high confidence")
class TestSelectionStateAbsentFromTheTextLayer:
    """EXPECTED TO FAIL — this is D7's dangerous half, unfixed.

    A real AcroForm checkbox is a widget annotation carrying no text. The text
    layer shows every option and no marker, so the selection state is genuinely
    absent from what the model is given and the only honest answer is empty.
    Measured: it picks one anyway, at `high` confidence with
    `needs_review=False`, and on Principal business activity it picked
    "Services" where the form says "Wholesale trade".

    These are categorical fields that decide treatment — filing status, entity
    type, coverage tier. A wrong one is not a formatting problem.
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


@pytest.mark.known_bug
@pytest.mark.xfail(strict=True, reason="one file is one document: the other "
                                       "documents are lost silently")
class TestSeveralDocumentsInOneFile:
    """EXPECTED TO FAIL — the core use case, unfixed.

    Three invoices in one PDF. The template asks for one invoice number, the
    file holds three, the model returns one, and the other two are lost with
    no error, no flag and no note. `needs_review` is False and the document
    reports `high`.
    """

    def test_every_document_in_the_file_is_represented(self, results):
        sc, ed = results["multi_document"]
        for what, ok, detail in S.extras(sc, ed):
            assert ok, f"{what} — found only [{detail}]"


class TestTheScenariosThemselves:
    def test_all_six_are_present(self):
        assert {s["name"] for s in S.load()} == {
            "grouped_one_band", "wrapped_values", "selection_markers",
            "selection_no_marker_in_text", "no_invention_vs_semantic_match",
            "multi_document"}

    def test_each_one_says_what_it_is_for(self):
        for s in S.load():
            assert len(s.get("what", "")) > 80, s["name"]
