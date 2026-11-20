"""Run F: pins beside the Batch 2 strict xfails (offline, scripted answers)."""
from __future__ import annotations

import tests.test_batch2_failure_classes as B


_FORM = ["Purchase Order", "Date: 03/04/2026",
          "Purchase Order #: ____________", "Shipping Date: ____________",
          "Buyer: ____________", "Address: ____________", "Phone: ____________",
          "Company Name: ____________"]


def _synthetic(grid, answer):
    return B.D.run_synthetic(lambda **_kw: B.D.model_response(answer), [_FORM], grid=grid)


def test_f2_real_pay_lines_and_sentences_on_other_documents_are_data():
    import real_data as RD
    assert RD.refusal("$1,234.56", "Net Pay $1,234.56", "Net Pay",
                      family="payslip", page_texts=[], specimen=False) == ""
    # a bill states real amounts in sentences; the prose rule is pay-only
    sentence = ("Your payment of $500.00 is due on the 15th and will be taken "
                "from the account on file for this bill")
    assert RD.refusal("$500.00", sentence, "Amount Due", family="invoice",
                      page_texts=[], specimen=False) == ""
    assert RD.refusal("$500.00", sentence, "Net Pay", family="payslip",
                      page_texts=[], specimen=False)
    # a quantity of 8 on an ordinary line is not a list number
    assert RD.refusal("8", "Hours worked 8", "Hours", family="payslip",
                      page_texts=[], specimen=False) == ""


def test_f3_a_real_name_containing_sample_on_an_ordinary_document_is_data():
    import real_data as RD
    ordinary = ["SAMPLE DOCUMENT — FICTIONAL BUSINESS\nBill To: Sample & Sons Ltd"]
    assert not RD.specimen_document(ordinary)
    assert RD.refusal("Sample & Sons Ltd", "Bill To: Sample & Sons Ltd", "Bill To",
                      family="invoice", page_texts=ordinary,
                      specimen=RD.specimen_document(ordinary)) == ""
    specimen = ["SAMPLE 2024 TAX FORM 1099-B\nMR A SAMPLE\nADD 1 Payer's Details"]
    assert RD.specimen_document(specimen)
    assert RD.refusal("ADD 3", "ADD 3", "Payer Address", family="form_1099",
                      page_texts=specimen, specimen=True)


def test_f1_one_grounded_value_means_the_form_is_not_blank():
    """A labels-and-blanks page with ONE value really filled in: nothing is
    cleared, and the invented answer keeps its ordinary flag."""
    grid = B._scalar_grid("Date", "Purchase Order Number")
    data = _synthetic(grid, B._answer(fields={
        B._field_id(grid, "Date"): {"value": "03/04/2026",
                                    "source": "Date: 03/04/2026", "page": 1},
        B._field_id(grid, "Purchase Order Number"): {
            "value": "PO-9999", "source": "Purchase Order #: ____________", "page": 1},
    }))
    assert set(data["extracted_fields"].values()) == {"03/04/2026", "PO-9999"}
    assert any(f["ref"] == "Purchase Order Number" for f in B._flags(data))
    assert not any("No data found" in str(a.get("text")) for a in data["attention"])


def test_f1_the_same_page_with_nothing_filled_is_no_data():
    grid = B._scalar_grid("Purchase Order Number", "Seller Company Name")
    data = _synthetic(grid, B._answer(fields={
        B._field_id(grid, "Purchase Order Number"): {
            "value": "PO-9999", "source": "Purchase Order #: ____________", "page": 1},
        B._field_id(grid, "Seller Company Name"): {
            "value": "ACME SUPPLY", "source": "Company Name: ____________", "page": 1},
    }))
    assert data["extracted_fields"] == {} and B._flags(data) == []
    assert data["document_state"] == "NEEDS_ATTENTION"
    assert any("No data found" in str(a.get("text")) for a in data["attention"])


def test_f1_a_model_that_answers_nothing_is_not_called_no_data():
    """Batch 2's test_06 shape on the blank PO: empty answers stay READY-able,
    because nothing was offered and nothing was refused."""
    grid = B._scalar_grid("Date", "Purchase Order Number")
    data = B._run_pdf("blank_po", grid, B._answer(fields={}), doc_type="purchase_order")
    assert not any("No data found" in str(a.get("text")) for a in data["attention"])
