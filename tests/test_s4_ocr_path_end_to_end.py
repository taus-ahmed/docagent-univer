"""Run S, Stage 4a/4d — an image goes through the SAME placement and
verification engine as a text-layer PDF, and disagreements are said.

A synthetic check (tools/make_synthetic_checks.py, made-up data) is written
as an image and run through `extractor.run_extraction` with a cheque
template and a scripted model answer. The OCR reader's word boxes are the
page's words: grounding, the MICR band, the amount reconciliation and the
reading-agreement check all run on them. Needs Tesseract (skips without).
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from tests import run_q_support as Q  # noqa: E402
from tests.harness import bootstrap as bs  # noqa: E402

bs.bootstrap()

LABELS = ["Payee", "Amount in Figures", "Amount in Words", "Date", "Check Number",
          "Routing Number", "Account Number", "Memo"]


def _need_ocr():
    import ocr_source
    ok, why = ocr_source.available()
    if not ok:
        pytest.skip(f"Tesseract not installed: {why}")


def _check(tmp_path, i=0):
    import make_synthetic_checks as G
    rng = random.Random(4242 + i)
    t = G.make_truth(i, rng)
    t.update({"watermark": "none", "capture": "scan"})
    img = G.capture(G.draw_check(t, rng), t, rng)
    p = tmp_path / "check.png"
    img.save(p)
    return t, p


def _run(path, answer_of):
    tpl = Q.template(fields=LABELS, doc_type="cheque")

    def answer(prompt):
        ids = Q.slot_ids(prompt)
        return {"fields": {ids[k]: v for k, v in answer_of().items() if k in ids},
                "tables": {}}
    res = Q.run(path, tpl, answer)
    return res[0].extracted_data


def _by_label(ed):
    lab = {f["ref"]: f["row_label"] for f in ed["slot_map"]["fields"]}
    cm = ed["validation"]["confidence_map"]
    return ({lab[r]: v for r, v in ed["extracted_fields"].items()},
            {lab[r]: cm.get(r) for r in lab},
            [f for f in ed["validation"]["flagged_fields"]])


def test_a_correct_answer_is_grounded_on_the_ocr_words_and_never_high(tmp_path):
    _need_ocr()
    t, path = _check(tmp_path)
    f = t["fields"]
    ans = {"Payee": {"value": f["payee"], "source": f["payee"], "page": 1},
           "Memo": {"value": f["memo"], "source": f["memo"], "page": 1},
           "Date": {"value": f["date"], "source": f["date"], "page": 1}}
    ed = _run(path, lambda: ans)
    vals, lv, _fl = _by_label(ed)
    assert vals["Payee"] == f["payee"]
    # a machine-read page: grounded values are at most UNVERIFIED (CLAUDE.md)
    assert lv["Payee"] == "unverified" and lv["Memo"] == "unverified"


def test_a_routing_number_the_band_contradicts_is_flagged(tmp_path):
    _need_ocr()
    t, path = _check(tmp_path)
    f = t["fields"]
    wrong = f["routing"][:-1] + str((int(f["routing"][-1]) + 1) % 10)
    ans = {"Routing Number": {"value": wrong, "source": wrong, "page": 1},
           "Account Number": {"value": f["account"], "source": f["account"], "page": 1}}
    ed = _run(path, lambda: ans)
    vals, lv, flags = _by_label(ed)
    assert lv["Routing Number"] == "low"
    assert any("MICR band encodes" in fl["reason"] and f["routing"] in fl["reason"]
               for fl in flags), [fl["reason"] for fl in flags]


def test_an_amount_one_digit_off_is_named_against_the_ocr_reading(tmp_path):
    _need_ocr()
    t, path = _check(tmp_path)
    f = t["fields"]
    amt = f["amount_numeric"]
    k = max(i for i, ch in enumerate(amt) if ch.isdigit() and ch != "9")
    off = amt[:k] + str(int(amt[k]) + 1) + amt[k + 1:]
    ans = {"Amount in Figures": {"value": off, "source": f"$ {off}", "page": 1},
           "Amount in Words": {"value": f["amount_words"], "source": f["amount_words"],
                               "page": 1}}
    ed = _run(path, lambda: ans)
    _vals, lv, flags = _by_label(ed)
    reasons = " ".join(fl["reason"] for fl in flags)
    assert lv["Amount in Figures"] == "low"
    assert "OCR reading has" in reasons and amt in reasons
    # figures vs words: the engine's own reconciliation disagrees too
    # (a bare "Amount" label names neither statement, by design - vocabulary.py)
    assert any("amount in figures (" in fl["reason"] and "disagree" in fl["reason"]
               for fl in flags), reasons
    assert lv["Amount in Words"] == "low"
