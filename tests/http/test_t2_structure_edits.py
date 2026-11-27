"""Run T2, Stage 6: reviewer structure edits - stored as changes to the plan
with who and when, applied by the export, deterministic, refused when they
cannot apply. Contract: docs/REVIEWER_STRUCTURE_API.md."""
import io
import json

from openpyxl import load_workbook

from tests.harness import bootstrap as bs
from tests.run_q_support import make_pdf

bs.bootstrap()

ITEMS = [(72, 740, "Member Name: Jane Roe"),
         (72, 700, "Kind"), (300, 700, "Amount"),
         (72, 686, "Alpha"), (330, 686, "1.50"),
         (72, 672, "Beta"), (330, 672, "2.75"),
         (72, 658, "Gamma"), (330, 658, "3.00"),
         (72, 620, "Stray footer words")]


def _job(db, users, tmp_path):
    import perception as P
    from app.models.models import DocumentResult, ExtractionJob
    j = ExtractionJob(user_id=users["acme"].id, client_id="acme_001", status="completed",
                      total_docs=1, successful=1, input_source="upload")
    db.add(j)
    db.commit()
    db.refresh(j)
    pdf = make_pdf(tmp_path / "e.pdf", [ITEMS])
    d = DocumentResult(job_id=j.id, filename="e.pdf", original_filename="e.pdf", s3_key=None,
                       extraction_json=json.dumps({"extracted_fields": {}}),
                       perception_json=P.pack(P.read_document(pdf)),
                       needs_review=False, reviewed=False)
    db.add(d)
    db.commit()
    db.refresh(d)
    return j, d


def _url(j, d, tail=""):
    return f"/api/jobs/{j.id}/docs/{d.id}/structure{tail}"


def _cell(view, text, page=1):
    return next(c for c in view["pages"][page - 1]["cells"] if c["text"] == text)


def _sheet(client, j, auth):
    r = client.get(f"/api/jobs/{j.id}/export?layout=organized", headers=auth["acme"])
    assert r.status_code == 200, r.text
    ws = load_workbook(io.BytesIO(r.content))["e"]
    return {c.coordinate: c.value for row in ws.iter_rows() for c in row if c.value is not None}


def test_the_layout_view_lists_cells_regions_and_lines(client, db, users, auth, tmp_path):
    j, d = _job(db, users, tmp_path)
    v = client.get(_url(j, d), headers=auth["acme"]).json()
    pg = v["pages"][0]
    assert _cell(v, "Alpha")["word_ids"]
    assert any(r["kind"] == "table" for r in pg["regions"])
    assert all({"id", "text", "left_out"} <= set(ln) for ln in pg["lines"])
    assert v["edits"] == []


def test_ignore_a_line_is_stored_with_who_and_when_and_the_export_applies_it(
        client, db, users, auth, tmp_path):
    j, d = _job(db, users, tmp_path)
    v = client.get(_url(j, d), headers=auth["acme"]).json()
    lid = next(ln["id"] for ln in v["pages"][0]["lines"] if ln["text"] == "Stray footer words")
    r = client.post(_url(j, d, "/edits"), headers=auth["acme"],
                    json={"op": "ignore_line", "page": 1, "line_id": lid, "reason": "footer"})
    assert r.status_code == 201, r.text
    e = r.json()["edit"]
    assert e["id"] == 1 and e["by"] and e["when"] and e["op"] == "ignore_line"
    assert "Stray footer words" not in _sheet(client, j, auth).values()
    ln = next(x for x in r.json()["pages"][0]["lines"] if x["id"] == lid)
    assert ln["left_out"] and ln["reason"] == "reviewer: footer"
    # and back
    r2 = client.post(_url(j, d, "/edits"), headers=auth["acme"],
                     json={"op": "unignore_line", "page": 1, "line_id": lid})
    assert r2.status_code == 201
    assert "Stray footer words" in _sheet(client, j, auth).values()


def test_move_merge_and_split_cells(client, db, users, auth, tmp_path):
    j, d = _job(db, users, tmp_path)
    v = client.get(_url(j, d), headers=auth["acme"]).json()
    alpha = _cell(v, "Alpha")["cell"]
    r = client.post(_url(j, d, "/edits"), headers=auth["acme"],
                    json={"op": "move_cell", "page": 1, "cell": alpha, "to": "F30"})
    assert r.status_code == 201, r.text
    assert _sheet(client, j, auth)["F30"] == "Alpha"
    v = r.json()
    a, b = _cell(v, "Member Name:")["cell"], _cell(v, "Jane Roe")["cell"]
    r = client.post(_url(j, d, "/edits"), headers=auth["acme"],
                    json={"op": "merge_cells", "page": 1, "cells": [a, b]})
    assert r.status_code == 201, r.text
    assert _sheet(client, j, auth)[a] == "Member Name: Jane Roe"
    r = client.post(_url(j, d, "/edits"), headers=auth["acme"],
                    json={"op": "split_cell", "page": 1, "cell": a, "at": 2, "to": "H1"})
    assert r.status_code == 201, r.text
    s = _sheet(client, j, auth)
    assert s[a] == "Member Name:" and s["H1"] == "Jane Roe"


def test_reassign_a_column_moves_the_words_within_their_table(client, db, users, auth, tmp_path):
    j, d = _job(db, users, tmp_path)
    v = client.get(_url(j, d), headers=auth["acme"]).json()
    table = next(r for r in v["pages"][0]["regions"] if r["kind"] == "table")
    beta = _cell(v, "2.75")
    r = client.post(_url(j, d, "/edits"), headers=auth["acme"],
                    json={"op": "reassign_column", "page": 1, "region": table["id"],
                          "word_ids": beta["word_ids"], "column": 0})
    assert r.status_code == 201, r.text
    moved = _cell(r.json(), "Beta 2.75")
    assert moved["cell"][0] == "A"


def test_an_edit_that_cannot_apply_is_refused_and_not_stored(client, db, users, auth, tmp_path):
    j, d = _job(db, users, tmp_path)
    v = client.get(_url(j, d), headers=auth["acme"]).json()
    alpha, beta = _cell(v, "Alpha")["cell"], _cell(v, "Beta")["cell"]
    r = client.post(_url(j, d, "/edits"), headers=auth["acme"],
                    json={"op": "move_cell", "page": 1, "cell": alpha, "to": beta})
    assert r.status_code == 422 and "not empty" in r.json()["detail"]["errors"][0]
    r = client.post(_url(j, d, "/edits"), headers=auth["acme"],
                    json={"op": "explode", "page": 1})
    assert r.status_code == 422
    assert client.get(_url(j, d), headers=auth["acme"]).json()["edits"] == []


def test_same_words_plan_and_edits_give_the_same_layout(client, db, users, auth, tmp_path):
    j, d = _job(db, users, tmp_path)
    v = client.get(_url(j, d), headers=auth["acme"]).json()
    client.post(_url(j, d, "/edits"), headers=auth["acme"],
                json={"op": "move_cell", "page": 1, "cell": _cell(v, "Gamma")["cell"],
                      "to": "E40"})
    first = client.get(_url(j, d), headers=auth["acme"]).json()
    again = client.get(_url(j, d), headers=auth["acme"]).json()
    assert first["pages"] == again["pages"]
    assert _sheet(client, j, auth) == _sheet(client, j, auth)


def test_an_edit_is_removed_by_its_id(client, db, users, auth, tmp_path):
    j, d = _job(db, users, tmp_path)
    v = client.get(_url(j, d), headers=auth["acme"]).json()
    r = client.post(_url(j, d, "/edits"), headers=auth["acme"],
                    json={"op": "move_cell", "page": 1, "cell": _cell(v, "Gamma")["cell"],
                          "to": "E40"})
    eid = r.json()["edit"]["id"]
    r = client.delete(_url(j, d, f"/edits/{eid}"), headers=auth["acme"])
    assert r.status_code == 200 and r.json()["edits"] == []
    assert client.delete(_url(j, d, f"/edits/{eid}"), headers=auth["acme"]).status_code == 404


def test_a_stale_cell_edit_is_reported_not_guessed():
    import structure_edits as SE
    page = {"page": 1, "words": [{"id": "w1", "text": "A", "x0": 0, "x1": 5},
                                 {"id": "w2", "text": "B", "x0": 9, "x1": 14}],
            "lines": [{"id": "l1", "word_ids": ["w1", "w2"]}]}
    cells = [{"row": 0, "col": 0, "word_ids": ["w2"], "text": "B"}]
    res = SE.apply_cell_edits(cells, page, [{"id": 7, "op": "move_cell", "page": 1, "cell": "A1",
                                             "to": "C1", "word_ids": ["w1"]}], lambda *a: None)
    assert res == [{"id": 7, "op": "move_cell", "applied": False,
                    "why": "A1 no longer holds the words this edit was made on"}]
    assert cells[0]["col"] == 0
