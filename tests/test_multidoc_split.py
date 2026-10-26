"""Generic multi-document splitting (Part 3.3), on generated stacks
(tests/fixtures/make_multidoc_fixtures.py).

A file splits where a candidate (a repeated title, a type change, the page
after a blank separator) is corroborated by a NEW reference. Where a candidate
can be neither confirmed nor refuted — no reference to compare, or a page of
another kind under the same reference — the file stays ONE record and every
value in it says `possible_multiple_documents`: never split on a guess, never
merged silently.
"""
import contextlib
import io
import sys
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()
sys.path.insert(0, str(bs.TESTS_DIR / "fixtures"))
import make_multidoc_fixtures as F  # noqa: E402
import make_locale_fixtures as M  # noqa: E402

DOCS = F.documents()


def _pages(d):
    import pdfplumber
    with pdfplumber.open(io.BytesIO(F.pdf(d))) as p:
        return [pg.extract_text() or "" for pg in p.pages]


@pytest.mark.parametrize("name", sorted(DOCS))
def test_each_stack_splits_where_its_truth_says(name):
    from doc_boundaries import find_starts
    rep = {}
    starts, _why = find_starts(_pages(DOCS[name]), report=rep)
    assert starts == DOCS[name]["starts"]
    assert bool(rep["uncertain"]) == DOCS[name]["flagged"], rep["uncertain"]


def test_a_label_with_a_colon_introduces_a_reference():
    from doc_boundaries import references
    assert references("Account Number: 000123456789") == {"000123456789"}


@pytest.fixture
def stub(monkeypatch):
    from connectors.llm_router import LLMRouter, settings
    monkeypatch.setattr(settings, "PRIMARY_LLM", "stub", raising=False)
    monkeypatch.setattr(settings, "LLM_FALLBACKS", "", raising=False)
    return SimpleNamespace(llm=LLMRouter())


def _run(stub, name, tmp_path, labels):
    import extractor
    path = tmp_path / f"{name}.pdf"
    path.write_bytes(F.pdf(DOCS[name]))
    tpl = {"layout": M._grid(labels), "doc_type": "other", "mode": "layout"}
    with contextlib.redirect_stdout(io.StringIO()):
        return extractor.run_extraction(stub, path, tpl)


def test_an_undecided_packet_is_one_record_that_says_so(stub, tmp_path):
    res = _run(stub, "claim_packet", tmp_path, ["Claim Number", "Estimate Total"])
    assert len(res) == 1
    ed = res[0].extracted_data
    assert ed["needs_review"]
    assert ed["validation"]["possible_multiple_documents"]["undecided_boundaries"] == [2]
    filled = [p for p in ed["field_provenance"].values() if p.get("source")]
    assert filled and all("possible_multiple_documents" in p["review_reasons"] for p in filled)
    assert any("may hold more than one document" in n for n in ed["validation_notes"])


def test_a_decided_stack_is_split_and_not_flagged(stub, tmp_path):
    res = _run(stub, "invoices_3", tmp_path, ["Invoice Number", "Total"])
    assert len(res) == 3
    for r in res:
        assert "possible_multiple_documents" not in (r.extracted_data.get("validation") or {})
