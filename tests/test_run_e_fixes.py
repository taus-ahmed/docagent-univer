"""Run E: pins for the review fixes that the strict xfails alone do not cover.

Offline only: editor grids, stored results and synthetic page lines.
"""
from __future__ import annotations

import json

from tests.harness import bootstrap as bs

bs.bootstrap()


def _grid(values, merges=None):
    return {"cells": {f"{r},{c}": {"value": v} for (r, c), v in values.items()},
            "merges": merges or {}, "colWidths": [], "repeatRows": []}


# ---------------------------------------------------------------------------
# E0: can the application itself write `Total | 15` as a band row above the
# Total slot? Not through extraction: `split_duplicate_totals` drops that row
# before the result is stored. Only a human edit or a job stored before Run C
# can hand the writer such a row, which is why the reader must expose it.

DUPLICATE_TOTAL_GRID = _grid({
    (0, 0): "INVOICE",
    (2, 0): "Description", (2, 1): "Amount",
    (6, 0): "Total",
})


def test_e0_extraction_drops_a_band_row_equal_to_its_total_slot():
    from slot_extractor import enumerate_slots
    from total_row_validators import split_duplicate_totals

    slots = enumerate_slots(DUPLICATE_TOTAL_GRID)
    table = slots["tables"][0]
    total_ref = next(f["ref"] for f in slots["fields"] if f["row_label"] == "Total")
    rows = [{"Description": "Widget", "Amount": "15.00"},
            {"Description": "Total", "Amount": "15.00"}]
    kept, dropped = split_duplicate_totals(
        table, rows, slots["tables"], slots["fields"], {total_ref: "15.00"})
    assert [r["Description"] for r in kept] == ["Widget"]
    assert [r["Description"] for r in dropped] == ["Total"]


def test_e4_a_merge_inside_a_band_is_kept_on_every_written_row():
    from tests.test_run_c_adversarial import MERGED_BAND, document, round_trip, stored
    from slot_extractor import enumerate_slots

    table = enumerate_slots(MERGED_BAND)["tables"][0]["name"]
    rows = [{"Item": f"W{i}", "Amount": "1.00"} for i in range(3)]
    result, _ = stored(MERGED_BAND, fields={"Total": "3.00"}, rows={table: rows})
    sheet = round_trip([document(result)], MERGED_BAND)["Results"]
    merged = {str(item) for item in sheet.merged_cells.ranges}
    assert {"B4:C4", "B5:C5", "B6:C6"} <= merged
    assert [sheet.cell(r, 2).value for r in (4, 5, 6)] == [1.0, 1.0, 1.0]


def _fields(grid):
    from template_shape import compute_shape
    return sorted((f["ref"], f["row_label"])
                  for f in compute_shape(grid, log=lambda _m: None)["field_slots"])


def test_e7_a_blank_corner_matrix_keeps_both_value_columns():
    grid = _grid({(0, 1): "2024", (0, 2): "2023",
                  (1, 0): "Revenue", (2, 0): "Expenses"})
    assert _fields(grid) == [("B2", "Revenue"), ("B3", "Expenses"),
                             ("C2", "Revenue"), ("C3", "Expenses")]


def test_e7_a_form_row_of_pairs_over_one_label_is_not_a_matrix():
    grid = _grid({(0, 0): "Name", (0, 2): "Date", (1, 0): "Address"})
    assert _fields(grid) == [("B1", "Name"), ("B2", "Address"), ("D1", "Date")]


def test_e7_a_two_level_header_still_inherits_its_vertical_merge():
    from template_shape import compute_shape
    grid = _grid({(0, 0): "Item", (0, 1): "Amount", (1, 1): "Debit", (1, 2): "Credit"},
                 merges={"0,0": {"rows": 2, "cols": 1}, "0,1": {"rows": 1, "cols": 2}})
    bands = compute_shape(grid, log=lambda _m: None)["repeat_bands"]
    assert [[c["header"] for c in b["columns"]] for b in bands] == [
        ["Item", "Debit", "Credit"]]


def test_e7_tbd_in_a_slot_cell_stays_a_placeholder_and_is_never_exported():
    import contextlib
    import io
    import json
    import openpyxl
    from types import SimpleNamespace
    from slot_extractor import enumerate_slots
    from app.api.routes.extract import _write_slot_excel

    grid = _grid({(0, 0): "TBD", (1, 0): "Date", (1, 1): "TBD"})
    assert _fields(grid) == [("B1", "TBD"), ("B2", "Date")]
    slots = enumerate_slots(grid)
    ed = {"template_type": "slot", "extracted_fields": {},
          "slot_map": {"fields": slots["fields"], "tables": []},
          "validation": {"confidence_map": {}, "flagged_fields": []}}
    payload = json.dumps(ed)
    doc = SimpleNamespace(filename="x.pdf", get_extracted_data=lambda: json.loads(payload))
    wb = openpyxl.Workbook()
    with contextlib.redirect_stdout(io.StringIO()):
        _write_slot_excel(wb.active, [doc], grid, grid["cells"], openpyxl)
    ws = wb.active
    assert ws["A1"].value == "TBD"          # the label is written
    assert ws["B2"].value is None           # the placeholder is not


# ---------------------------------------------------------------------------
# E9: a column filled by copying another column of the same row.

_BANK_LINES = [
    ("09/02/2026", "ACH DEBIT — BLUE RIVER WHOLESALE INV 8841", "1,254.00", "", "16,986.12"),
    ("09/03/2026", "ACH CREDIT — MAPLE & MAIN LLC PAYMENT", "", "4,980.00", "21,966.12"),
    ("09/05/2026", "POS PURCHASE — HOME SUPPLY #2214", "320.45", "", "21,645.67"),
]


def _bank_answer(parsed, memo):
    import copy
    answer = copy.deepcopy(parsed)
    rows = []
    for date, desc, wd, dep, bal in _BANK_LINES:
        cells = {"Date": date, "Description": desc, "Check Number": "",
                 "Withdrawal": wd, "Deposit": dep, "Running Balance": bal,
                 "GL Account": "", "Memo": desc if memo else ""}
        source = " ".join(x for x in (date, desc, wd, dep, bal) if x)
        rows.append({"cells": cells, "source": source, "page": 1})
    answer["tables"] = {"table": rows}
    return answer


def _replay(job, answer):
    import contextlib
    import io
    from tests.contract.run_a_driver import replay_job
    with contextlib.redirect_stdout(io.StringIO()):
        return replay_job(job, lambda _n, _kw, parsed: answer(parsed))


def test_e9_a_memo_copied_from_the_description_is_cleared_and_said():
    out = _replay(15, lambda parsed: _bank_answer(parsed, memo=True))
    ed = out["extracted_data"]
    rows = ed["table_rows"]
    assert [r["Description"] for r in rows] == [d for _x, d, *_r in _BANK_LINES]
    assert [r["Memo"] for r in rows] == ["", "", ""]
    flags = [f for f in ed["validation"]["flagged_fields"] if f["ref"] == "table[Memo]"]
    assert len(flags) == 1 and "'Description'" in flags[0]["reason"]
    assert ed["validation"]["copied_column_count"] == 1
    assert ed["needs_review"] is True
    from slot_extractor import COLUMN_COPY_RULE
    assert any(COLUMN_COPY_RULE in str(v) for v in out["calls"][0].values())


def test_e9_a_memo_the_model_left_empty_is_not_flagged():
    out = _replay(15, lambda parsed: _bank_answer(parsed, memo=False))
    ed = out["extracted_data"]
    assert ed["validation"]["copied_column_count"] == 0
    assert not [f for f in ed["validation"]["flagged_fields"] if f["ref"] == "table[Memo]"]


def test_e9_same_named_columns_and_amount_columns_are_not_copies():
    from slot_extractor import copied_columns
    rows = [{"Item Description": "Bolt", "Description": "Bolt", "Amount": "5.00", "Debit": "5.00"},
            {"Item Description": "Nut", "Description": "Nut", "Amount": "2.00", "Debit": "2.00"}]
    assert copied_columns(rows, ["Item Description", "Description", "Amount", "Debit"]) == []


def test_e9_the_rule_is_asked_only_of_templates_with_two_text_columns():
    from slot_extractor import column_copy_hint
    two = {"tables": [{"columns": [{"header": "Description"}, {"header": "Memo"}]}]}
    one = {"tables": [{"columns": [{"header": "Description"}, {"header": "Amount"}]}]}
    assert column_copy_hint(two) and column_copy_hint(one) == ""


# ---------------------------------------------------------------------------
# E10: a unit read from brackets inside the description is not misplaced.

def _po_answer(parsed, units):
    import copy
    answer = copy.deepcopy(parsed)
    for row, unit in zip(answer["tables"]["table"], units):
        row["cells"]["Unit"] = unit
    return answer


def _placement_flags(ed):
    return [f for f in ed["validation"]["flagged_fields"]
            if "column" in str(f.get("reason", "")).casefold()
            and "under" in str(f.get("reason", "")).casefold()]


def test_e10_a_unit_in_brackets_inside_the_description_is_not_flagged():
    out = _replay(19, lambda parsed: _po_answer(parsed, ["", "pair", "", "", "hours"]))
    ed = out["extracted_data"]
    rows = ed["table_rows"]
    assert [r["Unit"] for r in rows] == ["", "pair", "", "", "hours"]
    assert _placement_flags(ed) == []
    assert all(r.get("_confidence") != "low" for r in rows)


def test_e10_a_value_really_under_another_column_still_fires():
    # the unit price written into Unit: it stands alone under UNIT PRICE
    out = _replay(19, lambda parsed: _po_answer(parsed, ["", "42.00", "", "", ""]))
    flags = _placement_flags(out["extracted_data"])
    assert len(flags) == 1 and flags[0]["ref"] == "table[1].Unit"


# ---------------------------------------------------------------------------
# E11: minus/dash variants, non-breaking spaces and currency placement.

import pytest  # noqa: E402

_VARIANTS = {
    "minus sign U+2212": "−",
    "en dash U+2013": "–",
    "em dash U+2014": "—",
    "hyphen U+2010": "‐",
    "non-breaking hyphen U+2011": "‑",
}


@pytest.mark.parametrize("name", sorted(_VARIANTS))
def test_e11_a_printed_dash_variant_grounds_a_minus_answer(name):
    from slot_extractor import verify_span
    dash = _VARIANTS[name]
    page = f"Service charge {dash}45.00 Balance 1,200.00"
    source = f"Service charge {dash}45.00"
    assert verify_span("-45.00", source, 1, [page]) == (True, "")
    assert verify_span("-45.00", "Service charge -45.00", 1, [page]) == (True, "")
    assert verify_span(f"{dash}45.00", source, 1, [page]) == (True, "")


@pytest.mark.parametrize("space", [" ", " ", " "])
def test_e11_a_non_breaking_space_in_a_quote_or_value_grounds(space):
    from slot_extractor import verify_span
    page = f"Total{space}due $1,234.50"
    assert verify_span("$1,234.50", "Total due $1,234.50", 1, [page]) == (True, "")
    assert verify_span(f"${space}1,234.50", f"Total{space}due $1,234.50", 1, [page]) == (True, "")
    assert verify_span(f"Total{space}due", "Total due", 1, [page]) == (True, "")


@pytest.mark.parametrize("printed,answer", [
    ("-$45.00", "$-45.00"),
    ("$-45.00", "-$45.00"),
    ("45.00 €", "€45.00"),
    ("€45.00", "45.00€"),
    ("(£12.00)", "-£12.00"),
])
def test_e11_currency_symbol_placement_does_not_decide_grounding(printed, answer):
    from slot_extractor import verify_span
    page = f"Adjustment {printed} posted"
    assert verify_span(answer, f"Adjustment {printed}", 1, [page]) == (True, "")


def test_e11_a_different_number_still_fails():
    from slot_extractor import verify_span
    page = "Service charge −45.00"
    assert verify_span("-46.00", "Service charge −45.00", 1, [page])[0] is False
    assert verify_span("45.00", "Service charge −45.00", 1, [page])[0] is False


# ---------------------------------------------------------------------------
# E12: a multi-line address grounds as an ordered sequence of the page's lines.

def _run_doc(relative_pdf, sheet, doc_type, answer):
    """Any acceptance PDF + template sheet + a scripted answer, through the real
    `run_slot_extraction` (the same seams as run_a_driver.replay_job)."""
    import contextlib
    import io
    from types import SimpleNamespace
    import llm_contract as C
    from connectors.base import LLMResponse
    from core.preprocessor import preprocess_file
    from slot_extractor import run_slot_extraction
    from tests.contract.run_a_driver import DOCS, template_grid

    path = DOCS / relative_pdf
    with contextlib.redirect_stdout(io.StringIO()):
        document = preprocess_file(path)

    def extract(**_kw):
        return LLMResponse(raw_text=json.dumps(answer), parsed_json=answer,
                           success=True, model_used="offline-scripted-response")

    n = len(document.page_texts)
    with contextlib.redirect_stdout(io.StringIO()), C.collect_attempts(fresh=True):
        result = run_slot_extraction(
            SimpleNamespace(llm=SimpleNamespace(extract=extract)), path,
            {"layout": template_grid(sheet)}, None, page_images=[],
            doc_text=document.extracted_text, doc_text_pages=document.page_texts,
            file_type="digital_pdf", default_doc_type=doc_type, start=0.0,
            page_lines=document.page_lines,
            page_origins={i + 1: o for i, o in enumerate(document.page_origins)},
            page_numbers=list(range(1, n + 1)),
            widget_values=document.widget_values,
            unreadable={"ocr_failed": document.ocr_failed_pages,
                        "ocr_zero": document.ocr_zero_word_pages})[0]
    return result.extracted_data


_VENDOR = "14 Weavers Yard Shoreditch London E2 7DP United Kingdom"
_BILL_TO = "Unit 9, Quayside Business Park, Bristol BS1 6QS, United Kingdom"


def _invoice_answer(vendor, bill_to):
    f = lambda v, s=None: {"value": v, "source": s if s is not None else v, "page": 1}  # noqa: E731
    return {"fields": {
        "F1": f("Harwood Design Studio Ltd"),
        "F2": f(vendor),
        "F4": f("HD-2026-0142", "Harwood Design Studio Ltd INVOICE HD-2026-0142"),
        "F10": f("Bright Harbour Ltd", "Harwood Design Studio Ltd Bright Harbour Ltd"),
        "F11": f(bill_to),
    }, "tables": {"table": []}}


def _ref_flags(ed, label):
    return [f for f in ed["validation"]["flagged_fields"] if f["ref"] == label]


def test_e12_interleaved_multi_line_addresses_ground():
    ed = _run_doc("invoice/flowparse_invoice_tax.pdf", "AP_Inv_Full", "invoice",
                  _invoice_answer(_VENDOR, _BILL_TO))
    conf = ed["validation"]["confidence_map"]
    assert conf["B2"] in ("high", "grounded") and conf["B11"] in ("high", "grounded")
    assert _ref_flags(ed, "Vendor Address") == [] and _ref_flags(ed, "Bill To Address") == []
    assert ed["extracted_fields"]["B2"] == _VENDOR


def test_e12_an_address_whose_parts_are_not_on_the_page_is_still_flagged():
    ed = _run_doc("invoice/flowparse_invoice_tax.pdf", "AP_Inv_Full", "invoice",
                  _invoice_answer("14 Weavers Yard Hackney London E2 7DP United Kingdom",
                                  _BILL_TO))
    assert ed["validation"]["confidence_map"]["B2"] == "low"
    assert _ref_flags(ed, "Vendor Address")


def test_e12_lines_in_order_needs_consecutive_lines_in_order():
    from slot_extractor import in_line_order
    page = "14 Weavers Yard Unit 9\nShoreditch Quayside\nLondon E2 7DP Bristol\nUnited Kingdom"
    assert in_line_order("14 Weavers Yard, Shoreditch, London E2 7DP", [page], 1)
    assert not in_line_order("Shoreditch 14 Weavers Yard London", [page], 1)    # wrong order
    assert not in_line_order("14 Weavers Yard Hackney London", [page], 1)       # not printed


# ---------------------------------------------------------------------------
# E13: a percentage is a number with a percent format, in every slot.

_PCT_GRID = _grid({
    (0, 0): "Purchase APR",
    (1, 0): "Cash Advance APR",
    (2, 0): "Note",
    (4, 0): "Description", (4, 1): "Quantity", (4, 2): "Tax Rate", (4, 3): "Amount",
    (9, 0): "Total",
})


def _pct_sheet():
    from tests.test_run_c_adversarial import document, round_trip, stored
    from slot_extractor import enumerate_slots
    table = enumerate_slots(_PCT_GRID)["tables"][0]["name"]
    result, _ = stored(
        _PCT_GRID,
        fields={"Purchase APR": "21.99%", "Cash Advance APR": "29.9 %",
                "Note": "VAT charged at 20% on all lines", "Total": "1,200.00"},
        rows={table: [
            {"Description": "Brand refresh", "Quantity": "1", "Tax Rate": "20%", "Amount": "1,000.00"},
            {"Description": "Print", "Quantity": "2", "Tax Rate": "5.5%", "Amount": "200.00"},
        ]})
    return round_trip([document(result)], _PCT_GRID)["Results"]


def test_e13_field_percentages_are_numbers_showing_the_same_digits():
    ws = _pct_sheet()
    cells = {ws.cell(r, 1).value: ws.cell(r, 2) for r in range(1, ws.max_row + 1)
             if ws.cell(r, 1).value}
    apr, cash = cells["Purchase APR"], cells["Cash Advance APR"]
    assert apr.data_type == "n" and apr.value == pytest.approx(0.2199)
    assert apr.number_format == "0.00%"
    assert cash.value == pytest.approx(0.299) and cash.number_format == "0.0%"


def test_e13_a_percent_sign_inside_a_sentence_stays_text():
    ws = _pct_sheet()
    note = next(ws.cell(r, 2) for r in range(1, ws.max_row + 1)
                if ws.cell(r, 1).value == "Note")
    assert note.value == "VAT charged at 20% on all lines" and note.data_type == "s"


def test_e13_a_table_tax_rate_column_holds_numbers():
    ws = _pct_sheet()
    head = next(r for r in range(1, ws.max_row + 1) if ws.cell(r, 3).value == "Tax Rate")
    first, second = ws.cell(head + 1, 3), ws.cell(head + 2, 3)
    assert first.value == pytest.approx(0.2) and first.number_format == "0%"
    assert second.value == pytest.approx(0.055) and second.number_format == "0.0%"


def test_e13_line_items_in_the_combined_export_hold_numbers():
    import openpyxl
    from app.services.excel_cells import write_line_items
    ed = {"table_rows": [{"Description": "Brand refresh", "Tax Rate": "20%",
                          "_source": "x", "_page": 1}]}
    wb = openpyxl.Workbook()
    write_line_items(wb.active, 1, ed)
    vals = [c for row in wb.active.iter_rows() for c in row if c.value == 0.2]
    assert vals and vals[0].number_format == "0%"


@pytest.mark.parametrize("per_file", [True, False])
def test_e13_the_export_py_field_cells_hold_numbers_too(per_file):
    import io
    import openpyxl
    from types import SimpleNamespace
    from app.api.routes.export import _build_excel
    ed = {"extracted_data": {
        "Purchase APR": {"value": "21.99%", "confidence": "high", "ref": "B1"},
        "Note": {"value": "VAT charged at 20% on all lines", "confidence": "high", "ref": "B2"},
        "Total": {"value": "$1,250.00", "confidence": "high", "ref": "B3"}},
        "validation": {"confidence_map": {}, "flagged_fields": []}}
    payload = json.dumps(ed)
    doc = SimpleNamespace(id=1, filename="card.pdf", document_type="credit_card",
                          overall_confidence="high", needs_review=False,
                          get_extracted_data=lambda: json.loads(payload))
    job = SimpleNamespace(id=1, total_docs=1, successful=1, failed=0, needs_review=0,
                          total_time_sec=1.0)
    wb = openpyxl.load_workbook(io.BytesIO(_build_excel(job, [doc], None, per_file)))
    cells = [c for ws in wb.worksheets for row in ws.iter_rows() for c in row]
    apr = [c for c in cells if c.value == pytest.approx(0.2199)]
    assert apr and apr[0].number_format == "0.00%"
    assert any(c.value == 1250.0 for c in cells)
    assert any(c.value == "VAT charged at 20% on all lines" for c in cells)


# ---------------------------------------------------------------------------
# E14: money in the form lane is thousands, not European decimals.

def _write_record(ed, grid):
    from tests.test_run_c_adversarial import document, round_trip
    return round_trip([document(ed)], grid)["Results"]


def test_e14_the_1099_box_1_compensation_is_a_number():
    from tests.contract.run_a_driver import template_grid
    out = _replay(25, lambda parsed: parsed)
    ed = out["extracted_data"]
    assert ed["extracted_fields"]["B10"] == "15,250"
    ws = _write_record(ed, template_grid("F1099_NEC_MISC"))
    box1 = next(ws.cell(r, 2) for r in range(1, ws.max_row + 1)
                if ws.cell(r, 1).value == "Box 1 Nonemployee Compensation")
    assert box1.data_type == "n" and box1.value == 15250.0
    assert box1.number_format == "#,##0.00"      # overnight A3: money shows cents
    tin = next(ws.cell(r, 2) for r in range(1, ws.max_row + 1)
               if ws.cell(r, 1).value == "Payer TIN")
    assert tin.data_type == "s"                      # an identifier stays text


def _money_ed(value, label, **extra):
    from tests.test_run_c_adversarial import stored
    grid = _grid({(0, 0): label})
    result, _ = stored(grid, fields={label: value})
    result.update(extra)
    return result, grid


@pytest.mark.parametrize("other", [None, "$40.00", "12.50"])
def test_e14_a_us_money_document_reads_the_comma_as_thousands(other):
    """A W-2 by type; or another extracted amount in dollars; or another
    extracted amount written with a decimal point."""
    from tests.test_run_c_adversarial import stored
    labels = ["Wages", "Notes"] + (["Fee"] if other else [])
    grid = _grid({(i, 0): lab for i, lab in enumerate(labels)})
    fields = {"Wages": "1,234", "Notes": "see attached"}
    if other:
        fields["Fee"] = other
    result, _ = stored(grid, fields=fields)
    result["document_type"] = "invoice" if other else "w2"
    ws = _write_record(result, grid)
    wages = next(ws.cell(r, 2) for r in range(1, ws.max_row + 1)
                 if ws.cell(r, 1).value == "Wages")
    assert wages.data_type == "n" and wages.value == 1234.0


def test_e14_without_us_evidence_an_ambiguous_amount_stays_text():
    result, grid = _money_ed("1,234", "Amount", document_type="invoice")
    ws = _write_record(result, grid)
    assert ws["B1"].value == "1,234" and ws["B1"].data_type == "s"


def test_e14_a_non_money_label_is_not_reinterpreted():
    result, grid = _money_ed("15,250", "Reference", document_type="form_1099")
    ws = _write_record(result, grid)
    assert ws["B1"].data_type == "s"


def test_e0_a_disagreeing_duplicate_is_kept_and_both_are_low():
    from slot_extractor import enumerate_slots
    from total_row_validators import split_duplicate_totals, total_row_mismatch
    from validators import CheckContext

    slots = enumerate_slots(DUPLICATE_TOTAL_GRID)
    table = slots["tables"][0]
    total_ref = next(f["ref"] for f in slots["fields"] if f["row_label"] == "Total")
    rows = [{"Description": "Widget", "Amount": "15.00"},
            {"Description": "Total", "Amount": "16.00"}]
    values = {total_ref: "15.00"}
    kept, dropped = split_duplicate_totals(
        table, rows, slots["tables"], slots["fields"], values)
    assert len(kept) == 2 and dropped == []
    ctx = CheckContext(slots["fields"], values, [], tables=slots["tables"],
                       rows={table["name"]: kept})
    result = total_row_mismatch(ctx)
    assert len(result) == 1 and set(result[0].slots) == {
        total_ref, f'{table["name"]}_rows[1]'}
