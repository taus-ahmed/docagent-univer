"""Run S, Stage 3a — a grounded value whose owner is not the slot's party.

The ENGIE bill (round-2 run 9) answered `Customer Email Address` with the
issuer's own `care@engieresources.com` at HIGH confidence: printed, so
grounded, but not the customer's. The general rule (engine/party_fit.py):
a contact the document's ISSUER owns (printed on two or more pages, or its
domain spelling the letterhead) answering a COUNTERPARTY's slot is Low and
flagged, never blanked. The strict xfail in test_round2_I1 stays: it asks
for the value to be EMPTY, and the value is still written - now marked.
"""
from __future__ import annotations

import pytest

from tests.harness import bootstrap as _bs

_bs.bootstrap()

import party_fit as PF  # noqa: E402
from tests.harness import round2  # noqa: E402

PAGES = ["ACME POWER LLC\nStatement for Pat Lee\nAccount 001\n"
         "Questions? care@acmepower.com\nCustomer email: pat.lee@mail.com",
         "Page 2\nWrite to care@acmepower.com\n"]


def test_an_issuer_contact_printed_on_two_pages_is_the_issuers():
    assert PF.issuer_contact("care@acmepower.com", PAGES)


def test_a_domain_spelling_the_letterhead_is_the_issuers():
    pages = ["ACME POWER LLC\nStatement\n\nhelp@acmepower.com"]
    assert PF.issuer_contact("help@acmepower.com", pages)
    assert PF.issuer_contact("www.acmepower.com", pages)


def test_the_customers_own_address_is_not():
    assert not PF.issuer_contact("pat.lee@mail.com", PAGES)
    # a counterparty's company printed often, but not as the letterhead
    pages = ["NORTHWIND SUPPLY\nInvoice 77\nBill To: Harbor Foods\nHarbor Foods\n"
             "ap@harborfoods.com"]
    assert not PF.issuer_contact("ap@harborfoods.com", pages)


def test_only_a_counterpartys_slot_is_misowned():
    assert PF.misowned("Customer Email Address", "care@acmepower.com", PAGES)
    assert PF.misowned("Supplier Email", "care@acmepower.com", PAGES) is None
    assert PF.misowned("Customer Email Address", "pat.lee@mail.com", PAGES) is None


@pytest.fixture(scope="module")
def engie():
    results, _grid, _log = round2.run("run9_engie_BR4", mode="replay")
    return results[0].extracted_data


def test_engie_customer_email_is_low_and_says_whose_it_is(engie):
    ref = next(f["ref"] for f in engie["slot_map"]["fields"]
               if f["row_label"] == "Customer Email Address")
    assert engie["extracted_fields"].get(ref) == "care@engieresources.com"
    assert engie["validation"]["confidence_map"][ref] == "low"
    reasons = [f["reason"] for f in engie["validation"]["flagged_fields"]
               if f.get("ref") in ("Customer Email Address", ref)]
    assert any("issuer's own contact" in r for r in reasons), reasons


def test_no_other_engie_value_is_demoted_by_the_rule(engie):
    hits = [f for f in engie["validation"]["flagged_fields"]
            if "issuer's own contact" in str(f.get("reason"))]
    assert len(hits) == 1
