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


class TestCollapseRenames:
    """A schema that calls gold's "Payer Name" field "Drawer Company Name"
    makes ONE mistake. Scored naively it makes two — a miss (nothing answered
    to gold's name) and a hallucination (gold has no field by that name) — and
    the same defect lands in both headline metrics at once."""

    def _results(self, gold_name, gold_val, pred_name, pred_val, ftype="string"):
        from tests.harness.scoring import score_fields
        return score_fields({gold_name: gold_val}, {gold_name: ftype},
                            {pred_name: pred_val})

    def test_the_pair_becomes_one_renamed_entry(self):
        from tests.harness.scoring import collapse_renames
        r = self._results("Payer Name", "Nexus Global Trading LLC",
                          "Drawer Company Name", "Nexus Global Trading LLC")
        assert r["Payer Name"]["outcome"] == "missed"
        assert r["Drawer Company Name"]["outcome"] == "hallucinated"

        assert collapse_renames(r) == 1
        assert r["Payer Name"]["outcome"] == "renamed"
        assert r["Payer Name"]["renamed_to"] == "Drawer Company Name"
        assert r["Payer Name"]["actual"] == "Nexus Global Trading LLC"
        assert "Drawer Company Name" not in r, "the duplicate must be removed"

    def test_a_near_value_is_not_a_rename(self):
        """"Routing Number" = 021000021 vs a predicted "MICR Line" =
        "A021000021A C7743882201C 001847D" is a different, broader field that
        merely contains the routing number. Folding it would flatter the
        score, so it stays two entries — which is what it is."""
        from tests.harness.scoring import collapse_renames
        r = self._results("Routing Number", "021000021",
                          "MICR Line", "A021000021A C7743882201C 001847D")
        assert collapse_renames(r) == 0
        assert r["Routing Number"]["outcome"] == "missed"
        assert r["MICR Line"]["outcome"] == "hallucinated"

    def test_money_renames_match_across_formatting(self):
        from tests.harness.scoring import collapse_renames
        r = self._results("Closing Balance", 125357.26,
                          "Ending Balance", "$125,357.26", ftype="money")
        assert collapse_renames(r) == 1
        assert r["Closing Balance"]["outcome"] == "renamed"

    def test_one_prediction_cannot_absolve_two_gold_fields(self):
        from tests.harness.scoring import collapse_renames, score_fields
        r = score_fields({"A": "Janet Wu", "B": "Janet Wu"},
                         {"A": "string", "B": "string"},
                         {"Signed By": "Janet Wu"})
        assert collapse_renames(r) == 1
        outcomes = sorted(v["outcome"] for v in r.values())
        assert outcomes == ["missed", "renamed"], outcomes

    def test_a_genuine_hallucination_is_untouched(self):
        from tests.harness.scoring import collapse_renames
        r = self._results("Payer Name", "Nexus Global Trading LLC",
                          "Company Phone", "(212) 555-0148")
        assert collapse_renames(r) == 0
        assert r["Payer Name"]["outcome"] == "missed"
        assert r["Company Phone"]["outcome"] == "hallucinated"

    def test_renamed_is_not_counted_as_correct(self):
        """It is still a defect: the user's sheet has an empty cell where they
        expected a value, and a column they did not ask for."""
        from tests.harness.scoring import score_document
        label = {"document_id": "D", "document_type": "cheque",
                 "fields": {"Payer Name": "Nexus Global Trading LLC"},
                 "field_types": {"Payer Name": "string"}, "tables": {}}
        sc = score_document(label,
                            {"fields": {"Drawer Company Name":
                                        "Nexus Global Trading LLC"},
                             "tables": {}}, "Nexus Global Trading LLC")
        assert sc["counts"].get("renamed") == 1
        assert sc["counts"].get("correct", 0) == 0
        assert sc["counts"].get("hallucinated", 0) == 0
        assert sc["accuracy"] == 0.0
        assert sc["hallucination_rate"] == 0.0


class TestHallucinationKinds:
    """Three different events were being reported as one number. Only one of
    them is a lie, and one of them is not a defect at all."""

    def _doc(self, gold_fields, field_types, pred_fields, text,
             gold_tables=None, pred_tables=None):
        from tests.harness.scoring import score_document
        label = {"document_id": "D", "document_type": "invoice",
                 "fields": gold_fields, "field_types": field_types,
                 "tables": gold_tables or {}}
        return score_document(label, {"fields": pred_fields,
                                      "tables": pred_tables or {}}, text)

    def test_a_value_not_in_the_document_is_INVENTED(self):
        sc = self._doc({"Total": "100"}, {"Total": "money"},
                       {"Total": "100", "Vendor": "Nowhere Ltd"},
                       "Total 100")
        assert sc["halluc_kinds"]["invented"] == 1
        assert sc["halluc_kinds"]["out_of_schema"] == 0

    def test_real_content_under_a_name_gold_lacks_is_OUT_OF_SCHEMA(self):
        """Inference proposing "Company EIN" for an EIN printed on the page is
        the feature working, not a hallucination."""
        sc = self._doc({"Total": "100"}, {"Total": "money"},
                       {"Total": "100", "Company EIN": "47-3821654"},
                       "Total 100  EIN 47-3821654")
        assert sc["halluc_kinds"]["out_of_schema"] == 1
        assert sc["halluc_kinds"]["invented"] == 0
        assert sc["halluc_kinds"]["misfiled"] == 0

    def test_real_content_in_a_slot_gold_says_is_empty_is_MISFILED(self):
        """Gold HAS this field and says it is empty. We contradicted it."""
        sc = self._doc({"Total": "100", "Discount": None},
                       {"Total": "money", "Discount": "money"},
                       {"Total": "100", "Discount": "25"},
                       "Total 100  Shipping 25")
        assert sc["halluc_kinds"]["misfiled"] == 1
        assert sc["halluc_kinds"]["out_of_schema"] == 0

    def test_defect_rate_excludes_out_of_schema(self):
        sc = self._doc({"Total": "100"}, {"Total": "money"},
                       {"Total": "100", "Company EIN": "47-3821654",
                        "Company Phone": "(212) 555-0148"},
                       "Total 100 EIN 47-3821654 Tel (212) 555-0148")
        assert sc["counts"]["hallucinated"] == 2
        assert sc["halluc_kinds"]["out_of_schema"] == 2
        assert sc["hallucination_rate"] > 0
        from tests.harness.scoring import summarize
        assert summarize([sc])["overall"]["defect_rate"] == 0.0

    def test_an_extra_row_in_a_known_table_is_not_out_of_schema(self):
        """Gold knows how many rows this table has. An extra one is fabricated,
        not a schema difference."""
        sc = self._doc({}, {}, {},
                       "Consulting 100\nTotal 100",
                       gold_tables={"items": [{"Description": "Consulting",
                                               "Amount": "100"}]},
                       pred_tables={"items": [{"Description": "Consulting",
                                               "Amount": "100"},
                                              {"Description": "Total",
                                               "Amount": "100"}]})
        kinds = sc["halluc_kinds"]
        assert kinds["out_of_schema"] == 0
        assert kinds["misfiled"] == 2, kinds

    def test_internal_metadata_is_never_scored_as_a_value(self):
        """`_confidence` is ours, not the model's. Scoring it counted our own
        tag as something the model invented."""
        sc = self._doc({}, {}, {}, "Consulting 100\nTotal 100",
                       gold_tables={"items": [{"Description": "Consulting",
                                               "Amount": "100"}]},
                       pred_tables={"items": [{"Description": "Consulting",
                                               "Amount": "100"},
                                              {"Description": "Total",
                                               "Amount": "100",
                                               "_confidence": "grounded"}]})
        cols = [c["column"] for t in sc["tables"].values() for c in t["cells"]]
        assert not any(str(c).startswith("_") for c in cols), cols
        assert sc["halluc_kinds"]["invented"] == 0
