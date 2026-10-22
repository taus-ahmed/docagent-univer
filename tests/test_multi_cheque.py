"""Gate 4b — N cheques in one file give N records. RED, pending a design decision.

The accountant's files hold several cheques: one per page (`scan_batch_10pages`)
or several on one page (`scan_two_and_three_up`, 2 then 3). Measured
(2026-10-22, OCR through the seam): `doc_boundaries.split` makes ONE document
of every scanned cheque file in the generated fixtures, so one slot set is
asked of 10 cheques, or of 5 — nine of ten, or four of five, have no record.

Why: across pages, a cheque scan has no repeated title, no type change and no
"page n of N", so no candidate boundary is ever raised for the reference rule
to corroborate. Within a page there is no sub-page document at all — a
document is a run of whole pages by construction.

Both fixes change what a document IS (a new boundary signal; a sub-page
region with its own text, lines, image and provenance), which is a design
decision, not a local fix. Pinned strict so the day it lands the markers must
come off. Truth is the generator's manifest.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

import extractor  # noqa: E402
import ocr_source  # noqa: E402

GENERATOR = bs.TESTS_DIR / "fixtures" / "make_scan_variants.py"
TEMPLATE = {"layout": json.loads((bs.TESTS_DIR / "gold" / "templates"
                                  / "cheque.json").read_text(encoding="utf-8")),
            "doc_type": "cheque", "mode": "layout"}

try:
    ocr_source._configure()
    HAS_TESSERACT = True
except Exception:  # pragma: no cover - environment dependent
    HAS_TESSERACT = False
pytestmark = pytest.mark.skipif(not HAS_TESSERACT, reason="no tesseract binary")


@pytest.fixture(scope="module")
def variants(tmp_path_factory):
    out = tmp_path_factory.mktemp("scan_variants_multi")
    proc = subprocess.run([sys.executable, str(GENERATOR), "--out", str(out),
                           "--repo", str(bs.REPO_DIR), "--verify"],
                          capture_output=True)
    said = (proc.stdout.decode("utf-8", "replace")
            + proc.stderr.decode("utf-8", "replace"))
    assert proc.returncode == 0 and "verify: ok" in said, said
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    return out, {v["file"][:-len(".pdf")]: v for v in manifest["variants"]}


class _Resp:
    success, parsed_json, raw_text = True, {"fields": {}}, "{}"
    tokens_used, model_used, error = 0, "stub", ""


def _records(path):
    calls = []

    def extract(**kw):
        calls.append(kw)
        return _Resp()

    results = extractor.run_extraction(
        SimpleNamespace(llm=SimpleNamespace(extract=extract)), path,
        copy.deepcopy(TEMPLATE))
    return results, calls


def _truth(entry):
    return [c for p in entry["pages"] for c in p["cheques"]]


@pytest.mark.known_bug
@pytest.mark.xfail(strict=True, reason=(
    "Gate 4b design decision: no boundary signal fires between scanned "
    "cheques on consecutive pages (no title, type change or page numbering); "
    "a new cheque-level signal, e.g. a changed MICR band, is needed"))
def test_one_cheque_per_page_gives_one_record_per_cheque(variants):
    entry = variants[1]["scan_batch_10pages"]
    results, _calls = _records(variants[0] / "scan_batch_10pages.pdf")
    assert len(results) == len(_truth(entry)) == 10, len(results)


@pytest.mark.known_bug
@pytest.mark.xfail(strict=True, reason=(
    "Gate 4b design decision: a document is a run of WHOLE pages, so two or "
    "three cheques on one page are one document; sub-page regions are needed"))
def test_several_cheques_on_a_page_give_one_record_each(variants):
    entry = variants[1]["scan_two_and_three_up"]
    results, _calls = _records(variants[0] / "scan_two_and_three_up.pdf")
    assert len(results) == len(_truth(entry)) == 5, len(results)


def test_today_the_cheques_are_merged_and_it_is_said(variants):
    """GUARD, unmarked: what happens now. One record for five cheques — and
    it must at least never pass as clean: it is OCR, so it needs review."""
    results, calls = _records(variants[0] / "scan_two_and_three_up.pdf")
    assert len(results) == 1 and len(calls) == 1
    assert results[0].extracted_data["needs_review"] is True
