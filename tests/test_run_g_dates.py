"""Run G, G6: a date slot holding one unambiguous date is a real Excel date
(mm/dd/yyyy); anything else stays the printed text, and an ambiguous one says
why. Offline; the export writers only."""
from __future__ import annotations

import io
from datetime import date, datetime

import pytest
from openpyxl import Workbook, load_workbook

from app.services.excel_cells import (DATE_AMBIGUOUS_NOTE, DATE_FORMAT,
                                      DATE_TWO_DIGIT_NOTE, date_order_of,
                                      excel_date, put_extracted)


@pytest.mark.parametrize("printed,want", [
    ("09/30/2026", date(2026, 9, 30)),        # day above 12: month-first, fixed
    ("30/09/2026", date(2026, 9, 30)),        # day above 12: day-first, fixed
    ("14 Oct 2026", date(2026, 10, 14)),
    ("2026-10-05", date(2026, 10, 5)),
    ("October 5, 2026", date(2026, 10, 5)),
])
def test_each_printed_form_is_a_real_date(printed, want):
    assert excel_date(printed, "Invoice Date") == (want, None)


def test_other_dates_on_the_record_fix_the_order():
    us = {"extracted_fields": {"B1": "03/04/2026", "B2": "09/30/2026"}}
    eu = {"extracted_fields": {"B1": "03/04/2026"},
          "field_provenance": {"B9": {"source": "Delivered 30/09/2026 to the depot"}}}
    assert excel_date("03/04/2026", "Invoice Date", date_order_of(us)) == (date(2026, 3, 4), None)
    assert excel_date("03/04/2026", "Invoice Date", date_order_of(eu)) == (date(2026, 4, 3), None)


def test_disagreeing_cues_fix_nothing():
    mixed = {"extracted_fields": {"B1": "09/30/2026", "B2": "30/09/2026"}}
    assert date_order_of(mixed) is None
    assert excel_date("03/04/2026", "Due Date", date_order_of(mixed)) == (None, DATE_AMBIGUOUS_NOTE)


def _cell():
    return Workbook().active.cell(row=1, column=1)


def test_an_ambiguous_date_stays_printed_text_with_a_plain_sentence():
    c = _cell()
    put_extracted(c, "03/04/2026", "Statement Date", {"extracted_fields": {"B1": "03/04/2026"}})
    assert c.value == "03/04/2026" and c.data_type == "s"
    assert c.comment.text.startswith(DATE_AMBIGUOUS_NOTE)


def test_a_date_in_a_sentence_and_a_range_stay_text_without_a_note():
    for v in ("Payment is due on 09/30/2026 by noon", "09/01/2026 to 09/30/2026"):
        c = _cell()
        put_extracted(c, v, "Due Date", {})
        assert c.value == v and c.comment is None


def test_a_two_digit_year_is_not_given_a_century():
    assert excel_date("09/30/26", "Invoice Date") == (None, DATE_TWO_DIGIT_NOTE)


def test_a_slot_that_is_not_a_date_is_never_converted():
    assert excel_date("2026-10-05", "Invoice Number") == (None, None)
    assert excel_date("2026-10-05", "Pay Period Date Range") == (None, None)
    c = _cell()
    put_extracted(c, "2026-10-05", "Reference", {})
    assert c.value == "2026-10-05"


def test_the_written_cell_is_a_date_cell_after_a_round_trip():
    wb = Workbook()
    c = wb.active.cell(row=1, column=1)
    put_extracted(c, "October 5, 2026", "Payment Date", {})
    buf = io.BytesIO()
    wb.save(buf)
    back = load_workbook(io.BytesIO(buf.getvalue())).active["A1"]
    assert back.is_date and back.number_format == DATE_FORMAT
    assert back.value == datetime(2026, 10, 5)


def test_the_template_writer_writes_table_dates_by_the_same_rule(client, db, users, auth):
    import json
    from app.models.models import DocumentResult
    from tests.test_run_g_review import _template_case
    case = _template_case(db, users, auth)
    url = f"/api/jobs/{case.job_id}/export"
    ws = load_workbook(io.BytesIO(client.get(url, headers=case.headers).content))["Results"]
    assert ws["A6"].value == "03/04/2026"                       # nothing fixes the order
    assert DATE_AMBIGUOUS_NOTE in ws["A6"].comment.text       # after its review mark
    doc = db.get(DocumentResult, case.doc_id)
    ed = doc.get_extracted_data()
    ed["table_rows"][0]["Date"] = "09/30/2026"
    doc.extraction_json = json.dumps(ed)
    db.commit()
    ws = load_workbook(io.BytesIO(client.get(url, headers=case.headers).content))["Results"]
    assert ws["A6"].is_date and ws["A6"].value == datetime(2026, 9, 30)
    assert ws["A6"].number_format == DATE_FORMAT


from tests.http.conftest import (  # noqa: E402,F401
    _db_url, _scratch_storage, app, auth, client, db, users,
)
