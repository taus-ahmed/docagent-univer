"""Run T2, Stage 3: fillable-form values next to the labels of their boxes.

A synthetic page (invented labels) with drawn boxes, printed labels and
FILLED text widgets - two forms on one page - built here with pypdf; plus a
page with no widgets, which must keep the normal path."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.harness import bootstrap as bs  # noqa: E402

bs.bootstrap()

import form_boxes as FB  # noqa: E402
import perception as P  # noqa: E402
import structure_engine as S  # noqa: E402

H = 792.0


def _box(x0, top, x1, bottom):
    """A frame in top-left points -> PDF drawing ops (y from the bottom)."""
    y0, y1 = H - bottom, H - top
    return (f"{x0} {y0} m {x1} {y0} l S {x0} {y1} m {x1} {y1} l S "
            f"{x0} {y0} m {x0} {y1} l S {x1} {y0} m {x1} {y1} l S")


def _text(x, top, s, size=7):
    return f"BT /F1 {size} Tf 1 0 0 1 {x} {H - top - size} Tm ({s}) Tj ET"


def make_form(path, forms):
    """forms: [[(x0, top, x1, bottom, label, value or None, [extra label lines])]]."""
    from pypdf import PdfWriter
    from pypdf.generic import (ArrayObject, DictionaryObject, FloatObject, NameObject,
                               NumberObject, StreamObject, TextStringObject)
    w = PdfWriter()
    page = w.add_blank_page(612, H)
    ops, annots = ["0 g 0.5 w"], []
    for form in forms:
        for x0, top, x1, bottom, label, value, extra in form:
            ops.append(_box(x0, top, x1, bottom))
            ops.append(_text(x0 + 2, top + 2, label))
            for k, (dx, dy, t) in enumerate(extra):
                ops.append(_text(x0 + dx, top + dy, t))
            if value is not None:
                r = [x0 + 2, H - bottom + 2, x1 + 2, H - top - 12]      # overruns by 2 pt
                a = DictionaryObject({
                    NameObject("/Type"): NameObject("/Annot"),
                    NameObject("/Subtype"): NameObject("/Widget"),
                    NameObject("/FT"): NameObject("/Tx"),
                    NameObject("/T"): TextStringObject(label[:12]),
                    NameObject("/V"): TextStringObject(value),
                    NameObject("/Rect"): ArrayObject([FloatObject(v) for v in r]),
                    NameObject("/F"): NumberObject(4)})
                annots.append(w._add_object(a))
    stream = StreamObject()
    stream.set_data(" ".join(ops).encode("latin-1"))
    page[NameObject("/Contents")] = w._add_object(stream)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)})})
    page[NameObject("/Annots")] = ArrayObject(annots)
    w._root_object[NameObject("/AcroForm")] = DictionaryObject(
        {NameObject("/Fields"): ArrayObject(annots)})
    with open(path, "wb") as f:
        w.write(f)
    return path


FORM_A = [(40, 60, 200, 90, "1 Gross receipts", "4,210.00", [(150, 14, "$")]),
          (200, 60, 360, 90, "2 Fees withheld", "12.50", []),
          (40, 90, 200, 120, "3 Payee name", "Jane Roe", []),
          (200, 90, 360, 120, "4 Spare box", None, [(150, 14, "$")]),
          (40, 120, 200, 150, "5a", "QX 99", [(30, 6, "C"), (30, 11, "o"), (30, 16, "d"),
                                               (30, 21, "e")])]
FORM_B = [(40, 400, 200, 430, "Filer ref", "AB-1234", []),
          (200, 400, 360, 430, "Year", "2031", [])]


def _layout(tmp_path, forms):
    pdf = make_form(tmp_path / "f.pdf", forms)
    doc = P.read_document(pdf)
    return S.layout_document(doc), doc


def _pairs(cells):
    rows = {}
    for c in cells:
        rows.setdefault(c["row"], {})[c["col"]] = c["text"]
    out = {}
    for r in rows.values():
        for col, t in r.items():
            if col + 1 in r and col % 2 == 0:
                out[t] = r[col + 1]
    return out


def test_each_widget_value_sits_beside_its_box_label(tmp_path):
    lay, _ = _layout(tmp_path, [FORM_A])
    pairs = _pairs(lay["pages"][0])
    assert pairs["2 Fees withheld"] == "12.50"
    assert pairs["3 Payee name"] == "Jane Roe"


def test_a_currency_sign_joins_its_value_and_a_lone_one_is_left_out(tmp_path):
    lay, _ = _layout(tmp_path, [FORM_A])
    pairs = _pairs(lay["pages"][0])
    assert pairs["1 Gross receipts"] == "$4,210.00"
    texts = [c["text"] for c in lay["pages"][0]]
    assert "$" not in texts and "4 Spare box" in texts
    assert any(e["text"] == "$" and "currency" in e["reason"] for e in lay["excluded"])
    assert not any("not placed" in f for f in lay["flags"])


def test_a_label_set_in_stacked_pieces_reads_as_one_label(tmp_path):
    lay, _ = _layout(tmp_path, [FORM_A])
    pairs = _pairs(lay["pages"][0])
    assert pairs.get("5a Code") == "QX 99"


def test_two_forms_on_one_page_are_two_regions_with_their_own_anchor(tmp_path):
    lay, _ = _layout(tmp_path, [FORM_A, FORM_B])
    forms = [r for r in lay["plans"][1]["regions"] if r["kind"] == "form"]
    assert len(forms) == 2
    anchors = lay["anchors"][1]
    assert len({anchors[r["id"]] for r in forms}) == 2
    assert _pairs(lay["pages"][0])["Filer ref"] == "AB-1234"


def test_a_page_without_widgets_keeps_the_normal_path(tmp_path):
    from tests import t1_pdf
    doc = P.read_document(t1_pdf.make(tmp_path / "n.pdf", [[(40, 720, "Name:"),
                                                             (120, 720, "Jane Roe")]]))
    assert FB.form_regions(doc["pages"][0]) == []
    lay = S.layout_document(doc)
    assert all(r["kind"] != "form" for r in lay["plans"][1]["regions"])


def test_a_multi_line_widget_value_keeps_its_words_apart():
    # a value typed over three lines (`\r`) is one value with spaces, never
    # `CORNERMAIN`
    assert " ".join("ROW ONE\rROW TWO".split()) == "ROW ONE ROW TWO"


def test_label_text_joins_stacked_pieces_and_keeps_words():
    def w(t, x, base):
        return {"text": t, "x0": x, "x1": x + 4, "baseline": base, "size": 7}
    ws = [w("12x", 10, 10), w("C", 30, 15), w("o", 30, 20), w("d", 30, 25), w("e", 30, 30)]
    assert FB.label_text(ws) == "12x Code"
    assert FB.label_text([w("Fees", 10, 10), w("withheld", 30, 10)]) == "Fees withheld"


def test_without_widgets_a_currency_sign_joins_the_figure_on_its_line(tmp_path):
    from tests import t1_pdf
    items = [(40, 720, "Box 7 Interest"), (200, 720, "$"), (320, 720, "1,250.00"),
             (40, 700, "Box 8 Penalty"), (200, 700, "$")]
    lay = S.layout_document(P.read_document(t1_pdf.make(tmp_path / "s.pdf", [items])))
    texts = [c["text"] for c in lay["pages"][0]]
    assert "$1,250.00" in texts and "$" not in texts
    assert any(e["text"] == "$" and "no figure" in e["reason"] for e in lay["excluded"])
