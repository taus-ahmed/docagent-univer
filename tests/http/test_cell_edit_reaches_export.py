"""A value a person corrects must be the value they download — from every path.

`ResultsGrid.tsx` saves an edit by PUTting the whole document back with
`extracted_data[label] = {value, confidence: "edited"}`. Four downloads exist,
and they do not read the same place:

  template export  GET  /api/jobs/{id}/export      slot writer: extracted_fields[ref], *_rows
  zip export       GET  /api/jobs/{id}/export/zip  slot writer, one workbook per document
  combined         POST /api/export/combined       export.py: extracted_data[label]
  per-file         POST /api/export/perfile        export.py: extracted_data[label]

Every test goes through the real routes against real jobs. A field edit is the
exact payload the grid sends. Table rows and transposed records cannot be edited
in the app (the grid renders rows read-only), so they are changed the only way
possible, a PUT of the stored document; that is what "saves correctly" can mean
for them.
"""
import copy
import io
import zipfile

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from tests.http.test_batch_end_to_end import (  # noqa: E402,F401
    _await_job, _results, _upload, _worker_env, bank_template,
)

FIELD_EDIT = "FIELD CORRECTED 7731"
ROW_EDIT = "ROW CORRECTED 5512"
RECORD_EDIT = "RECORD CORRECTED 9043"
PATHS = ["template", "zip", "combined", "perfile"]


# ── jobs ─────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def transposed_template(db, users):
    from app.models.models import ColumnTemplate
    grid = (bs.TEMPLATES_DIR / "payslip_transposed.json").read_text(encoding="utf-8")
    t = (db.query(ColumnTemplate)
           .filter(ColumnTemplate.name == "e2e_payslip_transposed").first())
    if not t:
        t = ColumnTemplate(name="e2e_payslip_transposed", document_type="payslip",
                           description=grid, columns_json="[]",
                           user_id=users["acme"].id, client_id="acme_001")
        db.add(t)
        db.commit()
        db.refresh(t)
    db.commit()
    return t


def _job(client, auth, stem, template):
    up = _upload(client, auth, [stem], template_id=template.id)
    _await_job(client, auth, up["job_id"])
    docs = _results(client, auth, up["job_id"])
    assert len(docs) == 1
    return up["job_id"]


def _doc(client, auth, job_id):
    return _results(client, auth, job_id)[0]


def _put(client, auth, job_id, doc, extracted):
    r = client.put(f"/api/jobs/{job_id}/docs/{doc['id']}",
                   json={"extracted_data": extracted}, headers=auth["acme"])
    assert r.status_code == 200, r.text


def _text_value(v):
    return isinstance(v, str) and v.strip() and not any(ch.isdigit() for ch in v)


@pytest.fixture(scope="module")
def bank_job(client, auth, bank_template):
    return _job(client, auth, "STMT-2024-01", bank_template)


@pytest.fixture(scope="module")
def field_edit(client, auth, bank_job):
    """A field slot, edited with the grid's own payload."""
    doc = _doc(client, auth, bank_job)
    kv = doc["extracted_data"]["extracted_data"]
    label, entry = next((k, v) for k, v in kv.items()
                        if isinstance(v, dict) and v.get("ref") and _text_value(v.get("value")))
    updated = copy.deepcopy(doc["extracted_data"])
    updated["extracted_data"][label] = {"value": FIELD_EDIT, "confidence": "edited"}
    _put(client, auth, bank_job, doc, updated)
    return {"job": bank_job, "label": label, "ref": entry["ref"],
            "original": entry["value"], "edit": FIELD_EDIT}


@pytest.fixture(scope="module")
def row_edit(client, auth, bank_job, field_edit):
    """A table row cell, changed in the stored document (fresh copy, so the
    field edit above is kept)."""
    doc = _doc(client, auth, bank_job)
    updated = copy.deepcopy(doc["extracted_data"])
    key = next(k for k, v in updated.items() if k.endswith("_rows") and v)
    row = updated[key][0]
    col = next(k for k, v in row.items() if not k.startswith("_") and _text_value(v))
    original, row[col] = row[col], ROW_EDIT
    _put(client, auth, bank_job, doc, updated)
    return {"job": bank_job, "original": original, "edit": ROW_EDIT}


@pytest.fixture(scope="module")
def record_edit(client, auth, transposed_template):
    """A transposed record's value, changed in the stored document."""
    job_id = _job(client, auth, "PAYSLIP-EMP-0007-APR2024", transposed_template)
    doc = _doc(client, auth, job_id)
    updated = copy.deepcopy(doc["extracted_data"])
    t = next(t for t in updated["slot_map"]["tables"] if t.get("orientation") == "columns")
    rec = updated[f"{t['name']}_rows"][0]
    key = next(f["header"] for f in t["fields"] if _text_value(rec.get(f["header"])))
    original, rec[key] = rec[key], RECORD_EDIT
    _put(client, auth, job_id, doc, updated)
    return {"job": job_id, "original": original, "edit": RECORD_EDIT}


# ── the four downloads ───────────────────────────────────────────────────────

def _workbooks(client, auth, job_id, path):
    import openpyxl
    if path == "template":
        r = client.get(f"/api/jobs/{job_id}/export", headers=auth["acme"])
        blobs = [r.content]
    elif path == "zip":
        r = client.get(f"/api/jobs/{job_id}/export/zip", headers=auth["acme"])
        z = zipfile.ZipFile(io.BytesIO(r.content))
        blobs = [z.read(n) for n in z.namelist() if n.endswith(".xlsx")]
    else:
        r = client.post(f"/api/export/{path}", json={"job_id": job_id},
                        headers=auth["acme"])
        blobs = [r.content]
    assert r.status_code == 200, (path, r.text[:300])
    return [openpyxl.load_workbook(io.BytesIO(b)) for b in blobs]


def _cells(client, auth, job_id, path):
    return [c for wb in _workbooks(client, auth, job_id, path)
            for ws in wb.worksheets for row in ws.iter_rows() for c in row
            if c.value is not None]


# ══════════════════════════════════════════════════════════════════════════
# 1. the matrix
# ══════════════════════════════════════════════════════════════════════════

class TestAFieldSlotEditReachesEveryDownload:
    def test_the_edit_is_stored(self, client, auth, field_edit):
        kv = _doc(client, auth, field_edit["job"])["extracted_data"]["extracted_data"]
        assert kv[field_edit["label"]]["value"] == FIELD_EDIT

    @pytest.mark.parametrize("path", PATHS)
    def test_the_download_holds_the_edit(self, client, auth, field_edit, path):
        """THE DEFECT, on template and zip."""
        values = [c.value for c in _cells(client, auth, field_edit["job"], path)]
        assert FIELD_EDIT in values, (
            f"{path}: {field_edit['label']!r} ({field_edit['ref']}) was edited and "
            f"saved; the file still has the extracted {field_edit['original']!r}"
            if field_edit["original"] in values else f"{path}: edit not in the file")
        assert field_edit["original"] not in values, (path, "original still present")


class TestAStoredRowChange:
    @pytest.mark.parametrize("path", ["template", "zip"])
    def test_the_slot_writer_downloads_hold_it(self, client, auth, row_edit, path):
        values = [c.value for c in _cells(client, auth, row_edit["job"], path)]
        # the original is not checked for absence: a Type like `DEP` recurs in
        # other rows of the same statement
        assert ROW_EDIT in values

    @pytest.mark.parametrize("path", ["combined", "perfile"])
    def test_export_py_does_not_export_table_rows_at_all(self, client, auth, row_edit, path):
        """Not "saved correctly": these paths never write a table row, edited or
        not."""
        values = [c.value for c in _cells(client, auth, row_edit["job"], path)]
        assert ROW_EDIT not in values and row_edit["original"] not in values


class TestAStoredTransposedRecordChange:
    @pytest.mark.parametrize("path", ["template", "zip"])
    def test_the_slot_writer_downloads_hold_it(self, client, auth, record_edit, path):
        values = [c.value for c in _cells(client, auth, record_edit["job"], path)]
        assert RECORD_EDIT in values

    @pytest.mark.parametrize("path", ["combined", "perfile"])
    def test_export_py_does_not_export_records_at_all(self, client, auth, record_edit, path):
        values = [c.value for c in _cells(client, auth, record_edit["job"], path)]
        assert RECORD_EDIT not in values


# ══════════════════════════════════════════════════════════════════════════
# 2. provenance on a value that is no longer what the document said
# ══════════════════════════════════════════════════════════════════════════

def _cell_holding(client, auth, job_id, path, value):
    return next((c for c in _cells(client, auth, job_id, path) if c.value == value), None)


class TestAnEditedValueDoesNotQuoteWhatItReplaced:
    def test_a_field_edit_in_the_template_export(self, client, auth, field_edit):
        cell = _cell_holding(client, auth, field_edit["job"], "template", FIELD_EDIT)
        assert cell is not None, "the edit is not in the file (see the matrix)"
        assert not (cell.comment and cell.comment.text.startswith("“")), cell.comment.text

    def test_a_row_change_in_the_template_export(self, client, auth, row_edit):
        """Reachable today through the API: the changed cell sits under a
        comment quoting the original row."""
        cell = _cell_holding(client, auth, row_edit["job"], "template", ROW_EDIT)
        assert cell is not None
        assert not (cell.comment and cell.comment.text.startswith("“")), cell.comment.text

    def test_a_record_change_in_the_template_export(self, client, auth, record_edit):
        cell = _cell_holding(client, auth, record_edit["job"], "template", RECORD_EDIT)
        assert cell is not None
        assert not (cell.comment and cell.comment.text.startswith("“")), cell.comment.text

    def test_the_per_file_export_calls_a_field_edit_edited(self, client, auth, field_edit):
        cells = _cells(client, auth, field_edit["job"], "perfile")
        at = next(c for c in cells if c.value == FIELD_EDIT)
        conf = at.parent.cell(row=at.row, column=at.column + 1).value
        assert conf == "Edited by hand", conf

    def test_the_combined_export_carries_no_provenance(self, client, auth, field_edit):
        assert not any(c.comment for c in _cells(client, auth, field_edit["job"], "combined"))


# ══════════════════════════════════════════════════════════════════════════
# the grid's own sequence
# ══════════════════════════════════════════════════════════════════════════

class TestASecondEditDoesNotUndoTheFirst:
    """ResultsGrid receives `results` once and never refreshes it after a save,
    and every save PUTs the WHOLE document built from that copy. The second
    edit's payload is built from the pre-edit document."""

    def test_two_edits_in_a_row_are_both_kept(self, client, auth, bank_template):
        job_id = _job(client, auth, "STMT-2024-02", bank_template)
        stale = _doc(client, auth, job_id)             # the copy the grid holds
        kv = stale["extracted_data"]["extracted_data"]
        labels = [k for k, v in kv.items()
                  if isinstance(v, dict) and str(v.get("value", "")).strip()][:2]
        for label, value in zip(labels, ("FIRST EDIT 1001", "SECOND EDIT 1002")):
            payload = copy.deepcopy(stale["extracted_data"])
            payload["extracted_data"][label] = {"value": value, "confidence": "edited"}
            _put(client, auth, job_id, stale, payload)
        kept = _doc(client, auth, job_id)["extracted_data"]["extracted_data"]
        assert kept[labels[1]]["value"] == "SECOND EDIT 1002"
        assert kept[labels[0]]["value"] == "FIRST EDIT 1001", (
            f"the second save reverted the first: {labels[0]!r} is "
            f"{kept[labels[0]]['value']!r}")


# ══════════════════════════════════════════════════════════════════════════
# the slot-addressed edit route the grid now uses
# ══════════════════════════════════════════════════════════════════════════

class TestEditingAFieldSlotByReference:
    @pytest.fixture(scope="class")
    def patched(self, client, auth, bank_template):
        job_id = _job(client, auth, "STMT-2024-03", bank_template)
        doc = _doc(client, auth, job_id)
        kv = doc["extracted_data"]["extracted_data"]
        entry = next(v for v in kv.values()
                     if isinstance(v, dict) and v.get("ref") and _text_value(v.get("value")))
        r = client.patch(f"/api/jobs/{job_id}/docs/{doc['id']}/fields/{entry['ref']}",
                         json={"value": "PATCHED 3141"}, headers=auth["acme"])
        return job_id, doc, entry, r

    def test_the_route_returns_the_updated_document(self, patched):
        _job_id, _doc_, entry, r = patched
        assert r.status_code == 200, r.text
        ed = r.json()["extracted_data"]
        assert ed["extracted_fields"][entry["ref"]] == "PATCHED 3141"
        assert ed["validation"]["confidence_map"][entry["ref"]] == "edited"

    @pytest.mark.parametrize("path", PATHS)
    def test_every_download_holds_it(self, client, auth, patched, path):
        job_id, *_ = patched
        assert "PATCHED 3141" in [c.value for c in _cells(client, auth, job_id, path)]

    def test_the_cell_says_it_was_edited(self, client, auth, patched):
        job_id, _d, entry, _r = patched
        cell = _cell_holding(client, auth, job_id, "template", "PATCHED 3141")
        assert cell.coordinate == entry["ref"]
        assert cell.comment.text.startswith("Edited in DocAgent")

    def test_an_address_the_document_does_not_have_is_refused(self, client, auth, patched):
        job_id, doc, _e, _r = patched
        r = client.patch(f"/api/jobs/{job_id}/docs/{doc['id']}/fields/ZZ999",
                         json={"value": "x"}, headers=auth["acme"])
        assert r.status_code == 404

    def test_another_tenant_cannot_edit(self, client, auth, patched):
        job_id, doc, entry, _r = patched
        other = "other"                            # a different tenant
        r = client.patch(f"/api/jobs/{job_id}/docs/{doc['id']}/fields/{entry['ref']}",
                         json={"value": "x"}, headers=auth[other])
        assert r.status_code in (403, 404), r.status_code
