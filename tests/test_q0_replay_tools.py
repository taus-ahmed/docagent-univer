"""Run Q, Q0 — the raw-response export and replay tools, offline.

A stored answer is produced by the dev stub provider (no network), written in
exactly the layout `tools/export_raw_responses.py` writes, and replayed by
`tools/replay_raw.py`. The replay must reach the same values as the original
run, must count (not invent) any call it has no stored answer for, and must
write a workbook. The exporter itself is exercised against a throwaway
SQLite database.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

PDF = ROOT / "tests" / "test_pdfs" / "CHQ-001847.pdf"
TPL = ROOT / "tests" / "gold" / "templates" / "cheque.json"


def _stub_run():
    import replay_raw
    replay_raw._setup()
    from connectors.stub_client import StubClient
    from extractor import run_extraction
    stub = StubClient()
    raws = []

    def extract(prompt="", system_instruction="", **kw):
        r = stub.extract_data(kw.get("text", ""), prompt, system_instruction)
        raws.append(r.raw_text)
        return r

    grid = json.loads(TPL.read_text(encoding="utf-8"))
    td = replay_raw.template_data_of({"name": "cheque", "document_type": "cheque",
                                      "description": json.dumps(grid), "columns_json": "[]"})
    (r,) = run_extraction(SimpleNamespace(llm=SimpleNamespace(extract=extract)), PDF, td)
    return grid, r.extracted_data, raws


@pytest.mark.skipif(not PDF.exists(), reason="CHQ-001847.pdf fixture missing")
def test_replay_reproduces_the_original_values(tmp_path, monkeypatch):
    import replay_raw
    grid, ed, raws = _stub_run()
    assert raws, "the stub run made no model call"
    assert any(v for v in ed["extracted_fields"].values()), "stub filled nothing"
    raw_root, src = tmp_path / "raw", tmp_path / "src"
    (raw_root / "9001" / "docs").mkdir(parents=True)
    src.mkdir()
    (src / PDF.name).write_bytes(PDF.read_bytes())
    (raw_root / "9001" / "template.json").write_text(json.dumps(
        {"name": "cheque", "document_type": "cheque", "description": json.dumps(grid),
         "columns_json": "[]"}), encoding="utf-8")
    (raw_root / "9001" / "docs" / "1.json").write_text(json.dumps(
        {"id": 1, "filename": PDF.name, "original_filename": PDF.name,
         "raw_llm_response": raws[0], "extraction_json": ed}), encoding="utf-8")
    monkeypatch.setattr(replay_raw, "RAW", raw_root)
    monkeypatch.setattr(replay_raw, "SOURCES", src)

    assert replay_raw.has_raw(9001)
    rep = replay_raw.replay_job(9001)
    assert not rep["skipped"]
    ((_meta, red, missing),) = rep["docs"]
    assert red["extracted_fields"] == ed["extracted_fields"]
    assert len(missing) == len(raws) - 1          # counted, never invented
    out = replay_raw.write_workbook(9001, rep, tmp_path / "out.xlsx")
    import openpyxl
    wb = openpyxl.load_workbook(out)
    assert "Legend" in wb.sheetnames


def test_a_missing_source_is_skipped_with_a_reason(tmp_path, monkeypatch):
    import replay_raw
    raw_root = tmp_path / "raw"
    (raw_root / "9002" / "docs").mkdir(parents=True)
    (raw_root / "9002" / "template.json").write_text("null", encoding="utf-8")
    (raw_root / "9002" / "docs" / "1.json").write_text(json.dumps(
        {"id": 1, "original_filename": "nowhere.pdf", "raw_llm_response": "{}"}), encoding="utf-8")
    monkeypatch.setattr(replay_raw, "RAW", raw_root)
    monkeypatch.setattr(replay_raw, "SOURCES", tmp_path)
    rep = replay_raw.replay_job(9002)
    assert rep["docs"] == [] and "nowhere.pdf" in rep["skipped"][0]


def test_exporter_is_read_only_and_never_prints_the_url(tmp_path, capsys):
    import export_raw_responses as X
    db = tmp_path / "t.db"
    c = sqlite3.connect(db)
    c.executescript("""
      CREATE TABLE extraction_jobs (id INTEGER, status TEXT, total_docs INTEGER,
        schema_id TEXT, created_at TEXT, progress_message TEXT);
      CREATE TABLE column_templates (id INTEGER, name TEXT, document_type TEXT,
        description TEXT, columns_json TEXT);
      CREATE TABLE document_results (id INTEGER, job_id INTEGER, filename TEXT,
        original_filename TEXT, model_used TEXT, raw_llm_response TEXT, extraction_json TEXT);
      INSERT INTO extraction_jobs VALUES (7, 'completed', 1, '3', 'x', '');
      INSERT INTO column_templates VALUES (3, 'T', 'invoice', '{"cells":{}}', '[]');
      INSERT INTO document_results VALUES (11, 7, 'a.pdf', 'a.pdf', 'm', '{"fields":{}}',
        '{"page_count": 2}');
    """)
    c.commit()
    before = db.read_bytes()
    url = f"sqlite:///{db}"
    out = X.export([7, 8], url, tmp_path / "raw")
    assert out == {7: {"docs": 1, "raw": 1, "template": True}}
    doc = json.loads((tmp_path / "raw" / "7" / "docs" / "11.json").read_text(encoding="utf-8"))
    assert doc["page_count"] == 2 and doc["raw_llm_response"] == '{"fields":{}}'
    assert db.read_bytes() == before
    printed = capsys.readouterr()
    assert str(db) not in printed.out + printed.err


def test_live_corpus_is_offline_by_default_and_caps_calls(capsys):
    import live_corpus as L
    assert L.main([]) == 0
    assert "no calls made" in capsys.readouterr().out
    assert len(json.loads(L.MANIFEST.read_text(encoding="utf-8"))["jobs"]) == 29

    class Router:
        n = 0
        def extract(self, **kw):
            Router.n += 1
            return SimpleNamespace(success=True, attempts=[{"cost_estimate": 0.3}])
    capped = L.CappedLLM(Router(), max_calls=60, max_cost=1.0)
    results = [capped.extract(prompt="p") for _ in range(10)]
    assert Router.n == 4                    # 4 x $0.30 crosses $1.00, then refused
    assert all(not r.success and "cap" in r.error for r in results[4:])
    capped2 = L.CappedLLM(Router(), max_calls=2, max_cost=99)
    Router.n = 0
    [capped2.extract() for _ in range(5)]
    assert Router.n == 2


def test_main_writes_per_job_folder_and_names_a_missing_answer(tmp_path, monkeypatch, capsys):
    """Phase 2: the workbook lands in replay_out/<job_id>/, and a document
    with no stored answer is named as such (job 68-70 shape)."""
    import replay_raw
    raw_root, src = tmp_path / "raw", tmp_path / "src"
    (raw_root / "9003" / "docs").mkdir(parents=True)
    src.mkdir()
    (src / PDF.name).write_bytes(PDF.read_bytes())
    (raw_root / "9003" / "template.json").write_text("null", encoding="utf-8")
    (raw_root / "9003" / "docs" / "1.json").write_text(json.dumps(
        {"id": 1, "original_filename": PDF.name, "raw_llm_response": None}), encoding="utf-8")
    monkeypatch.setattr(replay_raw, "RAW", raw_root)
    monkeypatch.setattr(replay_raw, "SOURCES", src)
    monkeypatch.setattr(replay_raw, "OUT", tmp_path / "out")
    assert replay_raw.main(["9003"]) == 0
    out = capsys.readouterr().out
    assert "no raw answer stored" in out
    assert (tmp_path / "out" / "9003" / "job_9003_replay.xlsx").exists()
