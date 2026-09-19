# Synthetic Check Corpus (v2)

Generated programmatically for OCR/MICR pipeline testing. NOT real client
documents. See OCR-HANDOFF.md Section 7 -- results here are informative,
not a substitute for real client data.

- 18 checks, 5 distinct visual templates (A-E)
- 3 tiers per check: clean (.png), moderate (.jpg), hard (.jpg)
- Routing numbers pass real ABA checksum math EXCEPT ids 009 and 016,
  which are deliberately invalid (see intentional_invalid_checksum_test_case)
- Amount numeral vs. written-words MATCH except ids 007 and 014, which are
  deliberately mismatched (see intentional_mismatch_test_case)
- Ground truth: one JSON per check + _index.json with all records

**Tracked fixture.** Committed to git and read by `tests/test_micr.py`
(`_index.json` is the single source of truth for the 18 records) and by the
harness scripts `tests/harness/ocr_checks.py` and `ocr_feasibility.py`.
