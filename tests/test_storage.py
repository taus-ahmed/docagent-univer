"""
Phase 8 — persistent storage.

Railway containers are ephemeral. Before this, an upload was written to the web
container's own disk and its path handed to the worker, so a restart between
upload and processing lost the file, and every redeploy emptied the schemas
directory that `get_schema_path()` reads.

These tests pin the three things that make a deploy safe: a file survives a
restart, a key cannot escape its root, and a file that is genuinely gone is an
ordinary None rather than an exception on its way to a 500.
"""
import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from app.core.storage import (  # noqa: E402
    StorageError, StorageService, _safe_key, _safe_segment,
)


# ── an in-memory stand-in for the object store ───────────────────────────────
class FakeS3:
    """Enough of the S3 API to exercise our use of it, with no network.

    Deliberately not a mock that records calls: it actually stores bytes, so a
    test can assert the FILE survived rather than that a method was called.
    """

    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise KeyError("NoSuchKey")

        class _Body:
            def __init__(self, data):
                self._d = data

            def read(self):
                return self._d
        return {"Body": _Body(self.objects[(Bucket, Key)])}

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise KeyError("NoSuchKey")
        return {}

    def delete_object(self, Bucket, Key):
        self.objects.pop((Bucket, Key), None)

    def list_objects_v2(self, Bucket, Prefix, **kw):
        keys = [k for (b, k) in self.objects if b == Bucket and k.startswith(Prefix)]
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}

    def delete_objects(self, Bucket, Delete):
        for o in Delete["Objects"]:
            self.objects.pop((Bucket, o["Key"]), None)

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return (f"https://example-bucket.test/{Params['Key']}"
                f"?X-Amz-Expires={ExpiresIn}&X-Amz-Signature=stub")


def _settings():
    """The settings object STORAGE ITSELF uses.

    Not `from app.config import settings` — tests/test_config_aliases.py calls
    importlib.reload(app.config) to check env-var aliases, which builds a NEW
    settings object while storage.py keeps the reference it bound at import.
    Patching the new one then changed nothing, and these tests passed alone and
    failed in the suite.
    """
    import app.core.storage as st
    return st.settings


@pytest.fixture
def local_store(tmp_path, monkeypatch):
    settings = _settings()
    monkeypatch.setattr(settings, "LOCAL_UPLOAD_DIR", tmp_path / "st" / "uploads")
    monkeypatch.setattr(settings, "LOCAL_OUTPUT_DIR", tmp_path / "st" / "outputs")
    monkeypatch.setattr(settings, "LOCAL_SCHEMAS_DIR", tmp_path / "st" / "schemas")
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")
    return StorageService()


@pytest.fixture
def s3_store(monkeypatch):
    settings = _settings()
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(settings, "S3_BUCKET", "docagent-test")
    fake = FakeS3()
    svc = StorageService()
    assert svc.backend == "s3", "fixture did not select the object-store backend"
    monkeypatch.setattr(svc, "_s3", lambda: fake)
    svc._fake = fake
    return svc


class TestAFileSurvivesARestart:
    """A restart is a new process reading storage it did not write. On the
    object store that is the whole point; on a local volume it means the bytes
    outlived the StorageService that put them there."""

    def test_the_object_store_keeps_the_file_across_a_new_process(self, s3_store,
                                                                 monkeypatch):
        key, _ = s3_store.save_upload(b"%PDF-1.7 invoice", "inv.pdf", 7,
                                      client_id="acme")

        # RESTART: a brand new service, as a redeployed container or a separate
        # worker process would have. It shares only the bucket.
        restarted = StorageService()
        monkeypatch.setattr(restarted, "_s3", lambda: s3_store._fake)

        assert restarted.exists(key)
        assert restarted.get_bytes(key) == b"%PDF-1.7 invoice"

    def test_a_local_volume_keeps_the_file_across_a_new_process(self, local_store):
        key, _ = local_store.save_upload(b"%PDF-1.7 invoice", "inv.pdf", 7,
                                         client_id="acme")
        restarted = StorageService()
        assert restarted.get_bytes(key) == b"%PDF-1.7 invoice"

    def test_an_ephemeral_disk_loses_it_and_says_so(self, local_store, tmp_path):
        """The situation being fixed, pinned so it cannot come back silently:
        with no volume the bytes are gone, and the read is a clean None."""
        import shutil
        key, _ = local_store.save_upload(b"data", "inv.pdf", 7, client_id="acme")
        shutil.rmtree(local_store.root)              # the container was replaced

        restarted = StorageService()
        assert restarted.exists(key) is False
        assert restarted.get_bytes(key) is None
        assert restarted.get_local_path(key) is None

    def test_the_worker_gets_a_readable_path_from_a_key_alone(self, s3_store,
                                                              monkeypatch):
        """The worker is handed keys, never paths — that is what lets a
        separate process read what the web process received."""
        key, _ = s3_store.save_upload(b"%PDF-1.7", "a.pdf", 3, client_id="acme")
        worker = StorageService()
        monkeypatch.setattr(worker, "_s3", lambda: s3_store._fake)

        path = worker.get_local_path(key)
        assert path is not None and path.exists()
        assert path.read_bytes() == b"%PDF-1.7"


class TestPathTraversalStaysDefeated:
    TRAVERSALS = [
        "../../etc/passwd",
        "clients/acme/../../../etc/passwd",
        "/etc/passwd",
        "C:\\Windows\\System32\\config\\SAM",
        "~/.ssh/id_rsa",
        "clients//acme/x",
        "clients/./acme/x",
        "",
    ]

    @pytest.mark.parametrize("bad", TRAVERSALS)
    def test_a_traversing_key_is_rejected_outright(self, bad):
        with pytest.raises(StorageError):
            _safe_key(bad)

    @pytest.mark.parametrize("bad", TRAVERSALS)
    def test_reads_of_a_traversing_key_are_none_not_an_exception(self, local_store, bad):
        """A read must never raise on its way to a 500, but it must also never
        succeed."""
        assert local_store.get_bytes(bad) is None
        assert local_store.get_local_path(bad) is None
        assert local_store.exists(bad) is False

    def test_a_traversing_filename_cannot_escape_its_job(self, local_store):
        key, _ = local_store.save_upload(b"x", "../../../../etc/passwd", 1,
                                         client_id="acme")
        assert key == "clients/acme/jobs/1/source/etc_passwd" or "passwd" in key
        assert ".." not in key
        written = local_store._local_path(key).resolve()
        assert str(written).startswith(str(local_store.root.resolve()))

    def test_a_traversing_tenant_id_cannot_escape_either(self, local_store):
        key = local_store.upload_key("../../root", 1, "a.pdf")
        assert ".." not in key
        assert key.startswith("clients/")

    def test_a_write_outside_the_root_is_refused(self, local_store):
        with pytest.raises(StorageError):
            local_store.put("../escaped.txt", b"x")
        with pytest.raises(StorageError):
            local_store.put("/tmp/escaped.txt", b"x")

    def test_segments_keep_something_usable(self):
        assert _safe_segment("Invoice 2024.pdf") == "Invoice_2024.pdf"
        assert _safe_segment("") == "unknown"
        assert _safe_segment("...") == "unknown"


class TestAMissingFileFailsCleanly:
    def test_reads_of_an_absent_key_return_none(self, local_store):
        gone = "clients/acme/jobs/9/source/never-existed.pdf"
        assert local_store.exists(gone) is False
        assert local_store.get_bytes(gone) is None
        assert local_store.get_local_path(gone) is None
        assert local_store.get_output_bytes(gone) is None

    def test_an_absent_key_in_the_object_store_is_also_none(self, s3_store):
        assert s3_store.get_bytes("clients/a/jobs/1/source/x.pdf") is None
        assert s3_store.exists("clients/a/jobs/1/source/x.pdf") is False

    def test_a_missing_schema_is_none_not_a_crash(self, local_store):
        assert local_store.get_schema_path("no-such-client") is None

    def test_deleting_something_absent_is_success_not_an_error(self, local_store):
        assert local_store.delete("clients/acme/jobs/1/source/gone.pdf") is True
        assert local_store.delete_prefix("clients/acme/jobs/999") == 0

    def test_the_worker_turns_a_missing_source_into_a_failed_document(self):
        """Not a 500 and not a stuck job: the document fails with a message
        that says what happened, and the job still completes."""
        from app.api.routes.extract import _resolve_source

        class _Gone:
            def get_local_path(self, key):
                return None
        assert _resolve_source(_Gone(), "clients/a/jobs/1/source/x.pdf") is None

    def test_a_write_that_did_not_happen_raises(self, s3_store, monkeypatch):
        """Reads are forgiving; writes are not. A write that silently failed
        would leave a job pointing at a key holding nothing."""
        def _boom(**kw):
            raise RuntimeError("bucket unreachable")
        monkeypatch.setattr(s3_store._fake, "put_object", _boom)
        with pytest.raises(StorageError):
            s3_store.put("clients/acme/jobs/1/source/a.pdf", b"x")


class TestTenancyAndRetention:
    """The two things Phase 11 needs from the layout, checked now so the
    decision is real rather than aspirational."""

    def test_every_tenant_owns_a_prefix(self, local_store):
        a = local_store.upload_key("acme", 1, "x.pdf")
        b = local_store.upload_key("globex", 1, "x.pdf")
        assert a.startswith("clients/acme/") and b.startswith("clients/globex/")
        assert not a.startswith(b.rsplit("/", 1)[0])

    def test_sources_can_be_deleted_while_outputs_remain(self, local_store):
        src, _ = local_store.save_upload(b"pdf", "a.pdf", 5, client_id="acme")
        out, _ = local_store.save_output(b"xlsx", "a.xlsx", 5, client_id="acme")

        assert local_store.delete_job_sources("acme", 5) == 1

        assert local_store.get_bytes(src) is None, "source should be gone"
        assert local_store.get_bytes(out) == b"xlsx", "output must survive"

    def test_deleting_one_tenants_job_leaves_another_alone(self, local_store):
        mine, _ = local_store.save_upload(b"mine", "a.pdf", 5, client_id="acme")
        theirs, _ = local_store.save_upload(b"theirs", "a.pdf", 5, client_id="globex")
        local_store.delete_job_sources("acme", 5)
        assert local_store.get_bytes(mine) is None
        assert local_store.get_bytes(theirs) == b"theirs"

    def test_the_object_store_signs_a_short_lived_url(self, s3_store):
        key, _ = s3_store.save_upload(b"x", "a.pdf", 1, client_id="acme")
        url = s3_store.signed_url(key, expires_in=120)
        assert url and "X-Amz-Expires=120" in url

    def test_an_expiry_cannot_be_set_beyond_an_hour(self, s3_store):
        key, _ = s3_store.save_upload(b"x", "a.pdf", 1, client_id="acme")
        assert "X-Amz-Expires=3600" in s3_store.signed_url(key, expires_in=999999)

    def test_the_local_backend_admits_it_cannot_sign(self, local_store):
        """None, not a permanent URL — a link that never expires must not be
        able to ship by accident."""
        key, _ = local_store.save_upload(b"x", "a.pdf", 1, client_id="acme")
        assert local_store.signed_url(key) is None
