"""Run Q test support: real stored answers when present, reconstructions otherwise.

Every Run Q reproduction comes in two forms:

  test_<thing>_reconstructed   a mock model answer rebuilt from the staging
                               export (cells + their quoted sources). Always runs.
  test_<thing>_real            the SAME assertion fed the job's REAL raw model
                               answer from local_docs/raw/<job_id>/ (written by
                               tools/export_raw_responses.py). Skips with a
                               reason when that folder or the source PDF is absent.

`answer(job, filename)` -> the stored raw answer text, or None.
`source(filename)`      -> the original file under local_docs/DocAgent_testdocs, or None.
`scripted(answer)`      -> an orchestrator whose model returns `answer` (a dict or
                           JSON text) for the slot call and fails every other call.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "local_docs" / "raw"
SOURCES = ROOT / "local_docs" / "DocAgent_testdocs"
EXPORTS = ROOT / "local_docs"


def source(filename: str):
    if not SOURCES.is_dir():
        return None
    hits = [p for p in SOURCES.rglob(filename) if p.is_file()]
    return hits[0] if hits else None


def need_source(filename: str) -> Path:
    p = source(filename)
    if p is None:
        pytest.skip(f"{filename} not in local_docs/DocAgent_testdocs (git-ignored real data)")
    return p


def answer(job_id, filename: str):
    d = RAW / str(job_id) / "docs"
    if not d.is_dir():
        return None
    for p in sorted(d.glob("*.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        if filename in (doc.get("original_filename"), doc.get("filename")):
            return doc.get("raw_llm_response")
    return None


def need_answer(job_id, filename: str) -> str:
    a = answer(job_id, filename)
    if not a:
        pytest.skip(f"no real raw answer for job {job_id} / {filename}: run "
                    f"tools/export_raw_responses.py {job_id} first")
    return a


class _Resp:
    def __init__(self, parsed, raw=None):
        self.success = parsed is not None
        self.parsed_json = parsed
        self.raw_text = raw if raw is not None else json.dumps(parsed)
        self.tokens_used, self.model_used, self.error = 0, "scripted", ""
        self.error_kind, self.finish_reason, self.attempts = None, None, []


def scripted(ans, later=None):
    """An orchestrator: first slot call -> `ans`; later calls -> `later(prompt)`
    (a dict) or a failed call."""
    parsed = json.loads(ans) if isinstance(ans, str) else ans
    calls = []

    def extract(prompt="", system_instruction="", **kw):
        calls.append(prompt)
        if len(calls) == 1:
            return _Resp(parsed)
        nxt = later(prompt) if later else None
        if nxt is None:
            r = _Resp(None, "")
            r.error = "scripted: no further answer"
            return r
        return _Resp(nxt)

    return SimpleNamespace(llm=SimpleNamespace(extract=extract, calls=calls))


# ── synthetic native PDFs and templates ─────────────────────────────────────

def make_pdf(path, pages, size=10, w=612.0, h=792.0):
    """pages: [[(x, y, text), ...], ...] in PDF points (y up). A native text
    layer, through the project's own generator."""
    import importlib.util
    gen_path = ROOT / "tests" / "fixtures" / "make_scan_variants.py"
    spec = importlib.util.spec_from_file_location("make_scan_variants", gen_path)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    out = []
    for items in pages:
        ops = gen._text_ops([(x, y, size, t) for x, y, t in items], 0)
        out.append({"w_pt": w, "h_pt": h, "ops": ops})
    Path(path).write_bytes(gen.build_pdf(out))
    return Path(path)


def template(fields=(), tables=(), doc_type="other", start_row=0):
    """A grid: field labels down column A (value in B), then each table as a
    heading row with empty rows beneath. tables: [(name_or_None, [headers])]."""
    cells, r = {}, start_row
    for lab in fields:
        cells[f"{r},0"] = {"value": lab}
        r += 1
    for name, heads in tables:
        r += 1
        if name:
            cells[f"{r},0"] = {"value": name}
            r += 1
        for c, hd in enumerate(heads):
            cells[f"{r},{c}"] = {"value": hd}
        r += 6
    return {"layout": {"cells": cells, "colWidths": [120] * 26, "merges": {},
                       "repeatRows": [], "regions": []},
            "doc_type": doc_type, "mode": "layout"}


def slot_ids(prompt):
    """{label: slot id} from a slot prompt."""
    import re
    return {lab: sid for sid, lab in
            re.findall(r'^\s+(F\d+): .*labelled "(.+)"\s*$', prompt, re.M)}


def table_names(prompt):
    import re
    return re.findall(r'TABLE "([^"]+)"', prompt)


def run(path, tpl, answer_fn, later=None):
    """run_extraction with a model whose first answer is answer_fn(prompt)."""
    import copy
    from tests.harness import bootstrap as bs
    bs.bootstrap()
    import extractor
    first = {}

    def extract(prompt="", system_instruction="", **kw):
        if not first:
            first["p"] = prompt
            return _Resp(answer_fn(prompt))
        nxt = later(prompt) if later else None
        if nxt is None:
            r = _Resp(None, "")
            r.error = "scripted: no further answer"
            return r
        return _Resp(nxt)

    return extractor.run_extraction(SimpleNamespace(llm=SimpleNamespace(extract=extract)),
                                    Path(path), copy.deepcopy(tpl) if tpl else None)
