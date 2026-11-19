"""Run D, D13 — the template check reaches the editor through the API."""


def test_the_shape_route_and_a_saved_template_carry_the_warnings(client, auth):
    import json
    grid = {"cells": {"0,0": {"value": "Net"}, "0,2": {"value": "=SUM(B1:B3)"}},
            "colWidths": [], "merges": {}}
    r = client.post("/api/templates/shape", headers=auth["acme"], json={"grid": grid})
    assert r.status_code == 200, r.text
    assert any("formula" in w for w in r.json()["template_warnings"])
    saved = client.post("/api/templates", headers=auth["acme"], json={
        "name": "run-d-template-check", "document_type": "invoice", "columns": [],
        "description": json.dumps(grid)})
    assert saved.status_code == 201, saved.text          # never blocked
    assert any("formula" in w for w in saved.json()["shape"]["template_warnings"])
