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
    # Run T1 owner decision: a label is copied exactly as printed, INCLUDING
    # its colon (was "Employer Name" while Organized stripped it)
    assert "Employer Name:" in vals and "ACME Corp" in vals and 5731.0 in vals


ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
BANK = ROOT / "tests" / "fixtures" / "acceptance" / "source_docs" / "bank_statement"


def _job_with(db, users, files, schema_id=None):
    """A job whose documents are `files`: [(name, bytes or None)]. None
    stores no file, as after a deploy wiped the local disk."""
    from app.core.storage import get_storage
    from app.models.models import DocumentResult, ExtractionJob
    j = ExtractionJob(user_id=users["acme"].id, client_id="acme_001", status="completed",
                      total_docs=len(files), successful=len(files), input_source="upload",
                      schema_id=schema_id)
    db.add(j)
    db.commit()
    db.refresh(j)
    st = get_storage()
    for name, data in files:
        key = f"clients/acme_001/jobs/{j.id}/source/{name}"
        if data is not None:
            st.put(key, data)
        db.add(DocumentResult(job_id=j.id, filename=name, original_filename=name, s3_key=key,
                              extraction_json=json.dumps({"extracted_fields": {}, "template_type": "slot"}),
                              needs_review=False, reviewed=False))
    db.commit()
    return j


def _bank_files():
    return [(n, (BANK / n).read_bytes()) for n in ("flowparse_bank_us.pdf", "mammoth_2pg.pdf")]


def test_a_templated_job_is_laid_out_like_any_other(client, db, users, auth):
    """Staging job 141 (Bank - Monthly Reconciliation): the route answered
    400 for every templated job. The layout reads the page, never the
    extraction, so a template is no reason to refuse it."""
    j = _job_with(db, users, _bank_files(), schema_id="27")
    r = client.get(f"/api/jobs/{j.id}/export?layout=organized", headers=auth["acme"])
    wb = _sheets(r)
    assert "organized" in r.headers["content-disposition"]
    assert "flowparse_bank_us" in wb.sheetnames and "mammoth_2pg" in wb.sheetnames


def test_a_no_template_job_with_the_same_files_is_laid_out(client, db, users, auth):
    j = _job_with(db, users, _bank_files())
    wb = _sheets(client.get(f"/api/jobs/{j.id}/export?layout=organized", headers=auth["acme"]))
    assert "flowparse_bank_us" in wb.sheetnames and "mammoth_2pg" in wb.sheetnames


def test_a_missing_source_file_is_named_as_the_reason(client, db, users, auth):
    j = _job_with(db, users, [("gone.pdf", None)], schema_id="27")
    r = client.get(f"/api/jobs/{j.id}/export?layout=organized", headers=auth["acme"])
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert d["code"] == "source_missing"
    assert d["documents"] == [{"name": "gone.pdf", "code": "source_missing",
                               "reason": "the source file is no longer stored"}]


def test_a_scan_without_a_text_layer_is_named_as_the_reason(client, db, users, auth, tmp_path):
    scan = make_pdf(tmp_path / "scan.pdf", [[]]).read_bytes()
    j = _job_with(db, users, [("scan.pdf", scan)])
    r = client.get(f"/api/jobs/{j.id}/export?layout=organized", headers=auth["acme"])
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "no_text_layer"


def test_one_readable_document_still_downloads_and_lists_the_other(client, db, users, auth):
    files = _bank_files()[:1] + [("gone.pdf", None)]
    j = _job_with(db, users, files, schema_id="27")
    wb = _sheets(client.get(f"/api/jobs/{j.id}/export?layout=organized", headers=auth["acme"]))
    assert "flowparse_bank_us" in wb.sheetnames
    rows = [[c.value for c in row] for row in wb["Not organized"].iter_rows()]
    assert ["gone.pdf", "the source file is no longer stored"] in rows
