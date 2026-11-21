"""Run Q, Q1 — lost pages.

Job 72 (mobile_vendor_list_8pg, no template) came back with 49 of 90 rows and
no warning. Cause, measured offline on the real file: the eight-page report
was cut into THREE documents (pages 1-4, 5, 6-8) because the only page number
it prints is a footer, "Report generated: 06/24/2026 14:36 Page 5", which the
"states its own position" veto did not read. Each slice was then asked for
its own rows and pages 2-4 were lost under the first.
"""
from __future__ import annotations

import pytest

import doc_boundaries as D
from tests import run_q_support as Q


def _report_pages(n=4):
    out = []
    for i in range(1, n + 1):
        out.append("\n".join([
            "City of Mobile",
            "VENDOR INVOICE LIST",
            "INVOICE P.O. INV DATE CHECK RUN CHECK # INVOICE NET PAID AMOUNT DUE DATE",
            f"{300000 + i} VENDOR {i}",
            f"Vendor No {700000 + i * 11}",
            f"00{i}5 06/22/2026 H062426 2021828{i} 75.00 75.00 07/22/2026 INV PD",
            f"Report generated: 06/24/2026 14:36 Page {i}",
            "User: 910513287",
        ]))
    return out


def test_a_report_footer_page_number_keeps_the_report_whole_reconstructed():
    starts, _why = D.find_starts(_report_pages(4))
    assert starts == [0]


def test_prose_page_reference_mid_line_is_not_a_footer():
    assert not D._states_its_own_position("see page 2 for the terms below", 1)
    assert D._states_its_own_position("Report generated: 06/24/2026 Page 2", 1)
    assert not D._states_its_own_position("Report generated: 06/24/2026 Page 7", 1)


def test_mobile_vendor_list_is_one_document_real():
    import pdfplumber
    f = Q.need_source("mobile_vendor_list_8pg.pdf")
    with pdfplumber.open(f) as p:
        texts = [pg.extract_text() or "" for pg in p.pages]
    assert D.find_starts(texts)[0] == [0]


# ── Q1b: a printed row count against the rows extracted ──────────────────────

_ROWS = [("INV-1001", "06/01/2026", "100.00"), ("INV-1002", "06/02/2026", "100.00"),
         ("INV-1003", "06/03/2026", "100.00"), ("INV-1004", "06/04/2026", "100.00"),
         ("INV-1005", "06/05/2026", "100.00")]


def _vendor_list(tmp_path, footer="5 INVOICES 500.00"):
    items = [(72, 740, "VENDOR INVOICE LIST"),
             (72, 700, "Invoice"), (220, 700, "Date"), (420, 700, "Amount")]
    y = 680
    for inv, d, a in _ROWS:
        items += [(72, y, inv), (220, y, d), (420, y, a)]
        y -= 18
    items += [(72, y - 10, footer)]
    return Q.make_pdf(tmp_path / "list.pdf", [items])


def _answer(n):
    def fn(prompt):
        name = Q.table_names(prompt)[0]
        rows = [{"Invoice": i, "Date": d, "Amount": a, "source": f"{i} {d} {a}", "page": 1}
                for i, d, a in _ROWS[:n]]
        return {"fields": {}, "tables": {name: rows}}
    return fn


def _reasons(ed):
    return " ".join(str(a.get("text") if isinstance(a, dict) else a)
                    for a in ed.get("attention") or []).casefold()


TPL = Q.template(tables=[(None, ["Invoice", "Date", "Amount"])], doc_type="invoice")


@pytest.mark.parametrize("footer", ["5 INVOICES 500.00", "Total Invoices Count 5",
                                    "Number of Invoices: 5"])
def test_rows_short_of_a_printed_count_are_named_reconstructed(tmp_path, footer):
    (r,) = Q.run(_vendor_list(tmp_path, footer), TPL, _answer(3))
    why = _reasons(r.extracted_data)
    assert "prints 5 invoice" in why and "3 row(s)" in why, why
    assert r.extracted_data.get("document_state") == "NEEDS_ATTENTION"


def test_rows_equal_to_the_printed_count_are_quiet(tmp_path):
    (r,) = Q.run(_vendor_list(tmp_path), TPL, _answer(5))
    assert "row_count_mismatch" not in _reasons(r.extracted_data)


def test_a_count_of_something_else_does_not_accuse_the_table(tmp_path):
    (r,) = Q.run(_vendor_list(tmp_path, "Number of Checks 8"), TPL, _answer(5))
    assert "row_count_mismatch" not in _reasons(r.extracted_data)
