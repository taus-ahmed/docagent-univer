# Run Q progress — fix/review-fixes

Read this first on a restart; skip items marked done.

## Start
- [x] merged origin/review/run-n (helper already patches `llm_contract.setting("PAGE_RECOVERY_MAX_CALLS")`; all 7 strict xfails fail on their defect assertion under --runxfail)
- [x] baseline suite: no failures

## Items
- [x] Q0 raw-response export / replay / live corpus tools + real-or-reconstructed test mode (tools/export_raw_responses.py, tools/replay_raw.py, tools/live_corpus.py + manifest, tests/run_q_support.py, tests/test_q0_replay_tools.py)
- [ ] Q1 lost pages
- [ ] Q2 side-by-side column groups
- [ ] Q3 no-math checks
- [ ] Q4 false-low
- [ ] Q5 blank noise / blank forms
- [ ] Q6 placeholder policy
- [ ] Q7 wrong-slot / row-mix / invented
- [ ] Q8 OCR layer and images
- [ ] Q9 missing-silent
- [ ] Q10 spaces and text format
- [ ] Q11 ignored form / wrong template
- [ ] Q12 no fail reason / smartsheet_mileage
- [ ] Q13 bulk accept
- [ ] Q14 batch 1 leftovers
- [ ] Q15 tools/audit_exports.py
- [ ] UI1 new extraction
- [ ] UI2 notifications
- [ ] UI3 friendlier results page
- [ ] FINISH
