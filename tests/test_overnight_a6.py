"""A6 — consistency.

(a) per-document independence: the same model answer gives the identical
    record and the identical exported block whether pitt_sample_w2 is
    extracted alone or after another W-2 in the same job (job 48 vs job 51);
(b) job 48 split pitt's one state/local entity over three rows (PA, state ID,
    wages / state tax, local wages / local tax, locality): keyless fragment
    rows with disjoint columns merge into the one keyed row;
(c) every extraction call runs at temperature 0 (EXTRACTION_TEMPERATURE),
    and each attempt records the temperature it was sent with.
"""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import openpyxl

from tests import overnight_helpers as H
from tests.local_corpus import local_file
from tests.test_overnight_a1_a2 import PITT, STATE_LINE, pitt_answer, pitt_grid

MOD11 = "w2/irs_w2_mod11.pdf"


def _orchestrator(answers_by_marker, seen):
    from connectors.base import LLMResponse

    def extract(**kw):
        seen.append(kw)
        prompt = str(kw.get("prompt") or "")
        for marker, answer in answers_by_marker.items():
            if marker in prompt:
                a = copy.deepcopy(answer)
                return LLMResponse(raw_text=json.dumps(a), parsed_json=a, success=True,
                                   model_used="offline-overnight-a6")
        a = {"fields": {}, "tables": {}}
        return LLMResponse(raw_text=json.dumps(a), parsed_json=a, success=True,
                           model_used="offline-overnight-a6")
    return SimpleNamespace(llm=SimpleNamespace(extract=extract))


_VOLATILE = {"latency_ms", "processing_time_ms", "diagnostics", "attempts",
             "usage", "elapsed_ms", "started_at", "finished_at"}


def _stable(obj):
    if isinstance(obj, dict):
        return {k: _stable(v) for k, v in obj.items() if k not in _VOLATILE}
    if isinstance(obj, list):
        return [_stable(v) for v in obj]
    return obj


def _block(ws, title):
    """The rows of one document's block, as (values, comments), header strip
    first, located by its file name in the strip."""
    start = next(r for r in range(1, ws.max_row + 1)
                 if any(title in str(ws.cell(r, c).value or "")
                        for c in range(1, ws.max_column + 1)))
    out = []
    for r in range(start, ws.max_row + 1):
        row = [ws.cell(r, c).value for c in range(1, ws.max_column + 1)]
        if r > start and any("mod11" in str(v or "") for v in row):
            break
        out.append((row, [str(ws.cell(r, c).comment.text if ws.cell(r, c).comment else "")
                          for c in range(1, ws.max_column + 1)]))
    while out and not any(v not in (None, "") for v in out[-1][0]):
        out.pop()
    return out


def test_a6a_same_answer_same_record_alone_and_in_a_combined_job():
    from extractor import run_extraction

    g = pitt_grid()
    answers = {"PITTSBURGH": pitt_answer(g)}
    tpl = {"layout": g, "doc_type": "w2"}
    seen = []
    orch = _orchestrator(answers, seen)
    alone = run_extraction(orch, local_file(PITT), tpl)[0].extracted_data
    batch = {}
    run_extraction(orch, local_file(MOD11), tpl, batch_schemas=batch)
    combined = run_extraction(orch, local_file(PITT), tpl, batch_schemas=batch)[0].extracted_data
    assert _stable(alone) == _stable(combined)

    from app.services.excel_slot import _write_slot_excel

    def sheet(records):
        wb = openpyxl.Workbook()
        ws = wb.active
        docs = [SimpleNamespace(filename=name, get_extracted_data=lambda d=d: d)
                for name, d in records]
        _write_slot_excel(ws, docs, g, g["cells"], openpyxl)
        return ws

    mod11 = run_extraction(orch, local_file(MOD11), tpl)[0].extracted_data
    one = _block(sheet([("pitt_sample_w2.pdf", alone)]), "pitt_sample_w2.pdf")
    two = _block(sheet([("irs_w2_mod11.pdf", mod11), ("pitt_sample_w2.pdf", combined)]),
                 "pitt_sample_w2.pdf")
    assert one == two


def test_a6b_state_band_fragments_merge_into_the_one_entity_row():
    g = pitt_grid()
    rows = [
        {"cells": {"State": "PA", "Employer State ID": "XXXX5369",
                   "State Wages": "47808.35"}, "source": STATE_LINE, "page": 1},
        {"cells": {"State Income Tax": "1467.72", "Local Wages": "47808.35"},
         "source": STATE_LINE, "page": 1},
        {"cells": {"Local Income Tax": "478.08", "Locality Name": "700102"},
         "source": STATE_LINE, "page": 1},
    ]
    data, _ = H.run(PITT, g, pitt_answer(g, state_rows=rows), doc_type="w2")
    got = data.get(f"{H.table_name(g, 'State and Local')}_rows") or []
    assert len(got) == 1, got
    row = got[0]
    assert (row["State"], row["Employer State ID"], row["State Wages"],
            row["State Income Tax"], row["Local Wages"], row["Local Income Tax"],
            row["Locality Name"]) == ("PA", "XXXX5369", "47808.35", "1467.72",
                                      "47808.35", "478.08", "700102")


def test_a6b_two_real_entities_are_not_merged():
    g = pitt_grid()
    rows = [
        {"cells": {"State": "PA", "Employer State ID": "XXXX5369",
                   "State Wages": "47808.35"}, "source": STATE_LINE, "page": 1},
        {"cells": {"State": "PA", "State Income Tax": "1467.72"},
         "source": STATE_LINE, "page": 1},
    ]
    data, _ = H.run(PITT, g, pitt_answer(g, state_rows=rows), doc_type="w2")
    got = data.get(f"{H.table_name(g, 'State and Local')}_rows") or []
    assert len(got) == 2


def test_a6c_extraction_runs_at_temperature_zero_and_records_it(monkeypatch):
    import extractor

    monkeypatch.setenv("EXTRACTION_TEMPERATURE", "0")
    seen = []
    from connectors.base import LLMResponse

    def extract(**kw):
        seen.append(kw.get("temperature"))
        a = {"fields": {}, "tables": {}}
        return LLMResponse(raw_text="{}", parsed_json=a, success=True,
                           model_used="offline", attempts=[{"section": "x"}])
    orch = SimpleNamespace(llm=SimpleNamespace(extract=extract))
    _parsed, resp = extractor._llm_json(orch, "p", "s", text="t")
    assert seen == [0.0]
    assert all(a.get("temperature") == 0.0 for a in resp.attempts)
