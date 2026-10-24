"""The flat exports use a template only if the caller may see it (round 12 A1 scan).

`export._get_template_or_404` filtered by tenant alone, so any member of a
tenant could export through a colleague's PRIVATE template (its column list
shapes the file), while the system defaults every tenant may extract with
were refused. Visibility is now the one `load_template_for_user` already
applies at upload: own, default, or shared inside the caller's own tenant.
"""
import json

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()


@pytest.fixture(scope="module")
def user_job(db, users):
    from app.models.models import DocumentResult, ExtractionJob
    j = ExtractionJob(user_id=users["acme2"].id, client_id="acme_001",
                      status="completed", total_docs=1, successful=1,
                      input_source="upload")
    db.add(j)
    db.commit()
    db.refresh(j)
    db.add(DocumentResult(job_id=j.id, filename="a.pdf", document_type="sales_invoice",
                          overall_confidence="high", needs_review=False,
                          extraction_json=json.dumps({"extracted_data": {
                              "Total": {"value": "1", "confidence": "high"}}})))
    db.commit()
    return j


@pytest.mark.parametrize("route", ["combined", "perfile"])
@pytest.mark.parametrize("name,expected", [
    ("acme_private", 404),     # a colleague's private template
    ("other_private", 404),    # another tenant's
    ("acme_shared", 200),      # shared inside the tenant
    ("system_default", 200),   # a default every tenant may use
])
def test_template_visibility(client, auth, templates, user_job, route, name, expected):
    r = client.post(f"/api/export/{route}", headers=auth["acme2"],
                    json={"job_id": user_job.id, "template_id": templates[name].id})
    assert r.status_code == expected, r.text
