"""Every GitHub Action the CI uses is pinned to a full commit SHA, with the
version it names in a comment (Run 15, item 10). A tag can be moved to other
code; a commit cannot."""
from __future__ import annotations

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
PINNED = re.compile(r"uses:\s*[\w.-]+/[\w./-]+@[0-9a-f]{40}\s+#\s*v\d+(\.\d+)*\s*$")


def test_every_action_is_pinned_to_a_commit_with_its_version():
    uses = [(p.name, n, ln.strip())
            for p in sorted(WORKFLOWS.glob("*.yml"))
            for n, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if re.search(r"^\s*-?\s*uses:", ln)]
    assert uses, "no workflow steps found"
    bad = [u for u in uses if not PINNED.search(u[2])]
    assert not bad, bad
