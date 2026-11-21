"""Run Q, Q3 — arithmetic the document states is checked; never corrected.

Reconstructed from the real exports: job 79 (SSA-1099 Box 3 17,500, Box 4
15,000, Box 5 17,500; Box 5's own label reads "Box 3 minus Box 4") and job 71
(Shell: 6.736 G at 2.969/G charged 26.66). Each mismatch is a visible flag
naming the numbers; each control is quiet. Values are never changed.
"""
from __future__ import annotations

import pytest

from tests import run_q_support as Q


def _fields_answer(values):
    def fn(prompt):
        ids = Q.slot_ids(prompt)
        lines = [ln.strip() for ln in prompt.splitlines()]
        out = {}
        for label, v in values.items():
            src = next((ln for ln in lines if v in ln and "labelled" not in ln), v)
            out[ids[label]] = {"value": v, "source": src, "page": 1}
        tables = {n: [] for n in Q.table_names(prompt)}
        return {"fields": out, "tables": tables}
    return fn


def _flag_text(ed):
    return " ".join(str(f.get("reason", "")) for f in
                    (ed.get("validation") or {}).get("flagged_fields") or []).casefold()


def _conf(ed, label):
    return (ed.get("extracted_data") or {}).get(label, {}).get("confidence")


SSA = ["Box 3. Benefits Paid in 2026", "Box 4. Benefits Repaid to SSA in 2026",
       "Box 5. Net Benefits for 2026 (Box 3 minus Box 4)"]


def _ssa_pdf(tmp_path, b3, b4, b5):
    return Q.make_pdf(tmp_path / "ssa.pdf", [[
        (72, 740, "FORM SSA-1099 - SOCIAL SECURITY BENEFIT STATEMENT"),
        (72, 700, f"Box 3. Benefits Paid in 2026 {b3}"),
        (72, 680, f"Box 4. Benefits Repaid to SSA in 2026 {b4}"),
        (72, 660, f"Box 5. Net Benefits for 2026 (Box 3 minus Box 4) {b5}"),
    ]])


def test_ssa_box5_that_is_not_box3_minus_box4_is_flagged_reconstructed(tmp_path):
    pdf = _ssa_pdf(tmp_path, "17,500.00", "15,000.00", "17,500.00")
    tpl = Q.template(fields=SSA, doc_type="form_1099")
    (r,) = Q.run(pdf, tpl, _fields_answer(dict(zip(SSA, ["17,500.00", "15,000.00", "17,500.00"]))))
    ed = r.extracted_data
    assert _conf(ed, SSA[2]) == "low"
    why = _flag_text(ed)
    assert "2500" in why.replace(",", "") and "17,500.00" in why, why
    # never corrected
    assert ed["extracted_data"][SSA[2]]["value"] == "17,500.00"


def test_ssa_box5_that_adds_up_is_quiet(tmp_path):
    pdf = _ssa_pdf(tmp_path, "17,500.00", "15,000.00", "2,500.00")
    tpl = Q.template(fields=SSA, doc_type="form_1099")
    (r,) = Q.run(pdf, tpl, _fields_answer(dict(zip(SSA, ["17,500.00", "15,000.00", "2,500.00"]))))
    assert "arithmetic" not in _flag_text(r.extracted_data)
    assert "minus" not in _flag_text(r.extracted_data)


def test_a_w2_gets_no_cross_box_check(tmp_path):
    labels = ["Box 1 Wages, tips, other compensation", "Box 2 Federal income tax withheld",
              "Box 3 Social security wages"]
    pdf = Q.make_pdf(tmp_path / "w2.pdf", [[(72, 700, "Box 1 Wages, tips, other compensation 23500.00"),
                                            (72, 680, "Box 2 Federal income tax withheld 1500.00"),
                                            (72, 660, "Box 3 Social security wages 25000.00")]])
    (r,) = Q.run(pdf, Q.template(fields=labels, doc_type="w2"),
                 _fields_answer(dict(zip(labels, ["23500.00", "1500.00", "25000.00"]))))
    assert "minus" not in _flag_text(r.extracted_data)


def _shell(tmp_path, gallons):
    return Q.make_pdf(tmp_path / "shell.pdf", [[
        (72, 740, "SHELL"), (72, 720, "2029 S SAGINAW MIDLAND MI"),
        (72, 690, f"PUMP 03 UNLD {gallons} G @ 2.969/G"),
        (72, 670, "Total 26.66"),
    ]])


def test_fuel_gallons_times_price_not_the_total_is_flagged_reconstructed(tmp_path):
    tpl = Q.template(fields=["Merchant Name", "Total"], doc_type="receipt")
    (r,) = Q.run(_shell(tmp_path, "6.736"), tpl,
                 _fields_answer({"Merchant Name": "SHELL", "Total": "26.66"}))
    ed = r.extracted_data
    why = _flag_text(ed)
    assert "6.736" in why and "2.969" in why and "20.00" in why, why
    assert _conf(ed, "Total") == "low"
    assert ed["extracted_data"]["Total"]["value"] == "26.66"


def test_fuel_that_multiplies_out_is_quiet(tmp_path):
    tpl = Q.template(fields=["Merchant Name", "Total"], doc_type="receipt")
    (r,) = Q.run(_shell(tmp_path, "8.979"), tpl,
                 _fields_answer({"Merchant Name": "SHELL", "Total": "26.66"}))
    assert "gallons" not in _flag_text(r.extracted_data)


def _invoice_rows(tmp_path, amount):
    return Q.make_pdf(tmp_path / "po.pdf", [[
        (72, 740, "PURCHASE ORDER PO-77"),
        (72, 700, "Description"), (250, 700, "Qty"), (330, 700, "Unit Price"), (450, 700, "Amount"),
        (72, 680, "Widget"), (250, 680, "2"), (330, 680, "50.00"), (450, 680, amount),
        (72, 660, "Gear"), (250, 660, "1"), (330, 660, "30.00"), (450, 660, "30.00"),
        (330, 630, "Subtotal"), (450, 630, "130.00"),
    ]])


def _rows_answer(amount):
    def fn(prompt):
        name = Q.table_names(prompt)[0]
        ids = Q.slot_ids(prompt)
        rows = [{"Description": "Widget", "Qty": "2", "Unit Price": "50.00", "Amount": amount,
                 "source": f"Widget 2 50.00 {amount}", "page": 1},
                {"Description": "Gear", "Qty": "1", "Unit Price": "30.00", "Amount": "30.00",
                 "source": "Gear 1 30.00 30.00", "page": 1}]
        return {"fields": {ids["Subtotal"]: {"value": "130.00", "source": "Subtotal 130.00",
                                             "page": 1}},
                "tables": {name: rows}}
    return fn


PO_TPL = Q.template(fields=[], tables=[(None, ["Description", "Qty", "Unit Price", "Amount"])],
                    doc_type="purchase_order")
PO_TPL["layout"]["cells"]["12,0"] = {"value": "Subtotal"}


def test_po_line_quantity_times_price_and_line_sum_are_checked(tmp_path):
    (r,) = Q.run(_invoice_rows(tmp_path, "100.00"), PO_TPL, _rows_answer("120.00"))
    why = _flag_text(r.extracted_data)
    assert "2 x 50.00 is 100.00" in why, why
    # 120 + 30 = 150, not the printed subtotal 130
    assert "subtotal" in why and "150" in why, why


def test_po_that_adds_up_is_quiet(tmp_path):
    (r,) = Q.run(_invoice_rows(tmp_path, "100.00"), PO_TPL, _rows_answer("100.00"))
    why = _flag_text(r.extracted_data)
    assert " x " not in why and "subtotal" not in why, why


def test_a_value_printed_as_one_word_is_never_respelled_from_other_lines():
    """Found by Q3: Subtotal 130.00 came back as "1 30.00" - the join walked
    a Qty "1" and an Amount "30.00" on another line that, whitespace ignored,
    spell the same characters."""
    import text_layer as TL

    def w(t, x0, top):
        return {"text": t, "x0": x0, "x1": x0 + 6 * len(t), "top": top,
                "bottom": top + 10, "page": 1}
    lines = [[w("Gear", 72, 100), w("1", 250, 100), w("30.00", 450, 100)],
             [w("Subtotal", 330, 130), w("130.00", 450, 130)]]
    assert TL.canonical_value("130.00", lines)[0] == "130.00"
    # a value that really is two words still joins as before
    assert TL.canonical_value("Gear 1", lines)[0] == "Gear 1"
