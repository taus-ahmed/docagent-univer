# Decision log — phases 1–7, plus the template-editor decision

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
second is checkable; making it mandatory is what lets us say 0 inventions across
376 templated cells rather than merely believing it. The stricter variant was
tried and rejected on evidence: it was meant to catch a value truncated at a line
break, but it demoted 250 correct cells to reach 98.4% precision — worse than the
99.5% without it — because a correct value read off a line is structurally
identical to a truncated one and nothing in the span distinguishes them. We also
accepted, rather than hid, the limit this leaves: grounding proves text came from
the document, not that it belongs in that slot, which is why no-template mode can
report 415 high-confidence cells of which 90 are misfilings.

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
