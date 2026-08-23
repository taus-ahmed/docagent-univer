"""Unit tests for the engine-output adapter. Offline, no LLM, always green."""
from types import SimpleNamespace

from tests.harness.adapter import adapt


def _res(ed):
    return SimpleNamespace(extracted_data=ed)


LABEL = {
    "document_id": "T", "document_type": "balance_sheet",
    "fields": {"Total Current Assets": 415000, "Net Pay": 7513.03},
    "field_types": {"Total Current Assets": "money", "Net Pay": "money"},
    "tables": {
        "current_assets": [{"Label": "Cash", "Amount": 168000}],
        "line_items": [{"Description": "Widget", "Qty": 2, "Amount": 10.0}],
    },
    "table_types": {
        "current_assets": {"Label": "string", "Amount": "money"},
        "line_items": {"Description": "string", "Qty": "number", "Amount": "money"},
    },
}

GRID = {"cells": {
    "0,0": {"value": "Total Current Assets"}, "0,1": {"value": "", "extractTarget": True},
    "1,0": {"value": "Net Pay"}, "1,1": {"value": "", "extractTarget": True},
}}


class TestFields:
    def test_label_keyed_fields_with_value_dicts(self):
        out = adapt([_res({"extracted_data": {
            "Total Current Assets": {"value": "415,000", "confidence": "high"},
            "Net Pay": 7513.03,
            "_label_A1": "static",
        }})], LABEL, GRID)
        assert out["fields"]["Total Current Assets"] == "415,000"
        assert out["fields"]["Net Pay"] == 7513.03
        assert "_label_A1" not in out["fields"]

    def test_ref_keyed_fields_resolve_via_grid(self):
        out = adapt([_res({"extracted_fields": {"B1": "415000", "B2": "7513.03"}})],
                    LABEL, GRID)
        assert out["fields"]["Total Current Assets"] == "415000"
        assert out["fields"]["Net Pay"] == "7513.03"

    def test_fuzzy_field_name_maps_to_gold(self):
        out = adapt([_res({"extracted_data": {"total current assets": 415000}})],
                    LABEL, GRID)
        assert out["fields"]["Total Current Assets"] == 415000

    def test_unknown_field_survives_for_hallucination_scoring(self):
        out = adapt([_res({"extracted_data": {"Completely Invented": 1}})],
                    LABEL, GRID)
        assert out["fields"]["Completely Invented"] == 1


class TestLayoutSections:
    def test_section_maps_to_gold_schema(self):
        out = adapt([_res({"layout_sections": {"current_assets": {"rows": [
            {"label_col": "A", "value_col": "B", "row": 2,
             "label": "Cash", "value": "168000"},
        ]}}})], LABEL, GRID)
        assert out["tables"]["current_assets"] == [{"Label": "Cash", "Amount": "168000"}]

    def test_phantom_total_section_merges_not_vanishes(self):
        """A 'Total Current Assets' phantom section must merge into
        current_assets (like the writer does) so its duplicate row scores
        as hallucinated instead of silently disappearing."""
        out = adapt([_res({"layout_sections": {
            "current_assets": {"rows": [
                {"label": "Cash", "value": "168000", "row": 2}]},
            "total_current_assets": {"rows": [
                {"label": "Cash", "value": "168000", "row": 2}]},
        }})], LABEL, GRID)
        assert len(out["tables"]["current_assets"]) == 2

    def test_unmatched_section_kept_and_noted(self):
        out = adapt([_res({"layout_sections": {"zzz_nonsense": {"rows": [
            {"label": "Thing", "value": "1", "row": 1}]}}})], LABEL, GRID)
        assert "zzz_nonsense" in out["tables"]
        assert any("matches no gold table" in n for n in out["notes"])


class TestRowArrays:
    def test_table_rows_map_columns_to_gold(self):
        out = adapt([_res({"line_items_rows": [
            {"description": "Widget", "qty": "2", "amount": "$10.00",
             "_table_source": "x"},
        ]})], LABEL, GRID)
        rows = out["tables"]["line_items"]
        assert rows == [{"Description": "Widget", "Qty": "2", "Amount": "$10.00"}]

    def test_multiple_results_concatenate(self):
        r1 = _res({"line_items_rows": [{"description": "A", "amount": 1}]})
        r2 = _res({"line_items_rows": [{"description": "B", "amount": 2}]})
        out = adapt([r1, r2], LABEL, GRID)
        assert len(out["tables"]["line_items"]) == 2
        assert any("2 result blocks" in n for n in out["notes"])


class TestBestMatchWinsAGoldName:
    """Name matching was greedy and first-come-first-served, so a WEAK match
    could take a gold name an EXACT match wanted, and the exact match arriving
    afterwards was dropped as a duplicate.

    On BS-2024-Q1 the engine returned "Other Current Assets" = $8,800 and
    "Total Current Assets" = $1,129,003, both correct and both correctly
    placed. "Other Current Assets" was seen first, token-overlapped gold's
    "Total Current Assets" at exactly 0.5 — they share two of three tokens and
    the differing one carries the whole meaning — took that key, and the exact
    match was discarded. It was reported for four phases as that document's one
    genuine extraction error. It was ours.
    """

    LABEL = {"document_id": "BS", "document_type": "balance_sheet",
             "fields": {"Total Current Assets": 1129003},
             "field_types": {"Total Current Assets": "money"},
             "tables": {}, "table_types": {}}

    def _adapt(self, ordered_fields):
        from tests.harness.adapter import adapt
        r = _res({"extracted_data": {k: {"value": v, "confidence": "grounded"}
                                   for k, v in ordered_fields}})
        return adapt([r], self.LABEL, {"cells": {}})

    def test_the_exact_match_gets_the_gold_name(self):
        out = self._adapt([("Other Current Assets", "$8,800"),
                           ("Total Current Assets", "$1,129,003")])
        assert out["fields"]["Total Current Assets"] == "$1,129,003"

    def test_order_does_not_decide_it(self):
        out = self._adapt([("Total Current Assets", "$1,129,003"),
                           ("Other Current Assets", "$8,800")])
        assert out["fields"]["Total Current Assets"] == "$1,129,003"

    def test_the_loser_keeps_its_own_name_and_is_not_dropped(self):
        """It must still be visible — as out-of-schema, which is what it is."""
        out = self._adapt([("Other Current Assets", "$8,800"),
                           ("Total Current Assets", "$1,129,003")])
        assert out["fields"].get("Other Current Assets") == "$8,800"

    def test_a_lone_fuzzy_match_still_matches(self):
        """Best-match-wins must not turn off fuzzy matching — with no exact
        claim competing, the fuzzy one is still the best available."""
        from tests.harness.adapter import adapt
        r = _res({"extracted_data": {"Total Current Asset":
                                   {"value": "1129003", "confidence": "high"}}})
        out = adapt([r], self.LABEL, {"cells": {}})
        assert out["fields"].get("Total Current Assets") == "1129003"
