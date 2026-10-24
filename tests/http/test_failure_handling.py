"""Every bad input is a NAMED failure for that file — never an exception that
takes the batch down, never a silent success, never the wrong reason.

The upload route already refuses empty, truncated, encrypted and oversized
files at the door (tests/http/test_upload_hardening.py). These go through the
engine directly — Drive, demo samples and any future caller reach it without
that door — and through the job runner.
"""
from __future__ import annotations

import contextlib
import copy
import io
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

import extractor  # noqa: E402
from tests.test_multi_cheque import HAS_TESSERACT, TEMPLATE  # noqa: E402


class _Resp:
    def __init__(self, ok=True, error=""):
        self.success, self.error = ok, error
        self.parsed_json = {"fields": {}} if ok else None
        self.raw_text, self.tokens_used, self.model_used = "{}", 0, "stub"


class _LLM:
    def __init__(self, answer=None, raises=None):
        self.calls, self.answer, self.raises = 0, answer, raises

    def extract(self, **kw):
        self.calls += 1
        if self.raises:
            raise self.raises
        return self.answer or _Resp()


def _run(path, llm, monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.setattr(extractor.time, "sleep", lambda s: None)
    with contextlib.redirect_stdout(io.StringIO()):
        return extractor.run_extraction(SimpleNamespace(llm=llm), path,
                                        copy.deepcopy(TEMPLATE))


@pytest.fixture
def files(tmp_path):
    from pypdf import PdfWriter
    w = PdfWriter(); w.add_blank_page(612, 792); w.encrypt("user-pw", "owner-pw")
    with open(tmp_path / "locked.pdf", "wb") as f:
        w.write(f)
    with open(tmp_path / "zero.pdf", "wb") as f:
        PdfWriter().write(f)
    (tmp_path / "empty.pdf").write_bytes(b"")
    (tmp_path / "corrupt.pdf").write_bytes(b"%PDF-1.4\n garbage \x00\x01 not a pdf")
    shutil.copy(bs.PDF_DIR / "CHQ-001847.pdf", tmp_path / "good.pdf")
    return tmp_path


@pytest.mark.parametrize("name,says", [
    ("empty.pdf", "is empty"),
    ("corrupt.pdf", "could not be read"),
    ("locked.pdf", "password-protected"),
    ("zero.pdf", "has no pages"),
])
def test_an_unreadable_file_is_a_named_failure_and_costs_no_model_call(files, name, says):
    llm = _LLM()
    (r,) = _run(files / name, llm)
    assert r.success is False
    assert says in r.error and name in r.error, r.error
    assert llm.calls == 0


def test_a_provider_error_names_the_provider_failure(files, monkeypatch):
    (r,) = _run(files / "good.pdf", _LLM(answer=_Resp(False, "503 Service Unavailable")),
                monkeypatch)
    assert r.success is False
    assert "model call failed" in r.error and "503 Service Unavailable" in r.error, r.error


def test_a_provider_that_raises_is_a_named_failure(files, monkeypatch):
    (r,) = _run(files / "good.pdf", _LLM(raises=ConnectionError("connection reset")),
                monkeypatch)
    assert r.success is False
    assert "model call failed" in r.error and "connection reset" in r.error, r.error


def test_a_gigantic_page_is_not_a_silent_success(tmp_path):
    from pypdf import PdfWriter
    w = PdfWriter(); w.add_blank_page(14400, 14400)
    with open(tmp_path / "giant.pdf", "wb") as f:
        w.write(f)
    for r in _run(tmp_path / "giant.pdf", _LLM()):
        assert r.success is False or r.extracted_data["needs_review"] is True


@pytest.mark.skipif(not HAS_TESSERACT, reason="no tesseract binary")
def test_an_ocr_crash_is_named_and_needs_review(tmp_path, monkeypatch):
    import ocr_source
    from PIL import Image

    class Crash(ocr_source.OcrPageSource):
        def __init__(self, *a, **k):
            raise RuntimeError("tesseract crashed")

    monkeypatch.setattr(ocr_source, "OcrPageSource", Crash)
    Image.open(bs.TESTS_DIR / "test_OCR" / "chk_003_clean.png").convert("RGB").save(
        tmp_path / "scan.pdf", "PDF")
    for r in _run(tmp_path / "scan.pdf", _LLM()):
        assert r.success is False or (
            r.extracted_data["needs_review"] is True
            and r.extracted_data["validation"].get("ocr_failed_pages") == [1]), r


def test_an_unsupported_file_raises_a_named_error(tmp_path):
    (tmp_path / "notes").write_bytes(b"hello")
    with pytest.raises(ValueError, match="Unsupported file type"):
        _run(tmp_path / "notes", _LLM())


# ── the job runner: one bad file never takes the batch down ──────────────────

def test_the_batch_survives_a_failing_file(db, users, _db_url, monkeypatch, tmp_path):
    import orchestrator
    from app.api.routes import extract as extract_mod
    from app.models.models import DocumentResult, ExtractionJob

    job = ExtractionJob(user_id=users["acme"].id, client_id="acme_001",
                        status="pending", total_docs=3, input_source="upload")
    db.add(job); db.commit(); db.refresh(job)
    ok = SimpleNamespace(filename="good.pdf", document_type="cheque", success=True,
                         extracted_data={"needs_review": False, "validation": {}},
                         extraction_response=None,
                         validation=SimpleNamespace(needs_review=False, errors=[]),
                         processing_time_ms=1, error="")
    outcomes = iter([RuntimeError("engine blew up"),
                     [extract_mod._fail("bad.pdf", "bad.pdf is password-protected")],
                     [ok]])

    def fake(*a, **k):
        o = next(outcomes)
        if isinstance(o, Exception):
            raise o
        return o

    monkeypatch.setattr(orchestrator, "Orchestrator", lambda client_schema_path: SimpleNamespace())
    monkeypatch.setattr("app.services.job_worker.get_storage", lambda: object())
    monkeypatch.setattr("app.services.job_worker._resolve_source",
                        lambda _s, key: Path(tmp_path / Path(key).name))
    monkeypatch.setattr("app.services.job_worker._extract_with_template", fake)
    monkeypatch.setattr(extract_mod.settings, "RATE_LIMIT_DELAY", 0)
    extract_mod._run_extraction_sync(
        job.id, ["u/crash.pdf", "u/bad.pdf", "u/good.pdf"], str(tmp_path / "s.yaml"),
        _db_url, {"layout": {"cells": {}}}, str(bs.REPO_DIR), str(bs.BACKEND_DIR),
        str(bs.ENGINE_DIR))
    db.expire_all()
    docs = (db.query(DocumentResult).filter(DocumentResult.job_id == job.id)
            .order_by(DocumentResult.id).all())
    assert len(docs) == 3
    errors = [d.validation_errors or "" for d in docs]
    assert "engine blew up" in errors[0] and "password-protected" in errors[1]
    assert errors[2] == ""
    j = db.get(ExtractionJob, job.id)
    assert (j.status, j.successful, j.failed) == ("partial", 1, 2), (j.status, j.successful, j.failed)
    assert j.error_message
