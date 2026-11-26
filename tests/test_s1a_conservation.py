"""Run S, Stage 1a — conservation: nothing printed at a structural position
leaves the page without a word.

A structural token is a number at a position a person copying the page into
a sheet would copy: a table-row cell, a group header's identifier, a
subtotal or total, a labelled field's value. Every one is either held by a
value of the output, named by a reason that already exists (`not_captured`,
an attention item, a flag), or it raises a reason NAMING it.

Not structural, by design: page furniture (a line repeated on several pages,
"Page n of m"), paragraph prose, form metadata (OMB No., Rev., Cat. No.),
phone numbers, and the digits of an address or of a label's own words
("Section 897 Ordinary Dividends ....0.00": 0.00 is the value, 897 is not).

The cases the prompt names: Total Deduction left empty on a pay stub; vendor
numbers missing (job 138); the 1099-K amounts (job 115); a statement's
"Checks/withdrawals" total; fidelity's amounts. Unit cases here use generated
lines; the `_real` cases replay stored answers and skip when local_docs is
absent.
"""
from __future__ import annotations

import pytest

import conservation as CV


def _line(text, page=1, y=0.0, x=56.0):
    out = []
    for t in text.split():
        out.append({"text": t, "x0": x, "x1": x + 5 * len(t), "top": y,
                    "bottom": y + 8, "page": page})
        x += 5 * len(t) + 4
    return out


def _page(texts, page=1, top=60.0):
    return [_line(t, page, top + 14 * i) for i, t in enumerate(texts)]


# ── what is structural ──────────────────────────────────────────────────────

def _toks(pages):
    return {(t.text, t.role) for t in CV.structural_tokens(pages, list(range(1, len(pages) + 1)))}


def test_row_cells_totals_and_field_values_are_structural():
    pages = [_page([
        "Statement period: 01/01/2025 to 01/31/2025",
        "Date Description Amount Balance",
        "01/03/2025 PAYROLL DEPOSIT 1,250.00 4,250.00",
        "01/09/2025 CARD PURCHASE 45.10 4,204.90",
        "Total withdrawals 45.10",
        "Checks/withdrawals 54 $14,365.21",
    ])]
    t = _toks(pages)
    assert ("1,250.00", "row") in t and ("01/09/2025", "row") in t
    assert ("$14,365.21", "total") in t
    assert ("01/01/2025", "field") in t


def test_furniture_metadata_phones_and_label_digits_are_not():
    p1 = _page(["ACME BANK Page 1 of 2", "OMB No. 1545-0008",
                "Customer service: 1.800.888.8888", "(316)777-1171",
                "122 W Main", "Mulvane, KS 67110",
                "2e Section 897 Ordinary Dividends ..............0.00",
                "This statement is provided for your records and should be kept with "
                "your other important papers for a period of seven years 2025."])
    p2 = _page(["ACME BANK Page 2 of 2"], page=2)
    t = {x for x, _r in _toks([p1, p2])}
    for bad in ("1545-0008", "1.800.888.8888", "(316)777-1171", "122", "67110", "897",
                "2025."):
        assert bad not in t, bad
    assert "0.00" in t


def test_group_header_identifiers_are_structural():
    pages = [_page(["VENDOR INVOICE LIST", "INVOICE DATE NET PAID",
                    "300055 ANDERSON DULANEY", "0025 06/22/2026 75.00 75.00",
                    "299694 B&B LAWN", "2937 06/16/2026 2,480.00 2,480.00",
                    "2938 06/17/2026 2,400.00 2,400.00", "4,880.00",
                    "20320 BAGBY ELECTRIC", "1 05/28/2026 100.00 100.00",
                    "2 05/28/2026 50.00 50.00", "150.00"])]
    t = _toks(pages)
    assert ("300055", "group") in t and ("20320", "group") in t
    assert ("4,880.00", "total") in t


# ── the check ───────────────────────────────────────────────────────────────

def _check(pages, values, said=(), templated=False, band_pages=None):
    return CV.check(pages, list(range(1, len(pages) + 1)), values, said,
                    templated=templated, band_pages=band_pages)


VENDOR = [_page(["VENDOR INVOICE LIST", "INVOICE DATE NET PAID",
                 "300055 ANDERSON DULANEY", "0025 06/22/2026 75.00 75.00",
                 "299694 B&B LAWN", "2937 06/16/2026 2,480.00 2,480.00",
                 "2938 06/17/2026 2,400.00 2,400.00", "4,880.00",
                 "20320 BAGBY ELECTRIC", "1 05/28/2026 100.00 100.00",
                 "2 05/28/2026 50.00 50.00", "150.00"])]
ROW_VALUES = ["0025", "06/22/2026", "75.00", "2937", "06/16/2026", "2,480.00", "2938",
              "06/17/2026", "2,400.00", "1", "05/28/2026", "100.00", "2", "50.00",
              "4,880.00", "150.00"]


def test_vendor_numbers_missing_are_named_job_138():
    out = _check(VENDOR, ROW_VALUES + ["ANDERSON DULANEY", "B&B LAWN", "BAGBY ELECTRIC"])
    assert len(out["attention"]) == 1
    msg = out["attention"][0]
    for v in ("300055", "299694", "20320"):
        assert v in msg
    assert "group header" in msg
    assert {m.text for m in out["missing"]} == {"300055", "299694", "20320"}


def test_nothing_is_said_when_everything_is_held():
    out = _check(VENDOR, ROW_VALUES + ["300055", "299694", "20320"])
    assert out["attention"] == [] and out["not_captured"] == [] and out["missing"] == []


def test_a_value_in_a_longer_cell_is_held():
    out = _check(VENDOR, ROW_VALUES + ["300055 ANDERSON DULANEY", "299694 B&B LAWN",
                                       "Vendor 20320"])
    assert out["missing"] == []


def test_money_is_held_in_any_notation():
    pages = [_page(["Date Description Amount", "01/03/2025 DEPOSIT 1,250.00 9.00"])]
    out = _check(pages, ["01/03/2025", "$1250.00", "9"])
    assert out["missing"] == []


def test_a_token_an_existing_reason_already_names_is_not_said_twice():
    out = _check(VENDOR, ROW_VALUES, said=[
        "Not in this file: the vendor numbers 300055, 299694 and 20320."])
    assert out["attention"] == [] and out["missing"] == []


def test_a_missing_total_is_named_the_pay_stub_total_deduction():
    pages = [_page(["Deductions Current YTD", "Federal Tax 120.00 1,440.00",
                    "State Tax 40.00 480.00", "Total Deduction 160.00 1,920.00",
                    "Net Pay: 840.00"])]
    out = _check(pages, ["120.00", "1,440.00", "40.00", "480.00", "840.00"])
    assert "160.00" in out["attention"][0] and "1,920.00" in out["attention"][0]
    assert "total" in out["attention"][0]


def test_many_missing_tokens_are_counted_and_the_first_named():
    rows = [f"01/{d:02d}/2025 ITEM{d} {d}.00 {100 + d}.00" for d in range(1, 26)]
    pages = [_page(["Date Item Amount Balance"] + rows)]
    out = _check(pages, [])
    msg = out["attention"][0]
    assert "100 printed figures" in msg or "75 printed figures" in msg or "figures" in msg
    assert "and " in msg and "more" in msg
    assert len(out["missing"]) >= 75


def test_templated_tokens_outside_the_templates_tables_are_a_note_not_attention():
    """A template that does not ask for the summary box: the figures are
    printed and not in the file, which is SAID (not_captured, shown in the
    Results sheet and the Legend), but the template chose them out, so the
    document is not called incomplete."""
    pages = [_page(["Summary", "Beginning balance 1,000.00",
                    "Total deposits 250.00", "Date Description Amount",
                    "01/03/2025 DEPOSIT 250.00 1,250.00"])]
    out = _check(pages, ["01/03/2025", "DEPOSIT", "250.00", "1,250.00"],
                 templated=True, band_pages={1})
    assert out["attention"] == []
    assert out["not_captured"] and "1,000.00" in out["not_captured"][0]


def test_templated_missing_row_on_a_table_page_is_attention():
    pages = [_page(["Date Description Amount Balance",
                    "07/01/2019 DEPOSIT 209.54 654.82",
                    "07/03/2019 DEPOSIT CORRECTION CREDIT $13.04 $1,471.53"])]
    out = _check(pages, ["07/01/2019", "209.54", "654.82"], templated=True, band_pages={1})
    assert out["attention"] and "$13.04" in out["attention"][0]
    assert "table row" in out["attention"][0]


@pytest.mark.parametrize("vocab", [
    ("Account 4411-2290 RIVERSIDE HOLDINGS", "Txn Date Amount", "T1 03/01/2025 10.00 10.00"),
    ("Customer Code: KX-77 Harbor Foods", "Ref Date Current Over30", "A1 03/01/2025 120.00 0.00"),
    ("EMP0042 Jane Q. Doe", "Code Hours Rate Gross", "REG 40 25.00 1,000.00"),
])
def test_any_vocabulary_row_tokens_are_conserved(vocab):
    head, cols, row = vocab
    pages = [_page([cols, head, row, row.replace("10.00", "11.00").replace(
        "120.00", "121.00").replace("1,000.00", "1,001.00")])]
    out = _check(pages, [])
    assert out["missing"], vocab
    assert any("03/01/2025" in a or "25.00" in a for a in out["attention"])


# ── end to end through the pipeline ────────────────────────────────────────

def test_end_to_end_the_reason_reaches_the_result(tmp_path):
    from tests import run_q_support as Q
    items = [(56, 760 - 16 * i, t) for i, t in enumerate([
        "ACME CHECKING STATEMENT", "Account Holder: Pat Lee",
        "Date Description Amount Balance",
        "07/01/2019 DEPOSIT 209.54 654.82",
        "07/03/2019 SERVICE CHARGE 10.00 644.82",
        "07/05/2019 DEPOSIT CORRECTION CREDIT 13.04 657.86"])]
    pdf = Q.make_pdf(tmp_path / "s.pdf", [items], size=9)
    tpl = Q.template(fields=["Account Holder"],
                     tables=[(None, ["Date", "Description", "Amount", "Balance"])],
                     doc_type="bank_statement")

    def answer(prompt):
        ids = Q.slot_ids(prompt)
        name = Q.table_names(prompt)[0]
        rows = [{"Date": "07/01/2019", "Description": "DEPOSIT", "Amount": "209.54",
                 "Balance": "654.82", "source": "07/01/2019 DEPOSIT 209.54 654.82", "page": 1},
                {"Date": "07/03/2019", "Description": "SERVICE CHARGE", "Amount": "10.00",
                 "Balance": "644.82", "source": "07/03/2019 SERVICE CHARGE 10.00 644.82",
                 "page": 1}]
        return {"fields": {ids["Account Holder"]: {"value": "Pat Lee",
                                                  "source": "Account Holder: Pat Lee",
                                                  "page": 1}},
                "tables": {name: rows}}

    ed = Q.run(pdf, tpl, answer)[0].extracted_data
    texts = [a["text"] for a in ed["attention"]]
    assert any("13.04" in t and "657.86" in t for t in texts), texts
    assert ed["document_state"] == "NEEDS_ATTENTION"


def test_a_figure_glued_to_an_unreadable_glyph_is_named_the_total_deduction():
    """utah_paystub_2: `Total Deduction:` is followed by `�` `12` - the
    figure's first glyphs have no character in the text layer. `12` alone
    would be "held" by Federal Tax's $12, so a figure that is partly
    unreadable is its own token, held by no value, and named."""
    line = _line("Total Deduction:", 1, 300)
    line.append({"text": "�", "x0": 526.0, "x1": 532.0, "top": 300, "bottom": 308,
                 "page": 1})
    line.append({"text": "12", "x0": 529.0, "x1": 540.0, "top": 300, "bottom": 308,
                 "page": 1})
    pages = [_page(["Deductions Current YTD", "Federal Tax $12 $96"]) + [line]]
    out = _check(pages, ["$12", "$96"])
    assert out["attention"], out
    assert "�12" in out["attention"][0] and "total" in out["attention"][0]
