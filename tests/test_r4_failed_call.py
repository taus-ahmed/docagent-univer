"""Run R, R4 — job 133 (fiserv_merchant_5pg, no template) FAILED.

The stored diagnostics (local_docs/raw/133) say what happened, call by call:
inference answered; the slot call with structured output was refused, HTTP
400 invalid_request (the answer format built for that inferred template);
asked again without it, the whole-document call timed out at the 120 s client
limit, twice, and the document failed as "transient" with the generic
"returned no usable JSON". A 5-page document is under the 6-page threshold
for page-at-a-time calls, so nothing smaller was ever tried.

Fixed: a whole-document call that fails transiently (timeouts, 5xx, rate)
is asked again a page at a time; a document that still fails carries a
`failure_reason` built from its own attempts, used by the job's error
message and the Legend.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.run_q_support import make_pdf, template  # noqa: E402

#: job 133's four attempts, as stored (latency, status and kind only)
JOB_133_ATTEMPTS = [
    {"section": "", "http_status": 200, "error_kind": None, "latency_ms": 32118,
     "structured_output": False, "retry_reason": None},
    {"section": "fields+tables", "http_status": 400, "error_kind": "invalid_request",
     "latency_ms": 971, "structured_output": True, "retry_reason": None},
    {"section": "fields+tables", "http_status": None, "error_kind": "transient",
     "latency_ms": 120170, "structured_output": False, "retry_reason": "schema_rejected"},
    {"section": "fields+tables", "http_status": None, "error_kind": "transient",
     "latency_ms": 120163, "structured_output": False, "retry_reason": "transient"},
]


class TestFailureStory:
    def test_job_133_attempts_say_what_happened(self):
        import llm_contract as C
        s = C.failure_story(JOB_133_ATTEMPTS, timeout_s=120)
        assert "refused" in s and "400" in s
        assert "timed out after 120 s" in s and "twice" in s

    def test_failure_reason_text_prefers_the_story(self):
        from app.services.job_worker import failure_reason_text
        r = SimpleNamespace(extracted_data={"failure_kind": "transient",
                                            "failure_reason": "the call timed out after 120 s"},
                            extraction_response=None)
        assert "timed out after 120 s" in failure_reason_text(r)


class _Resp:
    def __init__(self, parsed, kind=None):
        self.success = parsed is not None
        self.parsed_json = parsed
        self.raw_text = json.dumps(parsed) if parsed is not None else ""
        self.tokens_used, self.model_used = 0, "scripted"
        self.error = "" if parsed is not None else "timed out"
        self.error_kind, self.finish_reason, self.attempts = kind, None, []


def _pages():
    head = "Date Description Amount"
    p1 = [(40, 720, "Merchant Statement"), (40, 700, "Merchant Number 12345"),
          (40, 680, head), (40, 660, "07/01/2026 Sale 10.00"),
          (40, 640, "07/02/2026 Sale 20.00")]
    p2 = [(40, 720, "Merchant Statement"), (40, 680, head),
          (40, 660, "07/03/2026 Sale 30.00"), (40, 640, "07/04/2026 Sale 40.00")]
    return [p1, p2]


class TestTimeoutFallsBackToPages:
    def test_a_timed_out_whole_document_call_is_asked_a_page_at_a_time(self, tmp_path):
        from extractor import run_extraction
        pdf = make_pdf(tmp_path / "m.pdf", _pages())
        tpl = template(fields=["Merchant Number"],
                       tables=[("Sales", ["Date", "Description", "Amount"])],
                       doc_type="bank_statement")
        calls = []

        def extract(prompt="", system_instruction="", **kw):
            calls.append(prompt)
            if len(calls) == 1:
                return _Resp(None, "transient")            # the 120 s timeout
            if "sent on its own" in prompt:
                rows = [{"cells": {"Date": d, "Description": "Sale", "Amount": a},
                         "source": f"{d} Sale {a}", "page": 1}
                        for d, a in (("07/01/2026", "10.00"), ("07/02/2026", "20.00"))
                        if d in prompt] + [
                        {"cells": {"Date": d, "Description": "Sale", "Amount": a},
                         "source": f"{d} Sale {a}", "page": 1}
                        for d, a in (("07/03/2026", "30.00"), ("07/04/2026", "40.00"))
                        if d in prompt]
                return _Resp({"tables": {"Sales": rows}})
            import re
            ids = re.findall(r"^\s+(F\d+): ", prompt, re.M)
            return _Resp({"fields": {i: {"value": "12345", "source": "Merchant Number 12345",
                                         "page": 1, "status": "found"} for i in ids},
                          "tables": {}})

        orch = SimpleNamespace(llm=SimpleNamespace(extract=extract))
        res = run_extraction(orch, pdf, tpl)
        ed = res[0].extracted_data
        assert ed.get("document_state") != "FAILED", ed.get("failure_reason")
        assert [r["Amount"] for r in ed["Sales_rows"]] == ["10.00", "20.00", "30.00", "40.00"]
        assert any("page at a time" in n for n in ed["validation_notes"])

    def test_a_refused_request_is_not_retried_by_page(self, tmp_path):
        # 400 is our request being wrong - asking five times smaller does not
        # make it right, and is not tried
        from extractor import run_extraction
        pdf = make_pdf(tmp_path / "m.pdf", _pages())
        tpl = template(fields=["Merchant Number"],
                       tables=[("Sales", ["Date", "Description", "Amount"])],
                       doc_type="bank_statement")
        calls = []

        def extract(prompt="", system_instruction="", **kw):
            calls.append(prompt)
            return _Resp(None, "invalid_request")

        res = run_extraction(SimpleNamespace(llm=SimpleNamespace(extract=extract)), pdf, tpl)
        ed = res[0].extracted_data
        assert ed["document_state"] == "FAILED"
        assert len(calls) == 1
        assert ed.get("failure_reason")


class TestJob133Real:
    def test_stored_failure_has_a_reason_now(self):
        p = ROOT / "local_docs" / "raw" / "133" / "docs" / "156.json"
        if not p.is_file():
            pytest.skip("local_docs/raw/133 not present (git-ignored real data)")
        import llm_contract as C
        ed = json.loads(p.read_text(encoding="utf-8"))["extraction_json"]
        s = C.failure_story(ed["diagnostics"]["attempts"], timeout_s=120)
        assert "400" in s and "timed out after 120 s" in s
