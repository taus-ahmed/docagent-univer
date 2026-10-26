"""The per-family segmenter interface (segmenters.py).

The cheque's MICR logic moved behind it with no behaviour change — the
existing boundary, multi-cheque and OCR tests are the proof. These pin the
interface: what is registered where, and that a family with no segmenter of
its own gets exactly what runs today.
"""
from tests.harness import bootstrap as bs

bs.bootstrap()

import segmenters  # noqa: E402
from cheque_segmenter import ChequeSegmenter  # noqa: E402
from doc_boundaries import find_starts  # noqa: E402


def test_the_cheque_segmenter_runs_for_cheques_and_unknown_families_only():
    """Run 15 item 9: a KNOWN non-cheque family never runs it (a reference
    line shaped like a MICR band is not a cheque)."""
    for fam in (None, "", "other", "unknown", "cheque", "check"):
        names = [s.name for s in segmenters.for_family(fam)]
        assert names == ["cheque"], fam
    for fam in ("invoice", "bank_statement", "payslip", "receipt"):
        assert [s.name for s in segmenters.for_family(fam)] == [], fam


def test_a_family_segmenter_runs_only_for_its_family(monkeypatch):
    class Stub(segmenters.Segmenter):
        name = "stub"
    monkeypatch.setattr(segmenters, "REGISTRY",
                        {segmenters.ANY: list(segmenters.for_family()), "ledger": [Stub()]})
    assert [s.name for s in segmenters.for_family("ledger")] == ["stub"]
    assert [s.name for s in segmenters.for_family("invoice")] == []
    assert [s.name for s in segmenters.for_family(None)] == ["cheque"]


def test_the_base_segmenter_sees_nothing():
    s = segmenters.Segmenter()
    assert s.page_marks("anything") == [] and s.starts_new([1], [2]) is False
    assert s.cut_page([]) == (None, "") and s.multiple_in_record(["x"]) is None


def test_the_split_reason_comes_from_the_segmenter():
    a = "PAY TO THE ORDER OF A\n⑆021000021⑆ 7743882201⑈ 001847"
    b = "PAY TO THE ORDER OF B\n⑆026009593⑆ 1234567890⑈ 000512"
    starts, why = find_starts([a, b])
    assert starts == [0, 1]
    assert why.startswith(ChequeSegmenter.start_reason)
