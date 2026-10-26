"""Amounts summed or compared share one currency (Part 1.5)."""
from __future__ import annotations

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from amounts import CURRENCY_AMBIGUOUS, CURRENCY_MISMATCH, currency_agreement  # noqa: E402
from validators import FAIL, PASS, UNREADABLE, CheckContext, CheckResult  # noqa: E402


@pytest.mark.parametrize("texts,verdict", [
    (["$10.00", "$5.00", "15.00"], "ok"),
    (["€10,00", "€5,00"], "ok"),
    (["£10.00", "€5.00"], CURRENCY_MISMATCH),
    (["$10.00", "€5.00"], CURRENCY_MISMATCH),
    (["USD 10.00", "INR 5.00"], CURRENCY_MISMATCH),
    (["$10.00", "C$5.00"], CURRENCY_AMBIGUOUS),
    (["¥1000", "元50.00"], CURRENCY_AMBIGUOUS),
    (["CAD 10.00", "C$5.00"], "ok"),
    (["10.00", "5.00"], "ok"),
])
def test_agreement(texts, verdict):
    assert currency_agreement(texts)[0] == verdict


def _gate(values, status=PASS):
    from validators import _currency_gate
    ctx = CheckContext(fields=[], values=values, pages=[])
    return _currency_gate(CheckResult("invoice_totals", status, list(values), "totals_mismatch"), ctx)


def test_a_sum_over_two_currencies_fails_with_its_own_reason():
    r = _gate({"B1": "£10.00", "B2": "€5.00", "B3": "15.00"})
    assert (r.status, r.reason) == (FAIL, CURRENCY_MISMATCH) and r.needs_review
    r = _gate({"B1": "£10.00", "B2": "€5.00"}, status=FAIL)
    assert r.reason == CURRENCY_MISMATCH


def test_possibly_different_dollars_are_ambiguous_not_failed():
    r = _gate({"B1": "$10.00", "B2": "C$5.00"})
    assert (r.status, r.reason) == (UNREADABLE, CURRENCY_AMBIGUOUS)


def test_one_currency_leaves_the_result_alone():
    r = _gate({"B1": "$10.00", "B2": "$5.00"})
    assert (r.status, r.reason) == (PASS, "totals_mismatch")


def test_end_to_end_on_the_invoice_family():
    from validators import run_checks
    fields = [{"ref": "B1", "row_label": "Subtotal"}, {"ref": "B2", "row_label": "Tax"},
              {"ref": "B3", "row_label": "Total"}]
    ctx = CheckContext(fields=fields, values={"B1": "£100.00", "B2": "€20.00",
                                              "B3": "120.00"}, pages=[])
    res = [r for r in run_checks("invoice", ctx) if r.check != "number_notation"]
    assert any(r.reason == CURRENCY_MISMATCH and r.status == FAIL for r in res), \
        [(r.check, r.status, r.reason) for r in res]
