"""
Unit tests for the runner's two safety mechanisms. Offline, always green.

These exist because both mechanisms fail SILENTLY when broken: a diff that
never flags a regression, and a stability check that calls everything stable,
both look exactly like good news.
"""
from tests.harness.runner import diff_runs, find_unstable, flatten_outcomes


def _report(fields, tables=None):
    return {"documents": {"DOC-1": {"score": {
        "fields": {k: {"outcome": v} for k, v in fields.items()},
        "tables": tables or {},
    }}}}


class TestDiff:
    def test_correct_to_wrong_is_flagged_regression(self):
        prev = _report({"Amount": "correct", "Payee": "correct"})
        cur = _report({"Amount": "wrong", "Payee": "correct"})
        changes = diff_runs(prev, cur)
        assert len(changes) == 1
        assert changes[0]["key"] == "DOC-1 :: Amount"
        assert changes[0]["before"] == "correct"
        assert changes[0]["after"] == "wrong"
        assert changes[0]["regression"] is True

    def test_correct_to_missed_is_also_a_regression(self):
        changes = diff_runs(_report({"A": "correct"}), _report({"A": "missed"}))
        assert changes[0]["regression"] is True

    def test_improvement_is_a_change_but_not_a_regression(self):
        changes = diff_runs(_report({"A": "wrong"}), _report({"A": "correct"}))
        assert len(changes) == 1
        assert changes[0]["regression"] is False

    def test_identical_runs_produce_no_diff(self):
        r = _report({"A": "correct", "B": "missed"})
        assert diff_runs(r, r) == []

    def test_disappearing_field_is_a_regression(self):
        changes = diff_runs(_report({"A": "correct"}), _report({}))
        assert changes[0]["after"] is None
        assert changes[0]["regression"] is True

    def test_row_count_mismatch_is_diffed(self):
        """The phantom-row metric must be diffable on its own, or a newly
        fabricated row shows up as nothing but a small cell-accuracy dip."""
        prev = _report({}, {"line_items": {"cells": [], "row_count_mismatch": 0}})
        cur = _report({}, {"line_items": {"cells": [], "row_count_mismatch": 1}})
        changes = diff_runs(prev, cur)
        assert changes[0]["key"] == "DOC-1 :: line_items :: row_count_mismatch"
        assert changes[0]["before"] == "0"
        assert changes[0]["after"] == "1"

    def test_flatten_includes_table_cells(self):
        rep = _report({}, {"t": {"row_count_mismatch": 0, "cells": [
            {"row": 0, "pred_row": 0, "column": "Amount", "outcome": "wrong"}]}})
        flat = flatten_outcomes(rep)
        assert flat["DOC-1 :: t[row 0].Amount"] == "wrong"


class TestStability:
    def test_varying_field_is_unstable(self):
        runs = [
            {"fields": {"Annual Salary": "145000.0"}, "tables": {}},
            {"fields": {"Annual Salary": "annual salary"}, "tables": {}},
        ]
        u = find_unstable(runs)
        assert [x["key"] for x in u] == ["field:Annual Salary"]

    def test_field_present_then_missing_is_unstable(self):
        runs = [{"fields": {"Total Equity": "698,104"}, "tables": {}},
                {"fields": {}, "tables": {}}]
        assert find_unstable(runs)[0]["key"] == "field:Total Equity"

    def test_identical_runs_are_stable(self):
        runs = [{"fields": {"A": "1"}, "tables": {"t": [{"X": "y"}]}}] * 3
        assert find_unstable(runs) == []

    def test_formatting_only_difference_is_not_unstable(self):
        """Values are compared normalized: 'Net 30' vs 'net  30' is the same
        answer, and flagging it would bury the real instabilities."""
        runs = [{"fields": {"Terms": "Net 30"}, "tables": {}},
                {"fields": {"Terms": "net  30"}, "tables": {}}]
        assert find_unstable(runs) == []

    def test_row_count_variation_is_unstable(self):
        runs = [{"fields": {}, "tables": {"line_items": [{"A": "1"}]}},
                {"fields": {}, "tables": {"line_items": [{"A": "1"}, {"A": "2"}]}}]
        keys = [x["key"] for x in find_unstable(runs)]
        assert "table:line_items:row_count" in keys

    def test_single_run_cannot_be_unstable(self):
        assert find_unstable([{"fields": {"A": "1"}, "tables": {}}]) == []
