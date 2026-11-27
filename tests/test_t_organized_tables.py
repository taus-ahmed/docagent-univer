"""Run T, Organized: what the page shows, laid out as the page is.

Synthetic pages, several vocabularies and layouts each, built through the
project's own PDF generator (tests/run_q_support.make_pdf). Every rule is
stated as a property of positions and printed text; no document is named.

  2   a line with no date and no amount under a row continues that row
  3   side-by-side bands: each band top to bottom, then left to right
  4   stacked headings: two sub-fields, records two lines tall
  7   a trailing minus stays trailing; leading minus and brackets as printed
  8   identifiers keep every printed character; money keeps its decimals
  9   a group line is two cells left of the table; CHECK DATE stays a pair
  10  rows split at the heading's columns; furniture left out; widgets
      beside their labels; one heading per section
"""
from __future__ import annotations

from datetime import datetime

import pdfplumber
import pytest

from tests import run_q_support as Q
from tests.harness import bootstrap as bs

bs.bootstrap()

import organized_layout as O  # noqa: E402


def _layout(tmp_path, pages, size=9, name="p.pdf"):
    pdf = Q.make_pdf(tmp_path / name, pages, size=size)
    return O.layout(pdf)


def _rows(cells):
    out = {}
    for c in cells:
        out.setdefault(c["row"], {})[c["col"]] = c
    return [out[r] for r in sorted(out)]


def _texts(row):
    return [row[c]["text"] for c in sorted(row)]


def _find(rows, text):
    return next(r for r in rows if any(c["text"] == text for c in r.values()))


def _col(rows, text):
    for r in rows:
        for col, c in r.items():
            if c["text"] == text:
                return col
    raise AssertionError(text)


# ── 2: tails ────────────────────────────────────────────────────────────────

BANKS = [
    # (heading, rows: (date, description, debit, credit, balance), tail)
    (("Date", "Description", "Debits", "Credits", "Balance"),
     [("07/14/2024", "Deposit", "", "$209.54", "$654.82"),
      ("07/15/2024", "SHOE RETAIL ACHDEBIT", "$21.70", "", "$633.12"),
      ("07/16/2024", "Deposit", "", "$76.02", "$709.14")], "REF 4471"),
    (("Fecha", "Concepto", "Cargo", "Abono", "Saldo"),
     [("03/22/2024", "Transferencia", "", "$1,000.00", "$5,000.00"),
      ("03/24/2024", "Pago tarjeta", "$250.00", "", "$4,750.00"),
      ("03/29/2024", "Comision", "$3.00", "", "$4,747.00")], "OPER 99812"),
]
X5 = [40, 110, 330, 410, 490]


def _bank_page(head, rows, tail, tail_after=1, tail_gap=9):
    items, y = [(40, 760, "Sample Statement")], 730
    items += [(x, y, h) for x, h in zip(X5, head)]
    y -= 16
    for i, r in enumerate(rows):
        for x, v in zip(X5, r):
            if v:
                items.append((x + (30 if v.startswith("$") else 0), y, v))
        if i == tail_after:
            items.append((X5[1], y - tail_gap, tail))
            y -= tail_gap
        y -= 14
    return items


@pytest.mark.parametrize("head,rows,tail", BANKS)
def test_a_tail_line_continues_its_row(tmp_path, head, rows, tail):
    L = _layout(tmp_path, [_bank_page(head, rows, tail)])
    rr = _rows(L["pages"][0])
    data = [r for r in rr if any(isinstance(c["value"], datetime) for c in r.values())]
    assert len(data) == len(rows)                      # row count matches the page
    assert not any(_texts(r) == tail.split()[::-1] or " ".join(_texts(r)) == tail
                   for r in rr), "the tail became a row of its own"
    second = data[1]
    desc = second[_col(rr, head[1])]["text"]
    assert desc == f"{rows[1][1]} {tail}"


def test_a_footnote_below_the_table_is_not_a_tail(tmp_path):
    head, rows, _ = BANKS[0]
    items = _bank_page(head, rows, "REF 4471")
    items.append((40, 600, "* Indicates a break in sequence"))
    rr = _rows(_layout(tmp_path, [items])["pages"][0])
    assert any(" ".join(_texts(r)) == "* Indicates a break in sequence" for r in rr)


# ── 3: side-by-side bands ──────────────────────────────────────────────────

def _bands_page(head, per_band, xs, sorted_page=True):
    items = [(40, 760, "CHECKS")]
    nb = len(per_band)
    for b in range(nb):
        for k, h in enumerate(head):
            items.append((xs[b][k], 730, h))
    for b, band in enumerate(per_band):
        for i, rec in enumerate(band):
            for k, v in enumerate(rec):
                items.append((xs[b][k], 714 - 12 * i, v))
    return items


@pytest.mark.parametrize("head", [("Number", "Date", "Amount"), ("Cheque", "Fecha", "Montant")])
def test_bands_read_top_to_bottom_then_left_to_right(tmp_path, head):
    bands = [[("4421", "07/22/24", "$12.53"), ("4422", "07/22/24", "$25.00")],
             [("4423", "07/19/24", "$114.00"), ("4424", "07/16/24", "$1,046.66")],
             [("4451", "07/25/24", "$150.00")]]
    xs = [[40, 110, 170], [230, 300, 360], [420, 490, 550]]
    rr = _rows(_layout(tmp_path, [_bands_page(head, bands, xs)])["pages"][0])
    hdr = [r for r in rr if _texts(r) == list(head)]
    assert len(hdr) == 1                                # one heading row, as printed
    nums = [r[min(r)]["text"] for r in rr[rr.index(hdr[0]) + 1:]]
    assert nums == ["4421", "4422", "4423", "4424", "4451"]


def test_two_bands_of_dates_and_amounts(tmp_path):
    head = ("Date", "Amount")
    bands = [[("07/13/24", "$2,860.22"), ("07/14/24", "$2,918.99"), ("07/15/24", "$2,888.81")],
             [("07/25/24", "$11,373.85"), ("07/26/24", "$10,120.07")]]
    xs = [[40, 140], [300, 400]]
    rr = _rows(_layout(tmp_path, [_bands_page(head, bands, xs)])["pages"][0])
    dates = [r[min(r)]["value"] for r in rr if isinstance(r[min(r)]["value"], datetime)]
    assert [d.day for d in dates] == [13, 14, 15, 25, 26]


# ── 4: stacked headings ────────────────────────────────────────────────────

def test_stacked_dates_are_two_sub_fields(tmp_path):
    items = [(40, 760, "Card Statement"),
             (40, 730, "Tran Date"), (120, 730, "Description"), (400, 730, "Amount"),
             (40, 721, "Post Date")]
    y = 705
    for tran, post, desc, amt in [("01/13/2024", "01/14/2024", "FUEL STOP", "41.00"),
                                  ("01/15/2024", "01/17/2024", "GROCERY MART", "88.15")]:
        items += [(40, y, tran), (120, y, desc), (400, y, amt), (40, y - 9, post)]
        y -= 24
    rr = _rows(_layout(tmp_path, [items])["pages"][0])
    hdr = next(r for r in rr if "Tran Date" in _texts(r))
    assert _texts(hdr) == ["Tran Date", "Post Date", "Description", "Amount"]
    recs = [r for r in rr if any(isinstance(c["value"], datetime) for c in r.values())]
    assert len(recs) == 2                               # one row per record
    tcol, pcol = _col(rr, "Tran Date"), _col(rr, "Post Date")
    assert recs[1][tcol]["value"].day == 15 and recs[1][pcol]["value"].day == 17


def test_stacked_money_sub_fields(tmp_path):
    items = [(40, 760, "Loan History"),
             (40, 730, "Date"), (150, 730, "Principal"), (260, 730, "Fees"),
             (150, 721, "Interest"), (260, 721, "Late Fees")]
    y = 705
    for d, p, i, f, lf in [("02/15/2024", "300.00", "45.10", "0.00", "15.00"),
                           ("03/15/2024", "302.25", "42.85", "5.00", "0.00")]:
        items += [(40, y, d), (150, y, p), (260, y, f), (150, y - 9, i), (260, y - 9, lf)]
        y -= 24
    rr = _rows(_layout(tmp_path, [items])["pages"][0])
    hdr = next(r for r in rr if "Principal" in _texts(r))
    assert _texts(hdr) == ["Date", "Principal", "Interest", "Fees", "Late Fees"]
    first = next(r for r in rr if any(isinstance(c["value"], datetime) for c in r.values()))
    got = {h: first[_col(rr, h)]["value"] for h in ("Principal", "Interest", "Fees", "Late Fees")}
    assert got == {"Principal": 300.0, "Interest": 45.1, "Fees": 0.0, "Late Fees": 15.0}


# ── 7: signs ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("printed,value,fmt", [
    ("26.08-", -26.08, "#,##0.00;#,##0.00-"),
    ("$1,204.00-", -1204.0, '"$"#,##0.00;"$"#,##0.00-'),
    ("-26.08", -26.08, "#,##0.00"),
    ("(26.08)", -26.08, "#,##0.00_);(#,##0.00)"),
    ("26.08", 26.08, "#,##0.00"),
    ("75.00", 75.0, "#,##0.00"),
    ("1,050", 1050.0, "#,##0"),
])
def test_sign_and_decimals_as_printed(printed, value, fmt):
    v, f = O.typed(printed)
    assert (v, f) == (value, fmt)


def test_trailing_minus_in_a_table(tmp_path):
    items = [(40, 760, "Statement"), (40, 730, "Date"), (120, 730, "Description"),
             (400, 730, "Amount"),
             (40, 714, "05/21/2024"), (120, 714, "Payment received"), (400, 714, "26.08-"),
             (40, 700, "05/22/2024"), (120, 700, "Purchase"), (400, 700, "19.99")]
    rr = _rows(_layout(tmp_path, [items])["pages"][0])
    c = _find(rr, "26.08-")[_col(rr, "26.08-")]
    assert c["value"] == -26.08 and c["number_format"] == "#,##0.00;#,##0.00-"


# ── 8: identifiers ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("printed,label", [("0025", None), ("021000021", None),
                                           ("26007893", "P.O."), ("917845", "CHECK #"),
                                           ("85004", "ZIP"), ("2937", "INVOICE")])
def test_identifiers_stay_text(printed, label):
    assert O.typed(printed, None, label) == (printed, None)


def test_a_count_is_still_a_number():
    assert O.typed("40", None, "Qty") == (40, "#,##0")


def test_a_column_mixing_padded_and_plain_numbers_stays_text(tmp_path):
    items = [(40, 760, "Invoice List"), (40, 730, "Ref"), (120, 730, "Date"), (300, 730, "Net"),
             (40, 714, "0025"), (120, 714, "06/22/2026"), (300, 714, "75.00"),
             (40, 700, "2937"), (120, 700, "06/16/2026"), (300, 700, "2,480.00")]
    rr = _rows(_layout(tmp_path, [items])["pages"][0])
    col = _col(rr, "0025")
    assert _find(rr, "2937")[col]["value"] == "2937"
    assert _find(rr, "0025")[col]["value"] == "0025"
    assert _find(rr, "75.00")[_col(rr, "75.00")]["number_format"] == "#,##0.00"


# ── 9: group lines ─────────────────────────────────────────────────────────

GROUPED = [
    ("INVOICE", "INV DATE", "NET", [("300055 ANDERSON SUPPLY", [("0025", "06/22/2026", "75.00")]),
                                    ("299694 HILL LAWN CARE", [("2937", "06/16/2026", "2,480.00"),
                                                               ("2938", "06/17/2026", "2,400.00")])]),
    ("DOC", "FECHA", "IMPORTE", [("C-1180 NORTE FOODS", [("A-77", "02/01/2024", "10.00")]),
                                 ("C-1190 SUR METALS", [("A-78", "02/02/2024", "20.00")])]),
]


@pytest.mark.parametrize("h1,h2,h3,groups", GROUPED)
def test_a_group_line_is_two_cells_left_of_the_table(tmp_path, h1, h2, h3, groups):
    items, y = [(40, 760, "VENDOR LIST"), (40, 730, h1), (120, 730, h2), (300, 730, h3)], 714
    for line, rows in groups:
        items.append((52, y, line))
        y -= 14
        for r in rows:
            items += [(40, y, r[0]), (120, y, r[1]), (300, y, r[2])]
            items += [(52, y - 8, "CHECK DATE:"), (130, y - 8, "06/24/2026")]
            y -= 22
    rr = _rows(_layout(tmp_path, [items])["pages"][0])
    hdr = next(r for r in rr if h1 in _texts(r))
    assert _texts(hdr) == [h1, h2, h3]                  # the heading row as printed
    first_col = min(c for c, x in hdr.items() if x["text"] == h1)
    for line, _rows_ in groups:
        ident, name = line.split(" ", 1)
        g = _find(rr, ident)
        assert _texts(g) == [ident, name]               # split, never glued
        assert max(g) < first_col                       # never in the table's columns
    pair = _find(rr, "CHECK DATE")
    assert [c["kind"] for c in pair.values()] == ["label", "value"]
    assert isinstance(list(pair.values())[1]["value"], datetime)


# ── 10: splitting, furniture, forms ────────────────────────────────────────

def test_a_row_is_split_at_the_headings_columns(tmp_path):
    # ordinary word spacing between columns: one segment to the gutter rule
    head = [(36, "INVOICE"), (163, "INV DATE"), (247, "CHECK RUN"), (297, "CHECK #"),
            (369, "INVOICE NET"), (434, "PAID AMOUNT"), (488, "DUE DATE"), (527, "TYPE"),
            (553, "STS"), (574, "DESCR")]
    row = [(36, "0025"), (163, "06/22/2026"), (247, "H062426"), (297, "20218284"),
           (382, "75.00"), (461, "75.00"), (488, "07/22/2026"), (534, "INV"), (553, "PD"),
           (574, "STRING")]
    row2 = [(36, "2937"), (163, "06/16/2026"), (247, "H062426"), (297, "917846"),
            (369, "2,480.00"), (449, "2,480.00"), (488, "07/16/2026"), (534, "INV"),
            (553, "PD"), (574, "Right")]
    items = [(36, 760, "VENDOR INVOICE LIST")] + [(x, 730, t) for x, t in head] \
        + [(x, 714, t) for x, t in row] + [(x, 700, t) for x, t in row2] \
        + [(36, 640, "Report generated 06/24/2026 14:36"), (520, 640, "Page 1"),
           (36, 628, "User: jdoe"), (36, 616, "Program ID: AP4410")]
    rr = _rows(_layout(tmp_path, [items], size=7)["pages"][0])
    hdr = next(r for r in rr if "INVOICE" in _texts(r))
    assert _texts(hdr) == [t for _x, t in head]
    first = _find(rr, "0025")
    assert len(first) == len(row)                       # one cell per printed column
    for (_x, h), (_x2, v) in zip(head, row):
        assert first[_col(rr, h)]["text"] == v, h
    flat = " ".join(" ".join(_texts(r)) for r in rr)
    for furn in ("Report generated", "Page 1", "jdoe", "AP4410"):
        assert furn not in flat


def test_one_heading_per_section_across_pages(tmp_path):
    def page(y0, rows, cont):
        items = [(40, 760, "TRANSACTIONS" + (" (continued)" if cont else "")),
                 (40, 740, "Date"), (120, 740, "Description"), (400, 740, "Amount")]
        for i, (d, t, a) in enumerate(rows):
            items += [(40, 724 - 14 * i, d), (120, 724 - 14 * i, t), (400, 724 - 14 * i, a)]
        return items
    L = _layout(tmp_path, [page(0, [("01/22/2024", "Rent", "900.00"),
                                    ("01/23/2024", "Power", "61.20")], False),
                           page(0, [("01/29/2024", "Water", "30.00"),
                                    ("01/30/2024", "Phone", "45.00")], True)])
    p2 = _rows(L["pages"][1])
    flat2 = [" ".join(_texts(r)) for r in p2]
    assert not any("TRANSACTIONS" in t or t.startswith("Date") for t in flat2)
    p1 = _rows(L["pages"][0])
    amt1 = _col(p1, "Amount")
    assert _find(p2, "30.00")[amt1]["value"] == 30.0     # under page 1's heading


def test_widget_values_sit_beside_their_labels(tmp_path):
    pdf = Q.make_pdf(tmp_path / "f.pdf", [[(40, 760, "Application Form"),
                                           (40, 730, "Employee Name:"), (40, 710, "ZIP:"),
                                           (40, 690, "Start Date:"), (300, 730, "Dept:"),
                                           (40, 670, "Signature")]], size=9)
    widgets = [{"x0": 120, "x1": 250, "top": 792 - 738, "bottom": 792 - 728, "value": "Jane Q Sample"},
               {"x0": 120, "x1": 200, "top": 792 - 718, "bottom": 792 - 708, "value": "03087"},
               {"x0": 120, "x1": 200, "top": 792 - 698, "bottom": 792 - 688, "value": "08/21/2024"}]
    with pdfplumber.open(str(pdf)) as doc:
        cells, _ = O.page_cells(doc.pages[0], widgets=widgets)
    rr = _rows(cells)
    name = _find(rr, "Employee Name")
    assert "Jane Q Sample" in _texts(name)
    z = _find(rr, "ZIP")
    assert [c["value"] for c in z.values()][-1] == "03087"
    sd = _find(rr, "Start Date")
    assert isinstance([c["value"] for c in sd.values()][-1], datetime)


def test_glued_word_and_figure_are_two_tokens(tmp_path):
    items = [(40, 760, "Summary"), (40, 740, "Number of Checks8"),
             (300, 740, "Total Amount of Checks$1,783.32"), (40, 720, "Ref INV2024 kept")]
    rr = _rows(_layout(tmp_path, [items])["pages"][0])
    flat = " | ".join(" ".join(_texts(r)) for r in rr)
    assert "Checks 8" in flat and "Checks $1,783.32" in flat and "INV2024" in flat
