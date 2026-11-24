"""Replay stored model answers through the post-model pipeline (Run Q, Q0).

    backend\\.venv\\Scripts\\python.exe tools\\replay_raw.py 56 72

Reads local_docs/raw/<job_id>/ (written by tools/export_raw_responses.py),
finds each document's original file under local_docs/DocAgent_testdocs by
its file name, and runs `extractor.run_extraction` — the function the job
worker calls — with a model stand-in that answers:

  * the slot call   -> the stored `raw_llm_response`, verbatim;
  * inference       -> the stored `inferred_template` (no-template jobs);
  * anything else   -> a FAILED call ("no stored answer"), counted and
                       printed, never invented. Page recovery therefore
                       reports itself as not recovered on replay.

Everything after the model — grounding, confidence, completeness, the
writers — is the code on disk. The workbook goes to
local_docs/replay_out/<id>/job_<id>_replay.xlsx. No network, no key, no .env.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "local_docs" / "raw"
SOURCES = ROOT / "local_docs" / "DocAgent_testdocs"
OUT = ROOT / "local_docs" / "replay_out"


def _setup():
    os.environ["DOCAGENT_TEST_NO_DOTENV"] = "1"        # never read .env
    os.environ.setdefault("PRIMARY_LLM", "gemini")
    os.environ.setdefault("GEMINI_API_KEY", "replay-no-network")
    sys.path.insert(0, str(ROOT))
    from tests.harness.bootstrap import bootstrap, chdir_backend
    bootstrap()
    chdir_backend()


def raw_dir(job_id) -> Path:
    return RAW / str(job_id)


def has_raw(job_id) -> bool:
    return (raw_dir(job_id) / "docs").is_dir()


def load_job(job_id) -> dict:
    d = raw_dir(job_id)
    tpl = json.loads((d / "template.json").read_text(encoding="utf-8"))
    docs = [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((d / "docs").glob("*.json"), key=lambda p: int(p.stem))]
    return {"template": tpl, "docs": docs}


def find_source(name: str):
    if not name:
        return None
    hits = [p for p in SOURCES.rglob("*") if p.is_file() and p.name == name]
    return hits[0] if hits else None


class ReplayLLM:
    """The model stand-in: stored answers only."""

    def __init__(self, raw_slot: str, inferred=None):
        self.queue = [raw_slot] if raw_slot else []
        self.inferred = inferred
        self.missing = []

    def _resp(self, raw):
        from connectors.base import LLMResponse
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            parsed = None
        return LLMResponse(raw_text=raw, parsed_json=parsed, model_used="replay",
                           tokens_used=0, success=parsed is not None,
                           error="" if parsed is not None else "stored answer is not JSON")

    def _miss(self, what):
        from connectors.base import LLMResponse
        self.missing.append(what)
        return LLMResponse(raw_text="", success=False, model_used="replay",
                           error=f"replay: no stored answer for {what}")

    def extract(self, prompt="", system_instruction="", **kw):
        if (system_instruction or "").startswith("You are a document analyst"):
            if self.inferred:
                return self._resp(json.dumps(self.inferred))
            return self._miss("template inference")
        if self.queue:
            return self._resp(self.queue.pop(0))
        return self._miss("a further slot call (page recovery or a page chunk)")

    def classify(self, *a, **kw):
        return self._miss("classification")


def template_data_of(tpl):
    if not tpl:
        return None
    from app.models.models import ColumnTemplate
    from app.services.template_parsing import _parse_template
    t = ColumnTemplate(name=tpl.get("name") or "replay", document_type=tpl.get("document_type") or "other",
                       description=tpl.get("description"), columns_json=tpl.get("columns_json") or "[]")
    return _parse_template(t)


def replay_doc(doc: dict, template_data, source: Path):
    """[(extracted_data, missing_calls)] for one stored document."""
    from extractor import run_extraction
    import copy
    ed = doc.get("extraction_json") or {}
    llm = ReplayLLM(doc.get("raw_llm_response") or "", ed.get("inferred_template"))
    results = run_extraction(SimpleNamespace(llm=llm), source,
                             copy.deepcopy(template_data) if template_data else None)
    return [(r.extracted_data or {}, list(llm.missing), r) for r in results]


def replay_job(job_id):
    """Replays every document of a job; returns
    {"docs": [(doc_meta, extracted_data, missing)], "skipped": [reason]}."""
    _setup()
    job = load_job(job_id)
    td = template_data_of(job["template"])
    out = {"docs": [], "skipped": [], "template": job["template"]}
    for doc in job["docs"]:
        src = find_source(doc.get("original_filename") or doc.get("filename"))
        if not src:
            out["skipped"].append(f"{doc.get('original_filename')}: source not in local_docs/DocAgent_testdocs")
            continue
        if not doc.get("raw_llm_response"):
            out["skipped"].append(f"{doc.get('original_filename')}: no raw answer stored")
            continue
        for ed, missing, _r in replay_doc(doc, td, src):
            out["docs"].append((doc, ed, missing))
    return out


def write_workbook(job_id, replayed, path: Path):
    import openpyxl
    from app.models.models import DocumentResult
    from app.services.excel_slot import _write_excel
    from app.services.excel_slot import _write_inferred_sheets
    from app.services.excel_cells import _add_review_legend
    docs = []
    for i, (meta, ed, _m) in enumerate(replayed["docs"], 1):
        d = DocumentResult(id=i, job_id=int(job_id), filename=meta.get("filename"),
                           original_filename=meta.get("original_filename"),
                           extraction_json=json.dumps(ed, default=str),
                           needs_review=bool(ed.get("needs_review")), reviewed=False)
        docs.append(d)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Results"
    tpl = replayed.get("template")
    grid = None
    if tpl and tpl.get("description"):
        try:
            grid = json.loads(tpl["description"])
        except ValueError:
            grid = None
    if isinstance(grid, dict) and "cells" in grid:
        from app.services.template_parsing import _analyse_template_regions
        _write_excel(ws, docs, grid, _analyse_template_regions(grid), openpyxl)
    else:
        _write_inferred_sheets(wb, ws, docs, openpyxl)
    _add_review_legend(wb, docs)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("job_ids", nargs="+")
    a = ap.parse_args(argv)
    for jid in a.job_ids:
        if not has_raw(jid):
            print(f"job {jid}: no local_docs/raw/{jid} - run tools/export_raw_responses.py first")
            continue
        rep = replay_job(jid)
        for s in rep["skipped"]:
            print(f"job {jid}: skipped {s}")
        for meta, _ed, missing in rep["docs"]:
            if missing:
                print(f"job {jid}: {meta.get('original_filename')}: {len(missing)} call(s) had no "
                      f"stored answer ({sorted(set(missing))})")
        p = write_workbook(jid, rep, OUT / str(jid) / f"job_{jid}_replay.xlsx")
        print(f"job {jid}: {len(rep['docs'])} document(s) -> {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
