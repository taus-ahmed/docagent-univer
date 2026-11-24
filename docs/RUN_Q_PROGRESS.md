PHASE 3 DONE

Phase 3 (UI1 rework, Q8, Q7, Q11, Q10, Q4 e-g, UI3, replay answer key): see the Phase 3 section of docs/RUN_Q_PHASE2_FINDINGS.md. Commits 60eff8e..162452f (162452f fixes the one full-suite regression, an amount in words). Answer key 24 documents / 1,055 values: 819 right, 3 wrong, 233 missing (229 are recovery rows replay cannot produce) before and after; replay Low 413 -> 381 over items 2-6.

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
- [x] Q4 false-low — (e)-(g) in Phase 3, e0ba07e; N2 x2, N4; outlined-text pages unverified not Low; multi-word headings + between-neighbours placement; spaceless quotes; group line above a row (601 -> 528 Low in the export re-score)
- [x] Q5 blank noise / blank forms — label-only quotes are not misses; blank form READY with note; parity cause reproduced
- [x] Q6 placeholder policy
- [x] Q7 wrong-slot / row-mix / invented (N5 done; Phase 3: rows drawn as outlines checked against the printed records, 02284e9)
- [x] Q8 OCR layer and images (Phase 3, 535be92: figure letters flagged, embedded layer pinned, one page item for an outlined page; a scan's thin OCR reading still open)
- [x] Q9 missing-silent — N7; a total label's own-line figure is evidence even when placed elsewhere (job 58)
- [x] Q10 spaces and text format (Phase 3, bc7b903, from wip/run-q-q10)
- [x] Q11 ignored form / wrong template (Phase 3, 1478c54)
- [x] Q12 no fail reason / smartsheet_mileage (5e053fd; outlined-page guard on the blank shortcut added in Q4)
- [ ] Q13 bulk accept
- [ ] Q14 batch 1 leftovers
- [x] Q15 tools/audit_exports.py (before numbers in RUN_Q_REPORT.md)
- [x] UI1 new extraction (grid uses the job's template; Phase 3 rework 60eff8e: a fresh page from the top action bar, no inline re-run)
- [x] UI2 notifications
- [x] UI3 friendlier results page (Phase 3, 276843b)
- [ ] FINISH
