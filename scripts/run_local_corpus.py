#!/usr/bin/env python
"""Run a folder of PDFs through the engine, offline (Part 3.4 d). Not a test.

    python scripts/run_local_corpus.py [--dir E:\\docagent-testdocs]
           [--provider stub|replay] [--template t.json] [--doc-type invoice]

For every PDF under --dir: the records the engine finds (one file can be
several documents), each record's pages, how many values it filled, how many
are low, every reason code with its count, whether it needs review, and the
time taken. No model is called: `stub` answers from the page text
(connectors/stub_client.py); `replay` answers only from the recorded cache
(tests/llm_cache/) and reports a file it has no answer for as a cache miss.

Read-only: the folder is never written to. Nothing here prints document text —
counts, codes and file names only (engine/log_safety.py's rule).
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend"), str(ROOT / "backend" / "engine")]
DEFAULT_DIR = r"E:\docagent-testdocs"


def _reasons(ed):
    c = Counter()
    for p in (ed.get("field_provenance") or {}).values():
        c.update(p.get("review_reasons") or [])
    for k, rows in ed.items():
        if k.endswith("_rows") and isinstance(rows, list):
            for r in rows:
                if isinstance(r, dict):
                    c.update(r.get("_review_reasons") or [])
    return c


def _router(provider):
    from types import SimpleNamespace
    if provider == "stub":
        os.environ.setdefault("ENVIRONMENT", "development")
        from connectors.llm_router import LLMRouter, settings
        settings.PRIMARY_LLM, settings.LLM_FALLBACKS = "stub", ""
        return SimpleNamespace(llm=LLMRouter())
    from tests.harness import bootstrap
    bootstrap.bootstrap()
    from tests.harness.llm_cache import LLMCache
    LLMCache(mode="replay").install()
    from connectors.llm_router import LLMRouter
    return SimpleNamespace(llm=LLMRouter())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default=DEFAULT_DIR)
    ap.add_argument("--provider", choices=("stub", "replay"), default="stub")
    ap.add_argument("--template", help="a template JSON ({layout, doc_type}); none = infer")
    ap.add_argument("--doc-type", default=None)
    a = ap.parse_args(argv)
    folder = Path(a.dir)
    if not folder.is_dir():
        print(f"{folder}: no such folder — nothing to run (see PROGRESS BLOCKED)")
        return 2
    pdfs = sorted(folder.rglob("*.pdf"))
    if not pdfs:
        print(f"{folder}: no PDFs")
        return 2
    tpl = json.loads(Path(a.template).read_text(encoding="utf-8")) if a.template else None
    if tpl is not None and a.doc_type:
        tpl["doc_type"] = a.doc_type
    router = _router(a.provider)
    import extractor
    totals = Counter()
    for pdf in pdfs:
        t0 = time.perf_counter()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                results = extractor.run_extraction(router, pdf, json.loads(json.dumps(tpl))
                                                   if tpl else None)
        except Exception as e:                       # a miss or a failure is a row
            print(f"{pdf.name}: FAILED {type(e).__name__}")
            totals["failed"] += 1
            continue
        dt = time.perf_counter() - t0
        print(f"{pdf.name}: {len(results)} record(s), {dt:.1f}s")
        for r in results:
            ed = getattr(r, "extracted_data", None) or {}
            if not getattr(r, "success", True) or not ed:
                print(f"   - FAILED: {(getattr(r, 'error', '') or '')[:80]}")
                totals["failed"] += 1
                continue
            cm = (ed.get("validation") or {}).get("confidence_map") or {}
            filled = sum(1 for v in (ed.get("extracted_fields") or {}).values() if str(v).strip())
            rows = sum(len(v) for k, v in ed.items() if k.endswith("_rows") and isinstance(v, list))
            low = sum(1 for v in cm.values() if v == "low")
            reasons = _reasons(ed)
            sp = ed.get("source_pages")
            span = f"pages {sp[0]}-{sp[-1]}" if sp else "whole file"
            print(f"   - {span}: {filled} field(s), {rows} row(s), "
                  f"{low} low, review={'yes' if ed.get('needs_review') else 'no'}; "
                  + (", ".join(f"{k}x{n}" for k, n in reasons.most_common()) or "no reasons"))
            totals["records"] += 1
            totals["review"] += bool(ed.get("needs_review"))
            totals.update({f"reason:{k}": n for k, n in reasons.items()})
    print(f"\n{len(pdfs)} file(s), {totals['records']} record(s), "
          f"{totals['review']} need review, {totals['failed']} failed")
    for k, n in sorted((k, n) for k, n in totals.items() if k.startswith("reason:")):
        print(f"  {k[7:]}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
