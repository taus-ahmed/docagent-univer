"""Run T1, Stage 4: every synthetic failure class, scored against its
ground truth (tools/make_synthetic_layouts.py, tools/structure_metrics.py).
The structure engine runs with no model - the geometry plan - which is what
the export produces when no plan was stored."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from tests.harness import bootstrap as bs  # noqa: E402

bs.bootstrap()

import make_synthetic_layouts as MS  # noqa: E402
import structure_metrics as SM  # noqa: E402


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("syn")
    MS.build(out)
    return out


@pytest.mark.parametrize("case", sorted(MS.CASES))
def test_case_matches_its_truth(built, case):
    truth = json.loads((built / f"{case}.truth.json").read_text(encoding="utf-8"))
    lay = SM.new_layout(built / f"{case}.pdf")
    m = SM.rates(SM.score(lay, truth))
    assert m["coverage"] == 1.0, m
    assert m["right_column_rate"] == 1.0, m
    assert m["row_order"] in (None, 1.0), m
    for k in ("glued", "empty_columns", "lost_zeros", "absent_hits", "header_repeats",
              "wrong_dates"):
        assert m[k] == 0, (k, m)


def test_formula_like_text_is_text(built):
    lay = SM.new_layout(built / "formula_text.pdf")
    by = {c["value"]: c for p in lay["pages"] for c in p}
    for t in ("=A1+1", "+44 20 7946", "@team", "-ref"):
        assert by[t].get("as_text"), t


def test_day_month_and_month_day_dates(built):
    from datetime import datetime
    for case in ("day_month", "month_day"):
        truth = json.loads((built / f"{case}.truth.json").read_text(encoding="utf-8"))
        lay = SM.new_layout(built / f"{case}.pdf")
        vals = [c["value"] for p in lay["pages"] for c in p if isinstance(c["value"], datetime)]
        want = sorted(tuple(v) for v in truth["dates"].values())
        assert sorted((v.year, v.month, v.day) for v in vals) == want, case


def test_trailing_minus_shown_trailing(built):
    lay = SM.new_layout(built / "trailing_minus.pdf")
    neg = [c for p in lay["pages"] for c in p if isinstance(c["value"], float) and c["value"] < 0]
    assert sorted(c["value"] for c in neg) == [-26.08, -3.5]
    assert all(c["number_format"].endswith("-") for c in neg)


def test_generator_is_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    MS.build(a)
    MS.build(b)
    for f in sorted(a.iterdir()):
        assert f.read_bytes() == (b / f.name).read_bytes(), f.name
