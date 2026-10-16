"""
The demo's activity trail: written for a demo tenant, invisible everywhere else.

`demo_activity` is append-only and nothing in the app reads it. The tests
therefore read the table directly, which is also what the reporting script
does — if these pass, the script has rows to print.

Four properties, in the order they matter:

  * the events are written for a demo account (login, failed login, upload,
    sample-document run, export, and each kind of refused upload);
  * NOTHING is written for anybody else, nor for the demo account while
    DEMO_CLIENT_IDS is unset;
  * a failing audit write never breaks the request it was describing;
  * the history cutoff does not touch this table — it hides a demo user's own
    history FROM THEM, and the trail is not theirs.
"""
import io
import json

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()


@pytest.fixture(autouse=True)
def _no_real_extraction(monkeypatch):
    import threading

    class _Inert(threading.Thread):
        def start(self):
            return None

    monkeypatch.setattr("app.api.routes.extract.threading.Thread", _Inert)


def _rows(db, client_id="pearx_demo", event=None):
    from app.models.models import DemoActivity
    q = db.query(DemoActivity).filter(DemoActivity.client_id == client_id)
    if event:
        q = q.filter(DemoActivity.event == event)
    return q.order_by(DemoActivity.id).all()


def _clear(db):
    """Start each test from a known state.

    The table is append-only IN THE APPLICATION; a test fixture emptying its
    own scratch database is not a code path, and without it these assertions
    would depend on test order.
    """
    from app.models.models import DemoActivity
    db.query(DemoActivity).delete()
    db.commit()


@pytest.fixture
def clean(db):
    _clear(db)
    yield
    _clear(db)


def _detail(row):
    return json.loads(row.detail) if row.detail else {}


def _upload(client, headers, pdf, *, name="doc.pdf", mime="application/pdf",
            client_id="pearx_demo", template_id=None):
    data = {"client_id": client_id}
    if template_id is not None:
        data["template_id"] = str(template_id)
    return client.post("/api/extract/upload", headers=headers, data=data,
                       files=[("files", (name, io.BytesIO(pdf), mime))])


# ── the shape of the table ───────────────────────────────────────────────────

class TestTheTableItself:
    def test_it_has_no_foreign_keys(self):
        """An audit row must outlive what it describes: a FK to
        `extraction_jobs` would let a cascade delete the evidence, and a FK to
        `users` would make the row a reason a user cannot be removed."""
        from app.models.models import DemoActivity
        assert DemoActivity.__table__.foreign_keys == set()

    def test_it_is_created_by_the_projects_own_table_creation(self):
        """`init_db()` is `Base.metadata.create_all`, and this model is in
        `Base` — which is how all six existing tables come into being."""
        from app.models.models import Base
        assert "demo_activity" in Base.metadata.tables

    def test_two_logins_are_two_rows_not_an_update(
            self, client, demo_auth, demo_on, demo_user, db, clean):
        for _ in range(2):
            client.post("/api/auth/login",
                        json={"username": demo_user.username,
                              "password": "pw-pearx2027"})
        rows = _rows(db, event="login")
        assert len(rows) == 2
        assert rows[0].id != rows[1].id


# ── what gets written ────────────────────────────────────────────────────────

class TestEventsAreRecordedForADemoAccount:
    def test_a_successful_login(self, client, demo_on, demo_user, db, clean):
        r = client.post("/api/auth/login",
                        json={"username": demo_user.username,
                              "password": "pw-pearx2027"})
        assert r.status_code == 200, r.text
        row, = _rows(db, event="login")
        assert row.user_id == demo_user.id
        assert row.client_id == "pearx_demo"
        assert _detail(row)["username"] == demo_user.username
        assert "pw-" not in (row.detail or ""), "a password reached the trail"

    def test_a_failed_login_on_a_known_demo_account(
            self, client, demo_on, demo_user, db, clean):
        r = client.post("/api/auth/login",
                        json={"username": demo_user.username,
                              "password": "wrong-on-purpose"})
        assert r.status_code == 401
        row, = _rows(db, event="login_failed")
        assert row.user_id == demo_user.id
        assert _detail(row)["username"] == demo_user.username
        assert "wrong-on-purpose" not in (row.detail or "")

    def test_a_failed_login_on_an_unknown_username_records_nothing(
            self, client, demo_on, db, clean):
        """The documented gap: nothing says which tenant the attempt was aimed
        at, and a guessed client_id would be worse than a missing row."""
        client.post("/api/auth/login",
                    json={"username": "nobody-at-all", "password": "x"})
        assert _rows(db) == []

    def test_an_upload(self, client, demo_auth, demo_on, demo_templates,
                       pdf_bytes, db, clean):
        r = _upload(client, demo_auth, pdf_bytes, name="statement.pdf",
                    template_id=demo_templates["demo_private"].id)
        assert r.status_code == 202, r.text
        row, = _rows(db, event="upload")
        assert row.job_id == r.json()["job_id"]
        d = _detail(row)
        assert d["files"] == [{"filename": "statement.pdf",
                               "size_bytes": len(pdf_bytes)}]
        assert d["template"] == "demo_private"      # the NAME, not the grid
        assert set(d) <= {"files", "template", "template_id",
                          "options_requested"}, d

    def test_a_sample_document_run_is_its_own_event(
            self, client, demo_auth, demo_on, demo_docs, db, clean):
        r = client.post("/api/demo/sample-docs/sample-invoice.pdf/extract",
                        headers=demo_auth)
        assert r.status_code == 202, r.text
        assert _rows(db, event="upload") == []
        row, = _rows(db, event="sample_extract")
        assert row.job_id == r.json()["job_id"]
        assert _detail(row)["files"][0]["filename"] == "sample-invoice.pdf"

    def test_every_export_route(self, client, demo_auth, demo_on, db, clean,
                                demo_user, users):
        from app.models.models import DocumentResult, ExtractionJob

        j = ExtractionJob(user_id=demo_user.id, client_id="pearx_demo",
                          status="completed", total_docs=1, successful=1,
                          input_source="upload")
        db.add(j)
        db.commit()
        db.refresh(j)
        db.add(DocumentResult(job_id=j.id, filename="x.pdf",
                              document_type="sales_invoice",
                              overall_confidence="high",
                              extraction_json=json.dumps({"extracted_data": {
                                  "Total": {"value": "1", "confidence": "high"}}})))
        db.commit()

        assert client.get(f"/api/jobs/{j.id}/export",
                          headers=demo_auth).status_code == 200
        assert client.get(f"/api/jobs/{j.id}/export/zip",
                          headers=demo_auth).status_code == 200
        assert client.post("/api/export/combined", headers=demo_auth,
                           json={"job_id": j.id}).status_code == 200
        assert client.post("/api/export/perfile", headers=demo_auth,
                           json={"job_id": j.id}).status_code == 200

        kinds = [_detail(r)["kind"] for r in _rows(db, event="export")]
        assert sorted(kinds) == ["combined", "perfile", "template", "zip"]
        assert {r.job_id for r in _rows(db, event="export")} == {j.id}


class TestRefusedUploadsAreRecordedWithTheirReason:
    def _reason(self, db):
        rows = _rows(db, event="upload_refused")
        assert len(rows) == 1, rows
        return _detail(rows[0])

    def test_a_scan(self, client, demo_auth, demo_on, scanned_pdf_bytes, db,
                    clean):
        r = _upload(client, demo_auth, scanned_pdf_bytes, name="scan.pdf")
        assert r.status_code == 422
        d = self._reason(db)
        assert d["reason"] == "scanned" and d["status"] == 422
        assert d["filename"] == "scan.pdf"

    def test_a_file_over_the_demo_ceiling(self, client, demo_auth, demo_on,
                                          pdf_bytes, db, clean):
        padded = pdf_bytes + b"\n% " + b"x" * (11 * 1024 * 1024)
        r = _upload(client, demo_auth, padded, name="big.pdf")
        assert r.status_code == 400
        assert self._reason(db)["reason"] == "too_large"

    def test_the_quota(self, client, demo_auth, demo_on, pdf_bytes, db,
                       demo_user, monkeypatch, clean):
        from app.config import settings
        from app.models.models import ExtractionJob
        used = db.query(ExtractionJob).filter(
            ExtractionJob.user_id == demo_user.id).count()
        monkeypatch.setattr(settings, "DEMO_MAX_UPLOADS", used)
        r = _upload(client, demo_auth, pdf_bytes)
        assert r.status_code == 429
        assert self._reason(db)["reason"] == "quota"

    def test_uploads_disabled(self, client, demo_auth, demo_on, pdf_bytes, db,
                              monkeypatch, clean):
        from app.config import settings
        monkeypatch.setattr(settings, "DEMO_UPLOADS_ENABLED", False)
        r = _upload(client, demo_auth, pdf_bytes)
        assert r.status_code == 403
        assert self._reason(db)["reason"] == "uploads_disabled"

    def test_the_products_own_refusal_is_NOT_in_the_demo_trail(
            self, client, demo_auth, demo_on, db, clean):
        """A `.yaml` upload is refused by the DEMO (PDF only) — but a file type
        the product itself rejects is not a demo rule, and `demo_reason` is
        what tells them apart."""
        r = _upload(client, demo_auth, b"x", name="thing.exe",
                    mime="application/octet-stream")
        assert r.status_code == 400
        assert _rows(db, event="upload_refused") == []


# ── and nothing for anyone else ──────────────────────────────────────────────

class TestNothingIsRecordedForAnybodyElse:
    def test_a_normal_users_whole_session_writes_no_rows(
            self, client, auth, users, demo_on, pdf_bytes, db, clean,
            scanned_pdf_bytes):
        from app.models.models import DemoActivity

        client.post("/api/auth/login",
                    json={"username": users["acme2"].username,
                          "password": "pw-acme_user"})
        client.post("/api/auth/login",
                    json={"username": users["acme2"].username,
                          "password": "wrong"})
        up = _upload(client, auth["acme2"], pdf_bytes, client_id="acme_001")
        assert up.status_code == 202
        _upload(client, auth["acme2"], scanned_pdf_bytes, name="scan.pdf",
                client_id="acme_001")
        assert db.query(DemoActivity).count() == 0

    def test_with_the_variable_unset_the_demo_user_writes_no_rows(
            self, client, demo_auth, demo_user, pdf_bytes, db, clean):
        from app.models.models import DemoActivity

        client.post("/api/auth/login",
                    json={"username": demo_user.username,
                          "password": "pw-pearx2027"})
        assert _upload(client, demo_auth, pdf_bytes).status_code == 202
        assert db.query(DemoActivity).count() == 0


# ── the audit must never be the reason a request fails ───────────────────────

class TestAFailingAuditDoesNotBreakTheRequest:
    @pytest.fixture
    def broken_audit(self, monkeypatch):
        import app.core.demo_audit as audit

        def boom(*a, **k):
            raise RuntimeError("audit table is on fire")

        monkeypatch.setattr(audit, "_write", boom)

    def test_a_login_still_succeeds(self, client, demo_on, demo_user,
                                    broken_audit, capfd):
        r = client.post("/api/auth/login",
                        json={"username": demo_user.username,
                              "password": "pw-pearx2027"})
        assert r.status_code == 200, r.text
        assert "[DEMO-AUDIT]" in capfd.readouterr().out

    def test_an_upload_still_succeeds(self, client, demo_auth, demo_on,
                                      pdf_bytes, broken_audit, db):
        r = _upload(client, demo_auth, pdf_bytes)
        assert r.status_code == 202, r.text
        # ...and the job it describes is really there.
        from app.models.models import ExtractionJob
        assert db.query(ExtractionJob).filter(
            ExtractionJob.id == r.json()["job_id"]).first() is not None

    def test_a_refusal_still_refuses_with_its_own_message(
            self, client, demo_auth, demo_on, scanned_pdf_bytes, broken_audit):
        r = _upload(client, demo_auth, scanned_pdf_bytes, name="scan.pdf")
        assert r.status_code == 422
        assert r.json()["detail"].startswith("This looks like a scanned")

    def test_an_export_still_downloads(self, client, demo_auth, demo_on,
                                       broken_audit, db, demo_user):
        from app.models.models import DocumentResult, ExtractionJob
        j = ExtractionJob(user_id=demo_user.id, client_id="pearx_demo",
                          status="completed", total_docs=1, successful=1)
        db.add(j)
        db.commit()
        db.refresh(j)
        db.add(DocumentResult(job_id=j.id, filename="x.pdf",
                              extraction_json=json.dumps({"extracted_data": {}})))
        db.commit()
        assert client.get(f"/api/jobs/{j.id}/export",
                          headers=demo_auth).status_code == 200


# ── the history cutoff and the trail are different things ────────────────────

class TestTheHistoryCutoffDoesNotTouchTheTrail:
    def test_an_old_audit_row_is_not_hidden_or_deleted(
            self, client, demo_auth, demo_on, db, clean, monkeypatch,
            demo_user):
        """The cutoff hides the demo user's own job history FROM THEM. The
        trail is not theirs and is not filtered by it."""
        from datetime import datetime

        from app.config import settings
        from app.models.models import DemoActivity

        old = DemoActivity(user_id=demo_user.id, client_id="pearx_demo",
                           event="login", ts=datetime(2026, 1, 1, 0, 0, 0),
                           detail=json.dumps({"username": "pearx2027"}))
        db.add(old)
        db.commit()
        before = db.query(DemoActivity).count()

        monkeypatch.setattr(settings, "DEMO_HISTORY_CUTOFF",
                            "2026-06-01T00:00:00Z")
        assert client.get("/api/jobs", headers=demo_auth).status_code == 200
        assert client.get("/api/jobs/999999",
                          headers=demo_auth).status_code == 404

        db.expire_all()
        assert db.query(DemoActivity).count() == before
        row = db.query(DemoActivity).filter(
            DemoActivity.id == old.id).first()
        assert row is not None and row.ts == datetime(2026, 1, 1, 0, 0, 0)

    def test_listing_jobs_writes_no_audit_rows_at_all(
            self, client, demo_auth, demo_on, db, clean):
        """Reading is not an event. Only the five things that DO something are
        recorded, so the trail stays readable."""
        from app.models.models import DemoActivity
        for _ in range(3):
            client.get("/api/jobs", headers=demo_auth)
            client.get("/api/templates", headers=demo_auth)
            client.get("/api/auth/me", headers=demo_auth)
        assert db.query(DemoActivity).count() == 0


# ── the reporting script's own formatting ────────────────────────────────────

class TestTheReportScript:
    def test_a_stored_utc_timestamp_prints_as_phoenix_wall_clock(self):
        """Phoenix is UTC-7 all year (no DST since 1968), so 19:30 UTC is
        12:30 the same day."""
        from datetime import datetime
        import sys
        sys.path.insert(0, str(bs.BACKEND_DIR))
        from scripts.demo_activity_report import _fmt_ts, _phoenix

        out = _fmt_ts(datetime(2026, 7, 4, 19, 30, 0), _phoenix())
        assert out.startswith("2026-07-04 12:30:00")

    def test_utc_is_printed_as_utc_when_asked(self):
        from datetime import datetime
        from scripts.demo_activity_report import _fmt_ts

        assert _fmt_ts(datetime(2026, 7, 4, 19, 30, 0), None) == \
            "2026-07-04 19:30:00 UTC"

    def test_the_detail_line_names_files_and_never_shows_content(self):
        from scripts.demo_activity_report import _fmt_detail

        line = _fmt_detail(json.dumps({
            "files": [{"filename": "inv.pdf", "size_bytes": 4096}],
            "template": "Bank statement"}))
        assert "inv.pdf (4 KB)" in line and "template=Bank statement" in line
