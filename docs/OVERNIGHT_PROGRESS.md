# Overnight run — progress (branch fix/review-fixes, started at cd2dbd4)

A restarted session reads this first and skips every item marked [x] or BLOCKED.

- [ ] CI1 — ci/backend "Backend tests" step fails on CI only
- [ ] A1 — wrong-slot and duplicate values (job 42 Remit To Bank; job 51 Box 11 / Box 13)
- [ ] A2 — repeated Box 14 entries never placed in another table's band
- [ ] A3 — identifiers are text; control number spacing; money always 2 decimals
- [ ] A4 — lost page recovery (mammoth page 2)
- [ ] A5 — silent empty slot (form title printed on the page)
- [ ] A6 — consistency (combined vs single parity; fragment rows; temperature 0)
- [ ] GATE A — full suite, harness, scoreboard, frontend
- [ ] B1 — grounding Low only when quote AND value both missing (normalised)
- [ ] B2 — "different column" decided by the value's own position
- [ ] B3 — no false completeness reasons on blank form boxes
- [ ] B4 — Legend counts equal marked cells
- [ ] GATE B
- [ ] C — merge origin/review/run-f; fix 13 strict xfails; restore _on_page
- [ ] GATE C
- [ ] D1 — three Run E strict xfails
- [ ] D2 — D13 warning-inventory test asserts content
- [ ] D3 — stale T9 ambiguity text
- [ ] GATE D
- [ ] E1 — review edits revert
- [ ] E2 — multi-page navigation in the review dialog
- [ ] GATE E
- [ ] M1 — no -latest candidates; GEMINI_MODEL_FALLBACKS; 404 fails visibly
- [ ] M2 — store modelVersion in model_used; Legend + job detail
- [ ] M3 — migration doc, per-model settings, tools/model_matrix.py
- [ ] H1 — audit log
- [ ] H2 — token revocation
- [ ] H3 — password policy
- [ ] H4 — raw response retention + log redaction
- [ ] FINISH — final checks, KNOWN_FAILING, TEMPLATE_RULES, OVERNIGHT_REPORT, push
