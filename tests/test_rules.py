"""Declarative template rules (Part 3.1, engine/rules.py): each type, its
reason codes, and what a wrongly stated rule does."""
import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from rules import rule_problems, rules_of, run_rules  # noqa: E402
from validators import FAIL, PASS, UNREADABLE, CheckContext  # noqa: E402

FIELDS = [{"ref": f"B{i + 1}", "row_label": lab, "row": i, "col": 1}
          for i, lab in enumerate(["Subtotal", "Tax", "Discount", "Total", "Invoice Date",
                                   "Due Date", "Line Count", "Routing", "PO Number",
                                   "Payment Terms", "Late Fee", "Currency Total"])]
TABLES = [{"name": "items", "columns": [{"key": "Qty", "header": "Qty"},
                                        {"key": "Price", "header": "Price"},
                                        {"key": "Amount", "header": "Amount"}]}]


def ctx(values, rows=None, **kw):
    return CheckContext(FIELDS, values, ["page"], tables=TABLES,
                        rows={"items": rows or []}, **kw)


def one(rule, values, rows=None, **kw):
    out = run_rules([{"name": "r", **rule}], ctx(values, rows, **kw))
    return out


ROWS = [{"Qty": "2", "Price": "10.00", "Amount": "20.00"},
        {"Qty": "3", "Price": "5.00", "Amount": "15.00"}]


def test_sum_equals_with_a_column_optional_and_subtracted_terms():
    v = {"B1": "35.00", "B2": "3.50", "B3": "1.00", "B4": "37.50"}
    [lines] = one({"type": "sum_equals", "terms": ["items.Amount"], "total": "Subtotal"}, v, ROWS)
    assert lines.status == PASS
    [g] = one({"type": "sum_equals", "terms": ["Subtotal", "Tax?", "-Discount"],
               "total": "Total"}, v)
    assert g.status == PASS
    v["B4"] = "38.50"
    [g] = one({"type": "sum_equals", "terms": ["Subtotal", "Tax?", "-Discount"],
               "total": "Total"}, v)
    assert g.status == FAIL and g.reason == "rule_failed:r"
    assert set(g.slots) == {"B1", "B2", "B3", "B4"}


def test_an_empty_optional_term_counts_as_nothing_and_an_empty_required_one_stops_the_rule():
    rule = {"type": "sum_equals", "terms": ["Subtotal", "Tax?"], "total": "Total"}
    assert one(rule, {"B1": "35.00", "B4": "35.00"})[0].status == PASS
    assert one({**rule, "terms": ["Subtotal", "Tax"]}, {"B1": "35.00", "B4": "35.00"}) == []


def test_an_ambiguous_amount_is_unreadable_not_failed():
    [r] = one({"type": "sum_equals", "terms": ["Subtotal"], "total": "Total"},
              {"B1": "1,234", "B4": "1234.00"})
    assert r.status == UNREADABLE and r.reason == "rule_unreadable:r"


def test_equals_numbers_and_text():
    assert one({"type": "equals", "left": "Subtotal", "right": "Total"},
               {"B1": "$1,000.00", "B4": "1000"})[0].status == PASS
    assert one({"type": "equals", "left": "PO Number", "right": "Payment Terms"},
               {"B9": "Net 30", "B10": "net  30"})[0].status == PASS
    assert one({"type": "equals", "left": "PO Number", "right": "Payment Terms"},
               {"B9": "Net 30", "B10": "Net 45"})[0].status == FAIL


def test_product_runs_per_row_and_marks_only_the_wrong_row():
    rows = [dict(ROWS[0]), {**ROWS[1], "Amount": "16.00"}]
    out = one({"type": "product", "factors": ["items.Qty", "items.Price"],
               "result": "items.Amount"}, {}, rows)
    assert [r.status for r in out] == [PASS, FAIL]
    assert out[1].slots == ["items_rows[1]"]


def test_range_and_regex_per_row_and_on_fields():
    out = one({"type": "range", "value": "items.Qty", "min": 1, "max": 2}, {}, ROWS)
    assert [r.status for r in out] == [PASS, FAIL]
    assert one({"type": "regex", "value": "PO Number", "pattern": r"PO-\d{4}"},
               {"B9": "PO-0018"})[0].status == PASS
    assert one({"type": "regex", "value": "PO Number", "pattern": r"PO-\d{4}"},
               {"B9": "PO-18"})[0].status == FAIL


def test_id_type_uses_the_identifier_plug_in():
    assert one({"type": "id_type", "value": "Routing", "id_type": "aba"},
               {"B8": "021000021"})[0].status == PASS
    assert one({"type": "id_type", "value": "Routing", "id_type": "aba"},
               {"B8": "021000022"})[0].status == FAIL


def test_date_order_and_an_ambiguous_date():
    rule = {"type": "date_order", "first": "Invoice Date", "then": "Due Date"}
    assert one(rule, {"B5": "2024-04-18", "B6": "2024-05-18"})[0].status == PASS
    assert one(rule, {"B5": "2024-06-18", "B6": "2024-05-18"})[0].status == FAIL
    assert one(rule, {"B5": "03/04/2024", "B6": "05/06/2024"})[0].status == UNREADABLE
    assert one(rule, {"B5": "03/04/2024", "B6": "05/06/2024"},
               locale="en-GB")[0].status == PASS


def test_count_matches():
    rule = {"type": "count_matches", "table": "items", "count": "Line Count"}
    assert one(rule, {"B7": "2"}, ROWS)[0].status == PASS
    assert one(rule, {"B7": "3"}, ROWS)[0].status == FAIL


def test_currency_same():
    rule = {"type": "currency_same", "values": ["Subtotal", "Total"]}
    assert one(rule, {"B1": "$10.00", "B4": "$12.00"})[0].status == PASS
    assert one(rule, {"B1": "$10.00", "B4": "€12.00"})[0].status == FAIL


def test_required_if_puts_the_record_into_review():
    rule = {"type": "required_if", "value": "Late Fee", "if": "Payment Terms", "equals": "Net 30"}
    [r] = one(rule, {"B10": "Net 30"})
    assert r.status == FAIL and r.needs_review and r.slots == ["B10"]
    assert one(rule, {"B10": "Net 30", "B11": "$5.00"})[0].status == PASS
    assert one(rule, {"B10": "Net 45"}) == []


@pytest.mark.parametrize("rule,said", [
    ({"type": "sum_of_squares"}, "unknown type"),
    ({"type": "sum_equals", "terms": ["Subtotal"]}, "needs total"),
    ({"type": "sum_equals", "terms": ["Nonexistent"], "total": "Total"}, "names no field"),
    ({"type": "regex", "value": "PO Number", "pattern": "("}, "does not compile"),
    ({"type": "id_type", "value": "Routing", "id_type": "imaginary"}, "unknown id_type"),
])
def test_a_wrongly_stated_rule_is_reported_and_never_skipped_quietly(rule, said):
    probs = rule_problems([{"name": "r", **rule}], FIELDS, TABLES)
    assert any(said in p for p in probs), probs
    [r] = run_rules([{"name": "r", **rule}], ctx({"B1": "1.00", "B4": "1.00"}))
    assert r.status == UNREADABLE and r.needs_review and r.reason == "rule_unreadable:r"


def test_duplicate_rule_names_are_a_problem():
    rr = [{"name": "x", "type": "range", "value": "Total", "max": 5}] * 2
    assert any("share this name" in p for p in rule_problems(rr, FIELDS, TABLES))


def test_rules_are_read_from_the_template_or_its_grid():
    r = [{"name": "x", "type": "range", "value": "Total", "max": 5}]
    assert rules_of({"rules": r}) == r
    assert rules_of({"layout": {"cells": {}, "rules": r}}) == r
    assert rules_of({"layout": {"cells": {}}}) == [] and rules_of(None) == []


def test_the_reason_label_names_the_rule():
    from app.core.review import reason_text
    label, _tip = reason_text("rule_failed:lines_sum")
    assert label == "Template rule failed (lines_sum)"
