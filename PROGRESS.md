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
