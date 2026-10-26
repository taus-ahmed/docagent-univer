"""Declared rules against the coded family checks, on every locale fixture
(Part 3.1).

Each fixture (tests/fixtures/make_locale_fixtures.py) is extracted twice from
its own truth: once as its family, so the CODED checks run, and once as a
family with nothing registered, carrying the rules a template author would
declare instead (tests/rules_equivalents.py). The checks every family shares
run in both, so any difference is the family's.

Measured: 14 of 16 mark exactly the same values low. The other two are the
bank-statement corruptions the coded check finds by walking the RUNNING
BALANCE row to row, which none of the ten rule types can express (it needs the
previous row). The declared rules catch both anyway — through the credit and
debit column sums — but mark different values, so for those two this test
asserts only what matters: the defect is caught both ways and nothing passes
silently. A family that needs the running balance keeps its coded check
(docs/ADDING-A-DOCUMENT-FAMILY.md).
"""
import json

import pytest

import tests.test_locale_fixtures as T
from tests.rules_equivalents import rules_for

RUNNING_BALANCE_ONLY = {"statement_us_dropped_row", "statement_us_swapped_debit_credit"}


def _low(ed):
    cm = (ed.get("validation") or {}).get("confidence_map") or {}
    out = {r for r, lv in cm.items() if lv == "low"}
    for k, rows in ed.items():
        if k.endswith("_rows") and isinstance(rows, list):
            out |= {f"{k}[{i}]" for i, r in enumerate(rows) if r.get("_confidence") == "low"}
    return out


def _both(name, tmp_path, monkeypatch):
    d = T.DOCS[name]
    coded = T.run(name, tmp=tmp_path)
    tpl = json.loads(json.dumps(d["template"]))
    monkeypatch.setitem(d, "template", {**tpl, "doc_type": "generic", "rules": rules_for(d)})
    declared = T.run(name, tmp=tmp_path)
    return coded, declared


@pytest.mark.parametrize("name", sorted(set(T.DOCS) - RUNNING_BALANCE_ONLY))
def test_declared_rules_mark_exactly_what_the_coded_checks_mark(name, tmp_path, monkeypatch):
    coded, declared = _both(name, tmp_path, monkeypatch)
    assert _low(declared) == _low(coded)
    ran = {k for k in declared.get("validation") or {} if k.startswith("rule:")}
    assert ran, "the declared rules did not run"


@pytest.mark.parametrize("name", sorted(RUNNING_BALANCE_ONLY))
def test_a_running_balance_defect_is_caught_both_ways(name, tmp_path, monkeypatch):
    clean_coded, _ = _both("statement_us", tmp_path, monkeypatch)
    monkeypatch.undo()
    coded, declared = _both(name, tmp_path, monkeypatch)
    baseline = _low(clean_coded)
    assert _low(coded) - baseline, "coded check missed the defect"
    assert _low(declared) - baseline, "declared rules missed the defect"
    assert coded.get("needs_review") and declared.get("needs_review")
    assert any(v == "fail" for k, v in (declared.get("validation") or {}).items()
               if k.startswith("rule:"))
