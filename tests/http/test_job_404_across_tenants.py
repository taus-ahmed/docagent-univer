"""
Another firm's job id answers exactly like an id that does not exist.

The job routes answered 403 "Access denied" for a job in another tenant and
404 "Job not found" for a missing one, so a caller could probe which ids exist
in other firms (roles.md item 4). Every job and result route must now give the
SAME status and the SAME body for both. A super-admin (admin, no client_id)
still sees every tenant's job.
"""
import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

MISSING = 987654321


@pytest.fixture(scope="module")
def other_job(db, users):
    from app.models.models import DocumentResult, ExtractionJob
    j = ExtractionJob(user_id=users["other"].id, client_id="other_002",
                      status="completed", total_docs=1, successful=1,
                      input_source="upload")
    db.add(j)
    db.commit()
    db.refresh(j)
    d = DocumentResult(job_id=j.id, filename="x.pdf", extraction_json="{}")
    db.add(d)
    db.commit()
    db.refresh(d)
    return j, d


def _routes(job_id, doc_id):
    j, d = job_id, doc_id
    return [
        ("get", f"/api/jobs/{j}", None),
        ("get", f"/api/jobs/{j}/results", None),
        ("get", f"/api/jobs/{j}/inferred-templates", None),
        ("get", f"/api/jobs/{j}/export", None),
        ("get", f"/api/jobs/{j}/export/zip", None),
        ("put", f"/api/jobs/{j}/docs/{d}", {"extracted_data": {}}),
        ("patch", f"/api/jobs/{j}/docs/{d}/fields/B1", {"value": "x"}),
        ("post", f"/api/jobs/{j}/docs/{d}/approve", None),
        ("delete", f"/api/jobs/{j}", None),
        ("get", f"/api/jobs/{j}/review", None),
        ("post", f"/api/jobs/{j}/docs/{d}/review",
         {"action": "accept", "ref": "B1"}),
        ("get", f"/api/jobs/{j}/docs/{d}/pages/1", None),
        ("get", f"/api/jobs/{j}/docs/{d}/pages/1/image", None),
    ]


def _call(client, method, path, body, headers):
    kw = {"headers": headers}
    if body is not None:
        kw["json"] = body
    return getattr(client, method)(path, **kw)


@pytest.mark.parametrize("who", ["acme", "acme2"])
def test_another_tenants_job_is_indistinguishable_from_a_missing_one(
        client, auth, other_job, who):
    job, doc = other_job
    differ = []
    for (m, p, b), (_, pm, _) in zip(_routes(job.id, doc.id),
                                     _routes(MISSING, doc.id)):
        r = _call(client, m, p, b, auth[who])
        rm = _call(client, m, pm, b, auth[who])
        if r.status_code != 404 or (r.status_code, r.json()) != (
                rm.status_code, rm.json()):
            differ.append(f"{m.upper()} {p}: {r.status_code} {r.text[:80]}"
                          f" vs missing {rm.status_code} {rm.text[:80]}")
    assert not differ, "\n".join(differ)


@pytest.mark.parametrize("path", ["/api/export/combined", "/api/export/perfile"])
def test_flat_exports_answer_404_for_another_tenants_job(
        client, auth, other_job, path):
    job, _ = other_job
    r = client.post(path, headers=auth["acme"], json={"job_id": job.id})
    rm = client.post(path, headers=auth["acme"], json={"job_id": MISSING})
    assert r.status_code == 404, r.text
    assert (r.status_code, r.json()) == (rm.status_code, rm.json())


def test_a_super_admin_still_reads_any_tenants_job(client, auth, other_job):
    job, _ = other_job
    assert client.get(f"/api/jobs/{job.id}",
                      headers=auth["super"]).status_code == 200


def test_the_owner_still_reads_their_job(client, auth, other_job):
    job, _ = other_job
    assert client.get(f"/api/jobs/{job.id}",
                      headers=auth["other"]).status_code == 200
