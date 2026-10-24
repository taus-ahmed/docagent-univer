"""Build tests/llm_cache/_alias_index.json from lookup traces.

Run on the RECORDING machine (the replay preflight passes there, so every exact
key matches), with tracing on, over everything that replays:

    set DOCAGENT_CACHE_TRACE=<trace.jsonl>
    python -m pytest
    python -m tests.harness.runner --mode replay
    python -m tests.harness.runner --mode replay --no-template
    python -m tests.harness.alias_index <trace.jsonl> [...]

Only exact hits of native-text requests (no page OCR'd) get an alias; see
`llm_cache.build_alias_index`. Prints how many cache entries are reachable by
alias and how many only by their exact key.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from tests.harness.bootstrap import CACHE_DIR
from tests.harness.llm_cache import build_alias_index, write_alias_index


def _entries(paths):
    for p in paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield json.loads(line)


def main(argv=None) -> int:
    paths = (argv if argv is not None else sys.argv[1:])
    if not paths:
        print(__doc__)
        return 2
    entries = list(_entries(paths))
    index, report = build_alias_index(entries)
    stored = {json.loads(p.read_text(encoding="utf-8")).get("key")
              for p in CACHE_DIR.glob("*.json") if not p.name.startswith("_")}
    exercised = {e["exact"] for e in entries if e.get("hit")}
    by_alias = set(index.values())
    report.update({
        "cache_entries": len(stored),
        "exercised_by_suite_and_harness": len(exercised & stored),
        "reachable_by_alias": len(by_alias & stored),
        "exact_key_only": len(stored - by_alias),
        "never_exercised": len(stored - exercised),
    })
    write_alias_index(CACHE_DIR, index, report)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
