"""The dev-only stub provider (Part A1): the whole pipeline offline."""
from __future__ import annotations

import contextlib
import io
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

LINES = ["ACME TRADING LTD", "Invoice No: INV-9001", "Invoice Date: 2024-03-15",
         "Bill To: Globex Corporation", "Description Qty Amount",
         "Widget assembly 2 $100.00", "Freight 1 $25.00", "Total: $125.00"]


def _pdf(path, lines=LINES):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    w = PdfWriter()
    page = w.add_blank_page(612, 792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject(
        {NameObject("/F1"): w._add_object(font)})})
    body = "BT /F1 11 Tf " + " ".join(
        f"1 0 0 1 72 {740 - 22 * i} Tm ({ln}) Tj" for i, ln in enumerate(lines)) + " ET"
    s = DecodedStreamObject()
    s.set_data(body.encode("latin-1"))
    page[NameObject("/Contents")] = w._add_object(s)
    with open(path, "wb") as fh:
        w.write(fh)
    return path


GRID = {"cells": {"0,0": {"value": "Invoice No"}, "1,0": {"value": "Invoice Date"},
                  "2,0": {"value": "Bill To"}, "3,0": {"value": "Total"},
                  "5,0": {"value": "Description"}, "5,1": {"value": "Qty"},
                  "5,2": {"value": "Amount"}},
        "colWidths": [], "merges": {}, "repeatRows": [],
        "regions": [{"type": "table", "r1": 5, "c1": 0, "r2": 10, "c2": 2,
                     "orientation": "rows", "name": "items"}]}


@pytest.fixture
def stub(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "PRIMARY_LLM", "stub", raising=False)
    monkeypatch.setattr(settings, "LLM_FALLBACKS", "", raising=False)
    from connectors.llm_router import LLMRouter
    return SimpleNamespace(llm=LLMRouter())


def test_a_templated_extraction_runs_offline_and_grounds(stub, tmp_path):
    import extractor
    with contextlib.redirect_stdout(io.StringIO()):
        res = extractor.run_extraction(stub, _pdf(tmp_path / "inv.pdf"),
                                       {"layout": GRID, "doc_type": "invoice",
                                        "mode": "layout"})
    ed = res[0].extracted_data
    vals = ed["extracted_fields"]
    assert "INV-9001" in vals.values() and "Globex Corporation" in vals.values()
    rows = ed.get("items_rows") or []
    assert [r["Description"] for r in rows] == ["Widget assembly", "Freight"]
    assert all(p.get("grounded") for p in ed["field_provenance"].values() if p.get("source"))


def test_no_template_inference_runs_offline(stub, tmp_path):
    import extractor
    with contextlib.redirect_stdout(io.StringIO()):
        res = extractor.run_extraction(stub, _pdf(tmp_path / "inv.pdf"), None)
    assert res and res[0].success, res[0].error


def test_the_router_never_falls_back_to_the_stub(monkeypatch):
    from app.config import settings
    from connectors import llm_router
    monkeypatch.setattr(settings, "PRIMARY_LLM", "nonsense", raising=False)
    monkeypatch.setattr(settings, "LLM_FALLBACKS", "", raising=False)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "", raising=False)
    with pytest.raises(ValueError):            # gemini has no key; stub is not a default
        llm_router.LLMRouter()


@pytest.mark.parametrize("env,ok", [("development", True), ("staging", False),
                                    ("production", False)])
def test_startup_refuses_the_stub_outside_development(env, ok, monkeypatch):
    from app.config import Settings
    monkeypatch.setenv("ENVIRONMENT", env)
    monkeypatch.setenv("PRIMARY_LLM", "stub")
    monkeypatch.setenv("SECRET_KEY", "x" * 64)
    if ok:
        assert Settings().PRIMARY_LLM == "stub"
    else:
        with pytest.raises(Exception, match="stub"):
            Settings()
