"""Review marks do not lose each other (Run 15, item 3).

Marking read the document's stored JSON, changed it and wrote the whole of it
back. Two reviewers marking DIFFERENT values at the same moment both read the
same version, and the second write erased the first mark: a value a person
had checked went back to "needs review", or — worse, the other way round —
the summary said reviewed for a write that no longer held the marks it
counted. The write is now a compare-and-swap on the stored text, re-read and
re-applied on a conflict, so both marks persist.
"""
from __future__ import annotations

import json
import threading

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()


@pytest.fixture
def doc(db, users):
    from app.models.models import DocumentResult, ExtractionJob
    j = ExtractionJob(user_id=users["acme2"].id, client_id="acme_001",
                      status="completed", total_docs=1, input_source="upload")
    db.add(j); db.commit(); db.refresh(j)
    ed = {"extracted_fields": {"B2": "1", "B3": "2", "B4": "3"},
          "field_provenance": {
              r: {"source": "x", "page": 1, "grounded": False,
                  "review_required": True, "review_reasons": ["grounding_failed"]}
              for r in ("B2", "B3", "B4")},
          "validation": {"confidence_map": {"B2": "low", "B3": "low", "B4": "low"}}}
    d = DocumentResult(job_id=j.id, filename="a.pdf", original_filename="a.pdf",
                       document_type="invoice", extraction_json=json.dumps(ed),
                       needs_review=True)
    db.add(d); db.commit(); db.refresh(d)
    return j.id, d.id


def _stored(db, did):
    from app.models.models import DocumentResult
    db.expire_all()
    d = db.get(DocumentResult, did)
    return d, json.loads(d.extraction_json)


def test_two_simultaneous_marks_on_different_values_both_persist(
        client, auth, doc, db, monkeypatch):
    from app.api.routes import review
    jid, did = doc
    url = f"/api/jobs/{jid}/docs/{did}/review"
    barrier = threading.Barrier(2, timeout=20)
    first = {}
    original = review._apply_marks

    def synchronised(ed, payload, stamp):
        out = original(ed, payload, stamp)
        me = threading.get_ident()
        if me not in first:            # only the first attempt waits
            first[me] = True
            barrier.wait()             # both have read the SAME version
        return out
    monkeypatch.setattr(review, "_apply_marks", synchronised)

    answers = {}

    def mark(ref):
        answers[ref] = client.post(url, headers=auth["acme2"],
                                   json={"values": [{"ref": ref}]})
    threads = [threading.Thread(target=mark, args=(r,)) for r in ("B2", "B3")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert all(a.status_code == 200 for a in answers.values()), \
        {r: a.text for r, a in answers.items()}
    _, ed = _stored(db, did)
    prov = ed["field_provenance"]
    assert "reviewed" in prov["B2"] and "reviewed" in prov["B3"]
    assert "reviewed" not in prov["B4"]


def test_the_last_mark_closes_the_document_even_when_racing(
        client, auth, doc, db, monkeypatch):
    """Three marks at once: the document ends reviewed, with all three."""
    from app.api.routes import review
    jid, did = doc
    url = f"/api/jobs/{jid}/docs/{did}/review"
    barrier = threading.Barrier(3, timeout=20)
    first = {}
    original = review._apply_marks

    def synchronised(ed, payload, stamp):
        out = original(ed, payload, stamp)
        if threading.get_ident() not in first:
            first[threading.get_ident()] = True
            barrier.wait()
        return out
    monkeypatch.setattr(review, "_apply_marks", synchronised)
    threads = [threading.Thread(target=client.post, args=(url,),
                                kwargs={"headers": auth["acme2"],
                                        "json": {"values": [{"ref": r}]}})
               for r in ("B2", "B3", "B4")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    d, ed = _stored(db, did)
    assert all("reviewed" in ed["field_provenance"][r] for r in ("B2", "B3", "B4"))
    assert d.reviewed is True and d.needs_review is False


def test_marking_the_same_value_twice_is_idempotent(client, auth, doc, db):
    jid, did = doc
    url = f"/api/jobs/{jid}/docs/{did}/review"
    for _ in range(2):
        r = client.post(url, headers=auth["acme2"], json={"values": [{"ref": "B2"}]})
        assert r.status_code == 200
    _, ed = _stored(db, did)
    assert set(ed["field_provenance"]["B2"]["reviewed"]) == {"by", "at"}
    assert r.json()["summary"]["needs_review"] == 2


def test_a_conflict_that_never_clears_is_an_error_not_a_lost_mark(
        client, auth, doc, db, monkeypatch):
    from app.api.routes import review
    jid, did = doc
    monkeypatch.setattr(review, "_swap", lambda *a, **k: False)
    r = client.post(f"/api/jobs/{jid}/docs/{did}/review", headers=auth["acme2"],
                    json={"values": [{"ref": "B2"}]})
    assert r.status_code == 409
    _, ed = _stored(db, did)
    assert "reviewed" not in ed["field_provenance"]["B2"]
