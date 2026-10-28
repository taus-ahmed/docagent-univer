#!/usr/bin/env python
"""Demo acceptance — the demo's own flow, end to end, against a running backend.

    python scripts/demo_acceptance.py --base-url http://127.0.0.1:8100 --creds <workdir>/creds.json
    python scripts/demo_acceptance.py --base-url https://staging.example.com      # DEMO_USER / DEMO_PASSWORD

Steps: sign in; upload a GENERATED fixture (a two-invoice PDF made here, so
nothing from a client is ever needed); wait for the job; open the review
queue and mark the first document reviewed; download the export and check it
is a workbook that contains the extracted invoice numbers; sign out. Prints a
pass/fail line per step and exits 0 only when every step passed.

Credentials come from `--creds` (the creds.json `scripts/e2e/stack.py` writes;
firm `e2e_a`) or from DEMO_USER / DEMO_PASSWORD. They are never printed.
Standard library only (it reuses scripts/smoke_test.py's client); it creates
one job and changes nothing else.

The browser version of the same flow is frontend/e2e/demo-acceptance.spec.cjs.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_test import Api  # noqa: E402

INVOICES = [
    ["ACME TRADING LTD", "INVOICE", "Invoice No: INV-9001", "Invoice Date: 2024-03-15",
     "Bill To: Globex Corporation", "Total: $125.00"],
    ["ACME TRADING LTD", "INVOICE", "Invoice No: INV-9002", "Invoice Date: 2024-03-22",
     "Bill To: Initech Ltd", "Total: $310.40"],
]


def fixture_pdf(pages=INVOICES) -> bytes:
    """A text PDF, one page per entry, one line per string (Helvetica)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None,
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lines in pages:
        esc = [ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for ln in lines]
        body = "BT /F1 12 Tf 72 720 Td 16 TL " + " ".join(f"({t}) Tj T*" for t in esc) + " ET"
        objs.append(f"<< /Length {len(body)} >>\nstream\n{body}\nendstream")
        content = len(objs)
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Contents {content} 0 R /Resources << /Font << /F1 3 0 R >> >> >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offs = "%PDF-1.4\n", []
    for i, o in enumerate(objs):
        offs.append(len(out))
        out += f"{i + 1} 0 obj\n{o}\nendobj\n"
    x = len(out)
    out += (f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n"
            + "".join(f"{o:010d} 00000 n \n" for o in offs)
            + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n")
    return out.encode("latin-1")


def _credentials(path):
    if path:
        c = json.loads(Path(path).read_text(encoding="utf-8"))
        a = c.get("e2e_a") or {}
        return a.get("username"), a.get("password")
    return os.environ.get("DEMO_USER"), os.environ.get("DEMO_PASSWORD")


def _workbook_text(content: bytes) -> str:
    """Every shared/inline string in an .xlsx, for a containment check."""
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        return " ".join(z.read(n).decode("utf-8", "replace") for n in z.namelist()
                        if n.startswith("xl/") and n.endswith(".xml"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--creds", help="creds.json from scripts/e2e/stack.py (firm e2e_a)")
    ap.add_argument("--timeout", type=int, default=300, help="seconds to wait for the job")
    a = ap.parse_args(argv)
    user, pw = _credentials(a.creds)
    if not (user and pw):
        print("give --creds or set DEMO_USER and DEMO_PASSWORD (never printed)")
        return 2
    rows = []

    def step(name, ok, note=""):
        rows.append((name, bool(ok), note))
        return bool(ok)

    api = Api(a.base_url)
    t0 = time.time()
    job_id, docs = None, []
    if step("sign in", api.login(user, pw) == 200):
        st, body = api.call("POST", "/api/extract/upload",
                            files=[("demo-two-invoices.pdf", fixture_pdf())])
        job_id = body.get("job_id") if isinstance(body, dict) else None
        step("upload a generated two-invoice PDF", st in (200, 202) and job_id,
             f"HTTP {st} job {job_id}")
    if job_id:
        status, end = None, time.time() + a.timeout
        while time.time() < end:
            _st, body = api.call("GET", f"/api/jobs/{job_id}")
            status = (body or {}).get("status")
            if status in ("completed", "partial", "failed", "cancelled"):
                break
            time.sleep(2)
        step("wait for the job", status in ("completed", "partial"), f"status {status}")
        st, docs = api.call("GET", f"/api/jobs/{job_id}/results")
        docs = docs if isinstance(docs, list) else []
        step("results", st == 200 and len(docs) >= 1,
             f"HTTP {st}, {len(docs)} document(s) (two expected when the file is split)")
        st, queue = api.call("GET", f"/api/jobs/{job_id}/review")
        step("open the review queue", st == 200, f"HTTP {st}")
        if docs:
            doc_id = docs[0].get("id")
            st, body = api.call("POST", f"/api/jobs/{job_id}/docs/{doc_id}/review",
                                {"scope": "document", "reviewed": True})
            step("mark a document reviewed", st == 200 and (body or {}).get("document_reviewed"),
                 f"HTTP {st}")
        st, content = api.call("GET", f"/api/jobs/{job_id}/export", raw=True)
        is_xlsx = st == 200 and isinstance(content, bytes) and content[:2] == b"PK"
        text = _workbook_text(content) if is_xlsx else ""
        found = [n for n in ("INV-9001", "INV-9002") if n in text]
        step("export a workbook holding the invoices", is_xlsx and found,
             f"HTTP {st}, {len(content) if isinstance(content, bytes) else 0} bytes, "
             f"found {', '.join(found) or 'none'}")
    if api.token:
        st, _ = api.call("POST", "/api/auth/logout")
        step("sign out", st == 200, f"HTTP {st}")
    width = max(len(n) for n, _o, _x in rows)
    for name, ok, note in rows:
        print(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {note}")
    failed = sum(1 for _n, ok, _x in rows if not ok)
    print(f"{len(rows) - failed} passed, {failed} failed in {time.time() - t0:.1f}s")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
