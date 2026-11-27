"""Run T1, 2f: every PDF record is stored with its perception, so exports
and regeneration never need the uploaded file."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.harness import bootstrap as bs  # noqa: E402

bs.bootstrap()

from tests import t1_pdf  # noqa: E402


def _pdf(tmp_path, n=2):
    pages = [[(60, 700, f"Page {i + 1} heading"), (60, 680, f"07/0{i + 1}/2026 Item 10.00")]
             for i in range(n)]
    return t1_pdf.make(tmp_path / "s.pdf", pages)


class TestStore:
    def test_packed_for_covers_the_records_pages(self, tmp_path):
        from app.services import perception_store as PS
        import perception as P
        pdf = _pdf(tmp_path, 3)
        cache = {}
        whole = P.unpack(PS.packed_for(pdf, {}, cache))
        assert [p["page"] for p in whole["pages"]] == [1, 2, 3]
        part = P.unpack(PS.packed_for(pdf, {"source_pages": [2, 3]}, cache))
        assert [p["page"] for p in part["pages"]] == [2, 3]
        assert part["version"] == P.PERCEPTION_VERSION
        assert len(cache) == 1                      # read once per file

    def test_non_pdf_and_unreadable_store_nothing(self, tmp_path):
        from app.services import perception_store as PS
        img = tmp_path / "x.png"
        img.write_bytes(b"not a png")
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"%PDF-1.4 garbage")
        assert PS.packed_for(img, {}, {}) is None
        assert PS.packed_for(bad, {}, {}) is None

    def test_stored_reads_it_back_without_the_file(self, tmp_path):
        from app.services import perception_store as PS
        pdf = _pdf(tmp_path)
        packed = PS.packed_for(pdf, {}, {})
        pdf.unlink()                                 # the upload is gone
        doc = PS.stored(SimpleNamespace(perception_json=packed))
        assert "Page 1 heading" in [ln["text"] for ln in doc["pages"][0]["lines"]]

    def test_the_column_exists_on_the_model(self):
        from app.models.models import DocumentResult
        assert "perception_json" in DocumentResult.__table__.columns
