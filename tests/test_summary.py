"""Summaries that cannot invent numbers (Part A4)."""
from __future__ import annotations

import contextlib
import io
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from summary import LABEL, deterministic_text, facts, verify_narrative  # noqa: E402

ED = {"document_type": "bank_statement",
      "slot_map": {"fields": [{"ref": "B1", "row_label": "Account Holder"}]},
      "extracted_fields": {"B1": "Jane Q. Example"},
      "items_rows": [{"Date": "2024-03-04", "Description": "Office rent", "Amount": "$1,250.00"},
                     {"Date": "2024-03-09", "Description": "Courier", "Amount": "$17.50"},
                     {"Date": "2024-03-15", "Description": "Stationery", "Amount": "€31.20"}]}


def test_facts_are_exact_and_never_mix_currencies():
    f = facts(ED)
    assert f["tables"] == {"items": 3}
    totals = {k.rsplit(":", 1)[1]: v for k, v in f["totals"].items()}
    assert totals["EUR"] == "31.20" and "1,267.50" in totals.values()
    assert f["date_range"] == ["2024-03-04", "2024-03-15"]
    assert f["top_items"][0]["item"] == "Office rent"


def test_the_deterministic_text_uses_only_facts():
    t = deterministic_text(facts(ED))
    assert "1,267.50" in t and "31.20" in t and "2024-03-04" in t
    assert verify_narrative(t, facts(ED))[0]


@pytest.mark.parametrize("prose,ok", [
    ("Jane Q. Example's statement shows rent of 1,250.00 and a total of 1,267.50.", True),
    ("Jane Q. Example paid 1,250.00 in rent and 9,999.00 to a supplier.", False),   # invented number
    ("Payments run from 2024-03-04 to 2024-03-15.", True),
    ("Payments run from 2024-03-04 to 2024-04-30.", False),                        # invented date
    ("Acme Holdings received 17.50.", False),                                      # invented name
])
def test_a_narrative_must_only_use_the_facts(prose, ok):
    assert verify_narrative(prose, facts(ED))[0] is ok


def _orch(prose):
    return SimpleNamespace(llm=SimpleNamespace(extract=lambda **k: SimpleNamespace(
        success=True, parsed_json={"summary": prose})))


def test_an_injected_fake_number_is_discarded_with_a_notice(capsys):
    from app.services.job_worker import _post_summarize
    ed = _post_summarize(dict(ED), _orch("Rent was 1,250.00 and fees 4,444.00."), "x",
                         narrative=True, allow_call=lambda: True)
    s = ed["summary"]
    assert s["narrative"] is None and "discarded" in s["notice"]
    assert s["text"] == deterministic_text(facts(ED)) and s["label"] == LABEL
    out = capsys.readouterr().out
    assert "4,444" not in out and "Rent was" not in out          # nothing of the prose logged


def test_a_good_narrative_is_kept_and_labelled():
    from app.services.job_worker import _post_summarize
    ed = _post_summarize(dict(ED), _orch("Office rent of 1,250.00 was the largest item."), "x",
                         narrative=True, allow_call=lambda: True)
    assert ed["summary"]["narrative"].startswith("Office rent") and ed["summary"]["label"] == LABEL


def test_the_cap_stops_the_call_and_says_so():
    from app.services.job_worker import _post_summarize
    called = []
    orch = SimpleNamespace(llm=SimpleNamespace(extract=lambda **k: called.append(1)))
    ed = _post_summarize(dict(ED), orch, "x", narrative=True, allow_call=lambda: False)
    assert called == [] and "limit" in ed["summary"]["notice"]


def test_without_the_narrative_option_no_model_is_called():
    from app.services.job_worker import _post_summarize
    orch = SimpleNamespace(llm=SimpleNamespace(extract=lambda **k: (_ for _ in ()).throw(AssertionError)))
    ed = _post_summarize(dict(ED), orch, "x")
    assert ed["summary"]["text"] and ed["summary"]["narrative"] is None


def test_the_model_failing_shows_the_deterministic_summary():
    from app.services.job_worker import _post_summarize

    def boom(**k):
        raise RuntimeError("503")
    ed = _post_summarize(dict(ED), SimpleNamespace(llm=SimpleNamespace(extract=boom)), "x",
                         narrative=True, allow_call=lambda: True)
    assert ed["summary"]["narrative"] is None and ed["summary"]["text"]


