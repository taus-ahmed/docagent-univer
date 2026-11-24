"""Run Q, Q4 — a correct value is not Low.

(a) job 82 ADP W-2: the form draws its values as vector outlines, so no
    span can be found in the text layer - that is "not checked", not
    "checked and failed".
(b) job 72: `P.O.` is printed narrower than its values, which sit right of
    it; the value lay between its neighbours' headings and was still called
    misplaced.
(c) job 57: a quote that dropped the printed spaces ("Purch.Doc.22356099").
(d) job 72: a Vendor ID printed on the vendor line ABOVE its invoice row.
Each keeps its failing twin: a really misplaced or absent value is still Low.
"""
from __future__ import annotations

from pathlib import Path

from tests import run_q_support as Q


# ── (a) outlined text ────────────────────────────────────────────────────────

def _outlined_pdf(path):
    """A page with one line of real text and 400 glyph-sized vector paths."""
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    w = PdfWriter()
    font = w._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica")}))
    page = w.add_blank_page(612, 792)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    ops = ["BT /F1 10 Tf 72 760 Td (Sample W-2 Wage and Tax Statement) Tj ET"]
    for i in range(400):
        x, y = 72 + (i % 40) * 12, 600 - (i // 40) * 14
        ops.append(f"{x} {y} m {x + 2} {y + 4} {x + 6} {y + 6} {x + 8} {y + 8} c f")
    s = DecodedStreamObject()
    s.set_data("\n".join(ops).encode("latin-1"))
    page[NameObject("/Contents")] = w._add_object(s)
    with open(path, "wb") as fh:
        w.write(fh)
    return Path(path)


def _w2_answer(prompt):
    ids = Q.slot_ids(prompt)
    return {"fields": {ids["Wages Tips Other Compensation"]: {
        "value": "23500.00", "source": "1 Wages, tips, other comp. 23500.00", "page": 1}},
        "tables": {}}


W2 = Q.template(fields=["Wages Tips Other Compensation"], doc_type="w2")


def _level(ed, label):
    return ed["extracted_data"][label]["confidence"]


def test_outlined_page_value_is_unverified_not_low_reconstructed(tmp_path):
    import text_layer as T
    f = _outlined_pdf(tmp_path / "w2.pdf")
    assert T.outlined_pages(f) == {1}
    (r,) = Q.run(f, W2, _w2_answer)
    ed = r.extracted_data
    assert _level(ed, "Wages Tips Other Compensation") == "unverified"
    prov = next(iter(ed["field_provenance"].values()))
    assert "outlined_text" in prov["review_reasons"]
    assert "grounding_failed" not in prov["review_reasons"]


def test_outlined_page_real():
    import text_layer as T
    f = Q.need_source("adp_w2_interactive.pdf")
    assert T.outlined_pages(f) == {1}
    (r,) = Q.run(f, W2, _w2_answer)
    assert _level(r.extracted_data, "Wages Tips Other Compensation") == "unverified"


def test_an_ordinary_page_is_not_outlined(tmp_path):
    import text_layer as T
    f = Q.make_pdf(tmp_path / "p.pdf", [[(72, 700, "Wages 23500.00")]])
    assert T.outlined_pages(f) == set()


# ── (b) a narrow heading ─────────────────────────────────────────────────────

def _po_line():
    def w(t, a, b):
        return {"text": t, "x0": a, "x1": b, "top": 100}
    head = [w("INVOICE", 36, 66), w("P.O.", 95, 112), w("INV", 163, 175), w("DATE", 179, 196),
            w("INVOICE", 369, 399), w("NET", 403, 416)]
    row = [w("560168", 36, 61), w("26008186", 125, 158), w("04/28/2026", 163, 205),
           w("264.60", 378, 403)]
    return head, row


def test_a_value_between_its_neighbours_is_under_its_own_column():
    import text_layer as T
    head, row = _po_line()
    cols = [{"header": h} for h in ("INVOICE", "P.O.", "INV DATE", "INVOICE NET")]
    bands = T.column_bands([head], [c["header"] for c in cols])
    assert bands["INV DATE"] == (163.0, 196.0)        # a two-word heading has a band
    cells = {"INVOICE": "560168", "P.O.": "26008186", "INV DATE": "04/28/2026", "INVOICE NET": "264.60"}
    assert T.check_placement(cells, cols, row, bands) == []


def test_a_date_written_to_the_po_column_still_fails():
    import text_layer as T
    head, row = _po_line()
    cols = [{"header": h} for h in ("INVOICE", "P.O.", "INV DATE", "INVOICE NET")]
    bands = T.column_bands([head], [c["header"] for c in cols])
    cells = {"INVOICE": "560168", "P.O.": "04/28/2026", "INV DATE": "", "INVOICE NET": "264.60"}
    bad = T.check_placement(cells, cols, row, bands)
    assert [k for k, _ in bad] == ["P.O."], bad


# ── (c) a quote without its printed spaces ───────────────────────────────────

def test_a_quote_that_dropped_its_spaces_grounds():
    import slot_extractor as S
    page = ["Purch. Doc. 22356099 dated 05/01/2024"]
    assert S.verify_span("22356099", "Purch.Doc.22356099", 1, page)[0]


def test_a_spaceless_quote_does_not_ground_a_truncation_or_absent_text():
    import slot_extractor as S
    page = ["Purch. Doc. 22356099 dated 05/01/2024"]
    assert not S.verify_span("2235", "Purch.Doc.2235", 1, page)[0]
    assert not S.verify_span("99999999", "Purch.Doc.99999999", 1, page)[0]


# ── (d) a group line above its row ───────────────────────────────────────────

HEADS = ["Vendor ID", "INVOICE", "AMOUNT"]


def _vendor_pdf(tmp_path):
    return Q.make_pdf(tmp_path / "v.pdf", [[
        (72, 760, "VENDOR INVOICE LIST"),
        (72, 740, "INVOICE"), (300, 740, "AMOUNT"),
        (90, 720, "300055 ANDERSON DULANEY"),
        (72, 704, "0025"), (300, 704, "75.00"),
        (90, 688, "10869 AT&T"),
        (72, 672, "629239"), (300, 672, "1,050.00"),
    ]])


def _vendor_answer(vid2):
    def fn(prompt):
        name = Q.table_names(prompt)[0]
        return {"fields": {}, "tables": {name: [
            {"Vendor ID": "300055", "INVOICE": "0025", "AMOUNT": "75.00",
             "source": "0025 75.00", "page": 1},
            {"Vendor ID": vid2, "INVOICE": "629239", "AMOUNT": "1,050.00",
             "source": "629239 1,050.00", "page": 1}]}}
    return fn


def _rows(ed):
    return ed.get("table_rows") or next(v for k, v in ed.items() if k.endswith("_rows") and v)


def test_a_vendor_id_on_the_line_above_grounds_reconstructed(tmp_path):
    tpl = Q.template(tables=[(None, HEADS)], doc_type="other")
    (r,) = Q.run(_vendor_pdf(tmp_path), tpl, _vendor_answer("10869"))
    rows = _rows(r.extracted_data)
    assert [x["_confidence"] for x in rows] != ["low", "low"]
    assert all("Vendor ID" not in (x.get("_ungrounded") or []) for x in rows), rows


def test_a_vendor_id_from_another_record_is_still_ungrounded_reconstructed(tmp_path):
    tpl = Q.template(tables=[(None, HEADS)], doc_type="other")
    # row 2 claims row 1's vendor id: the line above row 2 prints 10869, and
    # the walk stops at row 1's own line, so 300055 is not in its record
    (r,) = Q.run(_vendor_pdf(tmp_path), tpl, _vendor_answer("300055"))
    rows = _rows(r.extracted_data)
    assert "Vendor ID" in (rows[1].get("_ungrounded") or []), rows[1]
