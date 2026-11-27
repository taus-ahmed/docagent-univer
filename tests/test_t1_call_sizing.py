"""Run T1, 1a: a call is sized before it is made, and a piece whose answer
does not fit is halved - never asked again unchanged.

No model: every answer is scripted. The scripted model refuses (MAX_TOKENS,
a timeout, an unparseable answer, a 400 "too long") any request carrying
more rows than a threshold, the way a real output limit does.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.run_q_support import make_pdf, template  # noqa: E402

import call_sizing as CS  # noqa: E402

ROW = re.compile(r"^(N\d{4}) (\d{2}/\d{2}/2026) (\d+\.\d{2})$")


class _Resp:
    def __init__(self, parsed, kind=None, cause=None):
        self.success = parsed is not None
        self.parsed_json = parsed
        self.raw_text = json.dumps(parsed) if parsed is not None else ""
        self.tokens_used, self.model_used = 0, "scripted"
        self.error = "" if parsed is not None else str(kind)
        self.error_kind, self.finish_reason = kind, None
        self.attempts = [{"cause": cause}] if cause else []


def _doc_lines(prompt):
    """(page in prompt, line) for every line of the prompt's document text."""
    body = prompt.split("=== DOCUMENT TEXT ===", 1)[1].split("=== END DOCUMENT ===", 1)[0]
    page, out = 1, []
    for ln in body.splitlines():
        m = re.match(r"--- page (\d+) ---", ln)
        if m:
            page = int(m.group(1))
            continue
        out.append((page, ln.strip()))
    return out


def _scripted(limit, fail_kind="max_tokens", cause=None, calls=None):
    def extract(prompt="", system_instruction="", **kw):
        if calls is not None:
            calls.append(prompt)
        rows = [(p, ln) for p, ln in _doc_lines(prompt) if ROW.match(ln)]
        if len(rows) > limit:
            return _Resp(None, fail_kind, cause)
        out = []
        for p, ln in rows:
            n, d, a = ROW.match(ln).groups()
            out.append({"cells": {"Number": n, "Date": d, "Amount": a},
                        "source": ln, "page": p})
        return _Resp({"fields": {}, "tables": {"Items": out}})
    return SimpleNamespace(llm=SimpleNamespace(extract=extract))


def _pages(n_pages, per_page, heading_on_first=True, heading="No. Posted Value"):
    pages, i = [], 0
    for p in range(n_pages):
        items, y = [], 750
        if p == 0 and heading_on_first:
            items.append((40, y, heading))
            y -= 12
        for _ in range(per_page):
            i += 1
            items.append((40, y, f"N{i:04d} 07/{(i % 28) + 1:02d}/2026 {i}.00"))
            y -= 12
        pages.append(items)
    return pages


def _tpl():
    return template(tables=[("Items", ["Number", "Date", "Amount"])],
                    doc_type="other")


# ── pure functions ───────────────────────────────────────────────────────────

class TestEstimate:
    def test_small_document_fits_one_call(self):
        est = CS.estimate_tokens(5, [6], [20, 15])
        assert CS.fits_whole(est, 65536)

    def test_eight_page_270_row_list_does_not(self):
        # the failing vendor list: 8 pages, 270 rows, 11 columns
        est = CS.estimate_tokens(4, [11], [34] * 7 + [32])
        assert sum([34] * 7 + [32]) == 270
        assert not CS.fits_whole(est, 65536)

    def test_groups_fit_the_budget(self):
        per = [10000] * 8
        groups = CS.pack_groups(list(range(8)), per, 0.6 * 65536)
        assert groups == [[0, 1, 2], [3, 4, 5], [6, 7]]

    def test_row_cut_never_strands_a_wrapped_line(self):
        lines = ["01/01 Sale 1.00", "  wrapped description", "01/02 Sale 2.00",
                 "  more words", "01/03 Sale 3.00", "  tail", "01/04 Sale 4.00",
                 "  tail", "01/05 Sale 5.00", "  tail"]
        cut = CS.row_cut(lines)
        assert cut is not None and CS.line_has_row_value(lines[cut])

    def test_carry_takes_heading_and_group(self):
        lines = ["Number Date Amount", "300055 ANDERSON SUPPLY", "N1 01/01/2026 1.00"]
        c = CS.carried_context(lines, lambda s: s.startswith("Number Date"))
        assert c == {"heading": "Number Date Amount", "group": "300055 ANDERSON SUPPLY"}
        assert "never return" in CS.context_block(c)
        assert CS.context_block(None) == "" and CS.context_block({}) == ""


class TestSplittable:
    def test_kinds(self):
        for k in ("max_tokens", "transient", "invalid_json", "empty", "no_candidate"):
            assert CS.splittable_kind(_Resp(None, k))
        for k in ("quota_exhausted", "auth", "blocked"):
            assert not CS.splittable_kind(_Resp(None, k))

    def test_a_400_splits_only_when_the_request_was_too_long(self):
        assert CS.splittable_kind(_Resp(None, "invalid_request", "input_too_long"))
        assert not CS.splittable_kind(_Resp(None, "invalid_request", "schema"))
        assert not CS.splittable_kind(_Resp(None, "invalid_request"))


class TestAskAdaptive:
    def _run(self, limit_rows, kind="max_tokens", cause=None, pages=4, per=10):
        texts = ["\n".join(f"N{p}{i:03d} 01/01/2026 {i}.00" for i in range(per))
                 for p in range(pages)]
        calls = []

        def ask(pg, text=None, carry=None, part=None):
            calls.append((tuple(pg), part, carry))
            body = text if text is not None else "\n".join(texts[k] for k in pg)
            n = len(body.splitlines())
            if n > limit_rows:
                return None, _Resp(None, kind, cause)
            return {"rows": body.splitlines()}, _Resp({})
        res = CS.ask_adaptive(ask, list(range(pages)), page_text=lambda k: texts[k])
        return res, calls

    def test_max_tokens_halves_down_to_what_fits(self):
        res, calls = self._run(limit_rows=10)
        assert not res["failed"]
        got = [r for _pg, _part, parsed in res["pieces"] for r in parsed["rows"]]
        assert len(got) == 40 and len(set(got)) == 40
        assert [p[0] for p in res["pieces"]] == [[0], [1], [2], [3]]
        assert any("halved" in s for s in res["strategy"])
        # never the same request twice
        assert len(calls) == len(set((c[0], c[1]) for c in calls))

    def test_timeout_halves_too(self):
        res, _ = self._run(limit_rows=20, kind="transient")
        assert not res["failed"] and len(res["pieces"]) == 2

    def test_one_page_too_big_is_split_by_rows(self):
        res, calls = self._run(limit_rows=6, pages=1, per=10)
        assert not res["failed"]
        got = [r for _pg, _part, parsed in res["pieces"] for r in parsed["rows"]]
        assert len(got) == 10 and len(set(got)) == 10
        assert any(c[1] for c in calls)                 # a row-range part
        assert any("split by rows" in s for s in res["strategy"])

    def test_a_piece_that_never_fits_is_named_and_the_rest_kept(self):
        texts = ["\n".join(f"N0{i:03d} 01/01/2026 {i}.00" for i in range(10)),
                 "\n".join(f"N1{i:03d} 01/01/2026 {i}.00" for i in range(10))]

        def ask(pg, text=None, carry=None, part=None):
            if 1 in pg:
                return None, _Resp(None, "max_tokens")   # page 2 never fits
            return {"rows": texts[0].splitlines()}, _Resp({})
        res = CS.ask_adaptive(ask, [0, 1], page_text=lambda k: texts[k])
        assert list(res["failed"]) == [1]
        assert res["pieces"] and res["pieces"][0][0] == [0]

    def test_a_refusal_is_not_split(self):
        res, calls = self._run(limit_rows=0, kind="quota_exhausted")
        assert len(calls) == 1 and set(res["failed"]) == {0, 1, 2, 3}

    def test_carry_reaches_the_second_half(self):
        texts = ["Number Date Amount\nGRP 7 NORTH\n" +
                 "\n".join(f"N0{i:03d} 01/01/2026 {i}.00" for i in range(6)),
                 "\n".join(f"N1{i:03d} 01/01/2026 {i}.00" for i in range(6))]
        seen = []

        def ask(pg, text=None, carry=None, part=None):
            seen.append((tuple(pg), carry))
            if len(pg) > 1:
                return None, _Resp(None, "max_tokens")
            return {"rows": []}, _Resp({})
        CS.ask_adaptive(ask, [0, 1], page_text=lambda k: texts[k],
                        heading_test=lambda s: s.startswith("Number Date"))
        second = [c for pg, c in seen if pg == (1,)][0]
        assert second["heading"] == "Number Date Amount"
        assert second["group"] == "GRP 7 NORTH"


class TestDedupe:
    def test_a_seam_repeat_is_kept_once_and_same_piece_twins_stay(self):
        a = {"cells": {"A": "1"}, "source": "x 1", "_piece": 1}
        b = {"cells": {"A": "1"}, "source": "x 1", "_piece": 2}
        c = {"cells": {"A": "1"}, "source": "x 1", "_piece": 1}
        assert len(CS.dedupe_rows([a, b])) == 1
        assert len(CS.dedupe_rows([a, c])) == 2


# ── end to end, through run_extraction ──────────────────────────────────────

class TestEndToEnd:
    def test_eight_pages_400_rows_split_and_nothing_lost(self, tmp_path):
        from extractor import run_extraction
        pdf = make_pdf(tmp_path / "list.pdf", _pages(8, 50), size=9)
        calls = []
        res = run_extraction(_scripted(150, calls=calls), pdf, _tpl())
        ed = res[0].extracted_data
        assert ed.get("document_state") != "FAILED", ed.get("failure_reason")
        nums = [r["Number"] for r in ed["Items_rows"]]
        assert len(nums) == 400 and len(set(nums)) == 400
        assert nums == sorted(nums)                         # page order
        strat = " | ".join(ed["diagnostics"]["call_strategy"])
        assert "sized" in strat

    def test_a_short_document_too_big_for_one_call_is_sized(self, tmp_path, monkeypatch):
        # 4 pages (under page-at-a-time's 6) x 55 rows against a model whose
        # output limit is 30k: the estimate (26.7k) is over 60% of it before
        # any call is made
        monkeypatch.setattr(CS, "output_limit", lambda model=None: 30000)
        from extractor import run_extraction
        pdf = make_pdf(tmp_path / "short.pdf", _pages(4, 55), size=8)
        calls = []
        res = run_extraction(_scripted(1000, calls=calls), pdf, _tpl())
        ed = res[0].extracted_data
        assert ed.get("document_state") != "FAILED", ed.get("failure_reason")
        assert len(ed["Items_rows"]) == 220
        assert "sized" in " | ".join(ed["diagnostics"]["call_strategy"])

    def test_max_tokens_on_a_small_document_recovers_by_halving(self, tmp_path):
        from extractor import run_extraction
        pdf = make_pdf(tmp_path / "two.pdf", _pages(2, 20))
        res = run_extraction(_scripted(25), pdf, _tpl())
        ed = res[0].extracted_data
        assert ed.get("document_state") != "FAILED", ed.get("failure_reason")
        assert len(ed["Items_rows"]) == 40
        assert any("smaller pieces" in n for n in ed["validation_notes"])

    def test_unparseable_answer_recovers_by_halving(self, tmp_path):
        from extractor import run_extraction
        pdf = make_pdf(tmp_path / "two.pdf", _pages(2, 20))
        res = run_extraction(_scripted(25, fail_kind="invalid_json"), pdf, _tpl())
        assert len(res[0].extracted_data["Items_rows"]) == 40

    def test_a_400_too_long_recovers_by_halving(self, tmp_path):
        from extractor import run_extraction
        pdf = make_pdf(tmp_path / "two.pdf", _pages(2, 20))
        res = run_extraction(_scripted(25, fail_kind="invalid_request",
                                       cause="input_too_long"), pdf, _tpl())
        assert len(res[0].extracted_data["Items_rows"]) == 40

    def test_a_table_crossing_a_page_break_is_one_table(self, tmp_path):
        from extractor import run_extraction
        pdf = make_pdf(tmp_path / "cross.pdf", _pages(2, 20))
        res = run_extraction(_scripted(25), pdf, _tpl())
        rows = res[0].extracted_data["Items_rows"]
        assert [r["Number"] for r in rows] == [f"N{i:04d}" for i in range(1, 41)]
        assert {r["_page"] for r in rows} == {1, 2}

    def test_a_page_that_never_fits_is_named_not_the_document_failed(self, tmp_path):
        from extractor import run_extraction
        pdf = make_pdf(tmp_path / "two.pdf", _pages(2, 20))

        orch = _scripted(25)
        inner = orch.llm.extract

        def extract(prompt="", **kw):
            if "N0035 " in prompt:                  # page 2's rows, any size
                return _Resp(None, "max_tokens")
            return inner(prompt=prompt, **kw)
        orch.llm.extract = extract
        res = run_extraction(orch, pdf, _tpl())
        ed = res[0].extracted_data
        assert ed.get("document_state") != "FAILED"
        assert len(ed["Items_rows"]) >= 20
        assert any("Page 2" in a for a in ed.get("attention") or []
                   if isinstance(a, str)) or any(
            "Page 2" in str(a.get("text", "")) for a in ed.get("attention") or []
            if isinstance(a, dict))


class TestRecordedPlan:
    def test_replay_of_stored_answers_skips_presizing_but_still_halves(self, tmp_path,
                                                                        monkeypatch):
        from extractor import run_extraction
        monkeypatch.setattr(CS, "output_limit", lambda model=None: 30000)
        pdf = make_pdf(tmp_path / "short.pdf", _pages(4, 55), size=8)
        tok = CS.RECORDED_PLAN.set(True)
        try:
            ed = run_extraction(_scripted(1000), pdf, _tpl())[0].extracted_data
            assert "whole document in one call" in ed["diagnostics"]["call_strategy"][0]
            ed2 = run_extraction(_scripted(120), pdf, _tpl())[0].extracted_data
            assert len(ed2["Items_rows"]) == 220       # halved after the failure
        finally:
            CS.RECORDED_PLAN.reset(tok)
        assert CS.presize()
