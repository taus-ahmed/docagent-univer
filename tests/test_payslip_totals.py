"""The payslip validator.

Two checks, run only for templates whose family is payslip:
  net         gross pay - total deductions = net pay, within one cent
  deductions  the listed deductions sum to the total deductions, within one
              cent per line, when both are present
FAIL: every value in the failed sum exactly low, review_required,
"payslip_mismatch". UNREADABLE: the reason "payslip_unreadable", no level
moves. PASS: recorded only. Missing, qualified or ambiguous fields, or a table
a gate dropped rows from: no check. Synthetic native payslips; the stub model
quotes the page. Both gold payslips replay with every level unchanged.
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
_SLOT = re.compile(r'^\s+(F\d+): .*labelled "(.+)"\s*$', re.M)
SUMMARY = ["Total Deductions", "Net Pay"]

LINES = [("Federal Income Tax", "600.00"), ("Social Security", "310.00"),
         ("Medicare", "72.50"), ("Health Insurance", "150.00")]
GOOD = [("Total Earnings", "$5,000.00"), ("Total Deductions", "$1,132.50"),
        ("Net Pay", "$3,867.50")]


def _template(doc_type="payslip", top=("Employee Name", "Total Earnings"),
              summary=SUMMARY):
    cells = {f"{i},0": {"value": lab} for i, lab in enumerate(top)}
    cells["3,0"] = {"value": "Deductions"}
    cells["4,0"] = {"value": "Description"}
    cells["4,1"] = {"value": "Amount"}
    for i, lab in enumerate(summary):
        cells[f"{14 + i},0"] = {"value": lab}
    return {"layout": {"cells": cells, "colWidths": [120] * 26, "merges": {},
                       "repeatRows": [], "regions": []},
            "doc_type": doc_type, "mode": "layout"}


def _payslip(tmp_path, summary, lines=LINES):
    spec = importlib.util.spec_from_file_location("make_scan_variants", GENERATOR)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    s = dict(summary)
    text = [(72, 740, "Employee Name Jane Example")]
    tops = [lab for lab in s if lab not in SUMMARY and not lab.startswith("Total D")]
    y = 720
    for lab in tops:
        text.append((72, y, f"{lab} {s[lab]}"))
        y -= 20
    text += [(72, 680, "Deductions"), (72, 660, "Description"), (300, 660, "Amount")]
    y = 640
    for d, a in lines:
        text += [(72, y, d), (300, y, a)]
        y -= 20
    y -= 20
    for lab, val in summary:
        if lab not in tops:
            text += [(72, y, lab), (300, y, val)]
            y -= 20
    ops = gen._text_ops([(x, yy, 10, t) for x, yy, t in text], 0)
    path = tmp_path / "payslip.pdf"
    path.write_bytes(gen.build_pdf([{"w_pt": 612.0, "h_pt": 792.0, "ops": ops}]))
    return path


class _Resp:
    def __init__(self, parsed):
        self.success, self.parsed_json = True, parsed
        self.raw_text = json.dumps(parsed)
        self.tokens_used, self.model_used, self.error = 0, "stub", ""


def _run(path, summary, template, lines=LINES, repeat=()):
    def extract(**kw):
        prompt = kw.get("prompt") or ""
        text = [ln.strip() for ln in prompt.split("\n")]
        fields = {}
        for sid, label in _SLOT.findall(prompt):
            val = dict(summary).get(label) or (
                "Jane Example" if label == "Employee Name" else None)
            src = next((ln for ln in text if val and ln.endswith(val)
                        and ln.startswith(label)), None)
            if val and src:
                fields[sid] = {"value": val, "source": src, "page": 1}
        out = []
        for n, (d, a) in enumerate(lines):
            src = next(ln for ln in text if ln.startswith(d))
            out += [{"Description": d, "Amount": a, "source": src, "page": 1}] * (
                2 if n in repeat else 1)
        name = next(iter(re.findall(r'TABLE "([^"]+)"', prompt)), None) or "Deductions"
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


def _checks(ed):
    return {(r, k): v for r, p in ed["field_provenance"].items()
            for k, v in p.items() if k.endswith("_check")}


def test_the_fixture_is_clean_without_the_validator(tmp_path):
    ed, refs, rows = _run(_payslip(tmp_path, GOOD), GOOD, _template("other"))
    assert len(rows) == 4 and all(r["_confidence"] == HIGH for r in rows), rows
    for lab, _v in GOOD:
        assert _lvl(ed, refs[lab]) == HIGH, lab
    assert _checks(ed) == {} and ed["needs_review"] is False


@pytest.mark.parametrize("name", ["payslip", "pay_slip", "payslips", "pay_stub",
                                  "paystub", "pay_stubs", "salary_slip"])
def test_the_family_and_its_aliases(name):
    assert validators.family_of(name) == "payslip"


def test_consistent_pay_passes_and_raises_nothing(tmp_path):
    ed, refs, rows = _run(_payslip(tmp_path, GOOD), GOOD, _template())
    for lab, _v in GOOD:
        p = ed["field_provenance"][refs[lab]]
        assert _lvl(ed, refs[lab]) == HIGH and p["net_pay_check"] == "pass", lab
        assert p["review_reasons"] == []
    assert ed["field_provenance"][refs["Total Deductions"]]["deductions_check"] == "pass"
    assert all(r["_confidence"] == HIGH and r["_review_reasons"] == [] for r in rows)
    assert ed["needs_review"] is False


def test_one_wrong_digit_in_net_pay(tmp_path):
    bad = _summary(**{"Net Pay": "$3,876.50"})
    ed, refs, rows = _run(_payslip(tmp_path, bad), bad, _template())
    for lab, _v in GOOD:
        p = ed["field_provenance"][refs[lab]]
        assert _lvl(ed, refs[lab]) == LOW and p["net_pay_check"] == "fail", lab
        assert "payslip_mismatch" in p["review_reasons"] and p["review_required"]
    assert all(r["_confidence"] == HIGH for r in rows)        # the lines add up
    assert ed["needs_review"] is True
    assert any("net pay" in f["reason"] for f in ed["validation"]["flagged_fields"])


def test_one_wrong_digit_in_a_deduction(tmp_path):
    lines = list(LINES)
    lines[2] = ("Medicare", "75.20")                         # was 72.50
    ed, refs, rows = _run(_payslip(tmp_path, GOOD, lines), GOOD, _template(), lines)
    p = ed["field_provenance"][refs["Total Deductions"]]
    assert p["deductions_check"] == "fail" and _lvl(ed, refs["Total Deductions"]) == LOW
    assert all(r["_confidence"] == LOW and "payslip_mismatch" in r["_review_reasons"]
               for r in rows), rows
    for lab in ("Total Earnings", "Net Pay"):                 # net still adds up
        assert _lvl(ed, refs[lab]) == HIGH, lab
    assert ed["needs_review"] is True


def test_a_missing_page_leaves_the_deductions_short(tmp_path):
    """The file lacks the page printing the Health Insurance line."""
    lines = LINES[:3]
    ed, refs, rows = _run(_payslip(tmp_path, GOOD, lines), GOOD, _template(), lines)
    assert ed["field_provenance"][refs["Total Deductions"]]["deductions_check"] == "fail"
    assert all(r["_confidence"] == LOW for r in rows)
    assert _lvl(ed, refs["Net Pay"]) == HIGH


def test_an_unreadable_amount_moves_no_level(tmp_path):
    odd = _summary(**{"Net Pay": "see attached"})
    ed, refs, rows = _run(_payslip(tmp_path, odd), odd, _template())
    for lab, _v in GOOD:
        p = ed["field_provenance"][refs[lab]]
        assert p["net_pay_check"] == "unreadable" and _lvl(ed, refs[lab]) == HIGH
        assert "payslip_unreadable" in p["review_reasons"] and p["review_required"]
    assert ed["needs_review"] is True                          # the invariant


def test_an_unreadable_deduction_moves_no_level(tmp_path):
    lines = list(LINES)
    lines[1] = ("Social Security", "TBD")
    ed, refs, rows = _run(_payslip(tmp_path, GOOD, lines), GOOD, _template(), lines)
    assert ed["field_provenance"][refs["Total Deductions"]][
        "deductions_check"] == "unreadable"
    assert all(r["_confidence"] == HIGH and "payslip_unreadable" in r["_review_reasons"]
               for r in rows), rows
    assert _lvl(ed, refs["Total Deductions"]) == HIGH


def test_deductions_in_parentheses_and_the_tables_own_total_line(tmp_path):
    """The gold payslips print deductions as `($3,240.00)`, and one of them
    returns the table's `Total` line as a row: neither is a mismatch."""
    lines = [(d, f"({a})") for d, a in LINES] + [("Deductions total", "(1,132.50)")]
    summ = _summary(**{"Total Deductions": "($1,132.50)"})
    ed, refs, rows = _run(_payslip(tmp_path, summ, lines), summ, _template(), lines)
    p = ed["field_provenance"][refs["Total Deductions"]]
    assert p["deductions_check"] == "pass" and p["net_pay_check"] == "pass"
    assert all(r["_confidence"] == HIGH for r in rows)


def test_missing_qualified_or_ambiguous_fields_run_no_check(tmp_path):
    summ = [("Total Earnings", "$5,000.00"), ("Total Deductions", "$1,132.50")]
    ed, refs, _ = _run(_payslip(tmp_path, summ), summ,
                       _template(summary=["Total Deductions"]))
    assert ("net_pay_check" not in json.dumps(ed["field_provenance"])
            and ed["field_provenance"][refs["Total Deductions"]][
                "deductions_check"] == "pass")
    # YTD gross is not this period's gross, and a pre-tax subtotal is not the
    # total deductions
    summ2 = [("YTD Gross Earnings", "$20,000.00"),
             ("Total Pre-Tax Deductions", "$150.00"), ("Net Pay", "$3,867.50")]
    ed2, _r, _ = _run(_payslip(tmp_path, summ2), summ2, _template(
        top=("Employee Name", "YTD Gross Earnings"),
        summary=["Total Pre-Tax Deductions", "Net Pay"]))
    assert _checks(ed2) == {}
    # two labels claiming gross pay: nothing runs
    summ3 = [("Gross Pay", "$5,000.00")] + GOOD
    ed3, _r, rows3 = _run(_payslip(tmp_path, summ3), summ3, _template(
        top=("Employee Name", "Gross Pay", "Total Earnings")))
    assert _checks(ed3) == {} and all(r["_review_reasons"] == [] for r in rows3)


def test_a_table_that_lost_rows_to_a_gate_is_not_summed(tmp_path):
    lines = LINES[:3]
    ed, refs, rows = _run(_payslip(tmp_path, GOOD, lines), GOOD, _template(),
                          lines, repeat=(0,))
    assert ed["validation"]["dropped_row_count"] == 1
    assert "deductions_check" not in ed["field_provenance"][refs["Total Deductions"]]
    assert all(r["_confidence"] == HIGH for r in rows)
    assert ed["field_provenance"][refs["Net Pay"]]["net_pay_check"] == "pass"


@pytest.mark.parametrize("doc_id,deductions", [
    ("PAYSLIP-EMP-0007-APR2024", None),     # a deduction lost to the region rule
    ("PAYSLIP-EMP-0012-APR2024", "pass"),   # its Total line comes back as a row
])
def test_the_gold_payslips_keep_every_level(doc_id, deductions, replay_cache,
                                            monkeypatch):
    from tests.harness import runner

    (label,) = runner.load_labels({doc_id})
    td, _g, _ = runner.build_template_data(label, "replay")

    def run():
        (r,) = runner.run_pipeline(label, copy.deepcopy(td))[0]
        ed = r.extracted_data
        rows = [(x["_confidence"], x["_review_reasons"])
                for k, v in ed.items() if k.endswith("_rows") and isinstance(v, list)
                for x in v if isinstance(x, dict)]
        return ed, rows

    ed, rows = run()
    with monkeypatch.context() as m:
        m.setitem(validators.REGISTRY, "payslip", [])
        ed0, rows0 = run()
    assert ed["validation"]["confidence_map"] == ed0["validation"]["confidence_map"]
    assert rows == rows0 and rows
    assert ed["needs_review"] == ed0["needs_review"]
    refs = {f["row_label"]: f["ref"] for f in ed["slot_map"]["fields"]}
    prov = ed["field_provenance"]
    for lab in ("Total Earnings", "Total Deductions", "Net Pay"):
        assert prov[refs[lab]]["net_pay_check"] == "pass", lab
    assert prov[refs["Total Deductions"]].get("deductions_check") == deductions
