"""M2 — the model that ANSWERED is stored per document and shown in the
export's Legend (and the job detail: frontend/lib/jobModel.test.ts)."""

from __future__ import annotations

import contextlib
import io
from types import SimpleNamespace

import openpyxl

from tests.contract import run_a_driver as D  # noqa: F401  (bootstraps imports)

from connectors.base import LLMResponse  # noqa: E402


def test_the_returned_model_version_is_stored_not_the_requested_name():
    from app.services.job_worker import model_of
    r = LLMResponse(raw_text="{}", success=True, model_used="gemini-2.5-flash",
                    model_version="gemini-2.5-flash-001")
    assert model_of(r) == "gemini-2.5-flash-001"


def test_without_a_version_the_requested_name_is_stored():
    from app.services.job_worker import model_of
    r = LLMResponse(raw_text="{}", success=True, model_used="gemini-2.5-flash")
    assert model_of(r) == "gemini-2.5-flash"
    r2 = LLMResponse(raw_text="{}", success=True, model_used="gemini-2.5-flash",
                     attempts=[{"model_version": "gemini-2.5-flash-002"}])
    assert model_of(r2) == "gemini-2.5-flash-002"
    assert model_of(None) == "vision_direct"


def test_the_legend_names_the_model():
    from app.api.routes import extract as X
    wb = openpyxl.Workbook()
    docs = [SimpleNamespace(filename="a.pdf", model_used="gemini-2.5-flash-001",
                            get_extracted_data=lambda: {"extracted_fields": {}})]
    with contextlib.redirect_stdout(io.StringIO()):
        X._add_review_legend(wb, docs)
    text = [str(c.value) for row in wb["Legend"].iter_rows() for c in row if c.value]
    assert "Extracted by: gemini-2.5-flash-001" in text
