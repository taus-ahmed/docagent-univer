PHASE 2 DONE

Phase 2 (replay of real answers, jobs 40-84): see docs/RUN_Q_PHASE2_FINDINGS.md. Fixed causes 1, 2, 4 (f40e025, 0f5e7cf, 5e78732); replay Low 1062 -> 422.


# Run Q progress — fix/review-fixes

Read this first on a restart; skip items marked done.

## Start
- [x] merged origin/review/run-n (helper already patches `llm_contract.setting("PAGE_RECOVERY_MAX_CALLS")`; all 7 strict xfails fail on their defect assertion under --runxfail)
- [x] baseline suite: no failures

## Items
- [x] Q0 raw-response export / replay / live corpus tools + real-or-reconstructed test mode (tools/export_raw_responses.py, tools/replay_raw.py, tools/live_corpus.py + manifest, tests/run_q_support.py, tests/test_q0_replay_tools.py)
- [x] Q1 lost pages — (a) cause of job 72 was a document split, fixed (footer page number veto); recovery is not template-gated; (b) printed row counts reconciled; (c) N6 partial capped pages named
- [x] Q2 side-by-side column groups — grouped headings named in prompt + recovery, missing records flagged, daily balances left out with a note, other-account rows flagged
- [x] Q3 no-math checks — label arithmetic (SSA Box 5), qty x price, fuel gallons x price, PO family; restaurant receipt checks already existed and fired
- [x] Q4 false-low — N2 x2, N4; outlined-text pages unverified not Low; multi-word headings + between-neighbours placement; spaceless quotes; group line above a row (601 -> 528 Low in the export re-score)
- [x] Q5 blank noise / blank forms — label-only quotes are not misses; blank form READY with note; parity cause reproduced
- [x] Q6 placeholder policy
- [ ] Q7 wrong-slot / row-mix / invented (N5 done)
- [ ] Q8 OCR layer and images
- [x] Q9 missing-silent — N7; a total label's own-line figure is evidence even when placed elsewhere (job 58)
- [ ] Q10 spaces and text format
- [ ] Q11 ignored form / wrong template
- [x] Q12 no fail reason / smartsheet_mileage (5e053fd; outlined-page guard on the blank shortcut added in Q4)
- [ ] Q13 bulk accept
- [ ] Q14 batch 1 leftovers
- [x] Q15 tools/audit_exports.py (before numbers in RUN_Q_REPORT.md)
- [x] UI1 new extraction (POST /api/jobs/{id}/rerun + button; grid uses the job's template)
- [x] UI2 notifications
- [ ] UI3 friendlier results page
- [ ] FINISH
