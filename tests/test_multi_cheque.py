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

OCR_DIR = bs.TESTS_DIR / "test_OCR"
INDEX = {r["id"]: r for r in json.loads((OCR_DIR / "_index.json")
                                        .read_text(encoding="utf-8"))}


def _check_region_records(results, truths, page):
    """N records, one per cheque, in reading order, each with its OWN values,
    read off its own region of `page`, never flagged as a possible merge."""
    assert len(results) == len(truths), [r.filename for r in results]
    for j, (r, truth) in enumerate(zip(results, truths), 1):
        ed = r.extracted_data
        assert ed["source_pages"] == [page, page], ed["source_pages"]
        reg = ed["validation"]["source_region"]
        assert (reg["page"], reg["index"], reg["of"]) == (page, j, len(truths)), reg
        payee, prov = _value(ed, "Payee")
        assert payee == truth["payee"], (j, payee, truth["payee"])
        assert prov["page"] == page and prov["origin"] == "ocr", prov
        amount, _ = _value(ed, "Amount in Figures")
        assert amount in (None, truth["amount_numeral"]), (j, amount)
        routing, _ = _value(ed, "Routing Number")
        assert routing in (None, truth["routing_number"]), (j, routing)
        assert "possible_multiple_documents" not in json.dumps(ed["field_provenance"])
        assert ed["needs_review"] is True


@needs_tesseract
class TestSeveralChequesOnAPage:

    def test_two_then_three_cheques_give_five_records(self, variants):
        entry = variants[1]["scan_two_and_three_up"]
        results = _records(variants, "scan_two_and_three_up")
        assert len(results) == 5, [r.filename for r in results]
        _check_region_records(results[:2], [c["fields"] for c in entry["pages"][0]["cheques"]], 1)
        _check_region_records(results[2:], [c["fields"] for c in entry["pages"][1]["cheques"]], 2)
        for r in results:
            x0, top, x1, bottom = r.extracted_data["validation"]["source_region"]["box_pt"]
            assert 0 <= x0 < x1 <= 612 * 1.1 and 0 <= top < bottom <= 792 * 1.1

    def test_one_cheque_per_page_files_are_not_cut(self, variants):
        for r in _records(variants, "scan_batch_10pages"):
            assert "source_region" not in r.extracted_data["validation"]


def _compose(tmp_path, ids, side_by_side, name):
    """Real cheque images on one canvas, with a white gutter between them."""
    from PIL import Image
    imgs = [Image.open(OCR_DIR / INDEX[i]["files"]["clean"]).convert("RGB") for i in ids]
    gap = 120
    if side_by_side:
        w = sum(i.width for i in imgs) + gap * (len(imgs) + 1)
        h = max(i.height for i in imgs) + 2 * gap
    else:
        w = max(i.width for i in imgs) + 2 * gap
        h = sum(i.height for i in imgs) + gap * (len(imgs) + 1)
    canvas = Image.new("RGB", (w, h), "white")
    at = gap
    for im in imgs:
        canvas.paste(im, (at, gap) if side_by_side else (gap, at))
        at += (im.width if side_by_side else im.height) + gap
    path = tmp_path / name
    canvas.save(path, dpi=(300, 300))
    return path


def _run_image(path, ids):
    truths = [INDEX[i] for i in ids]
    entry = {"pages": [{"cheques": [{"fields": t} for t in truths]}]}
    return extractor.run_extraction(
        SimpleNamespace(llm=SimpleNamespace(extract=_honest_model(entry))), path,
        copy.deepcopy(TEMPLATE)), truths


@needs_tesseract
class TestComposedImages:

    def test_two_cheques_side_by_side(self, tmp_path):
        ids = ["chk_001", "chk_002"]
        results, truths = _run_image(_compose(tmp_path, ids, True, "side.png"), ids)
        _check_region_records(results, truths, 1)

    def test_two_cheques_stacked_one_with_a_misread_transit(self, tmp_path):
        """chk_009 clean: OCR reads its transit sentinel as `AG`, so the strict
        band parser finds nothing. Its cheque must neither vanish nor merge."""
        ids = ["chk_009", "chk_002"]
        results, truths = _run_image(_compose(tmp_path, ids, False, "stack.png"), ids)
        _check_region_records(results, truths, 1)

    def test_the_same_cheque_twice_on_a_page_is_one_record_flagged(self, tmp_path):
        """Two bands that name one cheque: the count cannot be established, so
        the page is NOT cut — one record, flagged, nothing dropped."""
        ids = ["chk_002", "chk_002"]
        results, _ = _run_image(_compose(tmp_path, ids, False, "twice.png"), ids)
        (r,) = results
        ed = r.extracted_data
        assert "source_region" not in ed["validation"]
        assert ed["validation"]["possible_multiple_documents"]["micr_bands"] == 2
        assert ed["needs_review"] is True
        assert all("possible_multiple_documents" in p["review_reasons"]
                   for p in ed["field_provenance"].values())


class TestTheCutOnSyntheticGeometry:
    """cut_regions on hand-placed words (points, top-left), no OCR."""

    @staticmethod
    def _line(top, x, text, gap=6.0, w=5.0):
        out = []
        for t in text.split():
            out.append({"text": t, "x0": x, "x1": x + w * len(t), "top": top,
                        "bottom": top + 9})
            x += w * len(t) + gap
        return out

    def _cheque(self, top, x, band, payee="Pay to the order of Ann Lee"):
        return [self._line(top, x, "Golden Plains Credit Union Date 11/20/2026"),
                self._line(top + 30, x, payee + " $ 100.00"),
                self._line(top + 60, x, "One hundred and 00/100 Dollars"),
                self._line(top + 90, x, band)]

    A = "C001002C A423511613A 559407816184C"
    B = "C001003C A316475251A 534192832764C"

    def test_stacked(self):
        from cheque_regions import cut_regions
        regs, why = cut_regions(self._cheque(10, 20, self.A) + self._cheque(150, 20, self.B))
        assert why == "" and [r["identity"]["routing"] for r in regs] == ["423511613",
                                                                          "316475251"]

    def test_side_by_side_on_shared_lines(self):
        """Tesseract may read both cheques' rows as ONE line each."""
        from cheque_regions import cut_regions
        left, right = self._cheque(10, 20, self.A), self._cheque(10, 400, self.B)
        regs, why = cut_regions([a + b for a, b in zip(left, right)])
        assert why == "" and len(regs) == 2
        assert all(w["x1"] < 390 for ln in regs[0]["lines"] for w in ln)

    def test_side_by_side_without_a_gutter_is_not_cut(self):
        from cheque_regions import cut_regions
        left, right = self._cheque(10, 20, self.A), self._cheque(10, 400, self.B)
        bridge = [self._line(40, 20, " ".join(["x" * 9] * 30))]
        regs, why = cut_regions([a + b for a, b in zip(left, right)] + bridge)
        assert regs is None and "gutter" in why

    def test_an_unreadable_band_still_anchors_its_cheque(self):
        from cheque_regions import cut_regions
        shaped = "C001009C A423S11G18A C5S94O78l6184C 0010002"
        regs, why = cut_regions(self._cheque(10, 20, shaped, "Pay to the order of Bo Chan")
                                + self._cheque(150, 20, self.B))
        assert why == "" and len(regs) == 2
        assert regs[0]["identity"] == {} and "Bo Chan" in regs[0]["text"]

    def test_two_bands_of_one_cheque_are_not_cut(self):
        from cheque_regions import cut_regions
        regs, why = cut_regions(self._cheque(10, 20, self.A) + self._cheque(150, 20, self.A))
        assert regs is None and "same cheque" in why

    def test_a_fragment_is_not_a_cheque(self):
        from cheque_regions import cut_regions
        regs, why = cut_regions(self._cheque(10, 20, self.A)
                                + [self._line(150, 20, self.B)])
        assert regs is None and "word" in why
