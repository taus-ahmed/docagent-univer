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
