"""Run Q, Q12 — a failed job's reason is in the job list as well as the detail."""
from tests.harness import bootstrap as bs

bs.bootstrap()


def test_failed_job_reason_reaches_list_and_detail(client, auth, db, users):
    from app.models.models import ExtractionJob
    j = ExtractionJob(user_id=users["acme2"].id, client_id="acme_001", status="failed",
                      total_docs=1, successful=0, failed=1, input_source="upload",
                      error_message="1 of 1 document(s) failed. Extraction failed: the "
                                    "model's answer was cut off (output limit reached).")
    db.add(j)
    db.commit()
    db.refresh(j)
    listed = [x for x in client.get("/api/jobs", headers=auth["acme"]).json() if x["id"] == j.id]
    assert listed and "cut off" in listed[0]["error_message"]
    detail = client.get(f"/api/jobs/{j.id}", headers=auth["acme"]).json()
    assert "cut off" in detail["error_message"]
