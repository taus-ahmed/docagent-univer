"""THE REVIEW INVARIANT: if ANY value has review_required True, the document's
needs_review is True. Everywhere — fields and table rows, native and OCR,
every reason code, not only amounts.

It is stated over the fixtures of Gates 1-3:
  Gate 1/2  every generated scan-variant file (scan, mixed, pre-OCR good and
            garbled, blank, rotated, batch, multi-up), answered from its
            manifest truth through the cheque template;
  Gate 3    the cheque cross-check cases (match, mismatch, unreadable words,
            no words field, a grounding failure);
  images    the source cheque images (JPG and PNG) read through the seam.

`amount_unreadable` used to be the exception — a value flagged for review in
a document that did not need it. There is no exception now.
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
from core.preprocessor import preprocess_file  # noqa: E402

GENERATOR = bs.TESTS_DIR / "fixtures" / "make_scan_variants.py"
TEMPLATE = {"layout": json.loads((bs.TESTS_DIR / "gold" / "templates"
                                  / "cheque.json").read_text(encoding="utf-8")),
            "doc_type": "cheque", "mode": "layout"}
#: Template label -> manifest/index truth field.
TRUTH_OF = {"Cheque Number": "check_number", "Date": "date", "Bank Name": "bank",
            "Payee": "payee", "Amount in Figures": "amount_numeral",
            "Amount in Words": "amount_words_shown", "Memo": "memo",
            "Routing Number": "routing_number", "Account Number": "account_number"}
_SLOT = re.compile(r'^\s+(F\d+): .*labelled "(.+)"\s*$', re.M)

try:
    ocr_source._configure()
    HAS_TESSERACT = True
except Exception:  # pragma: no cover - environment dependent
    HAS_TESSERACT = False
needs_tesseract = pytest.mark.skipif(not HAS_TESSERACT, reason="no tesseract binary")


def assert_review_invariant(ed, ctx):
    """The invariant, on one result's extracted_data."""
    owing = [ref for ref, p in (ed.get("field_provenance") or {}).items()
             if p.get("review_required") is True]
    for key, rows in ed.items():
        if key.endswith("_rows") and isinstance(rows, list):
            owing += [f"{key}[{i}]" for i, r in enumerate(rows)
                      if isinstance(r, dict) and r.get("_review_required") is True]
    if owing:
        assert ed["needs_review"] is True, (ctx, owing, ed.get("validation_notes"))


class _Resp:
    def __init__(self, parsed):
        self.success, self.parsed_json = True, parsed
        self.raw_text = json.dumps(parsed)
        self.tokens_used, self.model_used, self.error = 0, "stub", ""


def _answer_from_truth(path, truth):
    """A stub model answering every slot from `truth`, quoting the line the
    reader printed it on — or an invented line when it printed none, which is
    a grounding failure by construction."""
    doc = preprocess_file(path)
    lines = [ln.strip() for t in doc.page_texts for ln in t.split("\n") if ln.strip()]

    def extract(**kw):
        fields = {}
        for sid, label in _SLOT.findall(kw.get("prompt") or ""):
            val = str(truth.get(TRUTH_OF.get(label, ""), "") or "").strip()
            if val:
                src = next((ln for ln in lines if val in ln), f"{label}: {val} (seen)")
                fields[sid] = {"value": val, "source": src, "page": 1}
        return _Resp({"fields": fields})
    return extract


def _run(path, extract, template=TEMPLATE):
    return extractor.run_extraction(
        SimpleNamespace(llm=SimpleNamespace(extract=extract)), path,
        copy.deepcopy(template))


@pytest.fixture(scope="module")
def variants(tmp_path_factory):
    out = tmp_path_factory.mktemp("scan_variants_invariant")
    proc = subprocess.run([sys.executable, str(GENERATOR), "--out", str(out),
                           "--repo", str(bs.REPO_DIR), "--verify"],
                          capture_output=True)
    said = (proc.stdout.decode("utf-8", "replace")
            + proc.stderr.decode("utf-8", "replace"))
    assert proc.returncode == 0 and "verify: ok" in said, said
    return out, json.loads((out / "manifest.json").read_text(encoding="utf-8"))


@needs_tesseract
def test_gate_1_and_2_fixtures(variants, monkeypatch):
    """Each file is OCR'd ONCE: the stub model and the pipeline share one
    preprocessing (it was run twice, ~45 pages of Tesseract each time, which
    is what made this test take 6-9 minutes)."""
    import core.preprocessor as pre
    real, seen = pre.preprocess_file, {}

    def once(path):
        key = str(path)
        if key not in seen:
            seen[key] = real(path)
        return seen[key]

    monkeypatch.setattr(pre, "preprocess_file", once)     # the pipeline's call
    monkeypatch.setitem(globals(), "preprocess_file", once)  # the stub's call
    out, manifest = variants
    checked = 0
    for v in manifest["variants"]:
        cheques = [c for p in v["pages"] for c in p["cheques"]]
        truth = cheques[0]["fields"] if cheques else {}
        for r in _run(out / v["file"], _answer_from_truth(out / v["file"], truth)):
            if isinstance(r.extracted_data, dict) and "field_provenance" in r.extracted_data:
                assert_review_invariant(r.extracted_data, v["file"])
                checked += 1
    assert checked >= 10, checked
    # NOT VACUOUS: the scans were really read. With no Poppler nothing renders,
    # every OCR page is a named failure, and the invariant held over values
    # nobody had read — the test passed in 4 seconds.
    read = [v["file"] for v in manifest["variants"]
            if any(e["words"] > 0 for e in seen[str(out / v["file"])].ocr_pages)]
    assert len(read) >= 8, read


WORDS = "Three Thousand Five Hundred Seventy-Two and 78/100 Dollars"


@pytest.mark.parametrize("figures,words,payee_src", [
    ("$3,572.78", WORDS, None),                                       # match
    ("$8,572.78", WORDS, None),                                       # mismatch
    ("$3,572.78", "Thre Thousnd Five Hundred Seventy-Two and 78/100", None),  # unreadable
    ("$3,572.78", "five twenty and 00/100", None),                    # strict grammar
    ("$3,572.78", WORDS, "Pay to the order of Robert Kim"),           # grounding failed
])
def test_gate_3_cheque_cases(tmp_path, figures, words, payee_src):
    from tests.test_cheque_cross_check import CHEQUE, _native
    lines = ["Pay to the order of Maria Gonzalez", figures, words]
    resolved = {"Payee": (payee_src or lines[0], "Maria Gonzalez" if not payee_src
                          else "Robert Kim"),
                "Amount in Figures": (figures, figures),
                "Amount in Words": (words, words)}

    def extract(**kw):
        fields = {}
        for sid, label in _SLOT.findall(kw.get("prompt") or ""):
            if label in resolved:
                src, val = resolved[label]
                fields[sid] = {"value": val, "source": src, "page": 1}
        return _Resp({"fields": fields})

    (r,) = _run(_native(tmp_path, lines), extract, CHEQUE)
    assert_review_invariant(r.extracted_data, (figures, words))


@needs_tesseract
@pytest.mark.parametrize("cheque_id,tier", [("chk_002", "clean"), ("chk_007", "moderate"),
                                            ("chk_009", "moderate"), ("chk_014", "clean")])
def test_source_images(cheque_id, tier):
    rec = next(r for r in json.loads((bs.TESTS_DIR / "test_OCR" / "_index.json")
                                     .read_text(encoding="utf-8")) if r["id"] == cheque_id)
    path = bs.TESTS_DIR / "test_OCR" / rec["files"][tier]
    (r,) = _run(path, _answer_from_truth(path, rec))
    assert_review_invariant(r.extracted_data, path.name)
