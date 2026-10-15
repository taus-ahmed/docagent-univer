"""
The upload path holds ONE file's bytes at a time.

`_start_extraction_job` was factored out of `POST /api/extract/upload` so the
demo's sample documents could go through the same pipeline. The first version
of that refactor read every file into a list and then saved from the list,
which is simpler and multiplies peak memory by the batch size — up to 100 files
of up to 50MB here. It now does what the original route did: a validation pass
that reads a file, checks it and lets it go, then a save pass that reads it
again.

That is a memory property, and memory is not directly observable from a test,
so this measures the mechanism it rests on: each file is read ONCE PER PASS
(two reads per file, not one), and the second read returns the same bytes as
the first. A version that cached the batch would read each file once; a version
that forgot to rewind would read nothing the second time, and the job would
store empty files.
"""
import asyncio
import io

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


class TestEachFileIsReadOncePerPass:
    def test_a_batch_of_three_is_read_twice_each_not_once(
            self, client, auth, pdf_bytes, monkeypatch):
        from app.api.routes import extract as extract_mod

        reads: list[tuple[str, int]] = []
        original = extract_mod._IncomingUpload.read

        async def counting_read(self):
            content = await original(self)
            reads.append((self.filename, len(content)))
            return content

        monkeypatch.setattr(extract_mod._IncomingUpload, "read", counting_read)

        files = [("files", (f"doc{i}.pdf", io.BytesIO(pdf_bytes),
                            "application/pdf")) for i in range(3)]
        r = client.post("/api/extract/upload", headers=auth["acme2"],
                        data={"client_id": "acme_001"}, files=files)
        assert r.status_code == 202, r.text

        # Two passes over three files. One read each would mean the bytes were
        # being carried between the passes in a list.
        assert len(reads) == 6, reads
        # Every read of every file saw the whole file: the save pass is not
        # reading a spent stream.
        assert {name for name, _ in reads} == {"doc0.pdf", "doc1.pdf",
                                               "doc2.pdf"}
        assert {size for _, size in reads} == {len(pdf_bytes)}, reads

    def test_the_passes_are_in_order_validate_then_save(
            self, client, auth, pdf_bytes, monkeypatch):
        """Validation covers the WHOLE batch before anything is written, which
        is what makes a refused upload leave nothing behind."""
        from app.api.routes import extract as extract_mod

        events: list[str] = []
        original = extract_mod._IncomingUpload.read

        async def tracking_read(self):
            events.append(f"read:{self.filename}")
            return await original(self)

        monkeypatch.setattr(extract_mod._IncomingUpload, "read", tracking_read)

        from app.core.storage import get_storage
        storage = client.app.dependency_overrides.get(get_storage)
        assert storage is None, "this test assumes the real storage dependency"

        files = [("files", (f"doc{i}.pdf", io.BytesIO(pdf_bytes),
                            "application/pdf")) for i in range(2)]
        r = client.post("/api/extract/upload", headers=auth["acme2"],
                        data={"client_id": "acme_001"}, files=files)
        assert r.status_code == 202, r.text
        assert events == ["read:doc0.pdf", "read:doc1.pdf",
                          "read:doc0.pdf", "read:doc1.pdf"], events


class TestReadingTheSameSourceTwice:
    """The contract `_start_extraction_job` depends on, at the unit level."""

    def test_an_upload_gives_the_same_bytes_both_times(self):
        from fastapi import UploadFile

        from app.api.routes.extract import _IncomingUpload

        src = _IncomingUpload.from_upload(
            UploadFile(filename="x.pdf", file=io.BytesIO(b"abcdef")))
        assert asyncio.run(src.read()) == b"abcdef"
        assert asyncio.run(src.read()) == b"abcdef"

    def test_a_file_on_disk_gives_the_same_bytes_both_times(self, tmp_path):
        from app.api.routes.extract import _IncomingUpload

        p = tmp_path / "sample.pdf"
        p.write_bytes(b"%PDF-1.4 sample")
        src = _IncomingUpload.from_path(p)
        assert src.filename == "sample.pdf"
        assert asyncio.run(src.read()) == b"%PDF-1.4 sample"
        assert asyncio.run(src.read()) == b"%PDF-1.4 sample"
