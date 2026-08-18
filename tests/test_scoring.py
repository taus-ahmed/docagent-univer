"""Unit tests for the type-aware scorer. Offline, no LLM, always green."""
from tests.harness.scoring import (
    classify_field, compare_values, parse_date_candidates, parse_money,
    score_document, score_table, summarize, value_in_text,
)


DOC_TEXT = """NEXUS GLOBAL TRADING LLC EXPENSE REPORT
Steel Wire Coils Grade A 500m (SW-500A) 50 pcs $155.00 $7,750.00
Federal Income Tax ($1,245.00)
Accounts Receivable (net) $348,200
Employee: Marcus A. Thompson"""


class TestGrounding:
    """A hallucination metric must tell an INVENTED value from a MISPLACED
    one, or it reports shape bugs as fabrication and stops being believed."""

    def test_plain_number_with_separators(self):
        assert value_in_text("7750.0", DOC_TEXT, "money") is True
        assert value_in_text(7750, DOC_TEXT, "string") is True  # untyped cell

    def test_parenthesised_currency(self):
        assert value_in_text("-1245.0", DOC_TEXT, "money") is True
        assert value_in_text("1245.00", DOC_TEXT, "string") is True

    def test_absent_number_is_invented(self):
        assert value_in_text("999999.99", DOC_TEXT, "money") is False

    def test_string_present_and_absent(self):
        assert value_in_text("Marcus A. Thompson", DOC_TEXT, "string") is True
        assert value_in_text("MERCHANT NAME", DOC_TEXT, "string") is False

    def test_wrapped_string_matches_by_words(self):
        assert value_in_text("Accounts Receivable net", DOC_TEXT, "string") is True

    def test_empty_never_grounded(self):
        assert value_in_text("", DOC_TEXT, "string") is False
        assert value_in_text("x", "", "string") is False


class TestMoney:
    def test_symbols_and_separators(self):
        assert compare_values("$1,234.50", 1234.5, "money") == "correct"
        assert compare_values("£1 234,", "1234", "money") == "correct"
        assert compare_values(1234.5, "1234.50", "money") == "correct"

    def test_two_dp(self):
        assert compare_values(966.71, "966.71", "money") == "correct"
        assert compare_values(966.71, "966.72", "money") == "wrong"
        assert compare_values(966.714, "966.71", "money") == "correct"

    def test_accounting_negative(self):
        assert parse_money("(2.85)") == -2.85
        assert compare_values(-3240.0, "($3,240.00)", "money") == "correct"

    def test_sign_only_difference_is_near(self):
        assert compare_values(-3240.0, "3240.00", "money") == "near"

    def test_km_suffix(self):
        assert parse_money("5K") == 5000
        assert parse_money("1.2M") == 1200000

    def test_not_a_number_falls_back_to_string(self):
        assert compare_values(100, "one hundred", "money") == "wrong"


class TestDate:
    def test_cross_format(self):
        assert compare_values("2024-03-14", "14/03/2024", "date") == "correct"
        assert compare_values("2024-03-14", "03/14/2024", "date") == "correct"
        assert compare_values("2024-01-15", "January 15, 2024", "date") == "correct"
        assert compare_values("2024-01-15", "15 January 2024", "date") == "correct"

    def test_wrong_date(self):
        assert compare_values("2024-01-15", "2024-01-16", "date") == "wrong"

    def test_year_difference_is_near(self):
        assert compare_values("2024-01-15", "2023-01-15", "date") == "near"

    def test_yearless_matches_any_year(self):
        assert compare_values("03/15", "2024-03-15", "date") == "correct"
        assert compare_values("03/15", "03/15", "date") == "correct"
        assert compare_values("03/15", "2024-03-16", "date") == "wrong"

    def test_candidates_ambiguity(self):
        # 03/04 could be March 4 or April 3 — both readings present
        assert (None, 3, 4) in parse_date_candidates("03/04")
        assert (None, 4, 3) in parse_date_candidates("03/04")


class TestString:
    def test_casefold_whitespace(self):
        assert compare_values("Net  30", "net 30", "string") == "correct"

    def test_dash_and_punct_variants(self):
        assert compare_values("Janet Wu – VP Operations",
                              "Janet Wu - VP Operations", "string") == "correct"
        assert compare_values("Apex Industrial Supplies Inc.",
                              "Apex Industrial Supplies Inc", "string") == "correct"

    def test_containment_is_near_not_exact(self):
        assert compare_values("Janet Wu – VP Operations", "Janet Wu",
                              "string") == "near"

    def test_different_is_wrong(self):
        assert compare_values("Pacific Steel", "Atlantic Lumber",
                              "string") == "wrong"


class TestFourOutcomes:
    def test_correct(self):
        assert classify_field(100, "100.00", "money") == "correct"

    def test_wrong(self):
        assert classify_field(100, "999", "money") == "wrong"

    def test_missed(self):
        assert classify_field(100, "", "money") == "missed"
        assert classify_field(100, None, "money") == "missed"
        assert classify_field("x", "N/A", "string") == "missed"

    def test_hallucinated(self):
        assert classify_field(None, "42", "money") == "hallucinated"
        assert classify_field("", "invented", "string") == "hallucinated"

    def test_both_empty(self):
        assert classify_field(None, "", "money") == "empty_ok"


GOLD_ROWS = [
    {"Label": "Cash & Cash Equivalents", "Amount": 168000},
    {"Label": "Accounts Receivable", "Amount": 95000},
    {"Label": "Inventory", "Amount": 140000},
    {"Label": "Prepaid Expenses", "Amount": 12000},
]
COLS = {"Label": "string", "Amount": "money"}


class TestTables:
    def test_perfect_table(self):
        t = score_table(GOLD_ROWS, [dict(r) for r in GOLD_ROWS], COLS)
        assert t["row_precision"] == 1.0
        assert t["row_recall"] == 1.0
        assert t["cell_accuracy"] == 1.0
        assert t["row_count_mismatch"] == 0

    def test_phantom_duplicate_row_is_visible(self):
        """The audit's P3 shape: a fabricated duplicate of row 1 appended.
        Cell-accuracy over matched rows stays perfect — the phantom must
        surface via row_count_mismatch, row_precision and hallucinated_rows,
        never be averaged away."""
        pred = [dict(r) for r in GOLD_ROWS]
        pred.append(dict(GOLD_ROWS[0]))  # fabricated duplicate
        t = score_table(GOLD_ROWS, pred, COLS)
        assert t["row_count_mismatch"] == 1
        assert len(t["hallucinated_rows"]) == 1
        assert t["row_precision"] == 4 / 5
        assert t["row_recall"] == 1.0
        halluc_cells = [c for c in t["cells"] if c["outcome"] == "hallucinated"]
        assert len(halluc_cells) == 2  # Label + Amount of the phantom row

    def test_missing_row(self):
        t = score_table(GOLD_ROWS, GOLD_ROWS[:3], COLS)
        assert t["row_count_mismatch"] == -1
        assert len(t["missed_rows"]) == 1
        assert t["row_recall"] == 3 / 4

    def test_reordered_rows_still_align(self):
        t = score_table(GOLD_ROWS, list(reversed(GOLD_ROWS)), COLS)
        assert t["row_recall"] == 1.0
        assert t["cell_accuracy"] == 1.0

    def test_wrong_value_in_matched_row(self):
        pred = [dict(r) for r in GOLD_ROWS]
        pred[2]["Amount"] = 999999
        t = score_table(GOLD_ROWS, pred, COLS)
        assert t["row_recall"] == 1.0  # label still matches the row
        wrong = [c for c in t["cells"] if c["outcome"] == "wrong"]
        assert len(wrong) == 1
        assert wrong[0]["column"] == "Amount"

    def test_gold_empty_cell_filled_is_hallucinated(self):
        gold = [{"Date": "01/03", "Debit": None, "Credit": 15000}]
        pred = [{"Date": "01/03", "Debit": 15000, "Credit": 15000}]
        t = score_table(gold, pred, {"Debit": "money", "Credit": "money"})
        outcomes = {c["column"]: c["outcome"] for c in t["cells"]}
        assert outcomes["Debit"] == "hallucinated"
        assert outcomes["Credit"] == "correct"


class TestAggregation:
    def _label(self):
        return {
            "document_id": "X", "document_type": "cheque",
            "fields": {"Amount": 100, "Payee": "Pacific Steel", "Memo": None},
            "field_types": {"Amount": "money"},
            "tables": {}, "table_types": {},
        }

    def test_document_and_summary(self):
        adapted = {"fields": {"Amount": "100.00", "Payee": "Wrong Co",
                              "Memo": "invented"}, "tables": {}}
        d = score_document(self._label(), adapted)
        assert d["counts"]["correct"] == 1
        assert d["counts"]["wrong"] == 1
        assert d["counts"]["hallucinated"] == 1
        assert d["accuracy"] == 1 / 2
        assert d["hallucination_rate"] == 1 / 3
        s = summarize([d])
        assert s["overall"]["hallucinated"] == 1
        assert s["by_document_type"]["cheque"]["counts"]["correct"] == 1
        assert s["by_field_type"]["money"]["counts"]["correct"] == 1

    def test_invention_split_from_misplacement(self):
        label = self._label()
        adapted = {"fields": {"Amount": "100.00", "Payee": "Pacific Steel",
                              "Memo": "Marcus A. Thompson"}, "tables": {}}
        # 'Memo' is empty in gold -> hallucinated; but the value IS in the
        # document, so it is a misplacement, not an invention.
        d = score_document(label, adapted, doc_text=DOC_TEXT)
        assert d["counts"]["hallucinated"] == 1
        assert d["hallucinated_ungrounded"] == 0
        assert d["invention_rate"] == 0.0

        adapted["fields"]["Memo"] = "Totally Fabricated Payee Ltd"
        d2 = score_document(label, adapted, doc_text=DOC_TEXT)
        assert d2["counts"]["hallucinated"] == 1
        assert d2["hallucinated_ungrounded"] == 1
        assert summarize([d2])["overall"]["hallucinated_ungrounded"] == 1
