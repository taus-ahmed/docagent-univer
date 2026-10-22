"""Every PROJECT module this run imports resolves inside THIS tree.

Several worktrees share one virtualenv, and `sys.path` puts `backend/` and
`backend/engine/` first, so a stray path can make a test import the engine of
ANOTHER tree and measure code nobody is changing. Named `zz` so it runs last,
after every test module has imported what it imports.

A project module is one whose top-level name is a module or package of this
tree (`app`, `extractor`, `core`, `tests`, ...). The interpreter's standard
library and site-packages are never project modules, wherever the interpreter
happens to live — the S1 venv's own Python sits under `E:\\docagent-codex`.
"""
import sys
from pathlib import Path

from tests.harness import bootstrap as bs

bs.bootstrap()

HERE = Path(__file__).resolve().parents[1]
ROOTS = [HERE, HERE / "backend", HERE / "backend" / "engine"]


def _project_names():
    names = set()
    for root in ROOTS:
        for p in root.iterdir():
            if p.suffix == ".py":
                names.add(p.stem)
            elif p.is_dir() and (p / "__init__.py").exists() or \
                    p.is_dir() and any(p.glob("*.py")):
                names.add(p.name)
    return names


def _interpreter_dirs():
    dirs = {Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(),
            Path(sys.exec_prefix).resolve()}
    return [d for d in dirs if not d.is_relative_to(HERE)]


def test_project_modules_resolve_inside_this_tree():
    assert bs.REPO_DIR.resolve() == HERE
    import app.main, app.core.auth, app.models.models  # noqa: E401,F401
    import extractor, slot_extractor, text_layer, core.preprocessor  # noqa: E401,F401
    project, interp = _project_names(), _interpreter_dirs()
    foreign, inside = [], 0
    for name, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None)
        if not f or name.split(".")[0] not in project:
            continue
        p = Path(f).resolve()
        if "site-packages" in p.parts or any(p.is_relative_to(d) for d in interp):
            continue                    # a library that shares a project name
        if p.is_relative_to(HERE):
            inside += 1
        else:
            foreign.append((name, str(p)))
    msg = f"ISOLATION: {inside} project modules inside {HERE}; foreign={foreign}"
    print(msg)
    assert foreign == [], msg
    assert inside > 10, msg
