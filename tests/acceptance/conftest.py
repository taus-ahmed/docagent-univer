"""Acceptance fixtures and a hard outbound-network guard."""
from __future__ import annotations

import ipaddress
import json
import socket
from pathlib import Path
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "acceptance"
SOURCE_DOCS = FIXTURES / "source_docs"
JOB_RECORDS = FIXTURES / "job_records"
GOLDEN = ROOT / "tests" / "golden"


@pytest.fixture(scope="session")
def acceptance_fixtures() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def acceptance_source_docs() -> Path:
    return SOURCE_DOCS


@pytest.fixture(scope="session")
def acceptance_job_records() -> Path:
    return JOB_RECORDS


@pytest.fixture(scope="session")
def golden_dir() -> Path:
    return GOLDEN


@pytest.fixture(scope="session")
def replayed_jobs():
    """The four frozen responses replayed through the real, current engine."""
    from tests.contract.run_a_driver import replay_job

    return {job: replay_job(job) for job in (15, 19, 21, 25)}


@pytest.fixture
def local_pdf_tools(monkeypatch):
    """Use installed local PDF/OCR binaries without depending on Poppler.

    Production uses Poppler through ``external_tools.render``. This Windows
    test image has no Poppler, but it does have pypdfium2 and Tesseract. The
    fixture substitutes only the renderer seam and still exercises the real
    preprocessor, OCR reader, page geometry, and image/model-input contract.
    """
    import external_tools
    import pypdfium2 as pdfium
    import pytesseract

    def render(path, *, pages=None, dpi=200, first_page=None, last_page=None, **_kwargs):
        pdf = pdfium.PdfDocument(str(path))
        first = max(0, int(first_page or 1) - 1)
        stop = min(len(pdf), int(last_page or pages or len(pdf)))
        try:
            return [pdf[index].render(scale=float(dpi) / 72.0).to_pil()
                    for index in range(first, stop)]
        finally:
            pdf.close()

    monkeypatch.setattr(external_tools, "render", render)
    monkeypatch.setenv("OCR_WORKERS", "1")
    tesseract = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    if tesseract.exists():
        monkeypatch.setattr(pytesseract.pytesseract, "tesseract_cmd", str(tesseract))
    external_tools._PROBES.clear()
    return render


def _loopback(host: object) -> bool:
    if host in {None, "", "localhost"}:
        return True
    try:
        return ipaddress.ip_address(str(host)).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    """Normal acceptance tests may use loopback only, never a hosted service."""
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create = socket.create_connection

    def guarded_connect(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        if not _loopback(host):
            raise AssertionError(f"external network disabled in acceptance tests: {host}")
        return original_connect(sock, address)

    def guarded_create(address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if not _loopback(host):
            raise AssertionError(f"external network disabled in acceptance tests: {host}")
        return original_create(address, *args, **kwargs)

    def guarded_connect_ex(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        if not _loopback(host):
            raise AssertionError(f"external network disabled in acceptance tests: {host}")
        return original_connect_ex(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket, "create_connection", guarded_create)


# Reuse the HTTP suite's deliberately local test app: a disposable SQLite file
# and scratch storage, never the configured application database.
from tests.http.conftest import (  # noqa: E402,F401
    _db_url, _scratch_storage, app, auth, client, db, users,
)


def _run_a_stored_result() -> dict:
    return {
        "document_type": "bank_statement",
        "template_type": "slot",
        "extraction_method": "slot_directed",
        "extracted_fields": {"B1": "Lakeshore Bank", "B2": "$20,376.00"},
        "extracted_data": {
            "Bank Name": {"value": "Lakeshore Bank", "confidence": "high", "ref": "B1"},
            "Closing Balance": {"value": "$20,376.00", "confidence": "high", "ref": "B2"},
        },
        "field_provenance": {
            "B1": {"source": "Lakeshore Bank", "page": 1, "grounded": True,
                   "review_required": False, "review_reasons": []},
            "B2": {"source": "$20,376.00", "page": 1, "grounded": True,
                   "review_required": False, "review_reasons": []},
        },
        "slot_map": {
            "fields": [
                {"slot_id": "F1", "ref": "B1", "row_label": "Bank Name", "section": ""},
                {"slot_id": "F2", "ref": "B2", "row_label": "Closing Balance", "section": ""},
                {"slot_id": "F3", "ref": "B3", "row_label": "Total Deposits", "section": ""},
            ],
            "tables": [{
                "name": "table", "header_row": 4, "start_row": 5, "end_row": 20,
                "columns": [
                    {"col": 0, "header": "Date", "key": "Date"},
                    {"col": 1, "header": "Amount", "key": "Amount"},
                ],
            }],
        },
        "table_rows": [
            {"Date": "09/02/2026", "Amount": "1,254.00", "_confidence": "high",
             "_source": "09/02/2026 ACH 1,254.00", "_page": 1},
            {"Date": "09/03/2026", "Amount": "4,980.00", "_confidence": "high",
             "_source": "09/03/2026 ACH 4,980.00", "_page": 1},
        ],
        "validation": {
            "confidence_map": {"B1": "high", "B2": "high"},
            "flagged_fields": [{
                "ref": "Total Deposits", "value": "",
                "reason": "empty_flagged: amount $12,445.50 printed near this label",
            }],
        },
        "needs_review": True,
        "document_state": "NEEDS_ATTENTION",
        "diagnostics": {
            "pages": {"1": "processed", "2": "failed"},
            "coverage": {"reasons": ["missing total", "unread page"]},
        },
        "attention": [
            {"id": "att-1", "disposition": None,
             "text": "Amount $12,445.50 appears on page 1 next to Total Deposits but is not in any cell."},
            {"id": "att-2", "disposition": None,
             "text": "Page 2 could not be read (OCR found no words), so nothing on it was extracted."},
        ],
    }


@pytest.fixture
def run_a_http_doc(db, users):
    """One real routed job with open attention reasons and editable values."""
    from app.models.models import ColumnTemplate, DocumentResult, ExtractionJob

    grid = {
        "cells": {
            "0,0": {"value": "Bank Name"},
            "1,0": {"value": "Closing Balance"},
            "2,0": {"value": "Total Deposits"},
            "4,0": {"value": "Date"},
            "4,1": {"value": "Amount"},
        },
        "merges": {}, "colWidths": [], "repeatRows": [],
    }
    template = ColumnTemplate(
        name=f"run-a-acceptance-{uuid4().hex}",
        document_type="bank_statement",
        description=json.dumps(grid),
        columns_json="[]",
        client_id="acme_001",
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    job = ExtractionJob(
        user_id=users["acme"].id,
        client_id="acme_001",
        status="completed",
        total_docs=1,
        successful=1,
        input_source="upload",
        schema_id=str(template.id),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    document = DocumentResult(
        job_id=job.id,
        filename="stmt.pdf",
        original_filename="stmt.pdf",
        document_type="bank_statement",
        overall_confidence="high",
        needs_review=True,
        extraction_json=json.dumps(_run_a_stored_result()),
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return job, document
