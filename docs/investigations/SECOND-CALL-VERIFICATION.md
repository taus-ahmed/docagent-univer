# The second-call verification pass — scope, criteria, and what the experiment found

Written 2026-09-16, after DECISION-LOG §22 dissolved I8 and left one problem
standing.

**The problem.** A value read correctly, placed correctly, grounded correctly,
and still answering a different question than the field asked.
`Customer Email Address` = `care@engieresources.com` — the supplier's own
customer-care address, written into the customer's field at `high`, unflagged.
§22 established that no rule over the answer reaches it: every gate the engine
has is a property of **the page**, and this is a property of **the claim**.

The only candidate left is asking the model a second, different question about
a value it has already given, and treating disagreement as the signal.

---

## Decision criteria, stated before the numbers

Fixed in advance so the result has somewhere to land rather than somewhere to
be argued to:

| | |
|---|---|
| **Build it** | catch rate on real instances high **and** false positives on the 115 correct gold values near zero. Wiring: `LOW` + flag, fields only, one call per document, whole-page context. |
| **Do not build it** | either number bad. Record beside the label-witness gate in DECISION-LOG §22 and stop. |
| **Publishable either way** | a 0% catch rate is a result, not a failed gate. It would say this defect is not reachable from inside the model, which is worth knowing and worth writing down. |

---

## Why the expectation was low going in

**The wrong belief is stable across prompt revisions.** `care@engieresources.com`
was returned for `Customer Email Address` by:

| run | commit | conditions |
|---|---|---|
| round-2 run 9 | pre-I1 | the original manual run |
| `run9_engie_BR4_prefix_fe3385d` | `fe3385d` | bill SPLIT at page 4; this answer came from the pages 1-3 document |
| `run9_engie_BR4` (re-record) | `f3d4d4a` | bill NOT split; pages 1-4 in one prompt; post-I10 text layer |

Three runs, two materially different prompts — different document boundaries,
different text for pages 2 and 4 — and the same wrong answer every time. This
is not sampling noise that a second sample would wash out.

**So "ask again and compare" is refuted before it is tried.** The whole
proposal rests on whether *re-framing* the question dislodges a belief that two
prompt revisions did not. That is a real possibility and also a real way to
fail, and the experiment exists to find out which.

---

## The circularity constraint, in the codebase's own words

`app/core/confidence.py` wrote this down before the problem was found, defining
what `GROUNDED` may claim:

> the slot's label was written by the same model chain that produced the value,
> so nothing independent establishes that the value BELONGS there. Grounding
> proves the text came from the page, never that it belongs in that slot —
> **asking the model whether its own answer fits its own label is circular.**

That sentence rules out one of the three candidate questions outright and
shapes the other two.

### Q-B — "does the document answer this field at all?" — RULED OUT

It names the slot and asks the model to adjudicate its own assignment. It is
the circular form exactly as the docstring describes it, and it fails silently
in the case it exists for: a model that believes it found the customer's email
will not report the field as unanswered. Not measured, and should not be.

### Q-A — party and closed-list attribution — MEASURED FIRST

Two questions, both **about the document**, neither about our answer:

1. **party** — whose value is this: the issuer, the recipient, a third party,
   or nobody's?
2. **answers** — which ONE of these field labels does the document present this
   value as answering? (The template's labels, shuffled, `NONE` allowed.)

**The model is never shown which slot the value was written into.** It cannot
agree by reading our answer back; it has to re-derive the assignment from the
page. **We** do the comparison, in code. That is the only thing standing
between this and Q-B, and it is why the design is worth measuring.

It also answers the obvious objection from §22 — that the label-witness gate
failed because a document's own word for a field is a synonym (`No:` for Cheque
Number), an abbreviation (`Total` for Total Earnings) or absent. A **model**
asked which label a value answers can bridge a synonym that string matching
cannot. Whether it does was the first thing to measure.

### Q-C — blind inventory — THE FALLBACK

*"List every email address / tax ID / date printed here, with the label printed
next to each."* Purely extractive, the most independent of the three, and
template-free — it never sees our labels at all, so it cannot be steered by
them. Held in reserve because it needs a per-kind matcher afterwards and only
covers kinds we enumerate in advance, which makes it more code for narrower
coverage. It becomes the front-runner if Q-A's closed list turns out to be
leading the model to the answer rather than testing it.

---

## The experiment

`tests/harness/attribution.py`. Not a pipeline component — nothing in the
engine imports it and nothing it does changes an extraction.

**First call stubbed, second call live.** The first call's answer is what we
control; the verifier is the thing under test, so it runs live. Raw responses
for every call are committed to `tests/fixtures/attribution_raw/`.

**Both arms come off the same calls, and that is sound.** The verifier is never
shown which slot a value went into, so its answer for a value is a function of
(document, value, label list) and nothing else. Injecting a wrong assignment
cannot change what it says. One call per document therefore measures both arms:
the false-positive arm compares its answer to each value's **true** label, the
true-positive arm to the **injected** one. Running 115 near-identical calls to
vary a field the prompt does not contain would have measured sampling noise.

**The injection.** For each gold field slot, a **same-kind value from another
slot of the same document** — a date for a date, a money amount for a money
amount, a name for a name. Every injected value is real, printed, grounded,
correctly typed and correctly placed: the I8 class by construction rather than
by hand. 107 of 115 slots have a same-kind partner.

**The held-out four** are instances the **model itself produced**, not ones we
constructed: `care@engieresources.com` (run 9's own answer) and the three probe
injections recorded in DECISION-LOG §2's 2026-09-15 correction — the supplier's
`Fed. I.D.` as the customer's tax ID, the previous balance as a late fee, the
payment received as a deposit.

**Cost, measured.** 11 live calls, 963-3,217 input tokens each, **$0.0023 in
total**. A verification call on a gold document costs about $0.00014 against
$0.00015 to extract it — roughly a doubling of per-document LLM cost.

---

## Results (2026-09-16, `gemini-2.5-flash-lite`, temperature 0)

### Arm 2 — false positives, the 115 untouched correct values

| signal | false positives | |
|---|---|---|
| **`answers`** (closed-list attribution) | **0 of 115** | **0.0%** |
| **`party`** | **7 of 27** party-bearing slots | 25.9% |
| combined (flag if either disagrees) | 7 of 115 | 6.1% |

**The `answers` signal is clean, and it clears §22's objection outright.** All
33 values the label-witness gate flagged are among these 115, and the model
placed every one of them correctly — `No: CHQ-001847` answers Cheque Number,
`Terms: Net 30` answers Payment Terms, `Total $14,583.33` answers Total
Earnings, an unlabelled name on a cheque answers Payee. A model bridges the
synonym gap that string matching could not. That is the single most useful
thing the experiment established.

**Every one of the 7 party false positives is one document and one error.**
All 7 are `PO-2024-0018`, and all 7 are the same confusion: on a purchase order
the **buyer** issues the document and the **vendor** receives it, and the model
reversed it — calling Pacific Steel (the vendor) the ISSUER and Nexus (the
buyer) the RECIPIENT. It reads a PO as though it were an invoice. ⚠ **There is
exactly one purchase order in the corpus**, so we cannot tell whether this is a
PO-specific confusion that a document-type-aware comparison would fix, or the
visible corner of a general unreliability. That is the single biggest open
question about this design.

### Arm 1 — true positives, 107 same-kind swaps

| | |
|---|---|
| slots with a same-kind partner | 107 of 115 |
| **caught** | **107 (100.0%)** |
| missed | 0 |

By kind: money 48, identifier 25, name/text 24, date 10.

⚠ **Treat this number with suspicion, as planned.** These are assignments *we*
invented; the model never proposed them and has no attachment to them. A
constructed swap is an easy case by construction. It establishes that the
mechanism works and bounds nothing about real errors — which is exactly why the
held-out four exist.

### Held out — four instances the model itself produced

| assigned slot | value | `answers` | `party` | verdict |
|---|---|---|---|---|
| Customer Email Address | `care@engieresources.com` | **"Customer Email Address"** | ISSUER | caught by **party** only |
| Customer Tax ID | `76-0685946` | **"Customer Tax ID"** | THIRD_PARTY | caught by **party** only |
| Late Fee Amount | `$101.99` | `NONE` (printed `Previous Balance`) | RECIPIENT | caught by **answers** only |
| Deposit Amount | `-$101.99` | `NONE` (printed `Payments`) | RECIPIENT | caught by **answers** only |

**4 of 4 caught — but neither signal catches more than half alone, and they are
complementary in a way nobody designed.**

**The strongest finding in the experiment is the self-contradiction.** Asked
about `care@engieresources.com`, the model said in ONE response that it
*answers* `Customer Email Address`, that the label printed beside it is
`Email Us`, and that it belongs to the **ISSUER**. The stability evidence held:
re-framing did **not** dislodge the belief on the `answers` axis — it gave the
same wrong answer a fourth time. What did break was the model's ability to keep
that belief consistent with a second, differently-framed question about the
same value.

So the disagreement worth exploiting is **not** between our assignment and the
model's. It is between two answers the model gives about one value in one
response.

---

## Where this leaves the decision: DO NOT BUILD, on the stated criteria

Against the criteria fixed before the numbers: **false positives are not near
zero on the signal that does the work, so the answer is no.**

- **The `answers` signal alone** is clean — 0 of 115 — and it does not catch the
  flagship instance. Asked a fourth time, in a different frame, the model said
  `care@engieresources.com` answers `Customer Email Address`. Re-framing did
  **not** dislodge the belief on this axis. The stability evidence held.
- **The `party` signal alone** catches `care@` and the supplier's `Fed. I.D.`,
  and is wrong on 7 of 27 party-bearing slots — 25.9%.
- **Combined**, 4 of 4 real instances at 6.1% false positives. Better than the
  label-witness gate's 28.7%, and not near zero.

### The 7 false positives are the model's error, not our map's

This was checked rather than assumed. `PO-2024-0018` is a purchase order: the
**buyer** issues it, the **vendor** receives it. Our comparison map says
`Buyer → ISSUER` and `Vendor → RECIPIENT`, which is right. The model said
`Vendor Name` belongs to the ISSUER and `Buyer Name` to the RECIPIENT — it read
a PO as though it were an invoice, and reversed every party on the document.

A follow-up that looked promising was tried and is **not a different
measurement**: scoring the model's own `answers` label against its own `party`
answer, with no expectation of ours in the loop, returns **the identical 7
rows**, because `answers` agreed with the true label on all 115. There is no
cheaper re-scoring that rescues this. The party judgement itself is what is
unreliable.

⚠ **One purchase order in the corpus.** We cannot tell whether this is a
PO-specific confusion or the visible corner of a general unreliability, and
that is precisely the kind of thing 23 in-house templates were not allowed to
settle for gate rule A either.

### What is worth keeping from the result

Two things, both genuine:

**1. §22's objection is cleared.** A model bridges the synonym gap that string
matching could not: `No:` → Cheque Number, `Terms:` → Payment Terms, `Total` →
Total Earnings, an unlabelled name → Payee, 115 for 115. Anyone who reaches for
the label-witness idea again should know that the rule fails and the *question*
does not.

**2. The model contradicts itself, in one response, on the case that matters.**
Asked about `care@engieresources.com` it said simultaneously that the value
answers `Customer Email Address`, that the label printed beside it is
`Email Us`, and that it belongs to the **ISSUER**. The signal that exists here
is not disagreement between the model and us — it is incoherence inside a
single answer. That is a real phenomenon, recorded with its raw response, and
it is the thread a future attempt should pull.

### What would change the answer

Not a better prompt. **More document types**, so party attribution can be
priced on more than one instance of each. The binding constraint is now the
corpus, not the method: ten documents, nine types, one purchase order. Until
that changes, wiring this would mean shipping a gate whose only measured
failure mode we cannot bound — which is what was refused for the strict span
rule, for gate rule G, and for the label-witness gate.

Until then the honest state is what KNOWN-LIMITATIONS WRONG #3 already says: a
field the document does not answer can be filled from something nearby, and
nothing catches it.
