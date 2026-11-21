"""Export stored model answers for replay (Run Q, Q0). READ-ONLY.

    backend\\.venv\\Scripts\\python.exe tools\\export_raw_responses.py 56 72 73

Reads the database named by the DATABASE_URL environment variable of the
person running it. The URL is never printed, logged or written anywhere.
Every statement is a SELECT, inside a READ ONLY transaction on PostgreSQL.

For each job id it writes local_docs/raw/<job_id>/ (git-ignored):

    job.json                 status, total_docs, schema_id, created_at, error
    template.json            the template the job used (name, doc type, grid), or null
    docs/<doc_id>.json       one per document result:
                               filename, original_filename, model_used,
                               page_count (from the stored extraction, if any),
                               raw_llm_response (the model's exact answer, or null
                               when RAW_RESPONSE_RETENTION_DAYS has cleared it),
                               extraction_json (the stored extraction, as exported)

What is stored is the FIRST answer of the slot call per document
(`job_worker.py`, `raw_llm_response`); page-recovery and inference calls are
not kept. `tools/replay_raw.py` says so when a replay asks for a call it has
no stored answer for.

The database URL is read from the environment only (never a .env file).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "local_docs" / "raw"


def _page_count(ed: dict):
    if not isinstance(ed, dict):
        return None
    for k in ("page_count", "pages", "total_pages"):
        v = ed.get(k)
        if isinstance(v, int):
            return v
    v = (ed.get("validation") or {}).get("page_count")
    return v if isinstance(v, int) else None


def _rows(conn, sql, **params):
    from sqlalchemy import text
    res = conn.execute(text(sql), params)
    keys = list(res.keys())
    return [dict(zip(keys, r)) for r in res.fetchall()]


def export(job_ids, url: str, out: Path = OUT) -> dict:
    from sqlalchemy import create_engine, text
    eng = create_engine(url, pool_pre_ping=True)
    written = {}
    with eng.connect() as conn:
        if eng.dialect.name == "postgresql":
            conn.execute(text("SET TRANSACTION READ ONLY"))
        for jid in job_ids:
            jobs = _rows(conn, "SELECT id, status, total_docs, schema_id, created_at, "
                               "progress_message FROM extraction_jobs WHERE id = :j", j=jid)
            if not jobs:
                print(f"job {jid}: not found", flush=True)
                continue
            job = jobs[0]
            d = out / str(jid)
            (d / "docs").mkdir(parents=True, exist_ok=True)
            (d / "job.json").write_text(json.dumps(job, default=str, indent=1), encoding="utf-8")
            tpl = None
            if job.get("schema_id"):
                try:
                    t = _rows(conn, "SELECT id, name, document_type, description, columns_json "
                                    "FROM column_templates WHERE id = :t", t=int(job["schema_id"]))
                    tpl = t[0] if t else None
                except (TypeError, ValueError):
                    tpl = None
            (d / "template.json").write_text(json.dumps(tpl, default=str, indent=1), encoding="utf-8")
            docs = _rows(conn, "SELECT id, filename, original_filename, model_used, "
                               "raw_llm_response, extraction_json FROM document_results "
                               "WHERE job_id = :j ORDER BY id", j=jid)
            n_raw = 0
            for doc in docs:
                try:
                    ed = json.loads(doc["extraction_json"]) if doc["extraction_json"] else None
                except ValueError:
                    ed = None
                doc["extraction_json"] = ed
                doc["page_count"] = _page_count(ed)
                n_raw += bool(doc["raw_llm_response"])
                (d / "docs" / f"{doc['id']}.json").write_text(
                    json.dumps(doc, default=str, indent=1), encoding="utf-8")
            written[jid] = {"docs": len(docs), "raw": n_raw, "template": bool(tpl)}
            print(f"job {jid}: {len(docs)} document(s), {n_raw} with a raw answer, "
                  f"template={'yes' if tpl else 'none'}", flush=True)
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("job_ids", nargs="+", type=int)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("DATABASE_URL is not set in this shell's environment.", file=sys.stderr)
        return 2
    try:
        export(a.job_ids, url, Path(a.out))
    except Exception as e:      # never echo the URL: the class name only
        print(f"export failed: {type(e).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
