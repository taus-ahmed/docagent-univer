# Organized layout — spec (Run R, Part 2)

An export mode that prints a document **the way it is printed**: its labels
and values where the page has them, its tables with their own headings, its
spacing and its type. Behind an option, **off by default**
(`GET /api/jobs/{id}/export?layout=organized`); the default export is
unchanged. Target: `local_docs/syed/syed_sheet1_job127.xlsx`, sheet
`Sheet1` (utah_paystub_2), against today's sheet `Pay Stub`.

## Scope of v1

No-template documents with a **text layer** (native, or an embedded OCR
layer such as utah_paystub_2's). Built and tested on pay stubs:
utah_paystub_1, utah_paystub_2, saltlake_paycheck, ou_check_stub. Every value
is the page's own text (no model call); the extraction is not consulted.

## Rules

1. **Words, then segments.** Words come from the text layer with their font
   (bold / italic from the font name, size, colour). A line is split into
   segments at gaps wider than the page's gutter (`text_layer.gutter_for_page`);
   words closer than 1.5 pt (an OCR layer splitting `$32` into `$` `3` `2`)
   join with no space.
2. **Columns come from positions, never from guessed tables.** The left edges
   of all segments on a page are sorted and cut wherever two neighbours are
   more than 25 pt apart; each run is one sheet column, in page order. A
   segment goes to the column holding its left edge. A centred title goes to
   the column holding its centre.
3. **Rows follow the page.** Each printed line is one sheet row. A vertical
   gap of more than 1.6× the page's usual line pitch leaves one blank row
   (never more than one).
4. **Label/value pairs.** A segment whose words end in `:` at the end, or
   carry a `:` after their first word (`Employer Name: ABC Company`), is a
   label; the words after the colon, or else the next segment on the line,
   are its value. The label is written **exactly as printed, without its
   colon**. Two or more pairs on one line stay side by side.
5. **Wrapped values.** A line with no label, directly below a value and
   starting in that value's column, continues it (joined with a space):
   `3537 Rubaiyat Road, Grand` + `Rapids, MI, 49503`.
6. **Header over values.** A line of two or more label-free segments with no
   figure, directly above a line of figures or dates in the same columns, is
   a header row (`Payment Period (From) | (To) | Payment Date` over three
   dates) — and so is a table's heading line. Header rows are bold and
   centred.
7. **Tables.** One header row exactly as printed (nothing invented — no
   "Description" over the row labels). Row labels stay in the first column.
8. **Formatting is copied from the page's text**: bold, italic and size
   (scaled so the page's most common size is 11 pt; clamped 8–28) for every
   cell, not only the first label. Underline: not read in v1 (see open
   questions). Centred: a title centred on the page, and header rows.
9. **Values.** Money (`$5760`, `$ 3 2`) is written as a number with a
   currency format; a bare integer as a number; a date as a real date
   (`mm/dd/yyyy`). Everything else is text.
10. **Not copied.** Paragraph text (a line of 8+ words ending in `.` or `?`,
    or any line of 12+ words) and **markup** — text in a saturated colour
    (red, blue) that is under 40% of the page's characters: a reviewer's
    annotations, as on utah_paystub_2. No fill colours. Column widths fit the
    longest cell (8–60).

## How positions map to cells

| page | sheet |
|---|---|
| segment left edge in column run *k* | column *k* (A, B, …) |
| printed line | one row; one blank row for a gap > 1.6× pitch |
| label `X:` + value | `X` in its column, value in the value's column |
| title centred on the page | the column under its centre, bold, centred |
| several pages | one block per page, one blank row between |

## Scans and irregular layouts

* **No text layer (a scan without OCR):** not handled. The organized export
  falls back to the ordinary sheet and says so in the Legend. An OCR'd scan
  could be laid out from the OCR reader's word boxes, but OCR fonts carry no
  bold/italic, so formatting would be lost; deferred.
* **Jumbled or irregular layouts** are placed only by x and y: no table is
  guessed from them. What v1 does NOT handle:
  - columns that drift down the page (a column's left edge moving more than
    25 pt) split into two sheet columns;
  - text rotated or printed vertically is skipped;
  - two values stacked in one box come out as two rows;
  - a value right-aligned far from its label's column lands in its own column
    (correct position, but not beside the label);
  - overlapping text (an overprint) is written as read.

## Open questions

1. Underline is drawn as a line object, not a font flag: read it from the
   page's lines under a segment?
2. Should the organized export also carry the extraction's review marks and
   the provenance comments, or stay a clean picture of the page?
3. Markup by colour: is red always a reviewer's annotation for these
   clients?
4. Multi-page documents: one sheet per page, or one sheet with page blocks
   (v1)?
5. The partner's sheet renames two labels (`Pay Period From` for the
   printed `Payment Period (From)`, `Employee Address` for the second
   `Address:`); v1 keeps the printed text, per rule 4.

## Before / after

(Filled in after v1 is built: see the end of this file.)
