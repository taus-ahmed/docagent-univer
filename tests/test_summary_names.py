"""Review-3 F7: a summary cannot name anyone the data does not.

The name check looked only at RUNS of two or more capitalised words, so
"Alice approved the payment" passed with nothing about Alice in the facts and
was shown to the user. Every capitalised word, acronym and word in a caseless
script must now be in the facts, unless it is a common word starting a
sentence; anything else discards the prose for the plain facts summary.
"""
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from summary import deterministic_text, facts, verify_narrative  # noqa: E402

ED = {"document_type": "bank_statement",
      "slot_map": {"fields": [{"ref": "B1", "row_label": "Account Holder"},
                              {"ref": "B2", "row_label": "Bank"}]},
      "extracted_fields": {"B1": "Jane Q. Example", "B2": "Ficus Bank"},
      "items_rows": [{"Date": "2024-03-04", "Description": "Office rent", "Amount": "$1,250.00"},
                     {"Date": "2024-03-09", "Description": "Courier", "Amount": "$17.50"},
                     {"Date": "2024-03-15", "Description": "Stationery", "Amount": "€31.20"}]}
EMPTY = facts({})
F = facts(ED)


@pytest.mark.parametrize("prose", [
    "Alice approved the payment.",
    "The payment was approved by Alice.",
    "Alice's account paid 17.50.",
    "Alice’s account paid 17.50.",
    "Payment approved by O'Brien.",
    "Rent went to Smith-Jones.",
    "Paid to the IRS.",
    "The CFO approved it.",
    "Paid by Mr. Smith.",
    "Иван approved the payment.",
    "रवि approved the payment.",
    "Payment approved by 王伟.",
    "محمد approved the payment.",
    "Zelda reviewed this statement.",
])
def test_an_invented_name_is_rejected_with_empty_facts(prose):
    ok, problems = verify_narrative(prose, EMPTY)
    assert not ok and any("name" in p for p in problems), (prose, problems)


@pytest.mark.parametrize("prose", [
    "Alice approved the payment.",
    "Rent of 1,250.00 was approved by Alice.",
    "Courier costs went to DHL.",
    "Jane Q. Example paid Bob.",
])
def test_an_invented_name_is_rejected_beside_real_facts(prose):
    assert not verify_narrative(prose, F)[0], prose


@pytest.mark.parametrize("prose", [
    "Jane Q. Example's statement shows rent of 1,250.00 and a total of 1,267.50.",
    "Jane Q. Example’s statement shows rent of 1,250.00.",
    "The largest item was Office rent at 1,250.00.",
    "Payments run from 2024-03-04 to 2024-03-15.",
    "Ficus Bank shows three items in March.",
    "In EUR the total is 31.20.",
    "This statement has 3 rows. Most of the spending was rent.",
    "Office rent of 1,250.00 was the largest item.",
])
def test_names_and_words_from_the_facts_still_pass(prose):
    ok, problems = verify_narrative(prose, F)
    assert ok, (prose, problems)


def test_a_month_outside_the_data_is_a_name():
    assert not verify_narrative("Rent was paid in July.", F)[0]


def test_the_deterministic_text_always_verifies():
    for ed in (ED, {"extracted_fields": {"A1": "x"}}):
        f = facts(ed)
        assert verify_narrative(deterministic_text(f), f)[0], deterministic_text(f)


def test_the_check_fails_closed_when_it_cannot_run():
    ok, problems = verify_narrative("Alice", {"date_range": object()})
    assert not ok and problems


def test_the_worker_shows_the_facts_summary_instead():
    from app.services.job_worker import _post_summarize
    orch = SimpleNamespace(llm=SimpleNamespace(extract=lambda **k: SimpleNamespace(
        success=True, parsed_json={"summary": "Alice approved the payment."})))
    ed = _post_summarize({}, orch, "x", narrative=True, allow_call=lambda: True)
    s = ed["summary"]
    assert s["narrative"] is None and "discarded" in s["notice"]
    assert s["text"] == deterministic_text(facts({}))


# ── Recheck R2: spelled-out numbers and lowercase names ─────────────────────
#
# Codex: "Courier cost twelve thousand dollars." and "went to alice" both
# passed — a number written in words was never read as a number, and only a
# capital marked a name. A number word must now be grounded by the facts
# (the word itself, or its figure); an unknown word right after to / by /
# from / for / with / at / on behalf of / signed / approved / paid / issued
# is a name unless the facts hold it. Over-rejecting only costs the plainer
# facts summary.

@pytest.mark.parametrize("prose", [
    "Courier cost twelve thousand dollars.",
    "Courier is half the total.",
    "Stationery cost a dozen euros.",
    "The courier was paid twice.",
    "Rent doubled, a quarter of the spending.",
    "The rent went to alice.",
    "The rent went to bob smith and mark.",
    "The rent was approved by jsmith.",
    "Stationery was paid on behalf of acme.",
    "The courier signed kowalski.",
    "Payments were issued for globex.",
])
def test_spelled_numbers_and_lowercase_names_are_rejected(prose):
    ok, problems = verify_narrative(prose, F)
    assert not ok, (prose, problems)


@pytest.mark.parametrize("prose", ["Rent was paid three times.", "Rent was paid once a month.",
                                   "The first payment was rent.", "Rent was eleven percent."])
def test_a_number_word_whose_figure_is_not_in_the_facts_is_rejected(prose):
    ok, problems = verify_narrative(prose, EMPTY)
    assert not ok and any("number" in p for p in problems), (prose, problems)


@pytest.mark.parametrize("prose", [
    "Ficus Bank shows three items in March.",
    "The statement has three rows.",
    "Rent was paid to Ficus Bank for office rent.",
    "Payments run from 2024-03-04 to 2024-03-15.",
    "Most of the spending was paid for the rent.",
    "Jane Q. Example paid the courier 17.50.",
])
def test_grounded_number_words_and_known_names_still_pass(prose):
    ok, problems = verify_narrative(prose, F)
    assert ok, (prose, problems)
