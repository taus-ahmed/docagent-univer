#!/usr/bin/env python
"""Start a throwaway local stack for browser tests (Parts A7-A9). DEV ONLY.

    python scripts/e2e/stack.py --workdir <empty scratch dir> [--api-port 8100] [--web-port 3100]

Backend: the stub model (PRIMARY_LLM=stub, no network), ENVIRONMENT=development,
a NEW SQLite file and local storage inside --workdir — never any other
database. Two firms are created (e2e_a, e2e_b), each with an admin; their
passwords are written to <workdir>/creds.json for the specs, and e2e_a also has
a user left on a one-time password (the forced-change flow). Frontend: `next
dev` with BACKEND_URL / NEXT_PUBLIC_API_URL pointing at the backend, set in the
process environment so they win over any .env file.

Runs until interrupted; kills both servers on exit. Prints "STACK READY" when
both answer.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable


def wait(url, seconds=180):
    end = time.time() + seconds
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status < 500:
                    return True
        except Exception:
            time.sleep(1)
    return False


def backend_env(work: Path, web_port: int) -> dict:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("DATABASE_", "GEMINI", "AWS_", "S3_", "DOCAGENT_"))}
    storage = work / "storage"
    env.update({
        "ENVIRONMENT": "development", "PRIMARY_LLM": "stub", "LLM_FALLBACKS": "",
        "GEMINI_API_KEY": "", "DATABASE_URL": f"sqlite:///{(work / 'e2e.db').as_posix()}",
        "SECRET_KEY": secrets.token_hex(32), "STORAGE_BACKEND": "local",
        "LOCAL_UPLOAD_DIR": str(storage / "uploads"), "LOCAL_OUTPUT_DIR": str(storage / "outputs"),
        "LOCAL_SCHEMAS_DIR": str(storage / "schemas"),
        "ALLOWED_ORIGINS": f"http://localhost:{web_port}", "OCR_WORKERS": "1",
        "RATE_LIMIT_DELAY": "0", "DEMO_CLIENT_IDS": "", "BCRYPT_ROUNDS": "4",
        "PYTHONIOENCODING": "utf-8",
    })
    return env


SEED = r'''
import json, sys
sys.path.insert(0, ".")
from app.models import SessionLocal, init_db
from app.core.tenants import create_tenant
from app.core.auth import hash_password
from app.models.models import User
init_db()
db = SessionLocal()
out = {}
for firm in ("e2e_a", "e2e_b"):
    t = create_tenant(db, firm, firm.upper() + " Accountants", firm + "_admin")
    u = db.query(User).filter(User.username == firm + "_admin").one()
    pw = "Pw-" + firm + "-123456"
    u.password_hash = hash_password(pw)
    out[firm] = {"username": u.username, "password": pw}
db.add(User(username="e2e_a_new", display_name="New User", role="client",
            client_id="e2e_a", password_hash=hash_password("Temp-Pass-123456", one_time=True),
            is_active=True))
db.commit()
out["one_time"] = {"username": "e2e_a_new", "password": "Temp-Pass-123456"}
print(json.dumps(out))
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--api-port", type=int, default=8100)
    ap.add_argument("--web-port", type=int, default=3100)
    a = ap.parse_args()
    work = Path(a.workdir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    if (work / "e2e.db").exists():
        sys.exit(f"{work / 'e2e.db'} exists: give an EMPTY workdir")
    env = backend_env(work, a.web_port)
    seed = subprocess.run([PY, "-c", SEED], cwd=ROOT / "backend", env=env,
                          capture_output=True)
    if seed.returncode:
        sys.exit("seeding failed:\n" + seed.stderr.decode("utf-8", "replace")[-2000:])
    creds = json.loads(seed.stdout.decode("utf-8").strip().splitlines()[-1])
    creds["api"] = f"http://localhost:{a.api_port}"
    creds["web"] = f"http://localhost:{a.web_port}"
    (work / "creds.json").write_text(json.dumps(creds, indent=2), encoding="utf-8")
    procs = []
    with open(work / "backend.log", "wb") as blog, open(work / "web.log", "wb") as wlog:
        procs.append(subprocess.Popen(
            [PY, "-m", "uvicorn", "app.main:app", "--port", str(a.api_port), "--reload"],
            cwd=ROOT / "backend", env=env, stdout=blog, stderr=subprocess.STDOUT))
        wenv = dict(os.environ, BACKEND_URL=creds["api"], NEXT_PUBLIC_API_URL=creds["api"],
                    PORT=str(a.web_port), NEXT_TELEMETRY_DISABLED="1")
        npm = "npm.cmd" if os.name == "nt" else "npm"
        procs.append(subprocess.Popen([npm, "run", "dev", "--", "-p", str(a.web_port)],
                                      cwd=ROOT / "frontend", env=wenv, stdout=wlog,
                                      stderr=subprocess.STDOUT))
        try:
            ok = wait(creds["api"] + "/health") and wait(creds["web"] + "/login", 300)
            print("STACK READY" if ok else "STACK FAILED", flush=True)
            if not ok:
                return 1
            while all(p.poll() is None for p in procs):
                time.sleep(2)
            return 1
        finally:
            for p in procs:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)],
                                   capture_output=True)
                else:
                    p.send_signal(signal.SIGTERM)


if __name__ == "__main__":
    sys.exit(main())
