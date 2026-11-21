# Run Q report — fix/review-fixes

## Start

- Merged `origin/review/run-n` (3a0857a). Its helper already patches the
  real cap lookup, `llm_contract.setting("PAGE_RECOVERY_MAX_CALLS", 4)`
  (`slot_extractor.py:650`); there is no `Settings` attribute of that name.
  All 7 strict xfails fail under `--runxfail` on the assertion describing the
  defect (`'high' == 'low'`, `'low' == 'high'`, `'ambig' not in …`, `1 == 2` ×2,
  `'page 3' in ''`, `'rev c' not in …`), with no setup errors.
- Baseline suite: no failures, xfails only.

## Q0 — raw-response replay

- The raw answer is `document_results.raw_llm_response`, written in
  `services/job_worker.py` from `result.extraction_response.raw_text` and
  purged after `RAW_RESPONSE_RETENTION_DAYS` (default 7) by
  `core/raw_retention.py`. **Only the first slot call's answer is kept**:
  page-recovery calls, page chunks of a heavy document and template inference
  are not stored. Replay answers inference from the stored
  `inferred_template` and fails (counts, prints) every other call it has no
  answer for, so a replayed document that needed recovery says it was not
  recovered. It does not pretend.
- `tools/export_raw_responses.py <ids>`: `DATABASE_URL` from the
  environment only, never printed (errors print the exception class only),
  SELECT-only inside `SET TRANSACTION READ ONLY` on PostgreSQL. It writes
  `local_docs/raw/<id>/{job,template}.json` and `docs/<doc_id>.json`.
- `tools/replay_raw.py <ids>` runs `extractor.run_extraction` with the
  stored answer and the real writers, writing `local_docs/replay_out/`.
- `tools/live_corpus.py`: offline plan by default; `--live` needs
  `GEMINI_API_KEY`; caps at 60 calls and $1. A capped call FAILS and is never
  silently empty. It covers the 29 jobs 56–84 listed in
  `tools/live_corpus_manifest.json`; 68–70 are smartsheet_mileage. **Not run.**
- Test mode: `tests/run_q_support.py`. Each Run Q reproduction is named
  `…_reconstructed` (a mock rebuilt from the export) and has a `…_real` twin
  that reads `local_docs/raw/<job>` and skips with a reason when it is absent.

## Q15 — before scoreboard (`tools/audit_exports.py`)

`tools/audit_exports.py local_docs/rounds local_docs/batch1_exports`, at the
start of Run Q (exports as produced by the staging build):

```
file                                    low    amber     grey accepted placehol money_te  legend sum count
job_56_results.xlsx                       0        0        0       82        0        0       0   1     0
job_57_results.xlsx                       0        0        0       14        0        0       0   0     0
job_58_results.xlsx                       0        0        0        1        0        9       0   1     0
job_59_results.xlsx                       0        0        0       15        0        0       0   0     0
job_60_results.xlsx                     139       10        0        0        0        0       0   1     0
job_61_results.xlsx                       0        0        0        0        0        0       0   0     0
job_62_results.xlsx                       4       67        8        0        0        0       0   0     0
job_63_results.xlsx                       0        0        0        1        0        0       0   0     0
job_64_results.xlsx                       0        0        0       50        2        0       0   0     0
job_65_results.xlsx                       0        6        0        0        0        0       0   0     0
job_66_results.xlsx                       0        0        0       97        0        0       0   1     0
job_67_results.xlsx                      40        3       29        0        1        0       2   0     0
job_71_results.xlsx                      12        9        0       25        0        0       0   0     0
job_72_results.xlsx                     293      132        0      141        0        0       0   0     1
job_73_results.xlsx                      93        0        0        0        1        0       0   0     0
job_74_results.xlsx                       1        0        0        0        2        0       0   0     0
job_75_results.xlsx                      14        0        0        0        3        0       0   0     0
job_76_results.xlsx                       0        0        1        0        0        0       0   0     0
job_77_results.xlsx                       0        0        0        0        0        0       0   0     0
job_78_results.xlsx                       2        0        6        0        0        0       0   0     0
job_79_results.xlsx                       6        0       26        0        4        0       0   0     0
job_80_results.xlsx                       0        0        0        0        0        0       0   0     0
job_81_results.xlsx                       1        0       21        0        0        0       0   0     0
job_82_results.xlsx                      19        0        0        0        0        0       0   0     0
job_83_results.xlsx                      20        0        0        0        0        0       0   0     0
job_84_results.xlsx                     104        0        0        0        1        0       0   0     0
job_40_results.xlsx                       0        0        0        7        0        0       0   1     0
job_41_results.xlsx                       0        0        0        0        0        0       0   0     0
job_42_results.xlsx                       0        0        0        2        0        0       0   0     0
job_43_results.xlsx                       0        0        0        0        0        0       0   0     0
job_44_results.xlsx                       0        0        0        0        0        0       0   0     0
job_45_results.xlsx                       0        0        0        0        0        0       0   0     0
job_46_results.xlsx                      28        0        0        0        0        0       1   0     0
job_47_results.xlsx                       0        0        0        0        0        0       0   1     0
job_48_results.xlsx                       5        0        0        0        0        0       1   0     0
job_49_results.xlsx                       0        0        0        0        0        0       0   0     0
job_50_results.xlsx                       0        0        0        3        0        0       0   0     0
job_51_results.xlsx                       1        0        0        0        0        0       1   0     0
job_52_results.xlsx                       0        0        0        0        0        0       0   0     0
job_53_results.xlsx                       0        0        0       11        0        0       0   0     0
job_54_results.xlsx                       0        0        0       11        0        0       0   0     0
job_55_results.xlsx                       0        0        0        0        0        0       0   0     0
TOTAL (42 files)                        782      227       91      460       14        9       5   6     1
```

Columns: red/amber/grey cells; values accepted after a Low flag;
placeholder text left as a value; money stored as text; Legend counts that
disagree with the marks; Total rows that disagree with the sum of the rows
above (heuristic); printed counts that disagree with the table (heuristic).
Two findings are real and need nothing more than the tool: job 67's Legend
says Low 31 but 40 cells are red, and job 72's "Total Invoices Count 90"
sits against a 22-row table. The sum/count columns are heuristics. A
statement's "Total Deposits" is not the sum of the summary lines above it,
so read them as pointers, not verdicts.

