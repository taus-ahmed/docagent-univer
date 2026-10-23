"""The engine's document-level review decision survives API persistence."""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import openpyxl

from tests.harness import bootstrap as bs

bs.bootstrap()


def test_engine_review_flag_reaches_storage_job_list_results_and_export(
        client, auth, db, users, _db_url, monkeypatch, tmp_path):
    from app.api.routes import extract as extract_mod
    from app.models.models import DocumentResult, ExtractionJob
    import orchestrator

    job = ExtractionJob(
        user_id=users["acme"].id,
        client_id="acme_001",
        status="pending",
        total_docs=1,
        input_source="upload",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    extracted = {
        "overall_confidence": "high",
        "extracted_data": {
            "Invoice Number": {
                "value": "INV-REVIEW-1", "confidence": "high", "ref": "B1",
            },
        },
        "validation": {
            "flagged_count": 0,
            "flagged_fields": [],
            "confidence_map": {"B1": "high"},
        },
        # Gate 2 can require review solely because the page was machine-read,
        # even when every extracted value grounded and remained otherwise clean.
        "needs_review": True,
    }
    result = SimpleNamespace(
        filename="machine-read.pdf",
        document_type="other",
        success=True,
        extracted_data=extracted,
        extraction_response=None,
        validation=SimpleNamespace(needs_review=False, errors=[]),
        processing_time_ms=7,
        error="",
    )

    monkeypatch.setattr(orchestrator, "Orchestrator",
                        lambda client_schema_path: SimpleNamespace())
    monkeypatch.setattr(extract_mod, "get_storage", lambda: object())
    monkeypatch.setattr(extract_mod, "_resolve_source",
                        lambda _storage, _key: Path(tmp_path / "machine-read.pdf"))
    monkeypatch.setattr(extract_mod, "_extract_with_template",
                        lambda *args, **kwargs: [result])

    extract_mod._run_extraction_sync(
        job.id,
        ["uploads/acme_001/machine-read.pdf"],
        str(tmp_path / "schema.yaml"),
        _db_url,
        {"layout": {"cells": {}}},
        str(bs.REPO_DIR),
        str(bs.BACKEND_DIR),
        str(bs.ENGINE_DIR),
    )

    db.expire_all()
    stored = (db.query(DocumentResult)
                .filter(DocumentResult.job_id == job.id).one())
    refreshed_job = db.query(ExtractionJob).filter(ExtractionJob.id == job.id).one()
    assert stored.needs_review is True
    assert refreshed_job.needs_review == 1

    status = client.get(f"/api/jobs/{job.id}", headers=auth["acme"])
    assert status.status_code == 200, status.text
    assert status.json()["needs_review"] == 1

    listing = client.get("/api/jobs", headers=auth["acme"])
    assert listing.status_code == 200, listing.text
    listed = next(item for item in listing.json() if item["id"] == job.id)
    assert listed["needs_review"] == 1

    response = client.get(f"/api/jobs/{job.id}/results", headers=auth["acme"])
    assert response.status_code == 200, response.text
    assert response.json()[0]["needs_review"] is True
    assert response.json()[0]["extracted_data"]["needs_review"] is True

    exported = client.post(
        "/api/export/combined",
        headers=auth["acme"],
        json={"job_id": job.id, "include_needs_review_only": True},
    )
    assert exported.status_code == 200, exported.text
    workbook = openpyxl.load_workbook(io.BytesIO(exported.content))
    assert workbook["Extracted Data"]["D2"].value == "Review"
    assert workbook["Summary"]["B7"].value == 1
