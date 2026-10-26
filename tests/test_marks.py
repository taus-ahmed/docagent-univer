"""Stamps and unreadable regions (Part 3.4 a/b, engine/marks.py).

A VOID / SPECIMEN / COPY / PAID stamp never hides the record: every value
carries the reason and the record goes to review. A value read from beneath a
redaction bar is blanked, and every empty slot of a record with a painted-over
or unreadable region says why it is empty — nothing is invented.
"""
import base64
import contextlib
import io
import sys
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()
sys.path.insert(0, str(bs.TESTS_DIR / "fixtures"))
import make_locale_fixtures as M  # noqa: E402
from make_scan_variants import build_pdf  # noqa: E402
from marks import image_obscured, stamps  # noqa: E402


@pytest.mark.parametrize("line,kind", [
    ("VOID", "void"), ("*** VOID ***", "void"), ("SPECIMEN", "void"),
    ("NON-NEGOTIABLE", "void"), ("TEST ONLY", "void"), ("DUPLICATE COPY", "void"),
    ("CANCELLED", "void"), ("PAID", "paid"), ("PAID 05/02/2024", "paid"),
])
def test_a_stamp_line_is_found(line, kind):
    got = stamps([f"INVOICE\nInvoice Number: INV-1\n{line}\nTotal: $5.00"])
    assert got[kind] and got[kind][0][0] == 1


@pytest.mark.parametrize("text", [
    "Amount Paid: $40.00", "Customer copy - keep for your records",
    "Cancelled cheques are returned monthly", "Paid", "void where prohibited",
    "COPY THIS CODE: 1234"])
def test_words_in_ordinary_text_are_not_stamps(text):
    assert stamps([text]) == {"void": [], "paid": []}


def _png(fill, bar=None):
    from PIL import Image, ImageDraw
    img = Image.new("L", (850, 1100), 255)
    d = ImageDraw.Draw(img)
    for y in range(80, 1000, 40):
        d.text((60, y), "Invoice Number: INV-2201   Amount: $1,250.00", fill=0)
    if bar:
        d.rectangle(bar, fill=0)
    if fill is not None:
        img = Image.new("L", (850, 1100), fill)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


def test_scan_pages_that_cannot_be_read_are_recognised():
    assert image_obscured(_png(None)) is None
    assert image_obscured(_png(10)) == "page"            # near-black
    assert image_obscured(_png(128)) == "page"           # no contrast
    assert image_obscured(_png(None, bar=(300, 400, 700, 460))) == "regions"
    assert image_obscured(_png(255)) is None             # a blank separator page


def test_a_sparse_page_is_not_obscured():
    from PIL import Image, ImageDraw
    img = Image.new("L", (850, 1100), 255)
    ImageDraw.Draw(img).text((60, 80), "CASH SALE  Item: Tea  Amount: $8.00", fill=0)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG")
    assert image_obscured(base64.b64encode(buf.getvalue()).decode()) is None


@pytest.fixture
def stub(monkeypatch):
    from connectors.llm_router import LLMRouter, settings
    monkeypatch.setattr(settings, "PRIMARY_LLM", "stub", raising=False)
    monkeypatch.setattr(settings, "LLM_FALLBACKS", "", raising=False)
    return SimpleNamespace(llm=LLMRouter())


def _run(stub, tmp_path, lines, labels, extra_ops=b""):
    import extractor
    path = tmp_path / "doc.pdf"
    path.write_bytes(build_pdf([{"w_pt": 612, "h_pt": 792,
                                 "ops": M._ops(lines) + extra_ops}]))
    tpl = {"layout": M._grid(labels), "doc_type": "other", "mode": "layout"}
    with contextlib.redirect_stdout(io.StringIO()):
        [res] = extractor.run_extraction(stub, path, tpl)
    return res.extracted_data


LINES = ["CHEQUE", "Cheque Number: 004417", "Payee: Avery Fictional", "Amount: $2,100.00"]


def test_a_void_cheque_keeps_its_values_and_every_one_says_so(stub, tmp_path):
    ed = _run(stub, tmp_path, LINES + ["VOID"], ["Cheque Number", "Amount"])
    assert "004417" in ed["extracted_fields"].values()
    assert ed["needs_review"]
    assert ed["validation"]["document_marks"]["void_marker"]["marks"] == ["VOID"]
    filled = [p for p in ed["field_provenance"].values() if p.get("source")]
    assert filled and all("void_marker" in p["review_reasons"] for p in filled)


def test_a_paid_stamp_is_its_own_reason(stub, tmp_path):
    ed = _run(stub, tmp_path, LINES + ["PAID"], ["Cheque Number"])
    assert "paid_marker" in ed["validation"]["document_marks"]
    assert "void_marker" not in ed["validation"]["document_marks"]


def test_a_value_under_a_redaction_bar_is_blanked_and_flagged(stub, tmp_path):
    # LINES[3] ("Amount: …") is the 4th line: y = 780 - 18*3 = 726; a black
    # filled rectangle over the amount's words.
    bar = b"\n0 g 90 722 120 14 re f"
    ed = _run(stub, tmp_path, LINES, ["Cheque Number", "Amount"], bar)
    vals = ed["extracted_fields"]
    amount_ref = next(f["ref"] for f in ed["slot_map"]["fields"] if f["row_label"] == "Amount")
    assert vals.get(amount_ref, "") == ""
    assert "redacted_or_obscured" in ed["field_provenance"][amount_ref]["review_reasons"]
    assert any(f["ref"] == amount_ref for f in ed["validation"]["flagged_fields"])
    assert "004417" in vals.values()                    # the visible value stays
    assert ed["needs_review"] and ed["validation"]["redacted_or_obscured"]["pages"] == [1]


def test_a_clean_page_gets_none_of_this(stub, tmp_path):
    ed = _run(stub, tmp_path, LINES, ["Cheque Number", "Amount"])
    assert "document_marks" not in ed["validation"]
    assert "redacted_or_obscured" not in ed["validation"]
