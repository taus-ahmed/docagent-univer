"""Adversarial review of the Run N extraction fixes.

Every extraction is driven by a scripted model answer through
``run_slot_extraction``.  No provider client, remote service, or live model is
used.  Strict xfails are application defects, registered in
``tests/KNOWN_FAILING.md``.
"""
from __future__ import annotations

import re

import pytest

from tests import overnight_helpers as H
from tests.contract import run_a_driver as D
from tests.test_overnight_ae_adversarial_review import (
    _field_answer,
    _run_geometry,
    _word,
)


N2_WRAPPED_LABEL_GAP = pytest.mark.xfail(
    strict=True,
    reason=(
        "Run N review N2: a wrapped row label loses row identity and a wrong "
        "duplicate amount is silently re-anchored"
    ),
)
N2_NEIGHBOUR_DETAIL_GAP = pytest.mark.xfail(
    strict=True,
    reason=(
        "Run N review N2: a correct value on its row's continuation line is "
        "wrongly rejected when that line also carries companion text"
    ),
)
N4_INSIDE_EDGE_GAP = pytest.mark.xfail(
    strict=True,
    reason=(
        "Run N review N4: an X whose centre is inside an option is wrongly "
        "flagged tied when the next option is exactly 0.5 pt away"
    ),
)
N5_REPEATED_KEY_GAP = pytest.mark.xfail(
    strict=True,
    reason=(
        "Run N review N5: two real records sharing a state or account key are "
        "wrongly merged when the second row's key cell was missed"
    ),
)
N6_PARTIAL_PAGE_GAP = pytest.mark.xfail(
    strict=True,
    reason=(
        "Run N review N6: partially extracted pages beyond the recovery cap "
        "are silently treated as present and their missing rows are not named"
    ),
)
N7_METADATA_WIDGET_GAP = pytest.mark.xfail(
    strict=True,
    reason=(
        "Run N review N7: a legitimately unmapped form-metadata widget creates "
        "a false missing-value attention reason"
    ),
)


def _table_grid(headers, name="Rows", reserved=140):
    cells = {f"0,{i}": h for i, h in enumerate(headers)}
    return H.grid(cells, [{
        "type": "table",
        "name": name,
        "orientation": "rows",
        "r1": 0,
        "c1": 0,
        "r2": reserved,
        "c2": len(headers) - 1,
    }])


def _rows(data, grid, title="Rows"):
    return data.get(f"{H.table_name(grid, title)}_rows") or []


def _attention_text(data):
    return " ".join(H.reasons(data)).casefold()


# N2 -- grounding belongs to the row named by the quote ---------------------


def test_n2_control_an_unwrapped_label_rejects_an_amount_from_the_next_row():
    grid = H.column_grid(["Opening Balance"])
    lines = D.words(1, [
        "MONTHLY ACCOUNT STATEMENT RETAIN THIS PAGE WITH YOUR FINANCIAL RECORDS",
        "Opening Balance 100.00",
        "Closing Balance 170.00",
    ])
    answer = _field_answer(grid, [
        ("Opening Balance", "170.00", "Opening Balance 170.00", 1),
    ])

    data, _calls = _run_geometry([lines], grid, answer, doc_type="bank_statement")

    assert H.level(data, "Opening Balance") == "low"
    assert "Opening Balance" in H.flagged_refs(data)


def test_n2_control_the_same_amount_on_two_rows_grounds_on_the_named_row():
    grid = H.column_grid(["Opening Balance"])
    lines = D.words(1, [
        "MONTHLY ACCOUNT STATEMENT RETAIN THIS PAGE WITH YOUR FINANCIAL RECORDS",
        "Opening Balance 170.00",
        "Closing Balance 170.00",
    ])
    answer = _field_answer(grid, [
        ("Opening Balance", "170.00", "Opening Balance 170.00", 1),
    ])

    data, _calls = _run_geometry([lines], grid, answer, doc_type="bank_statement")

    assert H.level(data, "Opening Balance") == "high"
    assert "Opening Balance" not in H.flagged_refs(data)


@N2_WRAPPED_LABEL_GAP
def test_n2_wrapped_label_does_not_let_a_wrong_duplicate_amount_reanchor():
    grid = H.column_grid(["Opening Balance"])
    lines = D.words(1, [
        "MONTHLY ACCOUNT STATEMENT RETAIN THIS PAGE WITH YOUR FINANCIAL RECORDS",
        "Opening",
        "Balance 100.00",
        "Closing",
        "Balance 170.00",
    ])
    answer = _field_answer(grid, [
        ("Opening Balance", "170.00", "Opening Balance 170.00", 1),
    ])

    data, _calls = _run_geometry([lines], grid, answer, doc_type="bank_statement")

    assert H.level(data, "Opening Balance") == "low"
    assert "Opening Balance" in H.flagged_refs(data)


def test_n2_control_a_complete_multiline_quote_keeps_its_correct_value():
    grid = H.column_grid(["Purpose"])
    lines = D.words(1, [
        "EXPENSE REPORT RETAIN THIS PAGE WITH YOUR FINANCIAL RECORDS",
        "Purpose",
        "Supplier site visit Pacific Steel Code A-17",
    ])
    answer = _field_answer(grid, [
        (
            "Purpose",
            "Supplier site visit Pacific Steel",
            "Purpose Supplier site visit Pacific Steel Code A-17",
            1,
        ),
    ])

    data, _calls = _run_geometry([lines], grid, answer, doc_type="expense_report")

    assert H.level(data, "Purpose") == "high"
    assert "Purpose" not in H.flagged_refs(data)


@N2_NEIGHBOUR_DETAIL_GAP
def test_n2_correct_neighbouring_value_survives_unquoted_companion_text():
    grid = H.column_grid(["Purpose"])
    lines = D.words(1, [
        "EXPENSE REPORT RETAIN THIS PAGE WITH YOUR FINANCIAL RECORDS",
        "Purpose",
        "Supplier site visit Pacific Steel Code A-17",
    ])
    # The source is a faithful field-level excerpt.  The continuation line's
    # trailing Code belongs to a neighbouring field and is not part of Purpose.
    answer = _field_answer(grid, [
        (
            "Purpose",
            "Supplier site visit Pacific Steel",
            "Purpose Supplier site visit Pacific Steel",
            1,
        ),
    ])

    data, _calls = _run_geometry([lines], grid, answer, doc_type="expense_report")

    assert H.level(data, "Purpose") == "high"
    assert "Purpose" not in H.flagged_refs(data)


# N3 -- a figure is placed by its own position ------------------------------


def test_n3_control_a_misplaced_amount_inside_description_is_flagged():
    grid = _table_grid(["Description", "Amount"])
    name = H.table_name(grid, "Rows")
    page = [[
        [_word("Description", 0, 65, 0), _word("Amount", 200, 240, 0)],
        [_word("Service", 0, 42, 20), _word("70.00", 50, 80, 20)],
        [_word("Hosting", 0, 42, 40), _word("90.00", 205, 235, 40)],
    ]]
    answer = {"fields": {}, "tables": {name: [
        {
            "cells": {"Description": "Service 70.00", "Amount": "70.00"},
            "source": "Service 70.00",
            "page": 1,
        },
        {
            "cells": {"Description": "Hosting", "Amount": "90.00"},
            "source": "Hosting 90.00",
            "page": 1,
        },
    ]}}

    data, _calls = _run_geometry(page, grid, answer, doc_type="invoice")
    flags = [f for f in H.flags(data) if "column" in str(f.get("reason", ""))]

    assert any(f.get("ref") == f"{name}[0].Amount" for f in flags)
    assert not any(f.get("ref") == f"{name}[1].Amount" for f in flags)


# N4 -- checkbox ownership at the 0.5 point tolerance -----------------------


def _checkbox_result(beta_x0):
    grid = H.column_grid(["Box 13 Alpha", "Box 13 Beta"])
    lines = [[
        [
            _word("13", 0, 8, 0),
            _word("Alpha", 10, 40, 0),
            _word("Beta", beta_x0, 70, 0),
        ],
        [_word("X", 39, 41, 10)],  # centre 40: on Alpha's right edge
    ]]
    answer = _field_answer(grid, [("Box 13 Alpha", "X", "X", 1)])
    data, _calls = _run_geometry(lines, grid, answer, doc_type="w2")
    return data


def test_n4_control_just_outside_the_tolerance_belongs_to_the_spanned_option():
    data = _checkbox_result(40.501)

    assert H.value(data, "Box 13 Alpha") == "X"
    assert H.value(data, "Box 13 Beta") == ""
    assert "ambig" not in H.flag_text(data)


@N4_INSIDE_EDGE_GAP
def test_n4_an_x_inside_alpha_is_not_a_tie_at_the_exact_tolerance_edge():
    data = _checkbox_result(40.5)

    assert H.value(data, "Box 13 Alpha") == "X"
    assert H.value(data, "Box 13 Beta") == ""
    assert "ambig" not in H.flag_text(data)


# N5 -- fragment rows may merge only within one record ----------------------


def test_n5_control_distinct_quotes_without_the_first_key_do_not_merge():
    grid = _table_grid(["Account", "Debit", "Credit"])
    name = H.table_name(grid, "Rows")
    lines = D.words(1, [
        "Account Debit Credit",
        "Checking-A 100.00",
        "Savings-B 250.00",
    ])
    answer = {"fields": {}, "tables": {name: [
        {
            "cells": {"Account": "Checking-A", "Debit": "100.00", "Credit": ""},
            "source": "Checking-A 100.00",
            "page": 1,
        },
        {
            "cells": {"Account": "", "Debit": "", "Credit": "250.00"},
            "source": "Savings-B 250.00",
            "page": 1,
        },
    ]}}

    data, _calls = _run_geometry([lines], grid, answer, doc_type="bank_statement")

    assert len(_rows(data, grid)) == 2


@pytest.mark.parametrize(
    ("headers", "printed", "first_cells", "second_cells"),
    [
        (
            ["Account", "Debit", "Credit"],
            ["Household 100.00", "Household 250.00"],
            {"Account": "Household", "Debit": "100.00", "Credit": ""},
            {"Account": "", "Debit": "", "Credit": "250.00"},
        ),
        (
            ["State", "Employer ID", "Wages", "Tax"],
            ["PA ID-A 100.00", "PA ID-B 20.00"],
            {"State": "PA", "Employer ID": "ID-A", "Wages": "100.00", "Tax": ""},
            {"State": "", "Employer ID": "", "Wages": "", "Tax": "20.00"},
        ),
    ],
    ids=["shared-account-label", "shared-state"],
)
@N5_REPEATED_KEY_GAP
def test_n5_repeated_key_text_does_not_merge_two_real_records(
    headers, printed, first_cells, second_cells
):
    grid = _table_grid(headers)
    name = H.table_name(grid, "Rows")
    lines = D.words(1, [" ".join(headers), *printed])
    answer = {"fields": {}, "tables": {name: [
        {"cells": first_cells, "source": printed[0], "page": 1},
        {"cells": second_cells, "source": printed[1], "page": 1},
    ]}}

    data, _calls = _run_geometry([lines], grid, answer, doc_type="bank_statement")
    rows = _rows(data, grid)

    assert len(rows) == 2
    assert any("250.00" in row.values() or "20.00" in row.values() for row in rows)


# N6 -- every eligible page beyond the recovery cap stays visible -----------


def _many_page_case(monkeypatch, *, partial_beyond_cap):
    from config import settings
    import llm_contract as C

    monkeypatch.setattr(settings, "PAGE_CALL_MIN_PAGES", 0)
    real_setting = C.setting
    monkeypatch.setattr(
        C,
        "setting",
        lambda name, default: (
            1 if name == "PAGE_RECOVERY_MAX_CALLS" else real_setting(name, default)
        ),
    )
    grid = _table_grid(["Date", "Description", "Amount"], reserved=180)
    name = H.table_name(grid, "Rows")
    page_lines = []
    by_page = {}
    for page in range(1, 6):
        count = 100 if page == 1 else 4
        body = []
        rows = []
        for index in range(count):
            date = f"{(index // 28) + 1:02d}/{(index % 28) + 1:02d}/2026"
            desc = f"P{page}R{index + 1}"
            amount = f"{page * 1000 + index + 1}.00"
            source = f"{date} {desc} {amount}"
            body.append(source)
            rows.append({
                "cells": {"Date": date, "Description": desc, "Amount": amount},
                "source": source,
                "page": page,
            })
        texts = (["Date Description Amount"] if page == 1 else []) + body
        page_lines.append(D.words(page, texts))
        by_page[page] = rows

    initial = list(by_page[1])
    if partial_beyond_cap:
        initial.extend(by_page[page][0] for page in range(2, 6))

    def responder(kwargs, _call):
        prompt = str(kwargs.get("prompt") or "")
        if "RECOVERY REQUEST" in prompt:
            page = int(re.search(r"page (\d+) of 5", prompt).group(1))
            return {"fields": {}, "tables": {name: by_page[page]}}
        return {"fields": {}, "tables": {name: initial}}

    data, calls = _run_geometry(
        page_lines,
        grid,
        responder,
        doc_type="bank_statement",
    )
    return data, calls


def test_n6_control_names_every_wholly_missing_page_beyond_the_cap(monkeypatch):
    data, calls = _many_page_case(monkeypatch, partial_beyond_cap=False)
    attention = _attention_text(data)
    recovery = [c for c in calls if "RECOVERY REQUEST" in str(c.get("prompt"))]

    assert len(recovery) == 1
    for page in (3, 4, 5):
        assert f"page {page}" in attention
    assert data["document_state"] == "NEEDS_ATTENTION"


def test_n6_names_partially_missing_pages_beyond_the_cap(monkeypatch):
    data, calls = _many_page_case(monkeypatch, partial_beyond_cap=True)
    attention = _attention_text(data)
    recovery = [c for c in calls if "RECOVERY REQUEST" in str(c.get("prompt"))]

    assert len(recovery) == 1
    for page in (3, 4, 5):
        assert f"page {page}" in attention
    assert data["document_state"] == "NEEDS_ATTENTION"


# N7 -- unplaced widgets and word values without metadata noise -------------


def _entry(label, value):
    return {
        "label": label,
        "extra": "",
        "value": value,
        "box": None,
        "role": "whole",
        "kind": "text",
        "page": 1,
    }


def _form_with_unmapped_widget(label, value):
    grid = H.column_grid(["Employee Name"])
    lines = D.words(1, [
        "EMPLOYEE ENROLMENT FORM COMPLETE APPLICABLE FIELDS AND RETAIN A COPY",
        "Employee Name Alice Rivera",
        f"{label} {value}",
    ])
    entries = [_entry("Employee Name", "Alice Rivera"), _entry(label, value)]
    answer = {"fields": {
        H.field_id(grid, "Employee Name"): H.ans("", ""),
    }, "tables": {}}
    return _run_geometry(
        [lines],
        grid,
        answer,
        doc_type="form",
        widget_values={1: ["Alice Rivera", value]},
        form_fields={1: entries},
    )[0]


def test_n7_control_extra_address_widget_is_quiet_when_the_party_is_captured():
    data = _form_with_unmapped_widget("Address Line 2", "Suite Five")

    assert H.value(data, "Employee Name") == "Alice Rivera"
    assert "suite five" not in _attention_text(data)
    assert data["document_state"] == "READY"


@N7_METADATA_WIDGET_GAP
def test_n7_legitimately_unmapped_form_metadata_does_not_create_attention():
    data = _form_with_unmapped_widget("PDF Revision", "Rev C")

    assert H.value(data, "Employee Name") == "Alice Rivera"
    assert "rev c" not in _attention_text(data)
    assert data["document_state"] == "READY"


def test_n7_control_an_unmapped_business_widget_is_still_reported():
    data = _form_with_unmapped_widget("Client Reference", "ZX-NINE")

    assert "zx-nine" in _attention_text(data)
    assert data["document_state"] == "NEEDS_ATTENTION"


def test_n7_control_a_word_value_beside_an_empty_slot_is_reported():
    grid = H.column_grid(["Employee Name"])
    lines = D.words(1, [
        "EMPLOYEE ENROLMENT FORM COMPLETE APPLICABLE FIELDS AND RETAIN A COPY",
        "Employee Name Alice Rivera",
    ])
    answer = {"fields": {
        H.field_id(grid, "Employee Name"): H.ans("", ""),
    }, "tables": {}}

    data, _calls = _run_geometry([lines], grid, answer, doc_type="form")

    assert "alice rivera" in _attention_text(data)
    assert data["document_state"] == "NEEDS_ATTENTION"
