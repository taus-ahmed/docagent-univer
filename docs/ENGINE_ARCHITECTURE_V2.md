# Engine architecture v2: perception, understanding, verification (Run S)

The engine copies a page into a spreadsheet the way a careful person does.
That person sees the page's regions, pairs each label with its value by
position, reads a table by its printed header row, carries a group header
onto every row of its group, leaves nothing printed in a field or a table
behind, copies labels as printed, and checks the arithmetic. v2 splits that
work into three layers and fixes who is allowed to do what.

```
 PDF / image
     │
 PERCEPTION      deterministic   words + boxes + font, per page, one contract
     │                           (text layer, or OCR word boxes for images)
 UNDERSTANDING   the model       roles and names only: which region is a table,
     │                           which word is a label, what a slot is called
 VERIFICATION    deterministic   every value grounded, every structural token
     │                           accounted for, every printed total reconciled
 result dict (docs/ENGINE-RESULT-CONTRACT.md) → writers
```

## 1. Perception (deterministic)

One contract for every page: a list of words, each `{text, x0, x1, top,
bottom, page, size, fontname}`, grouped into lines (`text_layer.read_page`,
`group_lines`). Sources:

| page | reader | existing module |
|---|---|---|
| native text layer | pdfplumber, size-aware word grouping (I10), wrapped-value repair | `text_layer.py` |
| scan / image / picture on a native page | OCR word boxes through the reader seam | `ocr_source.py`, `core/preprocessor.py` |
| fillable form | AcroForm widgets written into the words at their x | `form_fields.py`, `text_layer.inject_markers` |

**v2 adds (Stage 4):** image cleanup before OCR (watermark and background
suppression, picked by measured accuracy), and a MICR reader for the cheque
band. Both return words in the same contract, so nothing downstream knows
which reader produced them.

Also deterministic and part of perception: page furniture (lines repeated
on several pages, page numbers), paragraph prose, group lines and subtotal
lines (`row_groups.py`), column bands from a printed heading line
(`column_bands`), and the page's gutter.

## 2. Understanding (the model)

The model is asked what things ARE, never what the page SAYS:

* no template: design the template (fields, tables, columns) —
  `shape_inference.infer_template`;
* every case: fill each addressed slot and quote the span it read it from
  (`slot_extractor`).

A value the model returns is a CLAIM about the page. It is kept only as far
as verification can tie it to printed words. When the model and the page
disagree, the page wins where the page is unambiguous (a group line's
identifier, a MICR field, the printed header), and the disagreement is
flagged where it is not.

## 3. Verification (deterministic)

Each check reads the perception layer, never the model's text:

| check | question | module |
|---|---|---|
| grounding | is the quoted span printed, and is the value inside it? | `slot_extractor.verify_span` |
| placement | does the value sit under its column? | `text_layer.check_placement` |
| arithmetic | do rows sum to the printed total, figures equal words? | `source_inventory.row_sum_checks`, `row_groups.apply`, `cheque_amounts` |
| completeness | is every table and section the page prints present? | `source_inventory.coverage` |
| **conservation (v2)** | is every number or word at a structural position in the output, or deliberately excluded? | `conservation.py` (Stage 1a) |
| **reading agreement (v2)** | do the OCR reading and the model's reading agree? | Stage 4d |

Conservation is the general "printed but not extracted" check. A structural
token is a number or a value word on a line that is not page furniture, not
a repeated column heading and not paragraph prose: a group header, a row
cell, a subtotal or total, a labelled field's value. Each one is either held
by a value of the output, named by an existing reason (`not_captured`, an
attention item), or it raises an attention reason naming it. Nothing is
silently dropped.

## Deterministic vs model, at a glance

| decided by code | decided by the model |
|---|---|
| words, boxes, fonts, lines, pages | which region is a table, a field, a list |
| furniture, prose, gutters, column bands | what an unlabelled thing is called |
| group lines, subtotals, totals (by arithmetic) | the slot a printed label answers |
| a group header's identifier vs its name | |
| grounding, placement, sums, conservation | |
| MICR fields and the ABA checksum | |
| the organized layout's cell positions (x/y) | |

## How it plugs into the existing pipeline

No rewrite. `extractor.run_extraction` → `run_slot_extraction` stays the one
path and every addition sits behind an existing interface:

* **Stage 1a** — `conservation.check(page_lines, page_numbers, output)` runs
  next to `source_inventory.coverage` in `run_slot_extraction`; its reasons
  join `attention`, its tokens `not_captured`. Results keep their contract.
* **Stage 1b** — `row_groups.apply` writes the group line's identifier and
  name into two columns from the page; `add_group_column` draws both.
* **Stage 1c** — page recovery (existing) is pointed at the pages
  conservation finds short before the reason is raised.
* **Stage 2** — `organized_layout.py` reads the same perception words; it
  stays behind `?layout=organized`.
* **Stage 4** — `ocr_source` gets a cleanup pass and a MICR reader; the
  words they return go through the same grounding, placement and
  conservation as a text-layer page.

## Guard rails

* Harness floor: 98.7% templated / 98.2% no-template, 17/17 tables.
* `tests/test_engine_generality.py`: no literal from a test document in
  engine code.
* Corpus metrics (`tools/corpus_metrics.py`) are reported on two halves split
  by file name: rules are tuned on `dev` and also reported on `report`.
