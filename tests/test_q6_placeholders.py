"""Run Q, Q6 — dummy text is not a value: empty, unflagged; masked numbers stay.

Reconstructed from jobs 79 (`YOUR CITY, YOUR STATE, ZIP`, `YOUR PHONE`),
74 (`XX,XXX.00`, `<140322-WSU _ _ _ >`), 75 (`00/00/00`), 64
(`City, State, Zip`, `DESIGNATION (IF ANY)`) and 60 (Pay Group =
`Business Unit`, printed `Business Unit:`).
"""
from __future__ import annotations

from tests import run_q_support as Q

LABELS = ["City or town", "Telephone number", "PAYER'S TIN", "RECIPIENT'S TIN",
          "Amount Due", "Invoice Ref", "Date Paid", "Pay Group", "Designation"]
ANSWERS = {"City or town": "YOUR CITY, YOUR STATE, ZIP", "Telephone number": "YOUR PHONE",
           "PAYER'S TIN": "40-100XXXX", "RECIPIENT'S TIN": "127-00-XXXX",
           "Amount Due": "XX,XXX.00", "Invoice Ref": "<140322-WSU _ _ _ _ >",
           "Date Paid": "00/00/00", "Pay Group": "Business Unit",
           "Designation": "DESIGNATION (IF ANY)"}
EMPTY = {"City or town", "Telephone number", "Amount Due", "Invoice Ref", "Date Paid",
         "Pay Group", "Designation"}


def _pdf(tmp_path):
    items, y = [(72, 750, "SAMPLE FORM 1099-R DISTRIBUTIONS")], 720
    for lab in LABELS:
        # job 60: "Pay Group" sits beside ANOTHER field's printed label
        items.append((72, y, f"{lab} {ANSWERS[lab]}" if lab != "Pay Group"
                      else "Pay Group      Business Unit: 400"))
        y -= 20
    return Q.make_pdf(tmp_path / "sample.pdf", [items])


def _answer(prompt):
    ids = Q.slot_ids(prompt)
    return {"fields": {ids[lab]: {"value": v, "source": (f"{lab} {v}" if lab != "Pay Group"
                                                        else "Pay Group Business Unit:"),
                                             "page": 1}
                       for lab, v in ANSWERS.items()},
            "tables": {n: [] for n in Q.table_names(prompt)}}


def test_placeholders_are_empty_and_unflagged_masked_numbers_stay_reconstructed(tmp_path):
    (r,) = Q.run(_pdf(tmp_path), Q.template(fields=LABELS, doc_type="form_1099"), _answer)
    ed = r.extracted_data
    data = ed["extracted_data"]
    for lab in EMPTY:
        assert not str((data.get(lab) or {}).get("value") or "").strip(), (lab, data.get(lab))
    assert data["PAYER'S TIN"]["value"] == "40-100XXXX"
    assert data["RECIPIENT'S TIN"]["value"] == "127-00-XXXX"
    flagged = {str(f.get("ref")) for f in ed["validation"]["flagged_fields"]}
    labels_flagged = {str(f.get("ref")) for f in ed["validation"]["flagged_fields"]} | {
        str(f.get("label", "")) for f in ed["validation"]["flagged_fields"]}
    for lab in EMPTY:
        assert lab not in labels_flagged and lab not in flagged, lab
    notes = " ".join(ed.get("validation_notes") or [])
    assert "placeholder text" in notes


def test_a_placeholder_table_cell_is_emptied(tmp_path):
    pdf = Q.make_pdf(tmp_path / "t.pdf", [[
        (72, 740, "SAMPLE INVOICE"),
        (72, 700, "Description"), (300, 700, "Amount"),
        (72, 680, "Consulting"), (300, 680, "XX,XXX.00"),
    ]])
    tpl = Q.template(tables=[(None, ["Description", "Amount"])], doc_type="invoice")

    def ans(prompt):
        name = Q.table_names(prompt)[0]
        return {"fields": {}, "tables": {name: [
            {"Description": "Consulting", "Amount": "XX,XXX.00",
             "source": "Consulting XX,XXX.00", "page": 1}]}}
    (r,) = Q.run(pdf, tpl, ans)
    rows = next(v for k, v in r.extracted_data.items() if k.endswith("_rows") and v)
    assert rows[0]["Description"] == "Consulting" and rows[0]["Amount"] == ""


def test_a_word_printed_once_as_a_label_and_once_as_a_value_is_kept(tmp_path):
    import real_data as RD
    assert not RD.printed_label_as_value("Business Unit", ["Business Unit: 400",
                                                          "Pay Group Business Unit"])
    assert RD.printed_label_as_value("Business Unit", ["Business Unit: 400"])
    assert not RD.placeholder_value("X")                 # a tick
    assert not RD.placeholder_value("XXX-XX-1234")       # a real masked SSN


def test_an_all_mask_id_is_a_placeholder_only_on_a_sample():
    """irs_1099nec_ellis (a real form) holds XXX-XX-XXXX as its Recipient
    TIN and keeps it; on a document that calls itself a SAMPLE it is dummy."""
    import real_data as RD
    assert not RD.placeholder_value("XXX-XX-XXXX")
    assert RD.placeholder_value("XXX-XX-XXXX", sample=True)
    assert not RD.placeholder_value("XXX-XX-1234", sample=True)
    assert RD.sample_document(["SAMPLE FORM 1099-R"]) and not RD.sample_document(["Form 1099-NEC"])
