"""The invoice-totals validator — the registry's first NON-cheque family.

Two checks, run only for templates whose family is invoice:
  lines  the line items' amounts sum to the subtotal, within one cent per line
  total  subtotal + charges + tax - discount = total, within one cent
FAIL: every value in the failed sum exactly low, review_required,
"totals_mismatch". UNREADABLE (a value that is not a plain amount): the
reason "totals_unreadable", no level moves. PASS: recorded only — never a
raised level. A document lacking the fields, or of another family, is
untouched. Synthetic native invoices; the stub model quotes the page.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import re
from types import SimpleNamespace


from tests.harness import bootstrap as bs

bs.bootstrap()

import extractor  # noqa: E402
from app.core.confidence import HIGH, LOW  # noqa: E402

GENERATOR = bs.TESTS_DIR / "fixtures" / "make_scan_variants.py"
LABELS = ["Invoice Number", None, "Description", "Qty", "Unit Price", "Amount"]
SUMMARY = ["Subtotal", "Shipping & Handling", "Sales Tax", "Discount", "Total Due"]
_SLOT = re.compile(r'^\s+(F\d+): .*labelled "(.+)"\s*$', re.M)


def _template(doc_type="invoice", summary=SUMMARY):
    cells = {"0,0": {"value": "Invoice Number"}}
    for c, h in enumerate(["Description", "Qty", "Unit Price", "Amount"]):
        cells[f"2,{c}"] = {"value": h}
    for i, lab in enumerate(summary):
        cells[f"{8 + i},0"] = {"value": lab}
    return {"layout": {"cells": cells, "colWidths": [120] * 26, "merges": {},
                       "repeatRows": [], "regions": []},
            "doc_type": doc_type, "mode": "layout"}


LINES = [("Widget assembly", "2", "50.00", "100.00"),
         ("Gear housing", "3", "50.00", "150.00")]


def _invoice(tmp_path, summary, lines=LINES):
    spec = importlib.util.spec_from_file_location("make_scan_variants", GENERATOR)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    text = [(72, 720, "Invoice Number INV-2024-0099"),
            (72, 690, "Description"), (300, 690, "Qty"), (360, 690, "Unit Price"),
            (470, 690, "Amount")]
    y = 670
    for d, q, u, a in lines:
        text += [(72, y, d), (300, y, q), (360, y, u), (470, y, a)]
        y -= 20
    y -= 20
    for lab, val in summary:
        text += [(300, y, lab), (470, y, val)]
        y -= 20
    ops = gen._text_ops([(x, yy, 10, t) for x, yy, t in text], 0)
    path = tmp_path / "invoice.pdf"
    path.write_bytes(gen.build_pdf([{"w_pt": 612.0, "h_pt": 792.0, "ops": ops}]))
    return path


class _Resp:
    def __init__(self, parsed):
        self.success, self.parsed_json = True, parsed
        self.raw_text = json.dumps(parsed)
        self.tokens_used, self.model_used, self.error = 0, "stub", ""


def _run(path, summary, template, lines=LINES):
    def extract(**kw):
        prompt = kw.get("prompt") or ""
        text = [ln.strip() for ln in prompt.split("\n")]
        fields = {}
        for sid, label in _SLOT.findall(prompt):
            val = dict(summary).get(label) or (
                "INV-2024-0099" if label == "Invoice Number" else None)
            src = next((ln for ln in text if val and val in ln
                        and "labelled" not in ln), None)
            if val and src:
                fields[sid] = {"value": val, "source": src, "page": 1}
        rows = []
        for d, q, u, a in lines:
            src = next(ln for ln in text if ln.startswith(d))
            rows.append({"Description": d, "Qty": q, "Unit Price": u,
                         "Amount": a, "source": src, "page": 1})
        tables = {}
        for m in re.finditer(r'"([^"]+)"\s*:\s*\[', prompt):
            pass
        name = next(iter(re.findall(r'TABLE "([^"]+)"', prompt)), None) or "table"
        tables[name] = rows
        return _Resp({"fields": fields, "tables": tables})

    (r,) = extractor.run_extraction(
        SimpleNamespace(llm=SimpleNamespace(extract=extract)), path,
        copy.deepcopy(template))
    ed = r.extracted_data
    refs = {f["row_label"]: f["ref"] for f in ed["slot_map"]["fields"]}
    rows = next((v for k, v in ed.items() if k.endswith("_rows") and v), [])
    return ed, refs, rows


GOOD = [("Subtotal", "$250.00"), ("Shipping & Handling", "$15.00"),
        ("Sales Tax", "$20.00"), ("Discount", "($10.00)"), ("Total Due", "$275.00")]


def _summary(**over):
    return [(lab, over.get(lab, val)) for lab, val in GOOD]


def _lvl(ed, ref):
    return ed["validation"]["confidence_map"][ref]


def test_the_fixture_is_clean_without_the_validator(tmp_path):
    """Control: the same invoice under a NON-invoice family is all high and
    carries no totals evidence — so anything below is the validator's."""
    ed, refs, rows = _run(_invoice(tmp_path, GOOD), GOOD, _template("other"))
    assert len(rows) == 2 and all(r["_confidence"] == HIGH for r in rows), rows
    for lab, _v in GOOD:
        assert _lvl(ed, refs[lab]) == HIGH, lab
    assert "totals_check" not in json.dumps(ed["field_provenance"])
    assert ed["needs_review"] is False


def test_consistent_totals_pass_and_raise_nothing(tmp_path):
    ed, refs, rows = _run(_invoice(tmp_path, GOOD), GOOD, _template())
    for lab, _v in GOOD:
        p = ed["field_provenance"][refs[lab]]
        assert _lvl(ed, refs[lab]) == HIGH and p["totals_check"] == "pass", (lab, p)
        assert p["review_reasons"] == []
    assert ed["field_provenance"][refs["Subtotal"]]["lines_check"] == "pass"
    assert ed["needs_review"] is False


def test_lines_that_do_not_sum_to_the_subtotal(tmp_path):
    bad = _summary(Subtotal="$260.00", **{"Total Due": "$285.00"})
    ed, refs, rows = _run(_invoice(tmp_path, bad), bad, _template())
    p = ed["field_provenance"][refs["Subtotal"]]
    assert _lvl(ed, refs["Subtotal"]) == LOW and p["lines_check"] == "fail"
    assert "totals_mismatch" in p["review_reasons"] and p["review_required"] is True
    for r in rows:
        assert r["_confidence"] == LOW and "totals_mismatch" in r["_review_reasons"], r
    assert ed["needs_review"] is True


def test_a_total_that_does_not_add_up(tmp_path):
    bad = _summary(**{"Total Due": "$285.00"})
    ed, refs, rows = _run(_invoice(tmp_path, bad), bad, _template())
    for lab, _v in GOOD:
        p = ed["field_provenance"][refs[lab]]
        assert _lvl(ed, refs[lab]) == LOW, lab
        assert "totals_mismatch" in p["review_reasons"] and p["totals_check"] == "fail"
    assert all(r["_confidence"] == HIGH for r in rows)       # the lines are fine
    assert any("total" in f["reason"] for f in ed["validation"]["flagged_fields"])


def test_an_unreadable_amount_moves_no_level(tmp_path):
    odd = _summary(**{"Sales Tax": "TBD"})
    ed, refs, _rows = _run(_invoice(tmp_path, odd), odd, _template())
    for lab, _v in GOOD:
        p = ed["field_provenance"][refs[lab]]
        assert p["totals_check"] == "unreadable", (lab, p)
        assert "totals_unreadable" in p["review_reasons"] and p["review_required"] is True
    assert _lvl(ed, refs["Total Due"]) == HIGH
    assert ed["needs_review"] is True                          # the invariant


def test_rounding_within_one_cent_per_line_passes(tmp_path):
    lines = [("Bolt pack", "3", "33.333", "33.33"), ("Nut pack", "3", "33.333", "33.33"),
             ("Washer pack", "3", "33.333", "33.33")]
    summ = [("Subtotal", "$100.00"), ("Total Due", "$100.00")]
    ed, refs, rows = _run(_invoice(tmp_path, summ, lines), summ,
                          _template(summary=["Subtotal", "Total Due"]), lines)
    assert ed["field_provenance"][refs["Subtotal"]]["lines_check"] == "pass"
    assert _lvl(ed, refs["Subtotal"]) == HIGH


def test_an_invoice_without_the_fields_is_untouched(tmp_path):
    summ = [("Subtotal", "$250.00")]
    ed, refs, rows = _run(_invoice(tmp_path, summ), summ,
                          _template(summary=["Subtotal"]))
    # lines -> subtotal can run; there is no total, so no total check
    p = ed["field_provenance"][refs["Subtotal"]]
    assert "totals_check" not in p
    ed2, refs2, _ = _run(_invoice(tmp_path, []), [], _template(summary=["Notes"]))
    assert "check" not in json.dumps(ed2["field_provenance"])


def test_a_tax_label_carrying_its_rate_is_still_the_tax(tmp_path):
    """Both gold invoices print `Sales Tax (8.88%)`: the label names a rate,
    the value is the tax amount. Excluding it called a correct total wrong."""
    summ = [("Subtotal", "$250.00"), ("Sales Tax (8.00%)", "$20.00"),
            ("Total Due", "$270.00")]
    ed, refs, _ = _run(_invoice(tmp_path, summ), summ,
                       _template(summary=[lab for lab, _v in summ]))
    for lab, _v in summ:
        assert ed["field_provenance"][refs[lab]]["totals_check"] == "pass", lab
        assert _lvl(ed, refs[lab]) == HIGH


def test_an_unknown_amount_inside_the_sum_stops_the_total_check(tmp_path):
    """A line between Subtotal and Total whose role is unknown (`Bottle
    deposit`) may be part of the sum: the total check does not guess."""
    summ = [("Subtotal", "$250.00"), ("Bottle deposit", "$5.00"),
            ("Total Due", "$255.00")]
    ed, refs, _ = _run(_invoice(tmp_path, summ), summ,
                       _template(summary=[lab for lab, _v in summ]))
    assert "totals_check" not in ed["field_provenance"][refs["Total Due"]]
    assert _lvl(ed, refs["Total Due"]) == HIGH


def test_line_items_continuing_on_page_2_are_not_marked_low(tmp_path):
    """The table continues onto page 2. One region per band keeps page 1's
    rows and leaves page 2's out (flagged, `regions`), so the lines that are
    left cannot sum to the subtotal — a lines check over them would call a
    correct subtotal and correct lines wrong. A table a gate dropped rows from
    is not summed (CheckContext.incomplete); the total check still runs."""
    spec = importlib.util.spec_from_file_location("make_scan_variants", GENERATOR)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    head = [(72, 690, "Description"), (300, 690, "Qty"), (360, 690, "Unit Price"),
            (470, 690, "Amount")]
    (d1, q1, u1, a1), (d2, q2, u2, a2) = LINES
    p1 = [(72, 720, "Invoice Number INV-2024-0099"), *head,
          (72, 670, d1), (300, 670, q1), (360, 670, u1), (470, 670, a1)]
    p2 = [*head, (72, 670, d2), (300, 670, q2), (360, 670, u2), (470, 670, a2)]
    y = 630
    for lab, val in GOOD:
        p2 += [(300, y, lab), (470, y, val)]
        y -= 20
    path = tmp_path / "invoice2.pdf"
    path.write_bytes(gen.build_pdf([
        {"w_pt": 612.0, "h_pt": 792.0,
         "ops": gen._text_ops([(x, yy, 10, t) for x, yy, t in pg], 0)}
        for pg in (p1, p2)]))
    ed, refs, rows = _run(path, GOOD, _template())
    assert ed["validation"]["unbound_row_count"] == 1, ed["validation"].get("regions")
    assert len(rows) == 1 and rows[0]["_confidence"] == HIGH, rows
    assert "totals_mismatch" not in rows[0]["_review_reasons"]
    p = ed["field_provenance"][refs["Subtotal"]]
    assert "lines_check" not in p and _lvl(ed, refs["Subtotal"]) == HIGH, p
    assert p["totals_check"] == "pass"                 # the total check still runs
