"""Run T2, Stage 5: stacked and spanning headings, repeated column groups,
side-by-side blocks, paragraphs and bullets, charts (invented text)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.harness import bootstrap as bs  # noqa: E402

bs.bootstrap()

import perception as P  # noqa: E402
import structure_engine as S  # noqa: E402
from tests import t1_pdf  # noqa: E402


def _right(x_right, y, text, size=10):
    return (x_right - 0.556 * size * len(text), y, text)


def _lay(tmp_path, pages, name="d.pdf"):
    return S.layout_document(P.read_document(t1_pdf.make(tmp_path / name, pages)))


def _heads(cells):
    return {(c["row"], c["col"]): c["text"] for c in cells if c.get("kind") == "header"}


def _find(cells, text):
    return next(c for c in cells if c["text"] == text)


def test_a_two_line_heading_is_one_joined_label_per_column(tmp_path):
    items = [(40, 720, "Tran"), (110, 720, "Post"), (300, 720, "Debit"),
             (40, 711, "Date"), (110, 711, "Date"), (300, 711, "Amount")]
    y = 696
    for i in range(3):
        items += [(40, y, f"01/0{i + 1}/30"), (110, y, f"01/0{i + 2}/30"), _right(340, y, f"{i}.50")]
        y -= 14
    cells = _lay(tmp_path, [items])["pages"][0]
    assert sorted(_heads(cells).values()) == ["Debit Amount", "Post Date", "Tran Date"]


def test_a_heading_spanning_two_columns_is_its_own_header_row(tmp_path):
    items = [(40, 730, "Kind"), (205, 730, "Paid In"), (330, 730, "Paid Out"),
             (180, 718, "Items"), (240, 718, "Amount"), (300, 718, "Items"), (365, 718, "Amount")]
    y = 702
    for i, k in enumerate(("Alpha", "Beta", "Gamma")):
        items += [(40, y, k), _right(205, y, str(i + 1)), _right(285, y, f"{i}.25"),
                  _right(325, y, str(i + 4)), _right(410, y, f"{i}.75")]
        y -= 14
    cells = _lay(tmp_path, [items])["pages"][0]
    heads = _heads(cells)
    group_row = min(r for r, _c in heads)
    groups = sorted(t for (r, _c), t in heads.items() if r == group_row)
    assert groups == ["Paid In", "Paid Out"]
    labels = sorted(t for (r, _c), t in heads.items() if r == group_row + 1)
    assert labels.count("Items") == 2 and labels.count("Amount") == 2
    # the group heading sits over the first of the columns it spans
    pin = next(c for c in cells if c["text"] == "Paid In")
    assert pin["span"] == 2 and heads[(group_row + 1, pin["col"])] == "Items"


def test_repeated_column_groups_are_one_table_with_one_header(tmp_path):
    items = [(40, 720, "Date"), (120, 720, "Amount"), (220, 720, "Date"), (300, 720, "Amount"),
             (400, 720, "Date"), (480, 720, "Amount")]
    dates = [f"03/{d:02d}/2030" for d in range(1, 9)]
    for k, d in enumerate(dates):
        band, row = divmod(k, 3)
        x = (40, 220, 400)[band]
        items += [(x, 706 - 14 * row, d), _right(x + 130, 706 - 14 * row, f"{k + 1}.00")]
    cells = _lay(tmp_path, [items])["pages"][0]
    assert sorted(_heads(cells).values()) == ["Amount", "Date"]
    rows = sorted(c["row"] for c in cells if c["text"] in dates)
    assert len(rows) == 8 and len(set(rows)) == 8               # one row per record
    assert [c["text"] for c in sorted((c for c in cells if c["text"] in dates),
                                      key=lambda c: c["row"])] == dates


def test_side_by_side_blocks_keep_their_own_columns(tmp_path):
    items = [(40, 720, "SENDER"), (300, 720, "RECIPIENT"),
             (40, 706, "Elm Row"), (300, 706, "Harbour Quay"),
             (300, 692, "Unit 9"),                           # only the right block
             (40, 678, "Northtown"), (300, 678, "Southville")]
    cells = _lay(tmp_path, [items])["pages"][0]
    left = {_find(cells, t)["col"] for t in ("SENDER", "Elm Row", "Northtown")}
    right = {_find(cells, t)["col"] for t in ("RECIPIENT", "Harbour Quay", "Unit 9",
                                              "Southville")}
    assert len(left) == 1 and len(right) == 1 and left != right


def test_a_paragraph_is_left_out_with_a_reason(tmp_path):
    items = [(40, 720, "Name:"), (120, 720, "Jane Roe"),
             (40, 690, "Each entry shown below is listed in the order"),
             (40, 678, "received, and late items appear on the next sheet.")]
    lay = _lay(tmp_path, [items])
    texts = [c["text"] for c in lay["pages"][0]]
    assert "Jane Roe" in texts and not any("Each entry" in t for t in texts)
    assert any("paragraph" in e["reason"] and "Each entry" in e["text"] for e in lay["excluded"])


def test_bullet_text_is_left_out_but_a_bullet_with_a_figure_stays(tmp_path):
    items = [(40, 720, "Name:"), (120, 720, "Jane Roe"),
             (40, 690, "\x95 Keep this sheet with your other papers"),
             (40, 670, "\x95 Fee for the year 12.50")]
    lay = _lay(tmp_path, [items])
    texts = " ".join(c["text"] for c in lay["pages"][0])
    assert "Keep this sheet" not in texts and "12.50" in texts
    assert any(e["reason"] == "bullet text" for e in lay["excluded"])


class _Pg:
    width, height = 612.0, 792.0

    def __init__(self, curves):
        self.curves = curves


def _wedge(x0, t, x1, b):
    return {"x0": x0, "top": t, "x1": x1, "bottom": b, "fill": True}


def _w(text, x0, top, i):
    return {"id": f"w{i}", "text": text, "x0": x0, "x1": x0 + 6 * len(text), "top": top,
            "bottom": top + 8, "baseline": top + 7, "size": 8}


def test_a_pie_with_figure_labels_is_a_chart_and_its_labels_go():
    pie = [_wedge(300, 300, 340, 340), _wedge(320, 300, 360, 340), _wedge(300, 320, 340, 360),
           _wedge(320, 320, 360, 360)]
    words = [_w("Paid", 250, 290, 0), _w("$1.00", 250, 300, 1), _w("Owed", 370, 350, 2),
             _w("$2.00", 370, 360, 3), _w("Total", 40, 600, 4)]
    figs = P.figures(_Pg(pie), words)
    assert len(figs) == 1
    gone = set(P.chart_labels(figs[0], words))
    assert gone == {"w0", "w1", "w2", "w3"}


def test_a_rounded_frame_a_logo_and_a_callout_are_not_charts():
    frame = [{"x0": 50, "top": 50, "x1": 550, "bottom": 300, "fill": False}]
    assert P.figures(_Pg(frame), []) == []
    logo = [_wedge(300, 300, 340, 340), _wedge(320, 300, 360, 340), _wedge(300, 320, 340, 360),
            _wedge(320, 320, 360, 360)]
    assert P.figures(_Pg(logo), [_w("Acme", 250, 290, 0)]) == []          # no figures beside
    callout = [_w("Note", 320, 320, 0), _w("1.5", 250, 290, 1), _w("2.5", 250, 300, 2)]
    assert P.figures(_Pg(logo), callout) == []                            # text inside it


def test_a_continued_repeated_group_table_ends_before_its_footnote_and_summary(tmp_path):
    head = [(40, 700, "Ref"), (110, 700, "Day"), (170, 700, "Sum"), (220, 700, "Ref"),
            (290, 700, "Day"), (350, 700, "Sum"), (400, 700, "Ref"), (470, 700, "Day"),
            (530, 700, "Sum")]
    p1 = [(40, 730, "PAYMENTS")] + head + [
        (40, 686, "5001"), (100, 686, "02/01/30"), _right(200, 686, "$10.00"),
        (220, 686, "5002"), (280, 686, "02/01/30"), _right(380, 686, "$20.00"),
        (400, 686, "5003"), (460, 686, "02/01/30"), _right(560, 686, "$30.00")]
    p2 = [(40, 730, "PAYMENTS (continued)")] + head + [
        (40, 686, "5004"), (100, 686, "02/02/30"), _right(200, 686, "$1.50"),
        (220, 686, "5006"), (280, 686, "02/03/30"), _right(380, 686, "$3.00"),
        (400, 686, "5008"), (460, 686, "02/04/30"), _right(560, 686, "$5.00"),
        (40, 674, "5005"), (100, 674, "02/02/30"), _right(200, 674, "$2.50"),
        (220, 674, "5007"), (280, 674, "02/03/30"), _right(380, 674, "$4.00"),
        (40, 655, "* Shows a gap in the order"),
        (40, 640, "Count of items 8"), (400, 640, "Total of items $76.00")]
    lay = _lay(tmp_path, [p1, p2])
    page2 = lay["pages"][1]
    # one table, one header (written on page 1), every record its own row
    assert not _heads(page2)
    recs = {c["text"]: c["row"] for c in page2 if c["text"].startswith("50")}
    assert sorted(recs) == ["5004", "5005", "5006", "5007", "5008"] and len(set(recs.values())) == 5
    texts = [c["text"] for c in page2]
    assert "Total of items $76.00" in texts or "$76.00" in texts
    assert not any("Count of items" in t and "50" in t for t in texts)
    assert any("Shows a gap" in e["text"] for e in lay["excluded"])
