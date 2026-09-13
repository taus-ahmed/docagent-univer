"""
Round-2 evidence runs — a real round-2 PDF, a reconstructed template, the real
pipeline.

    python -m tests.harness.round2 --run run1_berkshire_B1 --mode record   # live, costs money
    python -m tests.harness.round2 --run run1_berkshire_B1 --mode replay

The suite could not see I1 (docs/DocAgent_round2_report.md): 781 tests passed
while eight of twelve manual runs merged regions. So the evidence for I1 runs
the documents the defect was found on, not fixtures written to resemble them.

EVERY LIVE RUN STORES ITS RAW RESPONSE, twice:

  tests/llm_cache/<key>.json         what replay serves, keyed by the full
                                     request — so a replayed test is asking the
                                     exact question the live run asked
  tests/fixtures/round2_raw/<run>.json   the same response, readable, with the
                                     commit, model and time it was captured —
                                     so the model's actual answer can be read
                                     and argued with, not just replayed

An answer written by hand to look like the defect proves nothing about the
defect. A recorded one does.

The templates are RECONSTRUCTIONS (tests/fixtures/round2_templates/): the
originals were never saved. Each carries a `_reconstruction` note saying what
was known and what was guessed.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import time
from pathlib import Path

from tests.harness import bootstrap as bs

ROUND2_PDFS = bs.PDF_DIR / "round2"
TEMPLATES = bs.TESTS_DIR / "fixtures" / "round2_templates"
RAW_DIR = bs.TESTS_DIR / "fixtures" / "round2_raw"

#: run id -> (pdf, reconstructed template, round-2 run it stands for)
RUNS = {
    "run1_berkshire_B1": ("feb2225.pdf", "B1_earnings_table.json", 1),
    "run2_berkshire_B2": ("feb2225.pdf", "B2_operating_earnings.json", 2),
    "run4_engie_E1": ("SampleBill.pdf", "E1_bill_header.json", 4),
    "run6_engie_E3": ("SampleBill.pdf", "E3_itemised_charges.json", 6),
    "run9_engie_BR4": ("SampleBill.pdf", "BR4_absent_field_probe.json", 9),
    # Recorded at fe3385d (pre-I1) from a worktree; replays only on that code.
    "run9_engie_BR4_prefix_fe3385d": ("SampleBill.pdf",
                                      "BR4_absent_field_probe.json", 9),
}


def load_template(name):
    """(template_data, grid) exactly as a saved template loads in production."""
    bs.bootstrap()
    from app.api.routes.extract import _parse_template
    from app.models.models import ColumnTemplate

    grid = json.loads((TEMPLATES / name).read_text(encoding="utf-8"))
    tpl = ColumnTemplate(name=Path(name).stem, document_type="other",
                         description=json.dumps(grid), columns_json="[]")
    return _parse_template(tpl), grid


def _commit():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=bs.REPO_DIR,
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def run(run_id, mode="replay", orchestrator_llm=None):
    """(results, grid, log). `mode` is the LLMCache mode.

    `orchestrator_llm` replaces the model outright — for the ENGIE tests,
    whose evidence is the split and the writer, not the model's answer.
    """
    bs.bootstrap()
    bs.chdir_backend()
    from app.api.routes.extract import _extract_with_template
    from orchestrator import Orchestrator
    from tests.harness.llm_cache import LLMCache

    pdf, template, _n = RUNS[run_id]
    template_data, grid = load_template(template)
    buf = io.StringIO()
    cache = None
    if orchestrator_llm is None:
        cache = LLMCache(mode=mode)
        cache.context = f"round2:{run_id}"
        cache.install()
    try:
        with contextlib.redirect_stdout(buf):
            orch = Orchestrator(client_schema_path=_schema_path())
            if orchestrator_llm is not None:
                orch.llm = orchestrator_llm
            results = _extract_with_template(orch, ROUND2_PDFS / pdf,
                                             template_data)
    finally:
        if cache is not None:
            cache.uninstall()

    if cache is not None and mode in ("record", "live"):
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        record = {
            "run": run_id, "pdf": pdf, "template": template,
            "round2_run": RUNS[run_id][2],
            "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "commit": _commit(), "mode": mode,
            "calls": [{"method": m, "key": k, "source": s}
                      for m, k, s in cache.calls],
            "responses": [
                {"filename": getattr(r, "filename", ""),
                 "raw_llm_responses": (getattr(r, "extracted_data", None)
                                       or {}).get("raw_llm_responses", []),
                 "model_used": getattr(getattr(r, "extraction_response", None),
                                       "model_used", "")}
                for r in results],
        }
        (RAW_DIR / f"{run_id}.json").write_text(
            json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
    return results, grid, buf.getvalue()


def _schema_path():
    from tests.harness.runner import _schema_path as sp
    return sp()


def export(results, grid):
    """The worksheet the download endpoint would build, read back."""
    from tests.harness.runner import build_export
    ws, _shape = build_export(results, grid, no_template=False)
    return ws


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", choices=list(RUNS), required=True)
    ap.add_argument("--mode", choices=["replay", "record"], default="replay")
    a = ap.parse_args()
    results, grid, log = run(a.run, a.mode)
    for r in results:
        ed = getattr(r, "extracted_data", None) or {}
        print(r.filename, {k: len(v) for k, v in ed.items()
                           if k.endswith("_rows")})
        for n in ed.get("validation_notes") or []:
            print("  note:", n)
    ws = export(results, grid)
    if ws is not None:
        for row in ws.iter_rows(values_only=True):
            if any(v not in (None, "") for v in row):
                print("  |", " | ".join("" if v is None else str(v) for v in row))


if __name__ == "__main__":
    main()
