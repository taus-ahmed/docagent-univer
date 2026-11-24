"""Run Q, Q10 — printed spacing restored; money in an export is a number.

Job 78 exported "FASTEATS", "MARTAGARCIA", "123LILACAVENUE": the PDF prints
the space as a 2.17 pt gap at 8 pt with no space glyph, and the text layer
glued the words. Job 58 (no template) exported "$2,750", "(1,300)",
"( 4,125)" as TEXT. Reconstructed with a TJ kerning gap and with the real
job 58 notations.
"""
from __future__ import annotations

from tests import run_q_support as Q


def _glued_pdf(tmp_path):
    return Q.make_raw_pdf(tmp_path / "nec.pdf", [[
        "BT /F1 10 Tf 42 740 Td (FORM 1099-NEC NONEMPLOYEE COMPENSATION) Tj ET",
        "BT /F1 8 Tf 42 700 Td (PAYER'S name) Tj ET",
        "BT /F1 8 Tf 42 688 Td [(FAST) -270 (EATS)] TJ ET",
        "BT /F1 8 Tf 42 660 Td (RECIPIENT'S name) Tj ET",
        "BT /F1 8 Tf 42 648 Td [(MARTA) -270 (GARCIA)] TJ ET",
        "BT /F1 8 Tf 42 620 Td (1 Nonemployee compensation 1000.00) Tj ET",
    ]])


def _answer(prompt):
    ids = Q.slot_ids(prompt)
    return {"fields": {ids["Payer Name"]: {"value": "FASTEATS", "source": "FASTEATS", "page": 1},
                       ids["Recipient Name"]: {"value": "MARTAGARCIA", "source": "MARTAGARCIA",
                                               "page": 1},
                       ids["Box 1 Nonemployee Compensation"]: {
                           "value": "1000.00", "source": "1 Nonemployee compensation 1000.00",
                           "page": 1}},
            "tables": {}}


def test_glued_words_get_their_printed_spacing_back_reconstructed(tmp_path):
    tpl = Q.template(fields=["Payer Name", "Recipient Name", "Box 1 Nonemployee Compensation"],
                     doc_type="form_1099")
    (r,) = Q.run(_glued_pdf(tmp_path), tpl, _answer)
    data = r.extracted_data["extracted_data"]
    assert data["Payer Name"]["value"] == "FAST EATS"
    assert data["Recipient Name"]["value"] == "MARTA GARCIA"
    assert data["Box 1 Nonemployee Compensation"]["value"] == "1000.00"   # a number untouched
    assert data["Payer Name"]["confidence"] != "low"


def test_a_number_is_never_split_by_a_gap():
    import text_layer as TL
    chars = [{"text": c, "x0": 10 + i * 5 + (3 if i == 2 else 0), "x1": 15 + i * 5 + (3 if i == 2 else 0),
              "size": 8} for i, c in enumerate("1250")]
    assert TL.spaced_reading(chars) is None
    letters = [{"text": c, "x0": x0, "x1": x0 + 5, "size": 8}
               for c, x0 in zip("ABCD", (10, 15, 22.2, 27.2))]
    assert TL.spaced_reading(letters) == "AB CD"


def test_money_written_as_money_exports_as_a_number_on_a_us_document():
    """Job 58 (tcnj_financials, no template): balance-sheet lines whose labels
    are not money words."""
    from tests.harness import bootstrap as bs
    bs.bootstrap()
    from app.services.excel_cells import coerce_cell_value, money_hint
    for value, label, want in [("$2,750", "Cash", 2750.0), ("(1,300)", "Net loss", -1300.0),
                               ("( 4,125)", "Treasury stock", -4125.0),
                               ("12,000", "Revenue", 12000.0)]:
        h = money_hint(label, None, True, value)
        assert coerce_cell_value(value, label, h) == want, value
    # an identifier stays text, and nothing changes on a non-US document
    assert coerce_cell_value("12,000", "Account No", money_hint("Account No", None, True, "12,000")) == "12,000"
    assert money_hint("Cash", None, False, "1,265") is None


# ── Phase 3: the real stored answers, replayed ───────────────────────────────

def _replayed(job):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    import replay_raw
    replay_raw._setup()
    return replay_raw.replay_job(job)


def test_real_job78_names_keep_their_printed_spacing():
    Q.need_answer(78, "irs6744_1099NEC_1099K_garcia.pdf")
    vals = [str(v.get("value")) for _m, ed, _x in _replayed(78)["docs"]
            for v in (ed.get("extracted_data") or {}).values() if isinstance(v, dict)]
    for glued in ("FASTEATS", "MARTAGARCIA", "123LILACAVENUE"):
        assert not any(glued in v for v in vals), glued


def test_real_job58_money_exports_as_numbers(tmp_path):
    import re
    import openpyxl
    import replay_raw
    Q.need_answer(58, "tcnj_financials.pdf")
    p = replay_raw.write_workbook(58, _replayed(58), tmp_path / "j58.xlsx")
    wb = openpyxl.load_workbook(p)
    as_text = [c.value for ws in wb.worksheets if ws.title != "Legend"
               for row in ws.iter_rows() for c in row
               if isinstance(c.value, str)
               and re.fullmatch(r"\(?\s*\$?\s*\d{1,3}(?:,\d{3})+(?:\.\d+)?\s*\)?|\$\s*\d+(?:\.\d+)?",
                                c.value.strip())]
    assert as_text == []
