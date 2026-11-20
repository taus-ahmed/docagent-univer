"""H4 — raw model responses are not kept indefinitely, and the LLM-ATTEMPT
log line carries no document contents, tax ids or account numbers."""

from __future__ import annotations

import contextlib
import io
import json
from datetime import datetime, timedelta

from tests.contract import run_a_driver as D  # noqa: F401  (bootstraps imports)

SSN = "123-45-6789"
EIN = "12-3456789"
ACCOUNT = "83319204"
NAME = "Jane Q Taxpayer"
FILENAME = f"{NAME.replace(' ', '_')}_W2_{SSN}.pdf"


def test_the_attempt_line_carries_no_contents_ids_or_names(monkeypatch):
    import llm_contract as C
    from connectors.gemini_client import GeminiClient
    from log_safety import doc_ref

    answer = json.dumps({"fields": {"F1": {"value": SSN, "source": f"SSN {SSN}"},
                                    "F2": {"value": ACCOUNT, "source": f"Account {ACCOUNT}"},
                                    "F3": {"value": NAME, "source": NAME}}})
    cl = GeminiClient(api_key="offline-test-key")
    cl._preferred = "gemini-2.5-flash"
    monkeypatch.setattr(cl, "_post", lambda m, body, timeout: (answer, {
        "model_version": m, "candidate_count": 1, "prompt_tokens": 900,
        "output_tokens": 40, "thinking_tokens": 0, "finish_reason": "STOP",
        "http_status": 200}))
    tok = C.CALL_CONTEXT.set({"job_id": 7, "document": doc_ref(FILENAME), "pages": 1})
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            r = cl.extract_data(text=f"Employee {NAME} SSN {SSN} EIN {EIN} acct {ACCOUNT}",
                                prompt="Fill the W-2 slots")
    finally:
        C.CALL_CONTEXT.reset(tok)
    assert r.success
    lines = [ln for ln in buf.getvalue().splitlines() if "[LLM-ATTEMPT]" in ln]
    assert lines, buf.getvalue()[:500]
    blob = "\n".join(lines)
    for secret in (SSN, EIN, ACCOUNT, NAME, "Taxpayer", FILENAME, "6789", "W-2 slots"):
        assert secret not in blob, (secret, blob)
    assert "doc-" in blob and "prompt_tokens=900" in blob     # counts, not text


def test_raw_responses_are_cleared_after_the_retention_period():
    import sqlalchemy as sa
    from sqlalchemy.orm import sessionmaker

    from app.core.raw_retention import purge_raw
    from app.models.models import Base, DocumentResult, ExtractionJob

    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    job = ExtractionJob(user_id=1, client_id="acme_001", status="completed")
    db.add(job)
    db.commit()
    now = datetime(2026, 11, 20, 12, 0)
    old = DocumentResult(job_id=job.id, filename="a.pdf", raw_llm_response=f"SSN {SSN}",
                         extraction_json="{}", created_at=now - timedelta(days=8))
    new = DocumentResult(job_id=job.id, filename="b.pdf", raw_llm_response="recent",
                         extraction_json="{}", created_at=now - timedelta(days=2))
    db.add_all([old, new])
    db.commit()
    assert purge_raw(db, days=7, now=now) == 1
    db.expire_all()
    assert db.get(DocumentResult, old.id).raw_llm_response is None
    assert db.get(DocumentResult, old.id).extraction_json == "{}"   # extraction kept
    assert db.get(DocumentResult, new.id).raw_llm_response == "recent"
    assert purge_raw(db, days=0, now=now) == 1                      # 0 = none kept
    db.expire_all()
    assert db.get(DocumentResult, new.id).raw_llm_response is None


def test_zero_days_means_never_stored(monkeypatch):
    from app.config import settings
    from app.core import raw_retention as R
    monkeypatch.setattr(settings, "RAW_RESPONSE_RETENTION_DAYS", 0, raising=False)
    assert R.keep_raw() is False
    monkeypatch.setattr(settings, "RAW_RESPONSE_RETENTION_DAYS", 7, raising=False)
    assert R.keep_raw() is True and R.raw_days() == 7
