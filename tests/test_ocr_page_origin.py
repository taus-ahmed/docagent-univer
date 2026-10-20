"""OCR page provenance — the CONTRACT, written red before any fix (Gate 1).

A scanned page is now read by Tesseract through the reader seam
(`core/preprocessor._ocr_page`, `engine/ocr_source.py`). What happens to the
values read off that page was never specified, and today it is decided by one
document-wide bit:

    preprocessor.py   `native_chars` is computed per page and DROPPED;
                      `doc.native_text_chars` is never assigned, so any OCR'd
                      page makes `has_meaningful_text` False for the WHOLE file
    extractor.py      file_type = "scanned_pdf" for the whole file
    slot_extractor.py `conf_map = {k: UNVERIFIED for k in conf_map}` — every
                      field, including a grounded one on a native page AND a
                      value that FAILED its check (low -> unverified); table
                      rows are not floored at all

so a digital page that shares a file with one scan loses every confidence it
earned, a wrong value on the scan is reported as merely "unverified", and a
pre-OCR'd scan (an image carrying a scanner's invisible text layer) is read as
native text and can reach `high` with a value the scanner got wrong.

Every contract item is one or more tests marked `known_bug` +
`xfail(strict=True)`, the repo convention: the default suite stays green, and
the day a fix lands the unexpected pass FAILS the run and forces the marker
off. The unmarked tests are controls, guards and one characterization — they
pass today and must keep passing; each says why it exists.

FIXTURES. Generated per run into pytest's tmp dir by
`tests/fixtures/make_scan_variants.py --verify` (module-scoped fixture below;
nothing generated is committed). Its `manifest.json` is the ground truth:
which pages are native / scanned / pre-OCR'd, and every cheque's fields. All
SYNTHETIC — mechanism tests, not an accuracy claim about client scans.

NO MODEL CALLS. The provider is stubbed the way `test_i4_row_visibility.py`
stubs it. The stub answers each slot from a line it finds in the prompt, so
grounding, placement and confidence all run for real on real page text.

ASSUMED SHAPES — proposals for review, not settled design. Gate 2 may rename
them; if it does, these tests change in the same commit, never the outcomes:

    ProcessedDocument.page_origins         ["native" | "ocr" | "pre_ocr", ...]
    ProcessedDocument.ocr_zero_word_pages  [file page, ...]
    validation["page_origins"]             {file page: origin}
    validation["ocr_pages"]                [{page, words, rotated, deskewed,
                                             dpi, reader, reader_version}]
    validation["ocr_failed_pages"]         [file page, ...]
    validation["ocr_zero_word_pages"]      [file page, ...]
    validation["page_gates"]               {file page: {origin, graded_cells,
                                             low_confidence_cells,
                                             low_confidence_ratio,
                                             review_gate, text_floor}}
    field_provenance[ref]                  + origin, review_required,
                                             review_reason ("ocr_origin" |
                                             "pre_ocr_origin")

⚠ ITEM 3 IS A PROPOSED RULE, flagged for challenge: an OCR-origin value that
grounds against the machine-read text is UNVERIFIED (never high/grounded); one
that FAILS that check stays LOW. `app/core/confidence.py` defines UNVERIFIED as
"no text layer existed to check the span against", which is not literally true
of an OCR'd page — it has a machine-read layer. The reviewer should decide
whether that definition is widened or a new word is introduced.
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

import core.preprocessor as preprocessor  # noqa: E402
import extractor  # noqa: E402
import slot_extractor  # noqa: E402
from app.core.confidence import (  # noqa: E402
    CONFIDENT_LEVELS, HIGH, LOW, UNVERIFIED)
from ocr_source import available  # noqa: E402
from slot_extractor import run_slot_extraction  # noqa: E402
from template_shape import compute_shape  # noqa: E402

HAS_TESSERACT, TESSERACT_VERSION = available()
needs_tesseract = pytest.mark.skipif(
    not HAS_TESSERACT, reason=f"no tesseract binary: {TESSERACT_VERSION}")

GENERATOR = bs.TESTS_DIR / "fixtures" / "make_scan_variants.py"
BANK_STATEMENT_SAMPLE = bs.PDF_DIR / "round2" / "bank-statement-sample.pdf"

#: manifest origin -> the page origin the engine must record
ORIGIN_OF = {"native": {"native"}, "scan": {"ocr"},
             "pre_ocr": {"pre_ocr", "ocr"}}
OCR_REASONS = {"ocr_origin", "pre_ocr_origin"}


# ══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def variants(tmp_path_factory):
    """(out_dir, {variant name: manifest entry}) — generated, verified, never
    committed."""
    out = tmp_path_factory.mktemp("scan_variants")
    proc = subprocess.run(
        [sys.executable, str(GENERATOR), "--out", str(out),
         "--repo", str(bs.REPO_DIR), "--verify"],
        capture_output=True)
    said = (proc.stdout.decode("utf-8", "replace")
            + proc.stderr.decode("utf-8", "replace"))
    assert proc.returncode == 0 and "verify: ok" in said, said
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    return out, {v["file"][:-len(".pdf")]: v for v in manifest["variants"]}


def _pdf(variants, name):
    return variants[0] / f"{name}.pdf"


#: One preprocess per file per module. OCR is the slow part (~5-15 s a page)
#: and the result is a pure function of the file, so it is computed once and
#: every run gets its own deep copy.
_REAL_PREPROCESS = preprocessor.preprocess_file
_PREPROCESSED: dict = {}


def _preprocessed(path):
    key = str(Path(path).resolve())
    if key not in _PREPROCESSED:
        _PREPROCESSED[key] = _REAL_PREPROCESS(path)
    return copy.deepcopy(_PREPROCESSED[key])


# ── a template a user drew: six labels, value column beside them ─────────────

#: Three slots answered from the NATIVE page, three from the OCR'd page.
LABELS = ["Bank", "Payee", "Amount",
          "Scan Payee", "Scan Date", "Scan Cheque Number"]
GRID = {"cells": {f"{r},0": {"value": lab, "style": {}}
                  for r, lab in enumerate(LABELS)},
        "colWidths": [120] * 26, "merges": {}, "repeatRows": [], "regions": []}
TEMPLATE = {"layout": GRID, "doc_type": "cheque", "mode": "layout"}


def _fabricate(value):
    """The same string with its first digit changed: printed nowhere, so it
    FAILS grounding against the very line it is quoted from."""
    for i, ch in enumerate(value):
        if ch.isdigit():
            return value[:i] + str((int(ch) + 1) % 10) + value[i + 1:]
    raise AssertionError(f"no digit to change in {value!r}")


def _resolve(doc, manifest_entry, plan):
    """{label: (file page, source line, answer)} — each planned slot answered
    from a REAL line of the page it names. A slot whose truth is not on its
    page is left out; `TestFixtureSanity` fails if that happens, so a red test
    can never be red because the stub had nothing to say."""
    resolved = {}
    for label, page, field, fabricate in plan:
        cheque = manifest_entry["pages"][page - 1]["cheques"][0]
        truth = str(cheque["fields"][field])
        text = doc.page_texts[page - 1]
        line = next((ln for ln in text.split("\n") if truth and truth in ln), None)
        if line is None:
            continue
        resolved[label] = (page, line.strip(),
                           _fabricate(truth) if fabricate else truth)
    return resolved


def _mixed_plan(manifest_entry):
    """Native page: three truthful values. OCR page: one truthful, two
    fabricated (so the OCR page is 2/3 low and the document 2/6 = 33% low)."""
    pages = manifest_entry["pages"]
    native = next(p["page"] for p in pages if p["origin"] == "native")
    scan = next(p["page"] for p in pages if p["origin"] == "scan" and p["cheques"])
    return [("Bank", native, "bank", False),
            ("Payee", native, "payee", False),
            ("Amount", native, "amount_numeral", False),
            ("Scan Payee", scan, "payee", False),
            ("Scan Date", scan, "date", True),
            ("Scan Cheque Number", scan, "check_number", True)], native, scan


class _Resp:
    def __init__(self, parsed, success=True):
        self.success, self.parsed_json = success, parsed
        self.raw_text = json.dumps(parsed) if parsed else ""
        self.tokens_used, self.model_used = 0, "stub"
        self.error = "" if success else "stubbed vision failure"


_SLOT = re.compile(r'^\s+(F\d+): .*labelled "(.+)"\s*$', re.M)


def _answer(prompt, resolved):
    fields = {}
    for sid, label in _SLOT.findall(prompt or ""):
        if label in resolved:
            page, line, value = resolved[label]
            if line in prompt:
                fields[sid] = {"value": value, "source": line, "page": page}
    return {"fields": fields}


def _run(path, resolved=None, selected_pages=None, fail_vision=False,
         drop_images=False, template=TEMPLATE):
    """run_extraction end to end with the provider stubbed. Returns
    (results, provider calls)."""
    calls = []

    def extract(**kw):
        calls.append(kw)
        if fail_vision and kw.get("image_b64"):
            return _Resp(None, success=False)
        return _Resp(_answer(kw.get("prompt", ""), resolved or {}))

    def preprocess(p):
        doc = _preprocessed(p)
        if drop_images:                       # pdf2image unavailable
            doc.page_images_b64 = []
        return doc

    orch = SimpleNamespace(llm=SimpleNamespace(extract=extract))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(preprocessor, "preprocess_file", preprocess)
        results = extractor.run_extraction(orch, path, copy.deepcopy(template),
                                           selected_pages=selected_pages)
    return results, calls


def _ed(results):
    assert len(results) == 1, [r.filename for r in results]
    ed = results[0].extracted_data
    assert isinstance(ed, dict) and ed.get("extraction_method") == "slot_directed", ed
    return ed


def _refs_by_label(ed):
    return {f["row_label"]: f["ref"] for f in ed["slot_map"]["fields"]}


def _pages(d):
    """A page-keyed dict survives JSON with string keys; compare as ints."""
    return {int(k): v for k, v in (d or {}).items()}


@pytest.fixture(scope="module", params=["mixed_digital_then_scan",
                                        "mixed_scan_then_digital"])
def mixed_run(request, variants):
    """One end-to-end run per mixed fixture: (ed, native page, scan page,
    {label: ref}, {label: resolved answer})."""
    if not HAS_TESSERACT:
        pytest.skip(f"no tesseract binary: {TESSERACT_VERSION}")
    name = request.param
    entry = variants[1][name]
    plan, native, scan = _mixed_plan(entry)
    resolved = _resolve(_preprocessed(_pdf(variants, name)), entry, plan)
    results, _calls = _run(_pdf(variants, name), resolved)
    ed = _ed(results)
    return SimpleNamespace(name=name, ed=ed, native=native, scan=scan,
                           refs=_refs_by_label(ed), resolved=resolved)


@pytest.fixture(scope="module")
def blank_middle_run(variants):
    """mixed_with_blank_middle: native page 1, BLANK scan page 2, scan page 3."""
    if not HAS_TESSERACT:
        pytest.skip(f"no tesseract binary: {TESSERACT_VERSION}")
    name = "mixed_with_blank_middle"
    entry = variants[1][name]
    plan, native, scan = _mixed_plan(entry)
    resolved = _resolve(_preprocessed(_pdf(variants, name)), entry, plan)
    results, _calls = _run(_pdf(variants, name), resolved)
    ed = _ed(results)
    return SimpleNamespace(ed=ed, native=native, scan=scan,
                           refs=_refs_by_label(ed), resolved=resolved)


# ══════════════════════════════════════════════════════════════════════════════
# GUARDS AND CONTROLS — unmarked; they pass today and must keep passing
# ══════════════════════════════════════════════════════════════════════════════

class TestThisRunReadsItsOwnTree:
    """Two worktrees share one virtualenv. A test that imported the engine
    from the OTHER tree would measure code nobody is changing."""

    def test_engine_modules_resolve_inside_this_checkout(self):
        here = Path(__file__).resolve().parents[1]
        assert bs.REPO_DIR.resolve() == here
        for mod in (preprocessor, extractor, slot_extractor):
            assert Path(mod.__file__).resolve().is_relative_to(here), mod.__file__


@needs_tesseract
class TestFixtureSanity:
    """Every value a red test relies on must actually exist on its page, so a
    red test is red because of the engine — never because the stub could not
    find anything to answer with."""

    @pytest.mark.parametrize("name", ["mixed_digital_then_scan",
                                      "mixed_scan_then_digital",
                                      "mixed_with_blank_middle"])
    def test_every_planned_slot_is_answerable(self, variants, name):
        entry = variants[1][name]
        plan, _n, _s = _mixed_plan(entry)
        resolved = _resolve(_preprocessed(_pdf(variants, name)), entry, plan)
        assert sorted(resolved) == sorted(p[0] for p in plan), resolved

    def test_the_mixed_fixtures_are_one_document_each(self, mixed_run):
        """If the boundary detector ever splits them, items 2/3/4/6 would be
        measuring two single-origin documents instead of one mixed one."""
        assert mixed_run.ed.get("document_count") in (None, 1)


class TestControlTheStubCanEarnHigh:
    """The same template and stub, on an ALL-native file, yield HIGH. So when
    the mixed file's native values are not HIGH (item 2), the cause is the
    scan sharing the file — not the stub, the labels or the template."""

    def test_native_values_reach_high_in_a_digital_file(self, variants):
        name = "digital_batch_3pages"
        entry = variants[1][name]
        plan = [("Bank", 1, "bank", False), ("Payee", 1, "payee", False),
                ("Amount", 1, "amount_numeral", False)]
        resolved = _resolve(_preprocessed(_pdf(variants, name)), entry, plan)
        assert len(resolved) == 3
        results, _ = _run(_pdf(variants, name), resolved, selected_pages=[1])
        ed = _ed(results)
        refs = _refs_by_label(ed)
        for label in ("Bank", "Payee", "Amount"):
            assert ed["validation"]["confidence_map"][refs[label]] == HIGH, label


# ══════════════════════════════════════════════════════════════════════════════
# ITEM 1 — every page records where its text came from
# ══════════════════════════════════════════════════════════════════════════════

@needs_tesseract
class TestItem1PerPageOrigin:

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "no per-page origin exists: ProcessedDocument records which pages were "
        "OCR'd (ocr_pages) but not the origin of every page"))
    @pytest.mark.parametrize("name", ["mixed_digital_then_scan",
                                      "mixed_scan_then_digital"])
    def test_each_page_records_its_origin(self, variants, name):
        doc = _preprocessed(_pdf(variants, name))
        expected = [p["origin"] for p in variants[1][name]["pages"]]
        got = doc.page_origins
        assert len(got) == len(expected)
        for o, e in zip(got, expected):
            assert o in ORIGIN_OF[e], (got, expected)

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "preprocessor.py computes native_chars per page and drops it; "
        "doc.native_text_chars is never assigned, so one OCR'd page makes "
        "has_meaningful_text False for the whole file"))
    @pytest.mark.parametrize("name", ["mixed_digital_then_scan",
                                      "mixed_scan_then_digital"])
    def test_native_text_is_counted_and_one_scan_does_not_make_the_file_a_scan(
            self, variants, name):
        doc = _preprocessed(_pdf(variants, name))
        native = [i for i, p in enumerate(variants[1][name]["pages"])
                  if p["origin"] == "native"]
        assert doc.native_text_chars >= sum(
            len(doc.page_texts[i].strip()) for i in native) > 0
        assert doc.has_meaningful_text is True

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "the result carries no per-page origin"))
    def test_the_result_records_each_pages_origin(self, mixed_run):
        origins = _pages(mixed_run.ed["validation"]["page_origins"])
        assert origins == {mixed_run.native: "native", mixed_run.scan: "ocr"}


# ══════════════════════════════════════════════════════════════════════════════
# ITEM 2 — native pages keep their own confidence
# ══════════════════════════════════════════════════════════════════════════════

@needs_tesseract
class TestItem2NativePagesKeepTheirConfidence:

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "slot_extractor floors the WHOLE conf_map to unverified when the file "
        "type is scanned_pdf, and one OCR'd page makes the file scanned_pdf"))
    def test_a_grounded_value_on_a_native_page_reaches_high(self, mixed_run):
        cm = mixed_run.ed["validation"]["confidence_map"]
        for label in ("Bank", "Payee", "Amount"):
            ref = mixed_run.refs[label]
            assert mixed_run.ed["field_provenance"][ref]["page"] == mixed_run.native
            assert cm[ref] == HIGH, (label, cm[ref])

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "the label-keyed projection reads the floored conf_map"))
    def test_the_label_keyed_projection_agrees(self, mixed_run):
        kv = mixed_run.ed["extracted_data"]
        assert kv["Payee"]["confidence"] == HIGH, kv["Payee"]


# ══════════════════════════════════════════════════════════════════════════════
# ITEM 3 — OCR-origin values never exceed unverified; a failed check stays low
# (PROPOSED RULE — see the module docstring)
# ══════════════════════════════════════════════════════════════════════════════

@needs_tesseract
class TestItem3OcrValuesAreCapped:

    def test_a_true_ocr_value_is_never_confident(self, mixed_run):
        """GUARD, unmarked: true today only because the whole document is
        floored. A per-page fix must keep it true for the OCR page.

        Deliberately `not in CONFIDENT_LEVELS` rather than `== UNVERIFIED`:
        the proposed rule makes a true OCR value UNVERIFIED, but today D9
        flags it (skewed OCR lines are split by `group_lines`), so after a
        per-page fix alone it would read LOW. Which of the two is right is a
        Gate 2 decision; that it is never HIGH or GROUNDED is not."""
        ref = mixed_run.refs["Scan Payee"]
        assert mixed_run.ed["field_provenance"][ref]["page"] == mixed_run.scan
        assert mixed_run.ed["validation"]["confidence_map"][ref] in (UNVERIFIED, LOW)
        assert mixed_run.ed["validation"]["confidence_map"][ref] \
            not in CONFIDENT_LEVELS

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "the scanned-file floor replaces EVERY conf_map entry with "
        "unverified, so a value that FAILED its span check (low) is reported "
        "as unverified — a measured failure turned into no measurement"))
    def test_an_ocr_value_that_failed_its_check_stays_low(self, mixed_run):
        """'Failed its check' = flagged by ANY verification gate. Today the
        fabricated values are caught by D9 (`matches_loosely`) before span
        verification runs, so `grounded` is None rather than False: a scan
        skewed by less than ocr_source.SKEW_MIN is not deskewed, and
        `group_lines` (LINE_TOL) splits each sloping OCR line into fragments,
        so no run of words spells even a TRUE value. Either gate failing must
        leave the value LOW."""
        cm = mixed_run.ed["validation"]["confidence_map"]
        flagged = {f["ref"] for f in mixed_run.ed["validation"]["flagged_fields"]}
        for label in ("Scan Date", "Scan Cheque Number"):
            ref = mixed_run.refs[label]
            assert mixed_run.ed["field_provenance"][ref]["page"] == mixed_run.scan
            assert label in flagged, (label, flagged)
            assert cm[ref] == LOW, (label, cm[ref])


class TestItem3TableRowsOnAScan:
    """The floor touches `conf_map` only. Table rows carry their own
    `_confidence`, set before the floor and never revisited."""

    PAGE = ("ACME TRADING LTD STATEMENT\n"
            "Date Description Amount\n"
            "2024-01-04 Widget assembly 100.00\n")

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "on a scanned_pdf the field conf_map is floored to unverified but "
        "table rows keep _confidence='high'"))
    def test_a_table_row_read_from_a_scan_is_not_confident(self):
        grid = {"cells": {f"0,{c}": {"value": h, "style": {}}
                          for c, h in enumerate(["Date", "Description", "Amount"])},
                "colWidths": [120] * 26, "merges": {}, "repeatRows": [],
                "regions": [{"type": "table", "r1": 0, "c1": 0, "r2": 6,
                             "c2": 2, "orientation": "rows", "name": "items"}]}
        shape = compute_shape(grid, log=lambda _m: None)
        row = {"cells": {"Date": "2024-01-04", "Description": "Widget assembly",
                         "Amount": "100.00"},
               "source": "2024-01-04 Widget assembly 100.00", "page": 1}
        orch = SimpleNamespace(llm=SimpleNamespace(
            extract=lambda **k: _Resp({"tables": {"items": [row]}})))
        ed = run_slot_extraction(
            orch, "scan.pdf", {"layout": grid, "shape": shape}, None,
            page_images=[], doc_text=self.PAGE, doc_text_pages=[self.PAGE],
            file_type="scanned_pdf", default_doc_type="other", start=0.0,
        )[0].extracted_data
        assert ed["items_rows"], ed
        assert ed["items_rows"][0]["_confidence"] not in CONFIDENT_LEVELS


# ══════════════════════════════════════════════════════════════════════════════
# ITEM 4 — every OCR-origin value carries its own review flag
# ══════════════════════════════════════════════════════════════════════════════

@needs_tesseract
class TestItem4PerValueReviewFlag:

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "no per-value origin or review flag exists; field_provenance carries "
        "only source, page and grounded"))
    def test_every_ocr_value_is_flagged_with_a_reason(self, mixed_run):
        prov = mixed_run.ed["field_provenance"]
        for label in ("Scan Payee", "Scan Date", "Scan Cheque Number"):
            p = prov[mixed_run.refs[label]]
            assert p["origin"] == "ocr", (label, p)
            assert p["review_required"] is True, (label, p)
            assert p["review_reason"] == "ocr_origin", (label, p)

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason="no per-value origin exists")
    def test_native_values_are_not_flagged_for_their_origin(self, mixed_run):
        prov = mixed_run.ed["field_provenance"]
        for label in ("Bank", "Payee", "Amount"):
            p = prov[mixed_run.refs[label]]
            assert p["origin"] == "native", (label, p)
            assert not p.get("review_required"), (label, p)

    def test_the_document_needs_review(self, mixed_run):
        """GUARD, unmarked: true today (it has failed values). It must stay
        true when a fix removes those as a cause."""
        assert mixed_run.ed["needs_review"] is True


# ══════════════════════════════════════════════════════════════════════════════
# ITEM 5 — a page OCR read nothing from is a named failure
# ══════════════════════════════════════════════════════════════════════════════

@needs_tesseract
class TestItem5ZeroWordPages:

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "a zero-word OCR page is appended to ocr_pages as a success with "
        "words=0; it is not listed as a failure and no note names it"))
    @pytest.mark.parametrize("name,blank", [("scan_blank", 1),
                                            ("mixed_with_blank_middle", 2)])
    def test_a_zero_word_page_is_listed_and_named(self, variants, name, blank):
        assert [p["page"] for p in variants[1][name]["pages"]
                if p["blank"]] == [blank]
        doc = _preprocessed(_pdf(variants, name))
        assert doc.ocr_zero_word_pages == [blank]
        assert re.search(rf"\bpage {blank}\b", doc.processing_notes), \
            doc.processing_notes

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "neither ocr_pages nor any zero-word record reaches the result"))
    def test_the_result_names_the_zero_word_page(self, blank_middle_run):
        v = blank_middle_run.ed["validation"]
        assert v["ocr_zero_word_pages"] == [2]
        assert any(re.search(r"\bpage 2\b", n) and "word" in n.lower()
                   for n in blank_middle_run.ed["validation_notes"]), \
            blank_middle_run.ed["validation_notes"]
        assert blank_middle_run.ed["needs_review"] is True


# ══════════════════════════════════════════════════════════════════════════════
# ITEM 6 — the document gates are evaluated per page / origin
# ══════════════════════════════════════════════════════════════════════════════

@needs_tesseract
class TestItem6GatesPerPage:

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "the 30% low-confidence gate and the <50-char floor are computed over "
        "the whole document; no per-page gate exists"))
    def test_each_page_carries_its_own_gate(self, mixed_run):
        """Native page: 3 graded, 0 low. OCR page: 3 graded, at least the 2
        fabricated values low (today all 3: skewed OCR lines are split by
        `group_lines`, so D9 flags the true value too). The
        document as a whole is >= 33% low, so today the whole-document gate
        fires on the strength of the scan alone."""
        gates = _pages(mixed_run.ed["validation"]["page_gates"])
        n, s = gates[mixed_run.native], gates[mixed_run.scan]
        assert n["origin"] == "native" and s["origin"] == "ocr"
        assert n["graded_cells"] == 3 and n["low_confidence_cells"] == 0
        assert n["review_gate"] is False and n["text_floor"] is False
        assert s["graded_cells"] == 3 and s["low_confidence_cells"] >= 2
        assert s["review_gate"] is True

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "a blank OCR page in the same file floors the native page: the "
        "scanned-file floor is whole-document"))
    def test_a_blank_page_does_not_floor_the_native_page(self, blank_middle_run):
        cm = blank_middle_run.ed["validation"]["confidence_map"]
        for label in ("Bank", "Payee", "Amount"):
            assert cm[blank_middle_run.refs[label]] == HIGH, label
        gates = _pages(blank_middle_run.ed["validation"]["page_gates"])
        assert gates[1]["text_floor"] is False
        assert gates[2]["text_floor"] is True


# ══════════════════════════════════════════════════════════════════════════════
# ITEM 7 — OCR metadata reaches the persisted result, in FILE page numbers
# ══════════════════════════════════════════════════════════════════════════════

OCR_PAGE_KEYS = {"page", "words", "rotated", "deskewed", "dpi", "reader",
                 "reader_version"}


def _check_ocr_entries(entries, doc):
    by_page = {e["page"]: e for e in doc.ocr_pages}
    for e in entries:
        assert OCR_PAGE_KEYS <= set(e), e
        assert e["rotated"] in (0, 90, 180, 270)
        assert e["dpi"] > 0
        assert "tesseract" in str(e["reader"]).lower()
        assert str(e["reader_version"]).strip()
        # Persisted exactly as the reader recorded it — not re-derived.
        rec = by_page[e["page"]]
        assert (e["words"], e["rotated"], e["deskewed"]) == \
            (rec["words"], rec["rotated"], rec["deskewed"])
    # JSON round trip: the result is persisted as text (extraction_json).
    assert json.loads(json.dumps(entries)) == entries


@needs_tesseract
class TestItem7OcrMetadataIsPersisted:

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "doc.ocr_pages / ocr_failed_pages never leave the preprocessor; the "
        "extractor reads only the unchecked_* lists"))
    def test_a_single_scan(self, variants):
        path = _pdf(variants, "scan_only_single")
        ed = _ed(_run(path)[0])
        v = ed["validation"]
        assert [e["page"] for e in v["ocr_pages"]] == [1]
        _check_ocr_entries(v["ocr_pages"], _preprocessed(path))
        assert v["ocr_failed_pages"] == [] and v["ocr_zero_word_pages"] == []

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason="OCR metadata never reaches the result")
    def test_rotated_pages_keep_their_straightening_record(self, variants):
        path = _pdf(variants, "scan_rotated_pages")
        ed = _ed(_run(path)[0])
        v = ed["validation"]
        assert [e["page"] for e in v["ocr_pages"]] == [1, 2, 3]
        _check_ocr_entries(v["ocr_pages"], _preprocessed(path))

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason="OCR metadata never reaches the result")
    def test_page_numbers_are_file_pages_under_selected_pages(self, variants):
        """Selecting page 3 alone must report page 3 — not 1, its index in
        the selection — and must not report page 2, which was not extracted."""
        path = _pdf(variants, "mixed_with_blank_middle")
        ed = _ed(_run(path, selected_pages=[3])[0])
        v = ed["validation"]
        assert [e["page"] for e in v["ocr_pages"]] == [3]
        assert v["ocr_zero_word_pages"] == []


# ══════════════════════════════════════════════════════════════════════════════
# ITEM 8 — a pre-OCR'd scan is not native text
# ══════════════════════════════════════════════════════════════════════════════

class TestItem8PreOcrScans:
    """An image-dominant page carrying a scanner's invisible text layer. The
    layer is a machine's reading exactly as Tesseract's is, but today it is
    taken as the document's own words. Outcomes only: no threshold or filename
    is assumed about how the production rule decides."""

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "an embedded OCR layer is indistinguishable from native text today; "
        "no per-page origin exists"))
    @pytest.mark.parametrize("name", ["preocr_good", "preocr_garbled"])
    def test_generated_preocr_pages_are_ocr_origin(self, variants, name):
        doc = _preprocessed(_pdf(variants, name))
        assert len(doc.page_origins) == variants[1][name]["page_count"]
        assert all(o in ORIGIN_OF["pre_ocr"] for o in doc.page_origins), \
            doc.page_origins

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason="no per-page origin exists")
    def test_the_real_preocr_bank_statement_is_ocr_origin(self):
        doc = _preprocessed(BANK_STATEMENT_SAMPLE)
        assert doc.page_origins and all(
            o in ORIGIN_OF["pre_ocr"] for o in doc.page_origins), doc.page_origins

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason="no per-page origin exists")
    def test_no_digital_pdf_is_classified_as_ocr(self, variants):
        """ZERO false positives over every committed PDF (the gold set lives
        in tests/test_pdfs) and the generated digital control. The three
        CFPB forms carry an image covering 86% of a page and are digital —
        the hard negatives."""
        paths = [p for p in sorted(bs.PDF_DIR.rglob("*.pdf"))
                 if p.resolve() != BANK_STATEMENT_SAMPLE.resolve()]
        paths.append(_pdf(variants, "digital_batch_3pages"))
        wrong = {}
        for p in paths:
            doc = _REAL_PREPROCESS(p)
            if len(doc.page_origins) != doc.total_pages or \
                    any(o != "native" for o in doc.page_origins):
                wrong[p.name] = doc.page_origins
        assert wrong == {}, wrong

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "a wrong value in a pre-OCR'd layer grounds against that same layer "
        "and is written at HIGH, unflagged"))
    def test_a_wrong_value_from_the_embedded_layer_never_reaches_high(
            self, variants):
        name = "preocr_garbled"
        entry = variants[1][name]
        page, layer_field = next(
            (p["page"], f) for p in entry["pages"]
            for f in p["cheques"][0]["text_layer"]["fields"]
            if f["field"] == "amount_numeral" and not f["matches_truth"])
        wrong = layer_field["in_layer"]
        doc = _preprocessed(_pdf(variants, name))
        line = next(ln for ln in doc.page_texts[page - 1].split("\n")
                    if wrong in ln)
        template = {"layout": {**GRID, "cells": {"0,0": {"value": "Amount",
                                                         "style": {}}}},
                    "doc_type": "cheque", "mode": "layout"}
        results, _ = _run(_pdf(variants, name),
                          {"Amount": (page, line.strip(), wrong)},
                          template=template)
        ed = _ed(results)
        ref = _refs_by_label(ed)["Amount"]
        assert ed["extracted_fields"][ref] == wrong     # the stub's answer landed
        assert ed["validation"]["confidence_map"][ref] not in CONFIDENT_LEVELS
        prov = ed["field_provenance"][ref]
        assert prov["review_required"] is True
        assert prov["review_reason"] in OCR_REASONS


# ══════════════════════════════════════════════════════════════════════════════
# ITEM 9 — selected_pages filters the aggregate text too
# ══════════════════════════════════════════════════════════════════════════════

class TestItem9SelectedPagesFilterTheText:
    """`run_extraction` filters page_images / doc_text_pages / page_lines by
    `selected_pages` — but only `if selected_pages and page_images`, and never
    `doc_text`. The aggregate text reaches the model whenever vision fails
    (the text fallback in `_llm_json`) or no page could be rendered."""

    @staticmethod
    def _sentinels(variants):
        entry = variants[1]["digital_batch_3pages"]
        return [p["cheques"][0]["fields"]["payee"] for p in entry["pages"][1:]]

    @staticmethod
    def _sent(calls):
        return "\n".join(str(c.get("prompt", "")) + "\n" + str(c.get("text", ""))
                         for c in calls)

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "doc_text is never filtered by selected_pages, and _llm_json's text "
        "fallback sends it whole"))
    def test_excluded_pages_never_reach_the_model_on_the_text_fallback(
            self, variants):
        _results, calls = _run(_pdf(variants, "digital_batch_3pages"),
                               selected_pages=[1], fail_vision=True)
        assert any(c.get("text") for c in calls), "the fallback must have run"
        sent = self._sent(calls)
        for s in self._sentinels(variants):
            assert s not in sent, s

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "the selected_pages filter is skipped entirely when no page image "
        "was rendered"))
    def test_excluded_pages_never_reach_the_model_without_page_images(
            self, variants):
        _results, calls = _run(_pdf(variants, "digital_batch_3pages"),
                               selected_pages=[1], drop_images=True)
        assert calls
        sent = self._sent(calls)
        for s in self._sentinels(variants):
            assert s not in sent, s


# ══════════════════════════════════════════════════════════════════════════════
# ITEM 10 — CHARACTERIZATION: what the slot extraction call sends today
# ══════════════════════════════════════════════════════════════════════════════

class TestItem10WhatTheSlotCallSends:
    """Pins CURRENT behaviour, unmarked. Not a contract: if Gate 2 changes what
    the model is sent, this changes in the same commit, deliberately.

    `run_slot_extraction` hands `_llm_json` BOTH the page images and the
    aggregate text. With images present the provider is called with the
    images and a prompt that EMBEDS each page's text; the separate `text`
    argument is sent only on the fallback, after the image call fails."""

    PAGE = "Bank: First Union Bank\nPay to the order of: Priya Patel\n"
    IMAGES = ["IMAGE-PAGE-1"]

    def _call(self, fail_vision):
        seen_llm_json, provider = [], []
        real = slot_extractor._llm_json

        def spy(orchestrator, prompt, system, images=None, text="", **kw):
            seen_llm_json.append({"images": images, "text": text})
            return real(orchestrator, prompt, system, images=images, text=text, **kw)

        def extract(**kw):
            provider.append(kw)
            if fail_vision and kw.get("image_b64"):
                return _Resp(None, success=False)
            return _Resp({"fields": {}})

        grid = {"cells": {"0,0": {"value": "Payee", "style": {}}},
                "colWidths": [120] * 26, "merges": {}, "repeatRows": [],
                "regions": []}
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(slot_extractor, "_llm_json", spy)
            run_slot_extraction(
                SimpleNamespace(llm=SimpleNamespace(extract=extract)),
                "doc.pdf", {"layout": grid}, None, page_images=self.IMAGES,
                doc_text=self.PAGE, doc_text_pages=[self.PAGE],
                file_type="digital_pdf", default_doc_type="other", start=0.0)
        return seen_llm_json, provider

    def test_llm_json_receives_both_images_and_text(self):
        seen, _ = self._call(fail_vision=False)
        assert seen == [{"images": self.IMAGES, "text": self.PAGE}]

    def test_the_provider_gets_images_and_a_prompt_embedding_the_text(self):
        _, provider = self._call(fail_vision=False)
        assert len(provider) == 1
        assert provider[0]["image_b64"] == self.IMAGES
        assert "Pay to the order of: Priya Patel" in provider[0]["prompt"]
        assert "text" not in provider[0]

    def test_the_text_argument_is_sent_only_on_the_fallback(self):
        _, provider = self._call(fail_vision=True)
        assert [("image_b64" in c, c.get("text")) for c in provider] == \
            [(True, None), (False, self.PAGE)]
