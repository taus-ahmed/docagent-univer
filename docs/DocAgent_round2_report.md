# DocAgent — Test Round 2 Defect Report

Twelve extractions across four documents. Structured by trigger condition, not by document — the test files are stand-ins for common real-world layouts.

**Important caveat.** No code changed at any point during this round. Where a defect appears on one input and not another, that is not evidence of a fix. It is evidence that the second input does not trigger it. Nothing below is marked "resolved." The engine is deterministic per input — the same file and template produce the same output — so a defect absent from a new document simply means that document doesn't hit the condition.

---

## Runs

| # | Template | Document(s) | Declared? |
|---|---|---|---|
| 1 | B1 — earnings table, 5 col | Berkshire | No |
| 2 | B2 — operating earnings, 5 col | Berkshire | No |
| 3 | B1 + B3 composite (table + key-value) | Berkshire | No |
| 4 | E1 — bill header, key-value | ENGIE | No |
| 5 | E2 — balance summary, key-value | ENGIE | No |
| 6 | E3 — itemised charges, 2 col | ENGIE | No |
| 7 | BR6 — payoffs table, 2 col + total | H25E | No |
| 8 | BR1 — four-quadrant settlement, 2 bands | H25B | No |
| 9 | BR4 — absent-field probe, key-value | ENGIE | No |
| 10 | BR2 — cross-document comparison, 4 col | H25B + H25E | Declared |
| 11 | BR3 — decomposition, 4 col | ENGIE | Declared |
| 12 | BR5 — multi-page transactions, 3 col | BoA | Declared |

---

## I1 — Template semantics are not used to select a region

**The finding of the round.** A template describes a shape. The engine matches that shape against the document and binds *every* region that matches, then concatenates them.

**Observed in:** runs 1, 2, 3, 4, 5, 6, 10, 11 — eight of twelve.
**Not observed in:** 7, 8 (both single-page with one candidate region), 9 (partially — see note), 12.

Five distinct manifestations:

**(a) Second region appended below the first.** Runs 1–6, 11. Berkshire's page 1 and page 2 tables merged in both directions. ENGIE's page 4 glossary appended to the page 3 charges table. ENGIE's page 4 header block appended to the page 1 header block.

**(b) The template's header row is re-emitted above the appended block.** Runs 6, 11. Output contains `Charge Description | Amount` twice, as if it were data.

**(c) Column headers with semantic meaning are ignored; columns bind positionally.** Run 10. Headers read `Loan Estimate` / `Closing Disclosure` / `Variance`. No loan estimate was uploaded, yet column B received values — Borrower-Paid At Closing figures from the closing disclosure. Column D (`Variance`) received raw source amounts rather than differences. B, C and D were bound to source columns 1, 2 and 3 by position.

**(d) Multiple uploaded documents concatenate as rows, not columns.** Run 10. H25B occupies rows 2–46; a repeated header sits at row 49; H25E occupies rows 50–83. The comparison the template described is not attempted.

**(e) Bound regions need not be comparable.** Run 6 bound a prose glossary (`Meter Constant - A fixed value which is used when...`) to a charges template. Run 4 bound a meter-summary header to a bill header. Shape similarity is loose enough that a column of text qualifies.

**Pattern worth noting.** Every confirmed merge involved regions on *different pages*. Run 7 had a shape-compatible table directly below the target on the same page and did not merge it. Run 8 had four candidate tables on one page and bound them to four separate quadrants correctly. This suggests page-level discrimination exists somewhere and is not applied across page boundaries — a narrower target than a general rewrite.

**Changes:**
- Weight header text and label text in region selection, not just column count and shape
- Constrain a declared band to one source region unless the user explicitly asks for repeats
- When multiple candidates match, surface the choice rather than merging silently
- Multi-document uploads need an explicit mode: one sheet per document, or documents mapped to columns

---

## I2 — No provenance reaches the output

Every merged block arrives with no indication of where it came from. In run 10 there is no way to tell which block is which document without already knowing the source. In run 6 the glossary rows look like charge lines.

**Change (small, high value).** An optional source column carrying page number and document name. This alone converts I1 from silent corruption into visible extra data that a user can filter out.

---

## I3 — Band expansion (accepted, not a defect)

Declared row counts are advisory; a band grows to fit the table it matched and pushes downstream regions down. Run 3 expanded a 5-row band to 16 and relocated the key-value block from rows 7–11 to 18–22 with all values intact.

This is correct behaviour — a user drawing a template cannot know a table's row count in advance, and truncating would be worse.

**Change (small).** Note in the output or UI that a band expanded and by how much, so a user who laid out a multi-region sheet knows the layout shifted.

---

## I4 — Structurally distinct rows dropped, inconsistently

Rows that don't match the dominant pattern in a band are handled three different ways:

| Case | Behaviour | Run |
|---|---|---|
| Section total row | Value kept, **label dropped** | 8 (rows 2, 20 — `K. Due from Borrower at Closing` etc. blank) |
| Label-only sub-header | Row dropped entirely | 1, 2, 3 (`Net earnings includes:`) |
| Subtotal rows | **Present** with a 2-column template, **absent** with a 4-column template on the same page | 6 vs 11 |

That last row is the important one: same document, same source page, two templates, different row sets. Which rows survive depends on template shape.

**Change.** Emit every row inside the band. Leave value cells empty rather than dropping the row. A user can delete a row they don't want; they cannot recover one they never saw.

---

## I5 — Label boundary and contamination errors

Labels are assembled rather than quoted, and the assembly has several failure modes:

- **Prefix from an adjacent region.** `Oncor Customer Charge` where the source label is `Customer Charge` — `Oncor` comes from a sidebar callout. Runs 6 and 11, identical both times.
- **Label mirrored into a region that lacks it.** Run 8, `Adjustments` written into the seller quadrant where the source has no such sub-header.
- **Boundary placed inside the value.** Round 1: `01` + `0.25 %` → `01.25 %`, changing a mortgage points rate five-fold. Production: `EIN: 47-38`.
- **Prefix retention inconsistent within one file.** Run 10 block 1 strips section letters and line numbers (`Origination Charges`); block 2 keeps them (`A. Origination Charges`, `01 .5 % of Loan Amount (Points)`). Same run, same document type.

**Change.** Treat labels the same as values: a verbatim span from the source with its own quote and location. Assembled labels are how contamination gets in.

---

## I6 — Value formatting is document-dependent and internally inconsistent

Working correctly:

- Parenthesised negatives preserved — `(804)`, `(175)` (runs 1–3)
- Leading zeros preserved — `0000123456`, `0000000` (runs 4, 9)
- Ten-digit values intact — `2,157,034,121` (runs 1–3)

Not working:

- **Currency handling varies by document.** Preserved in Berkshire (`$19,694`); stripped in run 10 (`1802`, `405`, `29.8`).
- **One field, two formats, one file.** Run 10 stores `Aggregate Adjustment` as text twice: `- 0.01` in block 1, `– $0.01` in block 2.
- **Precision loss.** Run 11 rounds Unit Rate to two decimals. `$0.04116` → `$0.04`. Four rates collapse to `$0.00` (`$0.001374`, `$0.00033`, `$0.000282`, `$0.000127`). Needs checking whether this is cell format or the stored value — if stored, the data is gone.
- **Intermittent space injection.** Run 1 produced `$ 19,6 94`, `2,157,034,1 21`, `$ 9 . 13`, confined to the first value column. Runs 2 and 3, same document, clean.
- **Dotted leaders.** Retained in run 1 (`BNSF ....................`), stripped in runs 2 and 3.

**Change.** Store the source string verbatim alongside a parsed numeric in a separate field. Never round. Let the export decide presentation. This also fixes the grounding divergence noted below.

---

## I7 — Text-layer ordering artifacts pass through as values, and self-validate

Run 4 produced `Bill Account Number = 00000000112538645596`. Run 9 reproduced it **exactly**.

ENGIE page 4 stacks two account numbers vertically:

```
0000123456
0000158659
```

Interleaved character by character, these produce the observed string. This is a text-flattening artifact — two vertically stacked strings read across rather than down — not model invention.

**Why it matters more than a parsing bug.** By the time grounding runs, the artifact string genuinely exists in the extracted text. So it validates. Any corruption introduced by the flattener is self-validating, because the flattened text is what validation compares against.

**Change.** Validate against positional extraction (word boxes with coordinates), not against the flattened string. At minimum, flag values assembled from spans that are not horizontally contiguous.

---

## I8 — Values from the wrong source field validate as correct

Three instances, all real strings, all wrong:

- `Billing Period = Aug 12 / Sep 11` — exists on page 4 under `Reading Dates Previous/Current`. Meter reading dates, not the billing period. Runs 4 and 9.
- `Meter Number = 0123456789AB` — correct field, but returned inside a block that should not exist. Run 9.
- `Total withdrawals = -65.00` — exists in the BoA document attached to a Derry Diner transaction. Presented as a total. Run 12.

**Change.** Grounding must carry the quote's location and its nearest source label, not just confirm the string exists somewhere in the document.

---

## I9 — Column assignment cannot be verified (carried from round 1)

Run 10 demonstrates it plainly: values placed into columns B, C and D by source position, under headers meaning something entirely different, with nothing in the pipeline able to flag it.

The grounding layer confirms *value existence*. It cannot confirm *value placement*. In a multi-column financial table, which column an amount sits in is most of its meaning.

**Change.** Same root as I7 — this needs positional evidence carried through validation. It is the one item on this list that is a design question rather than a bug.

---

## I10 — Degraded text layers produce small, confident, self-consistent wrong answers

Run 12, BoA. The document contains roughly 130 date-stamped transaction lines across layered annotation overlays. The output has **two**.

Every extracted string exists in the source — `05/10/13`, `Overdraft`, `Safety`, `- 35.00`, `-- 30.00`, `-65.00`. But the pairings were assembled from fragments lines apart. `Safety Deposit Box` as a phrase does not appear anywhere; `Safety` and `Deposit` occur separately.

The dangerous part: `-35.00 + -30.00 = -65.00`. The output reconciles. A reviewer checking the arithmetic passes it, and 128 rows are missing with no signal.

**Change.** A coverage indicator — rows emitted versus candidate rows detected on the page — surfaced to the user. And a warning when the text layer shows heavy positional overlap, which is detectable before extraction runs.

---

## I11 — Non-atomic prose returned as a field value

Run 9: `Contract End Date = the last day of October 2020`. A sentence fragment, and semantically wrong — the source states the contract expires on the meter read date *following* the last day of October.

**Change.** For fields whose label implies a scalar (date, amount, number, ID), either return a parsed value or return nothing. A prose fragment in a date field is worse than an empty cell.

---

## I12 — Region emitted twice with no values

Run 5: the four balance-summary labels re-emitted at rows 7–10 with empty value cells. A variant of I1 where the second binding found no data.

---

## I13 — Column widths not auto-fitted

Recurs in most runs, including on user-supplied label text. Cosmetic, no data loss, but it makes every output look broken on first open.

**Change (small).** Auto-fit on export, always.

---

## I14 — Template formatting lost on export (carried from round 1)

Merged cells, centring and borders present in the editor are absent from the exported file.

---

## Behaviour that is correct — protect under regression

Any fix touching region binding or row classification will move through this logic. Each of these deserves a regression test first.

| Behaviour | Evidence |
|---|---|
| **No fabrication for genuinely absent fields** | Run 9: four fields absent from the document all returned empty, including `Customer Tax ID` where the document contains `Fed. I.D. 76-0685946` as a tempting near-match. This is the strongest single result of the round |
| Single-region pages bind cleanly | Runs 7, 8 — no merge, correct totals, correct empties |
| Four tables on one page bind to four separate quadrants | Run 8, ~30 values correct across K/L/M/N including repeated values on both sides |
| Grouped tables with multiple subtotals inside one band | Runs 6, 8 |
| Ambiguous label/amount ordering resolved correctly | Run 6 — source prints two labels then two amounts; both paired correctly |
| Decomposition of one source string into four fields | Run 11 — usage, rate and amount split out, with empties where the source has none |
| Legitimately duplicated rows repeated, not deduplicated | Runs 1–3 — same row label twice with identical values, both returned |
| Two-level column header flattened to four columns | Runs 1–3 |
| Semantic label matching across wording differences | `Applicants` → `Borrower`; `Full 2023` → `Full Year 2023` |
| Blank numbered source lines stay empty | Runs 7, 8 |
| Multi-line address joined correctly | Run 4 |
| Free-form prose fields with no labels in source | Run 3 — release date, company, ticker, contact, phone, all correct |
| Deterministic per input | Same file and template reproduce the same output, including reproducing defects exactly |

---

## Small changes worth making regardless

1. Auto-fit columns on export.
2. Optional source column: document name and page number per row.
3. Warn when a band expands beyond its declared size, and by how much.
4. Warn when more than one region matched a template band.
5. Never round extracted numerics; keep the source string.
6. Emit every row inside a band, with empty value cells, rather than dropping non-conforming rows.
7. Preserve template merge, centring and borders on export.
8. Surface per-cell confidence in the UI — it is already computed and would have flagged several of the above.

---

## Priority

1. **I1** — region selection ignores template semantics. Every other correctness issue in this round is downstream of it.
2. **I7 / I9** — grounding validates against flattened text, so flattening artifacts and column misplacement are both invisible to it. Design question, not a bug fix.
3. **I10** — silent under-extraction on degraded inputs. Needs a coverage signal before real documents arrive.
4. **I4 / I5** — row dropping and label assembly. Contained, mechanical.
5. Everything else.

---

## Recommended next run

Re-run the round 1 five-column cost table template against H25B, unchanged. It is the only way to convert "not observed this round" into an actual before/after on the biggest claim in the earlier report.
