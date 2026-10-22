"""Gate 4b — N cheques in one file give N records, each with its own values.

The accountant's files hold several cheques: one per page (`scan_batch_10pages`)
or several on one page (`scan_two_and_three_up`, 2 then 3). Measured before
this (2026-10-22, OCR through the seam): `doc_boundaries.split` made ONE
document of every scanned, mixed and pre-OCR cheque file in the generated
fixtures — 10 cheques, one record.

OPTION 1 (this file's first half): across pages, a MICR band naming a
different cheque from every band the document carried starts a new document,
ranked like a changed reference. A page with no band never starts anything.

FAIL CLOSED: a record holding a readable band and another band (readable or
band-shaped but unreadable) is kept as ONE record, and every value in it
carries `possible_multiple_documents`.

OPTION 2 (several cheques on ONE page) is the second half. Truth is the
generator's manifest.
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

import extractor  # noqa: E402
import ocr_source  # noqa: E402
from doc_boundaries import find_starts  # noqa: E402

GENERATOR = bs.TESTS_DIR / "fixtures" / "make_scan_variants.py"
TEMPLATE = {"layout": json.loads((bs.TESTS_DIR / "gold" / "templates"
                                  / "cheque.json").read_text(encoding="utf-8")),
            "doc_type": "cheque", "mode": "layout"}
TRUTH_OF = {"Payee": "payee", "Amount in Figures": "amount_numeral",
            "Date": "date", "Memo": "memo"}
_SLOT = re.compile(r'^\s+(F\d+): .*labelled "(.+)"\s*$', re.M)

try:
    ocr_source._configure()
    HAS_TESSERACT = True
except Exception:  # pragma: no cover - environment dependent
    HAS_TESSERACT = False
needs_tesseract = pytest.mark.skipif(not HAS_TESSERACT, reason="no tesseract binary")


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
    def __init__(self, parsed):
        self.success, self.parsed_json = True, parsed
        self.raw_text = json.dumps(parsed)
        self.tokens_used, self.model_used, self.error = 0, "stub", ""


def _cheques(entry):
    return [c for p in entry["pages"] for c in p["cheques"]]


def _honest_model(entry):
    """A stub that answers ONLY from what its prompt shows: the FIRST cheque
    (in manifest order) whose payee the prompt prints, each value quoted from
    the prompt line that prints it. A record holding two cheques is therefore
    answered as the first of them — a merge shows up as a wrong record."""
    cheques = _cheques(entry)

    def extract(**kw):
        prompt = kw.get("prompt") or ""
        lines = [ln.strip() for ln in prompt.split("\n")]
        own = next((c for c in cheques if c["fields"]["payee"] in prompt), None)
        fields = {}
        if own:
            for sid, label in _SLOT.findall(prompt):
                val = str(own["fields"].get(TRUTH_OF.get(label, ""), "") or "")
                src = next((ln for ln in lines if val and val in ln
                            and "labelled" not in ln), None)
                if src:
                    fields[sid] = {"value": val, "source": src, "page": 1}
        return _Resp({"fields": fields})
    return extract


_RUNS: dict = {}


def _records(variants, name):
    if name not in _RUNS:
        _RUNS[name] = extractor.run_extraction(
            SimpleNamespace(llm=SimpleNamespace(extract=_honest_model(variants[1][name]))),
            variants[0] / f"{name}.pdf", copy.deepcopy(TEMPLATE))
    return _RUNS[name]


def _value(ed, label):
    ref = next(f["ref"] for f in ed["slot_map"]["fields"] if f["row_label"] == label)
    return ed["extracted_fields"].get(ref), ed["field_provenance"].get(ref)


def _pages(r, n_pages):
    ed = r.extracted_data
    first, last = ed.get("source_pages") or [1, n_pages]
    return list(range(first, last + 1))


# ══════════════════════════════════════════════════════════════════════════════
# OPTION 1 — one cheque per page
# ══════════════════════════════════════════════════════════════════════════════

@needs_tesseract
class TestOneChequePerPage:

    def test_ten_cheques_give_ten_records_with_their_own_values(self, variants):
        entry = variants[1]["scan_batch_10pages"]
        results = _records(variants, "scan_batch_10pages")
        assert len(results) == 10, [r.filename for r in results]
        own_payee = 0
        for k, (r, doc) in enumerate(zip(results, entry["documents_in_reading_order"])):
            ed = r.extracted_data
            assert ed["source_pages"] == [doc["pages"][0]] * 2, ed["source_pages"]
            truth = next(c for c in _cheques(entry) if c["id"] in doc["cheque_ids"])
            payee, prov = _value(ed, "Payee")
            if payee is not None:
                # Never another cheque's value, and read off its own page.
                assert payee == truth["fields"]["payee"], (k, payee)
                assert prov["page"] == doc["pages"][0], (k, prov)
                own_payee += 1
            routing, rprov = _value(ed, "Routing Number")
            if routing is not None:
                assert routing == truth["fields"]["routing_number"], (k, routing)
            assert "possible_multiple_documents" not in json.dumps(ed["field_provenance"])
            assert ed["needs_review"] is True             # OCR origin
        assert own_payee >= 9, own_payee

    @pytest.mark.parametrize("name", ["scan_traps_4pages", "scan_rotated_pages",
                                      "preocr_good", "mixed_digital_then_scan",
                                      "mixed_scan_then_digital",
                                      "mixed_with_blank_middle",
                                      "digital_batch_3pages"])
    def test_records_match_the_truth_documents(self, variants, name):
        entry = variants[1][name]
        results = _records(variants, name)
        truth = entry["documents_in_reading_order"]
        assert len(results) == len(truth), [r.filename for r in results]
        for r, doc in zip(results, truth):
            assert _pages(r, len(entry["pages"]))[0] == doc["pages"][0], \
                (r.filename, r.extracted_data.get("source_pages"), doc)

    def test_single_cheque_files_are_one_record(self, variants):
        for name in ("scan_only_single", "scan_hard_single", "scan_pdf_rotate_attr"):
            assert len(_records(variants, name)) == 1, name


@needs_tesseract
class TestFailClosed:

    def test_an_unreadable_second_band_keeps_one_record_flagged(self, variants):
        """`preocr_garbled` page 2's band reads `A423S11G18A …`: band-shaped,
        no identity, so no boundary — but never a silent merge."""
        (r,) = _records(variants, "preocr_garbled")
        ed = r.extracted_data
        assert ed["validation"]["possible_multiple_documents"]["micr_bands"] == 2
        assert ed["needs_review"] is True
        assert ed["field_provenance"], "the stub answered something"
        for p in ed["field_provenance"].values():
            assert p["review_required"] is True
            assert "possible_multiple_documents" in p["review_reasons"], p


class TestTheSignalOnPageText:
    """find_starts on page text alone — the rule, without OCR."""

    A = "Golden Plains Credit Union\nPay to the order of Ann Lee\nA423511613A C559407816184C 001002D"
    B = "Rosewood Federal\nPay to the order of Bo Chan\nA316475251A C534192832764C 001003D"
    SAME_ACCOUNT_NEXT = "Golden Plains Credit Union\nPay to the order of Cy Dee\nA423511613A C559407816184C 001003D"
    REMITTANCE = "Remittance advice, continued\nInvoice 1 for services\nInvoice 2 for goods"

    def test_a_new_band_starts_a_document(self):
        assert find_starts([self.A, self.B])[0] == [0, 1]

    def test_a_continuation_page_with_no_band_stays_with_its_cheque(self):
        assert find_starts([self.A, self.REMITTANCE, self.B])[0] == [0, 2]

    def test_the_next_cheque_from_the_same_account_is_a_new_document(self):
        assert find_starts([self.A, self.SAME_ACCOUNT_NEXT])[0] == [0, 1]

    def test_the_same_band_twice_is_one_document(self):
        assert find_starts([self.A, self.A])[0] == [0]

    def test_bands_with_nothing_in_common_to_compare_do_not_split(self):
        # Only the routing is readable on one, only the account on the other:
        # no part in common is no evidence.
        only_routing = "Pay to the order of Ann Lee\nA423511613A C55@4o7816l84C"
        other = "Pay to the order of Bo Chan\nGARBLED 534192832764 C"
        assert find_starts([only_routing, other])[0] == [0]

    def test_the_page_numbering_veto_still_outranks_it(self):
        a = self.A + "\nPage 1 of 2"
        b = self.B + "\nPage 2 of 2"
        assert find_starts([a, b])[0] == [0]


# ══════════════════════════════════════════════════════════════════════════════
# OPTION 2 — several cheques on one page
# ══════════════════════════════════════════════════════════════════════════════

@needs_tesseract
@pytest.mark.known_bug
@pytest.mark.xfail(strict=True, reason=(
    "Gate 4b option 2: a document is a run of WHOLE pages, so two or three "
    "cheques on one page are one document; sub-page regions are needed"))
def test_several_cheques_on_a_page_give_one_record_each(variants):
    entry = variants[1]["scan_two_and_three_up"]
    results = _records(variants, "scan_two_and_three_up")
    assert len(results) == len(_cheques(entry)) == 5, len(results)


@needs_tesseract
def test_today_several_cheques_on_a_page_are_flagged_not_silent(variants):
    """GUARD, unmarked: until option 2, one record per PAGE (option 1 splits
    the pages) and each says it may hold several cheques."""
    results = _records(variants, "scan_two_and_three_up")
    assert len(results) == 2
    for r, n in zip(results, (2, 3)):
        ed = r.extracted_data
        assert ed["validation"]["possible_multiple_documents"]["micr_bands"] == n
        assert ed["needs_review"] is True
