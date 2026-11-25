"""Run R, Part 2: the organized layout is an OPTION on the job export, off by
default. Without `layout=organized` the download is the ordinary workbook,
unchanged; with it, a no-template job's PDFs are laid out from their pages."""
import io
import json

from openpyxl import load_workbook

from tests.harness import bootstrap as bs
from tests.run_q_support import make_pdf

bs.bootstrap()


def _job(db, users, tmp_path, schema_id=None):
    from app.core.storage import get_storage
    from app.models.models import DocumentResult, ExtractionJob
    j = ExtractionJob(user_id=users["acme"].id, client_id="acme_001", status="completed",
                      total_docs=1, successful=1, input_source="upload", schema_id=schema_id)
    db.add(j)
    db.commit()
    db.refresh(j)
    pdf = make_pdf(tmp_path / "stub.pdf", [[(72, 740, "Employer Name: ACME Corp"),
                                            (330, 740, "Employee ID No: E-77"),
                                            (72, 700, "Net Pay"), (330, 700, "$5,731.00")]])
    st = get_storage()
    key = f"clients/acme_001/jobs/{j.id}/source/stub.pdf"
    st.put(key, pdf.read_bytes())
    d = DocumentResult(job_id=j.id, filename="stub.pdf", original_filename="stub.pdf",
                       s3_key=key, extraction_json=json.dumps({"extracted_fields": {}}),
                       needs_review=False, reviewed=False)
    db.add(d)
    db.commit()
    return j


def _sheets(r):
    assert r.status_code == 200, r.text
    wb = load_workbook(io.BytesIO(r.content))
    return wb


def test_default_export_is_not_the_organized_layout(client, db, users, auth, tmp_path):
    j = _job(db, users, tmp_path)
    wb = _sheets(client.get(f"/api/jobs/{j.id}/export", headers=auth["acme"]))
    assert "stub" not in wb.sheetnames
    assert "Legend" in wb.sheetnames


def test_organized_export_lays_out_the_page(client, db, users, auth, tmp_path):
    j = _job(db, users, tmp_path)
    r = client.get(f"/api/jobs/{j.id}/export?layout=organized", headers=auth["acme"])
    wb = _sheets(r)
    assert "organized" in r.headers["content-disposition"]
    ws = wb["stub"]
    vals = [c.value for row in ws.iter_rows() for c in row if c.value is not None]
    assert "Employer Name" in vals and "ACME Corp" in vals and 5731.0 in vals


def test_a_templated_job_is_refused_in_words(client, db, users, auth, tmp_path):
    j = _job(db, users, tmp_path, schema_id="27")
    r = client.get(f"/api/jobs/{j.id}/export?layout=organized", headers=auth["acme"])
    assert r.status_code == 400 and "without a template" in r.json()["detail"]
