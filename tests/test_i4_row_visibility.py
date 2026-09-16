"""I4 — a row the engine drops is a row the reader is told about.

Three gates drop a table row. Two of them were made visible when they were
built; the third never was:

    region      slot_extractor.py:914   flag + counter + needs_review
    duplicate   slot_extractor.py:949   flag + counter + needs_review
    every schema cell empty  :1016      NOTHING

The third is I4. A row whose cells the band's column keys do not reach is
discarded at `if any(str(v).strip() for v in row.values())` with no flag, no
note, no counter and no review state — so a template that loses a section total
or a sub-header looks exactly like one that had none.

The cells are emptied one gate earlier, at :987, where `cells.get(h, "")` is an
EXACT lookup over the band's column keys: a key the model returned that the
template does not have is discarded on the floor, uncounted. That is the same
loss one level down, and it is what makes the drop depend on template shape —
same document, same answer, two templates, different row sets
(docs/DocAgent_round2_report.md, I4).

WHAT THE LIVE RUN FOUND (tests/harness/i4.py, 23 runs, 39 bands, 227 rows):
zero off-schema keys and zero silent drops, in every variant including 17
legitimately reworded bands. The model returns exactly the keys it is asked
for. So this is a LATENT defect, not an observed one — which is the argument
for making it loud rather than for guessing at it: nothing in the corpus would
tell us if it started happening.

The answers here are stubbed, not sampled, for that reason: the condition does
not occur in any recorded answer, so it has to be constructed to be pinned.
"""
import json

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from slot_extractor import run_slot_extraction  # noqa: E402
from template_shape import compute_shape  # noqa: E402

PAGE = ("ACME TRADING LTD — STATEMENT OF EARNINGS\n"
        "Date Description Qty Rate Amount\n"
        "2024-01-04 Widget assembly 2 50.00 100.00\n"
        "Net earnings includes:\n"
        "Subtotal 200.00\n")


def _grid(headers):
    """The grid the editor saves: a heading row, then a declared band."""
    return {"cells": {f"0,{c}": {"value": h, "style": {}}
                      for c, h in enumerate(headers)},
            "colWidths": [120] * 26, "merges": {}, "repeatRows": [],
            "regions": [{"type": "table", "r1": 0, "c1": 0, "r2": 8,
                         "c2": len(headers) - 1, "orientation": "rows",
                         "name": "items"}]}


def _run(headers, rows):
    grid = _grid(headers)
    shape = compute_shape(grid, log=lambda _m: None)
    band = shape["repeat_bands"][0]

    class _Resp:
        success, tokens_used, model_used = True, 0, "stub"
        parsed_json = {"tables": {band["name"]: rows}}
        raw_text = json.dumps(parsed_json)

    orch = type("O", (), {"llm": type(
        "L", (), {"extract": lambda self, **k: _Resp()})()})()
    ed = run_slot_extraction(
        orch, "ACME.pdf", {"layout": grid, "shape": shape}, None,
        page_images=[], doc_text=PAGE, doc_text_pages=[PAGE],
        file_type="digital_pdf", default_doc_type="other", start=0.0
    )[0].extracted_data
    return band, ed


#: One data row the template reaches, and one sub-header it does not — the
#: label is keyed `Label`, which a five-column band has no column for.
ROWS = [
    {"cells": {"Date": "2024-01-04", "Description": "Widget assembly",
               "Qty": "2", "Rate": "50.00", "Amount": "100.00"},
     "source": "2024-01-04 Widget assembly 2 50.00 100.00", "page": 1},
    {"cells": {"Label": "Net earnings includes:"},
     "source": "Net earnings includes:", "page": 1},
]

HEADERS = ["Date", "Description", "Qty", "Rate", "Amount"]


@pytest.fixture(scope="module")
def dropped():
    return _run(HEADERS, ROWS)


class TestTheDroppedRowIsStillDropped:
    """The gate stays. A row with nothing in any column the template has is not
    a row of that table, and emitting it would put a blank line into every
    sheet whose model returns a trailing empty object. Loud, not removed."""

    def test_it_is_not_written(self, dropped):
        _band, ed = dropped
        assert len(ed["items_rows"]) == 1
        assert ed["items_rows"][0]["Description"] == "Widget assembly"


class TestTheDroppedRowIsVisible:
    def test_it_raises_a_flag_carrying_its_own_content(self, dropped):
        _band, ed = dropped
        flags = [f for f in ed["validation"]["flagged_fields"]
                 if isinstance(f, dict) and "empty" in str(f.get("ref", ""))]
        assert len(flags) == 1, ed["validation"]["flagged_fields"]
        assert "Net earnings includes:" in str(flags[0]["value"])

    def test_it_is_counted(self, dropped):
        _band, ed = dropped
        assert ed["validation"]["empty_row_count"] == 1

    def test_it_sets_needs_review(self, dropped):
        _band, ed = dropped
        assert ed["needs_review"] is True

    def test_it_says_so_in_the_notes(self, dropped):
        """Asserted on the contract, not on a word: a note names the table and
        says a row was dropped from it."""
        _band, ed = dropped
        notes = ed["validation_notes"]
        assert any("items" in n and "dropped" in n for n in notes), notes


class TestTheOffSchemaKeyIsCounted:
    """:987 discards a key the band has no column for. Counted, at ROW
    granularity for the flag: the live run fired 0 per-key flags on 17
    legitimately reworded bands, so per-key would be affordable — but a row is
    the unit a reader can act on, and one flag naming three lost keys is worth
    more than three flags naming one each."""

    def test_the_discarded_key_is_counted(self, dropped):
        _band, ed = dropped
        assert ed["validation"]["off_schema_key_count"] == 1

    def test_one_flag_per_row_names_the_keys_it_lost(self, dropped):
        _band, ed = dropped
        flags = [f for f in ed["validation"]["flagged_fields"]
                 if isinstance(f, dict) and "unused keys" in str(f.get("ref", ""))]
        assert len(flags) == 1, ed["validation"]["flagged_fields"]
        assert "Label" in str(flags[0]["value"])

    def test_a_row_that_survives_still_reports_its_lost_keys(self):
        """The loss is not only fatal-to-the-row. A section total answered as
        {Label, Amount} against a five-column band keeps its value and loses
        its label — the row is written, half-empty, and that was silent too."""
        _band, ed = _run(HEADERS, [
            {"cells": {"Label": "Subtotal", "Amount": "200.00"},
             "source": "Subtotal 200.00", "page": 1}])
        assert len(ed["items_rows"]) == 1
        assert ed["items_rows"][0]["Amount"] == "200.00"
        assert ed["validation"]["off_schema_key_count"] == 1
        assert ed["needs_review"] is True


class TestNothingFiresOnAMatchingTemplate:
    """The control. Every gold band matched its answer in all 23 live runs, and
    a template that fits must stay silent or the signal is worthless."""

    def test_no_empty_row_no_off_schema_key(self):
        _band, ed = _run(HEADERS, [ROWS[0]])
        assert ed["validation"]["empty_row_count"] == 0
        assert ed["validation"]["off_schema_key_count"] == 0
        assert not [f for f in ed["validation"]["flagged_fields"]
                    if isinstance(f, dict)
                    and ("empty" in str(f.get("ref", ""))
                         or "unused keys" in str(f.get("ref", "")))]

    def test_the_source_and_page_keys_are_not_off_schema(self):
        """`source` and `page` are the row's envelope, not cells of it."""
        _band, ed = _run(HEADERS, [ROWS[0]])
        assert ed["validation"]["off_schema_key_count"] == 0


class TestRuleASeesWhatDetectionDropped:
    """A detected band is built from a run of ADJACENT non-empty headings, so a
    column whose heading is blank is not in `b["columns"]` at all — and rule A
    iterates `b["columns"]`. It can therefore only ever fire on a DECLARED
    region, and the identical hand-drawn table gets no warning while the
    declared one does.

    This is more likely to happen than I4 itself: it needs one blank cell, not
    a model that answers off-schema.
    """

    @staticmethod
    def _shape(cells):
        grid = {"cells": {k: {"value": v, "style": {}} for k, v in cells.items()},
                "colWidths": [120] * 26, "merges": {}, "repeatRows": [],
                "regions": []}
        return compute_shape(grid, log=lambda _m: None)

    #: headings in B and C, nothing in A, and a label below that puts column A
    #: inside the used range — the blank top-left corner of a drawn table.
    BLANK_CORNER = {"0,1": "Description", "0,2": "Amount", "6,0": "Total"}

    def test_the_declared_version_warns_today(self):
        """The control: the same shape, declared, already warns."""
        grid = {"cells": {k: {"value": v, "style": {}}
                          for k, v in self.BLANK_CORNER.items()},
                "colWidths": [120] * 26, "merges": {}, "repeatRows": [],
                "regions": [{"type": "table", "r1": 0, "c1": 0, "r2": 5,
                             "c2": 2, "orientation": "rows", "name": "t"}]}
        sh = compute_shape(grid, log=lambda _m: None)
        assert sh["coverage"]["warnings"], "declared blank corner must warn"

    def test_the_detected_version_warns_too(self):
        sh = self._shape(self.BLANK_CORNER)
        assert sh["repeat_bands"], "expected a detected band"
        assert sh["coverage"]["warnings"], (
            "a detected band abutting a blank heading warns about nothing; "
            "detection dropped the column before rule A could see it")

    def test_the_warning_names_the_column(self):
        sh = self._shape(self.BLANK_CORNER)
        assert any("column A" in w for w in sh["coverage"]["warnings"]), \
            sh["coverage"]["warnings"]

    def test_it_does_not_block(self):
        """A blank corner is a template a user may have meant. Warn, as A does."""
        sh = self._shape(self.BLANK_CORNER)
        assert not sh["coverage"]["blocking"]

    def test_a_band_starting_at_column_A_is_silent(self):
        """The control: nothing to the left, nothing to warn about."""
        sh = self._shape({"0,0": "Description", "0,1": "Amount",
                          "6,0": "Total"})
        assert sh["repeat_bands"]
        assert not sh["coverage"]["warnings"], sh["coverage"]["warnings"]
