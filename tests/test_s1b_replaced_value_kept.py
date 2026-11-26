"""Run S, 1b follow-up — a model value the group line replaces is not lost.

When the page's group line replaces a model's value in a group column, and
the line does not print that value, the value was kept only in a flag: job
72 lost nine printed per-invoice names that way (the page glues each name to
its invoice number, the model split them, and the name column was then given
the group line). The rule:

  * the replaced value goes in the cell of the column whose PRINTED text
    contains it (the cell's value is part of a printed token run that also
    prints the replaced value) - that cell gets the page's whole text;
  * otherwise the replaced value stays flagged with both readings.

Invented data only.
"""
from __future__ import annotations

import row_groups as RG


def _line(text, page=1, y=0):
    out, x = [], 10.0
    for t in text.split():
        out.append({"text": t, "x0": x, "x1": x + 6 * len(t), "top": y,
                    "bottom": y + 8, "page": page})
        x += 6 * len(t) + 4
    return out


def _lines(texts):
    return [_line(t, 1, 12 * i) for i, t in enumerate(texts)]


GLUED = _lines([
    "Harbor Transit Authority", "VENDOR INVOICE LIST",
    "INVOICE INV DATE CHECK # NET PAID",
    "410022 HARBOR PARTS",
    "71000001JaneRoe 71000001 04/24/2026 555001 150.00 150.00",
    "71000002MarkLee 71000002 04/24/2026 555001 90.00 90.00",
    "240.00",
    "410023 QUAY SUPPLY",
    "72000001AnnaPym 72000001 04/25/2026 555002 60.00 60.00",
    "72000002OttoVale 72000002 04/25/2026 555002 40.00 40.00",
    "100.00",
    "4 INVOICES 340.00"])

KEYS = ["Vendor ID", "Vendor Name", "Invoice", "Amount"]


def _rows(lines, answer):
    rows, where = [], {}
    for i, ln in enumerate(lines):
        if RG._kind(ln) == "row":
            toks = [w["text"] for w in ln]
            r = {k: "" for k in KEYS}
            r["Amount"] = toks[-1]
            r.update(answer(toks))
            rows.append(r)
            where[id(r)] = i
    return rows, where


def _glued_answer(toks):
    # the model split '71000001JaneRoe' into an invoice number and a "vendor"
    head = toks[0]
    n = len(toks[1])
    return {"Invoice": head[:n], "Vendor Name": head[n:]}


def test_a_replaced_name_printed_inside_another_cells_text_moves_there():
    g = RG.detect(GLUED)
    assert g is not None
    rows, where = _rows(GLUED, _glued_answer)
    _s, flags, notes = RG.apply(rows, where, g, None, KEYS, "grounded", "low",
                                split_keys=("Vendor ID", "Vendor Name"))
    assert [(r["Vendor ID"], r["Vendor Name"], r["Invoice"]) for r in rows] == [
        ("410022", "HARBOR PARTS", "71000001JaneRoe"),
        ("410022", "HARBOR PARTS", "71000002MarkLee"),
        ("410023", "QUAY SUPPLY", "72000001AnnaPym"),
        ("410023", "QUAY SUPPLY", "72000002OttoVale")]
    # nothing lost, so nothing to flag; the move is said in a note
    assert not flags
    assert any("JaneRoe" in n and "Invoice" in n for n in notes)


def test_every_printed_word_of_the_row_is_still_in_some_cell():
    g = RG.detect(GLUED)
    rows, where = _rows(GLUED, _glued_answer)
    RG.apply(rows, where, g, None, KEYS, "grounded", "low",
             split_keys=("Vendor ID", "Vendor Name"))
    for r in rows:
        held = " ".join(str(v) for v in r.values())
        for name in ("JaneRoe", "MarkLee", "AnnaPym", "OttoVale"):
            if name in r["Invoice"]:
                assert name in held


def test_a_replaced_value_no_cell_prints_stays_flagged():
    """The model's value is printed on the row as its own word, not inside
    any other cell's text: no cell to move it to, so the flag carries it."""
    lines = _lines([
        "Receivables list", "Ref Date Contact Amount",
        "Customer Code: KX-77 Harbor Foods",
        "A1 03/01/2025 Dana 120.00",
        "A2 03/04/2025 Eli 80.00",
        "200.00",
        "Customer Code: KX-81 Delta Bakery",
        "B7 03/02/2025 Finn 55.50",
        "B9 03/09/2025 Gus 44.50",
        "100.00"])
    keys = ["Customer Code", "Customer Name", "Ref", "Amount"]
    g = RG.detect(lines)
    assert g is not None
    rows, where = [], {}
    for i, ln in enumerate(lines):
        if RG._kind(ln) == "row":
            toks = [w["text"] for w in ln]
            r = {"Customer Code": "", "Customer Name": toks[2], "Ref": toks[0],
                 "Amount": toks[-1]}
            rows.append(r)
            where[id(r)] = i
    _s, flags, _n = RG.apply(rows, where, g, None, keys, "grounded", "low",
                             split_keys=("Customer Code", "Customer Name"))
    assert rows[0]["Customer Name"] == "Harbor Foods"
    assert rows[0]["Ref"] == "A1"
    assert any("Dana" in f[2] and "Harbor Foods" in f[2] for f in flags)
    assert len(flags) == 4


def test_a_value_that_is_part_of_the_group_line_is_replaced_without_a_move():
    g = RG.detect(GLUED)
    rows, where = _rows(GLUED, lambda toks: {
        "Invoice": toks[1],
        "Vendor Name": "HARBOR" if toks[1].startswith("71") else "QUAY"})
    _s, flags, notes = RG.apply(rows, where, g, None, KEYS, "grounded", "low",
                                split_keys=("Vendor ID", "Vendor Name"))
    assert rows[0]["Invoice"] == "71000001"
    assert not flags
    assert not any("moved" in n for n in notes)
