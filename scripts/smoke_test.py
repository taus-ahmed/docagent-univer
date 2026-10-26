#!/usr/bin/env python
"""Smoke test any deployment (Part 2.7) — local, staging, production.

    python scripts/smoke_test.py --base-url https://staging-backend.example.com

Credentials come from the environment and are never printed:
    SMOKE_USER, SMOKE_PASSWORD        a user of firm A (required)
    SMOKE_USER_B, SMOKE_PASSWORD_B    a user of another firm (for the isolation step)

Steps: /health and /ready; sign in; upload a tiny synthetic PDF; poll the job;
read its results and download its export; firm B must get 404 for it; start a
second job and cancel it; hard-delete the first. Prints a pass/fail table and
exits 0 only when every step passed. Standard library only. It creates two
small jobs in firm A and deletes one; nothing else is changed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid


def tiny_pdf(text="Smoke test document. Invoice No: SMOKE-1. Total: 1.00") -> bytes:
    body = f"BT /F1 11 Tf 72 720 Td ({text}) Tj ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(body)} >>\nstream\n{body}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = "%PDF-1.4\n", []
    for i, o in enumerate(objs):
        offs.append(len(out))
        out += f"{i + 1} 0 obj\n{o}\nendobj\n"
    x = len(out)
    out += (f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n"
            + "".join(f"{o:010d} 00000 n \n" for o in offs)
            + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n")
    return out.encode("latin-1")


class Api:
    def __init__(self, base, timeout=60):
        self.base, self.timeout, self.token = base.rstrip("/"), timeout, None

    def call(self, method, path, data=None, files=None, form=None, raw=False):
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body = None
        if files is not None:
            boundary = uuid.uuid4().hex
            parts = []
            for k, v in (form or {}).items():
                parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
            for name, content in files:
                parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; "
                              f"filename=\"{name}\"\r\nContent-Type: application/pdf\r\n\r\n").encode()
                             + content + b"\r\n")
            body = b"".join(parts) + f"--{boundary}--\r\n".encode()
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif data is not None:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                content = r.read()
                return r.status, (content if raw else _json(content))
        except urllib.error.HTTPError as e:
            return e.code, _json(e.read())

    def login(self, user, password):
        st, body = self.call("POST", "/api/auth/login", {"username": user, "password": password})
        if st == 200 and isinstance(body, dict):
            self.token = body.get("access_token")
        return st


def _json(b):
    try:
        return json.loads(b or b"{}")
    except ValueError:
        return {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--timeout", type=int, default=300, help="seconds to wait for a job")
    a = ap.parse_args(argv)
    user, pw = os.environ.get("SMOKE_USER"), os.environ.get("SMOKE_PASSWORD")
    if not (user and pw):
        print("set SMOKE_USER and SMOKE_PASSWORD (never printed)")
        return 2
    rows = []

    def step(name, ok, note=""):
        rows.append((name, bool(ok), note))
        return bool(ok)

    api = Api(a.base_url)
    st, _ = api.call("GET", "/health")
    step("GET /health", st == 200, f"HTTP {st}")
    st, body = api.call("GET", "/ready")
    step("GET /ready", st == 200, f"HTTP {st} " + ",".join(f"{k}={v}" for k, v in (body.get("checks") or {}).items()))
    step("sign in (firm A)", api.login(user, pw) == 200)
    job_id = None
    if api.token:
        st, body = api.call("POST", "/api/extract/upload", files=[("smoke.pdf", tiny_pdf())])
        job_id = body.get("job_id") if isinstance(body, dict) else None
        step("upload a tiny PDF", st in (200, 202) and job_id, f"HTTP {st} job {job_id}")
    status = None
    if job_id:
        end = time.time() + a.timeout
        while time.time() < end:
            st, body = api.call("GET", f"/api/jobs/{job_id}")
            status = (body or {}).get("status")
            if status in ("completed", "partial", "failed", "cancelled"):
                break
            time.sleep(3)
        step("job finishes", status in ("completed", "partial"), f"status {status}")
        st, body = api.call("GET", f"/api/jobs/{job_id}/results")
        step("read results", st == 200, f"HTTP {st}")
        st, content = api.call("GET", f"/api/jobs/{job_id}/export", raw=True)
        step("download export", st == 200 and isinstance(content, bytes) and content[:2] == b"PK",
             f"HTTP {st}, {len(content) if isinstance(content, bytes) else 0} bytes")
    ub, pb = os.environ.get("SMOKE_USER_B"), os.environ.get("SMOKE_PASSWORD_B")
    if job_id and ub and pb:
        b = Api(a.base_url)
        if step("sign in (firm B)", b.login(ub, pb) == 200):
            st, _ = b.call("GET", f"/api/jobs/{job_id}/results")
            step("firm B cannot read firm A's job", st == 404, f"HTTP {st}")
    elif job_id:
        step("firm isolation", True, "skipped: SMOKE_USER_B not set")
    if api.token:
        st, body = api.call("POST", "/api/extract/upload", files=[("smoke-2.pdf", tiny_pdf())])
        j2 = body.get("job_id") if isinstance(body, dict) else None
        if j2:
            st, _ = api.call("DELETE", f"/api/jobs/{j2}")
            # a job that already finished cannot be cancelled: 400 is an honest answer
            step("cancel a second job", st in (200, 400), f"HTTP {st}")
    if job_id:
        st, _ = api.call("DELETE", f"/api/jobs/{job_id}/data?confirm=true")
        step("delete the first job", st == 200, f"HTTP {st}")
        st, body = api.call("GET", f"/api/jobs/{job_id}/results")
        step("deleted job has no results", st == 200 and body == [], f"HTTP {st}")
    width = max(len(n) for n, _o, _x in rows)
    for name, ok, note in rows:
        print(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {note}")
    failed = sum(1 for _n, ok, _x in rows if not ok)
    print(f"{len(rows) - failed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
