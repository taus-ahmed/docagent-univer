"""Proof that splitting a module moved code without changing it.

    python scripts/split_proof.py record OUT.json FILE.py
        hash every top-level function and class of FILE.py (normalised AST:
        `ast.dump` without positions, so formatting and location do not count;
        decorators and docstrings DO count)
    python scripts/split_proof.py check OUT.json FILE.py [MORE.py ...]
        find each recorded definition in exactly one of the given files with
        the same hash; report anything lost, changed or duplicated

Used for the extract.py split (round 13, part C1): recorded before the first
move, checked after the last.
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path


def definitions(path: Path) -> dict[str, str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            dump = ast.dump(node, annotate_fields=True, include_attributes=False)
            h = hashlib.sha256(dump.encode("utf-8")).hexdigest()[:16]
            key = node.name
            n = 2
            while key in out:                 # a name defined twice keeps both
                key = f"{node.name}#{n}"
                n += 1
            out[key] = h
    return out


def main(argv) -> int:
    cmd, out = argv[0], Path(argv[1])
    files = [Path(p) for p in argv[2:]]
    if cmd == "record":
        d = definitions(files[0])
        out.write_text(json.dumps(d, indent=1, sort_keys=True), encoding="utf-8")
        print(f"recorded {len(d)} definitions of {files[0].name}")
        return 0
    want = json.loads(out.read_text(encoding="utf-8"))
    found: dict[str, list] = {}
    for f in files:
        for name, h in definitions(f).items():
            found.setdefault(name, []).append((f.name, h))
    lost = [n for n in want if n not in found]
    changed = [n for n in want if n in found and all(h != want[n] for _f, h in found[n])]
    dup = [n for n in want if len(found.get(n, [])) > 1]
    moved = {}
    for n in want:
        for f, h in found.get(n, []):
            if h == want[n]:
                moved[f] = moved.get(f, 0) + 1
    print(json.dumps({"recorded": len(want), "identical": sum(1 for n in want if n not in lost
                                                              and n not in changed),
                      "lost": lost, "changed": changed, "duplicated": dup,
                      "by_file": moved}, indent=1))
    return 1 if (lost or changed or dup) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
