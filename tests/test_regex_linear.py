"""Recheck R1: no admitted pattern can run long on one value.

Codex found two patterns the Review-3 F4 subset admitted that still ran for
tens of seconds on ONE value: `a{0,100}a{0,100}a{0,100}a{0,100}a{0,100}b`
against 512 `a`s (fullmatch, ~30 s: bounded quantifiers were never counted)
and `\\d*\\d*\\d*x` against 512 digits (search, ~18 s: three quantifiers was
the limit, and `search` retries from every start). The 2 s budget is checked
only between calls, so it could not stop either.

Matching now runs on RE2 (linear time in the text, no backtracking at all),
and the subset check stays as defence in depth: every variable-length
quantifier counts, bounded or not, and a pattern is test-matched against
adversarial strings before it is admitted. Each timing here runs in a fresh
interpreter with a hard timeout, so a regression fails the test instead of
hanging the suite.
"""
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

import safe_regex  # noqa: E402
from safe_regex import compile_safe, pattern_problem  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PER_VALUE = 1.5

#: (pattern, adversarial text) — Codex's two, nested and adjacent
#: quantifiers, and alternation overlap
WORST = [
    ("a{0,100}a{0,100}a{0,100}a{0,100}a{0,100}b", "a" * 512),
    (r"\d*\d*\d*x", "1" * 512),
    (r"(a+)+$", "a" * 511 + "b"),
    (r"(?:a{1,5}){1,50}b", "a" * 512),
    (r"a*a*a*a*a*a*b", "a" * 512),
    (r"(a|a)*b", "a" * 512),
    (r"(.*a){12}$", "a" * 511 + "b"),
]


def _timed(pattern, text, timeout=20):
    """Seconds for compile_safe + fullmatch + search in a fresh interpreter,
    or None when the pattern is refused. A hang FAILS in `timeout` seconds."""
    prog = textwrap.dedent(f"""
        import sys, time
        sys.path[:0] = [r"{ROOT / 'backend'}", r"{ROOT / 'backend' / 'engine'}"]
        from safe_regex import compile_safe, UnsafePattern
        try:
            p = compile_safe({pattern!r})
        except UnsafePattern:
            print("refused"); raise SystemExit
        worst = 0.0
        for fn in (p.fullmatch, p.search):
            t = time.perf_counter(); fn({text!r}); worst = max(worst, time.perf_counter() - t)
        print(worst)
    """)
    try:
        r = subprocess.run([sys.executable, "-c", prog], capture_output=True,
                           timeout=timeout, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        pytest.fail(f"{pattern!r} did not finish in {timeout} s")
    out = r.stdout.decode("utf-8", "replace").strip()
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-1500:]
    return None if out == "refused" else float(out)


@pytest.mark.parametrize("pattern,text", WORST, ids=[p for p, _ in WORST])
def test_worst_case_finishes_in_under_1_5_s_per_value(pattern, text):
    secs = _timed(pattern, text)
    assert secs is None or secs < PER_VALUE, (pattern, secs)


@pytest.mark.parametrize("pattern", ["a{0,100}a{0,100}a{0,100}a{0,100}a{0,100}b",
                                     "a{0,9}b{0,9}c{0,9}d{0,9}",
                                     r"\d?\d?\d?\d?x",
                                     r"(a|a)*b"])
def test_every_variable_quantifier_counts_and_overlap_is_refused(pattern):
    assert pattern_problem(pattern), pattern


@pytest.mark.parametrize("pattern", [r"[A-Z]{2}\d{5}", r"INV-\d+", r"(?:\d{3})+",
                                     r"^UBER\b", r"\d{3}-\d{4}", r"\d+-\d+", r"(?:\+|00)?\d{10}"])
def test_ordinary_patterns_are_admitted(pattern):
    assert pattern_problem(pattern) is None, pattern_problem(pattern)


def test_both_search_and_fullmatch_run_on_the_linear_engine():
    p = compile_safe(r"INV-\d+")
    assert p.engine == "re2"
    assert p.fullmatch("INV-0042") and not p.fullmatch("x INV-0042")
    assert p.search("ref INV-0042 paid").group(0) == "INV-0042"
    assert compile_safe("uber", 2).search("UBER TRIP")          # re.I


def test_a_pattern_slow_on_the_probe_strings_is_refused_at_save(monkeypatch):
    """The save-time probe really runs the pattern: with its allowance set to
    nothing, any pattern is 'too slow', and the reason says so."""
    monkeypatch.setattr(safe_regex, "PROBE_SEC", 0.0)
    why = pattern_problem(r"INV-\d+")
    assert why and "test string" in why, why


def test_lookarounds_are_refused_out_loud():
    """RE2 has no lookaround; a pattern using one is refused with a reason,
    never compiled by a different engine behind the user's back."""
    why = pattern_problem(r"(?=INV)\w+")
    assert why and "lookahead" in why, why


def test_a_category_budget_running_out_leaves_the_row_uncategorized(monkeypatch):
    from categorize import UNCATEGORIZED, categorize_rows
    monkeypatch.setattr(safe_regex, "BUDGET_SEC", 0.0)
    [e] = categorize_rows([{"Description": "UBER TRIP 123"}],
                          template_rules=[{"category": "Travel", "regex": [r"^UBER"]}])
    assert e["category"] == UNCATEGORIZED and "not applied" in e.get("note", ""), e
