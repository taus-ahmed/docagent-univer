"""Run C — C7 the cheque's bottom line, C8 the balance-sheet identity.

C7 runs on the committed moderate-quality cheque photos
(tests/test_OCR/chk_*_moderate.jpg), read by the local OCR seam. What the
model would put in each slot is SIMULATED from each cheque's ground truth
(the true values, and the routing/account pair swapped) — no model is called.
These checks make a wrong assignment VISIBLE; they do not make the reading
correct.
"""
from __future__ import annotations

import contextlib
import io
import json

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from validators import FAIL, CheckContext  # noqa: E402

CHK = bs.REPO_DIR / "tests" / "test_OCR"
FIELDS = [{"ref": "B1", "row_label": "Cheque Number"},
          {"ref": "B2", "row_label": "Routing Number"},
          {"ref": "B3", "row_label": "Account Number"}]


@pytest.fixture(scope="module")
def cheques():
    from core.preprocessor import preprocess_file
    out = []
    for j in sorted(CHK.glob("chk_*.json")):
        t = json.loads(j.read_text(encoding="utf-8"))
        with contextlib.redirect_stdout(io.StringIO()):
            pages = preprocess_file(CHK / t["files"]["moderate"]).page_texts
        out.append((t, pages))
    assert len(out) == 18
    return out


def _reasons(values, pages):
    import cheque_validators as CV
    return {r.reason for r in CV.bottom_line(CheckContext(FIELDS, values, pages))
            if r.status == FAIL or r.flags}


def _truth(t):
    return {"B1": t["check_number"], "B2": t["routing_number"], "B3": t["account_number"]}


class TestC7BottomLine:
    def test_the_true_values_raise_nothing_unless_the_routing_is_really_invalid(self, cheques):
        for t, pages in cheques:
            got = _reasons(_truth(t), pages)
            if t["intentional_invalid_checksum_test_case"]:
                assert got == {"routing_checksum_failed"}, t["id"]
            else:
                assert got == set(), (t["id"], got)

    def test_a_routing_account_swap_is_flagged_on_both_and_not_moved(self, cheques):
        import cheque_validators as CV
        valid = [(t, p) for t, p in cheques if not t["intentional_invalid_checksum_test_case"]]
        for t, pages in valid:
            vals = {"B1": t["check_number"], "B2": t["account_number"],
                    "B3": t["routing_number"]}
            res = [r for r in CV.bottom_line(CheckContext(FIELDS, vals, pages))
                   if r.reason == "possible_swap"]
            assert len(res) == 1 and sorted(res[0].slots) == ["B2", "B3"], t["id"]
            said = res[0].flags[0][2]
            assert f"Routing Number = {t['routing_number']}" in said, said
            assert vals["B2"] == t["account_number"]          # never auto-swapped

    def test_an_empty_cheque_number_is_flagged_when_the_bottom_line_has_one(self, cheques):
        hits = 0
        for t, pages in cheques:
            vals = {"B2": t["routing_number"], "B3": t["account_number"]}
            hits += "cheque_number_missing" in _reasons(vals, pages)
        # 16 of 18: on chk_001 and chk_007 OCR reads the cheque-number group
        # of the MICR line as letters, so there is no digit group to point at.
        assert hits >= 16, hits

    def test_a_cheque_number_unlike_the_top_right_number_is_low(self, cheques):
        t, pages = next((t, p) for t, p in cheques if t["id"] == "chk_004")
        vals = {**_truth(t), "B1": "001999"}
        assert "cheque_number_mismatch" in _reasons(vals, pages)

    def test_a_street_number_is_not_the_top_right_cheque_number(self):
        """Found on gold CHQ-001847 during this run: `330 Madison Ave` on the
        first line was taken as the cheque number and the correct
        `CHQ-001847` was flagged."""
        import pdfplumber
        import cheque_validators as CV
        with pdfplumber.open(str(bs.PDF_DIR / "CHQ-001847.pdf")) as pdf:
            pages = [pdf.pages[0].extract_text()]
        assert CV._top_number(pages) == "001847"
        assert _reasons({"B1": "CHQ-001847"}, pages) == set()
        assert "cheque_number_mismatch" in _reasons({"B1": "CHQ-001848"}, pages)

    @pytest.mark.parametrize("value", ["12345678", "1234567890", "021000022"])
    def test_routing_must_be_nine_digits_passing_the_checksum(self, value):
        assert "routing_checksum_failed" in _reasons({"B2": value}, [""])

    def test_the_checksum_is_applied_only_to_a_routing_slot(self):
        import cheque_validators as CV
        fields = [{"ref": "B1", "row_label": "Reference"}]
        assert CV.bottom_line(CheckContext(fields, {"B1": "123456789"}, [""])) == []

    def test_the_prompt_states_the_bottom_line_for_a_scanned_cheque_only(self):
        from slot_extractor import cheque_bottom_line_hint
        slots = {"fields": FIELDS}
        hint = cheque_bottom_line_hint("cheque", slots, {1: "ocr"})
        assert "exactly 9 digits" in hint and "3-6 digit" in hint
        assert cheque_bottom_line_hint("cheque", slots, {1: "native"}) == ""
        assert cheque_bottom_line_hint("invoice", slots, {1: "ocr"}) == ""


class TestC8BalanceIdentity:
    FIELDS = [{"ref": "B5", "row_label": "TOTAL ASSETS"},
              {"ref": "B9", "row_label": "TOTAL LIABILITIES & EQUITY"}]

    def _run(self, a, b):
        import balance_sheet_validators as BV
        return BV.balance_identity(CheckContext(self.FIELDS, {"B5": a, "B9": b}, []))

    def test_equal_totals_raise_nothing(self):
        res = self._run("$1,365,503", "$1,365,503")
        assert [r.status for r in res] == ["pass"] and not res[0].flags

    def test_rounding_is_not_a_difference(self):
        assert self._run("1,000.00", "1,000.01")[0].status == "pass"

    def test_differing_totals_flag_both_and_show_the_difference(self):
        res = self._run("$1,365,503", "$1,248,704")
        assert res[0].status == FAIL and sorted(res[0].slots) == ["B5", "B9"]
        assert res[0].reason == "assets_not_equal_liabilities_plus_equity"
        assert "116,799" in res[0].flags[0][2] and len(res[0].flags) == 2

    def test_only_one_total_present_checks_nothing(self):
        import balance_sheet_validators as BV
        assert BV.balance_identity(CheckContext(self.FIELDS[:1], {"B5": "$5"}, [])) == []

    @pytest.mark.parametrize("label", ["Total Liabilities and Shareholders' Equity",
                                       "TOTAL LIABILITIES & STOCKHOLDERS EQUITY",
                                       "Total liabilities and equity"])
    def test_label_variants(self, label):
        import balance_sheet_validators as BV
        assert BV.role_of(label) == "liab_eq"
