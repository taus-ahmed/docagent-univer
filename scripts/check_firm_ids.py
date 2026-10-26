#!/usr/bin/env python
"""Which firm ids would this release refuse? Read-only; no database.

Round 14 stopped NORMALISING firm ids (`client_id`): an id is used verbatim as
its storage prefix, or refused (`backend/app/core/storage.py::_tenant_segment`),
and the API accepts only ids matching `CLIENT_ID_PATTERN`
(`backend/app/schemas/schemas.py`). Before the first deploy, run this on every
firm id production holds (docs/OPERATIONS.md §12):

    python scripts/check_firm_ids.py ids.txt
    <list of ids> | python scripts/check_firm_ids.py

One id per line (blank lines and lines starting with '#' are skipped). The
script never connects to anything and reads nothing but its input. Exit code
0 when every id passes, 1 when any is refused or two ids collide.

For each refused id it prints the prefix the OLD code stored that firm's
files under, because those files stay where they are: a refused id must be
renamed (and its files moved) before that firm can upload again. Two ids the
old code normalised to ONE prefix shared a folder — that is reported too.

The two rules are copied here so the script imports nothing from the app
(importing `app` would load settings from the environment); a test checks
they agree with the app's own functions (tests/test_check_firm_ids.py).
"""
from __future__ import annotations

import re
import sys
from pathlib import PurePosixPath

#: backend/app/schemas/schemas.py::CLIENT_ID_PATTERN
CLIENT_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?$")


def old_prefix(value, fallback="unknown") -> str:
    """backend/app/core/storage.py::_safe_segment — what the old code used,
    as production (Linux) runs it: only '/' separates directories there."""
    name = PurePosixPath(str(value or "")).name
    name = name.replace("\\", "_")
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip("._-") or fallback
    return name[:120]


def verdict(firm_id: str) -> list:
    """Reasons this id is refused; [] when it passes."""
    why = []
    if old_prefix(firm_id) != firm_id:
        why.append(f"storage refuses it (the old code stored it under "
                   f"'{old_prefix(firm_id)}')")
    if not CLIENT_ID_PATTERN.match(firm_id):
        why.append("the API refuses it (letters and digits, then letters, "
                   "digits, '.', '_' or '-', up to 100 characters, ending in "
                   "a letter or digit)")
    return why


def check(ids) -> tuple:
    """(report lines, ok)."""
    lines, ok = [], True
    seen = {}
    for fid in ids:
        seen.setdefault(old_prefix(fid), []).append(fid)
        why = verdict(fid)
        if why:
            ok = False
            lines.append(f"REFUSED  {fid!r}: " + "; ".join(why))
        else:
            lines.append(f"ok       {fid!r}")
    for prefix, group in sorted(seen.items()):
        if len(group) > 1:
            ok = False
            lines.append(f"COLLIDE  {group!r} were all stored under '{prefix}' "
                         f"by the old code: their files share one folder")
    n_bad = sum(1 for ln in lines if not ln.startswith("ok"))
    lines.append(f"{len(ids)} id(s) checked, {n_bad} problem(s)")
    return lines, ok


def read_ids(stream) -> list:
    out = []
    for raw in stream:
        s = raw.rstrip("\r\n")
        if s.strip() and not s.lstrip().startswith("#"):
            out.append(s)
    return out


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv:
        with open(argv[0], encoding="utf-8") as fh:
            ids = read_ids(fh)
    else:
        ids = read_ids(sys.stdin)
    lines, ok = check(ids)
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
