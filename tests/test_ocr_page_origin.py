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
    field_provenance[ref]                  + origin, review_required: bool,
                                             review_reasons: list[str]
                                             (APPROVED: a list, not a single
                                             reason; only "ocr_origin" and
                                             "pre_ocr_origin" are contracted)

ITEM 3 (APPROVED): an OCR-origin value that grounds against the machine-read
text is exactly UNVERIFIED (never high/grounded); one that FAILS a check stays
exactly LOW — an origin cap never upgrades low to unverified. Pinned on a
DETERMINISTIC reader stub (`_StubOcrSource`) so neither Tesseract nor page
skew can supply or remove a failure. `app/core/confidence.py` defines
UNVERIFIED as "no text layer existed to check the span against", which is not
literally true of an OCR'd page; its wording is Gate 2's to change.
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

import importlib.util  # noqa: E402

from PIL import Image  # noqa: E402

import core.preprocessor as preprocessor  # noqa: E402
import extractor  # noqa: E402
import ocr_source  # noqa: E402
import slot_extractor  # noqa: E402
from app.core.confidence import (  # noqa: E402
    CONFIDENT_LEVELS, HIGH, LOW, UNVERIFIED)
from ocr_source import available  # noqa: E402
from slot_extractor import run_slot_extraction  # noqa: E402
from text_layer import CoordinateSpace, PageSource  # noqa: E402

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

# ── A DETERMINISTIC PAGE, read two ways ─────────────────────────────────────
#
# Items 3 and 4's exact semantics are pinned on ONE page whose words are fixed
# here, so neither Tesseract nor skew can supply — or remove — a failure:
#
#   OCR origin     a real image-only PDF goes through the real
#                  `preprocess_file`, which decides by itself that the page has
#                  no text layer; only the READER is replaced (`_StubOcrSource`
#                  behind `ocr_source.OcrPageSource`), returning these words,
#                  straight, in the reader's own pixel space.
#   native origin  the SAME words at the SAME positions, written as a native
#                  text PDF by the generator's own writer.
#
# Same template, same stubbed answers. The native run is the control: whatever
# it reports clean, the OCR run differs from it in ORIGIN ONLY.

PAGE_PT = (612.0, 792.0)          # US Letter
PX = 300.0 / 72.0                 # points -> pixels at the stub reader's dpi
FONT = 10.0
CHAR_W, SPACE_W = 5.5, 2.75       # Helvetica 10pt, near enough for a stub box

#: (top in points, [(x in points, text), ...]) — a chunk may hold several words.
FIELD_PAGE = [
    (72, [(72, "Prairie State Bank")]),
    (110, [(72, "PAY TO THE ORDER OF: John A. Smith")]),
    (140, [(72, "Date: 07/08/2026")]),
    (170, [(72, "$267.25")]),
]
TABLE_PAGE = [
    (72, [(72, "ACME TRADING LTD STATEMENT")]),
    (110, [(72, "Date"), (180, "Description"), (360, "Amount")]),
    (130, [(72, "2024-01-04"), (180, "Widget assembly"), (360, "100.00")]),
]

FIELD_TEMPLATE = {"layout": {
    "cells": {f"{r},0": {"value": lab, "style": {}}
              for r, lab in enumerate(["Payee", "Date", "Amount"])},
    "colWidths": [120] * 26, "merges": {}, "repeatRows": [], "regions": []},
    "doc_type": "cheque", "mode": "layout"}
TABLE_TEMPLATE = {"layout": {
    "cells": {f"0,{c}": {"value": h, "style": {}}
              for c, h in enumerate(["Date", "Description", "Amount"])},
    "colWidths": [120] * 26, "merges": {}, "repeatRows": [],
    "regions": [{"type": "table", "r1": 0, "c1": 0, "r2": 6, "c2": 2,
                 "orientation": "rows", "name": "items"}]},
    "doc_type": "other", "mode": "layout"}

#: Every answer quotes a line the page prints and is inside it.
GROUNDED = {"Payee": (1, "PAY TO THE ORDER OF: John A. Smith", "John A. Smith"),
            "Date": (1, "Date: 07/08/2026", "07/08/2026"),
            "Amount": (1, "$267.25", "$267.25")}
#: `Date` answered with a figure the page prints ELSEWHERE: D9 finds it as a
#: run of words, span verification does not find it in its quoted line.
FAILED = dict(GROUNDED, Date=(1, "Date: 07/08/2026", "267.25"))
TABLE_ROW = {"cells": {"Date": "2024-01-04", "Description": "Widget assembly",
                       "Amount": "100.00"},
             "source": "2024-01-04 Widget assembly 100.00", "page": 1}


def _stub_words(spec):
    words = []
    for top, chunks in spec:
        for x, text in chunks:
            for t in text.split():
                w = CHAR_W * len(t)
                words.append({"text": t, "x0": x * PX, "x1": (x + w) * PX,
                              "top": top * PX, "bottom": (top + FONT) * PX})
                x += w + SPACE_W
    return words


def _stub_reader(spec):
    """An `OcrPageSource` stand-in: same constructor, same declarations (pixels
    at the rendered dpi, top-left; NO capabilities), fixed words."""

    class _StubOcrSource(PageSource):
        capabilities = frozenset()

        def __init__(self, image, page_number=None, dpi=ocr_source.OCR_DPI,
                     straighten_page=True):
            self._n, self._dpi = page_number, float(dpi)
            self.applied = {"rotated": 0, "deskewed": 0.0}

        @property
        def page_number(self):
            return self._n

        @property
        def space(self):
            return CoordinateSpace(unit="px", origin="top-left", dpi=self._dpi,
                                   height=PAGE_PT[1] * PX, width=PAGE_PT[0] * PX)

        def raw_text(self):
            return "\n".join(" ".join(t for _x, c in chunks for t in c.split())
                             for _top, chunks in spec)

        def words(self, size_aware=True):
            return _stub_words(spec)       # fresh dicts: the seam normalises in place

        def chars(self):
            return []

    return _StubOcrSource


def _generator():
    spec = importlib.util.spec_from_file_location("make_scan_variants", GENERATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _native_pdf(path, spec):
    gen = _generator()
    lines = [(x, PAGE_PT[1] - top - FONT * 0.8, FONT, text)
             for top, chunks in spec for x, text in chunks]
    path.write_bytes(gen.build_pdf([{"w_pt": PAGE_PT[0], "h_pt": PAGE_PT[1],
                                     "ops": gen._text_ops(lines, 0)}]))
    return path


def _scan_pdf(path):
    Image.new("L", (int(PAGE_PT[0] * PX), int(PAGE_PT[1] * PX)), 255).save(
        path, resolution=300.0)
    return path


def _run_page(tmp_path, origin, spec, template, answers=None, tables=None):
    """One page, one origin, one stubbed answer. Returns the result dict."""
    if origin == "native":
        pdf = _native_pdf(tmp_path / "native.pdf", spec)
    else:
        pdf = _scan_pdf(tmp_path / "scan.pdf")

    def extract(**kw):
        parsed = _answer(kw.get("prompt", ""), answers or {})
        if tables:
            parsed["tables"] = tables
        return _Resp(parsed)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ocr_source, "OcrPageSource", _stub_reader(spec))
        mp.setattr(ocr_source, "render_pdf_page",
                   lambda *a, **k: Image.new("L", (2550, 3300), 255))
        results = extractor.run_extraction(
            SimpleNamespace(llm=SimpleNamespace(extract=extract)), pdf,
            copy.deepcopy(template))
    return _ed(results)


def _review_schema(p, ctx):
    """The APPROVED per-value review contract, exactly, on any provenance
    object — native or OCR. Mandatory fields are indexed, never `.get()`."""
    assert "review_reason" not in p, (ctx, p)    # no singular beside the plural
    assert isinstance(p["review_reasons"], list), (ctx, p)
    assert p["review_required"] is True or p["review_required"] is False, (ctx, p)


def _clean(ed):
    """No review-triggering defect of any kind other than origin."""
    v = ed["validation"]
    for k in ("ungrounded_count", "misplaced_count", "dropped_row_count",
              "empty_row_count", "off_schema_key_count", "merged_column_count",
              "overprinted_count", "unwitnessed_count", "low_confidence_cells",
              "unbound_row_count"):
        assert v.get(k, 0) == 0, (k, v.get(k))
    assert v["regions"] == []


@pytest.fixture(scope="module")
def det(tmp_path_factory):
    """Every deterministic run, once."""
    runs = {}
    for origin in ("native", "ocr"):
        for name, kw in {
                "grounded": dict(spec=FIELD_PAGE, template=FIELD_TEMPLATE,
                                 answers=GROUNDED),
                "failed": dict(spec=FIELD_PAGE, template=FIELD_TEMPLATE,
                               answers=FAILED),
                "table": dict(spec=TABLE_PAGE, template=TABLE_TEMPLATE,
                              tables={"items": [TABLE_ROW]})}.items():
            runs[(origin, name)] = _run_page(
                tmp_path_factory.mktemp(f"{origin}_{name}"), origin, **kw)
    return runs


class TestDeterministicControls:
    """Unmarked. The NATIVE reading of the deterministic page is clean, so
    anything the OCR reading reports beyond it is caused by origin alone."""

    def test_the_grounded_answers_are_clean_and_high_on_a_native_page(self, det):
        ed = det[("native", "grounded")]
        _clean(ed)
        assert len(ed["extracted_fields"]) == 3
        assert set(ed["validation"]["confidence_map"].values()) == {HIGH}
        assert all(p["grounded"] is True for p in ed["field_provenance"].values())
        assert ed["needs_review"] is False

    def test_the_failed_answer_fails_on_a_native_page_too(self, det):
        ed = det[("native", "failed")]
        ref = _refs_by_label(ed)["Date"]
        assert ed["field_provenance"][ref]["grounded"] is False
        assert ed["validation"]["confidence_map"][ref] == LOW

    def test_the_table_row_is_clean_and_high_on_a_native_page(self, det):
        ed = det[("native", "table")]
        _clean(ed)
        (row,) = ed["items_rows"]
        # `_ungrounded` is written only when some column failed.
        assert row.get("_ungrounded", []) == [] and row["_confidence"] == HIGH

    def test_the_ocr_reading_really_went_through_ocr(self, det):
        """The scan PDF has no text layer; the stub reader is what read it."""
        for name in ("grounded", "failed", "table"):
            v = det[("ocr", name)]["validation"]
            assert v.get("unchecked_overprint_pages") == [1], v
            assert "unchecked_overprint_pages" not in \
                det[("native", name)]["validation"]


class TestItem3OcrConfidenceIsExact:

    def test_a_grounded_ocr_value_is_exactly_unverified(self, det):
        """GUARD, unmarked — it CANNOT be red today: the whole-document floor
        already makes every field on an all-OCR file `unverified`. It pins the
        exact level so a per-page fix cannot drift to `low` or `grounded`."""
        ed = det[("ocr", "grounded")]
        _clean(ed)
        for ref, p in ed["field_provenance"].items():
            assert p["grounded"] is True, (ref, p)
            assert ed["validation"]["confidence_map"][ref] == UNVERIFIED, ref

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "the scanned-file floor replaces EVERY conf_map entry with "
        "unverified, so a value that FAILED span verification is reported "
        "as unverified: a measured failure turned into no measurement"))
    def test_a_failed_check_on_an_ocr_page_stays_exactly_low(self, det):
        ed = det[("ocr", "failed")]
        ref = _refs_by_label(ed)["Date"]
        assert ed["field_provenance"][ref]["grounded"] is False
        assert ed["validation"]["confidence_map"][ref] == LOW

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "the floor rewrites the field conf_map only; a table row read from an "
        "OCR page keeps _confidence='high'"))
    def test_a_grounded_table_row_on_an_ocr_page_is_exactly_unverified(self, det):
        ed = det[("ocr", "table")]
        _clean(ed)
        (row,) = ed["items_rows"]
        assert row.get("_ungrounded", []) == []
        assert row["_confidence"] == UNVERIFIED


class TestItem4OcrOriginAloneRequiresReview:
    """CORRECTION C — the causal proof. One OCR page, every value grounded, no
    other defect (`_clean`), and the identical native page needs no review
    (`TestDeterministicControls`). So review here is owed to origin alone."""

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "a document whose only distinction is OCR origin is not sent for "
        "review: _note_unchecked deliberately leaves needs_review alone, and "
        "no per-value review metadata exists"))
    def test_an_ocr_page_with_only_grounded_values_needs_review(self, det):
        ed = det[("ocr", "grounded")]
        _clean(ed)
        assert len(ed["extracted_fields"]) == 3
        assert all(p["grounded"] is True for p in ed["field_provenance"].values())
        assert ed["needs_review"] is True
        for ref, p in ed["field_provenance"].items():
            _review_schema(p, ref)
            assert p["origin"] == "ocr", (ref, p)
            assert p["review_required"] is True, (ref, p)
            assert "ocr_origin" in p["review_reasons"], (ref, p)

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason="no per-value review metadata exists")
    def test_native_values_carry_no_origin_reason(self, det):
        ed = det[("native", "grounded")]
        assert len(ed["field_provenance"]) == 3      # every native value has one
        for ref, p in ed["field_provenance"].items():
            _review_schema(p, ref)
            assert p["origin"] == "native", (ref, p)
            assert p["review_required"] is False, (ref, p)
            assert not set(p["review_reasons"]) & OCR_REASONS, (ref, p)


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
            _review_schema(p, label)
            assert p["origin"] == "ocr", (label, p)
            assert p["review_required"] is True, (label, p)
            assert "ocr_origin" in p["review_reasons"], (label, p)

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason="no per-value origin exists")
    def test_native_values_are_not_flagged_for_their_origin(self, mixed_run):
        prov = mixed_run.ed["field_provenance"]
        for label in ("Bank", "Payee", "Amount"):
            p = prov[mixed_run.refs[label]]
            _review_schema(p, label)
            assert p["origin"] == "native", (label, p)
            assert p["review_required"] is False, (label, p)
            assert not set(p["review_reasons"]) & OCR_REASONS, (label, p)

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
        assert s["graded_cells"] == 3
        assert 2 <= s["low_confidence_cells"] <= s["graded_cells"]
        assert s["review_gate"] is True
        # The reported ratio IS low/graded. abs=5e-5 admits the 4-decimal
        # rounding the whole-document `low_confidence_ratio` already uses.
        for g in (n, s):
            assert g["low_confidence_ratio"] == pytest.approx(
                g["low_confidence_cells"] / g["graded_cells"], abs=5e-5), g

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
        """Not a scanner's invisible layer — measured: Creator 'Adobe Photoshop
        CS5', 66 full-page images, 108 VISIBLE words in MyriadPro, 0 text
        operators in render mode 3. But OCR of the rendered page reads 485
        words and the whole transaction table (`B&Q`, `WESSEX WATER`,
        `GREGGS PLC`) is in pixels the text layer does not carry. Most of the
        page is not in its text layer, so it is not native either."""
        doc = _preprocessed(BANK_STATEMENT_SAMPLE)
        assert doc.page_origins and all(
            o in ORIGIN_OF["pre_ocr"] for o in doc.page_origins), doc.page_origins

    #: VERIFIED-NATIVE CONTROLS — an explicit list, each with the evidence that
    #: it is native. A committed PDF NOT on this list is not claimed either way.
    #: The test names files; production detection must never.
    #:
    #: HOW EACH FIGURE WAS MEASURED (2026-10-21, CPython 3.11.9, the S1 secure
    #: environment: pdfplumber 0.11.9, pdfminer.six 20251230, pypdf 6.21.1):
    #:   page.chars     len(page.chars), pdfplumber 0.11.9 (includes spaces)
    #:   image cover    largest single page.images box / page area, pdfplumber
    #:   Producer etc.  PdfReader.metadata, pypdf 6.21.1
    #:   render mode 3  pypdf ContentStream walk of every page AND every form
    #:                  XObject it draws, tracking Tr through q/Q, counting text
    #:                  show operators (Tj TJ ' ") drawn while Tr == 3
    #:   fonts          pypdf 6.21.1: /FontDescriptor carries /FontFile,
    #:                  /FontFile2 or /FontFile3 = embedded; /ToUnicode present on
    #:                  the font dict. Cross-checked against `pdffonts` (poppler
    #:                  23.13.0, MiKTeX) columns emb/uni — they agree font by font.
    NATIVE_CONTROLS = [
        # Creator 'Adobe InDesign CC (Macintosh)', Producer 'Adobe PDF Library
        # 10.0.1'. 6 pages; page.chars 504, 1881, 2405, 2668, 3947, 3300.
        # 0 of 1133 text show operators in render mode 3. p1 has 6 images, the
        # largest covering 86.1% of the page; p2-p6 have none. Fonts: subset
        # MyriadPro (BYZKFY+ -Regular -Bold -It -Semibold -BoldIt) EMBEDDED with
        # /ToUnicode; ArialMT, Arial-BoldMT and Georgia NOT embedded and WITHOUT
        # /ToUnicode. (A byte-identical copy — sha256 606a93c8baac… — also sits
        # at tests/test_pdfs/; not listed twice.)
        bs.PDF_DIR / "round2" / "201403_cfpb_closing-disclosure_cover-H25B.pdf",
        # Same Creator/Producer. 6 pages; page.chars 618, 1758, 1951, 927,
        # 3932, 2906. 0 of 818 text show operators in render mode 3. p1 has 6
        # images, largest 86.1%; p2-p6 none. Fonts: subset MyriadPro (UBKJLM+,
        # same five faces) embedded with /ToUnicode; ArialMT, Arial-BoldMT,
        # Georgia not embedded, no /ToUnicode.
        bs.PDF_DIR / "round2" / "201403_cfpb_closing-disclosure_cover-H25E.pdf",
        # Same Creator/Producer. 4 pages; page.chars 679, 1896, 1527, 2076.
        # 0 of 477 text show operators in render mode 3. p1 has 6 images,
        # largest 86.1%; p2-p4 none. Fonts: subset MyriadPro (ZLFYDC+ -Regular
        # -Bold -It -Semibold) embedded with /ToUnicode; ArialMT, Arial-BoldMT,
        # Georgia not embedded, no /ToUnicode.
        bs.PDF_DIR / "round2" / "201403_cfpb_loan-estimate_fixed-rate-loan-sample-H24B.pdf",
    ]

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason="no per-page origin exists")
    def test_verified_native_controls_are_never_classified_as_ocr(self, variants):
        """ZERO false positives on the verified-native controls above and on
        the generated digital control `digital_batch_3pages`, measured the same
        way in the same environment: no Producer or Creator (written by
        tests/fixtures/make_scan_variants.py, whose `digital_ops` draws in
        render mode 0 and places no image); 3 pages, page.chars 234, 239, 221;
        0 of 24 text show operators in render mode 3; no images; one font,
        base-14 Helvetica, NOT embedded and WITHOUT /ToUnicode. The three CFPB
        forms are the HARD negatives: an image covering 86.1% of a page, and
        native."""
        paths = list(self.NATIVE_CONTROLS) + [
            _pdf(variants, "digital_batch_3pages")]
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
        _review_schema(prov, ref)
        assert prov["origin"] in ORIGIN_OF["pre_ocr"], prov
        assert prov["review_required"] is True, prov
        # The reason names the origin the page was classified as.
        assert f"{prov['origin']}_origin" in prov["review_reasons"], prov


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
