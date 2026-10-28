# Progress

## Review-3 fixes

Codex reviewed `3343071` (integration/ocr-hardening) and returned REVISE.
One commit per item, each with a regression test that fails before the fix.

- **F1 word-order amounts** — `cheque_amounts.parse_words_amount` read
  "fifty cents one dollar" as 50.01. The subunit must now close the amount:
  a main-unit word after the subunit word, two subunit words, a number on
  both sides of the subunit word, or number words after a `/100` fraction
  give `unit_order` (unreadable, flagged). `tests/test_amount_unit_order.py`
  enumerates all 24 orders of number/unit/number/subunit for every main-unit
  and subunit word the parser knows and reads each by role.
- **F2 export precision** — `coerce_cell_value` turned the shared parser's
  Decimal into a float, so 123456789012345.67 exported as ...345.7.
  `excel_cells.excel_number` gives the float only when the value has at most
  15 significant digits (where a double round-trips to exactly the printed
  decimal); beyond that the printed text is written and `precision_flag`
  puts a comment on the cell, kept ahead of the provenance comment. The
  charts sheet uses the same rule for its totals. The flat, combined and
  per-file writers already wrote text and are pinned unrounded.
  `tests/test_export_precision.py` runs every writer.
- **F3 legacy export** — the layout, table, form, mixed and table-rows
  fallback writers each stripped `$`/`,` and called float(), so an ambiguous
  "1,234" became a number. Every number write now goes through
  `excel_cells.put_extracted` → `coerce_cell_value` (the shared parser with
  the document's own hint): ambiguous amounts and identifiers stay text,
  long numbers stay text and are flagged, numbers carry the printed notation
  as a number format. The mixed writer's "only amount labels become numbers"
  rule is kept (`numeric=False` otherwise). `_document_hint_of` moved to
  `excel_cells.document_hint_of` (excel_slot keeps the name).
- **F4 declared rules and category regexes** — (a) `(a+)+$` hung the worker:
  Python's `re` holds the GIL, so no thread timeout can stop it. New
  `engine/safe_regex.py` admits a pattern only from a safe subset (no varying
  quantifier or alternation inside a repeated group, no backreference, ≤3
  open-ended quantifiers, ≤300 chars), caps the input at 512 chars and gives
  each rule a 2 s budget; refused/over-budget is `rule_unreadable` with the
  reason. Category regexes use the same subset; a refused one is never run
  and is named in the row's note. (b) `tolerance`/`min`/`max` must be finite
  numbers; tolerance 0–1000. (c) each rule runs in its own try: one that
  raises is UNREADABLE (review), the others still run; `rules_of` keeps
  malformed entries so they are reported. `tests/test_rules_safety.py` runs
  the catastrophic cases in a subprocess with a timeout.
- **F5 save-time rule validation** — `rule_problems` ran only in the shape
  preview. `templates.template_rule_problems` now checks a grid's declared
  `rules` (against the slots its own shape yields) and its `categories`
  (`categorize.validate_rules`), and `POST /api/templates` and
  `PUT /api/templates/{id}` (when the grid changes) refuse with 422
  `template_rules_invalid` (in the detail and an `X-Error-Code` header)
  before anything is written. Those are the only routes that write a
  template: Duplicate and "save this inferred template" post to create.
  Not covered: a firm YAML's `categories` (schema upload) — refused patterns
  there are still never run (F4) and are named on each row.
  `tests/http/test_template_rules_on_save.py`.
- **F6 identifier registries** — a GSTIN starting `50` passed (state code
  tested as 01-99). Now GSTN's list: 01-38, 97, 99 (`GST_STATE_CODES`).
  The same class of gap in the other plug-ins: IBAN accepted any country
  outside the registry on mod 97 alone (now refused; 18 newer registry
  countries added to the length table); GB/XI VAT accepted GD500-999 and
  HA000-499 (now the issued halves only). Already closed: EU VAT prefixes,
  PAN entity letter, SWIFT country, EIN prefixes. Deliberately format-only:
  IFSC bank code (the RBI list changes monthly; a stale copy refuses real
  banks) and UAE TRN (no published checksum or ranges).
  `tests/test_identifier_registries.py`.
- **F7 summary names** — only RUNS of 2+ capitalised words were checked, so
  "Alice approved the payment" passed with empty facts. `verify_narrative`
  now checks every word that is capitalised (any cased script), an acronym,
  or in a caseless script (Devanagari, CJK, Arabic): it must be in the facts
  as a whole word, or start a sentence and be on a closed list of common
  summary words, or be the month/weekday of a date the facts hold.
  Possessives are stripped, hyphenated names checked part by part, and a
  check that raises fails closed. `tests/test_summary_names.py`.
- **F8 ENVIRONMENT normalisation** — `Production` / ` production ` passed the
  strict checks (which normalised a private copy) while `is_production` and
  HSTS compared the raw string. A field validator now strips, lower-cases and
  expands `dev`/`prod` once and stores the result; every check reads it.
  Unknown values refuse to start; unset/empty is development locally and
  refuses on a hosting platform (Railway/Render/Fly/Heroku/Cloud Run
  markers). `hide_input_in_errors=True`: a start-up error no longer echoes
  the settings input (pydantic appended a truncated dump of it — the old
  "never echoed" test passed only by truncation). Fixed
  `tests/test_config_aliases.py` to restore `app.config.settings` after its
  reload (order-dependence the new HSTS test exposed).
  **Deploy check:** confirm Railway sets `ENVIRONMENT` explicitly.
  `tests/test_environment_normalisation.py`.
- **F9 readiness exit** — `_bounded` used a ThreadPoolExecutor, whose
  workers are joined at interpreter exit, so a check hung on a dependency
  kept the process alive after the probe had timed out (measured: the
  before-fix subprocess never exited; killed at 30 s). Checks now run on a
  daemon thread; a check whose previous probe is still stuck answers
  `fail:busy` instead of stacking another thread. `tests/test_readiness_exit.py`.
- **F10 frontend PDF passwords** — passwords were a map keyed by file NAME,
  apart from the file list: removing a file kept its password and re-adding
  the same name restored it. `frontend/lib/uploadFiles.ts` gives every listed
  file an id and its own password; removing the entry removes the password,
  a re-added file starts empty, and all passwords are wiped when the upload
  request is made, on cancel and on reset (React state only — gone on
  navigation). Confirmed by a source check in the test: no
  localStorage/sessionStorage/router/history/URL use on any password line;
  the field keeps `autoComplete="off"` (plus password-manager ignore
  attributes and a per-entry `name`). `frontend/lib/uploadFiles.test.ts`
  (in `npm test`).
