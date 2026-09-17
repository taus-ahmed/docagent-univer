# OCR reader-interface scoping — does the word-list contract survive contact with the code?

Investigation only, 2026-09-16 at `d278139`. No code was written, stubbed or
installed; no OCR or vision API was called. Nothing outside this file changed.

**The claim under test**, `docs/OCR-HANDOFF.md` §5:

> OCR is another reader behind the same word-list contract. It returns the same
> dicts with the same keys and the same coordinate space, and `read_page`
> chooses the reader. Nothing downstream learns that OCR happened.

Every finding below shows the command and its real output. Where a finding
contradicts `OCR-HANDOFF.md` or `CLAUDE.md`, both are quoted.

---

## 1. The word dict, exactly

### 1.1 Where `read_page` actually lives — confirmed, not assumed

```
$ grep -rn "def read_page" --include=*.py . | grep -v "\.venv"
./backend/engine/text_layer.py:884:def read_page(page, widgets=(), stats=None):
```

One definition. The handoff's path is correct.

### 1.2 ⚠ The engine does not build the word dict. pdfplumber does.

```
$ sed -n 895,908p backend/engine/text_layer.py
    raw = page.extract_text() or ""
    try:
        words = page.extract_words(extra_attrs=_WORD_ATTRS)
        plain = page.extract_words()
    except TypeError:                     # a reader without extra_attrs
        words = plain = page.extract_words()
    except Exception:
        return raw, [], []
    shard = len(plain) / max(len(words), 1)
    if stats is not None:
        stats["shard_ratio"] = shard
    lines, repairs = repair_wrapped(words)
    lines, placed = inject_markers(lines, widgets)
    stamp_page(lines, getattr(page, "page_number", None))
```

There is no constructor. `read_page` receives a **pdfplumber page object** and
the dicts are pdfplumber's return value, mutated in place afterwards
(`stamp_page` adds `page`, `mark_overprints` adds `overprinted`,
`repair_wrapped` rewrites `text`/`x0`).

The only place the engine creates a word dict from nothing is `inject_markers`,
for AcroForm checkbox markers:

```
$ sed -n 819,823p backend/engine/text_layer.py
        mid = (w["top"] + w["bottom"]) / 2.0
        word = {"text": "[X]" if w["on"] else "[ ]",
                "x0": w["x0"], "x1": w["x1"],
                "top": w["top"], "bottom": w["bottom"]}
```

Note it carries **no `size`** — and the engine does not care (§2.2).

### 1.3 The real key set is 12 fields, not 7

```
$ python -c "... pg.extract_words(extra_attrs=['size'])[0] ... read_page(pg)"
extract_words(extra_attrs=["size"]) key set:
   text               'FIRST'
   x0                 12.96
   x1                 41.85
   top                11.509999999999991
   doctop             11.509999999999991
   bottom             21.50999999999999
   upright            True
   height             10.0
   width              28.89
   direction          'ltr'
   size               10.0

after read_page, a word carries: ['bottom', 'direction', 'doctop', 'height',
 'page', 'size', 'text', 'top', 'upright', 'width', 'x0', 'x1']
```

`OCR-HANDOFF.md` §5 lists seven fields:

> ```python
> {"text": str, "x0": float, "x1": float, "top": float, "size": float,
>  "page": int, "overprinted": bool}
> ```

**Contradiction.** `bottom` is missing from that list and **is consumed**
(§1.4). `doctop`, `height`, `width`, `upright`, `direction` are present and
unconsumed.

### 1.4 Consumers of each key — every reader, exact file:line

```
$ for k in text x0 x1 top size page overprinted; do grep -rn "\[\"$k\"\]\|get(\"$k\"" \
    --include=*.py backend/engine backend/app; done
```

| field | consumer count | consumer files (readers only) |
|---|---|---|
| `text` | 20 | `text_layer.py` 207, 218, 220, 221, 237, 295, 326, 465, 469, 485, 487, 489, 672, 712, 736, 961, 1044, 1050, 1076, 1111, 1131, 1156, 1161 |
| `x0` | 21 | `text_layer.py` 34, 35, 174, 180, 183, 216, 276, 281, 377, 378, 452, 614, 615, 629, 634, 648, 836, 1133, 1152, 1157, 1162 |
| `x1` | 13 | `text_layer.py` 35, 214, 281, 378, 452, 614, 615, 629, 635, 648, 1133, 1157, 1162 |
| `top` | 9 | `text_layer.py` 174, 175, 627, 636, 648, 819, 827, 828, 838 |
| `bottom` | 3 | `text_layer.py` 819, 822, 828 (`x.get("bottom", x["top"] + 10)`) |
| `size` | **0 on words** | only `text_layer.py:606` on `page.chars`, and `text_layer.py:867` as an **input** to `extract_words` |
| `page` | 1 | `text_layer.py:996` (`line_page`); written at 990 |
| `overprinted` | 1 | `text_layer.py:734` (`overprinted_value`); written at 653 |

**Every coordinate consumer is inside `text_layer.py`.** Confirmed by grepping
the downstream modules:

```
$ grep -rn 'w\["\|word\["\|\["top"\]\|\["x0"\]' backend/engine/slot_extractor.py \
    backend/engine/doc_boundaries.py backend/engine/shape_inference.py \
    backend/engine/template_shape.py
backend/engine/slot_extractor.py:1246:                row["_confidence"] = row_conf
backend/engine/slot_extractor.py:1249:                row["_source"] = source
backend/engine/slot_extractor.py:1250:                row["_page"] = page_of(...)
backend/engine/slot_extractor.py:1253:                    row["_ungrounded"] = unverified_cols
```

Those are result rows, not word dicts. Nothing outside `text_layer.py` indexes
a word. That is the single most favourable fact for the handoff's design
intent.

---

## 2. Load-bearing vs cosmetic

### 2.1 `x0` / `x1` / `top` — the tolerances, in points

```
$ grep -n "^LINE_TOL\|^EDGE_TOL\|^COLUMN_TOL\|^OVERPRINT\|^SHARD\|^GUTTER" backend/engine/text_layer.py
18:GUTTER_MULTIPLE = 4.0
21:GUTTER_FLOOR = 6.0
27:GUTTER = 24.0
101:LINE_TOL = 3.0
106:EDGE_TOL = 1.0
111:COLUMN_TOL = 2.0
534:OVERPRINT_FRAC = 0.5
538:OVERPRINT_MIN_RUN = 3
545:OVERPRINT_TOP_TOL = 1.0
881:SHARD_SHRED = 1.05
```

The actual comparison lines:

```
$ sed -n 214,216p backend/engine/text_layer.py
                if abs(float(c["x1"]) - float(w["x1"])) > EDGE_TOL:
                    continue
                if float(c["x0"]) < float(w["x0"]) - 0.5:

$ sed -n 627,629p backend/engine/text_layer.py
                    if abs(float(a["top"]) - float(b["top"])) > OVERPRINT_TOP_TOL:
                        continue
                    if float(a["x1"]) - float(b["x0"]) > OVERPRINT_FRAC * narrow:

$ sed -n 1198,1200p backend/engine/text_layer.py
        if abs(span[1] - band[1]) <= COLUMN_TOL:
            continue                                   # flush right: correct
        if span[0] < band[1] and band[0] < span[1]:
```

`EDGE_TOL`'s own docstring sets the bar:

> Measured on FORM-W2-2023, every genuine fragment matched to **0.0pt**; the
> tolerance is for rounding, not for guessing.

Against OCR bounding-box precision:

```
$ python -c "for dpi in (150,200,300,400,600): ..."
 150 dpi : 1 pt =   2.08 px | 1 px = 0.480 pt | EDGE_TOL 1.0pt=  2.1px  COLUMN_TOL 2.0pt=  4.2px  LINE_TOL 3.0pt=  6.2px  OVERPRINT_TOP_TOL 1.0pt=  2.1px
 200 dpi : 1 pt =   2.78 px | 1 px = 0.360 pt | EDGE_TOL 1.0pt=  2.8px  COLUMN_TOL 2.0pt=  5.6px  LINE_TOL 3.0pt=  8.3px  OVERPRINT_TOP_TOL 1.0pt=  2.8px
 300 dpi : 1 pt =   4.17 px | 1 px = 0.240 pt | EDGE_TOL 1.0pt=  4.2px  COLUMN_TOL 2.0pt=  8.3px  LINE_TOL 3.0pt= 12.5px  OVERPRINT_TOP_TOL 1.0pt=  4.2px
 400 dpi : 1 pt =   5.56 px | 1 px = 0.180 pt | EDGE_TOL 1.0pt=  5.6px  COLUMN_TOL 2.0pt= 11.1px  LINE_TOL 3.0pt= 16.7px  OVERPRINT_TOP_TOL 1.0pt=  5.6px
 600 dpi : 1 pt =   8.33 px | 1 px = 0.120 pt | EDGE_TOL 1.0pt=  8.3px  COLUMN_TOL 2.0pt= 16.7px  LINE_TOL 3.0pt= 25.0px  OVERPRINT_TOP_TOL 1.0pt=  8.3px
```

So at 300dpi one pixel of quantisation is **0.24pt**, and the tightest
tolerance in the engine, `EDGE_TOL`, is **4.2 pixels** wide. The headroom is
real but not generous: a wrapped-value repair requires the fragment's right
edge within ~4px of its parent's, on a reader whose glyph boxes are produced by
a segmentation model rather than by a font matrix.

### 2.2 `size` — never read from a word

```
$ grep -rn '\["size"\]\|get("size"' --include=*.py backend/engine backend/app
backend/engine/connectors/gdrive.py:228:   size=int(f.get("size", 0)),          # a Drive file size, unrelated
backend/engine/text_layer.py:606:   by_size.setdefault(round(float(c.get("size", 0)), 1), []).append(c)
backend/engine/text_layer.py:867:_WORD_ATTRS = ["size"]
backend/app/api/routes/extract.py:6547:   if style.get("fontSize"): fk["size"]=style["fontSize"]   # an Excel cell style
```

Line 606 reads `size` off **`page.chars`**, not off a word. Line 867 passes it
as an argument so that **pdfplumber splits words on a size change**. No code
anywhere reads `w["size"]`.

Proven by exercising the fallback branch:

```
$ python -c "...class NoAttrs: extract_words raises TypeError when given kwargs..."
--- a reader without extra_attrs (TypeError branch) ---
words have size key? [{'text', 'page', 'x0', 'x1', 'top'}]
```

`read_page` completes and returns usable lines from words that **have no
`size` key at all**. `size` is an input to grouping, not an output of the
contract.

Is a bbox-height surrogate safe? Measured:

```
$ python -c "... compare w['size'] vs w['height'] ..."
round2/HTR-043235.pdf      p3 words=5052 size==height: 4899 (97%)
      mismatches (size,height): [((2.4, 5.7), 96), ((2.4, 9.1), 57)]
round2/SampleBill.pdf      p4 words=245  size==height: 245 (100%)
CHQ-001847.pdf             p1 words=83   size==height: 83 (100%)
```

97% agreement in general, and the 153 disagreements are all the 2.4pt legal
layer on HTR page 3 — **the exact page the size-awareness was built for**
(DECISION-LOG §21). A height surrogate would merge that layer back into the
5.7/9.1pt text and reintroduce I10 there. It would do so silently, because
nothing asserts a size.

This is moot for a scan, which is one flattened image with no overlapping type
runs, but it is not moot for a hybrid page.

⚠ **The above covers `size` as a consumed field only. That is the smaller half
of the story — see §2.5, which is a separate and larger finding.**

### 2.3 `overprinted` — one producer, one consumer, and always-False is NOT safe

```
$ sed -n 648,654p backend/engine/text_layer.py
                wx0, wx1, wt = float(w["x0"]), float(w["x1"]), float(w["top"])
            ...
                if wx0 < x1 and x0 < wx1 and abs(wt - top) <= LINE_TOL:
                    w["overprinted"] = True

$ grep -rn 'get("overprinted"' --include=*.py backend/
backend/engine/text_layer.py:734:            if not w.get("overprinted"):
```

`True` is produced only by `mark_overprints` from `overprinted_spans(page)`,
which reads `page.chars` and requires ≥3 overlapping character pairs **at the
same font size within 1.0pt of one baseline**.

Does any document need it True to score correctly?

```
$ python -c "... overprinted_spans over the 10 gold PDFs ..."
BS-2024-Q1                   spans=0   words_marked=0
CHQ-001847                   spans=0   words_marked=0
EXP-2024-0081                spans=0   words_marked=0
INV-2024-0031                spans=0   words_marked=0
INV-2024-0047                spans=0   words_marked=0
IS-2024-Q4                   spans=0   words_marked=0
PAYSLIP-EMP-0007-APR2024     spans=0   words_marked=0
PAYSLIP-EMP-0012-APR2024     spans=0   words_marked=0
PO-2024-0018                 spans=0   words_marked=0
STMT-2024-01                 spans=0   words_marked=0
TOTAL overprint spans across the 10 GOLD documents: 0
```

**Zero across the whole gold corpus** — but that is a narrower result than it
first appears, and stating it alone was an error. **The gold corpus
structurally excludes the one file in the repo already known to trigger
overprint tagging.** `HTR-043235.pdf` is a round-2 evidence document, not a
gold-labelled one, so measuring "does any gold document need this" cannot
reach it. Measured directly, per `OCR-HANDOFF.md` §6:

```
$ python -c "... overprinted_spans + read_page per page of round2/HTR-043235.pdf ..."
p1 spans=0    words=227   marked=0     (0%)
p2 spans=14   words=1064  marked=260   (24%)
p3 spans=90   words=5052  marked=2647  (52%)
p4 spans=0    words=316   marked=0     (0%)
TOTAL spans=104 words=6659 marked=2907 (44%)
```

Page 3 is **2,647 of 5,052 words tagged, 52%**, confirming §6's figure exactly,
and page 2 adds a further 260. Document-wide, **44% of words carry the flag**.

**What the corrected claim is.** Constant `False` moves no number in the
**97.2% / 96.7% accuracy figures**, because those are computed only from the
ten gold documents and none of them carries an overprint. It does **not**
follow that constant `False` is safe. On the single most degraded real document
in the repo, the flag is what demotes values read off merged layers to `low`,
raises them in `flagged_fields`, and pushes the document to review — 44% of its
words. A reader that always returns `False` deletes that protection silently.

The asymmetry matters: OCR reading a scan of such a page does not *avoid* the
problem, it only stops being able to *report* it. The overlapping layers are
still on the paper, the OCR still produces a reading of them, and the one
mechanism that currently says "these words are not trustworthy" returns
`False` for every word. The garbage still arrives; the warning does not.

Whether an OCR reader could reconstruct an equivalent signal by other means is
unresolved and not investigated here. What is established is that "structurally
cannot produce overprints, so `False` is a safe default" is **true about the
gold accuracy numbers and false about the corpus**.

The one test that demands overprints exercises a digital PDF
through pdfplumber directly and does not involve a reader seam:

```
$ sed -n 141,147p tests/test_round2_regressions.py
    def test_it_still_fires_where_it_must(self, pdf_dir):
        import pdfplumber
        with pdfplumber.open(pdf_dir / ROUND2 / "HTR-043235.pdf") as pdf:
            spans = [s for p in pdf.pages for s in overprinted_spans(p)]
        assert len(spans) > 50, (
            "the one document with genuine same-size overprinting reports "
            "none — the detector has been turned into dead code")
```

### 2.4 `page` — reader-independent, confirmed

```
$ sed -n 908p backend/engine/text_layer.py
    stamp_page(lines, getattr(page, "page_number", None))

$ sed -n 984,991p backend/engine/text_layer.py
def stamp_page(lines, page_number):
    """Record the 1-based file page on every word of `lines`, in place."""
    if page_number is None:
        return
    for ln in lines:
        for w in ln:
            w["page"] = int(page_number)
```

Stamped by `read_page` after the reader has returned, from
`page.page_number`. A reader never supplies it. **Handoff correct.**

### 2.5 ⚠ `size` is a MECHANISM, not a field, and the mechanism does not port

§2.2 establishes that nothing reads `w["size"]`. That result is true and it is
not the important one, because `size` does its work **before** any word exists:
it is the argument that makes pdfplumber tokenise differently.

```
$ sed -n 897,903p backend/engine/text_layer.py
        words = page.extract_words(extra_attrs=_WORD_ATTRS)
        plain = page.extract_words()
    ...
    shard = len(plain) / max(len(words), 1)
```

Two calls to the **same reader over the same page**, one told to respect font
size and one not. The engine does not use `size` to describe a word; it uses
the *difference between two tokenisations* as a measurement. That difference
is the shredded-text-layer detector, in its entirety.

Measured:

```
$ python -c "... extract_words() vs extract_words(extra_attrs=['size']) per page ..."
SHARD_SHRED = 1.05
round2/HTR-043235.pdf    p1  without_size=222   with_size=227   ratio=0.98
round2/HTR-043235.pdf    p2  without_size=1213  with_size=1064  ratio=1.14  <== REBUILD
round2/HTR-043235.pdf    p3  without_size=12694 with_size=5052  ratio=2.51  <== REBUILD
round2/SampleBill.pdf    p1  without_size=306   with_size=306   ratio=1.00
round2/SampleBill.pdf    p2  without_size=505   with_size=508   ratio=0.99
round2/SampleBill.pdf    p3  without_size=436   with_size=436   ratio=1.00
CHQ-001847.pdf           p1  without_size=83    with_size=83    ratio=1.00
```

What the two tokenisations actually look like, one y-band of HTR page 3:

```
$ python -c "... words with 110 < top < 118, both ways ..."
one y-band, WITHOUT size (467 tokens):
    ['0', 'D', 'D', 'T00', 'D', 'a', '7', '777a', '77', 'a', 't', 'Ht', '/', '//', '/e', 'a2', '22', '0', '90', '/', '//', 'T1']
one y-band, WITH size (142 tokens):
    ['07/20/12', '07/', '20', 'Bank', 'of', 'America', 'ATM', '/', 'US', 'Gas', 'Remote', 'Salem', '#0000004022', '-', '80.00', 'Date', 'Descript', 'ion', 'Amount', 'Date', 'Descripti', 'on']
   sizes present: [2.4, 3.7, 4.9, 5.5, 5.8]
```

**An OCR reader has no equivalent second pass to diff against.** It performs
one segmentation and returns one tokenisation. There is no "the same reader,
told to ignore font size" to compare it to, because OCR never had font size to
respect or ignore — it has glyph bounding boxes, and a bbox-height surrogate
(§2.2) is derived from the *same* segmentation, so diffing a reading against a
surrogate of itself measures nothing.

Three consequences, in increasing order of size:

1. **`shard_ratio` cannot be computed.** It is a ratio between two readings
   that an OCR reader cannot produce.
2. **The rebuild decision cannot be made.** `read_page` returns `extract_text()`
   verbatim unless the page is shredded (line 930); with no ratio there is no
   basis for that branch.
3. **The detector's subject disappears along with its mechanism.** The
   shredded-layer warning exists because a size-blind reading shatters
   overlapping type runs. OCR on a scan of the same page does not shatter it —
   it produces one plausible-looking reading of visually overlapping text, with
   no signal that anything overlapped.

This is **separate from, and larger than, §2.2's "no downstream consumer"
result.** §2.2 says an OCR reader need not populate a field. §2.5 says a
detector the engine currently relies on has no implementation on the OCR path
at all — not a field to fill, a measurement that cannot be taken. It is also
distinct from §5.2: §5.2 says the detector is *blind to* thin OCR layers;
§2.5 says the detector *cannot run* on an OCR reader.

Note the direction of the coupling. `OCR-HANDOFF.md` §5 frames the contract as
"the same dicts with the same keys". `size` is neither — it is an argument to
the reader, and two of the engine's protections are built on being able to call
the reader twice with it set differently.

---

## 3. Coordinate space

### 3.1 pdfplumber's convention, proven from code

`top` is measured **downward from the top of the page**, in **points**. The
proof is the AcroForm path, which converts *into* that convention from PDF user
space (bottom-left origin, y increasing upward):

```
$ sed -n 773,799p backend/engine/text_layer.py
        from pypdf import PdfReader
    ...
            height = float(page.mediabox.height)
    ...
            x0, x1 = min(rect[0], rect[2]), max(rect[0], rect[2])
            y0, y1 = min(rect[1], rect[3]), max(rect[1], rect[3])
            items.append({"x0": x0, "x1": x1,
                          "top": height - y1, "bottom": height - y0,
```

`height - y1` is the flip. `page.mediabox` is in PDF points by definition, and
the result is compared directly against pdfplumber `top` values, so both sides
are points, top-down.

`page.mediabox.height` is the only place a page dimension is read anywhere in
`backend/engine` or `backend/app`:

```
$ grep -rn "\.height\|mediabox" --include=*.py backend/engine backend/app | grep -v excel_writer | grep -v export.py
backend/engine/text_layer.py:775:            height = float(page.mediabox.height)
```

### 3.2 Cross-source coordinate comparisons — there is exactly one

```
$ sed -n 819,838p backend/engine/text_layer.py
        mid = (w["top"] + w["bottom"]) / 2.0
        ...
            top = min(float(x["top"]) for x in ln)
            bottom = max(float(x.get("bottom", x["top"] + 10)) for x in ln)
            if top - LINE_TOL <= mid <= bottom + LINE_TOL:
                target = ln
            ...
            target.sort(key=lambda x: float(x["x0"]))
```

`inject_markers` compares **pypdf widget rectangles** (converted, points)
against **pdfplumber word coordinates** (points). This is the one place a
coordinate from a different source meets a word coordinate, and it is the one
place a reader returning pixels instead of points would misalign silently —
the comparison is an inequality against `LINE_TOL`, so a unit mismatch produces
a wrong line assignment, never an exception.

Declared template regions are **not** page coordinates and never touch a word:
they are grid cell indices `(r1, c1, r2, c2)`, per `CLAUDE.md` ("Regions are
absolute `(r1,c1,r2,c2)`"), and no region code appears in the `x0` consumer
list in §1.4.

---

## 4. Coupling to `read_page`

### 4.1 Call sites

```
$ grep -rn "read_page" --include=*.py . | grep -v "\.venv" | grep -v "def read_page"
```

**One production caller.** `backend/engine/core/preprocessor.py:21` (import)
and `:164` (call). Everything else — 30 further call sites — is in `tests/` or
`tests/harness/`.

```
$ sed -n 145,166p backend/engine/core/preprocessor.py
    # Step 1: Extract text from ALL pages using pdfplumber
        with pdfplumber.open(file_path) as pdf:
    ...
            for page_num, page in enumerate(pdf.pages):
                stats = {}
                text, lines, repairs = read_page(page, widgets.get(page_num) or [],
                                                 stats=stats)
```

No caller branches on which reader ran. The return triple is consumed
opaquely. **Handoff correct on the downstream half.**

### 4.2 ⚠ But `read_page` does not choose a reader — it *is* the pdfplumber reader

`read_page(page, widgets=(), stats=None)` takes no reader argument, and the
sole production caller hands it `pdf.pages` from `pdfplumber.open`. Inside, it
calls **four distinct pdfplumber APIs** on that object:

| line | API |
|---|---|
| 895 | `page.extract_text()` |
| 897 | `page.extract_words(extra_attrs=["size"])` |
| 908 | `page.page_number` |
| 581 (via `overprinted_spans(page)` at 910) | `page.chars` |

`OCR-HANDOFF.md` §5 says:

> It returns the same dicts with the same keys and the same coordinate space,
> and **`read_page` chooses the reader**.

**There is no such choice in the code.** No reader parameter, no dispatch, no
abstraction. An OCR reader cannot "return a word list" into this design — it
would have to present an object that satisfies all four pdfplumber APIs,
including `chars`, which is character-level and has no OCR analogue at all.

### 4.3 A page with no extractable text

Confirmed by exercising the path, since no such page exists in the corpus
(§5.2):

```
$ python -c "class EmptyPage: extract_text->None, extract_words->[] ..."
--- a page with no extractable text ---
read_page -> ('', [], [])
_recovered_words_missing("", []) -> False
```

Empty text, empty lines, no repairs, no exception. **Handoff correct**: a
scanned page today produces no words, silently.

---

## 5. The two known gaps, verified

### 5.1 `_is_text_pdf` has zero callers

```
$ grep -rn "_is_text_pdf" --include="*.py" . | grep -v "/.venv/"
./backend/app/api/routes/extract.py:99:def _is_text_pdf(file_path: Path, min_chars: int = 80) -> bool:
[exit 0]
```

Full output, one line: the definition. **Zero callers. Confirmed.**

### 5.2 The shredded-layer warning cannot see a thin OCR layer

The ratio is computed from **two readings of the same page**:

```
$ sed -n 897,903p backend/engine/text_layer.py
        words = page.extract_words(extra_attrs=_WORD_ATTRS)
        plain = page.extract_words()
    ...
    shard = len(plain) / max(len(words), 1)
```

`SHARD_SHRED = 1.05`. The numerator and denominator come from the same text
layer, so the measure is *internal consistency*, not *quantity*. A layer with
few words that are consistently grouped scores 1.00 no matter how little of the
page it covers — there is no page-coverage or word-count term anywhere in the
expression.

Measured across all 69 corpus PDFs:

```
$ python -c "... read_page per page, count words and images ..."
PAGES WITH ZERO WORDS: 0
THIN LAYER OVER IMAGES (<200 words, >=1 image): 5
    201403_cfpb_closing-disclosure_cover-H25B.pdf p1  words=77   images=6   shard=1.01
    201403_cfpb_closing-disclosure_cover-H25E.pdf p1  words=91   images=6   shard=1.01
    201403_cfpb_loan-estimate_fixed-rate-loan-sample-H24B.pdf p1  words=114  images=6   shard=1.01
    bank-statement-sample.pdf          p1  words=108  images=66  shard=1.00
```

`bank-statement-sample.pdf` — 108 words over 66 images — scores **1.00**,
against a 1.05 threshold. Confirmed independently of the handoff.

---

## 6. DECISION-LOG check

```
$ grep -rni "\bocr\b\|scanned\|\bscan\b" docs/DECISION-LOG.md
214:scan, its band-end rule, its region guard, ...        (unrelated: "scan" of a grid)
1114:a scan that found nothing would be indistinguishable from a broken scan, so the
1322:⚠ **IT DOES NOT DETECT A SCANNED DOCUMENT**, and the warning text says so.
1323:`round2/bank-statement-sample.pdf` is 108 words over 66 images — a scan with a
1325:signals. Treating this one as the OCR canary would give false assurance, which
```

**Nothing about an OCR reader design has been proposed or rejected.** The only
OCR-adjacent decision is the disclaimer on the shredded-layer warning, quoted
in full:

> ⚠ **IT DOES NOT DETECT A SCANNED DOCUMENT**, and the warning text says so.
> `round2/bank-statement-sample.pdf` is 108 words over 66 images — a scan with a
> thin text layer — and scores **1.00**. Two different failures, two different
> signals. Treating this one as the OCR canary would give false assurance, which
> is why the disclaimer is in the log line, in the note, and in
> `docs/KNOWN-LIMITATIONS.md` rather than only here.

There is therefore nothing here being re-derived from scratch, and nothing
previously rejected that a reader design would contradict.

---

## 7. Test-suite check

```
$ grep -rn 'assert.*\["x0"\]\|assert.*\["x1"\]\|assert.*\["top"\]\|assert.*\['"'"'x0'"'"'\]' tests/
(no output)
```

**No test asserts an exact or sub-pixel coordinate value.** The coordinate
assertions that exist are relative:

```
$ sed -n 230,234p tests/test_text_layer.py
        bands = column_bands(stmt_lines, HEADERS)
        assert set(bands) == set(HEADERS)
        # right-aligned money columns, left to right and non-overlapping
        assert bands["Debit"][1] < bands["Credit"][1] < bands["Balance"][1]
```

Ordering, set membership and tolerance-bounded verdicts from
`check_placement`. A coarser-precision reader would not fail these on precision
alone. **This is a clean result and the one place the test design is already
OCR-ready.**

### Incidental finding, outside the brief but in the same code

`GUTTER_MULTIPLE`, `GUTTER_FLOOR`, `GUTTER` and `_MIN_GAPS_FOR_MEDIAN` are each
defined **twice** in `text_layer.py`, at lines 18-27 and again at 361-372. The
second definition wins at import:

```
$ python -c "import text_layer as t; print(t._MIN_GAPS_FOR_MEDIAN)"
_MIN_GAPS_FOR_MEDIAN at runtime = 3 (first definition says 8, second says 3)
gutter_for_page references _MIN_GAPS_FOR_MEDIAN: True
```

`gutter_for_page` is documented against 8 and runs against 3. Not an OCR
finding and not investigated further; flagged because it lives in the gutter
arithmetic that OCR word spacing will exercise.

---

## The contract table

**The 12 keys a word actually carries after `read_page`**, named in full
(§1.3): `text`, `x0`, `x1`, `top`, `bottom`, `doctop`, `height`, `width`,
`size`, `upright`, `direction`, `page`. A 13th, `overprinted`, is present only
on words `mark_overprints` has tagged. Of these, **six are read**
(`text`, `x0`, `x1`, `top`, `bottom`, `page`) and **five are never read
anywhere** (`doctop`, `height`, `width`, `upright`, `direction`); `size` is
read zero times as a field and is load-bearing as a reader *argument* (§2.5).

`OCR-HANDOFF.md` §5 names seven: `text`, `x0`, `x1`, `top`, `size`, `page`,
`overprinted`. It omits `bottom`, which is consumed, and the five unconsumed
ones.

| field | consumer count | tolerance / precision required | can an OCR reader supply this as specified? |
|---|---|---|---|
| `text` | 20 readers, all `text_layer.py` (207…1161) | exact string; `_flat()` normalises punctuation/case at 1028 | **yes** — this is what OCR produces |
| `x0` | 21 readers (`text_layer.py` 34…1162) | ordering + `GUTTER_FLOOR` 6.0pt, `0.5pt` slack at 216 and 1152 | **yes** — coarse; 6.0pt = 25px @300dpi |
| `x1` | 13 readers (`text_layer.py` 35…1162) | **`EDGE_TOL` 1.0pt** at 214 (docstring: genuine fragments matched at 0.0pt); `COLUMN_TOL` 2.0pt at 1198 | **yes-with-risk** — 1.0pt = 4.2px @300dpi; tightest constraint in the engine |
| `top` | 9 readers (`text_layer.py` 174…838) | `LINE_TOL` 3.0pt at 178/829, `OVERPRINT_TOP_TOL` 1.0pt at 627 | **yes** — 3.0pt = 12.5px @300dpi |
| `bottom` | 3 (`text_layer.py` 819, 822, 828) | only for widget-line matching; **already has a fallback** `x.get("bottom", x["top"] + 10)` at 828 | **yes** — and optional. ⚠ absent from OCR-HANDOFF.md's field list |
| `size` (as a **field**) | **0 on words**; read only from `page.chars` at 606 | none — nothing reads it | **not required.** Proven: the `TypeError` branch yields words with no `size` key and `read_page` completes |
| `size` (as a **reader argument**) | drives `extract_words` tokenisation at 867/897; the two-pass diff at 903 **is** `shard_ratio` | the reader must be callable twice, size-respecting and size-blind, over one page | **no — see §2.5.** OCR performs one segmentation; there is no second reading to diff. `shard_ratio`, the rebuild branch and the shredded-layer detector have no OCR implementation |
| `page` | 1 (`text_layer.py` 996) | integer, 1-based file page | **n/a** — stamped downstream at 908/990, never supplied by a reader |
| `overprinted` | 1 (`text_layer.py` 734) | boolean | **no, not as constant False — see §2.3.** 0 spans across the 10 gold documents, but **104 spans and 2,907 of 6,659 words (44%) on `round2/HTR-043235.pdf`**, 52% on page 3 alone. Constant `False` moves no gold accuracy number and silently removes the only signal protecting the most degraded real document in the repo |

---

## What breaks the contract

Six findings from §1-7 are not a clean yes.

**1. There is no reader seam to implement against (§4.2).** `read_page` takes a
pdfplumber page and calls `extract_text()`, `extract_words(extra_attrs=…)`,
`.chars` and `.page_number` on it. An OCR reader cannot satisfy "return the
same dicts" because nothing in the code accepts dicts — the entry point accepts
a page object. `.chars` is the hard one: it is character-level with per-glyph
`size`, and it is what `overprinted_spans` needs. Any reader seam has to be
created first, and creating it means deciding what `overprinted_spans` does
when there are no chars.

**2. `EDGE_TOL = 1.0pt` is the tightest constraint and it guards a
value-rewriting operation (§2.1).** `repair_wrapped` *fuses two words into one*
when a fragment's right edge is within 1.0pt of its parent's — 4.2 pixels at
300dpi. Its docstring records that every genuine fragment matched at 0.0pt, so
the tolerance was never sized for reader noise. Too loose and it invents a
figure; too tight and it misses a repair. This is the one place coordinate
noise changes a *value* rather than a *verdict*.

**3. The one cross-source coordinate comparison fails silently on a unit
mismatch (§3.2).** `inject_markers` compares converted pypdf widget rectangles
against word coordinates using `LINE_TOL` inequalities. A reader returning
pixels rather than points would assign markers to wrong lines and never raise.

**4. `size` is not what the handoff says it is (§2.2), and the handoff's field
list is incomplete (§1.3).** `size` is an argument to pdfplumber's grouping,
never a consumed field; `bottom` is consumed and undocumented. A reader built
to the handoff's seven-field spec would supply a field nothing reads and omit
one that three call sites use.

**5. The shredded-layer detector's mechanism does not port at all (§2.5).**
`shard_ratio` is the ratio between two readings of one page by one reader,
size-respecting and size-blind. An OCR reader performs one segmentation and has
no second reading to diff — and a bbox-height surrogate is derived from that
same segmentation, so diffing against it measures nothing. This takes with it
`shard_ratio`, the `read_page` rebuild branch, and the `[TEXTLAYER] … SHREDDED
TEXT LAYER` warning. It is larger than finding 4: that is a field nobody reads,
this is a protection with no implementation on the OCR path.

**6. `overprinted` cannot be held constant False (§2.3).** The gold corpus
reports zero, which is why the first version of this report called the default
safe — but gold structurally excludes `round2/HTR-043235.pdf`, which carries
104 spans and 2,907 tagged words, 44% of the document and 52% of page 3. The
flag is what demotes those values to `low` and sends the document to review.
OCR on a scan of such a page does not avoid the overlap; it loses the ability
to report it.

Everything else checks out: coordinate consumption is wholly contained in
`text_layer.py`, no downstream module indexes a word, no caller branches on the
reader, `page` is stamped independently, and no test asserts an exact
coordinate.

---

## What OCR-HANDOFF.md got right vs wrong

### Right

| §5 claim | verdict |
|---|---|
| "The engine does not read text. It reads words with positions" | **correct** — §1.4, and all 66 coordinate reads are in one file |
| "Nothing downstream learns that OCR happened" | **correct for the downstream half** — one production caller, consumed opaquely, no reader branch (§4.1) |
| `page` "stamped by stamp_page downstream, not by the reader itself" | **correct** — §2.4 |
| "A scan has none of it… a scanned page today produces no words" | **correct** — `read_page` returns `('', [], [])` (§4.3) |
| "`_is_text_pdf` … called from nowhere" | **correct** — §5.1, zero callers |
| "the shredded-layer warning … silent on a thin OCR layer" | **correct** — 1.00 measured against a 1.05 threshold (§5.2). ⚠ and worse than stated: §2.5 finds the detector cannot run on an OCR reader at all |
| §6: "52% of that page's words are overprint-tagged" (HTR p3) | **correct** — 2,647 of 5,052 measured (§2.3). This report's first version missed it by measuring gold only |

### Wrong

| §5 claim | what the code says |
|---|---|
| "**`read_page` chooses the reader**" | No reader parameter and no dispatch exists. `read_page` *is* the pdfplumber reader and calls four pdfplumber-specific APIs, including `page.chars`. The seam the sentence describes has not been built (§4.2) |
| "It returns the same dicts with the same keys" | The engine never builds those dicts; pdfplumber does, and `read_page` mutates them. There is no interface to return dicts *to* (§1.2) |
| The 7-field dict `{text, x0, x1, top, size, page, overprinted}` | The real dict has **12** keys. `bottom` is consumed at three call sites and is missing from the list; `doctop`, `height`, `width`, `upright`, `direction` are present and unconsumed (§1.3) |
| `size` listed as part of the contract | **Zero word-level consumers** (§2.2) — but the handoff under-states it in the other direction too. `size` is an argument the reader must accept and be callable twice with, and two protections are built on that (§2.5). It belongs in the contract as a *capability*, not as a key |

The design intent survives in its important half — the downstream engine really
is indifferent to where words come from, and that is worth more than the
inaccuracies cost. What does not survive is the premise that the seam already
exists and only needs a second implementation behind it.

No OCR engine, library or build plan is recommended here; that decision follows
review of this report.
