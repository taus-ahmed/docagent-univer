"""Run R, R4 (job 129, fidelity_brokerage): 102 of 110 printed amounts were not
in the export. Cause: Run Q's open cause 6. Each page draws its statement
pictures as a BLACK rectangle with a slightly smaller WHITE one painted over
it (a drop shadow), and the text on top. `marks.native_bars` read each black
rectangle as a redaction bar and blanked every value printed on it.

A dark rectangle that a LATER light rectangle covers is a shadow or a frame,
not a bar: nothing it hides is hidden. A bar with nothing painted over it
still blanks what lies beneath (test below).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import marks  # noqa: E402


def _pdf(path, ops):
    import importlib.util
    gen_path = ROOT / "tests" / "fixtures" / "make_scan_variants.py"
    spec = importlib.util.spec_from_file_location("make_scan_variants", gen_path)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    text = gen._text_ops([(60, 600, 10, "Account Value $125,310.49")], 0)
    Path(path).write_bytes(gen.build_pdf([{"w_pt": 612.0, "h_pt": 792.0,
                                           "ops": ops + b"\n0 0 0 1 k\n" + text}]))
    return Path(path)


# a black box 40..400 x 560..680, the same box less 4 pt painted white over it
SHADOW = (b"0 0 0 1 k 40 560 360 120 re f\n"
          b"0 0 0 0 k 40 564 356 116 re f")
BAR = b"0 0 0 1 k 55 595 160 18 re f"


class TestShadowIsNotABar:
    def test_a_black_box_painted_over_in_white_hides_nothing(self, tmp_path):
        p = _pdf(tmp_path / "shadow.pdf", SHADOW)
        assert marks.native_bars(p) == {}

    def test_a_real_bar_still_hides_its_words(self, tmp_path):
        p = _pdf(tmp_path / "bar.pdf", BAR)
        got = marks.native_bars(p)
        assert got and "$125,310.49" in got[1]["hidden"]

    def test_a_bar_drawn_on_a_shadowed_panel_still_counts(self, tmp_path):
        p = _pdf(tmp_path / "both.pdf", SHADOW + b"\n" + BAR)
        got = marks.native_bars(p)
        assert got and len(got[1]["bars"]) == 1


class TestFidelityReal:
    def test_no_bar_on_the_fidelity_statement(self):
        hits = list((ROOT / "local_docs" / "DocAgent_testdocs").rglob("fidelity_brokerage.pdf")) \
            if (ROOT / "local_docs" / "DocAgent_testdocs").is_dir() else []
        if not hits:
            pytest.skip("fidelity_brokerage.pdf not in local_docs (git-ignored real data)")
        assert marks.native_bars(hits[0]) == {}


class TestReasonsOnce:
    def test_job_129_replay_has_no_repeated_reason(self):
        import json  # noqa: F401
        sys.path.insert(0, str(ROOT / "tools"))
        import replay_raw
        if not replay_raw.has_raw(129) or not replay_raw.find_source("fidelity_brokerage.pdf"):
            pytest.skip("local_docs/raw/129 or its PDF not present (git-ignored real data)")
        rep = replay_raw.replay_job(129)
        ed = rep["docs"][0][1]
        texts = [a["text"] for a in ed["attention"]]
        assert len(texts) == len(set(texts))
        assert not any("redacted_or_obscured" in (r.get("_review_reasons") or [])
                       for k, v in ed.items() if k.endswith("_rows") for r in v)
