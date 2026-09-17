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

## 19. I5: the report's recommendation is right about one kind of label and wrong about the other

*Recorded 2026-09-16*

The round-2 report says labels are "assembled rather than quoted" and recommends
treating them exactly as values — a verbatim span with its own quote and
location. That is **already implemented for the labels that come from the
document, and would re-run a measured failure for the labels that do not.**
There are four label paths and they are not the same kind of thing:

| label | comes from | has a span? |
|---|---|---|
| templated field slot (`template_shape.py:911`) | the USER's own grid cell | no, and the question does not apply |
| templated band column (`:709`, `:348`) | the user's grid heading | no, same |
| **band ROW label** | the document — it is a CELL of the answer row | **yes. Grounded, placement-checked, provenance-carrying** |
| inferred field / column / total (`shape_inference.py:333`) | the model | no |
| `layout_sections` row label (`extract.py:1537`) | the model, prompt says "item name from document" and never asks it to quote | no |

**Measured across every recorded answer in the repo — 5,225 labels, 332
answers, 25 documents:**

| class | labels | printed verbatim |
|---|---|---|
| band row label | 1,957 | **100.0%** |
| `layout_sections.label` | 410 | 98.8% |
| inference (field, column, table, total, title) | 2,858 | 55.9% |

**Right for band row labels — and already done.** A band's label column is
answered as a cell like any other, so it carries the row's source span, is
checked by `verify_span` and `check_placement`, and is written with provenance.
1,957 of 1,957 are the document's own words. There is nothing to change.

**Wrong for inference labels, and the project has measured why.** A verbatim
rule would reject **1,259 of 2,858** inference labels. That is not a defect
count; it is mostly the naming policy stated in CLAUDE.md, which exists on
purpose: *no printed label (a letterhead, a signature, the digits inside a MICR
line) → take the name from the canonical list*, and *printed label ambiguous
about WHICH value it is → prefer the list's precise term*. At least 100 and 78
of the observed non-verbatim labels are exactly those two rules. The cost of
over-restricting naming is already on the record: the first vocabulary told the
model to prefer listed names, it read that as "do not report what is not
listed", dropped the employer from a payslip and the status from an expense
report, and cost one invoice 34 points. **We are not doing that again.**

There is also nowhere to put a span. An inferred label's destination is a
`SheetSaveData` grid cell — `{value, style}`, text a user could have typed —
and that is the invariant the whole one-rule shape system rests on. Shape is
recomputed from the grid every run and never stored, so a span would have to
survive inference → `build_grid` → `compute_shape` → writer, across the one
boundary the architecture makes lossy on purpose.

### 19a. Mode 1 is a text-layer column problem, not a naming problem

`INV-2024-0047` prints two blocks side by side, and the flattener joins them:

```
Payment Instructions            Notes
Wire: First National Bank ...   Balance due March 4, 2024. Late ...
```

Inference is asked to prefix a block's heading onto each field under it, and
with the columns gone it has to guess which of two headings owns a line. It was
not choosing badly — it was choosing without the evidence. `column_text` builds
a SECOND rendering with the column breaks kept, **for inference only**:
`doc_text_pages` is what `verify_span` grounds against and what slot extraction
is prompted with, and rewriting it would change every span check in the project.

**Not every gutter is a block boundary, and marking all of them was tried and
rejected on evidence.** The blunt rule marked 63% of the corpus's lines,
including the gap between a label and its own amount, and the live no-template
harness fell **96.7% → 95.2% with 10 misfilings where there had been none**
(defect rate 0.0% → 2.2%, 7 regressions). `STMT-2024-01` is the clearest case:
marking `Opening Balance | $184,320.55` as two columns made inference model the
summary box as a *table*, and three fields gold expects went missing.

A break is a block boundary when the text on **both sides is prose**. A label
beside its amount is one thing in two columns; two runs of words side by side
are two blocks. That drops the marked share to 34%, and the live harness returns
to **96.7%, misfiled 0, defect rate 0.0%, every per-document accuracy identical
to baseline** — one extra out-of-schema label (`Member FDIC`, printed on the
cheque, which gold has no field for).

What it bought, on the two documents the defect lives on:

- `INV-2024-0031`: the field `Payment Instructions Notes` — a name manufactured
  from the two headings flattened onto one line — is **gone**. In its place, four
  fields correctly attributed to the left block (`Payment Instructions - Wire
  Bank / Wire ABA / Wire Account / Cheque Payable To`) and two to the right
  (`Notes - Payment Received`, `Notes - Reference`). Before, the wire details had
  no block prefix at all.
- `INV-2024-0047`: `Wire ABA`, `Wire Account Number`, `Wire Bank Name`, `Cheque
  Payable To` all become `Payment Instructions <X>`; the contentless field
  `Notes` becomes `Notes Late Payment Interest`.

⚠ **All 23 recorded `Notes X` labels were already CORRECT.** Every one names
something genuinely printed in the Notes column. The defect was never a wrong
answer on these documents — it was a correct guess made with no evidence, and
one manufactured field name. That distinction is why the fix had to be judged on
the harness rather than on the labels.

⚠ **The report's own example does not hold.** `run6_engie_E3`, now recorded
live against the real bill, reproduces `Oncor Customer Charge` exactly — and the
bill **prints `Oncor Customer Charge $2.05` verbatim**. `Oncor` is not a prefix
from a sidebar callout; it is the line. The mechanism I5 describes is real, but
this instance of it is a misreading.

⚠ **It does nothing for I7. Measured, not assumed.** The ENGIE interleaved
account number `00000000112538645596` is present, identically, in both the flat
and the column rendering. I7 is two strings stacked VERTICALLY and clustered into
one line; there is no horizontal gap to split, so a gutter rule cannot reach it.

### 19b. Mode 3 is a proven zero, and the reason is structural

No label in any recorded answer has its characters contiguous on the page but
its word boundary elsewhere. The one place a label is genuinely assembled from
the page in code — `shape_inference._AMOUNT_LINE`, which splits a printed line
at the whitespace before its trailing number — was audited directly across all
69 corpus PDFs: **678 labels assembled on 43 documents, 0 landing mid-token, 0
that are not a verbatim prefix of their own printed line.** The regex requires
`\s+` before the number, so the cut is at a word boundary *by construction*. It
cannot produce `01` + `0.25 %` → `01.25 %`; that join happened somewhere else.

**Mode 4's cause is measurable even though mode 4 is not.** The same splitter
retains **123 leading section letters and line numbers**, all on the Closing
Disclosure (`A. Origination Charges`, `01 0.25 % of Loan Amount (Points)`), and
hands them to the model without distinguishing "line number" from "label". No
recorded answer carries the same label both with and without a prefix, so the
inconsistency itself is unobserved here — the Closing Disclosure has no recorded
answer at all.

### 19c. The provenance sidecar, and the bug it nearly shipped with

`inferred_label_provenance: {cell_ref: {source, page}}` travels beside
`inferred_grid`, recording the line a label was read from **where there is one**.
It requires nothing, rejects nothing and renames nothing — which is the only way
to add it without re-running the failure above. 130 of 247 inferred labels on the
gold corpus (52.6%) carry one; the rest correctly carry none. Mode 2 — "is this
label policy or contamination?" — is answerable per label for the first time.

⚠ **Provenance is a property of (label, DOCUMENT), never of the schema.** Stored
on the inferred schema, it was handed to every document of that kind by batch
reuse: the second bank statement carried the FIRST one's quoted lines, statement
number included. `test_batch_isolation` caught it as cross-document
contamination. `_with_label_provenance` now binds it per document, on a shallow
copy, and never mutates the shared schema.

### 19d. `layout_sections` labels: skipped, and why

The report's recommendation applies cleanly here — one prompt line and a
`verify_span` — and it was not done, because the check would have no reference.
`_build_vision_prompt` has exactly one live caller (`extract.py:3701`, the image
path) and it passes `doc_text=""`. An image has no text layer; that is the
defining property of the path, and every value on it is already `unverified`.
Asking the model to quote a span there produces a quote nothing can check. The
other consumer is re-export of jobs stored before the slot pipeline. **Recorded
as not-worth-doing rather than left unmentioned.**

## 20. I11: the prose-in-a-scalar-field symptom moved; nothing was built to stop it

*Recorded 2026-09-16 · no code changed*

Round 2 run 9 answered `Contract End Date` with `the last day of October 2020` —
a sentence fragment, and wrong besides: the bill says the agreement expires on
the meter read date *following* the last day of October. The live BR4 run made
after the I1 fix returns empty for that field, so the question was whether a
check now stops it.

**It does not. The document extent changed and the model declined.**

| recording | commit | date | documents | `Contract End Date` |
|---|---|---|---|---|
| `run9_engie_BR4_prefix_fe3385d` | `fe3385d` | 2026-09-08 | **2** (`SampleBill.pdf [1 of 2]`, `[2 of 2]`) | `the last day of October 2020` |
| `run9_engie_BR4` | `39c4ec3` | 2026-09-13 03:50 | **1** | `""` |

`39c4ec3` **is** the I1 commit, recorded at 03:48; the clean run was captured two
minutes later. Pre-I1, a type change alone split the ENGIE bill at its glossary
page, and the slot set was asked against a document that stopped part way. Post-
I1 the file is one 4-page document — read today with the pipeline's own
`read_page` and `doc_boundaries.split`, `find_starts` returns `([0], '')`, one
document, 4 pages. **The contract sentence is still on page 3 and still in the
prompt.** The model saw *more* text and answered nothing; nothing removed the
temptation.

The two halves of the pre-I1 split also disagree with each other on the same
file — `Bill Account Number` `0000123456` vs `00000000112538645596`,
`Billing Period` `Aug 12, 2020 to Sep 11, 2020` vs `Aug 12 / Sep 11` — which is
the over-split cost I1 removed, and is why the I11 example came from a run whose
document extent was already wrong.

**Fed back to today's engine verbatim, the answer passes every check that looks
at what it MEANS.** `verify_span` → grounded (the words are printed on page 3),
`_single_datum` → True (no pipe, no email, no phone — the only three things it
looks at), `confidence_for` → **`high`**, unflagged, and `coerce_cell_value`
writes the fragment into the cell unchanged. `core/validator.py::_validate_type`
does carry a date check, and it is unreachable: its only caller is
`orchestrator._process_single_document`, which nothing under `backend/app/`
calls. **Nothing in the slot path types a value against its label.**

⚠ **CORRECTION, 2026-09-16, same day.** The paragraph above was first written as
"the answer still passes everything", and that was wrong end to end. Run through
the real pipeline on the real `SampleBill.pdf`, this value is **already demoted
and flagged** — by D9's word-run gate, `matches_loosely`, because the value
straddles a line break and no run of words on the page spells it. `confidence_for`
is never reached for it. The functions above were measured **in isolation**, and
that was mistaken for the end-to-end result. The error was caught by writing the
test: the first version asserted a before/after delta that did not exist. See §20b
for what was built and what it is actually worth.

### What the corpus says

Every recorded answer in the repo was replayed through the real pipeline and
every (label, value) pair harvested: 2,400 pairs over 61 runs and 23 documents
(gold ×2 modes, round-2, scenarios, the 23 i4 perturbations, plus the two raw
round-2 files replay cannot reach). A label is scalar-implying by generic word
class — prose nouns beat everything, then date, amount, count, then the engine's
own identifier list applied only at the head of the label.

| kind | empty | parsed | scalar in prose | no scalar |
|---|---|---|---|---|
| date | 2 | 66 | **1** | 0 |
| amount | 45 | 646 | 0 | 0 |
| number | 0 | 36 | 0 | 0 |
| id | 98 | 100 | 0 | 0 |
| **all** | 145 | 848 | **1** | 0 |

The one is `Contract End Date`. It is also the classifier's positive control:
a scan that found nothing would be indistinguishable from a broken scan, so the
pre-I1 answer was kept in the corpus precisely so the instrument could be seen
to fire.

**⚠ One instance across 994 is a measurement of these documents, not a property
of the system** — the same caveat as "invented 0". 23 documents, 12 distinct
date labels, and every template was drawn by us.

### Why the strict form of the recommendation is not built

"Return a parsed value or return nothing" costs, at the strict reading — one
token, and it is the whole value — **24 of the 849 values written today**:

| kind | kept | blanked |
|---|---|---|
| date | 47 | **20** |
| amount | 642 | 4 |
| number | 36 | 0 |
| id | 100 | 0 |

Nineteen of the twenty date blanks are legitimate ranges: `Pay Period` =
`April 1–30, 2024`, `Period` = `March 15–22, 2024`, `Billing Period` =
`Aug 12, 2020 to Sep 11, 2020`. A period field holds two dates because the
document prints two. **Twenty-three correct values destroyed to catch one wrong
one** is the same trade already refused for the strict span rule (§2, 250 cells
demoted to reach a worse number), arrived at from the other direction.

What survives the measurement is the lenient form — a scalar-implying label
whose value carries a token of the right kind *wrapped in prose* is demoted and
flagged, not blanked, with range connectors allowed.

## 20b. I11: the lenient rule is built, and it is worth less than it looks

*Built 2026-09-16 · `slot_extractor.prose_in_a_scalar`, called from
`confidence_for`*

One function beside `_single_datum`, called from the one place all three slot
paths already go through, so the reason travels out on `_flag` like every other
demotion and no call site needed touching. Three conditions, all required, each
one holding a measured class of template out of the net:

| condition | what it keeps out | on gold |
|---|---|---|
| the LABEL implies a scalar, and a label naming prose beats every other word in it | `Charge Description` is a description, `Payment Terms` are terms, `Amount in Words` IS prose, `Account Holder` is a person | — |
| the value CONTAINS a token of that kind — **"no scalar at all" deliberately does not fire** | a band's LABEL COLUMN: a two-column band is named after it, so the column headed `CURRENT ASSETS` holds account names and `COST OF GOODS SOLD` holds `Opening Inventory` | **103 cells** |
| the residue is a **closed-class** English word that is not one of the kind's own range connectors | `Common Stock (100 shares @ $1,000 par)` — `shares` and `par` are ordinary words, not function words; and every date RANGE, via the connector list | 3 + 19 cells |

### What it is worth, stated honestly

**It fires ZERO times across every recorded answer** — replayed through the real
pipeline, 61 runs, 23 documents, 458 table rows, and **1,138 cells whose label
the engine's own `scalar_kind` reads as scalar-implying**. That count is the §20
table's 994 counted differently, not a second corpus: it includes the band label
columns condition 2 spares and excludes the pre-I1 raw file, which replay cannot
reach. Zero fires, therefore zero false positives. Both harness modes are **byte-
identical** before and after: templated 97.2% / content 96.7% / structure 100% /
defect 1.0%, no-template 96.7% / 95.9% / 100% / 0.0%, `"diff": []` in both
reports, only the timestamp and commit SHA moved. Expected, and it held: the one
affected value is not in gold.

**And on the one instance the corpus does hold, the rule adds nothing** — D9's
`matches_loosely` catches it first, as the correction above records.

So the justification is **structural, not measured**, and that is the whole
argument for keeping it: D9's gate keys on word **adjacency**, which is a
property of the page's layout and not of the answer, and its reason —
"assembled from words that are not adjacent" — describes a flattening artifact,
not a sentence in a date cell. A prose fragment printed on ONE line matches
loosely, grounds, and reaches `high`. Page 3 of this same bill prints such a
line: `Charges for Billing Period for Aug 12, 2020 to Sep 11, 2020`. Answered
with a fragment of it, `Contract End Date` came back `high` and unflagged
before, `low` and flagged after — same pipeline, same document, every
pre-existing gate passing. That is the delta, and it is a **constructed** answer
rather than a recorded one, because no recorded answer in the repo contains a
contiguous prose fragment in a scalar slot. `tests/test_i11_scalar_prose.py`.

### What would break it

- **A non-English document.** Every word list is English, so condition 2 fails
  on `le dernier jour d'octobre 2020` and nothing fires. **Silent is the right
  failure for an English-only rule** — it demotes nothing it cannot read — but it
  is a GAP, not coverage, and a test pins it so it cannot be met as a surprise.
- **An answer with no scalar in it at all.** `on or about the end of the month`
  in a date cell passes, by the same condition that spares 103 label-column
  cells. Tightening that is not affordable until the label column is known here,
  and it is not: `confidence_for` sees a column KEY, not a role.
- **A label whose class is read wrongly.** `Company Tax ID` classifies as an
  *amount*, because `tax` is a money word and `ID` is not at the head. Only its
  lack of prose keeps it clean today.
- **A perfectly ordinary date that is simply the wrong date.** Nothing here
  reads meaning; that is §20's sibling defect, still open and still xfailed.

### Also recorded: dead validation that reads as coverage

`core/validator.py::_validate_type` checks `YYYY-MM-DD` on any schema field
typed `date`. Its only caller is `orchestrator._process_single_document`, and
nothing under `backend/app/` calls that. Grepping this repository for a date
check finds one; the pipeline the product runs has none. Added to
`docs/KNOWN-LIMITATIONS.md` rather than deleted — deleting it would take the
command-line tool's only validation with it, and the point is that the next
person gets the true answer, not that the line disappears.

## 21. I10: the text layer was never degraded — it was read without font size

*Built 2026-09-16 · `text_layer.read_page`, `overprinted_spans`,
`core/preprocessor`, `extractor`*

Round 2 run 12: a BoA statement of roughly 130 date-stamped transaction lines
came back as **two rows**, and `-35.00 + -30.00 = -65.00` reconciles, so a
reviewer checking the arithmetic passes it while 128 rows are missing.

**The model never had them to return.** `extract_words()` groups characters on
horizontal adjacency alone. Where a page prints several texts at different
SCALES over one band of y, their characters interleave in x and the size-blind
grouping shatters every one of them. One 12pt-tall band of page 3 holds 718
characters at five sizes:

    extract_words()                    265 words: 'A' 'AM' 'n' 'T' 'on' 'M' 'nu'
    extract_words(extra_attrs=[size])  116 words: 'For' 'consumer' 'accounts'

Across the file: **5 date-shaped words against 133**, and the PROMPT —
`extract_text()`, which groups the same way — carried **3** transaction lines.

`read_page` now asks for words that may not span a font size. The fix is one
argument; everything below is what it took to be sure of it.

### It had to reach the prompt, not just the geometry

`read_page` returns `extract_text()` VERBATIM when nothing was repaired, so the
one-argument change fixed `lines` and left the model reading the shards — page 3
still offered 5 dates while its geometry held 133. A shredded page is now
rebuilt from its words, and **only** a shredded one, because rewriting an
undamaged page changes what the model is asked and throws its cached answer away
for nothing.

Two tests decide "shredded", and the second exists because the first is not
enough:

| | fires on | why |
|---|---|---|
| **shard ratio ≥ 1.05** | HTR p3 (2.51), p2 (1.14) | per page over all 98 corpus pages with ≥40 words, the **highest clean page is 1.013** |
| **a recovered word the raw text lacks** | SampleBill p2, p4; the 5 audit letters | four words in four hundred do not move a ratio — SampleBill p4 sits at **1.00** and still prints its account number twice, at 11.0pt over 10.2pt |

Comparing the two TEXTS instead was tried and rejected: flattened for
whitespace it still fired on **36 of 114** pages, rewriting whole pages over one
token.

### ⚠ I7 was this defect all along, and its detector had to change with it

`SampleBill.pdf` page 4 — round 2's reported "overprinted account number", and
the artifact pinned in three test files — is **two account numbers at two font
sizes**, not an unrecoverable overprint:

    was   00000000112538645596     one word, nothing on the page prints it
    now   0000123456 0000158659    both numbers, in the words AND the text

I7's own docstring said "which of the two texts was wanted is not recoverable
from the page". That was true of the size-blind reading and is false now. The
same goes for the five gold-corpus audit letters, whose letterheads have
interleaved their address (8.0pt) with their reference number (7.5pt) since the
day they were committed: `NSou:i`, `tAe`, `U2D20-200,` are now `No:`, `Suite`,
`AUD-2024-001`.

**Left alone, the detector then condemned the values the fix had just rescued** —
13 words on SampleBill and **910 on HTR**, including both correct account
numbers, every one demoted to `low` and flagged. `overprinted_spans` now
compares characters **within one font size** (a cross-size overlap is two
separable texts) **and within 1.0pt of one baseline** (the audit letters' 8.0pt
address and the 8.0pt line below it are two lines, not two texts; `group_lines`
clusters at 3.0pt and had put them together).

What survives is the case still genuinely unrecoverable: two texts overlapping
at the SAME size. HTR is the corpus's only one — 1,037 same-size pairs within
half a point of one baseline — and `TestSameSizeOverprintIsStillCaught` keeps
the detector from becoming dead code.

**The I7 evidence tests were rewritten, not relaxed.** They asserted a premise
the fix removes; they now assert the stronger contract, and the artifact is
still caught if a model returns it anyway — by D9's word-run gate, which does
not depend on a detector firing.

### Measured end to end

- **10 gold documents × 2 modes: NO DIFFERENCE** in values, provenance source,
  provenance page, grounded flag, confidence, table rows and their `_source` /
  `_page`, every validation counter, flagged fields, notes or review state.
- **Both harness modes byte-identical**: templated 97.2 / 96.7 / 100% / 1.0%,
  no-template 96.7 / 95.9 / 100% / 0.0%, `"diff": []`, `unstable: 0`.
- **Wrapped-token repairs identical on all 68 PDFs**, 25 → 25. Berkshire
  (`feb2225.pdf`) is untouched; its one word change is `'1/1,500th'` (6.5pt +
  10.0pt) becoming `'1/1,500'` + `'th'` — a superscript ordinal correctly
  detached from its number.
- **12 PDFs' word lists moved, and every change is a REPAIR, not a difference**:
  `FEBRU`+`ARY`→`FEBRUARY`; `joan@zt.bizICUSBANK.`→`joan@zt.biz`+`ICUSBANK.`
  (an email address welded across 9.0pt/8.0pt); five audit letters' reference
  numbers; SampleBill's two account numbers; Berkshire's ordinal. None of the
  10 gold documents is among them.
- HTR after: **133 date words, 164 money words, 64 transaction-shaped lines,
  133 dates in the prompt**, and `column_bands` — which found NOTHING before —
  now locates three of the gold bank-statement headings.

### The warning, and what it deliberately does not cover

`[TEXTLAYER] page N: SHREDDED TEXT LAYER — 2.51x more words read without font
size than with it`, before the model is asked, plus a `validation_notes` entry,
`needs_review`, and `validation.shredded_pages`. It fires on HTR pages 2 and 3
and on nothing else in the corpus.

⚠ **IT DOES NOT DETECT A SCANNED DOCUMENT**, and the warning text says so.
`round2/bank-statement-sample.pdf` is 108 words over 66 images — a scan with a
thin text layer — and scores **1.00**. Two different failures, two different
signals. Treating this one as the OCR canary would give false assurance, which
is why the disclaimer is in the log line, in the note, and in
`docs/KNOWN-LIMITATIONS.md` rather than only here.

### The coverage indicator: NOT BUILT, and why

The report's other recommendation — rows emitted vs candidate rows detected,
surfaced to the user. A prototype using `column_bands` (a candidate row is a
line below the heading touching ≥2 of its column spans) over both harness modes,
on a corpus scoring 97.2% with 100% structure fidelity:

| | |
|---|---|
| bands measured | 35 |
| **no verdict** — the document prints no heading line | **17** |
| ratio on the rest | min **0.15**, p10 0.23, **median 0.38**, max 0.75 |

HTR, after the text-layer fix, scores 2 of 25 = **0.08**. The floor among
CORRECT extractions is **0.15** (`PAYSLIP-EMP-0012` Earnings, 2 of 13, right).
A factor of two, with half the bands abstaining. **A ratio reading 0.38 on a
perfect invoice trains people to ignore it**, which is the same class of bug as
the silent failure it would replace.

**The reason it does not separate is that the candidate counter OVER-COUNTS**: it
takes every printed line in the region touching two column spans, so wrapped
continuation lines, section totals and the block below the table all count as
candidate rows. The next attempt starts there — a candidate detector that models
a ROW rather than a LINE — not at picking a threshold.

And on today's code the signal was worse than useless: before this fix
`column_bands` found **zero** headings on HTR and the prototype returned *no
verdict* — the indicator was silent on the document it was designed for, because
the same defect that hid the rows hid the heading.

### What would break the text-layer fix

- **A page that legitimately sets one word in two sizes** — a drop cap, a
  superscript inside a token — is now two words. `feb2225.pdf` is exactly this
  (`1/1,500` + `th`) and it is the right answer there; a currency symbol set
  smaller than its amount would be the wrong one, and nothing in the corpus
  does that.
- **A reader without `extra_attrs`** falls back to the old call; the `TypeError`
  branch is not decoration.
- **The 1.05 and 1.0pt thresholds are corpus-measured**, on 98 pages and 69
  PDFs, all but two of them drawn in-house.

## 22. I8: the diagnosis is overturned on all three counts, and the obvious detector is measurably worse than nothing

I8 said: *values from the wrong source field validate as correct*, and named
three. Investigated from the code on 2026-09-16, after the round-2 answers were
re-recorded at `f3d4d4a`. **None of the three is an instance of the class the
item names.** Two were one structural defect that I1 had already fixed; the
third is a text-layer defect on I7's axis that already fails loudly. The item's
proposed change — "grounding must carry the quote's location and its nearest
source label" — was then measured on its own terms and **rejected**.

### Symptoms 1 and 2 were the page-4 split, and the prefix recording proves it

The report read `Billing Period = Aug 12 / Sep 11` (page 4, under `Reading
Dates Previous/Current`) and `Meter Number = 0123456789AB` "returned inside a
block that should not exist" as two findings about the model's judgement. They
are one finding about document boundaries, and the phrase "a block that should
not exist" was literally the whole cause rather than an aside.

`tests/fixtures/round2_raw/run9_engie_BR4_prefix_fe3385d.json` was captured
before I1, when a keyword classifier read the glossary page as a tax form and
cut `SampleBill.pdf` in two. **Both halves were asked the full slot set**, and
both answered:

| | F2 `Billing Period` | F3 `Meter Number` |
|---|---|---|
| document 1 — pages 1-3 | `Aug 12, 2020 to Sep 11, 2020` ✔ | *(empty)* |
| document 2 — page 4 alone | `Aug 12 / Sep 11` | `0123456789AB` |

Document 1 answered it correctly all along. **The model never confused the
meter reading dates with the billing period**; it was handed a one-page
document that does not contain a billing period, asked for one, and returned
the only date range printed on that page. That is correct behaviour under a
false premise. The report saw the two documents' output together and read
document 2's answer as the extraction's answer.

The meter number is not even a wrong value. Page 4 prints

```
Reading Dates    Meter   Meter      Meter Reading      Usage  Usage
Previous/Current Number  Constant   Previous Current   Type
Aug 12 / Sep 11  0123456789AB  1    0        0         kWh    982
```

and `0123456789AB` sits under `Meter … Number`. Right value, right column,
wrong document — and the document was the defect.

Both re-recorded runs confirm the fix: `run4_engie_E1` and `run9_engie_BR4`
answer `Aug 12, 2020 to Sep 11, 2020`, quoted from page 1's `Service Aug 12,
2020 to Sep 11, 2020`, under the printed `BILLING PERIOD` heading, and the
meter number now comes from page 4 of the one document it belongs to.

### Symptom 3 is a text-layer defect, and the arithmetic that alarmed the report is coincidence

`Total withdrawals = -65.00` on `round2/HTR-043235.pdf`. The report's alarm was
that `-35.00 + -30.00 = -65.00`, so "the output reconciles" and a reviewer
checking the arithmetic would pass it.

`65.00` is printed on page 3 in its own right — size **6.9 pt**, x 410.7-429.2,
top 435.2 — among two `$35.00` at **6.1 pt**, x 407.2-427.5, tops 435.1 and
435.8. Three amounts from three overlay layers, right-aligned into one column
on one baseline. The sum is a coincidence, not a synthesised total.

What produced the reading is `group_lines`, which clusters on `y` within
`LINE_TOL = 3.0` and is blind to layer. On this page that collapses 52 words
spanning four font sizes into a single 641-character line:

```
Total Total Note Total Direct your service service deposits Ending deposits
fees fees and Balance other … $9,999.99 - - - $35.00 $35.00 from 65.00 the
```

The pairing of `Total` with `65.00` never existed on the page as a visual unit;
line clustering manufactured it, and a span quoted from that line grounds
perfectly because the merged line **is** the text layer. This is I7's remaining
axis — §21 fixed word grouping across font sizes and left line clustering
untouched.

**It already fails loudly.** `overprinted_value` returns true for the value, so
`slot_extractor.py` demotes it to `low` and flags it; 2,647 of the page's 5,052
words (52%) are overprint-tagged, which also trips the >30% document gate. The
signal is indiscriminate rather than absent — correct values like `Derry Diner`
and `19.31` are condemned with it — and that is recorded in KNOWN-LIMITATIONS,
not fixed here.

### The label-witness gate: 33 false positives, and no true positive available

I8's proposed change is one rule: a value is trustworthy only if the document
prints **the slot's own label** near the quote. Measured over every recorded
gold answer, replayed (`tests/harness/witness.py`, pinned by
`tests/test_i8_witness.py`):

| | | |
|---|---|---|
| filled field slots | **115** | |
| label witnessed on the quote's line or the line above | 79 | 68.7% |
| **not witnessed** | **33** | **28.7%** |
| undecidable (no content word in the label, or no quote) | 3 | counted apart |
| of the 33: `correct` / `near` / defective | **28 / 5 / 0** | |

**Not one of the 33 is a defect.** And the corpus contains **no defective field
slot at all** — 110 `correct`, 5 `near`, nothing wrong, missed or hallucinated —
so these ten documents can price the gate's false positives and **cannot price
its true ones**. "Zero true positives" would overstate it; the honest statement
is that the gate costs 28.7% of correct values to catch something this corpus
cannot demonstrate it catches.

The misses are systematic, and they are this repo's own naming rules 1-3 seen
from the other side — *the document's own word for a field is routinely not the
field's name*:

| the slot asks for | the page prints | kind of miss |
|---|---|---|
| `Cheque Number` | `No: CHQ-001847` | a synonym |
| `Payment Terms` | `Terms: Net 30` | a synonym |
| `Total Earnings` | `Total $14,583.33` | an abbreviation of the compound label |
| `Bill To Company` | `Bill To:` as a heading above the block | label not beside the value |
| `Drawer Name`, `Payee` | nothing | **no printed label at all** — naming rule 2 |

A cheque is the worst case: six of its field slots fail the gate and all six
are correct, because a cheque labels almost nothing it prints. A gate that
contradicts the naming policy on its own corpus is not a gate that needs
tuning; the two cannot both be right. **Rejected, alongside gate rule G (R6)
and the strict span rule (§2)** — all three fire on legitimate documents, which
is the same class of bug as the silent failure they were meant to replace.

### Why no rule of this shape can work

Every gate the pipeline has is a property of **the page**: `verify_span` asks
whether the string is printed, `printed_numbers` whether the number is printed
whole, `matches_loosely` whether the words are adjacent, `check_placement`
whether the x-span fits the column, `overprinted_value` whether two texts share
the ink, `record_span` whether the cell sits in its own record, `select_region`
which page the row came from. A value that is real, printed, grounded,
correctly typed and correctly placed satisfies all of them.

The class I8 gestures at is a property of **the claim** — not *is this string
on the page* but *does this string answer the question this slot asked*. No
geometric check can reach it, because geometrically nothing is wrong. The only
meaning-aware checks in the engine are `_single_datum` and `prose_in_a_scalar`
(§20b), and both compare the label's implied **kind** to the value's kind;
neither can ask whose value it is.

**What survives of I8 is the fabrication gap**, and that is a different item:
`Customer Email Address` answered with the supplier's own
`care@engieresources.com` — page read correctly, value located correctly, typed
correctly (`_single_datum` passes an email precisely because the label says
"email"), grounded, and still the wrong party's address. It is pinned as a
strict xfail in `tests/test_round2_I1.py` and recorded in KNOWN-LIMITATIONS
WRONG #3. Reaching it means asking the model a **second, different question**
about the value it already gave and treating disagreement as the signal. The
pipeline makes one Gemini call today and has no verification pass; that is a
proposal with a per-document cost, not a recommendation.

### 22a. The second call: Q-A measured live, and rejected on false positives

Full scope, criteria and method in `docs/SECOND-CALL-VERIFICATION.md`; harness
`tests/harness/attribution.py`; every raw response committed to
`tests/fixtures/attribution_raw/`. The criteria were fixed **before** the
numbers, and a 0% catch rate was declared publishable in advance.

Q-A asked two questions about the **document**, never about our answer: which
party a value belongs to, and which of the template's labels the document
presents it as answering (closed list, shuffled, `NONE` allowed). The model was
never shown which slot a value had been written into, so it could not agree by
reading our answer back — that separation is the only thing distinguishing Q-A
from the circular form the confidence docstring rules out. 11 live calls,
$0.0023, `gemini-2.5-flash-lite` at temperature 0.

| signal | false positives on 115 correct gold values | held-out four |
|---|---|---|
| closed-list `answers` | **0 (0.0%)** | 2 of 4 |
| `party` | **7 of 27 party-bearing (25.9%)** | 2 of 4 |
| combined | 7 (6.1%) | 4 of 4 |

A separate arm injected 107 same-kind swaps and caught 107, which is discounted
on purpose: those are assignments **we** invented and the model has no
attachment to them.

**REJECTED, beside the label-witness gate above and for the same reason.** The
7 false positives are all one document, `PO-2024-0018`, and all one error: a
purchase order is issued by its **buyer** and received by its **vendor**, and
the model reversed every party on it — it reads a PO as though it were an
invoice. This was checked rather than assumed; our comparison map has the
direction right and the model does not. A follow-up scoring the model's own
`answers` label against its own `party` answer, with no expectation of ours in
the loop, returns the **identical 7 rows** — because `answers` agreed with the
true label on all 115 — so there is no cheaper re-scoring that rescues it.

⚠ **The binding constraint is corpus breadth, not the method.** Ten documents,
nine document types, **one purchase order**. A failure mode with one instance
cannot be bounded, and shipping a gate whose only measured failure we cannot
price is the same bug it was built to replace — the refusal already made for
the strict span rule (§2), gate rule G (R6) and the label-witness gate (§22).
**That is what would have to change before a retry is worth anything**: more
document types, several instances of each. A better prompt would not move it.

#### Finding 1 — the wrong belief is stable, and reframing did not move it

`care@engieresources.com` was returned for `Customer Email Address` by **four
runs across three prompt frames**:

| run | frame |
|---|---|
| round-2 run 9 | slot extraction, pre-I1 |
| `run9_engie_BR4_prefix_fe3385d` | slot extraction, bill SPLIT at page 4 |
| `run9_engie_BR4` (re-record at `f3d4d4a`) | slot extraction, unsplit, post-I10 text |
| the Q-A verification call | **a genuine reframing** — different question, closed list, model not shown our assignment |

The reframing was the whole proposal, and it returned the same wrong answer.
**This defect is not reachable from inside the model as currently asked.** Any
future attempt starts from that, not from the hope that a better phrasing
dislodges it.

#### Finding 2 — §22's objection is cleared: the rule fails, the question does not

The label-witness gate flagged 33 correct values because a document's own word
for a field is a synonym, an abbreviation, a heading above the block, or absent
(§22). Those same 33 values are inside this experiment's 115, and the model
placed **33 of 33** correctly: `No: CHQ-001847` answers Cheque Number,
`Terms: Net 30` answers Payment Terms, `Total $14,583.33` answers Total
Earnings, an unlabelled name on a cheque answers Payee.

So the two results are not the same result twice. **String matching cannot
bridge a synonym and a model can.** Anyone reaching for the witness idea again
should know that what failed was the mechanism, not the question — and that the
closed-list form of the question costs 0 false positives on this corpus.

#### Finding 3 — THE THREAD: the model contradicts itself inside one answer

The most useful thing the experiment produced, and the place a future attempt
should start.

Asked about `care@engieresources.com` in a **single response**, the model
asserted all three of these at once:

- it **answers** `Customer Email Address`
- the label **printed beside it** is `Email Us`
- it belongs to the **ISSUER**

Those cannot all be true. A value belonging to the issuer does not answer a
field asking for the customer's, and `Email Us` is the supplier's own contact
heading. **No comparison map of ours is required to see it** — the incoherence
is entirely within the model's own output, which is what makes it different
from everything rejected so far. Every gate this project has refused needed an
expectation we supplied; this one would not.

Recorded verbatim in **`tests/fixtures/attribution_raw/heldout.json`**, so the
contradiction can be re-read rather than taken on trust. It is not built,
because three consistent signals are not a measurement and one document is not
a corpus — see the binding constraint above.

#### Keep the swap generator: it is a fabrication probe in its own right

`attribution.py::swaps` pairs each field slot with a **same-kind value from
another slot of the same document** — a date for a date, money for money, a
name for a name. Every value it produces is real, printed, grounded, correctly
typed and correctly placed **by construction**, which is precisely the class
§22 showed the gold corpus contains none of (110 `correct`, 5 `near`, zero
defective).

It is therefore worth keeping **independently of Q-A**. Any future check on
this defect class needs a population of true positives to be priced against,
and the gold corpus cannot supply one. 107 of 115 slots have a same-kind
partner, it costs nothing to generate, and it is deterministic. Kept for that
reason, not because Q-A used it.

So round 2 closes with **one** open problem, not two. I8 does not merge into the
fabrication gap — it dissolves, and the fabrication gap is what is left standing.

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
