# A reader seam for `read_page` — design proposal

Written 2026-09-17, against `46f778f`. **Proposal only.** No code was written,
no dependency is added, and nothing in `text_layer.py` or `extract.py` has been
touched. This document says what a seam would have to be; it does not build one.

Its input is `docs/OCR-CONTRACT-SCOPING.md`, whose headline finding is that the
seam the design intent assumes **does not exist**: `read_page` takes a
pdfplumber page and calls four pdfplumber-specific APIs on it.

⚠ **This proposal is deliberately not OCR-shaped.** OCR is the motivating
second reader, not the only one, and a design that only fits OCR would be
untestable until OCR exists. Everything below is written so that *a second
pdfplumber-based reader for a different edge case* fits the same seam — which
is also the cheapest way to find out whether the seam design is right (§9).

---

## 1. Where the seam goes, and where it does not

`read_page` today does two separable jobs:

| job | lines | pluggable? |
|---|---|---|
| **obtain** raw text and a word list for one page | 895-901 | **yes — this is the seam** |
| **orchestrate**: repair wrapped values, inject markers, stamp pages, mark overprints, decide whether to rebuild the text | 903-933 | no — this is engine policy |

The proposal is a seam **below** `read_page`, not around it. `read_page` keeps
its orchestration and stops talking to pdfplumber directly. What becomes
pluggable is a **page source**: a thing that can be asked for this page's words,
its raw text, its page number, and — critically — *what it is able to do*.

**Backwards compatibility is a hard requirement, and the count is exact.**

```
$ grep -rn "read_page(" --include=*.py . | grep -v "/\.venv/" | grep -v "def read_page(" | grep -vE "import" | wc -l
31
$ grep -rn "read_page(" --include=*.py . | ... | sed 's/:.*//' | sort | uniq -c | sort -rn
      4 ./tests/test_round2_I1.py
      4 ./tests/test_multiline_and_widths.py
      3 ./tests/test_text_layer.py
      3 ./tests/test_round2_regressions.py
      3 ./tests/test_gate0_evidence.py
      2 ./tests/test_row_identity.py
      2 ./tests/test_i11_scalar_prose.py
      1 ./tests/test_scenarios.py
      1 ./tests/test_provenance.py
      1 ./tests/test_protected_behaviours.py
      1 ./tests/test_placement.py
      1 ./tests/test_numeric_grounding.py
      1 ./tests/test_i5_column_text.py
      1 ./tests/test_I6_precision.py
      1 ./tests/harness/scenarios.py
      1 ./tests/harness/attribution.py
      1 ./backend/engine/core/preprocessor.py
```

**31 invocations: 1 production (`core/preprocessor.py:164`) and 30 in tests and
harness**, across 16 test/harness files. Plus 1 definition and 20 import lines.
`text_layer.py` contains no self-invocation — the only `read_page(` in it is the
`def` at line 884.

**Backward compatibility means ZERO call-site changes.** Every one of the 31
passes a pdfplumber page positionally as the first argument. The proposal is
that `read_page` wraps a raw pdfplumber page in the default source
automatically, so the existing form keeps working verbatim:

```
# today, and unchanged after the seam — all 31 existing call sites
text, lines, repairs = read_page(page)
text, lines, repairs = read_page(page, widgets.get(page_num) or [], stats=stats)

# the new form, available but never required
text, lines, repairs = read_page(PdfplumberSource(page))
text, lines, repairs = read_page(SomeOtherSource(...), widgets, stats=stats)
```

The wrap is a type check on the first argument — if it is not already a
`PageSource`, it is a pdfplumber page and gets the default wrapper. No test
file is edited, and the evidence those 30 call sites carry is preserved intact.
That property is not a convenience; rewriting 30 test call sites in the same
change as a structural refactor would destroy the thing that would tell us the
refactor was safe.

---

## 2. The two things a reader must declare

The whole design rests on readers **declaring** rather than the engine
**assuming**. Two declarations, both checked at the boundary.

### 2.1 A coordinate-space declaration

Every reader states, per page: the unit, the origin, the page height and width
in that unit, and (where it applies) the raster resolution it worked at.

The seam's job is to **normalise once, at the boundary, to the engine's own
space** — points, top-left origin — and to refuse a reader whose declaration it
cannot convert. Nothing downstream of the seam ever sees a non-normalised
coordinate, which is what makes every existing tolerance in `text_layer.py`
continue to mean what it says.

This is not a new convention. It is the one the engine already uses implicitly,
and `acroform_widgets` already performs exactly this conversion by hand:

```
$ sed -n 775,799p backend/engine/text_layer.py
            height = float(page.mediabox.height)
    ...
            items.append({"x0": x0, "x1": x1,
                          "top": height - y1, "bottom": height - y0,
```

The proposal is to make that conversion a boundary responsibility with a
declared input, rather than a hand-written flip in one function.

### 2.2 A capability set

A reader states what it can produce. Proposed capabilities, each named for a
thing the engine currently does unconditionally:

| capability | what it unlocks | reader that lacks it |
|---|---|---|
| `CHARACTER_GEOMETRY` | `overprinted_spans` — needs per-character boxes and per-character font size (`text_layer.py:581`, `:606`) | overprint detection is **not run**, and says so (§8.2) |
| `SIZE_AWARE_TOKENISATION` | the two-pass `shard_ratio` at `text_layer.py:897-903`, and the rebuild branch at `:930` | the shredded-layer detector is **not run**, and says so (§8.1) |
| `TRUE_FONT_SIZE` | `size` on a word means a font size rather than a surrogate | nothing today; reserved, because §2.2 of the scoping report found zero word-level consumers |

**A capability is a claim about the reader, not about the document.** The
distinction matters: "this page has no overprints" and "this reader cannot see
overprints" are different facts, and the engine currently cannot tell them
apart because both arrive as an absent flag.

---

## 3. The interface, as notation

Not an implementation — a shape, to argue with:

```
PageSource
  .page_number            -> int (1-based, file page)
  .space                  -> CoordinateSpace(unit, origin, height, width, dpi?)
  .capabilities           -> frozenset[Capability]
  .raw_text()             -> str
  .words(size_aware=bool) -> list[word dict]      # size_aware honoured only
                                                  # with SIZE_AWARE_TOKENISATION
  .chars()                -> list[char dict]      # only with CHARACTER_GEOMETRY
```

`read_page(source_or_pdfplumber_page, widgets=(), stats=None)` keeps its
signature and its return triple.

---

## 4. Finding 1 — no reader seam, and the `page.chars` dependency

**Addressed.** §1-3 above are the answer to the structural half: a `PageSource`
protocol, a default implementation wrapping pdfplumber, and `read_page` talking
only to the protocol.

**`page.chars` is the hard part and is handled by capability, not by fallback.**
`overprinted_spans` (`text_layer.py:548-637`) is character-level by necessity —
its own docstring says so:

> That is why this is measured on CHARACTERS. It is the only level at which
> the two texts are still separable.

A reader without `CHARACTER_GEOMETRY` does not get a degraded overprint check.
It gets **no overprint check**, recorded as such. See §8.2 for the mechanism and
why a silent `False` is the one outcome the design forbids.

**Open question, needs real documents.** Some OCR engines do expose per-glyph
boxes, which would nominally satisfy `CHARACTER_GEOMETRY`. Whether glyph boxes
from a *raster* carry enough fidelity for `OVERPRINT_TOP_TOL = 1.0pt` and
`OVERPRINT_FRAC = 0.5` to mean anything is unknown and unknowable from this
repo. The capability must therefore be one a reader **opts into**, not one the
seam infers from the presence of a `chars()` method.

---

## 5. Finding 2 — `EDGE_TOL = 1.0pt` and value rewriting

**Partly addressed; the residue is an open question, not a design choice.**

`repair_wrapped` is the only place in the engine where coordinate noise changes
a **value** rather than a verdict — it fuses two words into one
(`text_layer.py:214-223`). Its tolerance was calibrated against a reader whose
coordinates are exact:

> Measured on FORM-W2-2023, every genuine fragment matched to **0.0pt**; the
> tolerance is for rounding, not for guessing.

**What the seam does:** `repair_wrapped` stays *downstream* of the seam and
stays in points, because after normalisation a point is a point regardless of
reader. It does not become reader-specific logic.

**What the seam adds:** the tolerance becomes a **declared reader property**
rather than a module constant — today's `1.0` for the pdfplumber source, and
whatever a new reader can honestly claim. The constant does not disappear; it
becomes the pdfplumber reader's declared value, so nothing changes for the
existing path.

**⚠ What the design explicitly refuses to decide.** Widening `EDGE_TOL` for a
coarser reader is **not** obviously the right move, and this proposal does not
propose it. A false fuse invents a figure that was never printed; a missed
repair leaves a visibly short value. The project has already chosen that
direction once, in `_shortfall`'s three-shape rule: *a missed repair is a
visible wrong value; a false repair invents a figure, which is worse.* A reader
that cannot meet 1.0pt may therefore need `repair_wrapped` **disabled** rather
than loosened — which is a third capability (`SUB_POINT_EDGE_GEOMETRY`) whose
threshold cannot be set from this repo.

**Needs real documents (§7):** whether scanned client documents even exhibit
wrapped-in-a-narrow-box values. If they do not, this is moot for the OCR
reader; if they do, the repair has to be priced on real scans before any
tolerance is chosen.

---

## 6. Finding 3 — the silent unit mismatch

This is the finding the seam most directly fixes, so it is worth restating what
breaks. From the scoping report, §3.2:

> `inject_markers` compares **pypdf widget rectangles** (converted, points)
> against **pdfplumber word coordinates** (points). This is the one place a
> coordinate from a different source meets a word coordinate, and it is the one
> place a reader returning pixels instead of points would misalign silently —
> the comparison is an inequality against `LINE_TOL`, so a unit mismatch
> produces a wrong line assignment, never an exception.

**Addressed, and by construction rather than by a check inside the comparison.**

Three parts:

1. **Widgets get a declared space too.** `acroform_widgets` (`text_layer.py:744`)
   reads the file with pypdf and is *already* a second coordinate source,
   independent of whichever reader produced the words. It should return its
   declaration alongside its rectangles rather than silently pre-converting.
2. **The seam normalises both sides to points/top-left before they meet.**
   `inject_markers` then compares two things that are guaranteed to be in one
   space, and its `LINE_TOL` inequality means what it says.
3. **A mismatch is refused at the boundary, loudly.** If a reader declares a
   space the seam cannot convert, or declares one whose page height contradicts
   the widget source's, that is a hard failure with a message — not a warning,
   not a fallback. This follows the project's existing rule: *do not add a bare
   `except` fallback around extraction; a failure must be a failure.*

**Why an explicit declaration rather than inference.** A pixel coordinate and a
point coordinate are both plausible floats. There is no value either side can
inspect to tell them apart, which is exactly why the current failure is silent.
Only a declaration makes the mismatch detectable at all.

### 6.1 The declaration covers origin as well as scale — and origin is a distinct failure

Stated explicitly, because finding #3 evidenced only one of these and the two
are independent:

| axis of mismatch | covered? | evidenced by |
|---|---|---|
| **unit scale** — points vs pixels | **yes**, `unit` + `dpi` | finding #3: a reader returning pixels misassigns markers via `LINE_TOL` and never raises |
| **origin and y-direction** — top-left/y-down vs bottom-left/y-up | **yes**, `origin` | **already real in this codebase**, see below |
| **page height** — needed to perform an origin flip correctly | **yes**, `height` | a flip against the wrong height misplaces every y by a constant |
| **rotation** (`/Rotate` 90/180/270) | **NO — open gap**, §10.7 | not evidenced; 0 of 114 corpus pages are rotated |
| **skew / deskew** on a raster | **NO — open gap**, §10.7 | cannot arise from a digital PDF; unknown for scans |

**Origin mismatch is not hypothetical — the codebase already performs an origin
flip by hand**, which is the proof that two sources with different conventions
already meet here:

```
$ sed -n 775,799p backend/engine/text_layer.py
            height = float(page.mediabox.height)
    ...
            items.append({"x0": x0, "x1": x1,
                          "top": height - y1, "bottom": height - y0,
```

PDF user space is bottom-left origin with y increasing upward; pdfplumber's
`top` is top-left with y increasing downward. `height - y1` is that conversion.
It is correct today and it is *unchecked* — it works because one function knows
both conventions and nothing else has to. A second reader with a different
convention would need the same flip and has nowhere to declare that it needs
one.

Note that an origin mismatch fails differently from a scale mismatch, and
arguably worse. A pixels-for-points error scales coordinates by a constant
factor, so markers land far away and the damage is likely to be visible. A
flipped origin **mirrors** the page: a marker for a checkbox near the top lands
near the bottom, in a line that genuinely exists, at a plausible `x`. Both are
silent, but the flipped one produces output that looks more reasonable.

**The boundary check must therefore verify all four covered axes, not just
unit** — and must cross-check `height` between the word source and the widget
source, because a flip performed against a disagreeing height is silent too.

**Rotation is an acknowledged gap, not a solved case.** Measured:

```
$ python -c "... pdfplumber page.rotation across the corpus ..."
pages scanned: 114 rotation values: {0: 114}
```

All 114 corpus pages are unrotated, so nothing here exercises it and the design
does not claim to handle it. A `/Rotate 90` page, or a scan fed in sideways,
is a fifth way two sources can disagree and is recorded as open at §10.7.

**Note the ordering constraint.** This is the one finding whose fix must land
*with* the seam rather than after it. Today there is one coordinate source and
the assumption holds by accident; the moment a second reader exists, the
assumption is load-bearing and unchecked.

---

## 7. Finding 4 — what the contract actually requires

From the corrected field list (scoping report §1.3 and the contract table), the
twelve keys split three ways:

### Required of every reader

| key | why |
|---|---|
| `text` | the value itself |
| `x0`, `x1` | 21 and 13 consumers; gutters, column bands, placement, fusion |
| `top` | 9 consumers; line clustering, overprint bands, marker placement |
| `bottom` | 3 consumers (`text_layer.py:819, 822, 828`) |

`bottom` is currently optional in practice — line 828 reads
`x.get("bottom", x["top"] + 10)`. **The proposal is to require it and retire the
fallback.** That `+ 10` is a magic constant standing in for a glyph height that
every reader actually knows; keeping it means a reader can omit a field it has
and get a silently wrong line box. Requiring it is a contract tightening that
costs the pdfplumber reader nothing, since pdfplumber already supplies it.

### Supplied by the seam, never by a reader

| key | who sets it |
|---|---|
| `page` | `stamp_page` at `text_layer.py:908/990`, from `source.page_number` |
| `overprinted` | `mark_overprints` at `:653`, only when `CHARACTER_GEOMETRY` is present (§8.2) |

A reader that sets either of these should be considered in error. They are
engine annotations, not reader output.

### Capability-gated, with a defined absence

| key | rule |
|---|---|
| `size` | supplied only with `TRUE_FONT_SIZE`. **Absent is legal and already works** — the scoping report proved it by exercising the `TypeError` branch at `text_layer.py:899`, which yields words with no `size` key and completes normally. A reader must **not** synthesise a surrogate silently (§8.1) |

### pdfplumber passthroughs the contract must not require

`doctop`, `height`, `width`, `upright`, `direction` — present on every
pdfplumber word and read by nothing, anywhere. Requiring them would force every
future reader to fabricate five fields to satisfy consumers that do not exist.
A reader may include them; nothing may depend on them.

---

## 8. Findings 5 and 6 — capability-gated checks that degrade loudly

Both of these are the same design problem: a check whose *mechanism* is
reader-specific, and whose absence must not look like a clean result. The
project already has the right vocabulary for this and it should be reused rather
than reinvented — `app/core/confidence.py` distinguishes:

> `UNVERIFIED` — No text layer existed to check the span against at all…
> The value may well be perfect; we simply did not check. Reported as "medium"
> before Phase 8, which implied a measurement that never happened.

*A measurement that never happened* is precisely the state both checks land in
for a reader that cannot run them. That is a third value, not a `False`.

### 8.1 Finding 5 — the shredded-layer detector

**Proposal: capability-gated, not dropped, and never silently skipped.**

`shard_ratio` is a ratio between two tokenisations of one page by one reader,
size-respecting and size-blind (`text_layer.py:897-903`). A reader without
`SIZE_AWARE_TOKENISATION` cannot produce the second reading, so the ratio, the
rebuild branch at `:930`, and the `[TEXTLAYER] … SHREDDED TEXT LAYER` warning
all have no input.

- With the capability: unchanged. `SHARD_SHRED = 1.05` keeps its meaning,
  because it is a ratio between two readings by the same reader — it is
  dimensionless and reader-relative, which is what makes it portable in
  principle.
- Without it: the detector **does not run**, `stats["shard_ratio"]` is absent
  rather than `1.0`, and the document records that this check was not performed
  — alongside `validation.shredded_pages`, not instead of it.

**Why not a surrogate.** A reader could tokenise twice using bbox height as a
stand-in for font size. The scoping report measured that surrogate at 97%
agreement, with every disagreement on the one page the mechanism exists for —
and more decisively, both passes would come from the *same* segmentation, so
the diff measures nothing. A surrogate here manufactures a reassuring number.
Absence of the check is the honest state.

**Explicitly out of scope for the seam:** *replacing* the detector for
non-text-layer readers. A scan has a different degradation mode — §5.2 of the
scoping report shows the existing detector is blind to thin OCR layers anyway,
scoring 1.00 on `bank-statement-sample.pdf` against a 1.05 threshold. What a
scanned page's equivalent canary should be is a separate question that needs
real documents, and the seam should not pretend to answer it.

### 8.2 Finding 6 — `overprinted`

**The first draft of this section proposed a three-valued per-word flag. The
call-site audit below says that is the wrong shape, and the proposal has
changed accordingly.**

Every read of the flag, repo-wide — direct on the word dict, and indirect via
`overprinted_value`, which is the only function that reads it:

```
$ grep -rn '\["overprinted"\]\|get("overprinted"' --include=*.py . | grep -v "/\.venv/"
./backend/engine/text_layer.py:653:                    w["overprinted"] = True
./backend/engine/text_layer.py:734:            if not w.get("overprinted"):
./tests/test_round2_regressions.py:93:                if w.get("overprinted")] == []

$ grep -rn "overprinted_value(" --include=*.py . | grep -v "/\.venv/" | grep -v "def "
./backend/engine/slot_extractor.py:945:                if overprinted_value(value, all_lines):
./tests/test_gate0_evidence.py:191:            assert overprinted_value(word, lines) is False, word
./tests/test_gate0_evidence.py:195:        assert overprinted_value("Meridian", lines) is False
./tests/test_gate0_evidence.py:196:        assert overprinted_value("Associates", lines) is False
./tests/test_round2_regressions.py:97:        assert overprinted_value("0123456789AB", lines) is False
```

| site | form | classification | behaviour under a 3-valued result |
|---|---|---|---|
| `text_layer.py:653` | `w["overprinted"] = True` | **write** — the only producer | n/a |
| `text_layer.py:734` | `if not w.get("overprinted"): continue` | **read — NEGATION** ⚠ | **CHANGES / SWALLOWS.** See below |
| `test_round2_regressions.py:93` | `if w.get("overprinted")` | read — truthy filter | a falsy third state is skipped, same as today; a truthy one breaks the assert |
| `slot_extractor.py:945` | `if overprinted_value(...):` | **read — TRUTHY on the function result** ⚠⚠ | **CHANGES.** See below |
| `test_gate0_evidence.py:191, 195, 196` | `assert ... is False` | **explicit identity comparison** | fails if the function ever returns anything but `False` for a clean word |
| `test_round2_regressions.py:97` | `assert ... is False` | **explicit identity comparison** | same |

**Two negation/truthy sites would silently mishandle a third value, and they
are the two that matter.**

`text_layer.py:734` is a negation: `if not w.get("overprinted"): continue`.
Today, "absent" and "`False`" both mean skip. If a not-measured state is
represented as absent or `None`, `not None` is `True`, the word is skipped,
`overprinted_value` returns `False`, and the caller is told **checked and
clean**. The third state is destroyed one line after it is introduced — this is
the exact silent-degradation failure the design exists to prevent, and it is
latent in the code today.

`slot_extractor.py:945` is worse, because it is a truthy check on the function
result and it drives a demotion:

- if the not-measured sentinel is **truthy** (an enum member, a string), the
  branch fires and **every value in the document is flagged as overprinted and
  demoted to `low`** — a corpus-wide false positive;
- if it is **falsy** (`None`), the branch never fires and the third state is
  invisible at the one place it would have mattered.

There is no choice of sentinel that makes both sites behave correctly without
editing them. **A three-valued `overprinted_value` cannot be delivered by
changing the reader alone.**

**Revised proposal: keep the per-word flag two-valued; carry "not measured" at
the document level.**

| level | value |
|---|---|
| per word | `True` / `False`, exactly as today. All six read sites keep their current meaning and the four `is False` asserts keep passing |
| per document | a capability-derived record: overprint detection **performed** or **not performed, because this reader lacks `CHARACTER_GEOMETRY`** — a note plus a `validation` entry, in the same shape as `validation.shredded_pages` |

**"Same shape as" — shown, not asserted.** `shredded_pages` is the closest
existing precedent, and it exists at three levels. The real definitions:

```
$ grep -rn "shredded_pages" --include=*.py . | grep -v "/\.venv/"
./backend/engine/core/preprocessor.py:45:    shredded_pages: list[int] = field(default_factory=list)
./backend/engine/core/preprocessor.py:181:                    doc.shredded_pages.append(page_num + 1)
./backend/engine/extractor.py:343:    shredded = list(getattr(doc, "shredded_pages", []) or [])
./backend/engine/extractor.py:389:            ed.setdefault("validation", {})["shredded_pages"] = list(shredded)
```

```
$ sed -n 41,45p backend/engine/core/preprocessor.py
    #: 1-based page numbers whose text layer was SHREDDED — several texts set
    #: at different font sizes over one band of y, their characters interleaved
    #: in x. Separated and rebuilt by `read_page`; listed here so the warning
    #: survives past the log line. NOT a scanned-page signal (I10).
    shredded_pages: list[int] = field(default_factory=list)
```

```
$ sed -n 385,390p backend/engine/extractor.py
            ed.setdefault("validation_notes", []).append(
                f"page {pages}: the text layer was SHREDDED — ...")
            ed["needs_review"] = True
            ed.setdefault("validation", {})["shredded_pages"] = list(shredded)
```

The proposed record, in the same three places and the same types:

```
# backend/engine/core/preprocessor.py — beside shredded_pages on ProcessedDocument
    #: 1-based page numbers on which overprint detection was NOT PERFORMED,
    #: because the reader that produced them does not declare
    #: CHARACTER_GEOMETRY. NOT a claim that the pages are clean — the check
    #: did not run. An empty list means every page was checked.
    unchecked_overprint_pages: list[int] = field(default_factory=list)

# backend/engine/extractor.py — beside the shredded block, same plumbing
    ed.setdefault("validation_notes", []).append(
        f"page {pages}: overprint detection was NOT PERFORMED — the reader "
        f"used for this document cannot supply character geometry. This does "
        f"not mean the page is clean; it means the check did not run.")
    ed["needs_review"] = True          # see the open question below
    ed.setdefault("validation", {})["unchecked_overprint_pages"] = list(pages)
```

Three properties carry over deliberately: it is a **list of 1-based file page
numbers**, not a boolean, so a mixed-reader document names the pages; it is
plumbed through `ProcessedDocument` → `extractor` → `validation`, adding no new
path; and an **empty list means "checked"**, so the field is safe to read on
documents produced before it existed.

One deliberate difference from `shredded_pages`: that field is populated when
something *was found and repaired*, whereas this one is populated when
something *was not looked at*. The note text has to carry that distinction,
which is why it says "this does not mean the page is clean" in as many words.

⚠ **`needs_review = True` is written above but is NOT settled.** `shredded_pages`
sets it because a shredded page is a page a person should check. Whether "this
reader could not run one of the checks" deserves the same treatment depends
entirely on how many documents arrive that way — see the open question below
and §10.4. If most client documents are scans, setting `needs_review` on every
one of them makes the flag meaningless.

This is also the shape the engine already uses for exactly this situation. An
image upload does not mark each cell's grounding `False`; it floors the whole
document and says why.

**Why this matters more than it first looks**, and the number that decides it:
the gold corpus reports zero overprints across all ten documents, which is why
the first draft of the scoping report called a constant `False` safe. It is not.
Measured on the one real degraded document in the repo:

```
p2 spans=14   words=1064  marked=260   (24%)
p3 spans=90   words=5052  marked=2647  (52%)
TOTAL spans=104 words=6659 marked=2907 (44%)
```

44% of `round2/HTR-043235.pdf` carries the flag, and the flag is what demotes
those values to `low` and sends the document to review. A reader returning a
constant `False` would delete that protection and report a clean document.

**The degradation is loud by construction:** a document read by a source without
`CHARACTER_GEOMETRY` says "overprint detection was not performed on this
document", the same way an image upload says `unverified` rather than claiming a
middling confidence. **It does not say the document is clean.**

**Open question, needs real documents** (`OCR-HANDOFF.md` §7; recorded at §10.4)**:** whether marking a whole class of
documents "not checked" produces a review volume anyone will actually work
through, or whether it becomes noise people learn to dismiss. That is the same
failure the rejected coverage indicator had — *a ratio reading 0.38 on a perfect
invoice trains people to ignore it* — and it cannot be answered without knowing
what proportion of client documents arrive as scans.

---

## 9. Validate the seam with a cheaper second reader than OCR

The seam's design cannot be tested by the reader it already has. But it does
**not** need OCR to be tested, and testing it with OCR first would confound two
unknowns — is the seam right, and does OCR meet it.

A second **pdfplumber-based** source would exercise every part of this proposal
at near-zero cost and with ground truth available, because the same PDF can be
read both ways and the outputs compared directly:

- it declares a coordinate space, so §6's boundary check has two sources to
  reconcile;
- it can be given a **reduced capability set** deliberately — e.g. declaring no
  `SIZE_AWARE_TOKENISATION` — which exercises §8.1's skip-and-say-so path
  against a document where we already know the right answer (`HTR-043235.pdf`
  pages 2 and 3 must lose their warning, and must say they lost it);
- declaring no `CHARACTER_GEOMETRY` exercises §8.2's document-level
  `unchecked_overprint_pages` record against a document whose true overprint
  count we have measured (104 spans) — the per-word flag must stay two-valued
  and the four `is False` asserts must keep passing;
- it adds no dependency.

Candidate shapes, none investigated: a source with different word-grouping
tolerances; a source restricted to `extract_text()` with synthesised boxes; a
deliberately capability-poor wrapper over the existing reader. **The point is
the seam, not the reader** — if a second pdfplumber source cannot be made to
fit, an OCR source certainly will not.

---

## 10. Open questions, all gated on facts we do not have

Per `OCR-HANDOFF.md` §7: there are no client documents in this repo, everything
is measured on 69 PDFs of which 61 are in-house, and first contact with real
client documents will be live. The following cannot be decided here, and the
design deliberately leaves each one open rather than choosing a default that
would look measured:

1. **Can any real reader meet `EDGE_TOL = 1.0pt`?** Decides whether
   `repair_wrapped` runs at all for that reader (§5). Unanswerable without
   scans at a known resolution.
2. **Do client scans contain wrapped-in-a-narrow-box values?** If not, §5 is
   moot. Unknown.
3. **Do glyph boxes from a raster support `CHARACTER_GEOMETRY` meaningfully?**
   Decides whether overprint detection is recoverable or permanently absent for
   scans (§4, §8.2).
4. **What is the scanned proportion, and the handwritten proportion within it?**
   Decides whether "not checked" is a rare annotation or the normal state, which
   decides whether §8's loud degradation is useful or is noise (§8.2).
5. **Does the MICR band need its own capability?** `engine/micr.py` parses E-13B
   from text today. On a scanned cheque the band is an image. Whether that is a
   reader capability, a separate pass, or a different component is not settled
   here, and cheques are central to the client work.
6. **Does a second coordinate source exist that is not pypdf widgets?** The
   audit found exactly one cross-source comparison (§6). If a reader introduces
   others — a table-detection pass, a signature locator — the boundary check has
   to cover them too.
7. **Rotation and skew.** The coordinate declaration covers unit, origin and
   page height; it does **not** cover `/Rotate` or raster skew (§6.1). All 114
   corpus pages are unrotated, so nothing here would catch a regression, and
   deskew is a property of scanning equipment we have never seen. Whether these
   belong in the declaration, in the reader, or in a pre-pass is unresolved.

None of these blocks designing the seam. All of them block choosing its
constants.

---

## 11. What this proposal does not do

- It does not name, recommend or evaluate an OCR engine or library.
- It does not add a dependency.
- It does not change `SHARD_SHRED`, `EDGE_TOL`, `COLUMN_TOL`, `LINE_TOL` or
  `OVERPRINT_TOP_TOL`. Every one of them keeps its current value for the
  pdfplumber reader, and the seam's job is to make sure they keep meaning what
  they say.
- It does not touch the confidence vocabulary. It reuses the distinction that
  vocabulary already draws between *checked and clean* and *not measured*.
- It does not propose a replacement canary for scanned pages (§8.1).
