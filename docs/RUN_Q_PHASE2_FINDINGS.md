# Run Q Phase 2 — findings from the real model answers

Source: the stored model answers in `local_docs/raw/<job>/` (jobs 40–84),
replayed through the current post-model pipeline by `tools/replay_raw.py`
(no model call, no key). The workbooks are in `local_docs/replay_out/<job>/`.
Jobs 68, 69 and 70 (smartsheet_mileage) have no stored answer and were not
replayed.

## What replay cannot do

Only the first slot call's answer is stored. Every later call (page recovery,
page chunks) has no answer, and replay counts it as failed, by name:

| job | file | calls with no stored answer |
|---|---|---:|
| 56 | carson_bank_6pg.pdf | 20 |
| 73 | fiserv_merchant_5pg.pdf | 10 |
| 46, 48 (×2), 51, 67, 84 | … | 4 each |
| 50, 54, 60, 74, 76, 78, 79, 81, 83 | … | 2 each |

A replayed document that needed recovery therefore shows fewer rows than
staging did. Rows missing for this reason are not counted below as a defect.

## Before / after per job (`tools/audit_exports.py`)

Before = the staging exports (`local_docs/rounds`, `local_docs/batch1_exports`).
After = the replay with the code at the start of Phase 2 (7bcea0d).

**Read the before column with care.** Several staging exports show 0 red cells
because a person accepted them (they show as `accepted` in the audit tool): job
66 had 97 accepted cells and replays as 97 Low, job 64 50 and 50, job 57 14 and
14, job 59 15 and 15. Accepted cells are not re-accepted on replay.

| job | low | amber | grey | placeholder | legend off | sum off | count off |
|---|---|---|---|---|---|---|---|
| 40 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 1→1 | 0→0 |
| 41–44 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| 45 | 0→0 | 0→4 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| 46 | 28→0 | 0→0 | 0→2 | 0→0 | 1→0 | 0→0 | 0→0 |
| 47 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 1→1 | 0→0 |
| 48 | 5→12 | 0→1 | 0→4 | 0→0 | 1→0 | 0→0 | 0→0 |
| 49 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| 50 | 0→6 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| 51 | 1→7 | 0→0 | 0→2 | 0→0 | 1→0 | 0→0 | 0→0 |
| 52, 53, 55 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| 54 | 0→0 | 0→0 | 0→1 | 0→0 | 0→0 | 0→0 | 0→0 |
| 56 | 0→1 | 0→0 | 0→0 | 0→0 | 0→0 | 1→1 | 0→0 |
| 57 | 0→14 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| 58 | 0→1 | 0→74 | 0→1 | 0→0 | 0→1 | 1→1 | 0→0 |
| 59 | 0→15 | 0→0 | 0→1 | 0→0 | 0→0 | 0→0 | 0→0 |
| 60 | 139→140 | 10→9 | 0→4 | 0→0 | 0→0 | 1→1 | 0→0 |
| 61 | 0→0 | 0→6 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| 62 | 4→4 | 67→67 | 8→1 | 0→0 | 0→0 | 0→0 | 0→0 |
| 63 | 0→2 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| 64 | 0→50 | 0→0 | 0→8 | 2→0 | 0→0 | 0→0 | 0→0 |
| 65 | 0→0 | 6→6 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| 66 | 0→97 | 0→0 | 0→0 | 0→0 | 0→0 | 1→1 | 0→0 |
| 67 | 40→43 | 3→1 | 29→30 | 1→1 | 2→2 | 0→0 | 0→0 |
| 68–70 | not replayed (no stored answer) | | | | | | |
| 71 | 12→42 | 9→54 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| 72 | 293→193 | 132→0 | 0→0 | 0→0 | 0→0 | 0→0 | 1→1 |
| 73 | 93→390 | 0→0 | 0→1 | 1→0 | 0→0 | 0→0 | 0→0 |
| 74 | 1→1 | 0→0 | 0→1 | 2→0 | 0→0 | 0→0 | 0→0 |
| 75 | 14→11 | 0→0 | 0→0 | 3→0 | 0→0 | 0→0 | 0→0 |
| 76 | 0→0 | 0→0 | 1→1 | 0→0 | 0→0 | 0→0 | 0→0 |
| 77, 80 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| 78 | 2→2 | 0→0 | 6→1 | 0→0 | 0→0 | 0→0 | 0→0 |
| 79 | 6→6 | 0→0 | 26→9 | 4→0 | 0→0 | 0→0 | 0→0 |
| 81 | 1→0 | 0→0 | 21→4 | 0→0 | 0→0 | 0→0 | 0→0 |
| 82 | 19→6 | 0→13 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| 83 | 20→6 | 0→13 | 0→4 | 0→0 | 0→0 | 0→0 | 0→0 |
| 84 | 104→13 | 0→0 | 0→6 | 1→1 | 0→0 | 0→0 | 0→0 |
| **total** | **782→1062** | **227→248** | **91→81** | **14→2** | | | |

Money stored as text is 9→9 (all job 58).

Job 73 rose from 93 to 390 Low. Staging stored the answers of 10 later calls
and the replay has none of them, so the replay keeps a different set of rows.
Its new Low cells come almost entirely from causes 1 and 2 below.

## Flagged cells by cause, ranked by count

Counted from the review comment on every red, amber and grey cell in the
replayed workbooks. Each cause was traced to its rule on the real page
geometry. A table row carries one row-level verdict, so one failed cell marks
every cell of its row. That is why a handful of rows makes hundreds of cells.

| # | cause | cells | jobs | kind |
|---|---|---:|---|---|
| 1 | **A long identifier is read as a phone number.** `_PHONE` has no digit boundaries, so any run of 10+ digits contains a "phone number". `_single_datum` then calls the cell "more than one piece of information". Batch `702000000803` (12 digits), invoice `08632520260515` (14) and `980104801-062326` are each one datum. | ~322 Low | 73 (33 rows: 297), 72 (2 rows: 25) | engine defect |
| 2 | **A repeated value's later copy skips the between-neighbours test.** `check_placement` looks at later copies of a value only for flush or overlap, not for the Q4 "between the neighbouring headings" rule. Job 73: `0.00` is printed under Chargebacks, Adjustments and Fees. The Fees copy (440–457) lies between `Fees` (417–437) and `Amount Processed` (471), but the first `0.00` is the one judged. Job 72: P.O. `26003221` is also glued into the invoice word `26003221AlexSysourat`. The real copy (125–158) sits between `P.O.` and `INV DATE`. | ~220 Low | 72 (10 rows: 131), 73 (11+ rows: ~90) | engine defect |
| 3 | **The scan's OCR reading is too thin to check against.** Tesseract read 106 words of the saltlake pay stub's scan page. The answer's lines are not in it, so they are "not found" and Low. The receipt photos (job 71) are the same. | 182 Low, 63 amber | 60 (140), 71 (42) | OCR reader (Q8) |
| 4 | **A value read from a picture on a native page.** The OU check stub prints the stub itself as an image (40% of page 1) on a page that has native text. The page is `native` and gets no OCR, because selective OCR needs a cover of at least 0.99. Every value is checked against a text layer that never held it, so all are "not found" and Low. | 97 Low | 66 | engine defect |
| 5 | **Undecided document boundary** ("May contain more than one document"). On tcnj_financials, page 2 is a second income statement ("Product" after "Service") with no reference to compare, so the flag is correct. | 75 amber, 45 Low, 22 grey | 58, 67 | correct, as designed |
| 6 | **A background panel is read as a redaction bar.** Fidelity pages 1–3 each draw two dark rectangles, each about 380×270 pt and just under half the page. About 500 printed words sit on them. `marks.native_bars` blanks every value "beneath" them. | 42 Low, 30 grey | 67 | engine defect |
| 7 | **Embedded OCR layer** (pre-OCR'd page, amber by design) | 79 amber, 4 Low | 62, 61, 65 | as designed |
| 8 | **Partly outlined page.** virtus_1099b draws its sample table as 788 glyph outlines next to 1,790 real characters. That is below the whole-page outlined rule (more paths than characters), so its values are Low, not unverified. | 65 Low | 64, 59 | engine gap |
| 9 | Grey: "Nothing was extracted, and something says a value was expected" | 51 grey | 79, 64, 84, 48, 60, 81 … | mixed: partly recovery calls with no stored answer |
| 10 | Placement in fidelity's two-column summary (`This Period` / `Year-to-Date`) | 37 Low | 67 | not traced |
| 11 | Ambiguous number format | 27 amber, 1 Low | 58 | as designed |
| 12 | Outlined text (ADP W-2) | 26 amber, 12 Low | 82, 83 | as designed (Q4) |
| — | small: payslip/receipt arithmetic (9), day/month swap (6), invoice check unreadable (4), currency decimals (2) | 21 | | as designed |

### Wrong or missing values

- **Answer key** (`local_docs/answers_extra.csv`, 13 values over 23 job
  documents). The replay has 22 of 23 correct. The one miss (job 44, "Recipient
  Address") holds `12 W Pine Street, Anytown, US 10000`, the street plus its
  city line, where the key has the street alone.
- **Missing rows on replay** come from the recovery calls that have no stored
  answer (table above). That is a replay limit, not a code cause.
- No other ground truth exists for jobs 40–84, so wrong values cannot be
  counted beyond the flags.

## Fixes chosen

These are the three largest **engine** causes: 1, 2 and 4. Cause 3 is larger
than cause 4, but it is the OCR reader's quality (Q8: psm 6 reads 312 words
of the same page against psm 3's 106, and still misses the table). Changing
the reader is outside this phase's scope, which allows no other items.

(Results are recorded below.)
