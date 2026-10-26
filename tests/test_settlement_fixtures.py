"""Derived fixtures with truth (Part 3.4 e): records found equal truth,
values and levels as expected, and a settlement whose net reads "aaaaaa" is
flagged low by the template's declared settlement rule."""
import contextlib
import io
import json
import re
import sys
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()
sys.path.insert(0, str(bs.TESTS_DIR / "fixtures"))
import make_settlement_fixtures as F  # noqa: E402

DOCS = F.documents()


class _Resp:
    def __init__(self, obj):
        self.success, self.parsed_json, self.raw_text = True, obj, json.dumps(obj)
        self.model_used, self.tokens_used, self.error = "truth-stub", 0, ""


def truth_stub(doc):
    """Answers from the document's truth, quoting the printed line."""
    def extract(text="", image_b64="", prompt="", **kw):
        fields = {}
        for sid, label in re.findall(r'^\s+(F\d+): .*the value on the row labelled "(.*)"\s*$',
                                     prompt, re.M):
            v = doc["fields"].get(label)
            fields[sid] = ({"value": v, "source": f"{label}: {v}", "page": 1}
                           if v is not None else {"value": "", "source": "", "page": 0})
        tables = {name: [{"cells": dict(r), "page": 1,
                          "source": "   ".join(r[c] for c in doc["columns"])}
                         for r in doc["rows"]]
                  for name in re.findall(r'^TABLE "(.+?)"', prompt, re.M)}
        return _Resp({"fields": fields, "tables": tables})
    return SimpleNamespace(llm=SimpleNamespace(extract=extract))


def run(name, tmp_path):
    import extractor
    d = DOCS[name]
    path = tmp_path / f"{name}.pdf"
    path.write_bytes(F.pdf(d))
    with contextlib.redirect_stdout(io.StringIO()):
        return extractor.run_extraction(truth_stub(d), path, json.loads(json.dumps(d["template"])))


def _low(ed):
    cm = (ed.get("validation") or {}).get("confidence_map") or {}
    return {ed["slot_map"] and next((f["row_label"] for f in ed["slot_map"]["fields"]
                                     if f["ref"] == r), r) for r, lv in cm.items() if lv == "low"}


def test_the_clean_settlement_is_one_record_and_its_rule_passes(tmp_path):
    [r] = run("settlement_2p", tmp_path)
    ed = r.extracted_data
    assert set(DOCS["settlement_2p"]["fields"].values()) <= set(ed["extracted_fields"].values())
    v = ed["validation"]
    assert v["rule:settlement"] == "pass" and v["rule:batches_sum"] == "pass"
    assert not {"Gross Sales", "Processing Fees", "Chargebacks", "Net Settlement"} & _low(ed)


def test_an_aaaaaa_net_settlement_is_flagged_low_by_the_settlement_rule(tmp_path):
    [r] = run("settlement_2p_junk", tmp_path)
    ed = r.extracted_data
    assert ed["validation"]["rule:settlement"] == "fail"
    assert {"Gross Sales", "Processing Fees", "Chargebacks", "Net Settlement"} <= _low(ed)
    net = next(f["ref"] for f in ed["slot_map"]["fields"] if f["row_label"] == "Net Settlement")
    assert "rule_failed:settlement" in ed["field_provenance"][net]["review_reasons"]
    assert ed["needs_review"]


def test_the_five_page_excerpt_is_one_record_and_says_which_rows_it_did_not_bind(tmp_path):
    [r] = run("statement_5p", tmp_path)
    ed = r.extracted_data
    rows = ed.get("rows_rows") or []
    truth = DOCS["statement_5p"]["rows"]
    # One region per band (round-2 I1, DECISION-LOG §12): page 1's rows are
    # kept and grounded; the other 16 are left out OUT LOUD, one flag each.
    assert [x["Description"] for x in rows] == [t["Description"] for t in truth[:4]]
    assert all(x.get("_confidence") != "low" for x in rows)
    unbound = [f for f in ed["validation"]["flagged_fields"] if "[not bound]" in f["ref"]]
    assert len(unbound) == 16 and ed["validation"]["unbound_row_count"] == 16
    assert ed["needs_review"]
