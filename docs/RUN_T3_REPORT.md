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

**Tests.** `tests/test_geometry_bugs.py` — 6 tests: trailing group header emitted,
data row still present, 2-baseline line splits into 2, each has date/amount, single-
baseline line not split, non-row-line baselines not split.

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

## Open items

- Flat form accuracy on the two IRS fixtures (irs6744_w2_mcguire,
  irs6744_1099NEC_1099K_garcia) is not yet measured with `STRUCTURE_READ_FLAT_FORMS=True`
  — the flag is off by default and the accuracy harness does not set it.  This is a
  "first pass plumbing" stage; a follow-up run with the flag on is needed to validate
  the inference heuristic against the answer keys.
- `group_cur` is reset to `None` after emitting the trailing group row (S4a), but the
  case where a vendor's rows continue onto the NEXT page (the group header appears but
  zero rows are on this page, all rows are on the next) is not yet handled — that
  document needs page-continuation logic, which is tracked in the existing multi-page
  continuation work.

---

## RUN T3 DONE
