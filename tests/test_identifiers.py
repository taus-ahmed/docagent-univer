"""Pluggable identifier validators (Part 1.6)."""
from __future__ import annotations

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

import identifiers  # noqa: E402
from identifiers.india import gstin_check_char  # noqa: E402
from validators import FAIL, PASS, CheckContext  # noqa: E402

PAN = "AAPFU0939F"
GSTIN = "27" + PAN + "1Z" + gstin_check_char("27" + PAN + "1Z")


@pytest.mark.parametrize("kind,text,ok", [
    ("iban", "GB82 WEST 1234 5698 7654 32", True),
    ("iban", "DE89 3704 0044 0532 0130 00", True),
    ("iban", "AE07 0331 2345 6789 0123 456", True),
    ("iban", "GB82 WEST 1234 5698 7654 33", False),    # one digit wrong
    ("iban", "DE89 3704 0044 0532 0130", False),       # wrong length
    ("swift", "DEUTDEFF", True), ("swift", "NWBKGB2LXXX", True),
    ("swift", "DEUTQQFF", False), ("bic", "BOFAUS3N", True),
    ("aba", "021000021", True), ("aba", "021000022", False),
    ("uk_sort_code", "12-34-56", True), ("uk_sort_code", "12-34-5", False),
    ("gstin", GSTIN, True), ("gstin", GSTIN[:-1] + ("A" if GSTIN[-1] != "A" else "B"), False),
    ("gstin", "27AAPFU0939F1A5", False),                # 14th must be Z
    ("pan", PAN, True), ("pan", "AAPXU0939F", False),   # 4th = holder type
    ("ifsc", "HDFC0001234", True), ("ifsc", "HDFC1001234", False),
    ("vat", "DE123456789", True), ("vat", "FR12345678901", True),
    ("vat", "NL123456789B01", True), ("vat", "ATU12345678", True),
    ("vat", "DE12345678", False), ("vat", "US123456789", False),
    ("vat", "GB123456789", True), ("vat", "EL123456789", True),
    ("trn", "100123456789003", True), ("trn", "10012345678900", False),
    ("ein", "12-3456789", True), ("ein", "07-3456789", False), ("ein", "1234567", False),
])
def test_plugins(kind, text, ok):
    v = identifiers.validate(kind, text)
    assert v.ok is ok, (kind, text, v)
    if not ok:
        assert v.reason


def test_the_registry_is_complete_and_every_reason_has_a_label():
    from app.core.review import REASONS
    assert {"iban", "swift", "bic", "aba", "uk_sort_code", "gstin", "pan", "ifsc",
            "vat", "trn", "ein"} <= set(identifiers.known_types())
    missing = identifiers.reason_codes() - set(REASONS)
    assert not missing, missing


def test_empty_is_not_checked_and_unknown_kind_raises():
    assert identifiers.validate("iban", "  ").ok is None
    with pytest.raises(KeyError):
        identifiers.validate("nope", "x")


def _ctx(values, kinds):
    fields = [{"ref": r, "row_label": r, "id_type": k} for r, k in kinds.items()]
    return CheckContext(fields=fields, values=values, pages=[])


def test_the_check_fails_invalid_ids_low_and_passes_valid_ones():
    from identifier_validators import identifier_check
    res = identifier_check(_ctx({"B1": "GB82WEST12345698765433", "B2": "DEUTDEFF"},
                                {"B1": "iban", "B2": "swift"}))
    got = {(r.status, tuple(r.slots), r.reason) for r in res}
    assert (FAIL, ("B1",), "iban_invalid") in got
    assert (PASS, ("B2",), "") in got


def test_pan_must_be_inside_the_gstin():
    from identifier_validators import identifier_check
    other_pan = "ABCPK1234L"
    res = identifier_check(_ctx({"B1": GSTIN, "B2": other_pan}, {"B1": "gstin", "B2": "pan"}))
    assert any(r.reason == "pan_gstin_mismatch" and r.status == FAIL for r in res)
    res = identifier_check(_ctx({"B1": GSTIN, "B2": PAN}, {"B1": "gstin", "B2": "pan"}))
    assert not [r for r in res if r.status == FAIL]


def test_an_unknown_declared_kind_is_said_and_reviewed():
    from identifier_validators import identifier_check
    res = identifier_check(_ctx({"B1": "x"}, {"B1": "passport"}))
    assert res and res[0].needs_review


def test_a_grid_declaration_reaches_the_slots():
    from slot_extractor import declare_id_types
    grid = {"cells": {"0,0": {"value": "IBAN"}, "0,1": {"value": "", "id_type": "iban"},
                      "2,0": {"value": "GSTIN"}, "2,1": {"value": "", "id_type": "gstin"}}}
    slots = {"fields": [{"ref": "B1", "row": 0, "col": 1}],
             "tables": [{"name": "t", "header_row": 2, "columns": [{"col": 1, "key": "GSTIN"}]}]}
    out = declare_id_types(grid, slots)
    assert out["fields"][0]["id_type"] == "iban"
    assert out["tables"][0]["columns"][0]["id_type"] == "gstin"
    assert "id_type" not in slots["fields"][0]      # the shape is not mutated


def test_gstin_against_the_published_sample():
    """27AAPFU0939F1ZV is the sample GSTIN in GSTN's own material: an
    independent vector, not one built with the function under test."""
    assert identifiers.validate("gstin", "27AAPFU0939F1ZV").ok is True
    assert identifiers.validate("gstin", "27AAPFU0939F1ZW").ok is False
