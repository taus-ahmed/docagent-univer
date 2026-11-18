from __future__ import annotations

from numbers import Number

import pytest

from tests.acceptance.export_fixture import document, extracted, workbook


RUN_A6 = pytest.mark.xfail(
    strict=True,
    reason="Run A6: compact bands, clean default export, draft marking, and deterministic document spacing are not implemented",
)


def _find(ws, value):
    return [cell for row in ws.iter_rows() for cell in row if cell.value == value]


def test_money_is_numeric_at_every_review_level_after_round_trip():
    wb = workbook(provenance=True, marks=True)
    ws = wb["Results"]
    for expected in (30.0, 2.4, 32.4, 10.0, 20.0):
        matches = [cell for row in ws.iter_rows() for cell in row
                   if isinstance(cell.value, Number) and abs(float(cell.value) - expected) < 1e-9]
        assert matches, expected


def test_identifiers_zips_and_last_four_remain_exact_text():
    wb = workbook()
    ws = wb["Results"]
    assert ws["B3"].value == "00501" and ws["B3"].data_type == "s"
    assert ws["B4"].value == "0042" and ws["B4"].data_type == "s"
    assert len(ws["B4"].value) == 4 and ws["B4"].value.isdigit()


@RUN_A6
def test_unused_reserved_rows_are_removed_and_totals_touch_the_band():
    wb = workbook()
    ws = wb["Results"]
    amounts = [cell.row for cell in _find(ws, 10.0) + _find(ws, 20.0)]
    subtotal = _find(ws, 30.0)
    subtotal_rows = [cell.row for cell in subtotal if ws.cell(cell.row, 1).value == "Subtotal"]
    assert subtotal_rows == [max(amounts) + 1]


def test_template_authored_blank_row_between_sections_is_kept():
    wb = workbook()
    ws = wb["Results"]
    marker = _find(ws, "Template-kept blank row follows")[0]
    assert all(ws.cell(marker.row - 1, col).value is None for col in range(1, 3))


@RUN_A6
def test_multiple_documents_have_header_strip_and_exactly_three_blank_rows():
    docs = [document(filename="a.pdf"), document(filename="b.pdf")]
    wb = workbook(docs=docs)
    ws = wb["Results"]
    titles = [cell.row for cell in _find(ws, "ACCEPTANCE EXPORT")]
    assert len(titles) == 2
    first_block_last = max(
        cell.row for row in ws.iter_rows(min_row=titles[0], max_row=titles[1] - 1)
        for cell in row if cell.value is not None
    )
    assert titles[1] - first_block_last - 1 == 3
    assert ws.cell(titles[1], 1).value == "ACCEPTANCE EXPORT"


@RUN_A6
def test_default_download_hides_source_and_review_columns_but_opt_in_restores_them():
    default = workbook(use_defaults=True)["Results"]
    default_headers = [str(cell.value or "") for cell in default[1]]
    assert not any("Source" in value or "Review status" in value for value in default_headers)
    opted = workbook(provenance=True, marks=True)["Results"]
    opted_values = [str(cell.value or "") for row in opted.iter_rows() for cell in row]
    assert any("Source" in value for value in opted_values)
    assert any("Review status" in value for value in opted_values)


def test_fills_comments_and_legend_survive_round_trip():
    wb = workbook(provenance=True, marks=True)
    ws = wb["Results"]
    assert ws["A1"].fill.fill_type == "solid"
    assert ws["A1"].fill.fgColor.rgb == "FFD9EAF7"
    assert ws["B2"].comment is not None
    assert "Legend" in wb.sheetnames
    assert wb["Legend"]["A1"].value


@RUN_A6
def test_attention_document_is_marked_draft():
    ed = extracted(state="NEEDS_ATTENTION")
    wb = workbook(docs=[document(ed, needs_review=True)], provenance=False, marks=False)
    values = [str(cell.value or "").casefold() for ws in wb.worksheets
              for row in ws.iter_rows() for cell in row]
    assert any("draft" in value for value in values)


def test_invoice_totals_block_is_present():
    wb = workbook()
    ws = wb["Results"]
    labels = {str(cell.value) for row in ws.iter_rows() for cell in row if cell.value is not None}
    assert {"Subtotal", "Tax", "Total"} <= labels
    numeric = {float(cell.value) for row in ws.iter_rows() for cell in row
               if isinstance(cell.value, Number)}
    assert {30.0, 2.4, 32.4} <= numeric
