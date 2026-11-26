"""Run S, Stage 1a on the real stored answers: every case the prompt names is
caught. Each test replays a job's stored model answer through the code on
disk (tools/replay_raw.py: no network, no key) and skips with a reason when
local_docs is absent (it is git-ignored real data).

"Caught" means the figure is held by a value, or named by a sentence the
document carries (an attention reason or a `not_captured` note), so it is
never silently absent.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


def _replay(job_id):
    import replay_raw
    if not replay_raw.has_raw(job_id):
        pytest.skip(f"local_docs/raw/{job_id} not present (git-ignored real data)")
    rep = replay_raw.replay_job(job_id)
    if not rep["docs"]:
        pytest.skip(f"job {job_id}: {rep['skipped']}")
    return rep["docs"][0][1]


def _said(ed):
    return " ".join([a.get("text", "") for a in ed.get("attention") or []]
                    + [str(x) for x in ed.get("not_captured") or []])


def _held_or_said(ed, figure):
    import conservation as CV
    tok = CV.Token(0, figure, CV.kind_of(figure) or "id", "row", "")
    vals = CV.output_values(ed.get("extracted_fields"),
                            {k[:-5]: v for k, v in ed.items()
                             if k.endswith("_rows") and isinstance(v, list)},
                            {k: v for k, v in ed.items()
                             if k.endswith("_subtotals") and isinstance(v, list)})
    return CV.Holder(vals).holds(tok) or figure in _said(ed)


def test_utah_paystub_2_total_deduction_is_named_job_127():
    ed = _replay(127)
    said = _said(ed)
    assert "�12" in said and "total" in said, said


def test_carson_page_1_checks_withdrawals_total_job_95():
    ed = _replay(95)
    assert _held_or_said(ed, "$14,365.21"), _said(ed)


def test_the_1099k_amounts_job_115():
    ed = _replay(115)
    for fig in ("8,525.00",):
        assert _held_or_said(ed, fig), _said(ed)


def test_fidelity_no_missing_amount_is_silent_job_129():
    import conservation as CV
    import replay_raw
    ed = _replay(129)
    rep = replay_raw.load_job(129)
    src = replay_raw.find_source(rep["docs"][0]["original_filename"])
    from text_layer import read_page
    import pdfplumber
    with pdfplumber.open(str(src)) as pdf:
        lines = [read_page(p)[1] for p in pdf.pages]
    toks = [t for t in CV.structural_tokens(lines) if t.kind == "amount"]
    assert len(toks) >= 50
    silent = [t.text for t in toks if not _held_or_said(ed, t.text)]
    assert silent == [], silent[:20]


def test_vendor_numbers_are_kept_job_131_for_138():
    ed = _replay(131)
    name = next(k[:-5] for k in ed if k.endswith("_rows") and ed[k])
    ids = {r.get("Vendor ID") for r in ed[f"{name}_rows"]}
    assert "300055" in ids and len(ids) == 31
