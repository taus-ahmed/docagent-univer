"""
The save gate on a pure-table template.

`coverage` measures LABELS that should have slots — the right question for a
form, and no question at all for a pure table. A template that is only a
declared band has no such labels, so it reported `labels: 0, complete: True`
and the gate had nothing to say however wrong the table was. All 23 real
templates in the repo reported complete; so did four deliberately broken ones.

Three rules fill that hole. Each was chosen on its FALSE-POSITIVE rate against
those 23 real templates, because a gate that fires on a legitimate template is
the same class of bug as the silent failure it replaces:

    A  a band column with no heading        0/23   WARN
    D  a band with no headings at all       0/23   BLOCK
    E  two declared regions overlapping     0/23   WARN
    G  duplicate headings inside a band     1/23   REJECTED

G is the one to keep in mind. It fires on `bs_luq`, a real production template
laying two label/value pairs side by side under two columns both headed
"Amount" — which the engine already handles correctly by disambiguating the key
with a column letter. A rule that flags that is worse than no rule.

The no-false-positive test below runs every real template in the repo, so the
sample grows whenever a template is added.
"""
import json

import pytest

from tests.harness import bootstrap as _bs

_bs.bootstrap()

from template_shape import compute_shape, is_usable  # noqa: E402


def _cells(d):
    return {f"{r},{c}": {"value": v} for (r, c), v in d.items()}


def _grid(cells, regions=()):
    return {"cells": _cells(cells), "colWidths": [], "merges": {},
            "repeatRows": [], "regions": list(regions)}


FIVE_COL = [{"type": "table", "r1": 0, "c1": 0, "r2": 20, "c2": 4,
             "orientation": "rows", "name": "Items"}]
HEADINGS = {(0, 0): "Item", (0, 1): "Qty", (0, 2): "Unit",
            (0, 3): "Unit Cost", (0, 4): "Total"}


def _cov(grid):
    return compute_shape(grid, log=lambda _m: None)["coverage"]


# ══════════════════════════════════════════════════════════════════════════
# A — a band column with no heading
# ══════════════════════════════════════════════════════════════════════════

class TestAnUnnamedColumnWarns:
    def test_a_blank_top_left_corner_is_reported(self):
        """T5, and D12(a). The engine synthesises "Column A" and asks the
        model to fill a column it cannot describe. Nothing in the editor tells
        the user; typing any heading fixes it completely."""
        cov = _cov(_grid({k: v for k, v in HEADINGS.items() if k != (0, 0)},
                         FIVE_COL))
        assert len(cov["warnings"]) == 1
        assert "column A" in cov["warnings"][0]
        assert cov["complete"] is False

    def test_a_region_dragged_one_column_too_wide_is_reported(self):
        cov = _cov(_grid({k: v for k, v in HEADINGS.items() if k != (0, 4)},
                         FIVE_COL))
        assert any("column E" in w for w in cov["warnings"])

    def test_it_warns_rather_than_blocks(self):
        """23 templates is evidence, not proof, and every one was drawn by us.
        The shapes a real user draws are exactly the ones not in that sample,
        so A must not be able to stop a save."""
        cov = _cov(_grid({k: v for k, v in HEADINGS.items() if k != (0, 0)},
                         FIVE_COL))
        assert cov["blocking"] == []

    def test_a_fully_headed_table_says_nothing(self):
        cov = _cov(_grid(HEADINGS, FIVE_COL))
        assert cov["warnings"] == [] and cov["blocking"] == []
        assert cov["complete"] is True


# ══════════════════════════════════════════════════════════════════════════
# D — a band with no headings at all
# ══════════════════════════════════════════════════════════════════════════

class TestAHeadlessTableBlocks:
    def test_a_region_over_blank_cells_blocks_the_save(self):
        cov = _cov(_grid({(6, 0): "Notes"}, FIVE_COL))
        assert len(cov["blocking"]) == 1
        assert "no column headings" in cov["blocking"][0]

    def test_the_message_says_what_to_do_about_it(self):
        cov = _cov(_grid({(6, 0): "Notes"}, FIVE_COL))
        assert "Put a heading" in cov["blocking"][0]

    def test_it_does_not_also_warn_about_each_column(self):
        """One block, not one block plus five warnings saying the same thing."""
        cov = _cov(_grid({(6, 0): "Notes"}, FIVE_COL))
        assert cov["warnings"] == []

    def test_the_shape_is_still_usable_so_this_is_a_separate_question(self):
        """`usable` asks whether there is anywhere to put anything, and there
        is — 105 band cells. Blocking has to be its own list rather than an
        overload of that bit."""
        shape = compute_shape(_grid({(6, 0): "Notes"}, FIVE_COL),
                              log=lambda _m: None)
        assert is_usable(shape) is True
        assert shape["coverage"]["blocking"]


# ══════════════════════════════════════════════════════════════════════════
# E — two declared regions overlapping
# ══════════════════════════════════════════════════════════════════════════

class TestOverlappingTablesWarn:
    def test_two_regions_sharing_cells_are_reported(self):
        regions = FIVE_COL + [{"type": "table", "r1": 3, "c1": 0, "r2": 25,
                               "c2": 4, "orientation": "rows", "name": "Items2"}]
        cov = _cov(_grid(HEADINGS, regions))
        assert any("overlap" in w for w in cov["warnings"])

    def test_two_regions_that_do_not_touch_say_nothing(self):
        regions = [{"type": "table", "r1": 0, "c1": 0, "r2": 5, "c2": 1,
                    "orientation": "rows", "name": "A"},
                   {"type": "table", "r1": 8, "c1": 0, "r2": 14, "c2": 1,
                    "orientation": "rows", "name": "B"}]
        cov = _cov(_grid({(0, 0): "Description", (0, 1): "Amount",
                          (8, 0): "Description", (8, 1): "Amount"}, regions))
        assert not any("overlap" in w for w in cov["warnings"])


# ══════════════════════════════════════════════════════════════════════════
# G — rejected, and it must stay rejected
# ══════════════════════════════════════════════════════════════════════════

class TestDuplicateHeadingsAreNotAFinding:
    def test_a_side_by_side_layout_with_two_amount_columns_is_fine(self,
                                                                   repo_dir):
        """`bs_luq` is a real production template: two label/value pairs side
        by side, both value columns headed "Amount". The engine handles it by
        disambiguating the key with a column letter. A gate that flags it
        would be the bug this whole gate exists to avoid."""
        raw = json.loads(
            (repo_dir / "tests/fixtures/prod_templates/bs_luq.json").read_text())
        cov = _cov(raw.get("grid", raw))
        assert cov["warnings"] == [], cov["warnings"]
        assert cov["blocking"] == [], cov["blocking"]


# ══════════════════════════════════════════════════════════════════════════
# The measurement that decides whether any of this may ship
# ══════════════════════════════════════════════════════════════════════════

def _all_real_templates(repo_dir):
    out = []
    for sub in ("tests/gold/templates", "tests/gold/hand_drawn",
                "tests/fixtures/prod_templates", "tests/fixtures/scenarios"):
        for f in sorted((repo_dir / sub).glob("*.json")):
            raw = json.loads(f.read_text(encoding="utf-8"))
            grid = raw.get("grid") if "grid" in raw else raw
            if isinstance(grid, dict) and "cells" in grid:
                out.append((f.stem, grid))
    out.append(("w2_table", json.loads(
        (repo_dir / "tests/fixtures/w2_table.json").read_text())))
    return out


class TestNoRealTemplateTripsTheGate:
    def test_the_sample_is_not_empty(self, repo_dir):
        assert len(_all_real_templates(repo_dir)) >= 20

    def test_not_one_of_them_is_blocked(self, repo_dir):
        blocked = [n for n, g in _all_real_templates(repo_dir)
                   if _cov(g)["blocking"]]
        assert blocked == [], blocked

    def test_not_one_of_them_is_warned_about(self, repo_dir):
        """This is the number the rules were chosen on. If adding a template
        breaks this test, either the template is wrong or the rule is — and
        the rule is the more likely of the two."""
        warned = [(n, _cov(g)["warnings"]) for n, g in _all_real_templates(repo_dir)
                  if _cov(g)["warnings"]]
        assert warned == [], warned
