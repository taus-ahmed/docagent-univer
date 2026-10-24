"""
Two things a demo account does not get: the half-built extras, and its own
test history.

OPTIONS. "Additional Options" offers categorisation, charts, an AI summary and
anomaly detection. Three of them are real work the server does after
extraction (`_run_extraction_sync` tests for `"categorize"`, `"summary"` and
`"anomaly"`); `graphs` is drawn in the browser and never reaches the server.
None are shown off in the demo, so the frontend will not let one be selected
and the backend forces them off — WITHOUT rejecting the request, because a
cosmetic limit must not become a failed upload in front of an audience.

HISTORY. `DEMO_HISTORY_CUTOFF` hides what the account did before a moment in
time. It is a VIEW: no row is deleted or modified, a non-demo tenant never
sees the filter, and with the variable unset nothing is hidden from anyone.
The quota counts the same jobs the user can see — otherwise an allowance
already spent by our own test runs would refuse their first upload.
"""
import io
from datetime import datetime

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

BEFORE = datetime(2026, 1, 1, 12, 0, 0)
CUTOFF = "2026-06-01T00:00:00Z"
AFTER = datetime(2026, 9, 1, 12, 0, 0)


@pytest.fixture
def thread_kwargs(monkeypatch):
    """The kwargs the route hands the worker thread, without running it."""
    import threading

    seen = []

    class _Inert(threading.Thread):
        def __init__(self, *a, **kw):
            seen.append(kw)
            super().__init__(*a, **kw)

        def start(self):
            return None

    monkeypatch.setattr("app.api.routes.extract.threading.Thread", _Inert)
    return seen


def _options_sent(seen):
    assert seen, "no extraction thread was started"
    return (seen[-1].get("kwargs") or {}).get("options")


def _upload(client, headers, pdf, *, options, client_id="pearx_demo"):
    import json
    return client.post(
        "/api/extract/upload", headers=headers,
        data={"client_id": client_id, "options": json.dumps(options)},
        files=[("files", ("doc.pdf", io.BytesIO(pdf), "application/pdf"))])


# ── 1. the post-extraction options ───────────────────────────────────────────

ASKED = ["categorize", "summary", "anomaly"]


class TestTheDemoRunsNoneOfTheExtras:
    def test_the_request_is_accepted_and_the_options_are_dropped(
            self, client, demo_auth, demo_on, pdf_bytes, thread_kwargs):
        r = _upload(client, demo_auth, pdf_bytes, options=ASKED)
        assert r.status_code == 202, r.text          # NOT rejected
        assert _options_sent(thread_kwargs) == []

    def test_it_says_so_in_the_log(
            self, client, demo_auth, demo_on, pdf_bytes, thread_kwargs, capfd):
        """A demo request asking for one came from a stale page or a direct
        API call. Worth a line; not worth an error."""
        _upload(client, demo_auth, pdf_bytes, options=ASKED)
        out = capfd.readouterr().out
        assert "[DEMO]" in out and "forced OFF" in out
        assert "categorize" in out

    def test_a_sample_document_run_drops_them_too(
            self, client, demo_auth, demo_on, demo_docs, thread_kwargs):
        """The other door. It shares `_start_extraction_job`, which is why it
        cannot be the one that forgets."""
        import json
        r = client.post("/api/demo/sample-docs/sample-invoice.pdf/extract",
                        headers=demo_auth,
                        data={"options": json.dumps(ASKED)})
        assert r.status_code == 202, r.text
        assert _options_sent(thread_kwargs) == []

    def test_a_demo_upload_with_no_options_is_unchanged(
            self, client, demo_auth, demo_on, pdf_bytes, thread_kwargs):
        r = _upload(client, demo_auth, pdf_bytes, options=[])
        assert r.status_code == 202, r.text
        assert _options_sent(thread_kwargs) == []


class TestEveryoneElseKeepsTheirOptions:
    def test_a_normal_user_gets_exactly_what_they_asked_for(
            self, client, auth, demo_on, pdf_bytes, thread_kwargs):
        r = _upload(client, auth["acme2"], pdf_bytes, options=ASKED,
                    client_id="acme_001")
        assert r.status_code == 202, r.text
        assert _options_sent(thread_kwargs) == ASKED

    def test_with_the_variable_unset_the_demo_user_keeps_them_too(
            self, client, demo_auth, pdf_bytes, thread_kwargs):
        r = _upload(client, demo_auth, pdf_bytes, options=ASKED)
        assert r.status_code == 202, r.text
        assert _options_sent(thread_kwargs) == ASKED

    def test_the_filter_itself(self, demo_user, users, demo_on):
        from app.core.demo import DEMO_BLOCKED_OPTIONS, filter_options

        assert filter_options(demo_user, list(DEMO_BLOCKED_OPTIONS)) == []
        assert filter_options(demo_user, []) == []
        for u in users.values():
            assert filter_options(u, ASKED) == ASKED


# ── 2. the history cutoff ────────────────────────────────────────────────────

@pytest.fixture
def cutoff_on(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "DEMO_HISTORY_CUTOFF", CUTOFF)
    return CUTOFF


@pytest.fixture(scope="module")
def dated_jobs(db, demo_user, users):
    """One old and one new job for the demo account, and the same for acme.

    `created_at` is written explicitly, which is the whole point of the
    fixture: `ExtractionJob.created_at` is a NAIVE UTC `DateTime`
    (`default=datetime.utcnow`), and the cutoff is compared against it in that
    same convention.
    """
    from app.models.models import ExtractionJob

    made = {}
    spec = [
        ("demo_old", demo_user.id, "pearx_demo", BEFORE),
        ("demo_new", demo_user.id, "pearx_demo", AFTER),
        ("acme_old", users["acme"].id, "acme_001", BEFORE),
        ("acme_new", users["acme"].id, "acme_001", AFTER),
    ]
    for key, uid, cid, when in spec:
        j = ExtractionJob(user_id=uid, client_id=cid, status="completed",
                          total_docs=1, successful=1, input_source="upload",
                          notes=key, created_at=when)
        db.add(j)
        db.commit()
        db.refresh(j)
        made[key] = j
    return made


def _job_ids(client, headers):
    r = client.get("/api/jobs?limit=200", headers=headers)
    assert r.status_code == 200, r.text
    return {j["id"] for j in r.json()}


class TestTheHistoryCutoffHidesTheOldRuns:
    def test_the_old_job_is_absent_from_the_demo_users_list(
            self, client, demo_auth, demo_on, cutoff_on, dated_jobs):
        ids = _job_ids(client, demo_auth)
        assert dated_jobs["demo_old"].id not in ids
        assert dated_jobs["demo_new"].id in ids

    def test_the_old_job_is_not_fetchable_by_id_either(
            self, client, demo_auth, demo_on, cutoff_on, dated_jobs):
        """Hidden from the list but served by id would leave it one bookmark
        away, with its results and its export."""
        old = dated_jobs["demo_old"].id
        assert client.get(f"/api/jobs/{old}",
                          headers=demo_auth).status_code == 404
        assert client.get(f"/api/jobs/{old}/results",
                          headers=demo_auth).status_code == 404
        assert client.get(f"/api/jobs/{old}/export",
                          headers=demo_auth).status_code == 404
        assert client.get(f"/api/jobs/{dated_jobs['demo_new'].id}",
                          headers=demo_auth).status_code == 200

    def test_a_NON_demo_user_sees_both_of_theirs(
            self, client, auth, demo_on, cutoff_on, dated_jobs):
        ids = _job_ids(client, auth["acme"])
        assert {dated_jobs["acme_old"].id, dated_jobs["acme_new"].id} <= ids
        assert client.get(f"/api/jobs/{dated_jobs['acme_old'].id}",
                          headers=auth["acme"]).status_code == 200

    def test_with_DEMO_CLIENT_IDS_unset_the_demo_user_sees_both_of_theirs(
            self, client, demo_auth, cutoff_on, dated_jobs):
        """The cutoff is set, but this account is not a demo tenant."""
        ids = _job_ids(client, demo_auth)
        assert {dated_jobs["demo_old"].id, dated_jobs["demo_new"].id} <= ids

    def test_with_the_cutoff_unset_the_demo_user_sees_both_of_theirs(
            self, client, demo_auth, demo_on, dated_jobs):
        """A demo tenant, but no cutoff: the shipped default hides nothing."""
        ids = _job_ids(client, demo_auth)
        assert {dated_jobs["demo_old"].id, dated_jobs["demo_new"].id} <= ids

    def test_nothing_was_deleted_or_modified(
            self, client, demo_auth, demo_on, cutoff_on, dated_jobs, db):
        from app.models.models import ExtractionJob
        _job_ids(client, demo_auth)
        row = db.query(ExtractionJob).filter(
            ExtractionJob.id == dated_jobs["demo_old"].id).first()
        assert row is not None
        assert row.created_at == BEFORE
        assert row.status == "completed"

    def test_templates_are_not_affected(
            self, client, demo_auth, demo_on, cutoff_on, demo_templates):
        """The cutoff is about history, not about what the demo can extract
        with. A template older than the cutoff is still offered."""
        r = client.get("/api/templates", headers=demo_auth)
        assert r.status_code == 200, r.text
        assert {"demo_private", "demo_owned_default"} <= \
            {t["name"] for t in r.json()}


class TestTheQuotaCountsOnlyWhatIsVisible:
    def test_a_hidden_job_does_not_spend_the_allowance(
            self, client, demo_auth, demo_on, cutoff_on, dated_jobs, db,
            demo_user, pdf_bytes, monkeypatch, thread_kwargs):
        """Two jobs exist, one of them hidden. With a ceiling of 2 the upload
        must go through, because only one job counts."""
        from app.config import settings
        from app.models.models import ExtractionJob

        visible = db.query(ExtractionJob).filter(
            ExtractionJob.user_id == demo_user.id,
            ExtractionJob.created_at >= datetime(2026, 6, 1)).count()
        hidden = db.query(ExtractionJob).filter(
            ExtractionJob.user_id == demo_user.id,
            ExtractionJob.created_at < datetime(2026, 6, 1)).count()
        assert hidden >= 1, "the fixture's pre-cutoff job is missing"

        monkeypatch.setattr(settings, "DEMO_MAX_UPLOADS", visible + 1)
        assert _upload(client, demo_auth, pdf_bytes,
                       options=[]).status_code == 202

    def test_the_same_ceiling_refuses_once_the_visible_jobs_reach_it(
            self, client, demo_auth, demo_on, cutoff_on, dated_jobs, db,
            demo_user, pdf_bytes, monkeypatch):
        from app.config import settings
        from app.models.models import ExtractionJob

        visible = db.query(ExtractionJob).filter(
            ExtractionJob.user_id == demo_user.id,
            ExtractionJob.created_at >= datetime(2026, 6, 1)).count()
        monkeypatch.setattr(settings, "DEMO_MAX_UPLOADS", visible)
        r = _upload(client, demo_auth, pdf_bytes, options=[])
        assert r.status_code == 429, r.text

    def test_without_the_cutoff_the_hidden_jobs_count_again(
            self, client, demo_auth, demo_on, dated_jobs, db, demo_user,
            pdf_bytes, monkeypatch):
        """No `cutoff_on`: every job on the account counts, including the old
        ones. This is the control for the test above."""
        from app.config import settings
        from app.models.models import ExtractionJob

        visible = db.query(ExtractionJob).filter(
            ExtractionJob.user_id == demo_user.id,
            ExtractionJob.created_at >= datetime(2026, 6, 1)).count()
        monkeypatch.setattr(settings, "DEMO_MAX_UPLOADS", visible + 1)
        r = _upload(client, demo_auth, pdf_bytes, options=[])
        assert r.status_code == 429, (
            "the pre-cutoff jobs were not counted even with no cutoff set")


class TestReadingTheCutoffItself:
    def test_the_three_spellings_mean_the_same_instant(self, monkeypatch):
        from app.config import settings
        from app.core.demo import history_cutoff

        want = datetime(2026, 6, 1, 0, 0, 0)
        for raw in ("2026-06-01T00:00:00Z", "2026-06-01T00:00:00+00:00",
                    "2026-06-01T00:00:00"):
            monkeypatch.setattr(settings, "DEMO_HISTORY_CUTOFF", raw)
            got = history_cutoff()
            assert got == want, raw
            assert got.tzinfo is None, "must be naive, like created_at"

    def test_an_offset_is_converted_to_utc(self, monkeypatch):
        from app.config import settings
        from app.core.demo import history_cutoff

        monkeypatch.setattr(settings, "DEMO_HISTORY_CUTOFF",
                            "2026-06-01T02:00:00+02:00")
        assert history_cutoff() == datetime(2026, 6, 1, 0, 0, 0)

    def test_unset_is_off(self, monkeypatch):
        from app.config import settings
        from app.core.demo import history_cutoff

        monkeypatch.setattr(settings, "DEMO_HISTORY_CUTOFF", "")
        assert history_cutoff() is None

    def test_a_bad_value_is_ignored_and_logged(self, monkeypatch, capfd):
        """Not "hide everything" and not "hide nothing, silently" — a config
        mistake should be visible and harmless."""
        import app.core.demo as demo_mod
        from app.config import settings

        monkeypatch.setattr(demo_mod, "_warned_bad_cutoff", False)
        monkeypatch.setattr(settings, "DEMO_HISTORY_CUTOFF", "last Tuesday")
        assert demo_mod.history_cutoff() is None
        out = capfd.readouterr().out
        assert "DEMO_HISTORY_CUTOFF" in out and "IGNORED" in out

    def test_a_bad_value_hides_nothing_from_the_demo_user(
            self, client, demo_auth, demo_on, dated_jobs, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "DEMO_HISTORY_CUTOFF", "nonsense")
        ids = _job_ids(client, demo_auth)
        assert {dated_jobs["demo_old"].id, dated_jobs["demo_new"].id} <= ids

    def test_the_warning_is_printed_once_not_per_request(
            self, client, demo_auth, demo_on, monkeypatch, capfd):
        import app.core.demo as demo_mod
        from app.config import settings

        monkeypatch.setattr(demo_mod, "_warned_bad_cutoff", False)
        monkeypatch.setattr(settings, "DEMO_HISTORY_CUTOFF", "nope")
        for _ in range(3):
            client.get("/api/jobs", headers=demo_auth)
        assert capfd.readouterr().out.count("DEMO_HISTORY_CUTOFF") == 1
