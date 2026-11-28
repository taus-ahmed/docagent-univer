# Run T3 progress log

Worktree: fix/review-fixes. Flags stay OFF. No live calls.

| stage | commit | status |
|---|---|---|
| create progress log | — | ✅ |
| 1 thinking | 43434ba | ✅ impl done, tests green |
| 2 cost | 43434ba | ✅ impl done, tests green |
| 3 plan validation | 43434ba | ✅ impl done |
| 4 geometry | 43434ba | ✅ S4a trailing group header + S4b stacked rows; tests green |
| 5 row count | 43434ba | ✅ measured: 90 text-layer rows = 90 engine rows (page 3: 12) |
| 6 reading order | 43434ba | ✅ order_pairs/order_violations metric added to position_check.py |
| 7 flat forms | 43434ba | ✅ STRUCTURE_READ_FLAT_FORMS flag; has_flat_form_boxes + form_regions(flat_form=True); tests green |
| 8 report | 43434ba | ✅ docs/RUN_T3_REPORT.md |

## Notes

- S5 measurement: `mobile_vendor_list_8pg.pdf` — text layer has exactly 90 invoice
  rows across all 8 pages (page 1: 13, 2: 15, 3: 12, 4: 14, 5: 14, 6: 12, 7: 10, 8: 0).
  Engine returned 90 rows.  Row count is correct.
- S6 adds `order_pairs` and `order_violations` to `score()` in `position_check.py`;
  `order%` column in the summary table = `100*(1 - violations/pairs)`.
- S7 flat forms: flag is `STRUCTURE_READ_FLAT_FORMS=False` (default off); when on,
  `structure_geometry.proposal()` calls `form_regions(page, flat_form=True)` for pages
  without widget values that have drawn boxes enclosing ≥4 text words.
  `_infer_flat_origins` assigns synthetic label/value origins by font size (smaller =
  label) with a y-position fallback.
