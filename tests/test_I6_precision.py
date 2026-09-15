"""I6 — the exported cell must never show fewer digits than the document printed.

Round 2, run 11 (ENGIE bill, 4-column itemised charges) exported Unit Rate as
`$0.04` for a rate printed `$0.04116`, and four rates as `$0.00`. The real
export is committed: tests/fixtures/round2_exports/run11_engie_BR3_job215.xlsx
(production job 215, 7 Sep 2026).

Reading it answered the report's open question. Every rate is STORED at full
precision; the cell's number format, `"$"#,##0.00`, displays two decimals. So
nothing was destroyed on the way to the sheet, but everything that reads what
the sheet SHOWS gets the wrong number: CSV, copy-as-values, print, a person.
The format came from `cell_format`, which counted the source's decimals and
then floored every count of 2 or more at 2.

The rule: the displayed precision is the source string's decimal count —
never fewer digits than it printed, and never more.

Every expected string below is read off the real PDF, not typed.
"""
import re

import pytest

from tests.harness import bootstrap as _bs

_bs.bootstrap()

EXPORT = _bs.TESTS_DIR / "fixtures" / "round2_exports" / "run11_engie_BR3_job215.xlsx"

#: the seven Unit Rate cells of the real export
RATE_CELLS = ("C2", "C4", "C5", "C6", "C7", "C9", "C10")


def displayed(value, fmt):
    """What Excel shows for `value` under `fmt`, for the formats the writer
    emits: an optional quoted symbol, `#,##0` with optional decimals, and an
    optional accounting negative section `_);(...)`."""
    if not isinstance(value, (int, float)):
        return str(value)
    if fmt in (None, "General"):
        return repr(value)
    sections = fmt.split(";")
    section = sections[1] if value < 0 and len(sections) > 1 else sections[0]
    sym = re.search(r'"([^"]*)"', section)
    sym = sym.group(1) if sym else ""
    dec = re.search(r"0\.(0+)", section)
    dec = len(dec.group(1)) if dec else 0
    body = f"{abs(value):,.{dec}f}" if "," in section else f"{abs(value):.{dec}f}"
    if value < 0 and section.strip().startswith("("):
        return f"({sym}{body})"
    return f"{'-' if value < 0 else ''}{sym}{body}"


@pytest.fixture(scope="module")
def export_sheet():
    import openpyxl
    return openpyxl.load_workbook(EXPORT).active


@pytest.fixture(scope="module")
def printed_lines(pdf_dir):
    """The itemised-charges page of the real bill, as the pipeline reads it."""
    import pdfplumber
    from text_layer import read_page
    with pdfplumber.open(pdf_dir / "round2" / "SampleBill.pdf") as pdf:
        return read_page(pdf.pages[2])[0].splitlines()


def _printed_row(label, lines):
    """(usage, rate, amount) exactly as the page prints them on `label`'s line."""
    line = next(l for l in lines if label in l)
    usage = re.search(r"(\d[\d,]*)\s?kWh", line)
    rate = re.search(r"@\s*(\$[\d.]+)", line)
    amount = re.findall(r"\$[\d,]+\.\d+", line)[-1]
    return (usage.group(1) if usage else "", rate.group(1) if rate else "", amount)


@pytest.fixture(scope="module")
def rows(export_sheet, printed_lines):
    """Run 11's rows: the charge labels from the real export, every value as
    printed on the real page."""
    out = []
    for r in range(2, 15):
        label = export_sheet.cell(row=r, column=1).value
        usage, rate, amount = _printed_row(label, printed_lines)
        out.append({"Charge": label, "Usage (kWh)": usage,
                    "Unit Rate": rate, "Amount": amount})
    return out


def _rebuild(rows):
    """Run 11's shape written through today's export path, end to end."""
    import openpyxl
    from app.api.routes.extract import _write_excel

    columns = ["Charge", "Usage (kWh)", "Unit Rate", "Amount"]
    grid = {"cells": {f"0,{i}": {"value": h, "style": {}}
                      for i, h in enumerate(columns)},
            "colWidths": [], "merges": {}, "repeatRows": [], "regions": []}

    class _Doc:
        def get_extracted_data(self):
            return {"template_type": "slot", "extracted_fields": {},
                    "Charges_rows": rows,
                    "slot_map": {"fields": [], "tables": [{
                        "name": "Charges", "start_row": 1,
                        "end_row": len(rows), "start_col": 0, "end_col": 3,
                        "orientation": "rows",
                        "columns": [{"header": h, "key": h, "col": i}
                                    for i, h in enumerate(columns)]}]}}

    ws = openpyxl.Workbook().active
    _write_excel(ws, [_Doc()], grid, {}, openpyxl)
    return ws


# ══════════════════════════════════════════════════════════════════════════
# the premise — what the real run-11 export holds
# ══════════════════════════════════════════════════════════════════════════

class TestTheRealRun11Export:
    def test_every_rate_was_stored_at_the_precision_the_page_printed(
            self, export_sheet, rows):
        """Nothing was destroyed: the cell VALUE is the printed rate."""
        by_label = {r["Charge"]: r for r in rows}
        for ref in RATE_CELLS:
            cell = export_sheet[ref]
            label = export_sheet.cell(row=cell.row, column=1).value
            assert f"${cell.value}" == by_label[label]["Unit Rate"], ref

    def test_and_every_one_was_displayed_with_fewer_digits(self, export_sheet, rows):
        """The shipped defect, read off the shipped file: `$0.04116` showed
        `$0.04`, and four rates showed `$0.00`."""
        shown = {ref: displayed(export_sheet[ref].value, export_sheet[ref].number_format)
                 for ref in RATE_CELLS}
        assert shown["C2"] == "$0.04"
        assert [shown[r] for r in ("C4", "C6", "C7", "C9")] == ["$0.00"] * 4
        by_label = {r["Charge"]: r["Unit Rate"] for r in rows}
        assert all(shown[ref] != by_label[export_sheet.cell(
            row=export_sheet[ref].row, column=1).value] for ref in RATE_CELLS)


# ══════════════════════════════════════════════════════════════════════════
# THE EVIDENCE — run 11 rebuilt through today's writer
# ══════════════════════════════════════════════════════════════════════════

class TestRun11RebuiltShowsWhatThePagePrinted:
    @pytest.mark.parametrize("ref", RATE_CELLS)
    def test_each_rate_displays_every_digit_the_page_printed(self, rows, ref):
        """THE EVIDENCE. At 811778f each of these shows two decimals."""
        ws = _rebuild(rows)
        cell = ws[ref]
        label = ws.cell(row=cell.row, column=1).value
        printed = next(r["Unit Rate"] for r in rows if r["Charge"] == label)
        assert displayed(cell.value, cell.number_format) == printed, (
            f"{ref} ({label}) holds {cell.value!r} and displays "
            f"{displayed(cell.value, cell.number_format)!r} under "
            f"{cell.number_format!r}; the page prints {printed!r}")

    def test_the_rate_is_still_a_number(self, rows):
        """The fix is presentation. The cell must still sum and sort."""
        ws = _rebuild(rows)
        assert all(isinstance(ws[ref].value, float) for ref in RATE_CELLS)

    def test_every_amount_on_the_same_sheet_is_unchanged(self, rows):
        """The 2-decimal control on the same document: `$21.10` keeps its
        trailing zero and gains nothing."""
        ws = _rebuild(rows)
        for r, row in enumerate(rows, start=2):
            cell = ws.cell(row=r, column=4)
            assert displayed(cell.value, cell.number_format) == row["Amount"], row


# ══════════════════════════════════════════════════════════════════════════
# ordinary amounts — never fewer digits, and never more
# ══════════════════════════════════════════════════════════════════════════

class TestOrdinaryAmountsDisplayAsPrinted:
    @pytest.mark.parametrize("printed", [
        "$19,694.00", "$19,694", "$7,750.00", "$155.00", "$0.32", "$21.10",
        "(1,234.50)", "1,980,000", "30", "1,268.7", "$0.04116", "$0.000127",
    ])
    def test_the_cell_displays_exactly_the_printed_string(self, printed):
        from app.api.routes.extract import cell_format, coerce_cell_value
        assert displayed(coerce_cell_value(printed), cell_format(printed)) == printed
