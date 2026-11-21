"""Run the Run Q test corpus through the real pipeline (Run Q, Q0).

    backend\\.venv\\Scripts\\python.exe tools\\live_corpus.py            # offline: plan only
    backend\\.venv\\Scripts\\python.exe tools\\live_corpus.py --live     # real Gemini calls

OFFLINE BY DEFAULT. Without --live it prints the plan (job, file, template)
and makes no call. With --live it needs GEMINI_API_KEY in this shell's
environment (never a .env file: DOCAGENT_TEST_NO_DOTENV is set) and stops at

    MAX_CALLS = 60 model calls   and   MAX_COST = $1.00 estimated

whichever comes first. A call refused by a cap is a FAILED call (the
document says so in its result), never a silent empty answer. Exports go to
local_docs/live_out/job_<id>_live.xlsx for tools/audit_exports.py.

The manifest is tools/live_corpus_manifest.json: the 29 Round A/B/C jobs
(56-84), each with the source file name(s) under local_docs/DocAgent_testdocs.
A job uses the template stored by tools/export_raw_responses.py in
local_docs/raw/<id>/template.json when that exists, else no template.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = Path(__file__).with_name("live_corpus_manifest.json")
OUT = ROOT / "local_docs" / "live_out"
MAX_CALLS = 60
MAX_COST = 1.00


class CappedLLM:
    """Wraps the real router; refuses calls past either cap."""

    def __init__(self, router, max_calls=MAX_CALLS, max_cost=MAX_COST):
        self.router, self.max_calls, self.max_cost = router, max_calls, max_cost
        self.calls, self.cost, self.refused = 0, 0.0, 0

    def _refuse(self, why):
        from connectors.base import LLMResponse
        self.refused += 1
        return LLMResponse(raw_text="", success=False, error=f"live_corpus cap: {why}",
                           error_kind="cap")

    def _cost_of(self, r):
        c = 0.0
        for a in getattr(r, "attempts", None) or []:
            if isinstance(a, dict) and a.get("cost_estimate") is not None:
                c += float(a["cost_estimate"])
        return c

    def extract(self, **kw):
        if self.calls >= self.max_calls:
            return self._refuse(f"{self.max_calls} calls reached")
        if self.cost >= self.max_cost:
            return self._refuse(f"${self.max_cost:.2f} reached")
        self.calls += 1
        r = self.router.extract(**kw)
        self.cost += self._cost_of(r)
        return r

    def classify(self, **kw):
        if self.calls >= self.max_calls or self.cost >= self.max_cost:
            return self._refuse("cap reached")
        self.calls += 1
        return self.router.classify(**kw)


def plan():
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    src = ROOT / "local_docs" / "DocAgent_testdocs"
    out = []
    for job in m["jobs"]:
        files = []
        for name in job["files"]:
            hits = [p for p in src.rglob(name) if p.is_file()]
            files.append(hits[0] if hits else None)
        tpl = ROOT / "local_docs" / "raw" / str(job["job"]) / "template.json"
        out.append({"job": job["job"], "files": files, "names": job["files"],
                    "template": tpl if tpl.exists() else None})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--live", action="store_true", help="make real model calls (costs money)")
    ap.add_argument("--jobs", nargs="*", type=int, help="only these job ids")
    a = ap.parse_args(argv)
    jobs = [j for j in plan() if not a.jobs or j["job"] in a.jobs]
    for j in jobs:
        miss = [n for n, f in zip(j["names"], j["files"]) if f is None]
        print(f"job {j['job']}: {len(j['files'])} file(s), template="
              f"{'stored' if j['template'] else 'none'}"
              + (f", MISSING {miss}" if miss else ""))
    if not a.live:
        print("offline: no calls made (pass --live to run).")
        return 0
    if not os.environ.get("GEMINI_API_KEY"):
        print("--live needs GEMINI_API_KEY in this shell's environment.", file=sys.stderr)
        return 2
    os.environ["DOCAGENT_TEST_NO_DOTENV"] = "1"
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(Path(__file__).parent))
    from tests.harness.bootstrap import bootstrap, chdir_backend
    bootstrap()
    chdir_backend()
    from connectors.llm_router import LLMRouter
    from extractor import run_extraction
    import replay_raw
    llm = CappedLLM(LLMRouter())
    for j in jobs:
        td = None
        if j["template"]:
            td = replay_raw.template_data_of(json.loads(j["template"].read_text(encoding="utf-8")))
        docs = []
        for name, f in zip(j["names"], j["files"]):
            if f is None:
                continue
            for r in run_extraction(SimpleNamespace(llm=llm), f, td, batch_schemas={}):
                docs.append(({"filename": name, "original_filename": name}, r.extracted_data or {}, []))
        rep = {"docs": docs, "template": json.loads(j["template"].read_text(encoding="utf-8"))
               if j["template"] else None}
        p = replay_raw.write_workbook(j["job"], rep, OUT / f"job_{j['job']}_live.xlsx")
        print(f"job {j['job']}: {len(docs)} document(s) -> {p.relative_to(ROOT)}  "
              f"[calls {llm.calls}/{MAX_CALLS}, ~${llm.cost:.3f}/{MAX_COST:.2f}, refused {llm.refused}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
