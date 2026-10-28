# UI changes on integration/ocr-hardening

Each defect fixed in the UI, with its commit and the test that pins it.
Frontend unit tests run with `npm test` (`node --test lib/*.test.ts`). The
browser specs in `frontend/e2e/` run against `scripts/e2e/stack.py`, which uses
the stub model and a throwaway SQLite database (`scripts/e2e/README.md`).

## Template editor
| Defect | Commit | Test |
|---|---|---|
| The grid listened on the whole window. Enter on Save moved the selection, typing anywhere edited a cell, keys reached the grid behind a dialog, and Tab threw focus out of the editor | 1e62af3 | `lib/gridKeys.test.ts` |
| Typing right after Tab dropped characters (`Total` became `Ttal`). A fast Tab or Enter after an edit landed on the page body | eae15ac | `e2e/template-editor.spec.cjs` |
| The unsaved-changes baseline was the sheet's first report, not the loaded grid | eae15ac | `lib/templateForm.test.ts` |
| No field-level errors, and no guard on leaving with unsaved edits. Templates had no Duplicate, delete did not name its target, and the cards were not keyboard-openable | cf915a3 | `lib/templateForm.test.ts` |
| Saving in the editor silently dropped the template's declared `rules` | a3ec020 | `lib/review.test.ts`; `tests/http/test_template_rules_on_save.py` (b8aa3be) |

## Extract page
| Defect | Commit | Test |
|---|---|---|
| The page-selection dialog for a multi-page PDF never appeared. A cleanup had deleted `POST /api/extract/page-count`, and the page swallowed the 404 | 8bc59b4 | `tests/http/test_page_count_route.py`, `e2e/creation-flow.spec.cjs` |
| A PDF password was keyed by file name. Removing a file kept its password, and re-adding the name restored it | 465a0ce | `lib/uploadFiles.test.ts` |
| The option cards had long, low-contrast text, and the "available after extraction" list described old behaviour | b205e0e | `e2e/sweep.spec.cjs` |
| Template rows and source tabs were clickable divs that a keyboard could not reach | b205e0e | `e2e/sweep.spec.cjs` |
| The Charts panel parsed numbers in the browser and summed across currencies | 9af3723 | `lib/charts.test.ts`, `tests/test_charts.py` |
| Option cards were not real checkboxes (no Space or Tab), and choices were not remembered | 68fe79b | `lib/options.test.ts`, `e2e/options.spec.cjs` |

## History, review and session
| Defect | Commit | Test |
|---|---|---|
| A reload or deep link logged the user out, because it redirected before the stored token was read. `?next=` now accepts only same-site paths | 3f683e6 | `lib/session-gate.test.ts` |
| Job cards were clickable divs that a keyboard could not reach | b205e0e | `e2e/sweep.spec.cjs` |
| The review screen could not be reached after the upload session ended | b5d4573 | `lib/review.test.ts` |
| Values needing review were not marked in the grid, and downloads gave no warning | b028a14 | `lib/review.test.ts` |
| Review link and engine path broken under uvicorn | 5a3a730 | none committed; found by an end-to-end run, now covered by `e2e/demo-acceptance.spec.cjs` |
| Delete data was admin-only, so a job's own user could not delete it. The request did not send `?confirm=true` | 139bc77 | `lib/permissions.test.ts` |
| A one-time password was not enforced in the UI | 139bc77 | `e2e/sweep.spec.cjs` (forced change) |
| A 429 page-limit refusal showed a generic error, not the server's message | 139bc77 | none (no unit test for `apiErrorText`) |
| The folder-path placeholder named a local user | a4ee4c9 | `scripts/prepush_check.py` personal-path scan |

## Whole flow
`e2e/demo-acceptance.spec.cjs` (92156b6) covers the whole flow:
1. sign in, draw a template, upload a two-invoice file with every option on
2. the file splits into two documents
3. edit a value, mark the document reviewed, export
4. firm B gets 404 for the job, its export and its listing

The `docs/screenshots/` captures are from the stub-provider run and contain
synthetic data only.

The PearX demo's UI (`frontend/lib/demo-error.ts`, the demo branch of
`app/extract/page.tsx`) is unchanged from origin/main apart from the options panel above.
