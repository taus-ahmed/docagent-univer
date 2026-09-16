# Decision log — phases 1–7, the template-editor decision, and
# what the defect analysis got wrong

The architectural decisions behind the current extraction engine, and the
reasoning that produced them. Until now this existed only in chat transcripts.

Each entry states what was chosen, what was rejected, and why. Where a decision
cost something, the cost is recorded with it — a decision log that only lists
wins is a marketing document.

Numbers quoted are from the live harness at commit `80fbf76`
(`--mode live --repeat 3`, cache bypassed): **templated 97.9% extraction /
97.9% export / 49.2% raw**, **no-template 86.5% / 86.5% / 77.8%**.

---

## 1. Slot-directed extraction, not extract-then-place

*Phase 1 · `0feb483` · `backend/engine/slot_extractor.py`*

We chose to enumerate the template's cells as addressed slots, ask the model to
fill each one by its address, and write every answer at the address it was
requested for. We rejected the previous design — extract a bag of values from
the document, then match those values into template cells afterwards — and with
it every heuristic that matching required: fuzzy label association, positional
fallbacks, section inference at write time. The reason is that the matching step
was itself the source of the four largest defect classes we were seeing, and no
amount of improving it could remove them: values landing in the wrong cell,
cells silently left empty because nothing matched them, one value written to two
places, and a section total being indistinguishable from a line item. Under slot
addressing those are not bugs to fix but states that cannot be represented — the
answer goes where it was asked for, every slot is asked about so `""` is an
answer rather than an absence, a slot is asked once and holds one value, and the
total has a different address from the line items and is asked for separately.
The measurable effect was accuracy moving from 45.5% to the high nineties over
phases 1–2, but the durable argument is the structural one: we deleted a category
of failure instead of reducing its frequency.

## 2. Grounding as a hard requirement, not a scoring bonus

*Phase 1 · `0feb483`, `aadba4c` · `verify_span`, `confidence_for`*

We chose to require every filled slot to return the value **and** the verbatim
span it was read from **and** the page, then verify that span against document
text read independently with pdfplumber — a value whose span cannot be located is
kept but marked low confidence and flagged, never presented as fact. We rejected
treating the model's own confidence as signal, and we rejected a stricter variant
of our own rule that would have required the value to be the whole span or set
off within it by a delimiter. The requirement exists because "the model was
confident" and "the text is in the document" are different claims, and only the
second is checkable; making it mandatory is what lets us say 0 values *absent
from the PDF* across 376 templated cells rather than merely believing it. The stricter variant was
tried and rejected on evidence: it was meant to catch a value truncated at a line
break, but it demoted 250 correct cells to reach 98.4% precision — worse than the
99.5% without it — because a correct value read off a line is structurally
identical to a truncated one and nothing in the span distinguishes them. We also
accepted, rather than hid, the limit this leaves: grounding proves text came from
the document, not that it belongs in that slot, which is why no-template mode can
report 415 high-confidence cells of which 90 are misfilings.

**Correction (2026-09-15).** "0 inventions" was repeated elsewhere as though
no invented value could reach a sheet. That is not a property of the system.
It covers a string that appears nowhere in the PDF. It does not cover a real
string from elsewhere on the page written into a field the document leaves
blank, and nothing checks for that. Round 2 run 9 answered `Customer Email
Address` with the supplier's `care@engieresources.com` at `high`. Given three
plausible wrong answers for the same bill's absent fields — `Customer Tax ID`
← `Fed. I.D. 76-0685946`, `Late Fee Amount` ← the previous balance, `Deposit
Amount` ← the payment received — the pipeline wrote all three at `high`, none
of them flagged. When absent fields came back empty, the model declined to fill
them; no code check would have caught it if it had not.

## 3. The arithmetic router, not sixteen English keywords

*Phase 2b · `ee07798` · `template_shape.choose_path`*

We chose to route a template by counting: how many columns does this template
need, and can the chosen path physically serve that many. Capacity is read off
each path's own output format rather than guessed — the layout path serves
exactly two columns because its prompt emits `{label_col, value_col}` and nothing
else, while the field and slot paths key cells by column name and have no
ceiling. We rejected `_VALUE_KW`, a sixteen-word list (`amount`, `amt`, `value`,
`total`, `balance`, `price`, …) matched against the user's own column headings to
decide what kind of template it was. That list silently misrouted any template
whose value column was headed `2024`, `USD`, `Q4`, a currency symbol, a
non-English word, or nothing at all — and misrouting was not a degradation but a
hard ceiling, because a five-column invoice sent to the two-column layout path
could not represent its line items however well the model read the document. This
was the single highest-value change in the project: 62.7% → 86.5% overall, with
`EXP-2024-0081` moving 7.4% → 81.5% and both invoices gaining more than 66 points,
and zero regressions. The general lesson we took from it: a router should ask a
question with an arithmetic answer, not pattern-match the user's vocabulary.

## 4. One pipeline, not three engines behind a flag

*Phase 2d · `2533afc` · `backend/engine/extractor.py`*

We chose a single path — template → shape → slot extraction — with no-template
documents taking the identical path from an inferred grid, and we deleted 2,524
lines: the `USE_NEW_EXTRACTOR` flag, the legacy inline pipeline in `extract.py`,
the layout/field/CBM extraction routes, the three-layer engine, and
`compute_binding_map` along with the keyword list 2b had already stopped
consulting. We rejected keeping the old engines behind a flag as insurance. The
reason is that the flag was not insurance, it was a hiding place: it was
implemented as a bare `except Exception` that caught **any** engine error —
including a bug introduced minutes earlier — logged one line to stdout, and
silently completed the request on a different engine producing a differently
shaped result and therefore a different spreadsheet, with nothing recording which
engine had run. A fallback that changes the output without saying so is worse
than a failure, because the failure is at least visible. We also deleted
`_understand_template`, which made a synchronous Gemini call of up to ~300 s
inside a template-save HTTP request. The harness was unchanged at 97.9% with zero
diff entries, which is the point: this removed code nothing could reach.

## 5. Declared shape, supplementing detection rather than replacing it

*Phase 7 · `520f5bc`, `2b769e4` · `template_shape._declared_bands`*

We chose to let a template declare its own tables — the user selects the region
as they see it, heading line included, and says which way the records run — and
to have `compute_shape` read declarations before falling back to detection on
everything undeclared. We rejected two alternatives. Replacing detection outright
was rejected because all nineteen production templates rely on it and declare
nothing, so removal would have converted one silent wrong answer into a hard
failure for every existing user; the full migration is written up separately in
`TEMPLATE-SHAPE-FUTURE-WORK.md` as deliberate future work rather than a side
effect. Extending the detector to cover the failing shapes was rejected on
evidence: a rule treating a gapped label row as a section header was written and
reverted because it cannot be distinguished from an ordinary two-up key/value row
and broke four other production templates when tried. The underlying reason is
that detection can only describe one shape — headings across a row with empty
rows beneath — and a transposed table has no empty rows beneath anything, so it
is not detected badly but read as unrelated single fields, with no error and no
signal. That is the same failure class as the sixteen-word router: a narrow rule
applied to a shape it cannot express, failing silently. Declaration retired the
`BS Luq` xfail and made transposed templates work at parity with upright ones
(94.6% both ways on the same document and the same gold).

## 6. Adapter widenings: elimination survived, preference did not

*Phases 2–4 · `cc8428d`, `5f6d9d9`, `7f82dcb` · `tests/harness/adapter.py`*

We chose to keep every mapping rule looser than "the names are the same" behind a
named switch and to report the ADAPTED and RAW numbers side by side in every run,
so a figure that depends on mapping leniency is visible as such — that gap is
currently 97.9% vs 49.2% templated, and we publish both. Four widenings survive:
`W1_fuzzy_names` (exact, then *unambiguous* substring or token overlap),
`W4_kv_rows_as_fields`, `E_elimination`, and `W2_table_by_content`, which is ON
for no-template only. Three were rejected and deleted — identify a table by its
row content, map leftover columns by position, and "if gold names one table,
anything unmatched is it" — because each expressed a *preference* with degrees of
freedom (W3 had as many as there were columns), and a scorer that prefers is a
scorer that flatters. They were replaced by elimination, which fires only when the
correspondence is *forced*: exactly one unmatched candidate on each side, zero
degrees of freedom, otherwise it does not fire. Templated accuracy was identical
at 97.9% under the strict rule, which is the evidence that the loose rules were
buying nothing there. W2 was restored for no-template alone because inference can
legitimately describe a balance sheet as three tables where the labels name five,
and no counting rule can pair three with five — that is a structural difference,
not leniency, and identifying a table only decides which gold row a value is
compared against; a wrong value still scores wrong. **This decision cost us
something and the cost is still outstanding:** `BS-2024-Q1` no-template went 73.9%
→ 23.9% when elimination replaced the three rules, the restore of W2 was honestly
noted at the time as changing nothing in practice (prompt work had made that
document return zero tables, so there was no predicted table to identify), and it
sits at **15.2% today**. We took a correct methodological decision and did not
follow through on the regression it exposed.

## 7. Gold labels record what the page prints

*Phase 1 · `e13c8ba` · `tests/gold/README.md`*

We chose to build gold labels independently of the engine — read from each PDF
with pdfplumber and cross-checked arithmetically (line items sum to their totals,
debits and credits reconcile to the closing balance, net pay equals earnings
minus deductions) — and to never regenerate them from engine output; when the
engine's output schema changes, the adapter changes instead. The governing rule
is **P0: gold is the value as printed, in that field's own region of the page**,
with `null` meaning the document genuinely has nothing there, which is what makes
hallucination measurable at all. We rejected labelling by interpretation, and the
six ambiguous cases were decided by the repo owner rather than by us: a `Less:`
contra line printed positive stays **positive** (P1) because inferring sign from
the prefix is an accounting transform, not a reading task — even though the
printed totals only reconcile if you subtract it — while accounting parentheses
are recorded **negative** (P2) because parentheses *are* explicit negative
notation; a name field printing `Janet Wu – VP Operations` keeps the full string
(P3) while a signature block printing `Janet Wu` alone does not, because the
documents differ; an identifier takes its human-facing form over the MICR serial
(P5); and print-security decoration is kept because it is on the page (P6). The
reason for deciding these explicitly and writing them down is that a wrong label
is worse than a missing one — it makes a correct extraction look like a defect
and sends work in the wrong direction — and the reason they were the owner's call
rather than ours is that they are product judgements, not engineering ones. An
extraction returning the other candidate in each case scores `near`, not `wrong`,
and `near` is reported separately, so these choices move numbers between columns
but never hide a disagreement.

---

## 8. Keep the hand-written spreadsheet, fix its data model

**Decided 2026-09-03. Reversing conditions are at the end of this section — read
them before reopening the question.**

The template editor, `DocAgentSpreadsheet.tsx`, is 844 hand-written lines. It had
three defects its author named: `applyStyle` materialising cells (so drawing a
border was what made a template extractable), merges writing a shape nothing
read, and no real undo. The question was whether to replace it with an
established grid rather than keep maintaining a spreadsheet.

**The arithmetic decided it.** Eight defects were reported from an hour of real
use. Traced to their mechanism, **two** live in the component — styling creating
slots, and the merged heading. The other six live in `compute_shape`'s field-slot
scan, its band-end rule, its region guard, `TemplateEditor.saveMutation`, and the
extract page's failure panel. **Every one of those six survives a component swap
unchanged.** Swapping buys 2 of 8 and costs a rewrite of the two things no
library provides: the region-declaration UI and the slot-highlight overlay.

### What the licences actually say (verified 2026-09-03, not from memory)

| | Licence | Usable in a commercial SaaS |
|---|---|---|
| **Univer** | Apache-2.0. Verified on disk: `@univerjs/core`, `/sheets`, `/sheets-ui` LICENSE files. Pro (commercial) adds collaboration, import/export, printing, charts, pivot tables, server-side calc — none of which we need. Merges are in the OSS package (`AddWorksheetMergeCommand`). | Yes |
| **Handsontable** | **Not open source.** v18.1.0 ships `SEE LICENSE IN LICENSE.txt`. The free key is `non-commercial-and-evaluation` only; their terms bar the production stage for anything "connected with your commercial activity". | **No** — disqualified |
| **AG Grid** | `ag-grid-community` is MIT, **but Cell Selection (range selection) is Enterprise-only** — the docs page carries `enterprise: true` and needs `CellSelectionModule` from `ag-grid-enterprise`. No spreadsheet merge model. | Community insufficient |
| **Luckysheet** | MIT, **archived 2025-10-30**. Its own README: "no longer maintained… use the upgraded version of Univer". Last npm release 2021-01-19. | Dead |
| **FortuneSheet** | MIT, clean. v1.0.4 (2025-11-06). Value and style are flattened into one object and `mc` (merge) is written into the cell *and* duplicated in `config.merge` — two sources of truth, the mistake we are removing. | Yes, but repeats our defect |
| **x-spreadsheet** | MIT. Last release 2021-05-20. | Dead |
| **RevoGrid** | MIT core, very active — **but cell merge and column span are Pro-only** (`@revolist/revogrid-pro`). | Open-core where we need it |
| **ReactGrid** | MIT community, PRO commercial. | Open-core |
| **Jspreadsheet CE** | Repo LICENSE is MIT, but published v5.0.4 declares **no `license` field at all**. Would need written confirmation. | Unclear |
| **Glide Data Grid** | MIT, but `latest` is 6.0.3 from 2024-02-03 — alphas only since. Row-object model, not a template editor. | Stale |
| react-datasheet-grid | MIT, active. Column-typed; no merges, no per-cell styling. | Capability fails |

Only **Univer** and **FortuneSheet** are permissively licensed, maintained, and
actually spreadsheets. Univer is the better of the two: `ICellData` keeps `s`
(style) in a separate field from `v` (value), `mergeData: IRange[]` lives on the
worksheet rather than on cells, and `getLastRowWithContent()` is first-class — so
it would solve the styling-creates-slots defect structurally rather than by rule.

**It still lost**, on cost against benefit: ~1.35 MB gzipped (measured across the
ESM entry points a sheets-core preset loads) versus 12 KB for what we ship, and
its plugin architecture registers by side effect so that is a floor. This repo
had already integrated Univer 0.21 and FortuneSheet and backed both out
(`666170c`), which required 18 `transpilePackages` entries and a webpack
`NormalModuleReplacementPlugin` for `opentype.js`. Re-adopting would put that
between us and a harness reading 98.5%, for no accuracy gain.

The three named defects were each bounded work in code we own: R1 made presence
meaningless so `applyStyle` materialising is harmless (`baeedcd`); merges moved
to the range list `SheetSaveData.merges` already had, deleting a second source of
truth rather than adding one; and undo became a snapshot of all four state slices
instead of one (`c4b0143`). The dead packages were deleted in `cd5c398`.

### What would reverse this

Two conditions, both pointing at Univer:

1. **In-browser `.xlsx` import**, so a user can upload an existing spreadsheet as
   a template. This is the one requirement our component cannot reach — it is a
   multi-month build. Note it is in Univer **Pro**, not the Apache-2.0 core, so
   it carries a licence cost as well.
2. **Formulas becoming a requirement** rather than the bonus they are today.

Neither is on the roadmap. If either arrives, take Univer and do not re-run the
comparison — it is here.

---

## 9. D1, D2, D3 did not reproduce — the mechanism was somewhere else

**The claim.** The defect analysis reported three severity-1 data-loss defects
in row classification: grouped tables losing the value column their group
headers occupy (D1), rows not matching the dominant pattern being discarded
entirely (D2), and rows carrying values in several value columns losing all but
one (D3). All three were attributed to the extractor, the writer or a
suppression filter, with four candidate fix locations named.

**What was measured.** Each was reproduced against the pipeline directly, by
injecting a controlled model response so the deterministic half could be
observed on its own.

| test | result |
|---|---|
| one band, `Description \| Amount`, over the grouped income statement; 13 rows sent including 3 group headers and 3 totals | **13/13 kept**, all `high`, nothing lost, no notes |
| a row carrying values in all five columns of a declared band | survives the pipeline **and** the writer intact |
| a totals row with four empty value columns | survives — not discarded as empty |
| multi-band grid where the first band overflows its drawn rows | all 14 rows written in the right order; the row-shift arithmetic is correct |
| a value present but UNGROUNDED | **kept**, marked `low` — never dropped |

Then live, at the analysis's own scale: a 5-column, 39-row declared band over a
grouped budget-vs-actual statement with group headers carrying their own values,
per-group subtotals and a grand total. **29 rows expected, 29 returned** —
every group header, every subtotal, the grand total, all four value columns on
every row, parentheses negatives preserved.

**The mechanism that was actually there.** `seen_sources` identified a row by
the TEXT of its source span and dropped every later row quoting the same words.
Injecting a response where a group's rows all quote the group header line — a
plausible model habit — sent 13 rows and kept 10: **the whole second group
gone, label and value together**, which is D1's stated signature ("first group
survives, later groups drop") and D2's ("rows discarded entirely") at once. The
loss was reported only in `validation_notes` — not flagged, not in
`needs_review`, not in the confidence map, invisible in the app and the export.

That is fixed (row identity is now positional), and the three defects are
closed. What made them look like three defects in row classification was one
defect in row identity.

**Why this is written down.** The analysis is a good document and will be read
again. Without this entry, D1–D3 read as open severity-1 defects with named fix
locations, and the obvious next step is to go and change row classification —
which is correct code that four separate tests now pin
(`tests/test_protected_behaviours.py`).

**What would reverse this.** A document where a grouped table loses values with
`dropped_row_count == 0`. That would be a real D1, and none of the evidence
above would apply to it.

---

## 10. D4 and D8 were one defect and one non-defect

**D4** — "a label ending in digits absorbs the leading digits of the value
beside it" — was reported as a label/value boundary error and ranked above the
other data-loss defects because it produces a plausible wrong number rather than
a visible gap.

It was neither a label problem nor a boundary problem. The PDF **wraps the value
inside its own cell**: `FORM-W2-2023` prints `$1,268.7` on one line and `5` on
the next, and `extract_words()` agrees with `extract_text()` — the split is in
the file. The model was handed a truncated number and answered the orphan for
the next slot, and both halves grounded because both are genuinely printed. The
`EIN: 47-38` sighting from the first production run is the same mechanism.

Fixed by reassembling on shared right edge (§`engine/text_layer.py`). Measured:
11 of 12 figures wrong and every one `high` → **12 of 12 correct**, with the
confidence no longer inverted.

**D8** — "numeric normalisation breaks the grounding chain" — is half right and
the wrong half is the important one. The **stored** value was always the
verbatim string and always did appear in the document; the grounding chain was
never broken. Only the exported spreadsheet cell dropped the currency symbol and
the trailing cents, because `coerce_cell_value` writes money as a number so the
cell can sum.

That made the fix one function at the export boundary — a number format derived
from the source string — rather than a rework of validation. Diagnosing it as a
grounding defect would have pointed at the wrong layer entirely.

---

## 11. D10 and D11 were the same dropper, or the wrong writer

**D10 — "a multi-column header band is emitted twice"**, once collapsed into a
single cell and once correctly split across its columns.

Reproduced against the slot writer: a heading merged across three columns above
a declared band writes **once**.

```
['TRANSACTION DETAIL', '', '', '']
['Date', 'Description', 'Amount', '']
['01/03', 'Wire deposit', 15000.0, '']
```

The defect survives only in `_write_form_excel` / `_write_mixed_excel`, which
serve the image path and re-exports of pre-slot jobs. The analysis says as much
itself — "carried forward from the first production run; not re-triggered by the
test templates". It is not a defect of the current pipeline, and fixing a legacy
writer that no live templated extraction reaches would be motion rather than
progress.

**D11 — "a sub-header that redefines a column is dropped"**, leaving the column
holding answers to two different questions with no marker at the boundary.

Reproduced: a `WITHDRAWALS` row inside a band, with its value columns empty,
comes back as its own row between the two data rows it separates.

```
{'Date': '01/03', 'Description': 'Wire deposit', 'Amount': '$15,000.00'}
{'Date': '',      'Description': 'WITHDRAWALS',  'Amount': ''}
{'Date': '01/05', 'Description': 'Payroll',      'Amount': '$18,450.00'}
```

Almost certainly a symptom of the `seen_sources` dropper (§9): a structural row
carries little text of its own and is exactly the kind of row whose quoted
source another row would also claim. The row-emission rule has always kept a
row with any non-empty cell — `if any(str(v).strip() for v in row.values())` —
so nothing ever discarded it for being structural.

**Why both are written down.** Neither should be re-opened from the analysis
document, and neither should be "fixed", because there is nothing in the
current path to fix. What would reverse this is a *declared* band on a live
templated extraction that loses a sub-header while `dropped_row_count` is 0.

---

## 12. I1: the strict region rule stays, and the continuation signal is recorded, not built

A band binds one region, and a region never crosses a page (commit `39c4ec3`).
That loses genuine continuations — `BS-2024-Q1` equity −2 rows,
`PAYSLIP-EMP-0007` deductions −1 — and the loss is flagged every time.

**Rejected: let a continuation through when the next page repeats the column
headings.** Berkshire's page-1 and page-2 tables carry identical headings, so it
merges the exact case the rule exists to separate.

**Measured, not built (2026-09-13).** Every page seam of every multi-page PDF in
`tests/test_pdfs/` (corpus + `round2/`) was checked; 17 are real table-region
pairs, 8 of them genuine continuations. Four positional features plus label
continuity:

| feature | continuations (8) | not (9) |
|---|---|---|
| region 2 at the top of the page body, with no heading of its own | **8** | **0** |
| row labels continue rather than restart | 7 | 0 |
| region 1 runs to the bottom of the page's text | 7 | 4 |
| region 1 ends in a total or closing row | **1** | **7** |

The first separates the sample perfectly. **It is not built**, because the 8
continuations come from about three generators — five balance sheets from one,
two payslips from another, one tax form — so "perfect on 17" is closer to
"perfect on 3". And "ends in a total" runs **backwards**: the intuitive signal
that a table is finished is present on the non-continuations, because a table
that closes with its total on page 1 is followed by something else on page 2. A
rule written from intuition would have picked the wrong sign.

The strict rule stays until the sample includes layouts nobody here generated.

## 13. A client schema has one source of truth: the database (decided, not scheduled)

*Recorded 2026-09-15 · no code changed*

A client's YAML schema is stored in several places: `client_schemas.yaml_content`,
a copy under the storage root (`schemas/clients/{id}.yaml`, which is what
`get_schema_path()` hands the engine), and, for `demo_001` only, a file committed
at `backend/storage/schemas/clients/demo_001.yaml`. Nothing says which copy wins.

**Production is `STORAGE_BACKEND=s3`** (Railway variables, bucket
`docagent-prod`). The copy the engine reads is the bucket object, and no API
path reads the committed file. The committed file wins only under
`STORAGE_BACKEND=local`: it is in the image and in every checkout, and
`_materialise_schemas` writes a schema from the database only when the file is
**missing**, so the committed copy is used and the database's is ignored.
**That is a local-dev problem**, and it is the reason local runs and production
can use different demo schemas without anyone noticing.

**The production risk is bucket versus database.** `POST /api/schemas`
calls `storage.save_schema()` first and commits the database row second, with
no transaction spanning them. A failed commit leaves the bucket holding a schema
the database never recorded. No boot step reconciles the two, because
`_materialise_schemas` skips any key that already exists. The engine then
extracts with the bucket's copy while every API response and the admin page
show the database's. **Not verified against production**: reading the
production row and bucket object was not permitted in the session that found
this, so whether they differ today is unknown.

**Agreed direction:**

- **The database is authoritative.** `yaml_content` is the schema.
- **Every stored file is a cache written from it**, never read back as a source.
  A deploy can then only re-apply what the database already says, so it cannot
  silently revert a schema.
- **Upload writes the database first**, then the cache. A failure leaves the
  cache *behind* the database, which the next write or reconciliation corrects,
  rather than *ahead* of it, which nothing detects.
- **Untrack `backend/storage/schemas/clients/demo_001.yaml`.** The demo seed
  already reads `engine/demo_accounting.yaml`. The committed copy differs from
  that seed only by a garbled em-dash in a comment, and does nothing except
  make local dev disagree with production.

**Rejected:** untracking the file alone, which fixes local dev and leaves the
production divergence untouched; and keeping the file with "prefer the
database" in `_materialise_schemas` while a second stored copy is still
treated as authoritative anywhere.

**Not scheduled.** The related defect, the upload route falling back to
`demo_001` for a client with no schema, is KNOWN-LIMITATIONS WRONG #4 and is
also unfixed.

## 14. I6: the format fix shipped; the value record is the real fix, and it is structural

*Recorded 2026-09-15 · scheduled, not built*

**What shipped.** Round 2 run 11 displayed a rate printed `$0.04116` as `$0.04`,
and four rates as `$0.00`. The committed real export
(`tests/fixtures/round2_exports/run11_engie_BR3_job215.xlsx`) shows every rate
**stored** at full precision under a `"$"#,##0.00` format. `cell_format` counted
the source's decimals and then floored every count of 2 or more at 2. It now
uses exactly the source's decimal count, never fewer and never more.
`tests/test_I6_precision.py` rebuilds run 11 from the real export and the real
PDF; all seven rate cells failed before the change. Harness reports were
identical before and after in both modes, and no answer in the recorded corpus
has more than two decimals, so no recorded cell changed.

**What a value carries today.** One **string** per cell: `extracted_fields[ref]`,
`extracted_data[label].value`, and `<band>_rows[i][column]`. That string is the
model's answer; for multi-line text, `canonical_value` re-joins it from the page.
Confidence is stored per field (`confidence_map`) and per row (`_confidence`),
and flags carry a reason. **Not stored:** the printed token, the line and page it
was read from (used during the run, then discarded; only the model's claimed
`source` survives, inside `raw_llm_responses`), the currency, and the parsed
number. The export re-derives the number (`coerce_cell_value`) and the notation
(`cell_format`) from the stored string every time.

**Why the format fix is not the whole fix.** The export can only show the digits
the stored string has, and nothing requires that string to be what the page
printed. `verify_span` accepted (until §15) a value whose digits appear inside the span, or
whose number equals a token in the span **rounded to two decimals**. Measured
against run 11's real line: `0.04`, `$0.04` and `0.041` all ground as `high`
against a printed `$0.04116`. If the model returns a rounded rate, the precision
is gone before storage, the cell is marked verbatim, and no format can restore
it. A model answer of `0.04116` for `$0.04116` also drops the currency symbol,
the same way.

**The real fix (scope):**

1. **A value record per cell:** `value` (as today), `printed` (the token located
   on the source line, verbatim), plus its page and line. The number and its
   notation are derived from `printed`, never from the model's rendering.
2. ~~**Grounding compares numbers exactly.**~~ **Done separately, §15.** Numeric
   grounding is now whole-token equality.
3. **Every writer derives from `printed`:** slot, inferred, the legacy
   form/mixed/table writers used by the image path, and `export.py`.
4. **Old jobs keep working.** Exports are rebuilt from `extraction_json` on every
   download, so readers must accept a bare string for as long as old rows exist.

**Why it is structural, not contained.** Cell values are bare strings, and that
shape is the contract for the writers above; for `tests/harness/adapter.py`,
`sheet_reader.py`, `scenarios.py` and `round2.py`; for `ResultsGrid.tsx`, the
extract and history pages and `lib/api.ts`; and for the cell-edit PATCH, which
writes strings back. Every stored production job has the old shape. Changing
the cell type touches all of these at once, and the grounding change moves
measured confidence.

**Status: scheduled.** This is the next change to the value contract. The
format fix removes the displayed loss today; this removes the stored one.

## 15. Numeric grounding is whole-token equality — a protective gate

*Recorded 2026-09-15*

**What changed.** `verify_span` grounded a number if it was a substring of its
span (rule A), if its digits were a substring of the span's digits (rule B), or
if it equalled a span number rounded to two decimals (rule C). All three arrived
with `0feb483`, and its commit message gives no reason for either tolerance.
Against a printed `$0.04116`, `0.04`, `$0.04`, `0.041`, `$40.4` and `4042` all
grounded as `high`. A number now grounds only if it is the same number as a
**whole printed token**, differing only in notation: whitespace, currency
symbol, thousands separators, parentheses as minus. It must have the same digits
and the same decimal point. B and C are gone; text values keep rule A.

**Rule B was compensating for word splitting, not grounding.** On the gold
corpus B never fired: all 835 accepted values were accepted by A. On the
Berkshire earnings release (`round2/feb2225.pdf`), pdfplumber's `extract_words`
splits numbers into touching words (`19,6` + `94`, `9` + `.` + `13`,
`2,157,034,1` + `21`; boxes within 0.1pt), and the flattened text puts a space
between them. The model returned the repaired `$ 19,694`, and B was the only
rule that grounded it, for 7 values. **The underlying defect is word splitting
in the text layer, not grounding.** It is not fixed there, because rebuilding
page text changes the prompt and invalidates every cached answer. **Token
rejoining (`printed_numbers`) now carries that load**, inside grounding only.

**How rejoining decides, and what it depends on.** The flattened text puts one
space between split pieces and between columns alike, so spacing cannot tell
them apart. The rule rests on the number itself: a piece continues only when it
is visibly incomplete, so a complete number never absorbs the next one.

| depends on | value | where it came from | generalises? |
|---|---|---|---|
| final thousands group is short | < 3 digits, completed to exactly 3 | the thousands-separator convention | **no** for 2-digit grouping (Indian `1,00,000`), which is not rejoined if split; European notation is already WRONG #2 |
| gap between pieces | exactly one space | pdfplumber's `extract_text` writes one space between any two words on a line | this is **not a distance check**: it separates nothing, it only refuses unusual text |
| lone decimal point | ` . ` as its own word | **the shape seen on Berkshire** | ⚠ **chosen by looking at Berkshire** |
| test premise: joined pieces touch | < 1pt | **measured on Berkshire** (joins −0.1 to 0.1pt; next-closest numeric pair 3.0pt; columns 13.7–50pt) | ⚠ **Berkshire-derived**; a test threshold, not a rule in the code |

The requirement that joining never cross "a gap larger than intra-number
spacing" **is not implementable from the text `verify_span` receives**, because
the text has no gaps. It is met on Berkshire by the completeness rule, and a
test checks it against the real word boxes. A document whose split pieces are
each complete numbers would not be rejoined: the answer is marked `low`, a
visible fault, never an invented join.

**Generality, measured on all 70 committed test PDFs** (115 pages, 5,540 text
lines): rejoining fires **8 times, all on `feb2225.pdf` page 1** (one line is
printed twice), and all 8 are correct: the word boxes touch. **It never fires on
any other document. The rule is unexercised outside Berkshire; that is not
evidence it is safe.**

**Measured movement: none.** Harness replay reports are identical before and
after in both modes (97.2% / 96.7%; confident cells 386/392 and 430/440).
Grounding calls are unchanged: templated 390 accepted, 174 of them numeric;
no-template 445 accepted, 176 numeric; the same 7 non-numeric rejections as
before; all 84 recorded round-2 values (65 numeric, including the 11 Berkshire
ones) still ground.

**This gate is protective.** It closes a hole with **no observed victim**: no
recorded answer in either corpus is a rounded or truncated number. The only
instance is the one constructed for the test. There is **no measured
movement**. Its value is that the next rounded answer is marked `low` instead
of stored as verbatim.

## 16. I2: the export carries provenance — and still no confidence

*Recorded 2026-09-15*

**Reversed: "the sheet carries VALUES ONLY".** The slot writer's docstring and
`TestExportCarriesNoConfidence` pinned an export with no annotations at all. That
rule had two halves, and only one of them was right. *No confidence in the
file* stays: levels, flag reasons and review state belong in the app, and the
test still forbids them, now in comments as well as cells. *No provenance in the
file* is reversed. It was why a merged block, a wrongly bound region or a second
stacked document arrived with nothing saying where it came from (round 2, I2).
The file is where an accountant checks a figure.

**What the sheet carries now.** A `Source` column one past the template's full
extent, `<file> · p.N`, on every row holding extracted values. A comment on every
extracted value quoting the words it was read from, with file and page. A quote
grounding did not find opens with "Not verified: these words were not found in
the document"; that is a fact about the quote, not a score. Opt out with
`?provenance=false`. Jobs stored before this carry no provenance and export
exactly as before: absent, not reconstructed.

**Where the page comes from (`page_of`), and what would break it:**

| source of the page | when | breaks if |
|---|---|---|
| the line a table row claimed | row identity found a line | the line stamp is wrong. It is set at read time as the FILE page (I1) |
| the page every line the quote matches is on | the quote matches lines on exactly one page | the quote matches a line on the wrong page only. Not observed |
| the model's page, mapped to file numbering | the quote matches no line | the model names the wrong page. Unverifiable, and used for 2 values of 349 |
| **none** | no geometry (text-only input), or the quote is on several pages and the model's page is not one of them | the Source cell shows the file name alone. Never a guess |

No thresholds. The one constant is Excel's own comment limit (32,767
characters). The comment box size (360pt wide, 13pt per line) is presentation
only.

**Exercised beyond the documents it was built on.** On the templated gold corpus,
all 386 confident values (109 fields, 277 row cells) are printed on the page
recorded for them. With no template, and across all seven scenarios and the three
recorded round-2 replays (Berkshire p.1 and p.2, ENGIE), no value checked has a
wrong page. The three text-only scenarios have no geometry and correctly get no
page (18 values). Page resolution across that run: 195 by a quote matching one
page, 132 by the row's claimed line, 2 by the model's page among several, 2 by
the mapped model page, 18 none. **Weak spot:** every gold table row is on page 1,
because the page-2 continuations are what I1 leaves out. The multi-page row
evidence is the round-2 Berkshire page-2 run and the three-invoice file.

**Measured movement: none.** Harness reports are identical before and after in
both modes, *including export accuracy*: the harness reads the written file back,
and neither the Source column nor comments disturb it. The transposed-template
run is unchanged (48.6%). Comments cost 1.1s and 96KB per 10,000 values.

**Found while scoping, not fixed: a cell edit never reaches the export.**
`ResultsGrid.tsx` saves an edit by replacing `extracted_data[label]` with
`{value, confidence: "edited"}`. The slot writer places values from
`extracted_fields`, which the edit does not touch, so the file keeps the
extracted value. The comment on that cell therefore quotes the words behind the
value actually in the file, which is consistent, but a user's correction is lost
on download.

## 17. A cell edit is addressed by SLOT — and two things it uncovered

*Recorded 2026-09-15*

Scoping §16 found that a correction typed into the results grid never reached
the downloaded file. Fixing it turned up two more defects that had nothing to
do with editing, and only one of the three is fixed. All three are recorded
here because the first was found by reading, the second by asking what *does*
read a label, and the third by asking what a label even identifies.

### 17a. An edit names a cell, not a label (fixed)

**What was wrong.** `ResultsGrid.tsx` saved an edit by replacing
`extracted_data[label]` and PUTting the whole document back. The slot writer
and the zip export place values from `extracted_fields[ref]`, which the edit
never touched, so the file kept the extracted value after the grid said
"Saved". True since 1076e05; 0feb483 removed the last label fallback. Only the
combined and per-file exports (`export.py`) read the edited copy, which is why
it went unnoticed — one of the two export families did the right thing.

**Why the label could not be the address, even in principle.** `extracted_data`
is a PROJECTION of the slots, keyed by `row_label`. A label is not an
identifier:

- Two slots can share one. A matrix template draws `Principal` under `Years
  1-7` and under `Years 8-30`; the label names both cells and neither.
- The projection is lossy in the other direction too. Only a slot's label
  survives into it, so a payload built from the projection cannot say which
  column it meant even when the user knew.
- It is rebuilt every run. A grid whose columns the model names differently on
  the next extraction re-keys every edit ever made against it.

A slot ref (`B13`) has none of those properties: it is the address the value
was requested at, the address it was written at, and the address the writer
places it at. Making it the edit's address means the edit and the export agree
by construction rather than by a matching rule — the same reason slot-directed
extraction exists at all (§1).

**What it cost.** `PATCH /api/jobs/{job}/docs/{doc}/fields/{ref}` edits one
slot and moves the slot value, the label projection, the confidence map
(`edited`) and `field_provenance` (`edited`, `original_value`) together; an
unknown ref is 404. The whole-document PUT *reconciles* rather than
overwriting, so a payload built from a stale copy cannot undo a stored edit,
and it **refuses (422) a label that names two cells** instead of guessing which
one. The writer comments an edited value as typed by a person, names the value
it replaced, and never quotes it as a source — an edit is not grounded and must
not look it.

**Evidence.** At b83ba1c, 11 of 24 new tests fail (template and zip field
edits, 3 provenance cases, the second-edit revert, 5 repeated-label tests) and
13 controls pass; with the fix all pass, plus 8 PATCH route tests. Harness
identical in both modes.

### 17b. The combined and per-file exports emit no table rows at all (NOT fixed)

Asking what else reads by label found `export.py::_build_excel`, which reads
`extracted_data["extracted_data"]` and nothing else. That key holds **scalar
fields only**. Neither `POST /api/export/combined` nor `/api/export/perfile`
has ever written a line item, a band row, or anything under `table_rows` or a
`*_rows` key — edited or not, with a template or without. An invoice exported
this way arrives with its header fields and no lines.

This is not a regression from the edit work; it is older than it, and it was
half-recorded already. The Phase-8 audit found `include_line_items` declared on
`ExportRequest` and read by nothing, and **removed the flag** with the
reasoning that "this export is a flat table of scalar fields and emits no line
items in any configuration, so the flag could only ever describe something the
writer cannot produce". That reasoning is correct about the flag and stops
short of the defect: it records that the writer cannot do it, not that a user
who exports this way loses the rows.

**Why it is not fixed here.** It is a writer change, not an edit change, and it
has a real design question in front of it — a combined sheet is one row per
document, and line items are many rows per document, so there is no obvious
place to put them without either a second sheet or a shape that is no longer
"one row per document". The template-shaped export
(`GET /api/jobs/{id}/export`) writes rows correctly and is the supported path.
Recorded in KNOWN-LIMITATIONS as an open defect so that it is a known cost
rather than a surprise.

### 17c. One value per repeated label was being dropped, silently (fixed)

The projection was built by assigning `kv[slot["row_label"]]`, so where two
slots shared a label the **second write overwrote the first**. The lost value
was still in `extracted_fields` and still written by the template export, but
it was absent from the results grid, from both label-keyed exports, and from
anything else reading `extracted_data` — with nothing saying a value had gone.
A user looking at the grid saw a complete-looking sheet.

A shared label is now qualified by its column heading, or by its cell ref where
the heading does not separate it (`Closing Balance [B29]`). A label used once
is unchanged, so nothing that reads an ordinary label sees any difference.

**How common it is, measured rather than assumed.** 1 of the 21 committed
template grids puts one label on more than one field slot — and it is the
purpose-built matrix fixture, so that number is close to meaningless as
evidence about real templates. The honest data point is the other path: 1 of
the 10 inferred grids does it on a real document. `STMT-2024-01`'s inference
prints `Closing Balance` twice, in the summary box and again under the
transactions, and before this fix one of them was dropped. Inference produces
repeated labels on documents nobody designed to produce them, which is the case
the hand-drawn corpus cannot show.

**What would break it.** The qualifier is derived from `col_header`, which is
the template's own text; two slots sharing a label *and* a column heading fall
through to the cell ref, which is always unique. The qualified string is a
display and addressing name, not a stored key — nothing persists it, and the
PATCH route addresses the ref directly, so a qualifier that changes between
runs cannot orphan an edit. What it does change is any consumer that reads the
projection by an exact label string; inside this repo the results grid and both
`export.py` writers were audited, and the harness adapter had to change with it
(below).

**The harness had to change with it, and that is where such a change belongs.**
Scoring resolved a field claim by NAME, which worked only while a label was
unique. With the projection qualifying the second slot, `STMT-2024-01` arrived
as three claims for two cells — `Closing Balance`, `Closing Balance [B13]`,
`Closing Balance [B29]` — and the two that lost the gold name counted as
out-of-schema, moving that figure 60 → 62 with no change in what was extracted.
The adapter now resolves each entry through its `ref` and dedupes on the slot,
not the spelling, which puts it back at 60 and makes it comparable with every
figure recorded before. Two slots that *disagree* still both appear, under the
engine's own qualified name: a flat `{name: value}` gold file has no room for
the second, and dropping it silently would hide exactly the defect 17c fixes.
The gold labels were not touched — an engine-shape change is the adapter's
problem by standing rule (§7).

## 18. I4: the third row gate is made loud, not removed — and measured first

*Recorded 2026-09-16*

**There was never a row classifier.** The round-2 report describes rows "not
matching the dominant pattern in a band" being dropped three different ways.
Nothing in the engine computes a dominant pattern or tests a row against one.
Four gates drop a row, and the shape of the defect is that two of them were
built visible and one never was:

| gate | where | visible before |
|---|---|---|
| not a JSON object | `slot_extractor.py:904` | n/a |
| region — the row is on another page | `:914` | flag, counter, `needs_review` |
| duplicate — its source line is spoken for | `:949` | flag, counter, `needs_review` |
| **every schema cell empty** | **`:1016`** | **nothing at all** |

The cells are emptied one level down, at `:987`, where `cells.get(h, "")` is an
**exact** lookup over the band's column keys. A key the model returned that the
template has no column for was discarded on the floor, uncounted. That is the
whole mechanism, and it is what makes the drop depend on template shape: change
a template's columns and you change which of the model's cells survive, so the
same document under two templates comes back with different rows. Reproduced
with the model's answer held fixed — a five-column band loses a `{Label: "Net
earnings includes:"}` row entirely and keeps a `{Label, Amount}` subtotal with
its label gone, while a two-column band keeps both — at `dropped_row_count = 0`,
`needs_review = False`, zero flags.

**The gate stays.** A row with nothing in any column this template has is not a
row of this table, and emitting it would put a blank line into every sheet whose
model returns a trailing empty object. What was wrong was the silence, which is
the same fault the duplicate drop was fixed for: nothing told the reader to go
and look, so a template that loses a section total looks exactly like one that
had none.

**Measured before designing, because the corpus could not see it.** Across all
374 cached responses — 166 with tables, 1,807 rows — the model had never
returned a row keyed differently from its table's other rows. That is not
evidence the defect is rare; every template in the corpus was drawn to fit the
document it points at, and a user's is not. So `tests/harness/i4.py` perturbs
the TEMPLATE and leaves everything else alone: each gold band **narrowed** (two
adjacent columns where the document has five), **widened** (two columns the
document does not have), and **reworded** (the same columns under different
words — the control).

23 live runs, 39 bands, 227 returned rows:

| variant | bands | rows | written | region-flagged | **silent** | off-schema keys |
|---|---|---|---|---|---|---|
| narrowed | 5 | 33 | 33 | 0 | **0** | **0** |
| widened | 17 | 102 | 97 | 5 | **0** | **0** |
| reworded | 17 | 92 | 89 | 3 | **0** | **0** |

The model returns exactly the keys it is asked for. Widened, it returns `Ref`
and `Notes` **empty** on all twelve bank-statement rows rather than inventing
content for columns the document lacks. Reworded, it answers under the
template's words — `Posted`, `Kind`, `Particulars`, `Withdrawals`, `Deposits`,
`Running Balance` — and maps the document's columns onto them correctly.

**That number decided the granularity.** A per-key flag would have fired zero
times on 17 legitimately reworded bands, so per-key was affordable on the
evidence. The flag is nonetheless per **ROW**, because a row is the unit a
reader can act on and one flag naming three lost keys is worth more than three
naming one each; the keys themselves are counted
(`validation.off_schema_key_count`). Zero observations cannot justify a noisier
choice than the useful one.

**What this is, honestly: a latent defect made reportable, not an observed one
fixed.** Nothing in the corpus would have told us if it started happening, and
that is the argument for the reporting rather than for guessing at the cause.
The tests stub their answers for the same reason — the condition occurs in no
recorded answer, so it has to be constructed to be pinned.

### 18a. Rule A could only ever fire on a declared region

Found while tracing the above, and **more likely to occur than I4 itself**: it
needs one blank cell rather than a model answering off-schema.

`_gate_findings` rule A warns about "a band column with no heading" by iterating
`b["columns"]`. A **detected** band is built from a run of ADJACENT non-empty
headings, so a column whose heading is blank is not in `columns` at all — there
was nothing there for A to find. A declared region keeps the column, calls it
`Column A` and warns; the identical hand-drawn table dropped the column before
the gate ran and said nothing, and the column is then never asked for and never
written.

The added half looks at the column immediately **left** of a detected band,
blank on the heading row and inside the used range — `m` is dense within that
box, so membership is the test. Left only: a blank column right of a table is
ordinary empty sheet, while the one to its left is a top-left corner somebody
forgot to fill in. It warns rather than blocks, like A, and it fires on **0 of
the 19 templates committed to this repo** — the same false-positive standard
every other gate rule was chosen on.

**Measured movement: none.** Both harness reports are identical before and
after, per document and in every summary, in both modes: templated 97.2% /
4 misfiled, no-template 96.7% / 60 out-of-schema. Suite 953 passed, 4 xfailed.
The new counters are additive keys on `validation`; nothing that reads the
result contract sees a changed value.

## What these decisions have in common

Five of the first seven replaced something that failed *silently* — placement
matching, model self-confidence, keyword routing, the fallback flag, and shape
detection. In each case the replacement was chosen less for accuracy than for
making failure visible or impossible to represent, and the accuracy followed. The
two that did not follow that pattern — the widening refactor and the labelling
policy — were both about not letting the measuring instrument flatter the thing
it measures.

§8 is the same instinct turned on a build-or-buy question. The component was
kept not because it was good but because counting where the defects actually
lived — two of eight in the component, six in the engine and the wiring — showed
that replacing it would have felt like progress while fixing almost nothing.

The one place we did not live up to it is recorded in §6: the no-template balance
sheet has been broken since the elimination refactor, it was visible in commit
messages at the time, and the aggregate covered it for four phases.
