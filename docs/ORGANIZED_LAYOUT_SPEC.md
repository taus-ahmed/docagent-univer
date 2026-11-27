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

## Before / after (v1, `local_docs/organized_out/`)

Made by `tools/organized_export.py`; the same code serves
`?layout=organized`.

| document | before (today's no-template export) | after (organized v1) |
|---|---|---|
| **utah_paystub_2** | one label/value column pair (A/B) down the sheet; the three dates stacked as three pairs; an invented `Description` heading over the earnings table; review fills on every value | the page's layout: title `Pay Stub` bold and centred in D1, file name F1 (as the partner's sheet); two pairs per row (Employer Name / ABC Company / Address / …); the three date headings side by side over their dates; `Rate / Hours / Current Total / YTD (Year to Date)` bold and centred, no `Description`; money and dates typed; no fills. **Every label the partner's sheet shares with the page is in the same column, in the same order** (tested). Differences left: the partner adds blank rows the page's white space does not show (rows 4, 6, 11–12, 18, 27), and renames two labels |
| **utah_paystub_1** | template-shaped fields | placed by position, but the OCR layer itself is garbled (`University ofGeorgia`, `osvi±@.`, a reviewer's notes OCR'd into the values in black): v1 lays out what the layer says, and that is not usable. Needs a better reading, not a better layout |
| **saltlake_paycheck** | template-shaped fields | page 1's text layer is the explanation printed around the stub (the stub is a picture); paragraphs are dropped, leaving a few fragments. Page 2 is a scan: listed on the `Not organized` sheet ("no text layer on this page") |
| **ou_check_stub** | template-shaped fields | the stub is a picture on page 1; the text layer is the numbered explanation, whose short list items survive the paragraph rule. Not useful |

So v1 does what the spec says on a document whose **text layer is the
form** (utah_paystub_2), and has nothing good to work with on the other three:
two print the stub as an image and one has a garbled OCR layer. Laying out an
image-only stub needs the OCR reader's word boxes (see "Scans" above).

# v2 — every text-layer PDF (Run S, Stage 2)

v1 was built on pay stubs. v2 extends the same rules to every document
with a text layer (bank statements, invoices, purchase orders, W-2s, 1099s,
1098s, receipts, pay stubs) and changes nothing about how a cell is placed:
**row from y, column from x, never from extraction order.** Still behind
`?layout=organized`, off by default, until the owner approves.

## Rules added or changed

11. **One header row per table.** A multi-page document reprints its column
    headings (and its title block) on every page. A line printed on an
    earlier page is not written again on a later one: a table's header row
    appears once, above its first rows. A heading line with nothing under
    it on its page (a stray header: the page ends, or the next line is
    another heading) is kept only on the page where rows follow it.
12. **Page furniture.** "Page n of m", "Page n" and a line printed on every
    page (a footer) are not copied.
13. **Underline** is read from the page's drawing, not the font: a
    horizontal line or a rectangle at most 1.5 pt tall lying within 3 pt
    under a segment and covering at least 80% of its width underlines that
    cell.
14. **Thick lines.** A horizontal rule at least 1.5 pt thick (a line's
    width, or a filled rectangle's height) spanning at least 30% of the
    page, and not an underline, gives the row written directly above it a
    thick bottom border across the written columns.
15. **Centred** is copied for any line that is one segment centred on the
    page (within 3% of its width), not only the title.
16. **One date format.** Every date in any printed notation (`08/01/2020`,
    `8/1/20`, `2020-08-01`, `Aug 1, 2020`, `1 August 2020`) is a real date
    shown as `mm/dd/yyyy`. Day/month order comes from the document's own
    unambiguous dates (`dates.document_order`); a date whose order nothing
    settles stays text as printed rather than be guessed.
17. **Nothing printed in a field or table region is left out.** Every
    figure on a line that is not prose, markup or furniture lands in a
    cell (tested over every text-layer PDF in the corpus).

## Jumbled and irregular layouts

A PDF's content stream may draw text in any order (a form filled field by
field, a statement written column by column). Placement reads positions
only, so the same page drawn in a shuffled order lays out identically
(tested). Still not handled: rotated text, columns that drift more than
the column cut, and two values stacked in one box (two rows).

# v3 — tables split at the page's own columns (Run T)

Still placement by x and y only, still behind `?layout=organized`. What v2
did not do, and v3 does:

18. **Table columns are the page's alleys.** A heading line (two or more
    segments, no figure, no label) with a row of dates or amounts under it
    starts a table. Its columns are the x ranges the data rows' ink covers;
    every word goes to the column it sits in and every heading word to the
    column it sits over. So `CHECK RUN CHECK #` is two headings and `75.00
    07/22/2026 INV PD` is four cells, though both are printed with ordinary
    word spacing. A headless column separated from its left neighbour by no
    more than word spacing is that neighbour's continuation (a description).
19. **Tails.** A line with no date and no amount directly under a row
    (closer than rows are to each other) and starting right of the table's
    first column continues that row, joined with a space - never a row.
20. **Side-by-side bands** (`Number Date Amount` x3): one header row; each
    band read top to bottom, then left to right; sorted by the first column
    when every band is printed sorted.
21. **Stacked headings** (`Tran Date` over `Post Date`): two sub-field
    columns side by side, top first; a record is two lines tall, the first
    line's values under the top heading, the second's under the bottom one.
22. **Group lines** (`300055 ANDERSON DULANEY`): identifier and name in two
    cells in the two columns LEFT of the table, bold - never in a column of
    the table. `CHECK DATE: 06/24/2026` lines inside the table stay
    label/value pairs (beside the group cells in a grouped table).
23. **A continued table keeps its first page's columns**: each later cell
    moves to the earlier column whose x span it overlaps most.
24. **Furniture** adds: report generated/printed/run lines with a date,
    user / operator / program / report id lines, `Page n` printed as two
    segments, and printed form instructions (see instructions, privacy act,
    OMB No., Cat. No., keep for your records).
25. **Every `Label:` pair** in a segment is split, not only the first; two
    printed items sharing a page column run are two cells. A word glued to a
    figure by the text layer (`Checks$1,783.32`, `of6`) is two tokens; an
    identifier with no lowercase run (`INV2024`) is not split.
26. **Values.** Identifiers keep every character: a zero-padded digit run,
    9+ digits, or a digit run under an identifier heading (INVOICE, P.O.,
    CHECK #, ZIP, ...) is text, and a column holding one zero-padded value is
    text throughout. A trailing minus stays trailing: `26.08-` is -26.08
    shown with `#,##0.00;#,##0.00-`; a leading minus and brackets as printed.
    Money keeps its printed decimals.
27. **Fillable forms**: widget values are placed where the form shows them,
    beside their labels.
