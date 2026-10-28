"""Review-3 F4: a declared rule can neither hang nor crash an extraction.

(a) `(a+)+$` against "aaaa…b" never returned: Python's `re` backtracks
    exponentially and holds the GIL, so the worker stopped with it. Patterns
    are now admitted from a safe subset (engine/safe_regex.py) and a refused
    one is UNREADABLE with its reason; the same for category regexes.
(b) a tolerance of NaN raised inside the comparison and Infinity passed every
    unequal pair; non-finite, negative and absurd tolerances are refused.
(c) a malformed rule is a visible UNREADABLE and the record goes to review;
    it never takes down the other rules or the record.
"""
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

import rules as rules_mod  # noqa: E402
from rules import rule_problems, rules_of, run_rules  # noqa: E402
from validators import FAIL, PASS, UNREADABLE, CheckContext  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIELDS = [{"ref": "B1", "row_label": "Code", "row": 0, "col": 1},
          {"ref": "B2", "row_label": "Subtotal", "row": 1, "col": 1},
          {"ref": "B3", "row_label": "Total", "row": 2, "col": 1}]
TABLES = [{"name": "items", "columns": [{"key": "Amount", "header": "Amount"}]}]
EVIL = "a" * 40 + "b"


def ctx(values, rows=None):
    return CheckContext(FIELDS, values, ["page"], tables=TABLES,
                        rows={"items": rows or []})


def _in_subprocess(code, timeout=30):
    """Run `code` in a fresh interpreter; a hang FAILS the test in `timeout`
    seconds rather than hanging the suite."""
    prog = textwrap.dedent("""
        import sys
        sys.path[:0] = [r"{b}", r"{e}"]
    """).format(b=ROOT / "backend", e=ROOT / "backend" / "engine") + textwrap.dedent(code)
    try:
        r = subprocess.run([sys.executable, "-c", prog], capture_output=True,
                           timeout=timeout, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        pytest.fail(f"did not finish in {timeout} s (catastrophic backtracking)")
    out = r.stdout.decode("utf-8", "replace")
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-2000:]
    return out


# ── (a) catastrophic patterns ────────────────────────────────────────────────

CATASTROPHIC = [r"(a+)+$", r"(a*)*$", r"(a|aa)+$", r"(\w+\s?)+$", r"(?:a?a)+$",
                r"(.*a){12}$"]


@pytest.mark.parametrize("pattern", CATASTROPHIC)
def test_a_catastrophic_rule_pattern_is_refused_at_save(pattern):
    probs = rule_problems([{"name": "code", "type": "regex", "value": "Code",
                            "pattern": pattern}], FIELDS, TABLES)
    assert probs and "code" in probs[0], probs


def test_a_catastrophic_rule_pattern_is_unreadable_at_run_time_and_quick():
    out = _in_subprocess(f"""
        import time
        from rules import run_rules
        from validators import CheckContext
        F = [{{"ref": "B1", "row_label": "Code", "row": 0, "col": 1}}]
        t = time.perf_counter()
        res = run_rules([{{"name": "code", "type": "regex", "value": "Code",
                          "pattern": r"(a+)+$"}}],
                        CheckContext(F, {{"B1": "{EVIL}"}}, ["p"], tables=[], rows={{}}))
        print(res[0].status, res[0].reason, res[0].needs_review, bool(res[0].notes),
              round(time.perf_counter() - t, 2))
    """)
    status, reason, review, noted, secs = out.split()
    assert (status, reason, review, noted) == (UNREADABLE, "rule_unreadable:code",
                                               "True", "True"), out
    assert float(secs) < 2


@pytest.mark.parametrize("pattern", CATASTROPHIC)
def test_a_catastrophic_category_pattern_is_refused_and_never_run(pattern):
    from categorize import validate_rules
    rules = [{"category": "Travel", "regex": [pattern]}]
    assert validate_rules(rules), pattern
    out = _in_subprocess(f"""
        from categorize import categorize_rows
        r = categorize_rows([{{"Description": "{EVIL}"}}],
                            template_rules=[{{"category": "Travel", "regex": [r"{pattern}"]}}])
        print(r[0]["category"], "|", r[0].get("note", ""))
    """)
    cat, note = [x.strip() for x in out.split("|", 1)]
    assert cat != "Travel" and "was not used" in note, out


def test_safe_patterns_still_work():
    for pat, val, want in [(r"[A-Z]{2}\d{5}", "AB12345", PASS),
                           (r"[A-Z]{2}\d{5}", "AB1234", FAIL),
                           (r"INV-\d+", "INV-0042", PASS),
                           (r"(?:\d{3})+", "123456", PASS)]:
        assert rule_problems([{"name": "c", "type": "regex", "value": "Code",
                               "pattern": pat}], FIELDS, TABLES) == []
        [r] = run_rules([{"name": "c", "type": "regex", "value": "Code", "pattern": pat}],
                        ctx({"B1": val}))
        assert r.status == want, (pat, val)
    from categorize import categorize_rows
    [e] = categorize_rows([{"Description": "UBER TRIP 123"}],
                          template_rules=[{"category": "Travel", "regex": [r"^UBER\b"]}])
    assert e["category"] == "Travel"


def test_an_overlong_value_is_unreadable_not_matched():
    [r] = run_rules([{"name": "c", "type": "regex", "value": "Code", "pattern": r"a+"}],
                    ctx({"B1": "a" * 5000}))
    assert r.status == UNREADABLE


def test_the_time_budget_stops_a_rule_out_loud(monkeypatch):
    import safe_regex
    monkeypatch.setattr(safe_regex, "BUDGET_SEC", 0.0)
    rows = [{"Amount": f"A{i}"} for i in range(5)]
    out = run_rules([{"name": "c", "type": "regex", "value": "items.Amount",
                      "pattern": r"A\d+"}], ctx({}, rows))
    assert any(r.status == UNREADABLE and "could not run" in r.notes[0] for r in out)


# ── (b) tolerances ───────────────────────────────────────────────────────────

BAD_TOLERANCES = ["NaN", "nan", float("nan"), "Infinity", float("inf"), "-inf",
                  -1, "-0.01", 10**9, "1e9", "abc", True, [], {}]


@pytest.mark.parametrize("tol", BAD_TOLERANCES, ids=repr)
@pytest.mark.parametrize("kind", ["sum_equals", "equals", "product"])
def test_a_bad_tolerance_is_refused_and_never_passes_unequal_values(kind, tol):
    rule = {"name": "t", "type": kind, "tolerance": tol,
            **{"sum_equals": {"terms": ["Subtotal"], "total": "Total"},
               "equals": {"left": "Subtotal", "right": "Total"},
               "product": {"factors": ["Subtotal"], "result": "Total"}}[kind]}
    assert any("tolerance" in p for p in rule_problems([rule], FIELDS, TABLES)), tol
    res = run_rules([rule], ctx({"B2": "10.00", "B3": "99.00"}))
    assert res and all(r.status == UNREADABLE for r in res), (tol, res)


@pytest.mark.parametrize("tol", [0, "0.01", 0.5, 1000])
def test_a_sane_tolerance_is_accepted(tol):
    rule = {"name": "t", "type": "equals", "left": "Subtotal", "right": "Total",
            "tolerance": tol}
    assert rule_problems([rule], FIELDS, TABLES) == []
    [r] = run_rules([rule], ctx({"B2": "10.00", "B3": "10.00"}))
    assert r.status == PASS


@pytest.mark.parametrize("bound", ["NaN", "Infinity", "abc"])
def test_a_bad_range_bound_is_refused(bound):
    rule = {"name": "r", "type": "range", "value": "Total", "min": bound}
    assert rule_problems([rule], FIELDS, TABLES)
    [r] = run_rules([rule], ctx({"B3": "5"}))
    assert r.status == UNREADABLE


# ── (c) malformed rules ──────────────────────────────────────────────────────

@pytest.mark.parametrize("rules", [["x"], [5], [None], [["a"]], "notalist",
                                   {"name": "x"}, [{"type": "regex"}],
                                   [{"name": "x", "type": "regex", "value": "Code",
                                     "pattern": 7}]], ids=repr)
def test_malformed_rules_are_reported_and_never_crash(rules):
    assert rule_problems(rules if isinstance(rules, list) else rules, FIELDS, TABLES)
    out = run_rules(rules, ctx({"B1": "x"}))
    assert out and all(r.status == UNREADABLE and r.needs_review and r.notes for r in out)


def test_rules_of_keeps_a_malformed_entry_so_it_is_reported():
    assert rules_of({"rules": ["x", {"name": "a"}]}) == ["x", {"name": "a"}]


def test_a_rule_that_raises_is_unreadable_and_the_others_still_run(monkeypatch):
    def boom(rule, ctx, R):
        raise ZeroDivisionError("division by zero")
    monkeypatch.setitem(rules_mod._RUN, "range", boom)
    out = run_rules([{"name": "bad", "type": "range", "value": "Total", "min": 0},
                     {"name": "ok", "type": "equals", "left": "Subtotal", "right": "Total"}],
                    ctx({"B2": "1.00", "B3": "1.00"}))
    bad = [r for r in out if r.check == "rule:bad"]
    ok = [r for r in out if r.check == "rule:ok"]
    assert bad and bad[0].status == UNREADABLE and bad[0].needs_review
    assert "ZeroDivisionError" in bad[0].notes[0]
    assert ok and ok[0].status == PASS


def test_through_the_registry_a_malformed_rule_sends_the_record_to_review():
    from validators import run_checks
    c = ctx({"B1": EVIL, "B2": "1", "B3": "1"})
    c.rules = [{"name": "code", "type": "regex", "value": "Code", "pattern": r"(a+)+$"},
               "junk"]
    res = [r for r in run_checks("invoice", c) if str(r.check).startswith("rule:")]
    assert res and all(r.status == UNREADABLE and r.needs_review for r in res)
