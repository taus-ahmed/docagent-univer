"""Possible duplicates in one batch: the same cheque scanned twice.

A pure function over the records of one result set. Two records are the same
cheque when routing + account + serial agree, and the amount and the date
agree too wherever both records have them. Both records are FLAGGED —
`possible_duplicate` on their identity values, review required, the document
needs review — and nothing is merged, dropped, or moved in level.
"""
import copy

from tests.harness import bootstrap as bs

bs.bootstrap()

from duplicates import POSSIBLE_DUPLICATE, flag_possible_duplicates, identity  # noqa: E402

LABELS = [("B2", "Cheque Number"), ("B3", "Date"), ("B4", "Payee"),
          ("B5", "Amount in Figures"), ("B6", "Routing Number"),
          ("B7", "Account Number")]


def cheque(serial="001847", date="07/08/2026", amount="$267.25",
           routing="021000021", account="7743882201", payee="John A. Smith",
           level="unverified"):
    vals = {"B2": serial, "B3": date, "B4": payee, "B5": amount, "B6": routing,
            "B7": account}
    return {
        "extracted_fields": dict(vals),
        "slot_map": {"fields": [{"ref": r, "row_label": l} for r, l in LABELS]},
        "field_provenance": {r: {"review_required": False, "review_reasons": [],
                                 "page": 1} for r in vals},
        "validation": {"confidence_map": {r: level for r in vals},
                       "flagged_fields": [], "flagged_count": 0},
        "needs_review": False,
    }


def _reasons(ed, ref):
    return ed["field_provenance"][ref]["review_reasons"]


def test_identity_reads_the_labels():
    i = identity(cheque())
    assert (i["routing"], i["account"], i["serial"]) == ("021000021", "7743882201", "1847")


def test_the_same_cheque_scanned_twice_is_flagged_on_both():
    recs = [cheque(), cheque(serial="1847", amount="267.25")]
    levels = [copy.deepcopy(r["validation"]["confidence_map"]) for r in recs]
    hit = flag_possible_duplicates(recs, names=["a.pdf", "b.pdf"])
    assert hit == [0, 1]
    for k, r in enumerate(recs):
        for ref in ("B2", "B5", "B6", "B7", "B3"):
            assert POSSIBLE_DUPLICATE in _reasons(r, ref)
            assert r["field_provenance"][ref]["review_required"] is True
        assert POSSIBLE_DUPLICATE not in _reasons(r, "B4")      # payee is not identity
        assert r["needs_review"] is True
        assert r["validation"]["confidence_map"] == levels[k]   # no level moves
        other = "b.pdf" if k == 0 else "a.pdf"
        assert r["validation"]["possible_duplicate"]["of"] == [other]
        assert r["validation"]["flagged_count"] == len(r["validation"]["flagged_fields"]) == 1
    assert len(recs) == 2                                        # nothing dropped


def test_two_different_cheques_from_one_account_are_not_flagged():
    recs = [cheque(serial="001847"), cheque(serial="001848", amount="$90.00")]
    assert flag_possible_duplicates(recs) == []
    assert all(r["needs_review"] is False for r in recs)


def test_same_serial_but_a_different_amount_is_not_the_same_cheque():
    recs = [cheque(), cheque(amount="$1,267.25")]
    assert flag_possible_duplicates(recs) == []


def test_same_serial_but_a_different_date_is_not_the_same_cheque():
    recs = [cheque(), cheque(date="07/09/2026")]
    assert flag_possible_duplicates(recs) == []


def test_a_missing_amount_or_date_does_not_prevent_the_match():
    a, b = cheque(), cheque(amount="", date="")
    assert flag_possible_duplicates([a, b]) == [0, 1]


def test_without_full_identity_nothing_is_compared():
    recs = [cheque(routing=""), cheque(routing="")]
    assert flag_possible_duplicates(recs) == []


def test_three_copies_all_name_each_other():
    recs = [cheque(), cheque(), cheque()]
    assert flag_possible_duplicates(recs, names=["a", "b", "c"]) == [0, 1, 2]
    assert recs[1]["validation"]["possible_duplicate"]["of"] == ["a", "c"]


def test_running_twice_adds_nothing():
    recs = [cheque(), cheque()]
    flag_possible_duplicates(recs)
    flag_possible_duplicates(recs)
    assert _reasons(recs[0], "B2").count(POSSIBLE_DUPLICATE) == 1
    assert len(recs[0]["validation"]["flagged_fields"]) == 1


def test_hostile_records_do_not_raise():
    junk = [None, {}, {"extracted_fields": None}, {"slot_map": {"fields": [None]}},
            "x", cheque(serial="٠٠١٨٤٧"), cheque(account="9" * 400)]
    assert flag_possible_duplicates(junk) == []
