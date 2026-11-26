"""Run S, Stage 2 — the organized layout for every text-layer PDF
(docs/ORGANIZED_LAYOUT_SPEC.md, v2 rules 11-17).

Synthetic PDFs carry real fonts (Helvetica, -Bold, -Oblique) and real
drawing operators (lines, rectangles), so bold, italic, underline and thick
rules are read the way they are read from a real page. Placement is by x/y:
the same page drawn in a shuffled order must lay out identically. The real
corpus test runs every text-layer PDF in local_docs and skips when absent.
"""
from __future__ import annotations

import random
import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.harness import bootstrap as bs  # noqa: E402

bs.bootstrap()

import organized_layout as OL  # noqa: E402

FONTS = {"R": "Helvetica", "B": "Helvetica-Bold", "I": "Helvetica-Oblique"}


def make_pdf(path, pages, shuffle=None, w=612.0, h=792.0):
    """pages: [[item]] where an item is ("t", x, y, size, text, font) or
    ("l", x1, y1, x2, y2, width) or ("r", x, y, w, h) (a filled rectangle).
    `shuffle`: a seed - the page's operators are drawn in a random order."""
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = PdfWriter()
    fonts = {}
    for key, base in FONTS.items():
        fonts[key] = writer._add_object(DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/" + base),
            NameObject("/Encoding"): NameObject("/WinAnsiEncoding")}))
    for items in pages:
        items = list(items)
        if shuffle is not None:
            random.Random(shuffle).shuffle(items)
        ops = []
        for it in items:
            if it[0] == "t":
                _k, x, y, size, text, font = it
                esc = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                ops.append(f"BT /F{font} {size} Tf 1 0 0 1 {x} {y} Tm ({esc}) Tj ET")
            elif it[0] == "l":
                _k, x1, y1, x2, y2, lw = it
                ops.append(f"{lw} w {x1} {y1} m {x2} {y2} l S")
            elif it[0] == "r":
                _k, x, y, rw, rh = it
                ops.append(f"{x} {y} {rw} {rh} re f")
        page = writer.add_blank_page(w, h)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({
                NameObject(f"/F{k}"): v for k, v in fonts.items()})})
        s = DecodedStreamObject()
        s.set_data("\n".join(ops).encode("cp1252", "replace"))
        page[NameObject("/Contents")] = writer._add_object(s)
    with open(path, "wb") as fh:
        writer.write(fh)
    return Path(path)


def T(x, y, text, size=10, font="R"):
    return ("t", x, y, size, text, font)


def _all(lay):
    return [c for p in lay["pages"] for c in p]


def _find(lay, text):
    hit = [c for c in _all(lay) if c["text"] == text]
    assert hit, (text, sorted(c["text"] for c in _all(lay)))
    return hit[0]


STATEMENT_PAGE = [
    T(220, 750, "ACME BANK STATEMENT", 16, "B"),
    T(72, 720, "Account Number:"), T(170, 720, "4411-2290"),
    T(330, 720, "Statement Date:"), T(430, 720, "08/31/2020"),
    T(72, 680, "Date", 10, "B"), T(150, 680, "Description", 10, "B"),
    T(360, 680, "Amount", 10, "B"), T(450, 680, "Balance", 10, "B"),
    T(72, 664, "08/03/2020"), T(150, 664, "PAYROLL DEPOSIT"),
    T(360, 664, "1,250.00"), T(450, 664, "4,250.00"),
    T(72, 650, "08/09/2020"), T(150, 650, "CARD PURCHASE"),
    T(360, 650, "45.10"), T(450, 650, "4,204.90"),
]


# ── 2b: placement is by position, never by drawing order ────────────────────

def test_a_shuffled_content_stream_lays_out_identically(tmp_path):
    a = OL.layout(make_pdf(tmp_path / "a.pdf", [STATEMENT_PAGE]))
    for seed in (1, 2, 3):
        b = OL.layout(make_pdf(tmp_path / f"b{seed}.pdf", [STATEMENT_PAGE], shuffle=seed))
        key = lambda c: (c["row"], c["col"], c["text"])  # noqa: E731
        assert sorted(map(key, _all(a))) == sorted(map(key, _all(b)))


def test_an_irregular_form_places_each_value_beside_its_label(tmp_path):
    # labels at uneven x, values right-aligned at different x, drawn last-first
    items = [T(400, 700, "Invoice No:"), T(470, 700, "INV-0091"),
             T(72, 700, "Bill To:"), T(120, 700, "Harbor Foods"),
             T(72, 684, "Ship To:"), T(125, 684, "Delta Bakery"),
             T(400, 684, "Due:"), T(470, 684, "09/15/2020")]
    lay = OL.layout(make_pdf(tmp_path / "f.pdf", [items], shuffle=7))
    for lab, val in (("Invoice No", "INV-0091"), ("Bill To", "Harbor Foods"),
                     ("Ship To", "Delta Bakery"), ("Due", None)):
        lc = _find(lay, lab)
        if val:
            vc = _find(lay, val)
            assert vc["row"] == lc["row"] and vc["col"] > lc["col"]


# ── 2c: one header row per table, no furniture ─────────────────────────────

def _two_pages():
    p1 = STATEMENT_PAGE + [T(270, 40, "Page 1 of 2", 8)]
    p2 = [T(220, 750, "ACME BANK STATEMENT", 16, "B"),
          T(72, 680, "Date", 10, "B"), T(150, 680, "Description", 10, "B"),
          T(360, 680, "Amount", 10, "B"), T(450, 680, "Balance", 10, "B"),
          T(72, 664, "08/14/2020"), T(150, 664, "UTILITY PAYMENT"),
          T(360, 664, "74.98"), T(450, 664, "4,129.92"),
          T(270, 40, "Page 2 of 2", 8)]
    return [p1, p2]


def test_headings_and_title_reprinted_on_page_two_are_written_once(tmp_path):
    lay = OL.layout(make_pdf(tmp_path / "s.pdf", _two_pages()))
    texts = [c["text"] for c in _all(lay)]
    assert texts.count("Description") == 1
    assert texts.count("ACME BANK STATEMENT") == 1
    assert "UTILITY PAYMENT" in texts and "74.98" in [c["text"] for c in _all(lay)]


def test_page_numbers_are_not_copied(tmp_path):
    lay = OL.layout(make_pdf(tmp_path / "s.pdf", _two_pages()))
    assert not any(re.search(r"Page \d", c["text"]) for c in _all(lay))


# ── 2d: formatting from the page ───────────────────────────────────────────

def test_bold_and_italic_come_from_the_font(tmp_path):
    items = STATEMENT_PAGE + [T(72, 600, "Note", 10, "I"), T(150, 600, "pending items", 10, "I")]
    lay = OL.layout(make_pdf(tmp_path / "s.pdf", [items]))
    assert _find(lay, "Description")["bold"] and not _find(lay, "CARD PURCHASE")["bold"]
    assert _find(lay, "pending items")["italic"]


def test_underline_is_read_from_the_line_drawn_under_a_segment(tmp_path):
    items = STATEMENT_PAGE + [T(72, 600, "Summary of Fees"), ("l", 72, 598, 150, 598, 0.8)]
    lay = OL.layout(make_pdf(tmp_path / "s.pdf", [items]))
    assert _find(lay, "Summary of Fees")["underline"]
    assert not _find(lay, "CARD PURCHASE").get("underline")


def test_a_thick_rule_gives_the_row_above_it_a_thick_bottom_border(tmp_path):
    items = STATEMENT_PAGE + [("l", 60, 645, 540, 645, 2.0),
                              T(72, 630, "Ending Balance:"), T(450, 630, "4,204.90")]
    lay = OL.layout(make_pdf(tmp_path / "s.pdf", [items]))
    row = _find(lay, "CARD PURCHASE")["row"]
    above = [c for c in _all(lay) if c["row"] == row]
    assert above and all(c.get("border_bottom") == "thick" for c in above)
    assert not _find(lay, "PAYROLL DEPOSIT").get("border_bottom")


def test_a_line_centred_on_the_page_is_centred(tmp_path):
    items = STATEMENT_PAGE + [T(250, 600, "Thank you for banking", 10)]
    lay = OL.layout(make_pdf(tmp_path / "s.pdf", [items]))
    c = _find(lay, "Thank you for banking")
    assert c["align"] == "center"
    assert _find(lay, "CARD PURCHASE")["align"] is None


def test_every_date_is_a_real_date_in_one_format(tmp_path):
    items = [T(72, 720, "Issued:"), T(140, 720, "Aug 1, 2020"),
             T(72, 704, "Due:"), T(140, 704, "2020-09-15"),
             T(72, 688, "Paid:"), T(140, 688, "20/09/20"),
             T(72, 672, "Ref Date:"), T(140, 672, "13/08/2020"),
             T(72, 656, "Other:"), T(140, 656, "03/04/2020"),
             T(72, 640, "Code:"), T(140, 640, "INV-1")]
    lay = OL.layout(make_pdf(tmp_path / "d.pdf", [items]))
    got = {c["text"]: c for c in _all(lay)}
    want = {"Aug 1, 2020": datetime(2020, 8, 1), "2020-09-15": datetime(2020, 9, 15),
            "13/08/2020": datetime(2020, 8, 13),
            # the document writes day first (13/08), so 03/04 is 3 April
            "03/04/2020": datetime(2020, 4, 3)}
    for text, d in want.items():
        assert got[text]["value"] == d, text
        assert got[text]["number_format"] == "mm/dd/yyyy"
    formats = {c["number_format"] for c in _all(lay) if isinstance(c["value"], datetime)}
    assert formats == {"mm/dd/yyyy"}


def test_an_unsettled_date_stays_as_printed(tmp_path):
    items = [T(72, 720, "Other:"), T(140, 720, "03/04/2020"),
             T(72, 704, "Code:"), T(140, 704, "INV-1"),
             T(72, 688, "Account holder name:"), T(200, 688, "Pat Lee")]
    lay = OL.layout(make_pdf(tmp_path / "d.pdf", [items]))
    c = _find(lay, "03/04/2020")
    # US order is the default only when nothing on the page contradicts it
    assert c["value"] == datetime(2020, 3, 4) or c["value"] == "03/04/2020"


def test_the_writer_writes_underline_and_the_thick_border(tmp_path):
    import openpyxl
    from app.services.excel_organized import write_layout
    items = STATEMENT_PAGE + [("l", 60, 645, 540, 645, 2.0),
                              T(72, 600, "Summary of Fees"), ("l", 72, 598, 150, 598, 0.8)]
    lay = OL.layout(make_pdf(tmp_path / "s.pdf", [items]))
    wb = openpyxl.Workbook()
    write_layout(wb.active, lay)
    cells = {c.value: c for r in wb.active.iter_rows() for c in r if c.value is not None}
    assert cells["Summary of Fees"].font.u == "single"
    assert cells["CARD PURCHASE"].border.bottom.style == "thick"
    assert not any(c.fill and c.fill.fill_type for c in cells.values())


# ── 2e: families (synthetic) and the real corpus ───────────────────────────

FAMILIES = {
    "invoice": [T(220, 750, "INVOICE", 16, "B"),
                T(72, 720, "Invoice No:"), T(160, 720, "INV-2020-77"),
                T(330, 720, "Date:"), T(400, 720, "08/12/2020"),
                T(72, 680, "Item", 10, "B"), T(250, 680, "Qty", 10, "B"),
                T(330, 680, "Unit Price", 10, "B"), T(450, 680, "Total", 10, "B"),
                T(72, 664, "Widget A"), T(250, 664, "2"), T(330, 664, "$10.00"),
                T(450, 664, "$20.00"),
                T(72, 650, "Widget B"), T(250, 650, "1"), T(330, 650, "$5.50"),
                T(450, 650, "$5.50"),
                T(330, 620, "Subtotal:"), T(450, 620, "$25.50")],
    "purchase_order": [T(200, 750, "PURCHASE ORDER", 16, "B"),
                       T(72, 720, "PO Number:"), T(160, 720, "PO-5521"),
                       T(72, 680, "Line", 10, "B"), T(130, 680, "Description", 10, "B"),
                       T(380, 680, "Qty", 10, "B"), T(450, 680, "Amount", 10, "B"),
                       T(72, 664, "1"), T(130, 664, "Copier paper"), T(380, 664, "10"),
                       T(450, 664, "45.00")],
    "w2": [T(72, 740, "a Employee's social security number"), T(72, 728, "XXX-XX-1234"),
           T(300, 740, "1 Wages, tips, other compensation"), T(300, 728, "28,000.00"),
           T(450, 740, "2 Federal income tax withheld"), T(450, 728, "2,400.00"),
           T(300, 700, "3 Social security wages"), T(300, 688, "28,000.00")],
    "1099": [T(72, 740, "PAYER'S TIN"), T(72, 728, "12-3456789"),
             T(300, 740, "1 Nonemployee compensation"), T(300, 728, "$ 8,525.00"),
             T(300, 700, "4 Federal income tax withheld"), T(300, 688, "$ 0.00")],
    "1098": [T(72, 740, "RECIPIENT'S/LENDER'S TIN"), T(72, 728, "98-7654321"),
             T(300, 740, "1 Mortgage interest received from payer(s)/borrower(s)"),
             T(300, 728, "$ 6,212.45"), T(300, 700, "2 Outstanding mortgage principal"),
             T(300, 688, "$ 182,000.00")],
    "receipt": [T(240, 750, "CORNER CAFE", 14, "B"), T(72, 720, "Latte"),
                T(300, 720, "4.50"), T(72, 706, "Muffin"), T(300, 706, "3.25"),
                T(72, 680, "Total"), T(300, 680, "7.75")],
    "pay_stub": [T(250, 750, "Pay Stub", 16, "B"),
                 T(72, 720, "Employee Name:"), T(170, 720, "Jane Roe"),
                 T(72, 690, "Rate", 10, "B"), T(150, 690, "Hours", 10, "B"),
                 T(250, 690, "Current", 10, "B"),
                 T(72, 676, "$32.00"), T(150, 676, "80"), T(250, 676, "$2,560.00")],
}

_FIG = re.compile(r"\d")


def _figures_printed(items):
    out = []
    for it in items:
        if it[0] == "t":
            for tok in it[4].split():
                if _FIG.search(tok) and not re.fullmatch(r"\d{1,2}", tok):
                    out.append(tok)
    return out


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_every_family_keeps_every_figure_and_its_labels(tmp_path, family):
    items = FAMILIES[family]
    lay = OL.layout(make_pdf(tmp_path / f"{family}.pdf", [items], shuffle=3))
    text = " ".join(c["text"] for c in _all(lay))
    flat = text.replace(" ", "")
    for f in _figures_printed(items):
        assert f.replace(" ", "") in flat, (family, f, text)
    assert not any(c["text"].endswith(":") for c in _all(lay))
    assert not any(c["text"] == "Description" for c in _all(lay)
                   if family not in ("purchase_order",))
    # one cell per address
    addrs = [(c["row"], c["col"]) for c in lay["pages"][0]]
    assert len(addrs) == len(set(addrs))


def _corpus_pdfs():
    src = ROOT / "local_docs" / "DocAgent_testdocs"
    if not src.is_dir():
        return []
    return sorted(p for p in src.rglob("*.pdf"))


def test_real_corpus_every_figure_on_a_laid_out_page_reaches_a_cell():
    pdfs = _corpus_pdfs()
    if not pdfs:
        pytest.skip("local_docs/DocAgent_testdocs not present (git-ignored real data)")
    lost, laid = {}, 0
    for p in pdfs:
        rep = OL.audit(p)
        if rep is None:
            continue
        laid += 1
        if rep["lost"]:
            lost[p.name] = rep["lost"][:5]
    assert laid >= 30
    assert lost == {}, lost
