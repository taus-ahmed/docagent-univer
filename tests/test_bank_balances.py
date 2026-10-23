"""The bank-statement balance validator.

Two checks, run only for templates whose family is bank_statement:
  summary  opening balance + total credits - total debits = closing balance
  running  each transaction row's balance = the previous balance + its credit
           - its debit (opening before the first row, closing after the last)
FAIL: every value in the failed step exactly low, review_required,
"balance_mismatch". UNREADABLE (a value that is not a plain amount): the
reason "balance_unreadable", no level moves. PASS: recorded only — never a
raised level. Missing or ambiguous fields, or a table a gate dropped rows from:
no check. Synthetic native statements; the stub model quotes the page. The
gold statement replays with every level unchanged.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import re
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

import extractor  # noqa: E402
import validators  # noqa: E402
from app.core.confidence import HIGH, LOW  # noqa: E402

GENERATOR = bs.TESTS_DIR / "fixtures" / "make_scan_variants.py"
HEAD = ["Date", "Description", "Debit", "Credit", "Balance"]
X = [72, 130, 300, 380, 470]
SUMMARY = ["Total Credits", "Total Debits", "Closing Balance"]
_SLOT = re.compile(r'^\s+(F\d+): .*labelled "(.+)"\s*$', re.M)

ROWS = [("01/02", "Customer deposit", "", "500.00", "1,500.00"),
        ("01/05", "Office rent", "300.00", "", "1,200.00"),
        ("01/09", "Service fee", "25.00", "", "1,175.00"),
        ("01/12", "Customer deposit", "", "250.00", "1,425.00")]
GOOD = [("Opening Balance", "$1,000.00"), ("Total Credits", "$750.00"),
        ("Total Debits", "$325.00"), ("Closing Balance", "$1,425.00")]


def _template(doc_type="bank_statement", top=("Statement No", "Opening Balance"),
              summary=SUMMARY):
    cells = {f"{i},0": {"value": lab} for i, lab in enumerate(top)}
    for c, h in enumerate(HEAD):
        cells[f"3,{c}"] = {"value": h}
    for i, lab in enumerate(summary):
        cells[f"{15 + i},0"] = {"value": lab}
    return {"layout": {"cells": cells, "colWidths": [120] * 26, "merges": {},
                       "repeatRows": [], "regions": []},
            "doc_type": doc_type, "mode": "layout"}


def _statement(tmp_path, summary, rows=ROWS):
    spec = importlib.util.spec_from_file_location("make_scan_variants", GENERATOR)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    s = dict(summary)
    text = [(72, 740, "Statement No STMT-0099")]
    if "Opening Balance" in s:
        text.append((72, 720, f"Opening Balance {s['Opening Balance']}"))
    text += [(x, 690, h) for x, h in zip(X, HEAD)]
    y = 670
    for row in rows:
        text += [(x, y, v) for x, v in zip(X, row) if v]
        y -= 20
    y -= 20
    for lab, val in summary:
        if lab != "Opening Balance":
            text += [(300, y, lab), (470, y, val)]
            y -= 20
    ops = gen._text_ops([(x, yy, 10, t) for x, yy, t in text], 0)
    path = tmp_path / "statement.pdf"
    path.write_bytes(gen.build_pdf([{"w_pt": 612.0, "h_pt": 792.0, "ops": ops}]))
    return path


class _Resp:
    def __init__(self, parsed):
        self.success, self.parsed_json = True, parsed
        self.raw_text = json.dumps(parsed)
        self.tokens_used, self.model_used, self.error = 0, "stub", ""


def _run(path, summary, template, rows=ROWS, repeat=()):
    def extract(**kw):
        prompt = kw.get("prompt") or ""
        text = [ln.strip() for ln in prompt.split("\n")]
        fields = {}
        for sid, label in _SLOT.findall(prompt):
            val = dict(summary).get(label) or (
                "STMT-0099" if label == "Statement No" else None)
            src = next((ln for ln in text if val and val in ln
                        and "labelled" not in ln), None)
            if val and src:
                fields[sid] = {"value": val, "source": src, "page": 1}
        out = []
        for n, row in enumerate(rows):
            src = next(ln for ln in text if ln.startswith(row[0]))
            ans = dict(zip(HEAD, row), source=src, page=1)
            out += [ans] * (2 if n in repeat else 1)
        name = next(iter(re.findall(r'TABLE "([^"]+)"', prompt)), None) or "table"
        return _Resp({"fields": fields, "tables": {name: out}})

    (r,) = extractor.run_extraction(
        SimpleNamespace(llm=SimpleNamespace(extract=extract)), path,
        copy.deepcopy(template))
    ed = r.extracted_data
    refs = {f["row_label"]: f["ref"] for f in ed["slot_map"]["fields"]}
    got = next((v for k, v in ed.items() if k.endswith("_rows") and v), [])
    return ed, refs, got


def _summary(**over):
    return [(lab, over.get(lab, val)) for lab, val in GOOD]


def _lvl(ed, ref):
    return ed["validation"]["confidence_map"][ref]


def _rows_low(rows):
    return [i for i, r in enumerate(rows) if r["_confidence"] == LOW]


def test_the_fixture_is_clean_without_the_validator(tmp_path):
    """Control: the same statement under a NON-statement family is all high
    and carries no balance evidence — so anything below is the validator's."""
    ed, refs, rows = _run(_statement(tmp_path, GOOD), GOOD, _template("other"))
    assert len(rows) == 4 and all(r["_confidence"] == HIGH for r in rows), rows
    for lab, _v in GOOD:
        assert _lvl(ed, refs[lab]) == HIGH, lab
    assert "balance_check" not in json.dumps(ed["field_provenance"])
    assert ed["needs_review"] is False


@pytest.mark.parametrize("name", ["bank_statement", "bank_statements",
                                  "account_statement"])
def test_the_family_and_its_aliases(name):
    assert validators.family_of(name) == "bank_statement"


def test_consistent_balances_pass_and_raise_nothing(tmp_path):
    ed, refs, rows = _run(_statement(tmp_path, GOOD), GOOD, _template())
    for lab, _v in GOOD:
        p = ed["field_provenance"][refs[lab]]
        assert _lvl(ed, refs[lab]) == HIGH and p["balance_check"] == "pass", (lab, p)
        assert p["review_reasons"] == []
    for lab in ("Opening Balance", "Closing Balance"):
        assert ed["field_provenance"][refs[lab]]["running_balance_check"] == "pass"
    assert all(r["_confidence"] == HIGH and r["_review_reasons"] == [] for r in rows)
    assert ed["needs_review"] is False


def test_one_wrong_digit_in_a_row_balance(tmp_path):
    rows = list(ROWS)
    rows[2] = ("01/09", "Service fee", "25.00", "", "1,176.00")   # was 1,175.00
    ed, refs, got = _run(_statement(tmp_path, GOOD, rows), GOOD, _template(), rows)
    assert _rows_low(got) == [1, 2, 3], got        # the steps into and out of it
    for i in (1, 2, 3):
        assert "balance_mismatch" in got[i]["_review_reasons"]
        assert got[i]["_review_required"] is True
    assert got[0]["_confidence"] == HIGH and got[0]["_review_reasons"] == []
    for lab, _v in GOOD:                           # the summary still adds up
        assert _lvl(ed, refs[lab]) == HIGH, lab
    assert ed["needs_review"] is True
    assert any("balance" in f["reason"] for f in ed["validation"]["flagged_fields"])


def test_one_wrong_digit_in_the_closing_balance(tmp_path):
    bad = _summary(**{"Closing Balance": "$1,452.00"})
    ed, refs, got = _run(_statement(tmp_path, bad), bad, _template())
    for lab, _v in GOOD:
        p = ed["field_provenance"][refs[lab]]
        assert _lvl(ed, refs[lab]) == LOW and p["balance_check"] == "fail", lab
        assert "balance_mismatch" in p["review_reasons"] and p["review_required"]
    assert _rows_low(got) == [3]                   # last row -> closing step
    assert ed["field_provenance"][refs["Closing Balance"]][
        "running_balance_check"] == "fail"


def test_a_missing_page_breaks_the_running_balance(tmp_path):
    """The file lacks the page printing the 01/09 fee: the summary (printed
    on page 1) still adds up, the balance chain does not."""
    rows = [ROWS[0], ROWS[1], ROWS[3]]
    ed, refs, got = _run(_statement(tmp_path, GOOD, rows), GOOD, _template(), rows)
    assert _rows_low(got) == [1, 2], got           # either side of the gap
    assert all("balance_mismatch" in got[i]["_review_reasons"] for i in (1, 2))
    for lab, _v in GOOD:
        assert _lvl(ed, refs[lab]) == HIGH, lab
    assert ed["needs_review"] is True


def test_an_unreadable_row_amount_moves_no_level(tmp_path):
    rows = list(ROWS)
    rows[2] = ("01/09", "Service fee", "25.00", "", "TBD")
    ed, refs, got = _run(_statement(tmp_path, GOOD, rows), GOOD, _template(), rows)
    assert all(r["_confidence"] == HIGH for r in got), got
    for i in (1, 2, 3):
        assert "balance_unreadable" in got[i]["_review_reasons"], got[i]
        assert got[i]["_review_required"] is True
    assert got[0]["_review_reasons"] == []
    assert ed["needs_review"] is True              # the invariant


def test_an_unreadable_summary_amount_moves_no_level(tmp_path):
    odd = _summary(**{"Total Debits": "n/a"})
    ed, refs, _ = _run(_statement(tmp_path, odd), odd, _template())
    for lab, _v in GOOD:
        p = ed["field_provenance"][refs[lab]]
        assert p["balance_check"] == "unreadable" and _lvl(ed, refs[lab]) == HIGH
        assert "balance_unreadable" in p["review_reasons"]
    assert ed["needs_review"] is True


def test_a_statement_listed_newest_first(tmp_path):
    rows = ROWS[::-1]
    ed, refs, got = _run(_statement(tmp_path, GOOD, rows), GOOD, _template(), rows)
    assert all(r["_confidence"] == HIGH for r in got)
    assert ed["field_provenance"][refs["Closing Balance"]][
        "running_balance_check"] == "pass"
    assert ed["needs_review"] is False


def test_debits_printed_negative_check_the_same(tmp_path):
    rows = [(d, t, f"-{dr}" if dr else "", cr, b) for d, t, dr, cr, b in ROWS]
    summ = _summary(**{"Total Debits": "-$325.00"})
    ed, refs, got = _run(_statement(tmp_path, summ, rows), summ, _template(), rows)
    assert all(r["_confidence"] == HIGH for r in got)
    assert ed["field_provenance"][refs["Closing Balance"]]["balance_check"] == "pass"


def test_missing_or_ambiguous_fields_run_no_summary_check(tmp_path):
    summ = [("Opening Balance", "$1,000.00"), ("Closing Balance", "$1,425.00")]
    ed, refs, _ = _run(_statement(tmp_path, summ), summ,
                       _template(summary=["Closing Balance"]))
    assert all("balance_check" not in p for p in ed["field_provenance"].values())
    # two labels claiming the closing balance: nothing runs at all
    summ2 = GOOD + [("Ending Balance", "$1,425.00")]
    ed2, _r, got2 = _run(_statement(tmp_path, summ2), summ2,
                         _template(summary=SUMMARY + ["Ending Balance"]))
    assert "balance_check" not in json.dumps(ed2["field_provenance"])
    assert all(r["_review_reasons"] == [] for r in got2)


def test_a_table_that_lost_rows_to_a_gate_is_not_chained(tmp_path):
    """A duplicate the dedup drops leaves a gap the reader is already told
    about; a balance chain across it would call correct rows wrong."""
    rows = [ROWS[0], ROWS[1], ROWS[3]]                    # 01/09 missing ...
    ed, _refs, got = _run(_statement(tmp_path, GOOD, rows), GOOD, _template(),
                          rows, repeat=(1,))              # ... and a drop
    assert ed["validation"]["dropped_row_count"] == 1
    assert "balance_mismatch" not in json.dumps(got)
    assert "running_balance_check" not in json.dumps(ed["field_provenance"])


def test_the_gold_statement_keeps_every_level(replay_cache, monkeypatch):
    """STMT-2024-01 replayed with and without the validator: identical
    levels and reasons, and both checks recorded as passing."""
    from tests.harness import runner

    (label,) = runner.load_labels({"STMT-2024-01"})
    td, _g, _ = runner.build_template_data(label, "replay")

    def run():
        (r,) = runner.run_pipeline(label, copy.deepcopy(td))[0]
        ed = r.extracted_data
        rows = ed["table_rows"]
        return ed, [(x["_confidence"], x["_review_reasons"]) for x in rows]

    ed, rows = run()
    with monkeypatch.context() as m:
        m.setitem(validators.REGISTRY, "bank_statement", [])
        ed0, rows0 = run()
    assert ed["validation"]["confidence_map"] == ed0["validation"]["confidence_map"]
    assert rows == rows0 and len(rows) == 12
    assert ed["needs_review"] == ed0["needs_review"]
    prov = ed["field_provenance"]
    checks = {(k, v) for p in prov.values() for k, v in p.items()
              if k.endswith("balance_check")}
    assert checks == {("balance_check", "pass"), ("running_balance_check", "pass")}
    refs = {f["row_label"]: f["ref"] for f in ed["slot_map"]["fields"]}
    assert prov[refs["Closing Balance"]]["running_balance_check"] == "pass"
