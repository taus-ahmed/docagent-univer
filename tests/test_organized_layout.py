"""Run R, Part 2 (v1) — the organized layout (docs/ORGANIZED_LAYOUT_SPEC.md).

Synthetic tests always run; the real tests compare utah_paystub_2 with the
owner's partner's sheet (local_docs/syed/syed_sheet1_job127.xlsx, "Sheet1")
and skip when local_docs is absent.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.run_q_support import make_pdf  # noqa: E402
from tests.harness import bootstrap as bs  # noqa: E402

bs.bootstrap()

import organized_layout as OL  # noqa: E402


def _gen():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "make_scan_variants", ROOT / "tests" / "fixtures" / "make_scan_variants.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    return gen


def _cells(pdf):
    lay = OL.layout(pdf)
    assert lay["pages"], lay["skipped"]
    return {(c["row"], c["col"]): c for c in lay["pages"][0]}


def _find(cells, text):
    hit = [c for c in cells.values() if c["text"] == text]
    assert hit, (text, sorted(c["text"] for c in cells.values()))
    return hit[0]


STUB = [
    (72, 740, "Employer Name: ACME Corp"), (330, 740, "Address: 1 Main St, Springfield"),
    (378, 728, "IL 62701"),
    (72, 700, "Employee Name:"), (180, 700, "Jane Roe"),
    (330, 700, "Employee ID No:"), (378, 700, "E-77"),
    (72, 640, "Pay Date From"), (220, 640, "Pay Date To"),
    (72, 626, "08/01/2020"), (220, 626, "08/31/2020"),
    (72, 580, "Earnings"),
    (180, 560, "Rate"), (260, 560, "Hours"), (330, 560, "Current"),
    (72, 546, "Regular"), (180, 546, "$32.00"), (260, 546, "180"), (330, 546, "$5,760.00"),
    (72, 480, "This statement is provided for your records and should be kept in a safe place."),
]


class TestSynthetic:
    def test_pairs_side_by_side_without_the_colon(self, tmp_path):
        c = _cells(make_pdf(tmp_path / "s.pdf", [STUB]))
        emp, name = _find(c, "Employer Name"), _find(c, "ACME Corp")
        addr = _find(c, "Address")
        assert emp["kind"] == "label" and name["kind"] == "value"
        assert emp["row"] == name["row"] == addr["row"]
        assert emp["col"] < name["col"] < addr["col"]
        assert not any(x["text"].endswith(":") for x in c.values())

    def test_a_wrapped_value_continues(self, tmp_path):
        c = _cells(make_pdf(tmp_path / "s.pdf", [STUB]))
        _find(c, "1 Main St, Springfield IL 62701")

    def test_a_label_and_its_value_in_separate_segments(self, tmp_path):
        c = _cells(make_pdf(tmp_path / "s.pdf", [STUB]))
        lab, val = _find(c, "Employee Name"), _find(c, "Jane Roe")
        assert lab["row"] == val["row"] and val["kind"] == "value"

    def test_header_over_values_is_bold_and_centred(self, tmp_path):
        c = _cells(make_pdf(tmp_path / "s.pdf", [STUB]))
        for t in ("Pay Date From", "Pay Date To", "Rate", "Hours", "Current"):
            h = _find(c, t)
            assert h["kind"] == "header" and h["bold"] and h["align"] == "center", t
        d = _find(c, "08/01/2020")
        assert d["value"] == datetime(2020, 8, 1) and d["number_format"] == "mm/dd/yyyy"
        assert d["col"] == _find(c, "Pay Date From")["col"]

    def test_money_is_a_number_and_nothing_is_invented(self, tmp_path):
        c = _cells(make_pdf(tmp_path / "s.pdf", [STUB]))
        m = _find(c, "$5,760.00")
        assert m["value"] == 5760.0 and "$" in m["number_format"]
        assert _find(c, "180")["value"] == 180
        rate = _find(c, "Rate")
        assert not any(x["row"] == rate["row"] and x["col"] < rate["col"] for x in c.values())

    def test_paragraph_text_is_not_copied(self, tmp_path):
        c = _cells(make_pdf(tmp_path / "s.pdf", [STUB]))
        assert not any("safe place" in x["text"] for x in c.values())

    def test_a_paragraphs_wrapped_tail_is_not_copied(self, tmp_path):
        page = STUB + [(72, 466, "kept for at least seven years by the employee,"),
                       (72, 452, "then shredded."),
                       (72, 420, "Net Pay:"), (180, 420, "$5,731.00")]
        c = _cells(make_pdf(tmp_path / "s.pdf", [page]))
        assert not any("shredded" in x["text"] or "seven years" in x["text"] for x in c.values())
        assert _find(c, "Net Pay")["kind"] == "label"

    def test_red_markup_is_not_copied(self, tmp_path):
        gen = _gen()
        body = gen._text_ops([(x, y, 10, t) for x, y, t in STUB], 0)
        red = gen._text_ops([(300, 600, 14, "1. Student's name")], 0)
        ops = body + b"\n1 0 0 rg\n" + red
        p = tmp_path / "m.pdf"
        p.write_bytes(gen.build_pdf([{"w_pt": 612.0, "h_pt": 792.0, "ops": ops}]))
        c = _cells(p)
        assert not any("Student" in x["text"] for x in c.values())

    def test_a_page_with_no_text_layer_is_said(self, tmp_path):
        gen = _gen()
        p = tmp_path / "blank.pdf"
        p.write_bytes(gen.build_pdf([{"w_pt": 612.0, "h_pt": 792.0, "ops": b""}]))
        lay = OL.layout(p)
        assert lay["pages"] == [] and lay["skipped"] == ["page 1: no text layer on this page"]


# ── utah_paystub_2 against the partner's sheet ──────────────────────────────

def _need(path):
    if not path.is_file():
        pytest.skip(f"{path.name} not present (git-ignored local_docs)")
    return path


def _syed():
    import openpyxl
    p = _need(ROOT / "local_docs" / "syed" / "syed_sheet1_job127.xlsx")
    ws = openpyxl.load_workbook(p)["Sheet1"]
    return {(c.row, c.column): c for r in ws.iter_rows() for c in r if c.value is not None}


def _ours(tmp_path):
    import openpyxl
    hits = list((ROOT / "local_docs" / "DocAgent_testdocs").rglob("utah_paystub_2.pdf")) \
        if (ROOT / "local_docs").is_dir() else []
    if not hits:
        pytest.skip("utah_paystub_2.pdf not present (git-ignored local_docs)")
    from app.services.excel_organized import organized_workbook
    wb = organized_workbook([(hits[0].name, hits[0])])
    p = tmp_path / "o.xlsx"
    wb.save(p)
    ws = openpyxl.load_workbook(p).worksheets[0]
    return {(c.row, c.column): c for r in ws.iter_rows() for c in r if c.value is not None}


def _by_text(cells):
    out = {}
    for (r, col), c in sorted(cells.items()):
        if isinstance(c.value, str):
            out.setdefault(c.value.strip().rstrip(":").strip(), []).append((r, col, c))
    return out


#: the partner's labels that are the page's own words (two are renamed there:
#: "Pay Period From" for "Payment Period (From)", "Employee Address")
SAME = ["Employer Name", "Employee Name", "Employee ID No", "Position/Title",
        "Payment Method", "Payment Date", "Earnings", "Rate", "Hours", "Current Total",
        "YTD (Year to Date)", "Regular", "Gross Pay", "Deductions", "Medicare",
        "Social Security", "Federal Tax", "UtahTax", "Total Deduction", "Net Pay"]


class TestAgainstThePartnersSheet:
    def test_every_shared_label_is_in_the_same_column_and_order(self, tmp_path):
        syed, ours = _by_text(_syed()), _by_text(_ours(tmp_path))
        rows_s, rows_o = [], []
        for lab in SAME:
            assert lab in ours, (lab, sorted(ours))
            for (rs, cs, _), (ro, co, _) in zip(syed[lab], ours[lab]):
                assert cs == co, (lab, cs, co)
                rows_s.append((rs, lab))
                rows_o.append((ro, lab))
        assert [lab for _r, lab in sorted(rows_s)] == [lab for _r, lab in sorted(rows_o)]

    def test_pairs_on_one_row_stay_on_one_row(self, tmp_path):
        ours = _by_text(_ours(tmp_path))
        for a, b in (("Employer Name", "ABC Company"), ("Employee Name", "John Smith"),
                     ("Employee ID No", "ID-2398"), ("Position/Title",
                                                     "Marketing Operations Specialist"),
                     ("Employer Name", "Address")):
            assert ours[a][0][0] == ours[b][0][0], (a, b)
        assert ours["Address"][0][1] == 4                       # D, as the partner's
        assert "3537 Rubaiyat Road, Grand Rapids, MI, 49503" in ours

    def test_values_sit_where_the_partner_put_them(self, tmp_path):
        syed, ours = _syed(), _ours(tmp_path)

        def col_of(cells, value):
            return sorted(col for (_r, col), c in cells.items() if c.value == value)
        for v in (5760, 46080, 5820, 46560, 40, 320, 5731, 45848):
            assert col_of(ours, v) == col_of(syed, v), v
        for d in (datetime(2020, 8, 1), datetime(2020, 8, 31), datetime(2020, 9, 1)):
            assert col_of(ours, d) == col_of(syed, d)
            c = next(c for c in ours.values() if c.value == d)
            assert c.number_format == "mm/dd/yyyy"
        money = next(c for c in ours.values() if c.value == 5760)
        assert "$" in money.number_format

    def test_formatting_comes_from_the_page(self, tmp_path):
        ours = _by_text(_ours(tmp_path))
        title = ours["Pay Stub"][0][2]
        assert title.font.b and title.alignment.horizontal == "center"
        assert (ours["Pay Stub"][0][0], ours["Pay Stub"][0][1]) == (1, 4)   # D1, as the partner's
        for lab in ("Employer Name", "Employee Name", "Payment Method", "Deductions"):
            assert ours[lab][0][2].font.b, lab                 # printed in Arial-Bold
        assert not ours["John Smith"][0][2].font.b              # printed in Arial
        for h in ("Rate", "Hours", "Current Total", "YTD (Year to Date)"):
            for _r, _c, cell in ours[h]:
                assert cell.font.b and cell.alignment.horizontal == "center", h
        assert not any(c.fill.fill_type for v in ours.values() for _r, _c, c in v)

    def test_the_reviewers_red_notes_are_not_copied(self, tmp_path):
        texts = " ".join(_by_text(_ours(tmp_path)))
        assert "Student" not in texts and "physical presence" not in texts
