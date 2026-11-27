"""Run T2, Stage 2: the general causes the positional checker found, one
synthetic page per cause (invented text; no model)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.harness import bootstrap as bs  # noqa: E402

bs.bootstrap()

import perception as P  # noqa: E402
import structure_engine as S  # noqa: E402
import structure_geometry as G  # noqa: E402
from tests import t1_pdf  # noqa: E402


def _right(x_right, y, text, size=10):
    return (x_right - 0.556 * size * len(text), y, text)


def _lay(tmp_path, pages, name="d.pdf"):
    doc = P.read_document(t1_pdf.make(tmp_path / name, pages))
    return S.layout_document(doc), doc


def _rows(cells):
    out = {}
    for c in cells:
        out.setdefault(c["row"], {})[c["col"]] = c["text"]
    return out


def _find(cells, text):
    return next(c for c in cells if c["text"] == text)


def _headers(cells):
    return [c for c in cells if c.get("kind") == "header"]


# ── where a table starts and ends ────────────────────────────────────────────

def test_an_address_block_above_a_table_is_never_its_heading(tmp_path):
    items = [(40, 720, "SENDER"), (200, 720, "RECIPIENT"),
             (40, 706, "Elm Row"), (200, 706, "Harbour Quay"),
             (40, 692, "Northtown"), (200, 692, "Southville"),
             (40, 660, "Item"), (200, 660, "Qty"), (300, 660, "Price")]
    y = 645
    for i, (name, q, pr) in enumerate([("Widget", "2", "4.50"), ("Gadget", "1", "9.00"),
                                       ("Sprocket", "5", "1.25")]):
        items += [(40, y, name), (200, y, q), _right(330, y, pr)]
        y -= 14
    lay, _ = _lay(tmp_path, [items])
    cells = lay["pages"][0]
    heads = [c["text"] for c in _headers(cells)]
    assert heads == ["Item", "Qty", "Price"]
    # the address lines are their own cells, never glued into one
    assert all("Southville" not in c["text"] or c["text"] == "Southville" for c in cells)


def test_a_second_heading_inside_a_block_starts_a_new_table(tmp_path):
    items = [(40, 720, "Kind"), (300, 720, "Count"),
             (40, 706, "Spare Parts"), _right(330, 706, "12.50"),
             (40, 692, "Fittings"), _right(330, 692, "3.75"),
             (40, 678, "Bank"), (150, 678, "Branch"), (300, 678, "Amount"),
             (40, 664, "Direct"), (150, 664, "North"), _right(330, 664, "8.00")]
    lay, _ = _lay(tmp_path, [items])
    cells = lay["pages"][0]
    heads = [c["text"] for c in _headers(cells)]
    assert heads == ["Kind", "Count", "Bank", "Branch", "Amount"]
    rows = _rows(cells)
    r = _find(cells, "8.00")["row"]
    assert rows[r][0] == "Direct" and "North" in rows[r].values()


def test_a_section_line_is_its_own_row_and_a_close_wrap_is_a_tail(tmp_path):
    items = [(40, 720, "Description"), (300, 720, "Amount")]
    items += [(40, 706, "Alpha charge"), _right(330, 706, "1.00"),
              (40, 692, "Beta charge"), _right(330, 692, "2.00"),
              (40, 670, "Fees"),                                    # a section, one line lower
              (40, 656, "Gamma charge"), _right(330, 656, "3.00"),
              (40, 647, "continued here"),                          # a close wrap
              (40, 633, "Delta charge"), _right(330, 633, "4.00")]
    lay, _ = _lay(tmp_path, [items])
    cells = lay["pages"][0]
    assert any(c["text"] == "Fees" for c in cells)
    assert _find(cells, "Gamma charge continued here")
    assert not any("Beta charge Fees" in c["text"] for c in cells)


def test_a_wrap_at_the_row_pitch_right_of_the_first_column_is_a_tail(tmp_path):
    items = [(40, 720, "Date"), (110, 720, "Description"), (300, 720, "Amount")]
    y = 706
    for i in range(4):
        items += [(40, y, f"01/0{i + 1}/2030"), (110, y, f"Payment {i}"), _right(330, y, f"{i + 1}.00")]
        y -= 14
        if i == 1:
            items.append((110, y, "REF 77"))        # same pitch as the rows
            y -= 14
    lay, _ = _lay(tmp_path, [items])
    cells = lay["pages"][0]
    assert _find(cells, "Payment 1 REF 77")


def test_a_range_ending_in_a_dash_continues_on_the_next_line(tmp_path):
    items = [(40, 720, "Name"), (150, 720, "Period"), (300, 720, "Total")]
    items += [(40, 706, "Jane Roe"), (150, 706, "01/02/30 -"), _right(330, 706, "9.00"),
              (150, 695, "01/03/30")]
    lay, _ = _lay(tmp_path, [items])
    assert _find(lay["pages"][0], "01/02/30 - 01/03/30")


def test_a_label_line_aligned_under_a_table_column_is_its_row(tmp_path):
    items = [(40, 720, "Line"), (200, 720, "Current"), (300, 720, "Year")]
    items += [(40, 706, "Alpha"), _right(230, 706, "1.00"), _right(330, 706, "10.00"),
              (40, 692, "Beta"), _right(230, 692, "2.00"), _right(330, 692, "20.00"),
              (40, 678, "Total Fees:"), _right(330, 678, "30")]
    lay, _ = _lay(tmp_path, [items])
    cells = lay["pages"][0]
    total = _find(cells, "30")
    year = next(c for c in _headers(cells) if c["text"] == "Year")
    assert total["col"] == year["col"]
    assert _find(cells, "Total Fees:")["row"] == total["row"]


# ── columns ──────────────────────────────────────────────────────────────────

def test_a_heading_printed_offset_claims_the_headless_column(tmp_path):
    items = [(120, 720, "Item Kind"), (330, 720, "Balance"),
             (40, 706, "Spare Parts"), _right(420, 706, "127.24"),
             (40, 692, "Fittings"), _right(420, 692, "91.58")]
    lay, _ = _lay(tmp_path, [items])
    cells = lay["pages"][0]
    heads = {c["col"]: c["text"] for c in _headers(cells)}
    assert sorted(heads.values()) == ["Balance", "Item Kind"]
    assert heads[_find(cells, "Spare Parts")["col"]] == "Item Kind"
    assert heads[_find(cells, "127.24")["col"]] == "Balance"


def test_a_heading_over_no_data_beside_headed_columns_keeps_its_own_column(tmp_path):
    items = [(40, 720, "Date"), (200, 720, "Debits"), (300, 720, "Credits")]
    items += [(40, 706, "01/02/2030"), _right(230, 706, "5.00"),
              (40, 692, "01/03/2030"), _right(230, 692, "6.00")]
    lay, _ = _lay(tmp_path, [items])
    heads = [c["text"] for c in _headers(lay["pages"][0])]
    assert heads == ["Date", "Debits", "Credits"]


def test_a_narrow_alley_under_a_heading_break_is_a_column(tmp_path):
    items = [(40, 720, "Member"), (130, 720, "Ref No"), (300, 720, "Total")]
    for i, y in enumerate((706, 692)):
        items += [(40, y, "Jane Roe"), (92, y, f"000123{i}"), _right(330, y, f"{i + 4}.00")]
    lay, _ = _lay(tmp_path, [items])
    cells = lay["pages"][0]
    assert _find(cells, "Jane Roe")["col"] != _find(cells, "0001230")["col"]


def test_a_reprinted_heading_is_written_once_only_over_a_continuation(tmp_path):
    def page(y0, n, first):
        items = [(40, 760, "Date"), (110, 760, "Detail"), (300, 760, "Amount")]
        y = 746
        for i in range(n):
            items += [(40, y, f"02/{first + i:02d}/2030"), (110, y, f"Item {first + i}"),
                      _right(330, y, f"{first + i}.00")]
            y -= 14
        return items
    lay, _ = _lay(tmp_path, [page(0, 3, 1), page(0, 3, 4)])
    assert len(_headers(lay["pages"][0])) == 3
    assert len(_headers(lay["pages"][1])) == 0
    # an explainer page that ends with notes does not continue into the next
    expl = page(0, 3, 1) + [(40, 600, "Each line above shows one sample entry")]
    lay2, _ = _lay(tmp_path, [expl, page(0, 3, 4)], name="e.pdf")
    assert len(_headers(lay2["pages"][1])) == 3


def test_a_label_line_inside_a_table_is_placed_by_pairs(tmp_path):
    items = [(40, 720, "INVOICE"), (100, 720, "REF"), (200, 720, "DATE"), (330, 720, "NET")]
    y = 706
    for i in range(3):
        items += [(40, y, f"10{i}"), (100, y, f"R{i}"), (200, y, f"03/0{i + 1}/2030"),
                  _right(360, y, f"{i + 1}.00")]
        y -= 14
        items += [(52, y, "PAID ON:"), (104, y, f"03/1{i}/2030")]
        y -= 14
    lay, _ = _lay(tmp_path, [items])
    cells = lay["pages"][0]
    assert sum(1 for c in cells if c["text"] == "PAID ON:") == 3
    assert not any(c["text"] in ("PAID", "ON:") for c in cells)


# ── label/value pairs ────────────────────────────────────────────────────────

def test_every_label_pair_in_one_segment_is_split():
    def w(t, x):
        return {"text": t, "x0": x, "x1": x + 6 * len(t)}
    seg = [w("Ref:", 0), w("AB-12", 30), w("Date:", 70), w("01/02/2030", 100), w("-", 160),
           w("01/03/2030", 170)]
    got = [(" ".join(x["text"] for x in ws), role) for ws, role in S.split_pairs(seg)]
    assert got == [("Ref:", "label"), ("AB-12", "value"), ("Date:", "label"),
                   ("01/02/2030 - 01/03/2030", "value")]
    seg2 = [w("Opening", 0), w("total:", 40), w("$4.10", 80), w("Closing", 120), w("total:", 160),
            w("$9.20", 200)]
    got2 = [(" ".join(x["text"] for x in ws), role) for ws, role in S.split_pairs(seg2)]
    assert got2 == [("Opening total:", "label"), ("$4.10", "value"),
                    ("Closing total:", "label"), ("$9.20", "value")]
    seg3 = [w("Name:", 0), w("Blue", 40), w("Ltd", 70), w("Phone:", 100), w("x", 150)]
    got3 = [" ".join(x["text"] for x in ws) for ws, _r in S.split_pairs(seg3)]
    assert got3 == ["Name:", "Blue Ltd", "Phone:", "x"]


# ── perception ───────────────────────────────────────────────────────────────

def _ch(text, x0, x1, size=8.0, top=100.0, color=(0,)):
    return {"text": text, "x0": x0, "x1": x1, "top": top, "bottom": top + size, "size": size,
            "fontname": "F", "non_stroking_color": color, "matrix": (1, 0, 0, 1, 0, 0)}


def test_a_space_wide_gap_with_no_space_character_cuts_a_word():
    chars = [_ch("A", 0, 5), _ch("B", 5, 10), _ch("C", 12.4, 17), _ch("D", 17, 22)]
    pieces = P._split_at_gaps(chars)
    assert ["".join(c["text"] for c in p) for p in pieces] == ["AB", "CD"]
    tight = [_ch("A", 0, 5), _ch("B", 5.4, 10)]            # kerning: one word
    assert len(P._split_at_gaps(tight)) == 1


def test_touching_glyphs_join_but_different_scales_do_not():
    def word(t, x0, x1, size=10.0, base=110.0):
        return {"text": t, "x0": x0, "x1": x1, "top": base - size, "bottom": base,
                "baseline": base, "size": size, "rotation": 0.0, "origin": "text",
                "bold": False, "italic": False}
    got = P.join_touching([word("$", 10, 16, base=110.41), word("4", 16, 22, base=110.65),
                           word("7", 22, 28)])
    assert [w["text"] for w in got] == ["$47"]
    mixed = P.join_touching([word("A", 10, 16), word("b", 16, 17.2, size=2.4)])
    assert len(mixed) == 2
    spaced = P.join_touching([word("one", 10, 30), word("two", 33, 50)])
    assert len(spaced) == 2


def test_word_glued_to_a_figure_is_two_words_but_an_identifier_is_not():
    w = {"text": "Items8", "x0": 0, "x1": 36}
    assert [x["text"] for x in P._unglue(w)] == ["Items", "8"]
    assert [x["text"] for x in P._unglue({"text": "INV2030", "x0": 0, "x1": 40})] == ["INV2030"]


def test_red_markup_is_left_out_with_a_reason_but_a_red_amount_on_a_row_is_kept(tmp_path):
    red = (0.9, 0.1, 0.1)
    items = [(40, 760, "Name:"), (120, 760, "Jane Roe"),
             {"x": 260, "y": 760, "text": "1. Check the name", "rgb": red},
             (40, 720, "Date"), (110, 720, "Detail"), (300, 720, "Amount")]
    y = 706
    for i in range(4):
        items += [(40, y, f"04/0{i + 1}/2030"), (110, y, f"Entry {i}"),
                  dict(zip(("x", "y", "text"), _right(330, y, f"{i + 1}.50")),
                       **({"rgb": red} if i == 2 else {}))]
        y -= 14
    for k in range(12):
        items.append((40, 500 - 12 * k, f"Plain filler line number {k}"))
    lay, _ = _lay(tmp_path, [items])
    texts = [c["text"] for c in lay["pages"][0]]
    assert "3.50" in texts                                    # red, but a row's amount
    assert not any("Check the name" in t for t in texts)
    assert any(e["text"] == "1. Check the name" and "markup" in e["reason"]
               for e in lay["excluded"])


def test_an_invisible_ocr_layer_over_images_carries_no_bold():
    class Pg:
        width, height, curves = 612, 792, []
        images = [{"x0": 0, "top": 0, "x1": 612, "bottom": 792}]
    words = [{"text": f"w{i}", "x0": 10 + i, "x1": 20 + i, "top": 10, "bottom": 20}
             for i in range(12)]
    assert P.quality(Pg(), words)["overlay"] is True


def test_words_in_a_cell_read_line_by_line_left_to_right(tmp_path):
    # `$`, `9`, `6` on one line at slightly different tops must read "$96"
    items = [(40, 720, "Line"), (300, 720, "Amount"),
             (40, 706, "Alpha"), {"x": 300, "y": 706.3, "text": "$"},
             {"x": 306.2, "y": 706.0, "text": "9"}, {"x": 312.0, "y": 705.7, "text": "6"},
             (40, 692, "Beta"), (300, 692, "$12")]
    lay, _ = _lay(tmp_path, [items])
    texts = [c["text"] for c in lay["pages"][0]]
    assert "$96" in texts or "$ 9 6" in texts
    assert "6 9 $" not in texts and "9 6 $" not in texts


def test_a_page_number_beside_a_field_is_furniture_with_a_reason(tmp_path):
    items = [(40, 720, "Member Number"), (160, 720, "0007"), (400, 720, "Page 2 of 5"),
             (40, 700, "Ratio"), (160, 700, "1/2")]
    lay, _ = _lay(tmp_path, [items])
    texts = [c["text"] for c in lay["pages"][0]]
    assert "Page 2 of 5" not in texts and "0007" in texts and "1/2" in texts
    assert any(e["text"] == "Page 2 of 5" and "furniture" in e["reason"] for e in lay["excluded"])
    assert not any("not placed" in f for f in lay["flags"])
    assert not G.is_furniture("1/2") and not G.is_furniture("Page 3") and G.is_furniture("3 of 9")
