"""scripts/prepush_check.py repository checks, on a throwaway git repository
with one planted violation per check. Secrets are reported by path, line and
type — never their value."""
import importlib.util
import subprocess

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

_spec = importlib.util.spec_from_file_location(
    "prepush_check", bs.REPO_DIR / "scripts" / "prepush_check.py")
pc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pc)

FAKE_KEY = "AKIA" + "Q" * 16
FAKE_GSK = "gsk_" + "a1" * 26


def _repo(tmp_path, files):
    for name, data in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    run = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, check=True,
                                    capture_output=True)
    run("init", "-q")
    run("add", "-A")
    run("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "x")
    return tmp_path


def _check(root):
    rep = pc.Report()
    pc.check_repo(rep, root=root)
    return {name: (st, detail) for name, st, detail in rep.rows}


CLEAN = {"README.md": "see [docs](docs/a.md)\n", "docs/a.md": "# a\n",
         "LICENSE": "MIT\n",
         ".github/workflows/ci.yml": "on: push\njobs:\n  t:\n    runs-on: x\n"}


def test_a_clean_repository_passes(tmp_path):
    rows = _check(_repo(tmp_path, CLEAN))
    assert all(st == "PASS" for st, _ in rows.values()), rows


@pytest.mark.parametrize("name,files,want", [
    ("secret scan of tracked files", {"cfg.py": f"KEY = '{FAKE_KEY}'\n"}, "cfg.py:1: AWS access key id"),
    ("secret scan of tracked files", {"x.env.example": f"K={FAKE_GSK}\n"}, "Groq API key"),
    ("no machine-specific paths", {"n.md": "C:\\Users\\someone\\x\n"}, "n.md:1"),
    (".env files untracked", {"backend/.env": "A=1\n"}, "backend/.env"),
    ("no tracked file over 5 MB", {"big.bin": b"\0" * (5 * 1024 * 1024 + 1)}, "big.bin"),
    ("no Groq/xAI references outside history docs", {"app.py": "import groq\n"}, "app.py"),
    ("README and docs links resolve", {"docs/b.md": "[x](missing.md)\n"}, "missing.md"),
    ("CI workflow syntax valid", {".github/workflows/ci.yml": "jobs: [\n"}, "ci.yml"),
])
def test_each_violation_fails_and_never_prints_the_value(tmp_path, name, files, want):
    rows = _check(_repo(tmp_path, {**CLEAN, **files}))
    st, detail = rows[name]
    assert st == "FAIL" and want in detail, (st, detail)
    assert FAKE_KEY not in detail and FAKE_GSK not in detail


def test_a_missing_license_is_manual_not_pass(tmp_path):
    files = dict(CLEAN)
    del files["LICENSE"]
    assert _check(_repo(tmp_path, files))["license file present"][0] == "MANUAL"


def test_a_dirty_tree_fails(tmp_path):
    root = _repo(tmp_path, CLEAN)
    (root / "new.txt").write_text("x", encoding="utf-8")
    assert _check(root)["working tree clean"][0] == "FAIL"


def test_a_local_dev_database_url_is_not_a_secret(tmp_path):
    rows = _check(_repo(tmp_path, {**CLEAN, "c.py":
                                   "U='postgresql://app:app@localhost:5432/app'\n"}))
    assert rows["secret scan of tracked files"][0] == "PASS"


def test_manual_items_fail_until_acknowledged(monkeypatch, capsys):
    monkeypatch.setattr(pc, "check_repo", lambda rep, root=None: None)
    assert pc.main(["--quick"]) == 1
    assert "Revoke the Groq API key" in capsys.readouterr().out
    assert pc.main(["--quick", "--manual-done"]) == 0


def test_every_setting_must_be_in_the_operations_doc(tmp_path):
    cfg = "class Settings:\n    SECRET_KEY: str = 'x'\n    NEW_KNOB: int = 0\n    APP_NAME: str = 'a'\n"
    root = _repo(tmp_path, {"backend/app/config.py": cfg,
                            "docs/OPERATIONS.md": "| `SECRET_KEY` | x |\n"})
    st, detail = _check(root)["every setting documented in docs/OPERATIONS.md"]
    assert st == "FAIL" and detail == "NEW_KNOB"


def test_the_real_settings_are_all_documented():
    assert pc.undocumented_settings() == []
