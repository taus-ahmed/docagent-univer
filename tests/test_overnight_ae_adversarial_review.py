"""Adversarial review of the overnight A-E fixes.

All extraction calls use scripted answers and the production post-model seam.
There are no provider clients, remote files, or live model calls.  The few
real-document controls use the local corpus through ``tests.local_corpus``.

Strict xfails are review defects: a wrong value can survive without a warning,
or correct source data can be combined into the wrong record.  Each marker is
also registered in ``tests/KNOWN_FAILING.md``.
"""
from __future__ import annotations

import copy
import io
import json
import re
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

from tests import legend_check as LEGEND
from tests import overnight_helpers as H
from tests import test_overnight_b4 as B4
from tests import test_run_e_adversarial_review as RUN_E
from tests import test_run_f_adversarial_review as RUN_F
from tests.contract import run_a_driver as D
from tests.test_overnight_a1_a2 import PITT, pitt_answer, pitt_grid
from tests.test_overnight_a4 import (
    MAMMOTH,
    mammoth_fields,
    mammoth_grid,
    mammoth_rows,
)


ROOT = Path(__file__).resolve().parents[1]

A1_CHECKBOX_GAP = pytest.mark.xfail(
    strict=True,
    reason="A1 checkbox ambiguity -- an equidistant X is silently assigned to the first option",
)
A4_CAP_GAP = pytest.mark.xfail(
    strict=True,
    reason="A4 recovery cap -- an eligible lost page beyond the cap is silently omitted",
)
A6_FRAGMENT_GAP = pytest.mark.xfail(
    strict=True,
    reason="A6 fragment merge -- two real keyless rows with disjoint columns are merged",
)
B1_REANCHOR_GAP = pytest.mark.xfail(
    strict=True,
    reason="B1 grounding -- an invented quote relocates a wrong value from another row",
)
B2_NESTED_AMOUNT_GAP = pytest.mark.xfail(
    strict=True,
    reason="B2 placement -- an amount found only inside the wrong column bypasses placement",
)
B3_WIDGET_GAP = pytest.mark.xfail(
    strict=True,
    reason="B3 completeness -- one unmatched filled widget is silently omitted",
)
B3_TEXT_GAP = pytest.mark.xfail(
    strict=True,
    reason="B3 completeness -- one missed prose value beside its label is silently omitted",
)


def _word(text: str, x0: float, x1: float, top: float, page: int = 1) -> dict:
    return {
        "text": text,
        "x0": x0,
        "x1": x1,
        "top": top,
        "bottom": top + 10,
        "page": page,
    }


def _table_grid(headers, name="Rows", reserved=8):
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


def _run_geometry(
    page_lines,
    grid,
    responder,
    *,
    doc_type="other",
    widget_values=None,
    form_fields=None,
):
    """Run scripted answers through ``run_slot_extraction`` over exact geometry."""
    import llm_contract as C
    from slot_extractor import run_slot_extraction
    from text_layer import text_from_lines

    page_texts = [text_from_lines(lines) for lines in page_lines]
    calls = []

    def extract(**kwargs):
        calls.append(kwargs)
        answer = responder(kwargs, len(calls)) if callable(responder) else responder
        return D.model_response(copy.deepcopy(answer))

    with C.collect_attempts(fresh=True):
        result = run_slot_extraction(
            SimpleNamespace(llm=SimpleNamespace(extract=extract)),
            "offline-ae-adversarial.pdf",
            {"layout": grid},
            None,
            page_images=[],
            doc_text="\n\n".join(page_texts),
            doc_text_pages=page_texts,
            file_type="digital_pdf",
            default_doc_type=doc_type,
            start=0.0,
            page_lines=page_lines,
            page_origins={i + 1: "native" for i in range(len(page_lines))},
            page_numbers=list(range(1, len(page_lines) + 1)),
            widget_values=widget_values or {},
            form_fields=form_fields or {},
            unreadable=None,
        )[0]
    return result.extracted_data, calls


def _field_answer(grid, values):
    return {
        "fields": {
            H.field_id(grid, label): H.ans(value, source, page)
            for label, value, source, page in values
        },
        "tables": {},
    }


def _rows(data, grid, title="Rows"):
    return data.get(f"{H.table_name(grid, title)}_rows") or []


def _attention_text(data) -> str:
    return " ".join(H.reasons(data)).casefold()


# A1/A2 ---------------------------------------------------------------------


def test_control_a1_a2_real_w2_keeps_legitimate_repeats_and_box12_rows():
    """Real pitt W-2: legitimate repeats survive; foreign Box 14 does not."""
    grid = pitt_grid()
    data, _calls = H.run(PITT, grid, pitt_answer(grid), doc_type="w2")

    assert H.value(data, "Box 3 Social Security Wages") == "48736.35"
    assert H.value(data, "Box 5 Medicare Wages and Tips") == "48736.35"
    box12 = _rows(data, grid, "Box 12 Codes")
    assert [(r["Box 12 Code"], r["Box 12 Amount"]) for r in box12] == [
        ("E", "4107.00"),
        ("W", "1500.00"),
    ]
    assert H.value(data, "Box 11 Nonqualified Plans") == ""
    assert "box 14 has a second entry 52.00 x that has no slot" in H.flag_text(data)


@A1_CHECKBOX_GAP
def test_a1_equidistant_checkbox_x_is_not_silently_moved_to_the_first_option():
    grid = H.column_grid(["Box 13 Alpha", "Box 13 Beta"])
    # The X centre is 41: exactly one point from Alpha's right edge and Beta's
    # left edge.  Geometry has no owner, so review is required.
    lines = [[
        [_word("13", 0, 8, 0), _word("Alpha", 10, 40, 0), _word("Beta", 42, 70, 0)],
        [_word("X", 39, 43, 10)],
    ]]
    answer = _field_answer(grid, [
        ("Box 13 Beta", "X", "X", 1),
    ])
    data, _calls = _run_geometry(lines, grid, answer, doc_type="w2")

    assert H.value(data, "Box 13 Alpha") == ""
    assert H.value(data, "Box 13 Beta") == "X"
    assert any("ambig" in str(f.get("reason", "")).casefold() for f in H.flags(data))


# A3 ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,value,expected,fmt",
    [
        ("Box 1 Wages", "15250", 15250.0, "#,##0.00"),
        ("Hours", "12", 12.0, "#,##0"),
        ("Quantity", "40", 40.0, "#,##0"),
        ("Tax Year", "2026", 2026.0, "0"),
        ("Rate Percent", "12.5%", 0.125, "0.0%"),
        ("Account Number", "0012 3456-7", "0012 3456-7", None),
        ("Control Number", "123456", "123456", None),
        ("Amount", "(1,234.50)", -1234.5, "#,##0.00_);(#,##0.00)"),
        ("Amount", "-43", -43.0, "#,##0.00"),
    ],
)
def test_control_a3_types_identifiers_and_signed_money(label, value, expected, fmt):
    from app.services.excel_cells import cell_format, coerce_cell_value

    assert coerce_cell_value(value, label, ".") == expected
    assert cell_format(value, label, ".") == fmt


# A4 ------------------------------------------------------------------------


def test_control_a4_real_lost_page_recovers_in_order_without_header_or_duplicates():
    grid = mammoth_grid()
    name = H.table_name(grid, "Transactions")
    first = {"fields": mammoth_fields(grid), "tables": {name: mammoth_rows(1)}}
    recovered = {"fields": {}, "tables": {name: mammoth_rows(2)}}
    data, calls = H.run(
        MAMMOTH,
        grid,
        None,
        doc_type="bank_statement",
        answers=[first, recovered],
    )
    rows = data[f"{name}_rows"]
    assert len(rows) == 48
    assert [r["Date"] for r in rows][37:] == [r["cells"]["Date"] for r in mammoth_rows(2)]
    assert len({(r.get("Date"), r.get("Description"), r.get("_source")) for r in rows}) == 48
    recovery = [c for c in calls if "RECOVERY REQUEST" in str(c.get("prompt"))]
    assert len(recovery) == 1 and "page 2 of 2" in recovery[0]["prompt"]


def test_control_a4_a_truly_empty_page_does_not_trigger_recovery(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "PAGE_CALL_MIN_PAGES", 0)
    grid = _table_grid(["Date", "Description", "Amount"])
    name = H.table_name(grid, "Rows")
    page1 = D.words(1, ["Date Description Amount", "01/01/2026 Rent 100.00", "01/02/2026 Tax 20.00"])
    page2 = D.words(2, ["Notes only", "No transactions on this page"])
    answer = {"fields": {}, "tables": {name: [
        {"cells": {"Date": "01/01/2026", "Description": "Rent", "Amount": "100.00"},
         "source": "01/01/2026 Rent 100.00", "page": 1},
        {"cells": {"Date": "01/02/2026", "Description": "Tax", "Amount": "20.00"},
         "source": "01/02/2026 Tax 20.00", "page": 1},
    ]}}
    _data, calls = _run_geometry([page1, page2], grid, answer)
    assert not any("RECOVERY REQUEST" in str(c.get("prompt")) for c in calls)


@A4_CAP_GAP
def test_a4_recovery_cap_must_report_the_eligible_page_it_did_not_call(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "PAGE_CALL_MIN_PAGES", 0)
    grid = _table_grid(["Date", "Description", "Amount"], reserved=120)
    name = H.table_name(grid, "Rows")

    by_page = {}
    page_lines = []
    for page in range(1, 7):
        count = 100 if page == 1 else 2
        texts = (["Date Description Amount"] if page == 1 else []) + [
            f"{page:02d}/{row + 1:02d}/2026 P{page}R{row + 1} {page * 100 + row + 1}.00"
            for row in range(count)
        ]
        page_lines.append(D.words(page, texts))
        by_page[page] = [
            {"cells": {
                "Date": f"{page:02d}/{row + 1:02d}/2026",
                "Description": f"P{page}R{row + 1}",
                "Amount": f"{page * 100 + row + 1}.00",
            }, "source": texts[row + (1 if page == 1 else 0)], "page": page}
            for row in range(count)
        ]

    def answer(kwargs, _call):
        prompt = str(kwargs.get("prompt") or "")
        if "RECOVERY REQUEST" in prompt:
            page = int(re.search(r"page (\d+) of 6", prompt).group(1))
            return {"fields": {}, "tables": {name: by_page[page]}}
        return {"fields": {}, "tables": {name: by_page[1]}}

    data, calls = _run_geometry(page_lines, grid, answer, doc_type="bank_statement")
    rows = _rows(data, grid)
    recovery_pages = [
        int(re.search(r"page (\d+) of 6", str(c["prompt"])).group(1))
        for c in calls if "RECOVERY REQUEST" in str(c.get("prompt"))
    ]
    assert recovery_pages[:4] == [2, 3, 4, 5]
    has_page_6 = any(r.get("Description") == "P6R1" for r in rows)
    assert has_page_6 or "page 6" in _attention_text(data), (
        "page 6 must be recovered or kept visibly missing")


# A5 ------------------------------------------------------------------------


def test_control_a5_one_title_fills_and_two_titles_flag_instead_of_guessing():
    labels = ["Form Type"]
    single = H.column_grid(labels)
    empty = {"fields": {H.field_id(single, "Form Type"): H.ans("", "")}, "tables": {}}
    one, _ = H.run("1099/irs_1099int_mod3.pdf", single, empty, doc_type="1099")
    many, _ = H.run(
        "1099/irs6744_brokerage_1099DIV_MISC_INT_B.pdf",
        single,
        empty,
        doc_type="1099",
    )

    assert H.value(one, "Form Type") == "1099-INT"
    assert H.value(many, "Form Type") == ""
    why = H.flag_text(many)
    assert "1099-div" in why and "1099-int" in why


# A6 ------------------------------------------------------------------------


def test_control_a6_real_single_entity_fragments_merge_and_temperature_is_zero(monkeypatch):
    from tests.test_overnight_a1_a2 import STATE_LINE

    monkeypatch.setenv("EXTRACTION_TEMPERATURE", "0")
    grid = pitt_grid()
    fragments = [
        {"cells": {"State": "PA", "Employer State ID": "XXXX5369", "State Wages": "47808.35"},
         "source": STATE_LINE, "page": 1},
        {"cells": {"State Income Tax": "1467.72", "Local Wages": "47808.35"},
         "source": STATE_LINE, "page": 1},
        {"cells": {"Local Income Tax": "478.08", "Locality Name": "700102"},
         "source": STATE_LINE, "page": 1},
    ]
    data, calls = H.run(
        PITT,
        grid,
        pitt_answer(grid, state_rows=fragments),
        doc_type="w2",
    )
    rows = _rows(data, grid, "State and Local")
    assert len(rows) == 1 and rows[0]["Locality Name"] == "700102"
    assert calls and all(c.get("temperature") == 0.0 for c in calls)


@A6_FRAGMENT_GAP
def test_a6_two_real_rows_with_disjoint_cells_are_not_merged_into_one_entity():
    grid = _table_grid(["Account", "Debit", "Credit"])
    name = H.table_name(grid, "Rows")
    lines = D.words(1, [
        "Account Debit Credit",
        "Checking-A 100.00",
        "Savings-B 250.00",
    ])
    answer = {"fields": {}, "tables": {name: [
        {"cells": {"Account": "Checking-A", "Debit": "100.00", "Credit": ""},
         "source": "Checking-A 100.00", "page": 1},
        # A real second line whose key was missed.  Merging its credit into the
        # Checking row silently changes which account owns 250.00.
        {"cells": {"Account": "", "Debit": "", "Credit": "250.00"},
         "source": "Savings-B 250.00", "page": 1},
    ]}}
    data, _calls = _run_geometry([lines], grid, answer, doc_type="bank_statement")
    rows = _rows(data, grid)

    assert len(rows) == 2
    assert rows[0]["Credit"] == ""
    assert rows[1]["Credit"] == "250.00"


# B1 ------------------------------------------------------------------------


def test_control_b1_numbers_ground_as_whole_tokens_and_missing_values_stay_low():
    grid = H.column_grid(["Interest Income", "Penalty"])
    lines = D.words(1, [
        "ANNUAL INFORMATION RETURN FOR THE RECIPIENT KEEP THIS PAGE WITH YOUR TAX RECORDS",
        "Interest Income .......... 70.00",
        "Penalty 170.00",
    ])
    answer = _field_answer(grid, [
        ("Interest Income", "70.00", "Interest Income .......... 70.00", 1),
        ("Penalty", "999.00", "Penalty 999.00", 1),
    ])
    data, _calls = _run_geometry([lines], grid, answer, doc_type="1099")

    assert H.level(data, "Interest Income") == "high"
    assert H.level(data, "Penalty") == "low"
    from slot_extractor import verify_span
    assert not verify_span("70.00", "Penalty 170.00", 1, ["Penalty 170.00"])[0]


@B1_REANCHOR_GAP
def test_b1_wrong_value_on_another_row_is_not_grounded_via_an_invented_quote():
    grid = H.column_grid(["Opening Balance"])
    lines = D.words(1, [
        "MONTHLY ACCOUNT STATEMENT PLEASE RETAIN THIS PAGE WITH YOUR PERMANENT FINANCIAL RECORDS",
        "Opening Balance 100.00",
        "Closing Balance 170.00",
    ])
    answer = _field_answer(grid, [
        ("Opening Balance", "170.00", "Opening Balance 170.00", 1),
    ])
    data, _calls = _run_geometry([lines], grid, answer, doc_type="bank_statement")

    assert H.level(data, "Opening Balance") == "low"
    assert "Opening Balance" in H.flagged_refs(data)


# B2 ------------------------------------------------------------------------


def _placement_page():
    return [[
        [_word("Description", 0, 65, 0), _word("Amount", 200, 240, 0)],
        [_word("Service", 0, 42, 20), _word("70.00", 50, 80, 20)],
        [_word("Hosting", 0, 42, 40), _word("90.00", 205, 235, 40)],
    ]]


def test_control_b2_value_really_under_another_column_is_flagged():
    grid = _table_grid(["Description", "Amount"])
    name = H.table_name(grid, "Rows")
    answer = {"fields": {}, "tables": {name: [
        {"cells": {"Description": "Service", "Amount": "70.00"},
         "source": "Service 70.00", "page": 1},
        {"cells": {"Description": "Hosting", "Amount": "90.00"},
         "source": "Hosting 90.00", "page": 1},
    ]}}
    data, _calls = _run_geometry(_placement_page(), grid, answer, doc_type="invoice")
    flags = [f for f in H.flags(data) if "column" in str(f.get("reason", ""))]
    assert any(f.get("ref") == f"{name}[0].Amount" for f in flags)


@B2_NESTED_AMOUNT_GAP
def test_b2_amount_found_only_inside_description_still_gets_a_placement_flag():
    grid = _table_grid(["Description", "Amount"])
    name = H.table_name(grid, "Rows")
    answer = {"fields": {}, "tables": {name: [
        {"cells": {"Description": "Service 70.00", "Amount": "70.00"},
         "source": "Service 70.00", "page": 1},
        {"cells": {"Description": "Hosting", "Amount": "90.00"},
         "source": "Hosting 90.00", "page": 1},
    ]}}
    data, _calls = _run_geometry(_placement_page(), grid, answer, doc_type="invoice")
    flags = [f for f in H.flags(data) if "column" in str(f.get("reason", ""))]
    assert any(f.get("ref") == f"{name}[0].Amount" for f in flags)


# B3 ------------------------------------------------------------------------


def test_control_b3_real_fillable_blank_boxes_do_not_create_false_reasons():
    grid = D.template_grid("F1099_INT_DIV")
    answer = {
        "fields": {},
        "tables": {t["name"]: [] for t in H.slots(grid)["tables"]},
    }
    data, calls = H.run(
        "1099/irs_1099int_mod3.pdf",
        grid,
        answer,
        doc_type="1099",
    )
    assert H.reasons(data) == []
    assert data["document_state"] == "READY"
    assert len(calls) == 1


@B3_WIDGET_GAP
def test_b3_one_unmatched_filled_widget_is_reported_even_below_the_batch_threshold():
    grid = H.column_grid(["Policy Number"])
    lines = D.words(1, [
        "EMPLOYEE BENEFITS ENROLMENT FORM COMPLETE ALL APPLICABLE FIELDS AND RETAIN A COPY",
        "Policy Number",
        "Client Reference ZX-9",
    ])
    answer = {"fields": {H.field_id(grid, "Policy Number"): H.ans("", "")}, "tables": {}}
    entry = {
        "label": "Client Reference",
        "extra": "client_ref",
        "value": "ZX-9",
        "box": None,
        "role": "whole",
        "kind": "text",
        "page": 1,
    }
    data, _calls = _run_geometry(
        [lines],
        grid,
        answer,
        doc_type="form",
        widget_values={1: ["ZX-9"]},
        form_fields={1: [entry]},
    )
    assert "zx-9" in _attention_text(data)
    assert data["document_state"] != "READY"


@B3_TEXT_GAP
def test_b3_one_missed_text_value_beside_its_label_is_reported():
    grid = H.column_grid(["Employee Name"])
    lines = D.words(1, [
        "EMPLOYEE BENEFITS ENROLMENT FORM COMPLETE ALL APPLICABLE FIELDS AND RETAIN A COPY",
        "Employee Name Alice Rivera",
    ])
    answer = {"fields": {H.field_id(grid, "Employee Name"): H.ans("", "")}, "tables": {}}
    data, _calls = _run_geometry([lines], grid, answer, doc_type="form")

    assert "alice rivera" in _attention_text(data)
    assert data["document_state"] != "READY"


# B4 ------------------------------------------------------------------------


def test_control_b4_legend_matches_multiple_blocks_and_an_edited_cell():
    grid, data = B4._pitt_with_empty_flags()
    edited = copy.deepcopy(data)
    ref = next(f["ref"] for f in H.slots(grid)["fields"]
               if f["row_label"] == "Box 1 Wages Tips Other Compensation")
    edited["extracted_fields"][ref] = "44630.00"
    edited["extracted_data"]["Box 1 Wages Tips Other Compensation"] = {
        "value": "44630.00", "confidence": "edited", "ref": ref,
    }
    edited["validation"]["confidence_map"][ref] = "edited"
    edited["field_provenance"].setdefault(ref, {}).update({
        "edited": {"old": "", "by": "reviewer", "at": "2026-11-20T00:00:00Z"},
        "review_required": False,
        "review_reasons": [],
    })
    edited["validation"]["flagged_fields"] = [
        f for f in edited["validation"]["flagged_fields"]
        if f.get("ref") != "Box 1 Wages Tips Other Compensation"
    ]
    wb = B4._workbook([("first.pdf", data), ("edited.pdf", edited)], grid)
    assert LEGEND.check(wb) == []


# C and D -------------------------------------------------------------------


def test_control_c_f_rules_keep_legitimate_values_and_reject_cross_column_provenance():
    RUN_F.test_f2_real_payslip_figure_in_a_sentence_is_data(
        "Net Pay",
        "$1,842.73",
        "Your net pay for this period is $1,842.73 and it will be deposited to your account today.",
    )
    RUN_F.test_f4_value_before_its_label_is_real_data("Qty", "5", "5 Qty  Stainless bolts")
    RUN_F.test_f5_repeated_total_is_disambiguated_by_its_template_statement_column()
    RUN_F.test_e9_payee_and_description_may_legitimately_be_identical()
    RUN_F.test_e11_trailing_minus_grounds_and_exports_as_a_negative_amount()
    RUN_F.test_e12_address_parts_in_a_different_normal_order_still_ground()
    RUN_F.test_e12_provenance_helper_does_not_self_certify_a_cross_column_address()


def test_control_d_template_structure_rules_and_warning_inventory():
    numbered = RUN_E._grid({
        (0, 0): "Name", (0, 2): "Approver 2", (1, 0): "Address",
    })
    note = RUN_E._grid({
        (0, 0): "Date", (0, 1): "Description", (0, 2): "Amount",
        (1, 4): "Total amounts shown in USD", (5, 0): "Total",
    })
    two_tables = RUN_E._grid({
        (0, 0): "Code", (0, 1): "Amount",
        (0, 3): "Date", (0, 4): "Description", (0, 5): "Charge",
        (4, 0): "Left total", (4, 3): "Right total",
    })
    assert RUN_E._fields(numbered) == [
        ("B1", "Name"), ("B2", "Address"), ("D1", "Approver 2"),
    ]
    assert RUN_E._fields(note) == [("B6", "Total")]
    assert RUN_E._band_headers(two_tables) == [
        ("Code", "Amount"), ("Date", "Description", "Charge"),
    ]

    from template_shape import template_warnings
    from tests.template_layout.helpers import FIXTURES, workbook_to_grid

    warnings = template_warnings(workbook_to_grid(FIXTURES / "F10.xlsx"))
    assert len(warnings) == 2 and all("formula" in w.casefold() for w in warnings)
    truth = json.loads((ROOT / "tests/templates/T9.truth.json").read_text(encoding="utf-8"))
    assert "Item" in json.dumps(truth) and "Debit" in json.dumps(truth) and "Credit" in json.dumps(truth)


# E -------------------------------------------------------------------------


def test_control_e_every_review_action_refreshes_results_and_failed_saves_are_visible():
    refresh = (ROOT / "frontend/lib/reviewRefresh.ts").read_text(encoding="utf-8")
    panel = (ROOT / "frontend/components/extract/ReviewPanel.tsx").read_text(encoding="utf-8")
    grid = (ROOT / "frontend/components/extract/ResultsGrid.tsx").read_text(encoding="utf-8")
    page = (ROOT / "frontend/app/extract/page.tsx").read_text(encoding="utf-8")

    for key in ('["review", jobId]', '["job-results", jobId]', '["job", jobId]', '["jobs"]'):
        assert key in refresh
    assert 'queryKey: ["job-results", activeJobId]' in page
    # accept/correct/empty use dispose -> changed; add row and edit do too.
    assert panel.count("changed();") >= 3
    assert "onChanged();" in panel
    assert "Not saved:" in panel and "Not added:" in panel
    assert "refreshAfterReview(qc, jobId)" in grid
    assert "toast.error" in grid and "Save failed" in grid
    # E2: page navigation exposes previous/next and moves selection with page.
    assert "pageNav(doc.pages, page, meta?.page_count)" in panel
    assert "firstValueOn(values, p)" in panel


def test_control_e_server_results_and_export_agree_after_review_actions(
    client, db, review_case_factory
):
    """Server half of E1 for accept, confirm-empty, and add-row."""
    from tests.test_review_flow_spec import _export, _review

    accepted = review_case_factory(open_refs=("B2",), flag_empty=False, table_open=False)
    r = _review(client, accepted, {"values": [
        {"ref": "B2", "disposition": "accepted_as_is"},
    ]})
    assert r.status_code == 200, r.text
    got = client.get(f"/api/jobs/{accepted.job_id}/results", headers=accepted.headers).json()[0]
    assert got["extracted_data"]["field_provenance"]["B2"]["reviewed"]["disposition"] == "accepted_as_is"
    assert "Machine value" in _workbook_values(_export(client, accepted).content)

    emptied = review_case_factory(open_refs=(), flag_empty=True, table_open=False)
    r = _review(client, emptied, {"values": [
        {"ref": "B3", "disposition": "confirmed_empty"},
    ]})
    assert r.status_code == 200, r.text
    got = client.get(f"/api/jobs/{emptied.job_id}/results", headers=emptied.headers).json()[0]
    assert got["extracted_data"]["extracted_fields"]["B3"] == ""
    assert "_DRAFT" not in _export(client, emptied).headers["content-disposition"]

    added = review_case_factory(
        open_refs=(), flag_empty=False, table_open=False,
        attention=[{"id": "missing-row", "text": "row missing", "disposition": None}],
    )
    r = client.post(
        f"/api/jobs/{added.job_id}/docs/{added.doc_id}/rows/items",
        headers=added.headers,
        json={"values": {"Description": "Added row", "Amount": "5.00"},
              "attention_id": "missing-row"},
    )
    assert r.status_code == 201, r.text
    got = client.get(f"/api/jobs/{added.job_id}/results", headers=added.headers).json()[0]
    assert any(row.get("Description") == "Added row"
               for row in got["extracted_data"]["items_rows"])
    assert "Added row" in _workbook_values(_export(client, added).content)


def _workbook_values(content: bytes) -> list:
    wb = openpyxl.load_workbook(io.BytesIO(content))
    return [cell.value for ws in wb.worksheets for row in ws.iter_rows() for cell in row]


# Import HTTP fixtures only after helpers are defined; these names make the
# local database/client fixtures available to the two E controls above.
from tests.http.conftest import (  # noqa: E402,F401
    _db_url,
    _scratch_storage,
    app,
    auth,
    client,
    db,
    users,
)
from tests.test_review_flow_spec import review_case_factory  # noqa: E402,F401
