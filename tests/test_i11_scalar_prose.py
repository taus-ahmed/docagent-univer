"""
I11 — a scalar-implying field holding a scalar WRAPPED IN PROSE is demoted and
flagged (docs/DocAgent_round2_report.md run 9, DECISION-LOG §20).

Round 2 answered `Contract End Date` with `the last day of October 2020` — a
sentence fragment, and wrong besides: the bill says the agreement expires on the
meter read date FOLLOWING that day.

⚠ READ THIS BEFORE BELIEVING THE HEADLINE. Run through the real pipeline on the
real `SampleBill.pdf`, that recorded answer was ALREADY demoted and flagged
before this rule existed — by D9's word-run gate (`matches_loosely`), because
the value straddles a line break and no run of words on the page spells it.
`confidence_for` is never reached for it. So on the one instance the corpus
holds, THIS RULE ADDS NOTHING, and the first version of this file claimed a
delta that did not exist: it had measured `verify_span` and `confidence_for` in
isolation, where the value does come back `high` and unflagged, and mistook that
for the end-to-end result.

WHY THE RULE IS STILL HERE. D9's gate keys on word ADJACENCY, which is a
property of the page's layout and not of the answer. A prose fragment printed on
ONE line matches loosely, grounds, and reaches `high` — and page 3 of this very
bill prints such a line:

    Charges for Billing Period for Aug 12, 2020 to Sep 11, 2020

`TestAContiguousProseAnswerReachesTheNewRule` is the demonstrated delta: the
same pipeline, the same document, a value that passes every pre-existing gate,
`high` and unflagged before, `low` and flagged after. It is a constructed answer
rather than a recorded one, and that is stated rather than dressed up — no
recorded answer in the repo contains a contiguous prose fragment in a scalar
slot.

THE EVIDENCE THAT IS RECORDED IS THE MODEL'S OWN WORDS. The pre-I1 answer in
`tests/fixtures/round2_raw/run9_engie_BR4_prefix_fe3385d.json`, captured live at
`fe3385d`, is replayed field-for-field into the real pipeline through the same
`orchestrator_llm` stub seam the other round-2 ENGIE tests use. The live BR4 run
made after I1 returns empty for that field — the model declining, not a check:
the bill is no longer split, the contract sentence is still on page 3 and still
in the prompt.
"""
import json

import pytest

from tests.harness import bootstrap as _bs

_bs.bootstrap()

from tests.harness import round2  # noqa: E402

RECORDING = "run9_engie_BR4_prefix_fe3385d"
PROSE_VALUE = "the last day of October 2020"
PROSE_SLOT = "Contract End Date"

#: A line page 3 of SampleBill.pdf really prints, and a fragment of it that is a
#: CONTIGUOUS run of its words — so every gate that predates this rule passes.
PRINTED_LINE = "Charges for Billing Period for Aug 12, 2020 to Sep 11, 2020"
CONTIGUOUS_PROSE = "Charges for Billing Period for Aug 12, 2020"


def _recorded_answers():
    """{row_label: {value, source, page}} — the pre-I1 answer, by LABEL.

    F-ids are mapped to labels by the engine's own `compute_shape` on the same
    reconstructed template the run used, so nothing here hand-writes a mapping
    that could drift from the grid.
    """
    from template_shape import compute_shape

    rec = json.loads((round2.RAW_DIR / f"{RECORDING}.json")
                     .read_text(encoding="utf-8"))
    grid = json.loads((round2.TEMPLATES / rec["template"])
                      .read_text(encoding="utf-8"))
    shape = compute_shape(grid, log=lambda _m: None)
    label_of = {s["slot_id"]: s["row_label"] for s in shape["field_slots"]}
    out = {}
    for resp in rec["responses"]:
        for raw in resp["raw_llm_responses"]:
            for sid, ans in json.loads(raw)["fields"].items():
                label = label_of.get(sid)
                if label and str(ans.get("value") or "").strip():
                    out.setdefault(label, ans)
    return out


class _AnswerStub:
    """Answers each slot the prompt offers from a {label: answer} dict.

    Reads the PROMPT for its slot ids, exactly as `_ReportStub` in
    `test_round2_I1.py` does, so it can only answer slots the pipeline chose to
    ask about.
    """

    def __init__(self, answers):
        self.answers = answers

    def extract(self, text="", image_b64="", prompt="", **_kw):
        import re

        from connectors.groq_client import LLMResponse
        fields = {}
        for sid, label in re.findall(r'^\s+(F\d+): .*"([^"]+)"$', prompt, re.M):
            ans = self.answers.get(label)
            if ans:
                fields[sid] = {"value": ans["value"], "source": ans["source"],
                               "page": ans["page"]}
        payload = {"fields": fields, "tables": {}}
        return LLMResponse(raw_text=json.dumps(payload), parsed_json=payload,
                           model_used="i11-stub", tokens_used=0, latency_ms=0,
                           success=True, error="")

    def classify(self, **_kw):  # pragma: no cover - not reached
        raise AssertionError("no classification call expected")


def _flags_for(ed, ref):
    return [f for f in ed["validation"]["flagged_fields"] if f["ref"] == ref]


# ══════════════════════════════════════════════════════════════════════════
# The demonstrated delta: prose the pre-existing gates let through
# ══════════════════════════════════════════════════════════════════════════

class TestAContiguousProseAnswerReachesTheNewRule:
    """The same pipeline, the same PDF, a value printed on one line.

    Before this rule the cell came back `high` with an empty `flagged_fields`;
    the test pins that every gate which could have caught it still passes, so
    the demotion has exactly one cause.
    """

    @pytest.fixture(scope="class")
    def run(self):
        answers = {PROSE_SLOT: {"value": CONTIGUOUS_PROSE,
                                "source": PRINTED_LINE, "page": 3}}
        results, _grid, _log = round2.run(
            "run9_engie_BR4", orchestrator_llm=_AnswerStub(answers))
        return results[0].extracted_data

    def test_the_document_really_prints_that_line(self, pdf_dir):
        import pdfplumber

        from text_layer import read_page
        with pdfplumber.open(pdf_dir / "round2" / "SampleBill.pdf") as pdf:
            pages = [read_page(p)[0] for p in pdf.pages]
        assert any(PRINTED_LINE in p for p in pages), (
            "the fixture line is no longer on the page — this test is measuring "
            "something else")

    def test_every_gate_that_predates_this_rule_passes(self, run):
        """Grounded, a contiguous run of printed words, one datum. Nothing but
        `prose_in_a_scalar` stands between this value and `high`."""
        import pdfplumber

        from slot_extractor import _single_datum
        from text_layer import matches_loosely, read_page

        ref = run["extracted_data"][PROSE_SLOT]["ref"]
        assert run["field_provenance"][ref]["grounded"] is True
        assert _single_datum(CONTIGUOUS_PROSE, PROSE_SLOT) is True
        with pdfplumber.open(round2.ROUND2_PDFS / "SampleBill.pdf") as pdf:
            lines = [ln for p in pdf.pages for ln in read_page(p)[1]]
        assert matches_loosely(CONTIGUOUS_PROSE, lines) is True

    def test_the_value_is_kept(self, run):
        """KEPT, not blanked. A visible wrong cell beats an invisible missing
        one — the same trade as a misplaced value and an overprinted one, and
        the reason the strict "a parsed value or nothing" reading was refused
        (it blanks 19 legitimate date ranges to catch one fragment)."""
        assert run["extracted_data"][PROSE_SLOT]["value"] == CONTIGUOUS_PROSE

    def test_it_is_demoted(self, run):
        from app.core.confidence import CONFIDENT_LEVELS, LOW
        ref = run["extracted_data"][PROSE_SLOT]["ref"]
        assert run["validation"]["confidence_map"][ref] == LOW
        assert run["validation"]["confidence_map"][ref] not in CONFIDENT_LEVELS

    def test_it_is_flagged_with_its_own_content_and_this_rules_reason(self, run):
        flags = _flags_for(run, PROSE_SLOT)
        assert len(flags) == 1
        assert flags[0]["value"] == CONTIGUOUS_PROSE
        assert "asks for a date" in flags[0]["reason"]
        assert "sentence" in flags[0]["reason"]

    def test_the_document_is_sent_for_review(self, run):
        assert run["needs_review"] is True


# ══════════════════════════════════════════════════════════════════════════
# The recorded answer — and which gate actually catches it
# ══════════════════════════════════════════════════════════════════════════

class TestTheRecordedProseAnswerEndToEnd:
    @pytest.fixture(scope="class")
    def run(self):
        answers = _recorded_answers()
        assert answers[PROSE_SLOT]["value"] == PROSE_VALUE, (
            "the recording no longer carries the I11 answer this test is about")
        results, _grid, _log = round2.run(
            "run9_engie_BR4", orchestrator_llm=_AnswerStub(answers))
        return results[0].extracted_data

    def test_the_value_is_kept_demoted_and_flagged(self, run):
        from app.core.confidence import LOW
        ref = run["extracted_data"][PROSE_SLOT]["ref"]
        assert run["extracted_data"][PROSE_SLOT]["value"] == PROSE_VALUE
        assert run["validation"]["confidence_map"][ref] == LOW
        assert _flags_for(run, PROSE_SLOT)

    def test_an_earlier_gate_is_what_catches_it_not_this_rule(self, run):
        """THE CORRECTION, pinned so it cannot be quietly re-claimed. D9's
        word-run gate fires first because the value straddles a line break, and
        `confidence_for` is never reached — so this rule's reason is NOT the one
        on the flag. The value of the rule is elsewhere (see the class above)."""
        flags = _flags_for(run, PROSE_SLOT)
        assert len(flags) == 1
        assert "no run of words on the page spells this value" in \
            flags[0]["reason"]
        assert "asks for a date" not in flags[0]["reason"]

    def test_the_rule_would_have_caught_it_too(self, run):
        """Agreement, not credit: asked directly, the rule says yes."""
        from slot_extractor import prose_in_a_scalar
        fires, why = prose_in_a_scalar(PROSE_VALUE, PROSE_SLOT)
        assert fires is True
        assert "asks for a date" in why

    def test_nothing_else_in_the_answer_moved(self, run):
        """A rule that demoted its own document's good cells would be the
        mirror of the defect it fixes. `Billing Period` is the one that would
        go first: it is a RANGE, `Aug 12, 2020 to Sep 11, 2020`."""
        from app.core.confidence import CONFIDENT_LEVELS
        conf = run["validation"]["confidence_map"]
        entry = run["extracted_data"]["Billing Period"]
        assert entry["value"] == "Aug 12, 2020 to Sep 11, 2020"
        assert conf[entry["ref"]] in CONFIDENT_LEVELS


# ══════════════════════════════════════════════════════════════════════════
# The three conditions, and what each one keeps out
# ══════════════════════════════════════════════════════════════════════════

class TestTheLabelMustImplyAScalar:
    @pytest.mark.parametrize("label,kind", [
        ("Contract End Date", "date"), ("Pay Period", "date"),
        ("Amount Due", "amount"), ("Closing Balance", "amount"),
        ("Qty", "number"), ("Account Number", "id"), ("Meter Number", "id"),
    ])
    def test_a_scalar_label_is_recognised(self, label, kind):
        from slot_extractor import scalar_kind
        assert scalar_kind(label) == kind

    @pytest.mark.parametrize("label", [
        "Charge Description",      # a description, not a charge
        "Payment Terms",           # terms, not a payment
        "Amount in Words",         # a cheque's legal amount IS prose
        "Account Holder",          # a person, not an identifier
        "Notes", "Bill To", "Status", "",
    ])
    def test_a_prose_label_is_not(self, label):
        from slot_extractor import scalar_kind
        assert scalar_kind(label) is None


class TestAValueWithNoScalarInItDoesNotFire:
    """Condition 2, and it is load-bearing. This is where a band's LABEL COLUMN
    lives: a two-column band is named after its label column, so the column
    headed `CURRENT ASSETS` holds account names and the one headed `COST OF
    GOODS SOLD` holds `Opening Inventory`. On the gold corpus that is 103 cells.

    The cost is stated: a date field answered with prose containing NO date is
    not caught either.
    """

    @pytest.mark.parametrize("label,value", [
        ("CURRENT ASSETS", "Accounts Receivable (net)"),
        ("COST OF GOODS SOLD", "Less: Closing Inventory"),
        ("OPERATING EXPENSES", "Bank Charges & Interest"),
        ("Contract End Date", "on or about the end of the month"),
    ])
    def test_it_is_left_alone(self, label, value):
        from slot_extractor import prose_in_a_scalar
        assert prose_in_a_scalar(value, label)[0] is False


class TestOrdinaryWordsAreNotProse:
    """Condition 3. Only a CLOSED-CLASS word is prose. An open-class word is
    what a short ordinary value is made of."""

    @pytest.mark.parametrize("label,value", [
        # a real gold cell: the equity line carries a number and four ordinary
        # words, and was a false positive under every looser rule tried.
        ("SHAREHOLDERS' EQUITY", "Common Stock (100 shares @ $1,000 par)"),
        ("Amount", "1,250.00 CR"),
        ("Qty", "40 hrs"),
        ("Doc No", "IS-2024-Q4"),
        ("Invoice Number", "INV-2024-0031"),
        ("Routing Number", "021000021"),
    ])
    def test_it_is_left_alone(self, label, value):
        from slot_extractor import prose_in_a_scalar
        assert prose_in_a_scalar(value, label)[0] is False


class TestARangeIsNotProse:
    """Range connectors are allowed. A period field holds two dates because the
    document prints two — this is the 19 legitimate values the STRICT reading
    ("a parsed value or nothing") would have blanked."""

    @pytest.mark.parametrize("label,value", [
        ("Billing Period", "Aug 12, 2020 to Sep 11, 2020"),
        ("Pay Period", "April 1-30, 2024"),
        ("Period", "March 15-22, 2024"),
        ("Statement Period", "01/01/2024 through 01/31/2024"),
    ])
    def test_it_is_left_alone(self, label, value):
        from slot_extractor import prose_in_a_scalar
        assert prose_in_a_scalar(value, label)[0] is False


class TestTheRuleIsSilentOnANonEnglishDocument:
    """STATED, not fixed. Every word list in this rule is English, so condition
    2 fails on a non-English date and nothing fires. Being silent is the right
    failure for an English-only rule — it demotes nothing it cannot read — but
    it is a GAP, not coverage, and this test exists so it cannot be discovered
    later as a surprise."""

    @pytest.mark.parametrize("value", [
        "le dernier jour d'octobre 2020",      # fr
        "der letzte Tag des Oktober 2020",     # de
        "el ultimo dia de octubre de 2020",    # es
    ])
    def test_a_non_english_prose_date_is_not_caught(self, value):
        from slot_extractor import prose_in_a_scalar
        assert prose_in_a_scalar(value, "Contract End Date")[0] is False

    def test_the_english_equivalent_is(self):
        from slot_extractor import prose_in_a_scalar
        assert prose_in_a_scalar(PROSE_VALUE, "Contract End Date")[0] is True


class TestItIsNotOnlyAboutDates:
    """The defect was found on a date, but the rule is written on the label's
    class rather than on dates, so an amount or a reference holding a sentence
    is caught by the same three conditions."""

    @pytest.mark.parametrize("label,value,kind", [
        ("Reference", "Payment for invoice 123", "id"),
        ("Late Fee Amount", "a charge of $25.00 after the due date", "amount"),
        ("Qty", "up to 40 units per month", "number"),
    ])
    def test_it_fires_and_names_the_kind(self, label, value, kind):
        from slot_extractor import prose_in_a_scalar
        fires, why = prose_in_a_scalar(value, label)
        assert fires is True
        assert f"asks for a {kind}" in why
