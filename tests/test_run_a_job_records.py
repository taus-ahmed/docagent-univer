"""Run A acceptance tests on the four staging job records (jobs 15, 19, 21,
25), with the model MOCKED: the first call returns exactly what Gemini
returned on staging (`raw_llm_responses`), and the targeted second call
returns whatever each test scripts.

The records, the PDFs and the template workbook live in `local_docs/`, which
is git-ignored owner material; every test here SKIPS when it is absent (CI).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

import llm_contract as C  # noqa: E402
from connectors.base import LLMResponse  # noqa: E402

LOCAL = Path(__file__).resolve().parents[1] / "local_docs"
DOCS = LOCAL / "DocAgent_testdocs"
XLSX = LOCAL / "DocAgent_templates_v2.xlsx"

pytestmark = pytest.mark.skipif(
    not (LOCAL / "job_records" / "job15.json").exists() or not XLSX.exists(),
    reason="local_docs/ (owner test material, git-ignored) is not present")


def _record(job):
    return json.loads((LOCAL / "job_records" / f"job{job}.json")
                      .read_text(encoding="utf-8"))[0]


def _grid(sheet):
    import openpyxl
    ws = openpyxl.load_workbook(XLSX)[sheet]
    cells = {f"{c.row - 1},{c.column - 1}": {"value": str(c.value)}
             for row in ws.iter_rows() for c in row
             if c.value is not None and str(c.value).strip()}
    merges = {f"{m.min_row - 1},{m.min_col - 1}":
              {"rows": m.max_row - m.min_row + 1, "cols": m.max_col - m.min_col + 1}
              for m in ws.merged_cells.ranges}
    return {"cells": cells, "merges": merges, "colWidths": [], "repeatRows": []}


def _run(rel, sheet, doc_type, script):
    """run_slot_extraction on the real PDF and template, the model scripted:
    `script(call_number, kwargs)` returns the parsed answer or None."""
    from core.preprocessor import preprocess_file
    from slot_extractor import run_slot_extraction
    doc = preprocess_file(DOCS / rel)
    calls = []

    def extract(**kw):
        calls.append(kw)
        obj = script(len(calls), kw)
        if obj is None:
            return LLMResponse(raw_text="", success=False, error_kind=C.INVALID_JSON,
                               error="mock: no answer")
        return LLMResponse(raw_text=json.dumps(obj), parsed_json=obj, success=True,
                           model_used="gemini-2.5-flash")
    n = len(doc.page_texts)
    with C.collect_attempts(fresh=True):
        r = run_slot_extraction(
            SimpleNamespace(llm=SimpleNamespace(extract=extract)), DOCS / rel,
            {"layout": _grid(sheet)}, None, page_images=[],
            doc_text=doc.extracted_text, doc_text_pages=doc.page_texts,
            file_type="digital_pdf", default_doc_type=doc_type, start=0.0,
            page_lines=doc.page_lines,
            page_origins={i + 1: o for i, o in enumerate(doc.page_origins)},
            page_numbers=list(range(1, n + 1)),
            widget_values=doc.widget_values, unreadable={})[0]
    return r, calls, doc


def _raw(job):
    return json.loads(_record(job)["extracted_data"]["raw_llm_responses"][0])


# ── job 15: valid JSON, no `tables` key ──────────────────────────────────────

_CREDIT = re.compile(r"CREDIT|DEPOSIT|WIRE IN|ZELLE", re.I)
_MONEY = re.compile(r"\d[\d,]*\.\d{2}")


def _job15_rows(doc):
    """The twelve transactions, read from the page the way a correct model
    answer reads them (source = the printed line)."""
    from text_layer import text_from_lines
    rows = []
    for ln in doc.page_lines[0]:
        line = text_from_lines([ln])
        if not re.match(r"\d\d/\d\d/2026 ", line) or "BEGINNING BALANCE" in line:
            continue
        nums = _MONEY.findall(line)
        if len(nums) < 2:
            continue
        date = line[:10]
        desc = line[11:line.find(nums[-2])].strip().rstrip("E").strip()
        amt, bal = nums[-2], nums[-1]
        dep = bool(_CREDIT.search(desc))
        rows.append({"cells": {"Date": date, "Description": desc, "Check Number": "",
                               "Withdrawal": "" if dep else amt,
                               "Deposit": amt if dep else "",
                               "Running Balance": bal, "GL Account": "", "Memo": ""},
                     "source": line, "page": 1})
    return rows


SUMMARY = "$18,240.12 $10,309.62 $12,445.50 $20,376.00"


class TestJob15:
    def test_the_recorded_answer_breaks_the_contract(self):
        from slot_extractor import enumerate_slots
        from template_shape import compute_shape
        g = _grid("Bank_Recon")
        slots = enumerate_slots(g, compute_shape(g, log=lambda m: None))
        kinds = {f["kind"] for f in C.check_answer(_raw(15), slots)}
        assert kinds == {C.MISSING_SLOT, C.MISSING_TABLE}

    def test_the_targeted_second_call_fills_the_table(self):
        holder = {}

        def script(n, kw):
            if n == 1:
                return _raw(15)
            assert "SECOND REQUEST" in kw["prompt"]
            ans = {"tables": {"table": _job15_rows(holder["doc"])}}
            ans["fields"] = {sid: {"value": v, "source": SUMMARY, "page": 1}
                             for sid, v in (("F9", "$12,445.50"), ("F10", "$10,309.62"),
                                            ("F14", "$10,309.62"), ("F15", "$12,445.50"))}
            return ans
        from core.preprocessor import preprocess_file
        holder["doc"] = preprocess_file(DOCS / "bank_statement/flowparse_bank_us.pdf")
        r, calls, _doc = _run("bank_statement/flowparse_bank_us.pdf", "Bank_Recon",
                              "bank_statement", script)
        ed = r.extracted_data
        assert len(calls) == 2
        assert '"table"' in calls[1]["prompt"] or "TABLE \"table\"" in calls[1]["prompt"]
        assert len(ed["table_rows"]) == 12
        assert ed["document_state"] in ("READY", "NEEDS_REVIEW"), ed["attention"]
        assert ed["diagnostics"]["contract"]["retried_tables"] == ["table"]

    def test_when_the_second_call_fails_too_it_needs_attention_never_ready(self):
        r, calls, _doc = _run("bank_statement/flowparse_bank_us.pdf", "Bank_Recon",
                              "bank_statement",
                              lambda n, kw: _raw(15) if n == 1 else {"fields": {}})
        ed = r.extracted_data
        assert len(calls) == 2
        assert ed["document_state"] == "NEEDS_ATTENTION"
        texts = " ".join(a["text"] for a in ed["attention"])
        assert "about 12 transaction lines but 0 were extracted" in texts
        assert "10,309.62" in texts
        assert ed["table_rows"] == []


# ── jobs 21 / 25: fillable forms answered empty ─────────────────────────────

class TestFillableForms:
    @pytest.mark.parametrize("job,rel,sheet", [
        (21, "w2/irs_w2_mod11.pdf", "W2_Full"),
        (25, "1099/irs_1099nec_ellis.pdf", "F1099_NEC_MISC")])
    def test_widget_values_now_reach_the_text_the_model_reads(self, job, rel, sheet):
        r, calls, doc = _run(rel, sheet, "other", lambda n, kw: _raw(job))
        want = {21: ["222-00-2314", "10535", "SETH W. WIGGINS"],
                25: ["Nancy Ellis", "15,250", "Printing Corporation"]}[job]
        for v in want:
            assert v in calls[0]["prompt"], v

    @pytest.mark.parametrize("job,rel,sheet", [
        (21, "w2/irs_w2_mod11.pdf", "W2_Full"),
        (25, "1099/irs_1099nec_ellis.pdf", "F1099_NEC_MISC")])
    def test_empty_answers_need_attention_and_empty_flagged_fires(self, job, rel, sheet,
                                                                  monkeypatch):
        """The Run A safety net, with the Run B form-field lane switched off
        (no widget matches a slot). With the lane on, the same answers are
        filled from the widgets: tests/test_run_b_forms.py."""
        import form_fields
        monkeypatch.setattr(form_fields, "match", lambda *a, **k: (None, False))
        from app.core import review as R
        r, calls, _doc = _run(rel, sheet, "other",
                              lambda n, kw: _raw(job) if n == 1 else {"fields": {}})
        ed = r.extracted_data
        assert len(calls) == 2 and "SECOND REQUEST" in calls[1]["prompt"]
        assert ed["document_state"] == "NEEDS_ATTENTION"
        assert any("filled form field" in a["text"] for a in ed["attention"])
        statuses = [v["status"] for v in R.document_values(ed)]
        assert statuses.count("empty_flagged") >= 5
        # review cannot erase it: no document-level mark until each is settled
        assert R.document_state(ed) == "NEEDS_ATTENTION"
        stamp = {"by": "t", "at": "now"}
        R.apply_dispositions(ed, [{"id": a["id"], "choice": "confirmed_absent"}
                                  for a in ed["attention"]], stamp)
        assert R.attention_open(ed) == []
        assert R.document_state(ed) != "NEEDS_ATTENTION"

    def test_a_retry_that_fills_the_values_clears_the_attention(self):
        def script(n, kw):
            if n == 1:
                return _raw(25)
            return {"fields": {
                "F4": {"value": "Printing Corporation", "source": "Printing Corporation", "page": 1},
                "F5": {"value": "Nancy Ellis", "source": "Nancy Ellis", "page": 1},
                "F7": {"value": "XXX-XX-XXXX", "source": "10-XXXXXXX XXX-XX-XXXX 15,250 Copy 1", "page": 1},
                "F6": {"value": "10-XXXXXXX", "source": "10-XXXXXXX XXX-XX-XXXX 15,250 Copy 1", "page": 1},
                "F10": {"value": "15,250", "source": "10-XXXXXXX XXX-XX-XXXX 15,250 Copy 1", "page": 1},
            }}
        r, calls, _doc = _run("1099/irs_1099nec_ellis.pdf", "F1099_NEC_MISC", "other",
                              script)
        ed = r.extracted_data
        placed = set(ed["extracted_fields"].values())
        assert {"Nancy Ellis", "15,250"} <= placed
        assert not any("filled form field" in a["text"] for a in ed["attention"])


# ── job 19: the healthy case ─────────────────────────────────────────────────

class TestJob19:
    def test_ready_no_new_flags_output_unchanged(self):
        rec = _record(19)["extracted_data"]
        r, calls, _doc = _run("purchase_order/flowparse_po.pdf", "PO_Full",
                              "purchase_order", lambda n, kw: _raw(19))
        ed = r.extracted_data
        assert len(calls) == 1                         # no second request
        assert ed["document_state"] == "READY", ed["attention"]
        assert ed["attention"] == []
        assert ed["extracted_fields"] == rec["extracted_fields"]
        strip = lambda rows: [{k: v for k, v in x.items() if not k.startswith("_")}
                              for x in rows]
        assert strip(ed["table_rows"]) == strip(rec["table_rows"])
        old = {f["ref"] for f in rec["validation"]["flagged_fields"]}
        new = {f["ref"] for f in ed["validation"]["flagged_fields"]}
        assert new <= old
