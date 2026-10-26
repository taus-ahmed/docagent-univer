"""A page image is sized from its HEADER before anything decodes it (Run 15,
item 4).

The review screen's page route read an image source through the preprocessor,
which opened, converted and base64-encoded it whole, and then converted it
again to draw it. A PNG of a few hundred bytes can declare 40,000 x 40,000
pixels — 4.8 GB as RGB. PIL's `Image.open` is lazy and reads only the header,
so the size is known for free: it is checked against MAX_IMAGE_PIXELS first,
and the request is refused with a message saying so.
"""
from __future__ import annotations

import struct
import zlib

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()


def huge_png(width=40_000, height=40_000) -> bytes:
    """A valid PNG header declaring width x height, with a tiny IDAT."""
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)   # 8-bit grey
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"\x00" * 1024)) + chunk(b"IEND", b""))


def test_the_engine_refuses_before_decoding(tmp_path):
    import core.preprocessor as pre
    path = tmp_path / "bomb.png"
    path.write_bytes(huge_png())
    assert path.stat().st_size < 2000
    with pytest.raises(pre.ImageTooLarge, match="1600000000 pixels"):
        pre.open_image_bounded(path, limit=50_000_000)
    with pytest.raises(pre.ImageTooLarge):
        pre.preprocess_file(path)


def test_a_normal_image_opens_lazily(tmp_path):
    from PIL import Image
    import core.preprocessor as pre
    path = tmp_path / "ok.png"
    Image.new("RGB", (300, 200), "white").save(path)
    img = pre.open_image_bounded(path, limit=50_000_000)
    assert img.size == (300, 200)


@pytest.fixture
def bomb_job(db, users):
    from app.core.storage import get_storage
    from app.models.models import DocumentResult, ExtractionJob
    j = ExtractionJob(user_id=users["acme2"].id, client_id="acme_001",
                      status="completed", total_docs=1, input_source="upload")
    db.add(j); db.commit(); db.refresh(j)
    key, _ = get_storage().save_upload(huge_png(), "scan.png", j.id,
                                       client_id="acme_001")
    d = DocumentResult(job_id=j.id, filename="scan.png", original_filename="scan.png",
                       document_type="invoice", extraction_json="{}",
                       needs_review=True, s3_key=key)
    db.add(d); db.commit(); db.refresh(d)
    return j.id, d.id


@pytest.mark.parametrize("what", ["/image", ""])
def test_the_page_routes_refuse_a_huge_image_with_a_clear_error(
        client, auth, bomb_job, what):
    jid, did = bomb_job
    r = client.get(f"/api/jobs/{jid}/docs/{did}/pages/1{what}",
                   headers=auth["acme2"])
    assert r.status_code == 413, r.text[:300]
    assert "MAX_IMAGE_PIXELS" in r.json()["detail"]
