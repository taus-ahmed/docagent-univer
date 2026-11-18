# Strict acceptance xfails

Every item below is marked `xfail(strict=True)`. A Run A implementation that makes one pass will produce an XPASS failure until the marker is removed. Do not weaken the assertion.

| Run A section | Tests | Parametrized cases | Waiting for |
| --- | --- | ---: | --- |
| A2 | `test_answer_contract.py`, `test_retry_contract.py` | 18 | Typed unusable-answer outcomes, bounded injectable retries, and section-only MAX_TOKENS recovery |
| A3 | `test_completeness_review_edits.py`, `test_input_lanes.py` | 8 | AcroForm text-widget evidence, OCR/page ledger states, image attachment, and partial-page survival |
| A4 | `test_completeness_review_edits.py`, `test_input_lanes.py`, `test_scoreboard.py` | 7 | Source inventory, evidence-aware empty flags, per-page completeness, and the zero-silent-defect recorded gate |
| A5 | `test_completeness_review_edits.py` | 5 | Explicit reason dispositions, review gating, persistent edits, and visible save failures |
| A6 | `test_export_contract.py` | 4 | Compact bands, three-row document separation, clean default columns, and draft marking |

The count is the number pytest collects after parameter expansion. Existing OCR outcome xfails tied to Tesseract below 5.4 remain separately documented in `tests/harness/tesseract_gate.py`.
