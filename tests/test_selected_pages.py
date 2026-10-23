"""`selected_pages` FAILS CLOSED — Gate 2 review (Codex), red first.

A selection is a promise about what the model may see. `run_extraction`
resolved it to the pages that exist and, when NONE did (`[999]`), skipped the
filter and sent every page — the page-2 sentinel reached the prompt. A
requested selection that resolves to nothing is now a named failure with no
model call; a partly invalid one keeps its valid pages, in FILE order, once
each, and says which numbers it ignored.

Numbers are FILE page numbers (1-based). Route-level rejection of an
out-of-range selection before any job exists is the API's job (Codex); this
is the engine's own guarantee underneath it.
"""
from __future__ import annotations

import copy
import importlib.util
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

import extractor  # noqa: E402

GENERATOR = bs.TESTS_DIR / "fixtures" / "make_scan_variants.py"
#: One sentinel per page; each must reach the model only if its page is selected.
SENTINELS = ["Alice Ames pays page one", "Robert Kim pays page two",
             "Carla Diaz pays page three"]
TEMPLATE = {"layout": {"cells": {"0,0": {"value": "Payee", "style": {}}},
                       "colWidths": [120] * 26, "merges": {},
                       "repeatRows": [], "regions": []},
            "doc_type": "other", "mode": "layout"}


@pytest.fixture(scope="module")
def pdf(tmp_path_factory):
    spec = importlib.util.spec_from_file_location("make_scan_variants", GENERATOR)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    pages = [{"w_pt": 612.0, "h_pt": 792.0,
              "ops": gen._text_ops([(72, 700, 11, s),
                                    (72, 680, 11, "Statement of account, "
                                     "printed for the selected-pages contract")],
                                   0)}
             for s in SENTINELS]
    path = tmp_path_factory.mktemp("selected") / "three_pages.pdf"
    path.write_bytes(gen.build_pdf(pages))
    return path


def _run(pdf, selected):
    calls = []

    def extract(**kw):
        calls.append(kw)
        return SimpleNamespace(success=True, parsed_json={"fields": {}},
                               raw_text="{}", tokens_used=0, model_used="stub",
                               error="")

    results = extractor.run_extraction(
        SimpleNamespace(llm=SimpleNamespace(extract=extract)), pdf,
        copy.deepcopy(TEMPLATE), selected_pages=selected)
    sent = "\n".join(str(c.get("prompt", "")) + "\n" + str(c.get("text", ""))
                     for c in calls)
    return results, calls, sent


class TestASelectionThatResolvesToNothingFailsClosed:

    @pytest.mark.parametrize("selected", [[999], [0], [-1], [0, -3, 4], []])
    def test_no_model_call_and_a_named_failure(self, pdf, selected):
        """`[]` is a selection of NOTHING, not "no selection" (that is None):
        it used to be falsy and sent every page."""
        results, calls, _sent = _run(pdf, selected)
        assert calls == []
        (r,) = results
        assert r.success is False
        assert "page" in (r.error or "").lower() and "3" in r.error, r.error


class TestAPartlyValidSelection:

    def test_valid_pages_are_kept_and_invalid_ones_reported(self, pdf):
        results, calls, sent = _run(pdf, [2, 999, 0])
        assert calls
        assert SENTINELS[1] in sent
        assert SENTINELS[0] not in sent and SENTINELS[2] not in sent
        ed = results[0].extracted_data
        assert ed["validation"]["selected_pages_ignored"] == [999, 0]
        assert any("999" in n for n in ed["validation_notes"])
        assert ed["needs_review"] is True

    def test_a_duplicate_number_sends_its_page_once(self, pdf):
        _results, calls, _sent = _run(pdf, [2, 2])
        assert len(calls) == 1
        assert calls[0]["prompt"].count(SENTINELS[1]) == 1

    def test_pages_are_sent_in_file_order(self, pdf):
        results, calls, _sent = _run(pdf, [3, 1])
        prompt = calls[0]["prompt"]
        assert prompt.index(SENTINELS[0]) < prompt.index(SENTINELS[2])
        assert SENTINELS[1] not in prompt
        assert sorted(int(p) for p in
                      results[0].extracted_data["validation"]["page_origins"]) == [1, 3]

    def test_no_selection_means_every_page(self, pdf):
        """Control, unmarked: None is the absence of a selection."""
        _results, calls, sent = _run(pdf, None)
        assert calls and all(t in sent for t in SENTINELS)

    def test_a_valid_selection_is_unchanged(self, pdf):
        """Control, unmarked: a plain valid selection filters as before."""
        _results, calls, sent = _run(pdf, [1])
        assert calls and SENTINELS[0] in sent
        assert SENTINELS[1] not in sent and SENTINELS[2] not in sent
