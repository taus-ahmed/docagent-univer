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
