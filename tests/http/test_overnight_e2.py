"""E2 — the review dialog can reach every page of a multi-page document.

mammoth_2pg has two pages; with page 2's rows lost, the job review listed
only page 1 (the pages holding a value) and the dialog could not move. The
document's pages come from its page ledger / inventory, and the page endpoint
reports the page count the dialog's previous / next use (frontend tests:
frontend/lib/reviewPages.test.ts).
"""

from __future__ import annotations

from tests.http.test_review_routes import job  # noqa: F401  (fixture)


def test_every_page_of_the_document_is_listed_not_only_pages_with_values():
    from app.api.routes.review import _pages_of

    ed = {"field_provenance": {"B1": {"page": 1}},
          "Transactions_rows": [{"Date": "08/02/2026", "_page": 1}],
          "slot_map": {"tables": [{"name": "Transactions"}]},
          "diagnostics": {"pages": {"1": "processed", "2": "processed"},
                          "inventory": {"pages": 2}}}
    assert _pages_of(ed) == [1, 2]


def test_a_split_document_keeps_its_own_page_range():
    from app.api.routes.review import _pages_of

    ed = {"source_pages": [3, 4], "field_provenance": {"B1": {"page": 3}},
          "diagnostics": {"inventory": {"pages": 6}}}
    assert _pages_of(ed) == [3, 4]


def test_the_page_endpoint_reports_the_page_count(client, auth, job):  # noqa: F811
    jid, did = job
    r = client.get(f"/api/jobs/{jid}/docs/{did}/pages/1", headers=auth["acme2"])
    assert r.status_code == 200, r.text
    assert isinstance(r.json()["page_count"], int) and r.json()["page_count"] >= 1
