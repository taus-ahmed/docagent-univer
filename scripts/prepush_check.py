"""Everything that must hold before the first push — one command, read-only.

    python scripts/prepush_check.py            # every check (~25 min: suite, harness, build)
    python scripts/prepush_check.py --quick    # repository checks only (seconds)
    python scripts/prepush_check.py --manual-done   # Tauseef has done the MANUAL items

Read-only on the working tree: the test suite, the native readings and both
harness modes run in a clean `git archive HEAD` export in a temporary
directory (the harness writes its reports there, not here); the frontend build
and tests run in frontend/ and write only its ignored build output. Nothing is
pushed, nothing is sent anywhere, and a secret found is reported by path,
line and TYPE — never its value.

Exit 0 only when every check passes. MANUAL items (docs/RELEASE-CHECKLIST.md)
cannot be checked by a script and count as failures until `--manual-done`.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 5 * 1024 * 1024

SECRET_PATTERNS = {
    "AWS access key id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    "Groq API key": re.compile(r"\bgsk_[0-9A-Za-z]{40,}\b"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
    "xAI key": re.compile(r"\bxai-[A-Za-z0-9]{40,}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "database URL with password": re.compile(
        # a local development default (localhost, the compose service) is not
        # a credential anyone can use; any other host is
        r"\b(?:postgres(?:ql)?|mysql|mongodb)(?:\+\w+)?://[^\s:/@]+:(?!password@|pass@|<)"
        r"[^\s@/]{3,}@(?!localhost\b|127\.0\.0\.1\b|db\b|postgres\b)"),
}
#: Files whose job is to contain fake key shapes (the scanner's own tests).
SECRET_ALLOW = ["scripts/prepush_check.py", "tests/test_prepush_check.py"]

PERSONAL_PATTERNS = {
    "Windows user profile path": re.compile(r"\b[A-Za-z]:[\\/]+Users[\\/]+(?!Public\b)[A-Za-z0-9._-]+", re.I),
    "POSIX home path": re.compile(r"(?<![\w.])/(?:home|Users)/(?!runner\b|user\b|USER\b|you\b|<)[a-z][a-z0-9._-]+/"),
    "Git Bash drive path": re.compile(r"(?<![\w.])/[c-z]/Users/[A-Za-z0-9._-]+", re.I),
    "local repo path": re.compile(r"\b[A-Za-z]:[\\/]+docagent[-\w]*", re.I),
}
#: Paths where a machine path is the subject (the checker and its tests).
PERSONAL_ALLOW = ["scripts/prepush_check.py", "tests/test_prepush_check.py",
                  "frontend/package-lock.json"]

PROVIDER_RE = re.compile(r"\b(?:groq|grok|xai)\b", re.I)
#: Where the removed provider may be NAMED: history, and the test that pins
#: its absence. Anywhere else (code, config, env examples) is a failure.
PROVIDER_ALLOW = ["docs/DEPLOY-RUNBOOK.md", "docs/ROADMAP.md", "docs/SECURITY.md",
                  "docs/RELEASE-CHECKLIST.md", "docs/design-history/*",
                  "docs/DECISION-LOG.md", "tests/test_llm_router.py",
                  "scripts/prepush_check.py", "tests/test_prepush_check.py"]

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

MANUAL = [
    "Revoke the Groq API key committed in ecaead9 (on main) at the provider",
    "Railway: delete the unused GROQ_* variables (and PRIMARY_LLM if it says groq)",
    "Railway: check DEMO_CLIENT_IDS names only the demo tenant",
    "Choose and add a LICENSE",
    "Review redistribution terms of the third-party sample PDFs in tests/test_pdfs/round2",
    "Set up staging (docs/CHEQUE-TRIAL.md section 1) before real cheques",
    "Decide the explicit platform_admin role (docs/proposals/roles.md); owner delete was decided in round 14",
    "Confirm every VERIFY in docs/OPERATIONS.md and docs/CLIENT-DATA-FAQ.md before showing the FAQ to a client",
    "Railway: set DRIVE_TENANT if Google Drive is used (off by default since round 14); confirm Railway appends the client IP last in X-Forwarded-For",
    "Run scripts/check_firm_ids.py on the production firm ids before the first deploy (docs/OPERATIONS.md section 12)",
]

#: Settings that are internal constants, not something an operator sets.
SETTINGS_INTERNAL = {"APP_NAME", "APP_VERSION", "ALGORITHM"}
SETTING_RE = re.compile(r"^    ([A-Z][A-Z0-9_]+)\s*:", re.M)


def undocumented_settings(root=ROOT) -> list[str] | None:
    """Every field of backend/app/config.py::Settings must be named in
    docs/OPERATIONS.md (the operator's variable table). None when the repo
    has no config file."""
    cfg = root / "backend" / "app" / "config.py"
    if not cfg.exists():
        return None
    ops = root / "docs" / "OPERATIONS.md"
    text = ops.read_text(encoding="utf-8") if ops.exists() else ""
    names = sorted(set(SETTING_RE.findall(cfg.read_text(encoding="utf-8"))) - SETTINGS_INTERNAL)
    return [n for n in names if f"`{n}`" not in text]


class Report:
    def __init__(self):
        self.rows = []

    def add(self, name, ok, detail=""):
        self.rows.append((name, "PASS" if ok is True else "FAIL" if ok is False else ok, detail))

    @property
    def failed(self):
        return [r for r in self.rows if r[1] != "PASS"]

    def print(self):
        for name, st, detail in self.rows:
            print(f"[{st:6}] {name}" + (f"\n         {detail}" if detail and st != "PASS" else
                                        f" — {detail}" if detail else ""))


def git(*args, cwd=ROOT) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True)
    if r.returncode:
        raise RuntimeError(r.stderr.decode("utf-8", "replace").strip())
    return r.stdout.decode("utf-8", "replace")


def tracked(root=ROOT) -> list[str]:
    return [p for p in git("ls-files", "-z", cwd=root).split("\0") if p]


def _allowed(path, globs):
    return any(fnmatch.fnmatch(path, g) for g in globs)


def _text(root, path):
    p = root / path
    try:
        if p.stat().st_size > MAX_BYTES:
            return None
        data = p.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:4096]:
        return None
    return data.decode("utf-8", "replace")


def scan(root, files, patterns, allow, skip_dirs=()) -> list[str]:
    hits = []
    for f in files:
        if _allowed(f, allow) or any(f.startswith(d) for d in skip_dirs):
            continue
        t = _text(root, f)
        if t is None:
            continue
        for n, line in enumerate(t.splitlines(), 1):
            for kind, rx in patterns.items():
                if rx.search(line):
                    hits.append(f"{f}:{n}: {kind}")
    return hits


# ── repository checks (fast) ─────────────────────────────────────────────────

def check_repo(rep: Report, root=ROOT):
    status = git("status", "--porcelain", cwd=root).strip()
    rep.add("working tree clean", not status,
            "" if not status else f"{len(status.splitlines())} changed/untracked path(s)")
    files = tracked(root)

    hits = scan(root, files, SECRET_PATTERNS, SECRET_ALLOW)
    rep.add("secret scan of tracked files", not hits, "; ".join(hits[:20]))

    hits = scan(root, files, PERSONAL_PATTERNS, PERSONAL_ALLOW,
                skip_dirs=("tests/llm_cache/",))
    rep.add("no machine-specific paths", not hits, "; ".join(hits[:20]))

    env = [f for f in files if re.search(r"(^|/)\.env(\.[\w-]+)?$", f)
           and not f.endswith(".example")]
    rep.add(".env files untracked", not env, ", ".join(env))

    lic = [f for f in files if re.fullmatch(r"(LICEN[CS]E|COPYING)(\.\w+)?", f, re.I)]
    rep.add("license file present", True if lic else "MANUAL",
            ", ".join(lic) if lic else "no LICENSE file (a choice only Tauseef can make)")

    big = [f"{f} ({(root / f).stat().st_size // 1024} KB)" for f in files
           if (root / f).is_file() and (root / f).stat().st_size > MAX_BYTES]
    rep.add("no tracked file over 5 MB", not big, ", ".join(big))

    prov = []
    for f in files:
        if _allowed(f, PROVIDER_ALLOW):
            continue
        t = _text(root, f)
        if t and PROVIDER_RE.search(t):
            prov.append(f)
    rep.add("no Groq/xAI references outside history docs", not prov, ", ".join(prov[:20]))

    broken = []
    for f in files:
        if not (f.endswith(".md") and (f == "README.md" or f.startswith("docs/"))):
            continue
        t = _text(root, f) or ""
        for target in LINK_RE.findall(t):
            if re.match(r"^(https?:|mailto:|#)", target):
                continue
            rel = target.split("#", 1)[0]
            if rel and not (root / f).parent.joinpath(rel).exists():
                broken.append(f"{f} -> {target}")
    rep.add("README and docs links resolve", not broken, "; ".join(broken[:20]))

    missing = undocumented_settings(root)
    rep.add("every setting documented in docs/OPERATIONS.md", not missing,
            "no backend/app/config.py" if missing is None else ", ".join(missing))

    bad = []
    try:
        import yaml
        for f in files:
            if f.startswith(".github/workflows/") and f.endswith((".yml", ".yaml")):
                try:
                    doc = yaml.safe_load((root / f).read_text(encoding="utf-8"))
                    if not isinstance(doc, dict) or "jobs" not in doc:
                        bad.append(f"{f}: no jobs")
                except yaml.YAMLError as e:
                    bad.append(f"{f}: {type(e).__name__}")
        rep.add("CI workflow syntax valid", not bad, "; ".join(bad))
    except ImportError:
        rep.add("CI workflow syntax valid", False, "PyYAML not installed")


# ── heavy checks (clean export) ──────────────────────────────────────────────

def _run(cmd, cwd, env=None, timeout=3600):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8", **(env or {})})
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")


def _export(dest: Path):
    tar = dest / "head.tar"
    with open(tar, "wb") as fh:
        subprocess.run(["git", "archive", "HEAD"], cwd=ROOT, stdout=fh, check=True)
    with tarfile.open(tar) as t:
        t.extractall(dest / "x")
    tar.unlink()
    return dest / "x"


def check_heavy(rep: Report):
    py = sys.executable
    tmp = Path(tempfile.mkdtemp(prefix="prepush-"))
    try:
        x = _export(tmp)
        code, out = _run([py, "-m", "pytest", "-q", "-p", "no:cacheprovider"], x)
        tail = [ln for ln in out.splitlines() if re.search(r"\d+ (passed|failed)", ln)]
        rep.add("full test suite (clean export)", code == 0, tail[-1] if tail else out[-300:])

        code, out = _run([py, "-m", "tests.harness.native_hashes", "--check"], x)
        rep.add("native readings match the recorded hashes", code == 0,
                out.strip().splitlines()[-1] if out.strip() else "")

        want = json.loads((x / "tests" / "reports" / "release_baseline.json")
                          .read_text(encoding="utf-8"))["harness"]
        for mode, args in (("templated_export", []), ("no_template_export", ["--no-template"])):
            code, out = _run([py, "-m", "tests.harness.runner", "--mode", "replay", *args], x)
            m = re.search(r"accuracy  EXPORT\s*:\s*([\d.]+%)", out)
            got = m.group(1) if m else "?"
            rep.add(f"harness {mode} = {want[mode]}", code == 0 and got == want[mode],
                    f"got {got}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    fe = ROOT / "frontend"
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm or not (fe / "node_modules").exists():
        rep.add("frontend build and tests", False, "npm or frontend/node_modules missing")
        return
    for name, cmd in (("frontend type-check", [npm, "run", "type-check"]),
                      ("frontend tests", [npm, "test"]),
                      ("frontend build", [npm, "run", "build"])):
        code, out = _run(cmd, fe)
        rep.add(name, code == 0, "" if code == 0 else out.strip()[-300:])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="pre-push checks (read-only)")
    ap.add_argument("--quick", action="store_true", help="repository checks only")
    ap.add_argument("--manual-done", action="store_true",
                    help="Tauseef has done every MANUAL item in docs/RELEASE-CHECKLIST.md")
    a = ap.parse_args(argv)
    rep = Report()
    check_repo(rep)
    if not a.quick:
        check_heavy(rep)
    for item in MANUAL:
        rep.add(f"manual: {item}", True if a.manual_done else "MANUAL")
    rep.print()
    bad = rep.failed
    print(f"\n{len(rep.rows) - len(bad)} passed, {len(bad)} not passed"
          + (" (MANUAL items need Tauseef; see docs/RELEASE-CHECKLIST.md)"
             if any(r[1] == "MANUAL" for r in bad) else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
