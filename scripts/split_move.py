"""Move top-level definitions out of a module, verbatim (round 13, part C1).

    python scripts/split_move.py SRC.py DEST.py DOTTED.DEST NAME [NAME ...]
        [--doc "module docstring"] [--prelude FILE] [--dry-run]

For each NAME (a function, class, or a module-level assignment) the exact
source text — with its decorators and the comment block directly above it —
is cut from SRC and appended to DEST (created if absent). DEST gets the
imports its moved code needs, computed from the AST:

  * a name SRC binds by an import -> the same import, narrowed to that name;
  * a name an earlier split module defines -> imported from that module;
  * a name that would stay in SRC -> an ERROR (it would make a cycle); the
    plan must move it too, earlier or now.

SRC then re-exports every moved name (`from DOTTED.DEST import ...`) right
after its own imports, so every existing `extract.X` keeps working. No body is
edited: the proof is scripts/split_proof.py.
"""
from __future__ import annotations

import argparse
import ast
import builtins
import re
import sys
from pathlib import Path

BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}


def _bound(node) -> set[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        ts = node.targets if isinstance(node, ast.Assign) else [node.target]
        out = set()
        for t in ts:
            for n in ast.walk(t):
                if isinstance(n, ast.Name):
                    out.add(n.id)
        return out
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return {(a.asname or a.name.split(".")[0]) for a in node.names}
    return set()


def _used(node) -> set[str]:
    """Free names a top-level node reads (locals and parameters excluded
    approximately: any name it also binds inside is still reported, which
    errs towards importing too much, never too little)."""
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)
            and isinstance(n.ctx, ast.Load)}


def _local_names(node) -> set[str]:
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, ast.arg):
            out.add(n.arg)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n is not node:
            out.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            out |= {(a.asname or a.name.split(".")[0]) for a in n.names}
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
    return out


def _segment(lines, node, prev_end):
    """Line span [start, end) of a node with its decorators and the comment
    block directly above it (stopping at a blank line or the previous node)."""
    start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])]) - 1
    s = start
    while s - 1 >= prev_end and lines[s - 1].lstrip().startswith("#"):
        s -= 1
    return s, node.end_lineno


def plan(src_text):
    tree = ast.parse(src_text)
    return tree, tree.body


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dest")
    ap.add_argument("dotted")
    ap.add_argument("names", nargs="+")
    ap.add_argument("--doc", default="")
    ap.add_argument("--prelude", default=None,
                    help="text inserted after DEST's imports (e.g. sys.path setup)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--provided", action="append", default=[],
                    help="MODULE:NAME,NAME — SRC-level names whose equal value "
                         "another module provides (e.g. the path constants)")
    a = ap.parse_args(argv)

    src = Path(a.src)
    text = src.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    tree = ast.parse(text)
    body = tree.body

    want = set(a.names)
    owner = {}                               # name -> top-level node
    for node in body:
        for n in _bound(node):
            owner.setdefault(n, node)
    missing = want - set(owner)
    if missing:
        print("not found:", sorted(missing))
        return 2
    moving = [n for n in body if _bound(n) & want and not isinstance(n, (ast.Import, ast.ImportFrom))]
    for node in moving:
        extra = _bound(node) - want
        if extra:
            print(f"ERROR: {sorted(_bound(node))} bound together; name all of them")
            return 2
    moved_names = set().union(*(_bound(n) for n in moving))

    # what the moved code needs from SRC's top level
    need = set()
    for node in moving:
        need |= (_used(node) - _local_names(node)) if not isinstance(node, (ast.Assign, ast.AnnAssign)) else _used(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for d in node.decorator_list:
                need |= _used(d)
            if not isinstance(node, ast.ClassDef):
                for dflt in node.args.defaults + node.args.kw_defaults:
                    if dflt is not None:
                        need |= _used(dflt)
    need -= moved_names
    need -= BUILTINS

    dest = Path(a.dest)
    dest_text = dest.read_text(encoding="utf-8") if dest.exists() else ""
    imports, errors = [], []
    provided = {}
    for spec in a.provided:
        mod, names = spec.split(":", 1)
        for n in names.split(","):
            provided[n.strip()] = mod
    for name in sorted(need):
        if name in provided:
            imports.append(f"from {provided[name]} import {name}")
            continue
        node = owner.get(name)
        if node is None:
            continue                          # a local of the function, or a builtin
        if isinstance(node, ast.ImportFrom):
            alias = next(x for x in node.names if (x.asname or x.name) == name)
            mod = "." * node.level + (node.module or "")
            imports.append(f"from {mod} import {alias.name}"
                           + (f" as {alias.asname}" if alias.asname else ""))
        elif isinstance(node, ast.Import):
            alias = next(x for x in node.names if (x.asname or x.name.split('.')[0]) == name)
            imports.append(f"import {alias.name}" + (f" as {alias.asname}" if alias.asname else ""))
        else:
            # defined in SRC: is it a re-export of an earlier split module?
            errors.append(name)
    # names SRC re-exports from earlier split modules are ImportFrom nodes and
    # were handled above; anything left would stay in SRC -> cycle
    if errors:
        print("ERROR: moved code uses names that stay in", src.name, "->", errors)
        return 3

    blocks, spans = [], []
    prev_end = 0
    for node in body:
        if node in moving:
            s, e = _segment(lines, node, prev_end)
            spans.append((s, e))
            blocks.append("".join(lines[s:e]).rstrip("\n") + "\n")
        prev_end = node.end_lineno
    if a.dry_run:
        print(f"would move {len(moving)} nodes ({sum(e - s for s, e in spans)} lines); imports:")
        print("\n".join(imports))
        return 0

    # DEST
    if not dest_text:
        head = '"""' + (a.doc or f"Moved from {src.name}.") + '"""\n'
        future = "from __future__ import annotations\n" if "from __future__ import annotations" in text else ""
        dest_text = (head + future + "\nimport app.services.paths  # noqa: F401  (engine on sys.path)\n"
                     + "# --imports-end--\n")
    have = set(re.findall(r"^(?:from \S+ import .+|import .+)$", dest_text, re.M))
    new_imports = [i for i in dict.fromkeys(imports) if i not in have]
    prelude = Path(a.prelude).read_text(encoding="utf-8") if a.prelude and "# --prelude--" not in dest_text else ""
    if new_imports or prelude:
        marker = "# --imports-end--\n"
        if marker not in dest_text:
            dest_text = dest_text.rstrip("\n") + "\n" + "\n".join(new_imports) + "\n" \
                + (("# --prelude--\n" + prelude) if prelude else "") + marker
        else:
            dest_text = dest_text.replace(marker, "\n".join(new_imports) + "\n"
                                          + (("# --prelude--\n" + prelude) if prelude else "")
                                          + marker, 1)
    dest_text = dest_text.rstrip("\n") + "\n\n\n" + "\n\n\n".join(b.rstrip("\n") for b in blocks) + "\n"
    dest.write_text(dest_text, encoding="utf-8", newline="")

    # SRC: cut spans (from the bottom), then re-export after the import block
    keep = list(lines)
    for s, e in sorted(spans, reverse=True):
        del keep[s:e]
    out = "".join(keep)
    out = re.sub(r"\n{4,}", "\n\n\n", out)
    reexport = (f"from {a.dotted} import (  # noqa: E402,F401  moved, re-exported\n    "
                + ",\n    ".join(sorted(moved_names)) + ",\n)\n")
    anchor = "# --split-reexports--\n"
    if anchor not in out:
        print("ERROR: SRC has no '# --split-reexports--' line to re-export at")
        return 4
    out = out.replace(anchor, anchor + reexport, 1)
    src.write_text(out, encoding="utf-8", newline="")
    print(f"moved {len(moving)} nodes, {sum(e - s for s, e in spans)} lines -> {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
