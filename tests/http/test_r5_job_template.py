"""Run R, R5 — "Template used: No template" for a job that used a template.

The job row stores `schema_id` (the template's id) at upload, and the export
used it, but neither `JobStatus` (GET /api/jobs/{id}, polled while the job
runs and read after it ends) nor `JobListItem` (GET /api/jobs, History)
declared the field, so the API dropped it and the frontend's
`templateOfJob(jobStatus, templates)` always answered "no template".
"""
from tests.harness import bootstrap as bs

bs.bootstrap()


def _job(db, owner, schema_id, status):
    from app.models.models import ExtractionJob
    j = ExtractionJob(user_id=owner.id, client_id="acme_001", status=status,
                      total_docs=1, input_source="upload", schema_id=schema_id)
    db.add(j)
    db.commit()
    db.refresh(j)
    return j


def test_job_status_names_its_template_while_running_and_after(client, db, users, auth):
    for status in ("processing", "completed"):
        job = _job(db, users["acme2"], "27", status)
        r = client.get(f"/api/jobs/{job.id}", headers=auth["acme2"])
        assert r.status_code == 200
        assert r.json().get("schema_id") == "27"


def test_history_names_each_jobs_template(client, db, users, auth):
    with_tpl = _job(db, users["acme2"], "33", "completed")
    without = _job(db, users["acme2"], None, "completed")
    r = client.get("/api/jobs?limit=200", headers=auth["acme2"])
    assert r.status_code == 200
    by_id = {j["id"]: j for j in r.json()}
    assert by_id[with_tpl.id].get("schema_id") == "33"
    assert by_id[without.id].get("schema_id") is None
