"""The job runner flags the same cheque uploaded twice — on both records —
and keeps both; a different cheque from the same account is left alone."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from tests.harness import bootstrap as bs

bs.bootstrap()

from tests.test_duplicates import cheque  # noqa: E402


def _result(name, ed):
    return SimpleNamespace(filename=name, document_type="cheque", success=True,
                           extracted_data=ed, extraction_response=None,
                           validation=SimpleNamespace(needs_review=False, errors=[]),
                           processing_time_ms=1, error="")


def test_a_cheque_uploaded_twice_is_flagged_and_kept(db, users, _db_url, monkeypatch,
                                                     tmp_path):
    import orchestrator
    from app.api.routes import extract as extract_mod
    from app.models.models import DocumentResult, ExtractionJob

    job = ExtractionJob(user_id=users["acme"].id, client_id="acme_001",
                        status="pending", total_docs=3, input_source="upload")
    db.add(job); db.commit(); db.refresh(job)
    batch = iter([[_result("a.pdf", cheque())],
                  [_result("b.pdf", cheque(serial="1847", amount="267.25"))],
                  [_result("c.pdf", cheque(serial="001848", amount="$90.00"))]])
    monkeypatch.setattr(orchestrator, "Orchestrator",
                        lambda client_schema_path: SimpleNamespace())
    monkeypatch.setattr("app.services.job_worker.get_storage", lambda: object())
    monkeypatch.setattr("app.services.job_worker._resolve_source",
                        lambda _s, key: Path(tmp_path / Path(key).name))
    monkeypatch.setattr("app.services.job_worker._extract_with_template",
                        lambda *a, **k: next(batch))
    monkeypatch.setattr(extract_mod.settings, "RATE_LIMIT_DELAY", 0)

    extract_mod._run_extraction_sync(
        job.id, ["u/a.pdf", "u/b.pdf", "u/c.pdf"], str(tmp_path / "s.yaml"), _db_url,
        {"layout": {"cells": {}}}, str(bs.REPO_DIR), str(bs.BACKEND_DIR),
        str(bs.ENGINE_DIR))

    db.expire_all()
    docs = (db.query(DocumentResult).filter(DocumentResult.job_id == job.id)
            .order_by(DocumentResult.id).all())
    assert len(docs) == 3                                  # nothing dropped or merged
    eds = [json.loads(d.extraction_json) for d in docs]
    assert [bool(ed["validation"].get("possible_duplicate")) for ed in eds] == [True, True, False]
    assert eds[0]["validation"]["possible_duplicate"]["of"] == ["b.pdf"]
    assert [d.needs_review for d in docs] == [True, True, False]
    assert "possible_duplicate" in eds[1]["field_provenance"]["B2"]["review_reasons"]
    assert "possible_duplicate" in docs[0].validation_warnings
    refreshed = db.get(ExtractionJob, job.id)
    assert refreshed.needs_review == 2 and refreshed.status == "completed"
