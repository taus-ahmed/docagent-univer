"""Run A — the model's answer is untrusted until validated; the page decides
what counts as complete. Engine-level, no live calls, no local_docs needed.

  A0  every attempt recorded; tokens include THINKING; cost by model returned
  A2  typed failures; transient retried with backoff, invalid never retried;
      MAX_TOKENS retried once with a larger cap and less thinking
  A3  the source inventory and the coverage gate
  A4  document states
  A7  a scan page OCR read nothing from is NEEDS_ATTENTION
  A8  page-at-a-time tables: a failed page is retried ALONE and the other
      pages are kept; a page printing no part of the band gives no rows
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

import llm_contract as C  # noqa: E402
import source_inventory as SI  # noqa: E402
from connectors.base import LLMResponse  # noqa: E402
from text_layer import stamp_page  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────────

def _lines(page_no, texts):
    """Synthetic page words: one visual line per string. A line may be a
    tuple of cells, placed in columns at x = 40, 160, 320, 420."""
    out = []
    for i, t in enumerate(texts):
        cells = t if isinstance(t, tuple) else (t,)
        ln = []
        for col, cell in enumerate(cells):
            x = (40.0, 160.0, 320.0, 420.0)[col] if isinstance(t, tuple) else 40.0
            for w in str(cell).split():
                ln.append({"text": w, "x0": x, "x1": x + 6 * len(w),
                           "top": 50.0 + 14 * i, "bottom": 60.0 + 14 * i})
                x += 6 * len(w) + 6
        out.append(ln)
    stamp_page(out, page_no)
    return out


def _resp(obj, **kw):
    return LLMResponse(raw_text="{}", parsed_json=obj, success=obj is not None,
                       model_used="gemini-2.5-flash", **kw)


class _Gemini:
    """A GeminiClient whose HTTP layer is scripted."""

    def __init__(self, script):
        from connectors.gemini_client import GeminiClient
        self.client = GeminiClient(api_key="test-not-a-key")
        self.script = list(script)
        self.bodies = []

        def post(model, body, timeout):
            self.bodies.append(body)
            step = self.script.pop(0)
            if isinstance(step, Exception):
                raise step
            return step
        self.client._post = post


def _ok(text='{"fields": {}}', finish="STOP", thoughts=None):
    return text, {"http_status": 200, "model_version": "gemini-2.5-flash-001",
                  "candidate_count": 1, "prompt_tokens": 1000,
                  "output_tokens": 200, "thinking_tokens": thoughts,
                  "finish_reason": finish, "block_reason": None}


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []
    import connectors.gemini_client as G
    monkeypatch.setattr(G.time, "sleep", lambda s: slept.append(s))
    return slept


# ── A0: attempts, thinking tokens, cost ──────────────────────────────────────

class TestAttemptRecords:
    def test_tokens_used_includes_thinking_tokens(self, no_sleep):
        g = _Gemini([_ok(thoughts=3000)])
        with C.collect_attempts(fresh=True) as att:
            r = g.client.extract_data("", "p")
        assert r.success
        assert r.tokens_used == 1000 + 200 + 3000
        a = att[-1]
        assert (a["prompt_tokens"], a["output_tokens"], a["thinking_tokens"]) == (1000, 200, 3000)
        assert a["model_version"] == "gemini-2.5-flash-001"
        assert a["finish_reason"] == "STOP" and a["parse"] == "ok"

    def test_cost_is_priced_by_the_model_returned_with_thinking_as_output(self, no_sleep):
        g = _Gemini([_ok(thoughts=3000)])
        with C.collect_attempts(fresh=True) as att:
            g.client.extract_data("", "p")
        # gemini-2.5-flash: 0.30 / 2.50 per 1M; output = 200 + 3000 thinking
        assert att[-1]["cost_estimate"] == pytest.approx(1000 / 1e6 * 0.30 + 3200 / 1e6 * 2.50)

    def test_a_counter_the_api_did_not_report_is_none_not_zero(self, no_sleep):
        g = _Gemini([_ok(thoughts=None)])
        with C.collect_attempts(fresh=True) as att:
            g.client.extract_data("", "p")
        assert att[-1]["thinking_tokens"] is None
        assert C.summarise([{"prompt_tokens": None}])["total_tokens"] is None

    def test_the_log_line_carries_no_content(self, no_sleep, capsys):
        g = _Gemini([_ok(text='{"fields": {"F1": {"value": "SECRET-VALUE-123"}}}')])
        g.client.extract_data("SECRET-DOC-TEXT", "SECRET-PROMPT")
        out = capsys.readouterr().out
        line = [ln for ln in out.splitlines() if ln.startswith("[LLM-ATTEMPT]")]
        assert line and "thinking_tokens=" in line[-1]
        assert "SECRET" not in out and "test-not-a-key" not in out


# ── A2: transport retries ────────────────────────────────────────────────────

class TestTransportRetries:
    def test_503_is_retried_with_backoff_and_succeeds(self, no_sleep):
        g = _Gemini([C.LLMCallError(C.TRANSIENT, "HTTP 503", status=503), _ok()])
        with C.collect_attempts(fresh=True) as att:
            r = g.client.extract_data("", "p")
        assert r.success and len(att) == 2
        assert att[0]["error_kind"] == C.TRANSIENT and att[0]["http_status"] == 503
        assert att[1]["retry_reason"] == "transient:503"
        assert len(no_sleep) == 1 and no_sleep[0] >= 1.0

    def test_429_honours_retry_after(self, no_sleep):
        g = _Gemini([C.LLMCallError(C.TRANSIENT, "HTTP 429", status=429,
                                    retry_after=7.0), _ok()])
        assert g.client.extract_data("", "p").success
        assert no_sleep == [pytest.approx(7.0, abs=0.01)] or no_sleep[0] >= 7.0

    def test_transient_attempts_are_capped_at_three(self, no_sleep):
        err = C.LLMCallError(C.TRANSIENT, "HTTP 503", status=503)
        g = _Gemini([err, err, err, _ok()])
        r = g.client.extract_data("", "p")
        assert not r.success and r.error_kind == C.TRANSIENT
        assert len(g.bodies) == 3 and len(no_sleep) == 2

    def test_an_invalid_request_is_never_retried(self, no_sleep):
        g = _Gemini([C.LLMCallError(C.INVALID_REQUEST, "HTTP 400", status=400), _ok()])
        r = g.client.extract_data("", "p")
        assert not r.success and r.error_kind == C.INVALID_REQUEST
        assert len(g.bodies) == 1 and no_sleep == []

    def test_an_exhausted_quota_is_never_retried(self, no_sleep):
        from connectors.gemini_client import classify_http
        assert classify_http(429, b'{"quotaId": "GenerateRequestsPerDayPerProjectPerModel"}') == C.QUOTA
        g = _Gemini([C.LLMCallError(C.QUOTA, "HTTP 429", status=429), _ok()])
        assert not g.client.extract_data("", "p").success
        assert len(g.bodies) == 1

    def test_a_503_does_not_silently_switch_models(self, no_sleep):
        err = C.LLMCallError(C.TRANSIENT, "HTTP 503", status=503)
        g = _Gemini([err, err, err])
        g.client.extract_data("", "p")
        assert len(g.bodies) == 3          # same model, never the next candidate

    def test_a_refused_schema_is_asked_once_more_without_it(self, no_sleep):
        g = _Gemini([C.LLMCallError(C.INVALID_REQUEST, "HTTP 400", status=400), _ok()])
        r = g.client.extract_data("", "p", response_schema={"type": "OBJECT"})
        assert r.success
        assert "responseSchema" in g.bodies[0]["generationConfig"]
        assert "responseSchema" not in g.bodies[1]["generationConfig"]


# ── A2: answer-level failures and the logical-call retries ──────────────────

class TestAnswerFailures:
    def test_max_tokens_is_typed_and_never_parsed(self, no_sleep):
        g = _Gemini([_ok(text='{"fields": {}}', finish="MAX_TOKENS")])
        r = g.client.extract_data("", "p")
        assert not r.success and r.error_kind == C.MAX_TOKENS and r.parsed_json is None

    def test_a_parse_failure_is_not_re_asked_behind_the_callers_back(self, no_sleep):
        g = _Gemini([_ok(text='{"fields": {"F1": '), _ok()])
        r = g.client.extract_data("", "p")
        assert not r.success and r.error_kind == C.INVALID_JSON
        assert len(g.bodies) == 1

    def test_max_tokens_retries_that_call_once_with_a_bigger_cap_and_no_thinking(self):
        from extractor import _llm_json
        calls = []

        def extract(**kw):
            calls.append(kw)
            if len(calls) == 1:
                return LLMResponse(raw_text="", success=False, error_kind=C.MAX_TOKENS)
            return _resp({"fields": {}})
        parsed, _r = _llm_json(SimpleNamespace(llm=SimpleNamespace(extract=extract)),
                               "p", "s", text="t", max_output_tokens=8000)
        assert parsed == {"fields": {}} and len(calls) == 2
        assert calls[1]["max_output_tokens"] == 16000
        assert calls[1]["thinking_budget"] == 0

    @pytest.mark.parametrize("kind", [C.QUOTA, C.INVALID_REQUEST, C.BLOCKED,
                                      C.TRANSIENT])
    def test_terminal_failures_are_not_retried_by_the_logical_call(self, kind):
        from extractor import _llm_json
        calls = []

        def extract(**kw):
            calls.append(kw)
            return LLMResponse(raw_text="", success=False, error_kind=kind)
        parsed, r = _llm_json(SimpleNamespace(llm=SimpleNamespace(extract=extract)),
                              "p", "s", text="t")
        assert parsed is None and len(calls) == 1 and r.error_kind == kind


# ── A2: the response contract ────────────────────────────────────────────────

SLOTS = {"fields": [{"slot_id": "F1", "ref": "B1", "row_label": "Bank Name",
                     "section": ""},
                    {"slot_id": "F2", "ref": "B2", "row_label": "Closing Balance",
                     "section": ""}],
         "tables": [{"name": "table", "columns": [
             {"header": "Date", "key": "Date"}, {"header": "Amount", "key": "Amount"}],
             "start_row": 5, "end_row": 20, "section": ""}]}


class TestContract:
    def test_the_schema_requires_every_slot_and_every_table(self):
        from slot_extractor import table_headers
        s = C.response_schema(SLOTS, table_headers)
        assert s["required"] == ["fields", "tables"]
        assert s["properties"]["fields"]["required"] == ["F1", "F2"]
        assert s["properties"]["tables"]["required"] == ["table"]
        row = s["properties"]["tables"]["properties"]["table"]["items"]
        assert row["properties"]["cells"]["required"] == ["Date", "Amount"]
        assert "status" in s["properties"]["fields"]["properties"]["F1"]["required"]

    def test_job15_shape_no_tables_key_is_missing_table_not_empty(self):
        fails = C.check_answer({"fields": {"F1": {"value": "x"}}}, SLOTS)
        kinds = {f["kind"] for f in fails}
        assert kinds == {C.MISSING_SLOT, C.MISSING_TABLE}
        assert next(f for f in fails if f["kind"] == C.MISSING_SLOT)["slots"] == ["F2"]

    def test_an_empty_table_is_a_failure_only_when_the_page_shows_rows(self):
        ans = {"fields": {"F1": {}, "F2": {}}, "tables": {"table": []}}
        assert C.check_answer(ans, SLOTS, expected_rows={"table": 0}) == []
        fails = C.check_answer(ans, SLOTS, expected_rows={"table": 12})
        assert [f["kind"] for f in fails] == [C.EMPTY_TABLE]

    @pytest.mark.parametrize("parsed,kind", [({}, C.EMPTY), (None, C.INVALID_JSON)])
    def test_empty_and_invalid_are_typed(self, parsed, kind):
        assert C.check_answer(parsed, SLOTS)[0]["kind"] == kind

    def test_merge_takes_only_what_was_asked_again_and_never_overwrites(self):
        first = {"fields": {"F1": {"value": "A"}, "F2": {"value": ""}}}
        second = {"fields": {"F1": {"value": "Z"}, "F2": {"value": "9.00"}},
                  "tables": {"table": [{"cells": {"Date": "1/1"}}]}}
        out = C.merge_answers(first, second, ["F1", "F2"], ["table"])
        assert out["fields"]["F1"]["value"] == "A"
        assert out["fields"]["F2"]["value"] == "9.00"
        assert len(out["tables"]["table"]) == 1


# ── A3: the source inventory ─────────────────────────────────────────────────

STATEMENT = ["Lakeshore Bank Statement", "Closing balance $1,234.56",
             "DATE DESCRIPTION AMOUNT BALANCE",
             "09/01/2026 BEGINNING BALANCE 1,000.00",
             "09/02/2026 ACH DEBIT 254.00 746.00",
             "09/03/2026 PAYMENT RECEIVED 488.56 1,234.56",
             "09/04/2026 CHECK #1077 85.00 1,149.56",
             "Call 555-123-4567 or visit us. Account 7301558842. Year 2026."]


class TestInventory:
    def test_amounts_rows_and_what_is_not_an_amount(self):
        inv = SI.build([_lines(1, STATEMENT)], [1])
        p = inv["pages"][1]
        assert p["dated_rows"] == 3                 # the BEGINNING BALANCE line is not one
        vals = {a["value"] for a in p["amounts"]}
        assert "$1,234.56" in vals and "254.00" in vals
        assert not any(v in vals for v in ("555-123-4567", "7301558842", "2026",
                                           "09/01/2026", "1077"))

    def test_a_page_without_the_bands_headings_has_no_matching_table(self):
        band = {"name": "t", "columns": [{"header": "Date"}, {"header": "Amount"},
                                          {"header": "Balance"}]}
        assert SI.page_has_band(_lines(1, STATEMENT), band)
        assert not SI.page_has_band(_lines(2, ["Vendor list", "ACME 12.00"]), band)

    def test_coverage_names_the_missing_rows_and_the_unplaced_amount(self):
        slots = {"fields": [{"slot_id": "F1", "ref": "B1", "row_label": "Closing Balance"}],
                 "tables": [{"name": "table", "columns": [
                     {"header": "Date"}, {"header": "Description"},
                     {"header": "Amount"}, {"header": "Balance"}]}]}
        lines = [_lines(1, STATEMENT)]
        inv = SI.build(lines, [1])
        cov = SI.coverage(inv, slots, {}, {"table": []}, {}, lines, [1])
        text = " ".join(cov["reasons"])
        assert "about 3 transaction lines but 0 were extracted" in text
        assert "$1,234.56" in text and "Closing Balance" in text
        assert cov["flag_slots"] == {"B1": cov["flag_slots"]["B1"]}

    def test_a_correct_extraction_raises_nothing(self):
        slots = {"fields": [{"slot_id": "F1", "ref": "B1", "row_label": "Closing Balance"},
                            {"slot_id": "F2", "ref": "B2", "row_label": "GL Account"}],
                 "tables": [{"name": "table", "columns": [
                     {"header": "Date"}, {"header": "Description"},
                     {"header": "Amount"}, {"header": "Balance"}]}]}
        lines = [_lines(1, STATEMENT)]
        inv = SI.build(lines, [1])
        rows = [{"Date": d, "Amount": a, "Balance": b} for d, a, b in (
            ("09/02/2026", "254.00", "746.00"), ("09/03/2026", "488.56", "1,234.56"),
            ("09/04/2026", "85.00", "1,149.56"))]
        cov = SI.coverage(inv, slots, {"B1": "$1,234.56"}, {"table": rows}, {}, lines, [1])
        assert cov["reasons"] == [] and cov["flag_slots"] == {}   # GL Account: no noise

    def test_a_label_quoted_with_no_value_is_empty_flagged(self):
        # Run Q, Q5: the quote carries a value beside the label. A quote of the
        # label ALONE is the box shown empty (tests/test_q5_blank_forms.py).
        slots = {"fields": [{"slot_id": "F1", "ref": "B1", "row_label": "Payer TIN"}],
                 "tables": []}
        lines = [_lines(1, ["PAYER'S TIN 10-0000002 RECIPIENT'S TIN"])]
        cov = SI.coverage(SI.build(lines, [1]), slots, {}, {},
                          {"F1": {"value": "", "source": "PAYER'S TIN 10-0000002"}}, lines, [1])
        assert "B1" in cov["flag_slots"]

    def test_a_label_quoted_alone_over_a_blank_box_is_not_flagged(self):
        # Run Q, Q5 changed this case's expectation (was: flagged "quoted this
        # label"). The page prints only captions; the quote is the label alone.
        slots = {"fields": [{"slot_id": "F1", "ref": "B1", "row_label": "Payer TIN"}],
                 "tables": []}
        lines = [_lines(1, ["PAYER'S TIN RECIPIENT'S TIN"])]
        cov = SI.coverage(SI.build(lines, [1]), slots, {}, {},
                          {"F1": {"value": "", "source": "PAYER'S TIN"}}, lines, [1])
        assert "B1" not in cov["flag_slots"]

    def test_unread_scan_pages_are_reasons(self):
        inv = SI.build([_lines(1, ["x 1.00"]), []], [1, 2], origins={1: "native", 2: "ocr"},
                       ocr_zero=[2])
        cov = SI.coverage(inv, {"fields": [], "tables": []}, {}, {}, {}, [[], []], [1, 2])
        assert any("Page 2 could not be read" in r for r in cov["reasons"])


# ── A4 / A7 / A8 through run_slot_extraction ────────────────────────────────

BAND_GRID = {"cells": {"0,0": {"value": "Date"}, "0,1": {"value": "Description"},
                       "0,2": {"value": "Amount"}},
             "merges": {}, "colWidths": [], "repeatRows": []}


def _run(extract, pages_text, origins=None, unreadable=None, grid=BAND_GRID):
    from slot_extractor import run_slot_extraction
    from text_layer import text_from_lines
    lines = [_lines(i + 1, t) for i, t in enumerate(pages_text)]
    texts = [text_from_lines(ln) for ln in lines]
    orch = SimpleNamespace(llm=SimpleNamespace(extract=extract))
    with C.collect_attempts(fresh=True):
        return run_slot_extraction(
            orch, "doc.pdf", {"layout": grid}, None, page_images=[],
            doc_text="\n\n".join(texts), doc_text_pages=texts,
            file_type="digital_pdf", default_doc_type="other", start=0.0,
            page_lines=lines,
            page_origins=origins or {i + 1: "native" for i in range(len(lines))},
            page_numbers=list(range(1, len(lines) + 1)), unreadable=unreadable)[0]


def _row(date, desc, amt):
    line = f"{date} {desc} {amt}"
    return {"cells": {"Date": date, "Description": desc, "Amount": amt},
            "source": line, "page": 1}


class TestStatesThroughTheEngine:
    PAGE = [("DATE", "DESCRIPTION", "AMOUNT"), ("09/02/2026", "ACH DEBIT", "254.00"),
            ("09/03/2026", "RENT PAYMENT", "488.56"), ("09/04/2026", "CHECK", "85.00")]

    def test_a_complete_answer_is_ready(self):
        ans = {"tables": {"table": [_row("09/02/2026", "ACH DEBIT", "254.00"),
                                    _row("09/03/2026", "RENT PAYMENT", "488.56"),
                                    _row("09/04/2026", "CHECK", "85.00")]}}
        r = _run(lambda **kw: _resp(ans), [self.PAGE])
        assert r.extracted_data["document_state"] == "READY"
        assert r.extracted_data["attention"] == []

    def test_an_answer_with_no_table_and_a_failed_second_request_needs_attention(self):
        calls = []

        def extract(**kw):
            calls.append(kw["prompt"])
            return _resp({"fields": {}})
        r = _run(extract, [self.PAGE])
        ed = r.extracted_data
        assert len(calls) == 2 and "SECOND REQUEST" in calls[1]
        assert ed["document_state"] == "NEEDS_ATTENTION"
        assert any("0 were extracted" in a["text"] for a in ed["attention"])
        assert ed["diagnostics"]["contract"]["retried_tables"] == ["table"]

    def test_a_zero_word_scan_page_needs_attention(self):
        ans = {"tables": {"table": [_row("09/02/2026", "ACH DEBIT", "254.00"),
                                    _row("09/03/2026", "RENT PAYMENT", "488.56"),
                                    _row("09/04/2026", "CHECK", "85.00")]}}
        r = _run(lambda **kw: _resp(ans), [self.PAGE, []],
                 origins={1: "native", 2: "ocr"}, unreadable={"ocr_zero": [2]})
        ed = r.extracted_data
        assert ed["document_state"] == "NEEDS_ATTENTION"
        assert any("Page 2 could not be read" in a["text"] for a in ed["attention"])
        assert ed["diagnostics"]["pages"] == {"1": "processed", "2": "failed"}

    def test_a_failed_call_is_failed_with_its_typed_reason(self):
        r = _run(lambda **kw: LLMResponse(raw_text="", success=False,
                                          error_kind=C.QUOTA, error="quota"),
                 [self.PAGE])
        assert r.success is False
        assert r.extracted_data["document_state"] == "FAILED"
        assert r.extracted_data["failure_kind"] == C.QUOTA


class TestPageAtATime:
    """Seven pages: a statement on 1-3, a vendor list on 4-7."""
    STMT = [["DATE DESCRIPTION AMOUNT", f"09/0{p}/2026 ITEM-{p}A 1{p}.00",
             f"09/0{p}/2026 ITEM-{p}B 2{p}.00"] for p in (1, 2, 3)]
    OTHER = [["Vendor list", "ACME SUPPLY", "BETA LLC"] for _ in range(4)]

    def _extract(self, fail_pages, calls):
        def extract(**kw):
            p = kw["prompt"]
            import re
            m = re.search(r"This is page (\d+) of", p)
            n = int(m.group(1)) if m else 0
            calls.append(n)
            if n in fail_pages and fail_pages[n] > 0:
                fail_pages[n] -= 1
                return LLMResponse(raw_text="", success=False,
                                   error_kind=C.INVALID_JSON)
            rows = [{"cells": {"Date": f"09/0{n}/2026", "Description": f"ITEM-{n}{s}",
                               "Amount": f"{a}{n}.00"},
                     "source": f"09/0{n}/2026 ITEM-{n}{s} {a}{n}.00", "page": 1}
                    for s, a in (("A", 1), ("B", 2))]
            return _resp({"tables": {"table": rows}})
        return extract

    def test_a_failed_page_is_retried_alone_and_the_others_are_kept(self, monkeypatch):
        monkeypatch.setattr(C, "setting", lambda n, d: {"PAGE_CALL_MIN_PAGES": 6,
                                                        "PAGE_CALL_CONCURRENCY": 2}.get(n, d))
        calls = []
        r = _run(self._extract({2: 2}, calls), self.STMT + self.OTHER)
        ed = r.extracted_data
        # page 2 failed (and its own retry inside _llm_json), then was retried alone
        assert sorted(set(calls)) == [1, 2, 3]
        assert calls.count(1) == 1 and calls.count(3) == 1 and calls.count(2) >= 2
        assert len(ed["table_rows"]) == 6
        assert ed["diagnostics"]["pages"]["2"] == "processed"

    def test_a_page_that_fails_twice_is_reported_and_nothing_else_is_lost(self, monkeypatch):
        monkeypatch.setattr(C, "setting", lambda n, d: {"PAGE_CALL_MIN_PAGES": 6,
                                                        "PAGE_CALL_CONCURRENCY": 2}.get(n, d))
        calls = []
        r = _run(self._extract({2: 99}, calls), self.STMT + self.OTHER)
        ed = r.extracted_data
        assert len(ed["table_rows"]) == 4                 # pages 1 and 3
        assert ed["diagnostics"]["pages"]["2"] == "failed"
        assert ed["document_state"] == "NEEDS_ATTENTION"
        assert any("Page 2 could not be extracted" in a["text"] for a in ed["attention"])

    def test_a_band_no_page_was_chosen_for_is_asked_over_the_whole_document(self, monkeypatch):
        """The inventory can be blind (an OCR misread): never skip silently."""
        monkeypatch.setattr(C, "setting", lambda n, d: {"PAGE_CALL_MIN_PAGES": 6}.get(n, d))
        prompts = []

        def extract(**kw):
            prompts.append(kw["prompt"])
            return _resp({"tables": {"table": []}})
        _run(extract, self.OTHER + self.OTHER)          # 8 pages, no headings anywhere
        assert len(prompts) >= 1
        assert 'TABLE "table"' in prompts[0] and "This is page" not in prompts[0]

    def test_ocr_misread_dates_still_count_as_rows(self):
        lines = _lines(1, ["O7/09/2019 Deposit $130.26 $1,764.35",
                           "o7/12/2019 DEPOSIT CREDIT $1.00 $2,396.78"])
        assert [SI.row_kind(ln) for ln in lines] == ["dated", "dated"]

    def test_pages_without_the_table_are_never_asked_and_give_no_rows(self, monkeypatch):
        monkeypatch.setattr(C, "setting", lambda n, d: {"PAGE_CALL_MIN_PAGES": 6}.get(n, d))
        calls = []
        r = _run(self._extract({}, calls), self.STMT + self.OTHER)
        assert not set(calls) & {4, 5, 6, 7}
        notes = " ".join(r.extracted_data["validation_notes"])
        assert "no matching table on page 4" in notes
        assert {row["_page"] for row in r.extracted_data["table_rows"]} == {1, 2, 3}
