"""Review-3 F5: a template whose rules cannot run is refused on EVERY save.

`rule_problems` ran only in `POST /api/templates/shape`, the editor's
preview. `POST /api/templates` and `PUT /api/templates/{id}` stored any grid
they were given, so a rule naming nothing, a catastrophic pattern or a NaN
tolerance went straight into a template every later extraction ran.

The routes that write a template's grid are create and update; the
templates page's Duplicate and "save this inferred template" both post to
create, so they are covered by it. Each is driven here with a bad rule set
(refused, 422 `template_rules_invalid`, nothing written) and a good one
(saved).
"""
import json

import pytest

GRID_CELLS = {"0,0": {"value": "Subtotal"}, "1,0": {"value": "Total"},
              "0,1": {"value": ""}, "1,1": {"value": ""}}

GOOD_RULES = [{"name": "tot", "type": "equals", "left": "Subtotal", "right": "Total"}]
BAD = {
    "names_nothing": {"rules": [{"name": "x", "type": "equals",
                                 "left": "Subtotal", "right": "Grand Total"}]},
    "catastrophic": {"rules": [{"name": "x", "type": "regex", "value": "Total",
                                "pattern": "(a+)+$"}]},
    "nan_tolerance": {"rules": [{"name": "x", "type": "equals", "left": "Subtotal",
                                 "right": "Total", "tolerance": "NaN"}]},
    "malformed": {"rules": ["junk"]},
    "not_a_list": {"rules": {"name": "x"}},
    "bad_category": {"categories": [{"category": "Travel", "regex": ["(a|aa)+"]}]},
    # Recheck R1: Codex's patterns the old subset admitted (~30 s and ~18 s)
    "slow_bounded": {"rules": [{"name": "x", "type": "regex", "value": "Total",
                                "pattern": "a{0,100}a{0,100}a{0,100}a{0,100}a{0,100}b"}]},
    "slow_category": {"categories": [{"category": "Travel",
                                      "regex": [r"\d?\d*\d*\d*x"]}]},
}


def _desc(**extra):
    return json.dumps({"cells": GRID_CELLS, "colWidths": [], "merges": {}, **extra})


def _body(name, **extra):
    return {"name": name, "document_type": "invoice", "columns": [],
            "description": _desc(**extra)}


def _refused(r):
    assert r.status_code == 422, (r.status_code, r.text)
    assert "template_rules_invalid" in r.json()["detail"]
    assert r.headers.get("X-Error-Code") == "template_rules_invalid"


@pytest.mark.parametrize("case", sorted(BAD))
def test_create_refuses_unrunnable_rules(client, auth, case):
    name = f"f5-create-{case}"
    _refused(client.post("/api/templates", headers=auth["acme"], json=_body(name, **BAD[case])))
    listed = client.get("/api/templates", headers=auth["acme"]).json()
    assert name not in {t["name"] for t in listed}


def test_create_accepts_runnable_rules(client, auth):
    r = client.post("/api/templates", headers=auth["acme"],
                    json=_body("f5-create-good", rules=GOOD_RULES,
                               categories=[{"category": "Travel", "regex": [r"^UBER\b"]}]))
    assert r.status_code == 201, r.text


@pytest.mark.parametrize("case", sorted(BAD))
def test_update_refuses_unrunnable_rules_and_keeps_the_old_grid(client, auth, case):
    r = client.post("/api/templates", headers=auth["acme"],
                    json=_body(f"f5-update-{case}", rules=GOOD_RULES))
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    _refused(client.put(f"/api/templates/{tid}", headers=auth["acme"],
                        json={"description": _desc(**BAD[case])}))
    kept = client.get(f"/api/templates/{tid}", headers=auth["acme"]).json()
    assert json.loads(kept["description"])["rules"] == GOOD_RULES


def test_update_without_a_new_grid_is_not_revalidated(client, auth):
    r = client.post("/api/templates", headers=auth["acme"],
                    json=_body("f5-rename", rules=GOOD_RULES))
    tid = r.json()["id"]
    r = client.put(f"/api/templates/{tid}", headers=auth["acme"], json={"name": "f5-renamed"})
    assert r.status_code == 200, r.text


def test_duplicate_goes_through_create(client, auth):
    """The templates page duplicates by posting the source's description to
    create: a source saved before this check with a bad rule cannot be copied
    on without the problem being named."""
    r = client.post("/api/templates", headers=auth["acme"],
                    json=_body("f5-dup (copy)", **BAD["catastrophic"]))
    _refused(r)


def test_a_legacy_prose_description_is_not_a_grid(client, auth):
    r = client.post("/api/templates", headers=auth["acme"],
                    json={"name": "f5-prose", "document_type": "invoice", "columns": [],
                          "description": "rules: anything, this is prose"})
    assert r.status_code == 201, r.text
