"""Independent adversarial review of Run B extraction rules.

Every answer is frozen or locally scripted.  Nothing in this module creates a
provider client or permits a network/model call.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.contract import run_a_driver as D  # bootstraps backend imports
from tests.test_run_b_forms import DOCS, FORMS, _golden, _run

import aliases as AL  # noqa: E402
import form_fields as FF  # noqa: E402
import format_rules as FR  # noqa: E402
import source_inventory as SI  # noqa: E402


# B3: last-four and type boundaries -------------------------------------------------

@pytest.mark.parametrize("label, expected", [
    ("Ending Balance", False),
    ("Last Payment", False),
    ("Statement Ending", False),
    ("Account Type", False),
    ("Routing Number", False),
    ("Card number last four", True),
])
def test_last_four_rule_does_not_spread_to_nearby_business_labels(label, expected):
    assert FR.is_last4_slot(label) is expected


@pytest.mark.parametrize("line, value", [
    ("Account 99110088", "0088"),
    ("Account 77001100", "1100"),
    ("Card 55550011", "0011"),
])
def test_last_four_keeps_repeated_zero_eight_and_one_digits(line, value):
    assert FR.check_last4(value, D.words(1, [line]))[:2] == ("ok", value)


def test_last_four_flags_even_when_model_picks_one_of_two_accounts():
    lines = D.words(1, ["Account 11110088", "Card 22220011"])
    assert FR.check_last4("0088", lines)[0] == "ambiguous"


def test_routing_number_is_not_a_last_four_candidate():
    lines = D.words(1, ["Routing Number 071000505", "Account Number 7301558842"])
    assert FR.account_numbers(lines) == [
        ("7301558842", "Account Number 7301558842")]
    assert FR.check_last4("58842", lines)[:2] == ("corrected", "8842")


# B1: widget pairing ----------------------------------------------------------------

WIDGET_SLOTS = {
    "irs_w2_mod11": {
        "Box a Employee SSN", "Box b Employer EIN", "Box c Employer Name",
        "Employer Address", "Box e Employee Name", "Box f Employee Address",
        "Box 1 Wages Tips Other Compensation", "Box 2 Federal Income Tax Withheld",
        "Box 3 Social Security Wages", "Box 4 Social Security Tax Withheld",
        "Box 5 Medicare Wages and Tips", "Box 6 Medicare Tax Withheld",
    },
    "irs_w2_2012": {
        "Box a Employee SSN", "Box b Employer EIN", "Box c Employer Name",
        "Employer Address", "Box e Employee Name", "Box f Employee Address",
        "Box 1 Wages Tips Other Compensation", "Box 2 Federal Income Tax Withheld",
        "Box 3 Social Security Wages", "Box 4 Social Security Tax Withheld",
        "Box 5 Medicare Wages and Tips", "Box 6 Medicare Tax Withheld",
        "Box 7 Social Security Tips",
    },
    "irs_1099nec_ellis": {
        "Payer Name", "Payer Address", "Payer TIN", "Recipient Name",
        "Recipient Address", "Recipient TIN", "Box 1 Nonemployee Compensation",
    },
    "irs_1099int_mod3": {
        "Payer Name", "Payer TIN", "Recipient Name", "Recipient TIN",
        "INT Box 1 Interest Income",
    },
    "irs_1098_joe_angela": {
        "Tax Year", "Lender Name", "Lender TIN", "Borrower Name",
        "Borrower TIN", "Box 1 Mortgage Interest",
    },
}


@pytest.mark.parametrize("rel,sheet,doc_type,truth", FORMS,
                         ids=[f"all-widget-pairs-{x[3]}" for x in FORMS])
def test_every_fillable_fixture_pairs_each_widget_with_only_its_intended_slot(
        rel, sheet, doc_type, truth):
    from core.preprocessor import preprocess_file
    from slot_extractor import enumerate_slots
    from tests.tools.score_runs import values_equal

    document = preprocess_file(DOCS / rel)
    entries = [entry for page in document.form_fields.values() for entry in page]
    slots = enumerate_slots(D.template_grid(sheet))["fields"]
    data = _run(rel, sheet, doc_type)
    actual = {label: cell.get("value")
              for label, cell in data["extracted_data"].items()}
    truth_values = _golden(truth)["headers"]

    matched = {}
    for slot in slots:
        entry, _strong = FF.match(slot["row_label"], entries)
        if entry is None:
            continue
        label = slot["row_label"]
        assert label in WIDGET_SLOTS[truth], (truth, label, entry)
        assert entry["kind"] == "text"
        assert values_equal(truth_values[label]["value"], actual.get(label),
                            truth_values[label]["type"]), \
            (truth, label, truth_values[label]["value"], actual.get(label), entry)
        assert FF.same_value(actual[label], entry["value"])
        matched[label] = entry

    assert set(matched) == WIDGET_SLOTS[truth]
    assert all(FF.match(slot["row_label"], [entry])[0] is None
               for entry in entries if entry["kind"] == "checkbox"
               for slot in slots)
    assert all(str(entry["value"]).strip()
               for entry in entries if entry["kind"] == "text")


def test_zero_is_a_widget_value_but_empty_widgets_and_checkboxes_do_not_fill_slots():
    words = D.words(1, ["1 Wages"])[0]
    zero_entries = FF.entries_for_page(words, [{
        "x0": 40, "x1": 180, "top": 64, "bottom": 80,
        "value": "0", "name": "box_1", "tooltip": "Box 1 wages",
    }], 1)
    entry, _strong = FF.match("Box 1 Wages", zero_entries)
    assert entry is not None and entry["value"] == "0"
    assert FF.prompt_block(zero_entries).count(": 0") == 1
    assert FF.prompt_block([]) == ""                 # upstream drops empty /V
    checkbox = {"label": "Corrected", "extra": "", "value": "checked",
                "box": None, "role": "whole", "kind": "checkbox", "page": 1}
    assert FF.match("Corrected", [checkbox]) == (None, False)


# B2: aliases are hints, never cross-slot assignment --------------------------------

@pytest.mark.parametrize("labels, printed, values", [
    (("Ship To", "Bill To"),
     ("Delivered To Warehouse A", "Sold To Head Office"),
     ("Warehouse A", "Head Office")),
    (("Remit To", "Bill To"),
     ("Remit To Lockbox 9", "Sold To Client HQ"),
     ("Lockbox 9", "Client HQ")),
    (("Date", "Due Date"),
     ("Transaction Date 2026-01-01", "Pay By 2026-02-01"),
     ("2026-01-01", "2026-02-01")),
])
def test_alias_pairs_do_not_cross_assign(labels, printed, values):
    from slot_extractor import enumerate_slots

    grid = {"cells": {f"{i},0": {"value": label}
                      for i, label in enumerate(labels)},
            "merges": {}, "colWidths": [], "repeatRows": []}
    slots = enumerate_slots(grid)["fields"]
    answer = {"fields": {
        slot["slot_id"]: {"value": value, "source": source, "page": 1}
        for slot, value, source in zip(slots, values, printed)
    }, "tables": {}}
    prompts = []

    def extract(**kwargs):
        prompts.append(kwargs.get("prompt", ""))
        return D.model_response(json.loads(json.dumps(answer)))

    data = D.run_synthetic(extract, [list(printed)], grid=grid)
    got = {label: cell["value"] for label, cell in data["extracted_data"].items()}
    assert got == dict(zip(labels, values))
    assert data["validation"]["flagged_fields"] == []
    # The hint vocabulary for one label must not contain the other label.
    left = {_normal_alias(labels[0]), *map(_normal_alias, AL.aliases_for(labels[0]))}
    right = {_normal_alias(labels[1]), *map(_normal_alias, AL.aliases_for(labels[1]))}
    assert not left.intersection(right)
    assert prompts


def _normal_alias(value):
    return " ".join(str(value).casefold().replace("-", " ").split())


# B4: watermark audit ---------------------------------------------------------------

def test_watermark_removal_audits_every_acceptance_and_available_local_pdf():
    import pdfplumber
    from text_layer import PdfplumberSource, watermark_chars

    roots = [Path(__file__).parent / "fixtures" / "acceptance"]
    local = Path(__file__).parents[1] / "local_docs"
    if local.exists():
        roots.append(local)
    pdfs = sorted(path for root in roots for path in root.rglob("*.pdf"))
    assert pdfs
    audited = hits = 0
    for path in pdfs:
        with pdfplumber.open(path) as pdf:
            for page_no, page in enumerate(pdf.pages, 1):
                audited += 1
                before = page.extract_words()
                marks = watermark_chars(page)
                source = PdfplumberSource(page)
                after = source._page.extract_words()
                removed = max(0, len(before) - len(after))
                print(f"watermark-audit {path.relative_to(Path(__file__).parents[1])} "
                      f"page={page_no} removed_words={removed} "
                      f"watermark_chars={len(marks)}")
                if marks:
                    hits += 1
                    assert "".join(str(char.get("text", "")) for char in marks) == "SAMPLE"
                else:
                    assert before == after
                    assert source.raw_text() == page.extract_text()
                    assert removed == 0
    assert audited >= 55
    assert hits == 5


def test_small_diagonal_paid_stamp_is_not_a_watermark():
    from text_layer import watermark_chars

    body = [{"text": "x", "size": 10, "matrix": (1, 0, 0, 1)} for _ in range(20)]
    angle = math.radians(35)
    matrix = (math.cos(angle), math.sin(angle), -math.sin(angle), math.cos(angle))
    paid = [{"text": char, "size": 10, "matrix": matrix} for char in "PAID"]
    assert watermark_chars(SimpleNamespace(chars=body + paid)) == []


def test_vertical_body_size_form_text_is_not_a_watermark():
    from text_layer import watermark_chars

    body = [{"text": "x", "size": 10, "matrix": (1, 0, 0, 1)} for _ in range(20)]
    vertical = [{"text": char, "size": 10, "matrix": (0, 1, -1, 0)}
                for char in "FORM"]
    assert watermark_chars(SimpleNamespace(chars=body + vertical)) == []


# B6: row-sum false-positive attacks -----------------------------------------------

SUM_SLOTS = {"fields": [], "tables": [{"name": "table", "columns": [
    {"header": "Description"}, {"header": "Amount"},
]}]}


@pytest.mark.xfail(
    strict=True,
    reason=("Run B item B6: row_sum_checks takes the absolute value of a "
            "parenthesized Less line and falsely flags a correct net total"),
)
def test_row_sum_respects_less_lines_and_parenthesized_negatives():
    rows = {"table": [{"Description": "Services", "Amount": "100.00"},
                      {"Description": "Less discount", "Amount": "(20.00)"}]}
    page = [D.words(1, ["Services 100.00", "Less discount (20.00)",
                        "Total 80.00"])]
    assert SI.row_sum_checks(SUM_SLOTS, rows, page, [1]) == []


@pytest.mark.xfail(
    strict=True,
    reason=("Run B item B6: a multi-page band with a correct subtotal on each "
            "page is compared as one grand sum and falsely flagged"),
)
def test_row_sum_accepts_per_page_subtotals_in_a_multi_page_band():
    rows = {"table": [
        {"Description": "A", "Amount": "40.00", "_page": 1},
        {"Description": "B", "Amount": "60.00", "_page": 1},
        {"Description": "C", "Amount": "30.00", "_page": 2},
        {"Description": "D", "Amount": "70.00", "_page": 2},
    ]}
    pages = [D.words(1, ["A 40.00", "B 60.00", "Subtotal 100.00"]),
             D.words(2, ["C 30.00", "D 70.00", "Subtotal 100.00"])]
    assert SI.row_sum_checks(SUM_SLOTS, rows, pages, [1, 2]) == []


@pytest.mark.parametrize("job", [15, 19, 21, 25])
def test_row_sum_adds_no_false_flag_to_any_frozen_owner_run(job):
    data = D.replay_job(job)["extracted_data"]
    reasons = data["diagnostics"]["coverage"]["reasons"]
    flags = data["validation"]["flagged_fields"]
    assert not [reason for reason in reasons if "row_sum_mismatch" in reason]
    assert not [flag for flag in flags if "extracted rows sum" in flag.get("reason", "")]


def test_row_sum_accepts_subtotal_tax_total_harness_case():
    rows = {"table": [{"Description": "A", "Amount": "40.00"},
                      {"Description": "B", "Amount": "60.00"}]}
    page = [D.words(1, ["A 40.00", "B 60.00", "Subtotal 100.00",
                        "Tax 8.00", "Total 108.00"])]
    assert SI.row_sum_checks(SUM_SLOTS, rows, page, [1]) == []


# B8: invented versus reworded template columns ------------------------------------

@pytest.mark.parametrize("header, printed, should_flag", [
    ("Variance", "Amount", True),
    ("Item Description", "Description", False),
])
def test_template_columns_distinguishes_invention_from_rewording(
        header, printed, should_flag):
    from slot_extractor import enumerate_slots

    grid = {"cells": {"0,0": {"value": "Date"},
                      "0,1": {"value": header},
                      "0,2": {"value": "Amount"}},
            "merges": {}, "colWidths": [], "repeatRows": []}
    table = enumerate_slots(grid)["tables"][0]
    row = {"Date": "01/01", header: "ITEM-A" if not should_flag else "40.00",
           "Amount": "40.00"}
    answer = {"fields": {}, "tables": {table["name"]: [{
        "cells": row,
        "source": f"01/01 ITEM-A 40.00", "page": 1,
    }]}}
    data = D.run_synthetic(
        lambda **_kwargs: D.model_response(json.loads(json.dumps(answer))),
        [[f"DATE {printed.upper()} AMOUNT", "01/01 ITEM-A 40.00"]], grid=grid)
    flags = [flag for flag in data["validation"]["flagged_fields"]
             if flag["ref"] == "template columns"]
    assert bool(flags) is should_flag
