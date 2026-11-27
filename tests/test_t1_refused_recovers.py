"""Run T1, 1c: a refused request RECOVERS at the document level.

Mocked at urllib (the real GeminiClient's HTTP error path runs; no
network). A 400 for the response schema is asked again without it; a 400
saying the request is too long is asked again in sized pieces; the document
finishes with its rows either way. The >28-field rule (Run T, 11) stays: an
oversized schema is never sent (tests/test_t11_gemini_400.py)."""
from __future__ import annotations

import json
import re
from types import SimpleNamespace

from tests.harness import bootstrap as bs

bs.bootstrap()

from connectors import gemini_client as G  # noqa: E402
from tests.run_q_support import make_pdf, template  # noqa: E402
from tests.test_t11_gemini_400 import _Ok, _http_400  # noqa: E402

ROW = re.compile(r"^(N\d{4}) (\d{2}/\d{2}/2026) (\d+\.\d{2})$")


def _answer(prompt):
    body = prompt.split("=== DOCUMENT TEXT ===", 1)[1].split("=== END DOCUMENT ===", 1)[0]
    page, rows = 1, []
    for ln in body.splitlines():
        m = re.match(r"--- page (\d+) ---", ln)
        if m:
            page = int(m.group(1))
        elif ROW.match(ln.strip()):
            n, d, a = ROW.match(ln.strip()).groups()
            rows.append({"cells": {"Number": n, "Date": d, "Amount": a},
                         "source": ln.strip(), "page": page})
    return rows


def _orch(monkeypatch, refuse):
    """A real GeminiClient behind urlopen; `refuse(body, n_rows)` returns an
    HTTPError to raise or None to answer."""
    calls = []

    def urlopen(req, timeout=None):
        body = json.loads(req.data.decode())
        calls.append(body)
        prompt = body["contents"][0]["parts"][0]["text"]
        rows = _answer(prompt)
        err = refuse(body, len(rows))
        if err is not None:
            raise err
        return _Ok(json.dumps({"fields": {}, "tables": {"Items": rows}}))

    monkeypatch.setattr(G.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(G.time, "sleep", lambda s: None)
    cl = G.GeminiClient(api_key="K")
    monkeypatch.setattr(cl, "fallbacks", lambda: [])
    cl._preferred = "gemini-test"
    return SimpleNamespace(llm=SimpleNamespace(
        extract=lambda prompt="", system_instruction="", image_b64=None, text="", **kw:
        cl.extract_data(text, prompt, system_instruction=system_instruction,
                        **{k: v for k, v in kw.items()
                           if k in ("response_schema", "max_output_tokens",
                                    "thinking_budget")}))), calls


def _pdf(tmp_path, n_pages=2, per=20):
    pages, i = [], 0
    for _p in range(n_pages):
        items, y = [], 750
        for _ in range(per):
            i += 1
            items.append((40, y, f"N{i:04d} 07/{(i % 28) + 1:02d}/2026 {i}.00"))
            y -= 12
        pages.append(items)
    return make_pdf(tmp_path / "d.pdf", pages)


def _tpl():
    return template(tables=[("Items", ["Number", "Date", "Amount"])])


class TestRefusedRequestRecovers:
    def test_schema_refusal_recovers_without_the_schema(self, tmp_path, monkeypatch):
        from extractor import run_extraction
        orch, calls = _orch(monkeypatch, lambda body, n: _http_400()
                            if "responseSchema" in body["generationConfig"] else None)
        ed = run_extraction(orch, _pdf(tmp_path), _tpl())[0].extracted_data
        assert ed.get("document_state") != "FAILED", ed.get("failure_reason")
        assert len(ed["Items_rows"]) == 40
        att = ed["diagnostics"]["attempts"]
        assert att[0]["http_status"] == 400 and att[0]["cause"] == "schema"
        assert any(a.get("retry_reason") == "schema_rejected" for a in att)

    def test_too_long_refusal_recovers_in_smaller_pieces(self, tmp_path, monkeypatch):
        from extractor import run_extraction
        orch, calls = _orch(monkeypatch, lambda body, n: _http_400(
            "The input token count exceeds the maximum number of tokens allowed")
            if n > 25 else None)
        ed = run_extraction(orch, _pdf(tmp_path), _tpl())[0].extracted_data
        assert ed.get("document_state") != "FAILED", ed.get("failure_reason")
        assert [r["Number"] for r in ed["Items_rows"]] == [f"N{i:04d}" for i in range(1, 41)]
        assert any("sized" in s for s in ed["diagnostics"]["call_strategy"])

    def test_any_other_refusal_still_fails_with_its_reason(self, tmp_path, monkeypatch):
        from extractor import run_extraction
        orch, calls = _orch(monkeypatch, lambda body, n: _http_400("API key not valid"))
        ed = run_extraction(orch, _pdf(tmp_path), _tpl())[0].extracted_data
        assert ed["document_state"] == "FAILED"
        assert "API key" in ed["failure_reason"]
