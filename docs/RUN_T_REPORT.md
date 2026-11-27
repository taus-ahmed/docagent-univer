# Run T report — extraction and Organized quality (fix/review-fixes)

Rules kept: causes, not documents (literal scan `tests/test_engine_generality.py`
green after every engine commit); synthetic tests first, in two or more
vocabularies with negative twins; no live model call; not deployed.

**Evidence actually available.** `local_docs/batch4/` holds only job 138's
export — **jobs 140-150 are not there** (the `job_14x` files in Downloads
are June/July, an older numbering). Stored answers: `local_docs/raw` jobs
40-134 (carson 56/95, mammoth 46/94/100, fidelity 67/129, vendor list
72/131; **neobank and oregon invoice have no stored answer**, so they were
checked on the Organized layout only). Halves: `corpus_metrics.half_of`
(hash of the file name); rules developed on dev; the vendor list (named by
the prompt) is the one report-half file looked at.

## Before / after, both halves

Regular = the replayed stored answers (`tools/corpus_metrics.py`, t0 at
07ec0de -> t2 at the final code). Organized = every text-layer PDF of
`DocAgent_testdocs` laid out by the old and the new code
(`tools/run_t_metrics.py`, the "before" run in a worktree of 07ec0de).

| metric | layer | dev before → after | report before → after |
|---|---|---:|---:|
| false Lows | Regular | 255 → 254 | 88 → 46 |
| printed amounts missing | Regular | 274 → 274 | 415 → 415 |
| printed amounts missing (rule 17 audit) | Organized | 0 → 0 | 0 → 0 |
| wrong values at high confidence | Regular | 2 → 2 | 18 → 18 |
| rows split wrongly (tail lines as rows) | Organized | 18 → 10 | 23 → 10 |
| rows split wrongly (dateless rows in dated tables) | Regular | 3 → 3 | 0 → 0 |
| column-order errors (see caveat) | Organized | 13 → 229 | 301 → 252 |
| glued cells (2+ figures in one cell) | Organized | 141 → 33 | 425 → 127 |
| lost leading zeros | Organized | 11 → 0 | 17 → 0 |
| lost leading zeros | Regular export | 0 → 0 | 0 → 0 |

Read with care:
* **False Lows** fall where the cause was a grounding failure marking a
  whole row (flowparse_bank_us 49 → 9, calif photo 12 → 10). Low cells
  total 876 → 750; 81 no-template cells moved Low → amber (machine-read
  origin, still owed a look).
* **Missing amounts and wrong-at-high do not move on replay**: no stored
  answer changes, and a new column / recovery needs a live call. An early
  run showed wrong-at-high 18 → 9; that was the column RENAME hiding values
  from the answer key, not a better value — corpus_metrics now scores a
  renamed result under the key's names (`_as_keyed`), and it is 18 → 18.
* **Column-order errors are a noisy instrument.** It compares each value's
  sheet header with the nearest digit-free heading line printed above the
  value. Remaining hits checked by hand are dominated by titles taken as
  headings ("INVESTMENT REPORT", "VENDOR INVOICE LIST"), headers written
  over several rows (fiserv, checked: values sit under their own columns)
  and OCR-garbled layers (isu, pitt W-2). The count rose on dev mainly
  because splitting glued cells creates ~700 more single-figure cells to
  check. Verified directly: carson pages 2-6 now sit under page 1's
  Debits/Credits/Balance; the vendor list's 11 headings each over their own
  values. Not verified: long_digital_25pg's later card section (its heading
  is not detected as a table; those rows stay free layout).
* Regular trailing minus / leading zeros: the corpus answers hold no
  trailing-minus amount and no zero-padded value the old writer lost; both
  rules rest on the synthetic tests (Excel itself shows `26.08-`).

## Items

| # | cause | change | commit |
|---|---|---|---|
| 1 | spacing failed "found as quoted"; one failed cell made the row Low | spacing-free match (4+ chars, token boundaries); a grounding failure is Low on its own cell; a row is Low only when none of its values grounded | 2d5b9fa |
| 2 | a tail line answered/laid out as a row | Regular: a dateless, amountless row on the line directly below, starting right of the row's first word, joins it (`attached_tail_count`); Organized: same rule on the page | 51e0d1c, 1b9cc91 |
| 3 | side-by-side groups interleaved line by line | Regular: group order (each top to bottom, then left to right), sorted when every group is; Organized: one header, band-major | 0b50bce, 1b9cc91 |
| 4 | stacked headings unknown | `text_layer.stacked_headings`; Regular swaps a record's two sub-field values back by line; inference names the pairs (only when present); Organized: two sub-field columns, two-line records; a wrapped heading is not stacked | fb55dba, b13bcc8, 325d02d |
| 5 | printed amount columns dropped silently | `<table>[columns not in template]` flag + `unasked_columns`, only when the row holds none of the column's figures | 24c13c7, 325d02d |
| 6 | a computed total was Low | new level `derived` (sixth word): equals the sum of a column of its rows, `field_provenance.derived`; printed totals and failed sums unaffected | 7bd8643 |
| 7 | trailing minus displayed leading | `#,##0.00;#,##0.00-`, verified in Excel; Organized keeps it numeric and trailing | 0d32b5b, 1b9cc91 |
| 8 | "0025" → 25 (Organized), mixed columns | identifiers by shape and heading stay text; a column with a zero-padded value is text throughout; P.O. is an identifier heading | 0d32b5b, 1b9cc91 |
| 9 | group line glued into the INVOICE column | identifier + name in two cells left of the table; label lines stay pairs | 1b9cc91 |
| 10 | segments split by the gutter only | columns from the data rows' alleys; heading words to their columns; furniture; widgets; every Label: pair; glued word+figure; money in any currency; heading lines above; continued tables keep columns | 1b9cc91, b13bcc8, 5f8b837 |
| 11 | 400 logged without a cause | status, API status/reason, one-word cause, model, pages, schema size, retries, fallback, recovered; schemas over 28 field slots not sent (all 11 stored refusals had 31-50, every accepted ≤ 26) | 44d51fb |
| owner | no-template invented header names | a column takes the heading the page prints over its values, only when unambiguous; unheaded columns and unprinted field labels marked inferred (amber, comment) | 03c23f9, d147c00 |

The owner rename was measured before it was trusted: its first version
renamed row labels, section titles and group columns on 5 stored answers
(saltlake "Description" → "Accidental Death Dismembmnt", tcnj "Amount" →
"Retained Earnings"). It now needs a confirmed heading line, one phrase
over the values that is not a group heading, a repeated sub-heading, a
wrapped half or a title. Remaining renames on the corpus: vendor list
(Invoice Number → INVOICE, Invoice Date → INV DATE), fidelity
(Symbol/Security Name → Security Name).

## Checks

| check | result |
|---|---|
| synthetic Run T tests | 11 files, all green |
| harness templated / no-template | 98.7% / 98.2%, 17/17 both, invented 0, misfiled 0, defect 0.0% |
| full suite (final code) | **5787 passed, 0 failed**, 19 xfailed (an earlier run on mid-run code found 28 failures: a stacked-heading false positive that changed a gold prompt, and an over-eager unasked-column flag - both fixed) |
| frontend type-check | clean (`derived` status added to `lib/review.ts`) |

## Not done / not verified

* No live run: the model's answers to the stacked-heading hint, to an
  unsent large schema, and anything needing recovery are unmeasured.
* Organized is still off by default; the owner has not approved it as the
  default for no-template text PDFs.
* A heading printed on several lines is laid out as several header rows;
  group headings spanning sub-columns sit over the first sub-column.
