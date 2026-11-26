"""Attention reasons on the gold corpus, replayed (Run S guard).

    backend\\.venv\\Scripts\\python.exe tools\\gold_attention.py [--no-template]

A new completeness check that fires on the gold documents (whose answers
score 98.7%) is a false alarm by construction worth reading: this prints
every attention reason and `not_captured` sentence each gold document gets,
from the cached answers, no network.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-template", action="store_true")
    a = ap.parse_args(argv)
    from tests.harness import bootstrap as bs
    from tests.harness import runner as R
    from tests.harness.llm_cache import LLMCache
    bs.bootstrap()
    bs.chdir_backend()
    R.set_widenings(W2_table_by_content=bool(a.no_template))
    cache = LLMCache(mode="replay")
    cache.install()
    total = 0
    out = []
    for label in R.load_labels(None):
        cache.context = label["document_id"]
        td = None if a.no_template else R.build_template_data(label, "replay")[0]
        results, _log = R.run_pipeline(label, td)
        for r in results:
            ed = r.extracted_data or {}
            att = [x.get("text") for x in ed.get("attention") or []]
            nc = list(ed.get("not_captured") or [])
            total += len(att)
            out.append(f"{label['document_id']}: {len(att)} attention, {len(nc)} not_captured")
            out += [f"   ATT {t}" for t in att] + [f"   NC  {t}" for t in nc]
    out.append(f"TOTAL attention reasons: {total}")
    sys.stdout.buffer.write(("\n".join(out) + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
