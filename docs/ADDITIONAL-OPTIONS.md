# Additional options

Run after extraction, on the extracted data; none changes a value or its
level. Each card states what it does and costs (`frontend/lib/options.ts`).

| Option | id | AI calls |
|---|---|---|
| Categorization | `categorize` | none for rule matches; at most one per table for the rest |
| Charts & graphs | `graphs` | none |
| Summary | `summary` | none |
| Written summary (AI) | `narrative` | one per document, counted toward the firm's month |
| Anomaly detection | `anomaly` | none |

## Categorization — `engine/categorize.py` (3eac5e7)
Rules first, in order: the template's rules, then the firm's (`categories:` in
its YAML), then generic defaults. Rules are whole-word keywords or regex.
- One category matches: `grounded`, recording the rule and the words that matched.
- Several match: `Uncategorized` with `category_uncertain`. It never guesses.
- None match: the model is asked, for those rows only. Its answer counts only
  if it names a listed category, and it is marked `unverified`. If the model is
  down, the result says so.
- Stored in `ed['categories']`, never written into a row; review values with
  the same statuses; a marked `Categories` export sheet; editor rules box.
- A category rule's regex must be in the safe subset (`engine/safe_regex.py`).

Tests: `tests/test_categorize.py`, `frontend/lib/categoryRules.test.ts`.

## Anomaly detection — `engine/anomalies.py` (67e13b7)
No model. Each finding carries its rule, the rows, the numbers and a severity:
exact/near duplicates; outliers by median/MAD within one rule-assigned
category (≥ 8 values, never across a mixed column); round-number clusters
(≥ 40% of ≥ 8 amounts); weekend and out-of-period dates; sequence gaps and
repeats; non-positive amounts in a positive column; failed totals (from the
validators); currency mix.

Limits: at most 50 findings (`CAP`), sorted. The findings are informational
only and change no level. They are counted in the job's review summary, listed
per document, and given an `Anomalies` export sheet.

Tests: `tests/test_anomalies.py`. Clean fixtures produce no findings.

## Summary and Written summary — `engine/summary.py` (427c830, c41185b)
Summary: facts (counts, totals per table and per currency, never mixed, the
date range, top items, categories) and a plain summary built only from those facts.
Written summary (needs Summary; the card says so while it is disabled):
a model writes prose from the facts; `verify_narrative` rejects any number,
date or name-like word not in the facts, and rejected prose is discarded with
a notice in favour of the data-built summary. Labelled "generated, verify
against the data"; never a value. Prompts and answers are never logged.

Config: `OPTION_MAX_CALLS_PER_JOB` (default 20). Each call counts as a page
toward `TENANT_MONTHLY_PAGE_LIMIT` (`_grant_option_call`).

Tests: `tests/test_summary.py`, `tests/test_summary_names.py`,
`tests/http/test_option_call_cap.py`, `tests/http/test_logs_carry_no_content.py`.

## Charts — `engine/charts.py` (9af3723)
Spend by category, by month, the largest items and the distribution.
- Sums are `Decimal` per currency (unstated is `unstated`, never assumed);
  ambiguous amounts are left out and counted; too little data gives a message.
- Served by `GET /api/jobs/{id}/charts` (job access, and in the all-routes
  isolation test). The response includes how many values still need review,
  which the panel shows as a banner.
- The page draws plain SVG with no chart library. The old panel parsed numbers
  in the browser and summed across currencies.
- The export gets a `Charts` sheet with native charts per currency when the job
  asked for graphs. `graphs` is now sent to the server.

Tests: `tests/test_charts.py`, `frontend/lib/charts.test.ts`.

## Panel and demo (68fe79b, b205e0e)
- Cards are labels around real checkboxes (Space/Tab, `aria-describedby`);
  choices remembered per user in the browser, storage failures tolerated.
- Turning Summary off also drops Written summary.
- Demo tenants are refused all five options on the server
  (`DEMO_BLOCKED_OPTIONS`). `narrative` was added to that list, so the demo
  behaves as before.

Tests: `frontend/lib/options.test.ts`, `frontend/e2e/options.spec.cjs`,
`tests/http/test_demo_options_and_history.py`.
