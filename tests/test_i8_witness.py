# -*- coding: utf-8 -*-
"""I8 — the label-witness gate is REJECTED ON EVIDENCE, and this pins the
evidence so the rule cannot be quietly re-derived.

The rule: a filled field slot is trustworthy only if the document prints the
slot's own label near the value the model quoted. It is the obvious detector
for the class I8 named, and it is the first thing anyone re-reading that report
will reach for. DECISION-LOG §22 records why it does not survive the corpus;
these tests are the measurement itself, replayed from cache.

⚠ THIS SUITE IS ALLOWED TO FAIL when the recorded answers change. The counts
are a measurement, not a contract, and a measurement that silently follows its
subject is worthless — the same rule `known_bug` follows. If a number here
moves, re-run `python -m tests.harness.witness`, read the new failing set, and
update §22 and these numbers together.
"""
import pytest

from tests.harness import bootstrap as _bs

_bs.bootstrap()

from tests.harness import witness  # noqa: E402


@pytest.fixture(scope="module")
def measured():
    rows = witness.measure()
    return rows, witness.summarise(rows)


class TestTheGateFiresOnCorrectValues:
    def test_the_population(self, measured):
        """115 filled field slots across the ten gold documents."""
        _rows, s = measured
        assert s["slots"] == 115

    def test_two_thirds_are_witnessed(self, measured):
        _rows, s = measured
        assert s["witnessed"] == 79

    def test_a_quarter_are_not(self, measured):
        _rows, s = measured
        assert s["unwitnessed"] == 33
        assert round(100.0 * s["unwitnessed"] / s["slots"], 1) == 28.7

    def test_the_undecidable_are_counted_apart(self, measured):
        """A label with no content word to look for is not a hit and not a
        miss. Scoring a blind spot as either would flatter the measurement."""
        _rows, s = measured
        assert s["undecidable"] == 3
        assert s["witnessed"] + s["unwitnessed"] + s["undecidable"] == s["slots"]

    def test_not_one_of_them_is_defective(self, measured):
        """THE RESULT. Every value the gate would demote is one the accuracy
        harness scores as correct or near — 28 and 5. Not one is wrong,
        missed or hallucinated."""
        _rows, s = measured
        assert s["unwitnessed_correct"] == 28
        assert s["unwitnessed_near"] == 5
        assert s["unwitnessed_defective"] == 0

    def test_the_true_positive_rate_is_UNMEASURABLE_here(self, measured):
        """Not 'zero' — unmeasurable. The gold corpus contains no defective
        field slot at all, so this corpus can price the gate's false positives
        and cannot price its true ones. Stated out loud because '0 true
        positives' would read as evidence the gate catches nothing, which is a
        stronger claim than these ten documents can support."""
        _rows, s = measured
        assert s["defective_total"] == 0


class TestTheMissesAreSystematic:
    """They are not noise to be tuned away. Each is CLAUDE.md's naming rules
    1-3 seen from the other side: the document's own word for a field is
    routinely not the field's name."""

    @pytest.mark.parametrize("doc,label,printed", [
        # a synonym
        ("CHQ-001847", "Cheque Number", "No:"),
        ("INV-2024-0031", "Payment Terms", "Terms:"),
        # an abbreviation of the compound label
        ("PAYSLIP-EMP-0007-APR2024", "Total Earnings", "Total"),
        # a block heading set ABOVE the value, not beside it
        ("INV-2024-0047", "Bill To Company", None),
        # no printed label at all — naming rule 2
        ("CHQ-001847", "Drawer Name", None),
        ("CHQ-001847", "Payee", None),
    ])
    def test_a_named_miss(self, measured, doc, label, printed):
        rows, _s = measured
        hit = [r for r in rows if r["doc"] == doc and r["label"] == label]
        assert hit, f"{doc}/{label} is no longer in the measured population"
        assert hit[0]["witness"] is False
        assert hit[0]["outcome"] in ("correct", "near")
        if printed:
            assert printed.lower() in hit[0]["source"].lower()

    def test_the_cheque_is_the_worst_case(self, measured):
        """Six of the cheque's field slots fail the gate and all six are
        correct. A cheque labels almost nothing it prints."""
        rows, _s = measured
        bad = [r for r in rows if r["doc"] == "CHQ-001847"
               and r["witness"] is False]
        assert len(bad) == 6
        assert all(r["outcome"] in ("correct", "near") for r in bad)


class TestTheHelperIsHonest:
    def test_an_absent_label_is_undecidable_not_a_miss(self):
        assert witness.witnessed("", "anything", ["anything"])[0] is None
        assert witness.witnessed("Total", "x", ["x"])[0] is None  # all stopwords

    def test_an_absent_quote_is_undecidable_not_a_miss(self):
        assert witness.witnessed("Invoice Number", "", ["Invoice Number 7"])[0] is None

    def test_a_label_printed_beside_its_value_is_witnessed(self):
        assert witness.witnessed("Invoice Number", "Invoice Number: INV-7",
                                 ["Invoice Number: INV-7"])[0] is True

    def test_a_label_printed_above_its_value_is_witnessed(self):
        assert witness.witnessed("Invoice Number", "INV-7",
                                 ["Invoice Number", "INV-7"])[0] is True

    def test_a_value_under_a_different_label_is_not(self):
        assert witness.witnessed("Invoice Number", "PO-2024-0018",
                                 ["PO Reference", "PO-2024-0018"])[0] is False
