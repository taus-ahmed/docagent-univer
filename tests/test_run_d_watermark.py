"""Run D, D3 — rotated text is removed only when it is clearly decoration,
and the result says exactly what was removed."""
from __future__ import annotations

import math
from types import SimpleNamespace

from tests.harness import bootstrap as bs

bs.bootstrap()

from text_layer import watermark_chars, watermark_runs  # noqa: E402

BODY = [{"text": "x", "size": 10, "matrix": (1, 0, 0, 1)} for _ in range(20)]
A = math.radians(35)
DIAG = (math.cos(A), math.sin(A), -math.sin(A), math.cos(A))


def _run(text, size=10, color=None, matrix=DIAG):
    return [{"text": ch, "size": size, "matrix": matrix,
             **({"non_stroking_color": color} if color is not None else {})}
            for ch in text]


def _page(*runs):
    chars = list(BODY)
    for r in runs:
        chars += r + BODY[:1]           # upright text between runs
    return SimpleNamespace(chars=chars)


def test_an_oversized_diagonal_word_is_decoration():
    assert [t for t, _ in watermark_runs(_page(_run("SAMPLE", size=48)))] == ["SAMPLE"]


def test_a_tiled_body_size_word_is_decoration():
    page = _page(_run("CONFIDENTIAL"), _run("CONFIDENTIAL"))
    assert [t for t, _ in watermark_runs(page)] == ["CONFIDENTIAL", "CONFIDENTIAL"]


def test_a_very_faint_word_is_decoration():
    assert watermark_chars(_page(_run("DRAFT", color=(0.9, 0.9, 0.9))))


def test_a_body_size_stamp_in_normal_ink_stays():
    assert watermark_runs(_page(_run("PAID", color=(0.8, 0.0, 0.0)))) == []


def test_rotated_text_with_digits_is_never_removed():
    page = _page(_run("PAID 03/12/2026", size=48), _run("$1,250.00", size=48),
                 _run("$1,250.00", size=48))
    assert watermark_runs(page) == []


def test_the_result_names_the_words_removed_from_each_page():
    """The generated acceptance bank statement carries the 48pt SAMPLE
    stamp: the record says page 1 lost exactly that word and nothing else."""
    import contextlib
    import io
    from core.preprocessor import preprocess_file
    from tests.contract.run_a_driver import DOCS
    with contextlib.redirect_stdout(io.StringIO()):
        d = preprocess_file(DOCS / "bank_statement" / "flowparse_bank_us.pdf")
    assert d.watermark_removed == {1: ["SAMPLE"]}
