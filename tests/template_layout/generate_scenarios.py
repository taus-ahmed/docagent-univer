"""Generate the workbook fixtures for the template-layout audit.

The expected structures below are intentionally authored independently of the
engine.  They describe what a workbook reader would reasonably mean by each
layout; the tests compare the production shape/writer with these JSON files.
Run from the repository root with Python 3.11+ and openpyxl installed.
"""

from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.styles import Border, Font, PatternFill, Side
from openpyxl.worksheet.table import Table, TableStyleInfo


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tests" / "templates"
THIN = Side(style="thin", color="000000")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def new_book(title: str = "Template"):
    wb = Workbook()
    ws = wb.active
    ws.title = title
    return wb, ws


def setv(ws, cell: str, value, *, bold=False, border=False, fill=None):
    c = ws[cell]
    c.value = value
    if bold:
        c.font = Font(bold=True)
    if border:
        c.border = BOX
    if fill:
        c.fill = PatternFill("solid", fgColor=fill)
    return c


def blank(ws, cell: str, *, border=False, number_format=None):
    c = ws[cell]
    c.value = None
    if border:
        c.border = BOX
    if number_format:
        c.number_format = number_format
    return c


def header(ws, row: int, start_col: int, names: list[str], *, border=False):
    for offset, name in enumerate(names):
        c = ws.cell(row=row, column=start_col + offset, value=name)
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="D9EAF7")
        if border:
            c.border = BOX


def reserve(ws, first_row: int, last_row: int, first_col: int, last_col: int,
            *, border=False):
    for row in range(first_row, last_row + 1):
        for col in range(first_col, last_col + 1):
            c = ws.cell(row=row, column=col)
            if border:
                c.border = BOX


def merged_note(ws, row: int, start_col: int, end_col: int, text: str):
    ws.merge_cells(start_row=row, start_column=start_col,
                   end_row=row, end_column=end_col)
    ws.cell(row=row, column=start_col, value=text)


def field(label: str, label_cell: str, value_cell: str, *, value=None, empty=False,
          sheet="Template"):
    d = {"label": label, "label_cell": label_cell, "cell": value_cell,
         "sheet": sheet}
    if value is not None:
        d["value"] = value
    if empty:
        d["empty"] = True
    return d


def band(name: str, header_row: int, first_data_row: int, reserved_rows: int,
         start_col: str, columns: list[str], *, totals=None, write_rows=None,
         sheet="Template", orientation="rows", first_data_col=None,
         reserved_records=None, interior=None):
    d = {
        "name": name,
        "sheet": sheet,
        "orientation": orientation,
        "header_row": header_row,
        "first_data_row": first_data_row,
        "reserved_rows": reserved_rows,
        "start_col": start_col,
        "columns": columns,
        "totals_cells": totals or [],
        "write_rows": reserved_rows if write_rows is None else write_rows,
    }
    if first_data_col is not None:
        d["first_data_col"] = first_data_col
    if reserved_records is not None:
        d["reserved_records"] = reserved_records
    if interior:
        d["interior_rows"] = interior
    return d


def truth(scenario: str, title: str, fields=None, bands=None, *,
          prompt_ambiguities=None, native=None, write=None, formulas=None,
          sheets=None):
    return {
        "scenario": scenario,
        "title": title,
        "sheets": sheets or ["Template"],
        "fields": fields or [],
        "bands": bands or [],
        "formulas": formulas or [],
        "native_features": native or {},
        "write": write or {},
        "prompt_ambiguities": prompt_ambiguities or [],
    }


def scenarios():
    out = []

    wb, ws = new_book()
    setv(ws, "A1", "Invoice Number"); blank(ws, "B1")
    setv(ws, "A2", "Auditor"); blank(ws, "B2")
    out.append((wb, truth("F1", "label left, slot right",
        [field("Invoice Number", "A1", "B1"), field("Auditor", "A2", "B2", empty=True)])))

    wb, ws = new_book()
    setv(ws, "A1", "Invoice Date"); blank(ws, "A2")
    setv(ws, "C1", "Approval Code"); blank(ws, "C2")
    out.append((wb, truth("F2", "label above, slot below",
        [field("Invoice Date", "A1", "A2"), field("Approval Code", "C1", "C2", empty=True)],
        prompt_ambiguities=["The engine describes horizontal slots B1/D1 instead of the intended cells below A1/C1."])))

    wb, ws = new_book()
    setv(ws, "A1", "Account"); blank(ws, "D1")
    setv(ws, "A2", "Reference"); blank(ws, "C2")
    out.append((wb, truth("F3", "label and slot separated by empty columns",
        [field("Account", "A1", "D1"), field("Reference", "A2", "C2", empty=True)],
        prompt_ambiguities=["Empty separator columns are outside the text-defined used range, so the prompt invents adjacent slots."])))

    wb, ws = new_book()
    for cell, text in [("A1", "Name"), ("C1", "Date"), ("E1", "Total")]: setv(ws, cell, text)
    out.append((wb, truth("F4", "side-by-side key-value pairs",
        [field("Name", "A1", "B1"), field("Date", "C1", "D1"),
         field("Total", "E1", "F1", empty=True)])))

    wb, ws = new_book()
    for cell, text in [("A1", "Entity"), ("C1", "Period"), ("H1", "Status"),
                       ("A4", "Owner"), ("C4", "Region"), ("E4", "Currency"),
                       ("G4", "Rate"), ("I4", "Threshold"), ("G5", "Reviewer")]:
        setv(ws, cell, text)
    f5 = [field("Entity", "A1", "B1"), field("Period", "C1", "D1"),
          field("Status", "H1", "I1"), field("Owner", "A4", "B4"),
          field("Region", "C4", "D4"), field("Currency", "E4", "F4"),
          field("Rate", "G4", "H4"), field("Threshold", "I4", "J4"),
          field("Reviewer", "G5", "H5", empty=True)]
    out.append((wb, truth("F5", "scattered field groups", f5)))

    wb, ws = new_book()
    ws.merge_cells("A1:B1"); setv(ws, "A1", "Legal Name")
    ws.merge_cells("C1:D1")
    ws.merge_cells("A3:B3"); setv(ws, "A3", "Reporting Date")
    ws.merge_cells("C3:D3")
    out.append((wb, truth("F6", "merged label cells and merged slot cells",
        [field("Legal Name", "A1", "C1"), field("Reporting Date", "A3", "C3", empty=True)],
        prompt_ambiguities=["Merged empty value ranges produce no field-slot prompt; only merge anchors can carry values."] ,
        native={"merged_ranges": ["A1:B1", "C1:D1", "A3:B3", "C3:D3"]})))

    wb, ws = new_book()
    ws.merge_cells("A1:B1"); setv(ws, "A1", "Payer", bold=True)
    ws.merge_cells("A6:B6"); setv(ws, "A6", "Recipient", bold=True)
    f7 = []
    for row, label in [(2, "Name"), (3, "Date"), (4, "Total"),
                       (7, "Name"), (8, "Date"), (9, "Total")]:
        setv(ws, f"A{row}", label); blank(ws, f"B{row}")
        f7.append(field(label, f"A{row}", f"B{row}", empty=(row == 9)))
    out.append((wb, truth("F7", "duplicate labels in different sections", f7,
        prompt_ambiguities=["Both Name, Date, and Total pairs are described without Payer/Recipient section context."],
        native={"merged_ranges": ["A1:B1", "A6:B6"]})))

    wb, ws = new_book()
    labels = ["Invoice No.:", "Amount (USD)", "Tax*", "Weight (kg)"]
    f8 = []
    for row, label in enumerate(labels, 1):
        setv(ws, f"A{row}", label); blank(ws, f"B{row}")
        f8.append(field(label, f"A{row}", f"B{row}", empty=(row == 4)))
    out.append((wb, truth("F8", "punctuation, units, asterisks, and parentheses", f8)))

    wb, ws = new_book()
    specs = [("Currency", "$#,##0.00", "$1,234.50"),
             ("Date", "mm/dd/yyyy", "11/19/2026"),
             ("Rate", "0.0%", "12.5%"), ("Code", "@", "00123"),
             ("Status", "General", "")]
    f9 = []
    for row, (label, fmt, value) in enumerate(specs, 1):
        setv(ws, f"A{row}", label); blank(ws, f"B{row}", number_format=fmt)
        f9.append(field(label, f"A{row}", f"B{row}", value=value, empty=(not value)))
    dv = DataValidation(type="list", formula1='"Draft,Approved,Rejected"')
    ws.add_data_validation(dv); dv.add(ws["B5"])
    out.append((wb, truth("F9", "formatted slots and dropdown validation", f9,
        native={"number_formats": {f"B{i+1}": s[1] for i, s in enumerate(specs)},
                "validations": ["B5"]})))

    wb, ws = new_book()
    setv(ws, "A1", "Net Amount"); blank(ws, "B1")
    setv(ws, "C1", "Tax"); setv(ws, "D1", "=B1*0.2")
    setv(ws, "A2", "Gross Amount"); setv(ws, "B2", "=SUM(B1,D1)")
    setv(ws, "A3", "Notes"); blank(ws, "B3")
    out.append((wb, truth("F10", "formula cells next to extracted fields",
        [field("Net Amount", "A1", "B1"), field("Notes", "A3", "B3", empty=True)],
        formulas=[{"cell": "D1", "formula": "=B1*0.2"},
                  {"cell": "B2", "formula": "=SUM(B1,D1)"}],
        prompt_ambiguities=["Formula text participates in label geometry and can create unintended field slots."])))

    wb, ws = new_book()
    setv(ws, "A1", "Name"); setv(ws, "B1", "[enter name]")
    setv(ws, "A2", "Date"); setv(ws, "B2", "TBD")
    out.append((wb, truth("F11", "placeholder text inside slot cells",
        [field("Name", "A1", "B1"), field("Date", "A2", "B2", empty=True)],
        prompt_ambiguities=["Placeholders are static labels under the one rule, so neither intended slot appears in the prompt."])))

    wb, ws = new_book()
    ws.merge_cells("A1:D1"); setv(ws, "A1", "INVOICE REVIEW", bold=True)
    ws.merge_cells("A2:D2"); setv(ws, "A2", "Complete blue cells only")
    setv(ws, "A4", "Invoice Number"); blank(ws, "B4")
    setv(ws, "A5", "Date"); blank(ws, "B5")
    ws.row_dimensions[5].hidden = True
    ws.column_dimensions["D"].hidden = True
    ws.merge_cells("A8:D8"); setv(ws, "A8", "Notes: leave blank if unknown")
    out.append((wb, truth("F12", "titles, instructions, notes, spacers, and hidden axes",
        [field("Invoice Number", "A4", "B4"), field("Date", "A5", "B5", empty=True)],
        native={"merged_ranges": ["A1:D1", "A2:D2", "A8:D8"],
                "hidden_rows": [5], "hidden_columns": ["D"]})))

    wb, ws = new_book()
    labels = ["Inv. No.", "Fecha", "Montant", "MwSt."]
    f13 = []
    for row, label in enumerate(labels, 1):
        setv(ws, f"A{row}", label); blank(ws, f"B{row}")
        f13.append(field(label, f"A{row}", f"B{row}", empty=(row == 4)))
    out.append((wb, truth("F13", "abbreviated and non-English labels", f13)))

    wb, ws = new_book(); header(ws, 1, 1, ["Item", "Qty", "Amount"]); reserve(ws, 2, 6, 1, 3)
    setv(ws, "A7", "Total"); blank(ws, "B7")
    out.append((wb, truth("T1", "header plus five reserved rows",
        [field("Total", "A7", "B7")],
        [band("table", 1, 2, 5, "A", ["Item", "Qty", "Amount"], totals=[{"label":"Total","cell":"B7"}], write_rows=5)])))

    wb, ws = new_book(); header(ws, 1, 1, ["Item", "Qty", "Amount"])
    out.append((wb, truth("T2", "header only, no reserved rows", [],
        [band("table", 1, 2, 0, "A", ["Item", "Qty", "Amount"], write_rows=3)],
        prompt_ambiguities=["The prompt claims the header-only sheet has ten blank rows, although the workbook reserves none."])))

    wb, ws = new_book(); header(ws, 1, 1, ["Item", "Qty", "Amount"]); reserve(ws, 2, 3, 1, 3)
    setv(ws, "A4", "Total A"); blank(ws, "B4"); merged_note(ws, 4, 3, 4, "USD")
    header(ws, 6, 1, ["Code", "Hours", "Cost"]); reserve(ws, 7, 8, 1, 3)
    setv(ws, "A9", "Total B"); blank(ws, "B9"); merged_note(ws, 9, 3, 4, "USD")
    out.append((wb, truth("T3", "two tables stacked with one blank row",
        [field("Total A", "A4", "B4"), field("Total B", "A9", "B9", empty=True)],
        [band("table_1", 1, 2, 2, "A", ["Item", "Qty", "Amount"], totals=[{"label":"Total A","cell":"B4"}]),
         band("table_2", 6, 7, 2, "A", ["Code", "Hours", "Cost"], totals=[{"label":"Total B","cell":"B9"}])],
        native={"merged_ranges": ["C4:D4", "C9:D9"]})))

    wb, ws = new_book(); header(ws, 1, 1, ["Item", "Qty", "Amount"]); reserve(ws, 2, 3, 1, 3)
    setv(ws, "A4", "Total A"); blank(ws, "B4"); merged_note(ws, 4, 3, 4, "USD")
    header(ws, 5, 1, ["Code", "Hours", "Cost"]); reserve(ws, 6, 7, 1, 3)
    setv(ws, "A8", "Total B"); blank(ws, "B8"); merged_note(ws, 8, 3, 4, "USD")
    out.append((wb, truth("T4", "two tables stacked with no blank row",
        [field("Total A", "A4", "B4"), field("Total B", "A8", "B8", empty=True)],
        [band("table_1", 1, 2, 2, "A", ["Item", "Qty", "Amount"], totals=[{"label":"Total A","cell":"B4"}]),
         band("table_2", 5, 6, 2, "A", ["Code", "Hours", "Cost"], totals=[{"label":"Total B","cell":"B8"}])],
        native={"merged_ranges": ["C4:D4", "C8:D8"]})))

    wb, ws = new_book(); header(ws, 1, 1, ["A Item", "A Qty", "A Amount"]); reserve(ws, 2, 2, 1, 3)
    header(ws, 3, 1, ["B Item", "B Qty", "B Amount"]); reserve(ws, 4, 5, 1, 3)
    setv(ws, "A6", "Prepared by"); blank(ws, "B6")
    out.append((wb, truth("T5", "header row 1 and header row 3; first table grows to ten rows",
        [field("Prepared by", "A6", "B6", empty=True)],
        [band("table_1", 1, 2, 1, "A", ["A Item", "A Qty", "A Amount"], write_rows=10),
         band("table_2", 3, 4, 2, "A", ["B Item", "B Qty", "B Amount"], write_rows=2)])))

    wb, ws = new_book(); header(ws, 1, 1, ["Left A", "Left B", "Left C", "Left D"]); header(ws, 1, 6, ["Right A", "Right B", "Right C", "Right D"])
    reserve(ws, 2, 3, 1, 4); reserve(ws, 2, 3, 6, 9)
    setv(ws, "A4", "End left"); setv(ws, "F4", "End right")
    out.append((wb, truth("T6", "two tables side by side; left table grows",
        [], [band("left", 1, 2, 2, "A", ["Left A", "Left B", "Left C", "Left D"], write_rows=5),
             band("right", 1, 2, 2, "F", ["Right A", "Right B", "Right C", "Right D"], write_rows=2)],
        prompt_ambiguities=["The gapped header row yields no table slot descriptions, so neither side is addressable."])))

    wb, ws = new_book(); header(ws, 1, 1, ["Item", "Qty", "Amount"], border=True); reserve(ws, 2, 3, 1, 3, border=True)
    setv(ws, "A4", "Prepared by", border=True); blank(ws, "B4", border=True)
    out.append((wb, truth("T7", "bordered table", [field("Prepared by", "A4", "B4", empty=True)],
        [band("table", 1, 2, 2, "A", ["Item", "Qty", "Amount"])], native={"bordered_ranges": ["A1:C3"]})))

    wb, ws = new_book(); header(ws, 1, 1, ["Item", "Qty", "Amount"], border=True); reserve(ws, 2, 3, 1, 3, border=True)
    setv(ws, "A4", "End bordered"); blank(ws, "B4"); merged_note(ws, 4, 3, 4, "END")
    header(ws, 6, 1, ["Code", "Hours", "Cost"]); reserve(ws, 7, 8, 1, 3)
    setv(ws, "A9", "End plain"); blank(ws, "B9"); merged_note(ws, 9, 3, 4, "END")
    out.append((wb, truth("T8", "one bordered and one unbordered table",
        [field("End bordered", "A4", "B4"), field("End plain", "A9", "B9", empty=True)],
        [band("table_1", 1, 2, 2, "A", ["Item", "Qty", "Amount"]),
         band("table_2", 6, 7, 2, "A", ["Code", "Hours", "Cost"])],
        native={"bordered_ranges": ["A1:C3"]})))

    wb, ws = new_book(); ws.merge_cells("A1:A2"); setv(ws, "A1", "Item", bold=True)
    ws.merge_cells("B1:C1"); setv(ws, "B1", "Amount", bold=True); header(ws, 2, 2, ["Debit", "Credit"]); reserve(ws, 3, 5, 1, 3)
    setv(ws, "A6", "Prepared by"); blank(ws, "B6")
    out.append((wb, truth("T9", "two-level merged headers", [field("Prepared by", "A6", "B6", empty=True)],
        [band("Amount", 2, 3, 3, "A", ["Item", "Debit", "Credit"])],
        prompt_ambiguities=["The merged Item header heads the band's first column; the prompt exposes a three-column Item/Debit/Credit band, and the two-level Amount heading is flattened into Debit and Credit."],
        native={"merged_ranges": ["A1:A2", "B1:C1"]})))

    wb, ws = new_book()
    header(ws, 2, 1, ["Direct", "Qty", "Amount"]); reserve(ws, 3, 4, 1, 3); setv(ws, "A5", "Total direct"); blank(ws, "B5"); merged_note(ws, 5, 3, 4, "USD")
    header(ws, 7, 1, ["Blank", "Qty", "Amount"]); reserve(ws, 8, 9, 1, 3); setv(ws, "A11", "Total after blank"); blank(ws, "B11"); merged_note(ws, 11, 3, 4, "USD")
    header(ws, 13, 1, ["Right", "Qty", "Amount"]); reserve(ws, 14, 15, 1, 3); setv(ws, "E14", "Total right"); blank(ws, "F14"); setv(ws, "A16", "End"); merged_note(ws, 16, 3, 4, "END")
    setv(ws, "A18", "Total above"); blank(ws, "B18"); header(ws, 19, 1, ["Above", "Qty", "Amount"]); reserve(ws, 20, 21, 1, 3); setv(ws, "A22", "End"); merged_note(ws, 22, 3, 4, "END")
    t10_fields = [field("Total direct", "A5", "B5"), field("Total after blank", "A11", "B11"),
                  field("Total right", "E14", "F14"), field("Total above", "A18", "B18", empty=True)]
    t10_bands = [band("table_1", 2, 3, 2, "A", ["Direct", "Qty", "Amount"], totals=[{"label":"Total direct","cell":"B5"}]),
                 band("table_2", 7, 8, 2, "A", ["Blank", "Qty", "Amount"], totals=[{"label":"Total after blank","cell":"B11"}]),
                 band("table_3", 13, 14, 2, "A", ["Right", "Qty", "Amount"], totals=[{"label":"Total right","cell":"F14"}]),
                 band("table_4", 19, 20, 2, "A", ["Above", "Qty", "Amount"], totals=[{"label":"Total above","cell":"B18"}])]
    out.append((wb, truth("T10", "totals below, after a blank, to the right, and above", t10_fields, t10_bands,
        prompt_ambiguities=["Totals have no explicit ownership; the prompt treats any detected total as an independent field."])))

    wb, ws = new_book(); header(ws, 1, 1, ["Date", "Description", "Qty", "Rate", "Amount"]); reserve(ws, 2, 6, 1, 5)
    setv(ws, "A4", "Subtotal"); setv(ws, "E4", "=SUM(E2:E3)")
    ws.merge_cells("A7:B7"); setv(ws, "A7", "End")
    ws.merge_cells("C7:D7"); setv(ws, "C7", "Section")
    ws.merge_cells("E7:F7"); setv(ws, "E7", "END")
    out.append((wb, truth("T11", "subtotal row inside a table", [],
        [band("table", 1, 2, 5, "A", ["Date", "Description", "Qty", "Rate", "Amount"],
              interior=[{"label_cell":"A4","formula_cell":"E4"}])],
        formulas=[{"cell":"E4","formula":"=SUM(E2:E3)"}],
        native={"merged_ranges": ["A7:B7", "C7:D7", "E7:F7"]})))

    wb, ws = new_book(); setv(ws, "A1", "Line item"); setv(ws, "B1", "Q1"); setv(ws, "C1", "Q2"); setv(ws, "D1", "Q3")
    for row, label in [(2, "Revenue"), (3, "COGS"), (4, "Profit")]: setv(ws, f"A{row}", label)
    out.append((wb, truth("T12", "transposed table", [],
        [band("table", 1, 2, 3, "A", ["Revenue", "COGS", "Profit"], orientation="columns", first_data_col="B", reserved_records=3)],
        prompt_ambiguities=["Without an editor declaration, the transposed matrix is described as scalar fields rather than records."])))

    wb, ws = new_book(); header(ws, 1, 1, ["Document", "Date", "Entity", "Total"])
    out.append((wb, truth("T13", "one-row-per-document flat list", [],
        [band("table", 1, 2, 0, "A", ["Document", "Date", "Entity", "Total"], write_rows=1)],
        prompt_ambiguities=["The prompt claims ten reserved rows for a header-only flat list."])))

    wb, ws = new_book(); header(ws, 1, 1, ["Item", "Qty", "Amount"]); reserve(ws, 2, 2, 1, 3)
    tab = Table(displayName="AuditTable", ref="A1:C2")
    tab.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(tab)
    out.append((wb, truth("T14", "Excel Format-as-Table object", [],
        [band("AuditTable", 1, 2, 1, "A", ["Item", "Qty", "Amount"], write_rows=1)],
        native={"tables": [{"name":"AuditTable","ref":"A1:C2"}]},
        prompt_ambiguities=["The Excel Table object is ignored; the prompt falls back to the ten-row edge-band heuristic."])))

    wb, ws = new_book(); header(ws, 1, 1, ["Item", "Qty", "Amount"]); reserve(ws, 2, 4, 1, 3)
    setv(ws, "E2", "Owner"); blank(ws, "F2"); setv(ws, "E3", "Reviewed"); blank(ws, "F3")
    setv(ws, "A5", "End"); merged_note(ws, 5, 3, 4, "END")
    out.append((wb, truth("T15", "fields beside a table on the same rows",
        [field("Owner", "E2", "F2"), field("Reviewed", "E3", "F3", empty=True)],
        [band("table", 1, 2, 3, "A", ["Item", "Qty", "Amount"])],
        prompt_ambiguities=["Rows owned by a table are excluded wholesale from scalar-field inference, so side fields are absent."])))

    wb, ws = new_book(); header(ws, 1, 10, ["Date", "Description", "Debit", "Credit"]); reserve(ws, 2, 3, 10, 13)
    setv(ws, "J4", "Prepared by"); blank(ws, "K4")
    out.append((wb, truth("T16", "table at the far right", [field("Prepared by", "J4", "K4", empty=True)],
        [band("table", 1, 2, 2, "J", ["Date", "Description", "Debit", "Credit"])])))

    wb, ws = new_book(); t17_fields=[]; t17_bands=[]
    for idx, name in enumerate(["Revenue", "COGS", "Expenses"]):
        base = 1 + idx * 6
        ws.merge_cells(start_row=base, start_column=1, end_row=base, end_column=2); setv(ws, f"A{base}", name, bold=True)
        header(ws, base + 1, 1, [name, "Amount"]); reserve(ws, base + 2, base + 3, 1, 2)
        setv(ws, f"A{base+4}", f"Total {name}"); blank(ws, f"B{base+4}")
        t17_fields.append(field(f"Total {name}", f"A{base+4}", f"B{base+4}", empty=(name=="Expenses")))
        t17_bands.append(band(name, base+1, base+2, 2, "A", [name, "Amount"], totals=[{"label":f"Total {name}","cell":f"B{base+4}"}]))
    out.append((wb, truth("T17", "several section bands with totals", t17_fields, t17_bands,
        native={"merged_ranges": ["A1:B1", "A7:B7", "A13:B13"]})))

    wb, ws = new_book("Fields"); setv(ws, "A1", "Entity"); blank(ws, "B1"); setv(ws, "A2", "Date"); blank(ws, "B2")
    lines = wb.create_sheet("Lines"); header(lines, 1, 1, ["Item", "Qty", "Amount"]); reserve(lines, 2, 3, 1, 3); setv(lines, "A4", "End")
    out.append((wb, truth("T18", "multiple sheets in one template",
        [field("Entity", "A1", "B1", sheet="Fields"), field("Date", "A2", "B2", empty=True, sheet="Fields")],
        [band("table", 1, 2, 2, "A", ["Item", "Qty", "Amount"], sheet="Lines")],
        sheets=["Fields", "Lines"], prompt_ambiguities=["Only the first sheet reaches the grid; the Lines sheet has no prompt slots."])))

    wb, ws = new_book(); header(ws, 1, 1, ["Date", "Amount", "Notes"]); reserve(ws, 2, 3, 1, 3); setv(ws, "A4", "Prepared by"); blank(ws, "B4")
    out.append((wb, truth("T19", "extra template and document columns",
        [field("Prepared by", "A4", "B4", empty=True)],
        [band("table", 1, 2, 2, "A", ["Date", "Amount", "Notes"])],
        write={"model_extra_columns": ["Ignored"], "model_omit_columns": ["Notes"]})))

    wb, ws = new_book(); header(ws, 1, 1, ["Item", "Amount"]); reserve(ws, 2, 3, 1, 2); setv(ws, "A4", "Total"); blank(ws, "B4")
    out.append((wb, truth("T20", "table receiving 0, 1, 30, and 300 rows",
        [field("Total", "A4", "B4", empty=True)],
        [band("Item", 1, 2, 2, "A", ["Item", "Amount"], totals=[{"label":"Total","cell":"B4"}])],
        write={"row_variants": [0, 1, 30, 300]})))

    wb, ws = new_book(); header(ws, 1, 1, ["Item", "Amount"]); reserve(ws, 2, 3, 1, 2); setv(ws, "A4", "Total"); blank(ws, "B4")
    out.append((wb, truth("T21", "three documents stacked with different line counts",
        [field("Total", "A4", "B4", empty=True)],
        [band("Item", 1, 2, 2, "A", ["Item", "Amount"], totals=[{"label":"Total","cell":"B4"}])],
        write={"documents": 3, "document_row_counts": [1, 4, 10]})))

    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    made = []
    for wb, expected in scenarios():
        sid = expected["scenario"]
        xlsx = OUT / f"{sid}.xlsx"
        js = OUT / f"{sid}.truth.json"
        wb.save(xlsx)
        js.write_text(json.dumps(expected, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
        made.append(sid)
    (OUT / "README.md").write_text(
        "# Template layout audit fixtures\n\n"
        "Each `F*.xlsx` or `T*.xlsx` is paired with independently authored "
        "`*.truth.json`. Regenerate them with "
        "`python -m tests.template_layout.generate_scenarios`. The generator "
        "uses no application parser and no model.\n",
        encoding="utf-8",
    )
    print(f"generated {len(made)} scenarios: {', '.join(made)}")


if __name__ == "__main__":
    main()
