"""Run S, Stage 1e — job 138: 686 of 1,046 values marked, ranked by reason.

The export (local_docs/batch4/job_138_results.xlsx, the owner's download)
carries ONE reason on all 686 marked cells: "Low: Not found on the page as
quoted". The pattern: the first row of every vendor group is clean, every
LATER row of the group is red in every cell. The model answered the group
column (`Vendor`) with the vendor's name. That name is printed on the group
line above the rows, not on a row's own line, so it failed grounding against
the row's record, and one failed cell marks the whole row. The first row of
each group passed only because the model quoted the GROUP LINE as its source,
whose record span reaches down to the row.

The rule, general: a value in a group column is checked against the group
line its row sits under. Every other column is still checked against the
row's own record. The false reason is gone; a wrong vendor still fails.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import run_q_support as Q

ROOT = Path(__file__).resolve().parent.parent
EXPORT_138 = ROOT / "local_docs" / "batch4" / "job_138_results.xlsx"

TEXTS = ["City Utility Board", "VENDOR INVOICE LIST",
         "INVOICE INV DATE CHECK # NET PAID STS",
         "300055 ANDERSON DULANEY",
         "0025 06/22/2026 20218284 75.00 75.00 PD",
         "299694 B&B LAWN/LANDSCAPING",
         "2937 06/16/2026 917846 2,480.00 2,480.00 PD",
         "2938 06/17/2026 917846 2,400.00 2,400.00 PD",
         "4,880.00",
         "20320 BAGBY ELECTRIC",
         "012523 05/28/2026 917847 100.00 100.00 PD",
         "013179 05/28/2026 917847 50.00 50.00 PD",
         "150.00",
         "5 INVOICES 5,105.00"]
GROUP_OF = {"0025": ("300055 ANDERSON DULANEY", "ANDERSON DULANEY"),
            "2937": ("299694 B&B LAWN/LANDSCAPING", "B&B LAWN/LANDSCAPING"),
            "2938": ("299694 B&B LAWN/LANDSCAPING", "B&B LAWN/LANDSCAPING"),
            "012523": ("20320 BAGBY ELECTRIC", "BAGBY ELECTRIC"),
            "013179": ("20320 BAGBY ELECTRIC", "BAGBY ELECTRIC")}


def _run(pdf, inferred, rows_of):
    from tests.harness import bootstrap as bs
    bs.bootstrap()
    import extractor
    calls = []

    def extract(prompt="", system_instruction="", **kw):
        calls.append(prompt)
        if (system_instruction or "").startswith("You are a document analyst"):
            return Q._Resp(copy.deepcopy(inferred))
        if len(calls) <= 2:
            return Q._Resp(rows_of(prompt))
        r = Q._Resp(None, "")
        r.error = "scripted: no further answer"
        return r

    return extractor.run_extraction(SimpleNamespace(llm=SimpleNamespace(extract=extract)),
                                    pdf, None)[0].extracted_data


def _answer_138_shape(name_key):
    """The shape job 138's answer had: the group column holds the NAME, the
    group's first row quotes the group line, later rows quote their own."""
    def rows_of(_prompt):
        rows, seen = [], set()
        for t in TEXTS:
            k = t.split()
            if k[0] not in GROUP_OF or len(k) < 5:
                continue
            line, name = GROUP_OF[k[0]]
            src = line if line not in seen else t
            seen.add(line)
            rows.append({name_key: name, "INVOICE": k[0], "INV DATE": k[1],
                         "NET": k[3], "source": src, "page": 1})
        return {"fields": {}, "tables": {"Invoices": rows}}
    return rows_of


INFERRED = {"document_type": "invoice", "title": "Vendor invoice list", "fields": [],
            "totals": [], "tables": [{"name": "Invoices", "row_count": 5,
                                      "columns": ["INVOICE", "INV DATE", "NET"]}]}


def test_later_rows_of_a_group_are_not_low_for_the_group_name(tmp_path):
    pdf = Q.make_pdf(tmp_path / "v.pdf", [[(56, 760 - 16 * i, t)
                                          for i, t in enumerate(TEXTS)]], size=9)
    ed = _run(pdf, INFERRED, _answer_138_shape("Vendor Name"))
    rows = ed["Invoices_rows"]
    assert len(rows) == 5
    assert [r["_confidence"] for r in rows] == ["grounded"] * 5, [
        (r.get("INVOICE"), r.get("_ungrounded")) for r in rows]
    assert [r["Vendor ID"] for r in rows] == ["300055", "299694", "299694", "20320", "20320"]


def test_a_group_value_the_group_line_does_not_print_still_fails(tmp_path):
    pdf = Q.make_pdf(tmp_path / "v.pdf", [[(56, 760 - 16 * i, t)
                                          for i, t in enumerate(TEXTS)]], size=9)
    base = _answer_138_shape("Vendor Name")

    def wrong(prompt):
        a = base(prompt)
        a["tables"]["Invoices"][2]["Vendor Name"] = "ZETA CORP"   # 2938's group is B&B
        return a
    ed = _run(pdf, INFERRED, wrong)
    flags = [f["reason"] for f in ed["validation"]["flagged_fields"]]
    assert any("ZETA CORP" in r for r in flags)


# ── the real export: job 138 reconstructed ─────────────────────────────────

def _need_138():
    if not EXPORT_138.exists():
        pytest.skip("local_docs/batch4/job_138_results.xlsx not present (owner's export, "
                    "git-ignored)")
    raw = Q.answer(131, "mobile_vendor_list_8pg.pdf")
    if not raw:
        pytest.skip("no stored answer for job 131 (the same file) in local_docs/raw")
    return Q.need_source("mobile_vendor_list_8pg.pdf"), json.loads(raw)


def _export_138():
    """{invoice: (vendor name, quote)} for every row of job 138's export."""
    import openpyxl
    ws = openpyxl.load_workbook(EXPORT_138).worksheets[0]
    out, red = {}, 0
    head = None
    for row in ws.iter_rows():
        vals = [c.value for c in row]
        if vals[:2] == ["Vendor", "INVOICE"]:
            head = vals
            continue
        if head is None or not vals[1]:
            continue
        for c in row:
            if c.fill and c.fill.fill_type and c.fill.fgColor.rgb == "FFFFC7CE":
                red += 1
        cm = row[1].comment.text if row[1].comment else ""
        quote = next((ln.strip("“”") for ln in cm.splitlines() if ln.startswith("“")), "")
        out[str(vals[1])] = (str(vals[0]), quote)
    return out, red


def test_job_138_reconstructed_no_row_is_low_for_its_vendor_name():
    """131's stored rows (the same file) answered in 138's shape: the vendor
    NAME in the group column, each row quoting what 138's export says it
    quoted. Before: every later row of a group was Low (686 cells in 138's
    own export). After: none is, and every row carries its vendor number."""
    src, ans = _need_138()
    rows_138, red_before = _export_138()
    assert red_before == 686
    rows = ans["tables"]["Invoice List"]
    hit = 0
    for r in rows:
        inv = r["cells"]["INVOICE"]
        if inv in rows_138:
            name, quote = rows_138[inv]
            r["cells"]["Vendor Name"] = name
            if quote:
                r["source"] = quote
            hit += 1
    assert hit >= 85
    doc = json.loads((ROOT / "local_docs" / "raw" / "131" / "docs" / "153.json")
                     .read_text(encoding="utf-8"))
    inferred = doc["extraction_json"]["inferred_template"]
    ed = _run(src, inferred, lambda _p: copy.deepcopy(ans))
    out = ed["Invoice List_rows"]
    assert len(out) == 90
    low = [r.get("INVOICE") for r in out if r.get("_confidence") == "low"]
    assert low == [], low
    assert all(r["Vendor ID"] and r["Vendor Name"] for r in out)
    assert len({r["Vendor ID"] for r in out}) == 31
