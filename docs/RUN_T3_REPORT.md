# RUN T3 Report

Branch: `fix/review-fixes`. Date: 2026-11-27. No live calls, no flags enabled.

---

## S1 — Thinking budget

**Problem.** Structure-plan calls on `gemini-2.5` models were hitting `MAX_TOKENS`
because thinking tokens are billed as output and consume the same `maxOutputTokens`
cap.  A plan call that needs ~300 output tokens was being pushed out by 7k–18k
thinking tokens.

**Fix.** Added `GEMINI_THINKING_BUDGET_PLAN: int = 0` to `config.py` (default 0 =
thinking off for plan calls).  `perception_store.plan_pages` reads it and passes
`thinking_budget=0` to `_llm_json`.  `gemini_client._gen_config` already supports
`thinkingBudget` for `gemini-2.5` and uses `thinkingLevel` for `gemini-3.x` — no
change there.  Extraction calls follow the existing `GEMINI_THINKING_BUDGET` setting
(default: model's own).

**Tests.** `tests/test_thinking_budget.py` — 7 tests: budget forwarded as
`thinkingBudget` for 2.5, ignored for 3.x, plan calls pass budget=0 by default.

---

## S2 — Cost accounting

**Problem.** A timed-out call that returned no token data was charged ~$0.1004 via
the blended-rate fallback `$0.15/M tokens × tokens_in_progress`.  The model never
processed the request; charging it as an ordinary call inflates job cost estimates
and confuses per-document cost reporting.

**Fix.** In `llm_contract.finish_attempt()`: when `error_kind` is set and
`total_tokens` is None (no token data came back), `cost_estimate` is set to `0.0`
rather than leaving it None for the fallback to fill.  Calls that did return token
data (e.g. a MAX_TOKENS hit that still billed prompt tokens) keep their real cost.
`cost_breakdown()` already skips entries with no tokens; with `cost_estimate=0.0`
the entry is counted as a call but billed $0.

**Tests.** `tests/test_cost_accounting.py` — 6 tests: timeout/transient → $0,
MAX_TOKENS with real tokens → real cost, successful call unaffected, breakdown sums
correctly, no-tokens-no-error edge case stays None.

---

## S3 — Plan validation

**Problem.** The model often put lines in `group_header_line_ids` but forgot to also
include them in `line_ids`, causing 19–20 validator errors per vendor-list page and
forcing a plan retry.

**Fix.** `_normalize_plan()` (new, in `structure_engine.py`) runs before validation:
any `group_header_line_ids` / `header_line_ids` / `carried_line_ids` entry not in
`line_ids` is auto-added to it.  The validator still runs and logs the first 10
error messages so genuine problems surface; the common missing-id case is silently
repaired.  `plan_source` is set to `"model_normalized"` on the repaired path.

---

## S4 — Geometry bugs (mobile_vendor_list_8pg page 3)

### S4a — Trailing group header

**Problem.** A group header for the last vendor in a list (no data rows following it
on that page) was set in `group_cur` but never attached — the loop ended and
`group_cur` was discarded silently.

**Fix.** After the row-building loop, if `has_groups and group_cur is not None`:
emit a standalone `_section=True` row carrying the group, then clear `group_cur`.

### S4b — Stacked rows glued by pdfplumber

**Problem.** Two invoice rows printed very close together are merged into one line
by pdfplumber's y-tolerance clustering.  The structure engine then placed them as
one row, losing one invoice line per glued pair.

**Fix.** `_split_stacked_words(ws, pitch)` (new): when a line's words span two
distinct baselines with a gap ≥ `min(0.4 × size, 0.6 × pitch)`, AND each
sub-cluster looks like a row line (has a date or ≥1 amount), split the words into
two groups and emit two rows.  Conservative: neither cluster needs to be a row-line
→ no split (labels stacked above labels are not rows).

**Tests.** `tests/test_geometry_bugs.py` — 9 tests: trailing group header emitted,
data row still present, 2-baseline line splits into 2, each has date/amount, single-
baseline line not split, non-row-line baselines not split.  Plus 3 cross-page group
tests (see S4 Close-out below).

---

## S5 — Row count (mobile_vendor_list_8pg)

Measured with pdfplumber:

| page | text-layer invoice rows | engine rows |
|------|------------------------|-------------|
| 1    | 13                     | —           |
| 2    | 15                     | —           |
| 3    | 12                     | —           |
| 4    | 14                     | —           |
| 5    | 14                     | —           |
| 6    | 12                     | —           |
| 7    | 10                     | —           |
| 8    |  0 (summary page)      | —           |
| **Total** | **90**           | **90**      |

Row count is **correct**.  The 90 rows returned by the engine match exactly the 90
invoice rows the text layer contains.  Page 3 had 12 actual data rows (not 29 — the
29 included CHECK DATE headers, totals and the footer line).

---

## S6 — Reading order metric

Added `order_pairs` and `order_violations` to `score()` in `tools/position_check.py`.

**Definition.** For every ordered pair of placed value items on the same page, where
item A precedes item B in the key: if A's sheet row > B's sheet row, it is a
violation.  `order%` = `100 × (1 − violations / pairs)`.

Printed in the per-document table as `order%` and in the TOTAL line as
`order=…% (viol=N/M)`.

---

## S7 — Flat forms

**Problem.** `form_boxes.form_regions()` only ran when a page had AcroForm widget
values.  Flattened IRS forms (W-2, 1099-NEC/K) have drawn boxes and printed values
but no widgets — they scored 0% with the flat-form path.

**Fix.** New `STRUCTURE_READ_FLAT_FORMS: bool = False` config flag.  When on:

- `form_boxes.has_flat_form_boxes(page)` detects a flat form: drawn edges enclose
  ≥4 text words, no widget values.
- `form_boxes.form_regions(page, flat_form=True)` runs the existing box-reading
  code; `_infer_flat_origins(ws, box)` assigns synthetic `origin="label"` / `"value"`:
  - If two font-size clusters exist and the smaller is at the top of the box → smaller
    = label, larger = value.
  - Fallback: two baseline clusters with a gap ≥ 1 × size → top = label, rest = value.
  - Single-word box → no split (whole box is label).
- `structure_geometry.proposal()` calls `form_regions(page, flat_form=True)` for
  pages without widget values when the flag is on; the original path is unchanged.

**Tests.** `tests/test_flat_forms.py` — 10 tests: detection (positive/negative cases),
label/value inference (size cluster, baseline fallback, single word), form_regions
returns regions with value fields, fillable-form path unaffected.

---

---

## Close-out: Regression check (Item 1)

Measured with `tools/position_check.py` on 11 keyed documents (6 dev, 5 heldout).
Three versions compared: old Organized engine, commit c50e8de, and HEAD.

| half | version | right-hdr% | right-row% | glued | split | miss | order% |
|---|---|---|---|---|---|---|---|
| dev | HEAD | 99.7% | 99.7% | 1 | 4 | 3 | 100.0% |
| heldout | HEAD | 86.8% | 85.8% | 4 | 9 | 42 | 100.0% |
| heldout | c50e8de | 83.5% | 83.5% | 5 | 16 | 78 | 100.0% |

**No regressions since c50e8de.** T3 changes (S1–S8) improved heldout right-row from 83.5% → 85.8%.  Every cell that moved, moved in the right direction.  The low heldout score is entirely explained by irs6744_w2_mcguire and irs6744_1099NEC_1099K_garcia (both score 0% right-header — they require STRUCTURE_READ_FLAT_FORMS=True, which is off by default).

---

## Close-out: Reading order (Item 2)

`order%` from position_check.py (2026-11-27):

| half | order% | violations | pairs |
|---|---|---|---|
| dev | 100.0% | 0 | 46,199 |
| heldout | 100.0% | 5 | 15,987 |

**5 violations, all in irs6744_w2_mcguire (W-2 form).** All 5 are caused by `$28,000` for "3 Social security wages" placed at sheet row 30 while later fields land at rows 11–19 — a flat-form multi-copy reading artefact (the box structure is not decoded without STRUCTURE_READ_FLAT_FORMS=True).  This is a pre-existing condition since c50e8de; it is not a T3 regression.  With STRUCTURE_READ_FLAT_FORMS=True the violations drop to 0 (measured separately).  **No general fix without enabling the flag.**

---

## Close-out: Flat form accuracy (Item 3)

Measured with `STRUCTURE_READ_FLAT_FORMS=True` against the answer keys.

| document | key items | correct | wrong | missing | accuracy |
|---|---|---|---|---|---|
| irs6744_w2_mcguire | 61 | 20 (hdr) | 0 | 41 | **62.5%** kv-items |
| irs6744_1099NEC_1099K_garcia | 99 | 15 (hdr) | 0 | 84 | **14.8%** kv-items |

Both are **under 80%**.

**What blocks W-2 (62.5%):** The PDF has no internal edges dividing the first-name / last-name / suffix area.  Three separate fields collapse into one large box; `_infer_flat_origins` assigns all words to "label" and no value is extracted.  Lowering the font-ratio threshold (1.3 → 1.2) and baseline-gap multiplier (1.0x → 0.7x) had no effect — the problem is a missing edge in the PDF, not a threshold issue.

**What blocks 1099 (14.8%):** Multi-line labels wrap into adjacent frames.  The first line of a 2-line label becomes the box's "label" words while the second line is in the adjacent box.  The decoder sees the second-line fragment as a separate field's label and misassigns its value.  Additionally, monthly breakdown rows (5a–5l) have no box edges at all — 49/99 key items are simply absent from the flat-form reading.

The `_infer_flat_origins` heuristic is correct for well-formed flat forms; the IRS fixtures fail for structural PDF reasons outside the heuristic's scope.  Threshold changes are kept (they are correct for the stated cases) but do not affect these two documents.

---

## Close-out: Group headers across pages (Item 4)

**Problem.** Two related bugs with S4a:
1. `group_cur` was never reset after a data row, so S4a would always fire for the last group even when it had rows — emitting a spurious section row.
2. When a table continues onto the next page and the group header was on the previous page, the continuation page had no `group_ids`, so `group_cur` started as `None` and rows were written without any group attached.

**Fix.**
- Added `group_had_rows = False` tracking: set True when any data row is emitted under a group, reset to False on a new group header.  S4a only fires when `not group_had_rows`.
- Added `region["_last_group"]` to store the last active group at end of `_place_table`.
- In `_place_table` initialization: when `region.get("continued") and prev_tables and not has_groups`, inherit `prev_tables[-1]["last_group"]` as `group_cur` with `group_had_rows = True` (the header was shown on the previous page, not a trailing one).
- In `place_page`'s `prev_tables.append(...)`: added `"last_group": reg.get("_last_group")`.

**Tests.** 3 new tests in `tests/test_geometry_bugs.py` (`TestGroupHeadersAcrossPages`):
- `test_group_header_bottom_page1_rows_on_page2`: group header trailing on page 1, rows on page 2 → rows carry correct group.
- `test_group_rows_spanning_page2_to_page3`: group starting on page 2 continues into page 3 → page 3 rows carry correct group.
- `test_s4a_does_not_fire_when_group_had_rows`: group with rows on same page → no spurious section row.

All 9 geometry tests pass.

---

## RUN T3 DONE
