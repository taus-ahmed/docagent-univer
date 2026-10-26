"""No document content in the logs (round 12 A3; docs/SECURITY.md "Logging").

Runs real extractions — the job thread, the engine, the router and the Gemini
client, with only the HTTP call to Gemini replaced — on a PDF whose text, file
name, model answers and option answers all carry a sentinel, and asserts the
sentinel never reaches stdout, stderr or any logger at any level. Real sockets
are blocked, so nothing here can make a provider call.

Covered: a templated run with every option on; a no-template run (inference);
a model answer that is not JSON (the client used to print it); a document that
raises inside the engine (exception messages and tracebacks); a source that is
missing from storage.
"""
from __future__ import annotations

import io
import json
import logging
import re
import socket
import urllib.request
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

SENTINEL = "QZXSECRET"
FILENAME = f"{SENTINEL}FILE_payslip.pdf"
LINES = [
    "INVOICE",
    f"Customer Name {SENTINEL}NAME",
    f"Invoice Number {SENTINEL}INV",
    f"Notes {SENTINEL}BODY text",
]
GRID = {"cells": {"0,0": {"value": "Customer Name"}, "1,0": {"value": "Invoice Number"},
                  "2,0": {"value": "Notes"}},
        "colWidths": [160, 160], "merges": {}, "repeatRows": []}


def _pdf(lines) -> bytes:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    w = PdfWriter()
    page = w.add_blank_page(612, 792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)})})
    ops = ["BT /F1 12 Tf 72 720 Td 16 TL"]
    for ln in lines:
        ops.append(f"({ln}) Tj T*")
    ops.append("ET")
    s = DecodedStreamObject()
    s.set_data("\n".join(ops).encode("latin-1"))
    page[NameObject("/Contents")] = w._add_object(s)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


class _FakeGemini:
    """Stands in for generativelanguage.googleapis.com. Every answer carries
    the sentinel; the first slot answer is not JSON at all."""

    def __init__(self):
        self.calls = 0
        self.broke_once = False

    def _answer(self, prompt: str) -> str:
        slots = re.findall(r'^\s+(F\d+): .*"([^"]+)"$', prompt, re.M)
        if "Return ONLY a JSON object starting with" in prompt and not slots:
            return json.dumps({"fields": {}, "tables": {}})   # the client's retry
        if slots:
            # (the deliberate non-JSON answer moved to the summary call when
            # anomalies became rule-based, Part A3: the retry resends the bad
            # answer, not the prompt, so breaking HERE left nothing extracted)
            by_label = {"Customer Name": LINES[1], "Invoice Number": LINES[2],
                        "Notes": LINES[3]}
            fields = {}
            for sid, label in slots:
                line = by_label.get(label)
                if line:
                    fields[sid] = {"value": line[len(label) + 1:], "source": line, "page": 1}
            return json.dumps({"fields": fields, "tables": {}})
        if '"summary"' in prompt:
            if not self.broke_once:
                self.broke_once = True
                return f"Sorry, I read {SENTINEL}RAW and cannot answer as JSON"
            return json.dumps({"summary": f"The customer {SENTINEL}SUMMARY owes money."})
        if 'Assign a business category' in prompt or '"categories"' in prompt:
            return json.dumps({"categories": [f"{SENTINEL}CAT"]})
        if '"anomalies"' in prompt:
            return json.dumps({"anomalies": [f"{SENTINEL}ANOMALY looks odd"]})
        # Shape inference: design a template from the document.
        return json.dumps({"document_type": "sales_invoice", "title": "Invoice",
                           "fields": [{"label": "Customer Name"},
                                      {"label": "Invoice Number"}],
                           "tables": [], "totals": []})

    def urlopen(self, req, timeout=None):
        self.calls += 1
        body = json.loads(req.data.decode("utf-8"))
        prompt = "\n".join(p.get("text", "") for p in body["contents"][0]["parts"])
        text = self._answer(prompt)
        payload = json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}],
                              "usageMetadata": {"promptTokenCount": 10,
                                                "candidatesTokenCount": 5}}).encode()

        class _Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return _Resp(payload)


@pytest.fixture
def offline(monkeypatch):
    """Gemini answered locally; any real socket is an error."""
    def _no_network(*a, **k):
        raise AssertionError("a test tried to open a network connection")
    monkeypatch.setattr(socket.socket, "connect", _no_network)
    monkeypatch.setattr(socket, "create_connection", _no_network)
    from connectors import gemini_client
    fake = _FakeGemini()
    monkeypatch.setattr(gemini_client.urllib.request, "urlopen", fake.urlopen)
    from app.config import settings
    monkeypatch.setattr(settings, "PRIMARY_LLM", "gemini", raising=False)
    monkeypatch.setattr(settings, "LLM_FALLBACKS", "", raising=False)
    monkeypatch.setattr(settings, "RATE_LIMIT_DELAY", 0, raising=False)
    return fake


@pytest.fixture
def everything_logged(caplog):
    """Every logger, every level."""
    caplog.set_level(logging.DEBUG)
    root = logging.getLogger()
    old = root.level
    root.setLevel(logging.DEBUG)
    yield caplog
    root.setLevel(old)


def _job(db, users, n):
    from app.models.models import ExtractionJob
    j = ExtractionJob(user_id=users["acme"].id, client_id="acme_001", status="pending",
                      total_docs=n, input_source="upload")
    db.add(j)
    db.commit()
    db.refresh(j)
    return j


def _run(db, users, _db_url, monkeypatch, tmp_path, *, template, keys, options=None):
    import orchestrator
    from connectors.llm_router import LLMRouter
    from app.api.routes import extract as ex
    from app.models.models import ColumnTemplate

    store = {}
    for k in keys:
        p = tmp_path / k.replace("/", "_")
        if not k.endswith("missing.pdf"):
            p.write_bytes(_pdf(LINES) if not k.endswith("broken.pdf")
                          else b"%PDF-1.4 " + SENTINEL.encode() + b"BROKEN junk")
            store[k] = p
    monkeypatch.setattr(orchestrator, "Orchestrator",
                        lambda client_schema_path: SimpleNamespace(llm=LLMRouter()))
    monkeypatch.setattr("app.services.job_worker._resolve_source", lambda _s, k: store.get(k))
    template_data = None
    if template:
        tpl = ColumnTemplate(name=f"{SENTINEL}TEMPLATE", document_type="sales_invoice",
                             description=json.dumps(GRID), columns_json="[]")
        template_data = ex._parse_template(tpl)
    job = _job(db, users, len(keys))
    ex._run_extraction_sync(job.id, keys, str(tmp_path / "schema.yaml"), _db_url,
                            template_data, str(bs.REPO_DIR), str(bs.BACKEND_DIR),
                            str(bs.ENGINE_DIR), options=options or [],
                            original_filenames=[FILENAME] * len(keys))
    return job


def _assert_clean(capfd, caplog):
    out, err = capfd.readouterr()
    logged = "\n".join(f"{r.name} {r.levelname} {r.getMessage()} {r.exc_text or ''}"
                       for r in caplog.records)
    for name, text in (("stdout", out), ("stderr", err), ("logging", logged)):
        hits = [ln for ln in text.splitlines() if SENTINEL.lower() in ln.lower()]
        assert not hits, f"{len(hits)} {name} line(s) carry document content:\n" + \
            "\n".join(hits[:15])
    return out


def test_a_templated_run_with_every_option_logs_no_content(
        db, users, _db_url, monkeypatch, tmp_path, offline, everything_logged, capfd):
    from app.models.models import DocumentResult
    job = _run(db, users, _db_url, monkeypatch, tmp_path, template=True,
               keys=[f"clients/acme_001/jobs/1/source/{FILENAME}"],
               options=["categorize", "summary", "narrative", "anomaly"])
    out = _assert_clean(capfd, everything_logged)
    # The run really happened and really carried the sentinel to the result —
    # otherwise a clean log would prove nothing.
    assert offline.calls >= 2 and offline.broke_once
    doc = db.query(DocumentResult).filter(DocumentResult.job_id == job.id).one()
    assert SENTINEL in json.dumps(doc.get_extracted_data())
    assert "[THREAD]" in out and "doc-" in out


def test_a_no_template_run_logs_no_content(
        db, users, _db_url, monkeypatch, tmp_path, offline, everything_logged, capfd):
    _run(db, users, _db_url, monkeypatch, tmp_path, template=False,
         keys=[f"clients/acme_001/jobs/2/source/{FILENAME}"])
    _assert_clean(capfd, everything_logged)
    assert offline.calls >= 1


def test_failures_log_no_content(
        db, users, _db_url, monkeypatch, tmp_path, offline, everything_logged, capfd):
    from app.models.models import DocumentResult
    job = _run(db, users, _db_url, monkeypatch, tmp_path, template=True,
               keys=[f"clients/acme_001/jobs/3/source/{SENTINEL}broken.pdf",
                     f"clients/acme_001/jobs/3/source/{SENTINEL}missing.pdf"])
    _assert_clean(capfd, everything_logged)
    docs = db.query(DocumentResult).filter(DocumentResult.job_id == job.id).all()
    assert len(docs) == 2 and all(not d.overall_confidence or True for d in docs)


def test_doc_ref_is_stable_and_opaque():
    from log_safety import doc_ref
    assert doc_ref(FILENAME) == doc_ref(f"clients/x/jobs/1/source/{FILENAME}")
    assert SENTINEL not in doc_ref(FILENAME) and doc_ref(FILENAME).startswith("doc-")
    assert doc_ref(None) == doc_ref("") == "doc-none"


def test_the_unhandled_exception_handler_logs_no_content(app, everything_logged, capfd):
    """Method and path, the exception's type, frames only — not the query
    string, the message or the request body."""
    import asyncio
    from starlette.requests import Request
    handler = app.exception_handlers[Exception]
    scope = {"type": "http", "method": "POST", "path": "/api/jobs/1",
             "query_string": f"name={SENTINEL}QUERY".encode(), "headers": []}
    try:
        raise ValueError(f"could not parse {SENTINEL}BODY")
    except ValueError as exc:
        resp = asyncio.run(handler(Request(scope), exc))
    assert resp.status_code == 500
    _assert_clean(capfd, everything_logged)
    assert any("ValueError" in r.getMessage() for r in everything_logged.records)


TPL = "QZXTPLTEXT"


def test_a_templates_own_text_is_not_logged(
        db, users, _db_url, monkeypatch, tmp_path, offline, everything_logged, capfd):
    """Run 15 item 7: the template's labels and headings are the firm's own
    text. Labels, a band and a refused two-column band all carry a sentinel."""
    import tests.http.test_logs_carry_no_content as me
    grid = {"cells": {"0,0": {"value": f"Customer Name {TPL}"},
                      "1,0": {"value": f"Invoice Number {TPL}"},
                      "3,0": {"value": f"Item {TPL}"}, "3,1": {"value": f"Qty {TPL}"},
                      "3,2": {"value": f"Amount {TPL}"},
                      "8,0": {"value": f"Total {TPL}"}, "8,1": {"value": f"Tax {TPL}"}},
            "colWidths": [160, 160, 160], "merges": {}, "repeatRows": []}
    monkeypatch.setattr(me, "GRID", grid)
    _run(db, users, _db_url, monkeypatch, tmp_path, template=True,
         keys=[f"clients/acme_001/jobs/4/source/{FILENAME}"])
    out, err = capfd.readouterr()
    logged = out + err + "\n".join(r.getMessage() for r in everything_logged.records)
    hits = [ln for ln in logged.splitlines() if TPL.lower() in ln.lower()]
    assert not hits, "\n".join(hits[:10])
    assert "[THREAD]" in out


def test_a_refused_band_names_its_headings_to_the_user_not_the_log():
    from template_shape import compute_shape
    lines = []
    grid = {"cells": {"0,0": {"value": f"Total {TPL}"}, "0,1": {"value": f"Tax {TPL}"}},
            "colWidths": [], "merges": {}}
    shape = compute_shape(grid, log=lines.append)
    assert any(TPL in s for s in shape["coverage"]["skipped"])
    assert not [ln for ln in lines if TPL in ln], lines
