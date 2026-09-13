# DocAgent — what it does not do yet

A plain-language list of the limits, written for someone who will use this
system rather than read its code.

**The one distinction that matters:** for every limitation below, the answer is
either **WRONG** or **ABSENT**.

> **ABSENT** — the value is missing, blank, or the document is refused outright.
> You can see that something is not there. Annoying; not dangerous.
>
> **WRONG** — a plausible value appears in a cell and it is not what the
> document says. You cannot tell by looking at the spreadsheet. **These are the
> ones to check against the source.**

There are **two WRONG entries** in this file. Everything else is ABSENT.

Last checked 5 September 2026, against 60 test documents and 7 purpose-built
awkward cases.

---

# The two that produce a WRONG value

## 1. Ticked boxes that were "flattened" or scanned

**WRONG** ⚠

**When it happens.** A form with tick-boxes — filing status, entity type,
coverage tier, "is this a final return?" — where the tick is part of the picture
of the page rather than a real form field. This is what you get from a scanned
form, or one that has been printed to PDF and re-saved ("flattened").

**What happens.** The system can read every option printed on the line —
*Accrual*, *Cash* — but nothing tells it which one is ticked. **It picks one and
reports it as confidently as anything else on the page.** On our test form it
answered *Services* where the form said *Wholesale trade*.

**What is already handled.** If the tick-boxes are real form fields (a proper
fillable PDF), the state is read from the file and is correct. If the ticks are
printed as characters — `[X]` and `[ ]` — that is correct too. It is only the
flattened/scanned kind that guesses.

**We reduced it but did not fix it.** On a four-option test form, it went from 1
right to 3 right. The remaining one still guesses.

**What to do.** On any form with tick-boxes, check the tick-box answers against
the original. If you can get the form as a proper fillable PDF rather than a
scan, this problem disappears.

---

## 2. European number format (45,00 meaning forty-five)

**WRONG** ⚠

**When it happens.** A document that writes decimals with a comma and thousands
with a full stop — `€1.234,56` — which is normal across most of continental
Europe.

**What happens.** `€45,00` is read as **4500**. The figure is wrong by a factor
of one hundred, looks perfectly ordinary in the spreadsheet, and nothing flags
it.

**Why it is not fixed.** A single number cannot tell you which convention it is
in — `1,234` is valid in both. Deciding it needs evidence from the whole
document, and guessing per number would break US documents to fix European ones.

**What to do.** Do not use this on European-format documents yet. US and UK
formatting is safe.

**Same family, also untested:** documents in more than one currency, and amounts
written with a trailing `CR` / `DR`.

---

# Things that come back ABSENT

Missing or refused. Visible, not dangerous.

## Scanned documents and photographs

**ABSENT.** There is no OCR. A PDF that is a picture of a page — a scan, a photo
— has no text to read. Nothing is invented: values come back blank or marked as
unverified, and the document is flagged for review. A PDF produced by accounting
software or exported from a system is fine; a scanned one is not.

## A merged file whose documents carry no reference number stays one document

**ABSENT.** Deciding where one document ends and the next begins now needs the
**reference number to change** — the invoice number, the loan number, the
employee ID. Repeating the same one is how a form's later pages say "this is
still me", so a repeated heading is no longer enough on its own.

The cost is deliberate: merge a stack of documents carrying **no reference
number at all** — unnumbered delivery notes, plain letters — and they are read
as **one** document, so only the first one's values come back.

**Why it is taken this way.** The alternative is guessing from a repeated
heading, and that is what cut a six-page form in half and lost a whole page of
it. Guessing where there is least information is where guessing does the most
damage.

**What to do.** Split those files before uploading, or put a reference number on
the documents. A file whose documents *are* numbered — invoices, statements,
cheques, payslips, purchase orders — splits correctly.

## A table that continues onto the next page is cut at the page

**ABSENT.** A table in your template is filled from **one** region of the
document, and a region never crosses a page. If the table genuinely runs on
from the bottom of one page to the top of the next, only the part on the page
where the answer began comes back.

It is never silent. The document is marked for review, the warning says how
many regions matched and on which pages, and every row left out is listed with
its contents. Measured on the test documents: a two-page balance sheet loses
the last two lines of its equity section, and a two-page payslip loses its
ninth deduction.

**Why it is taken this way.** The alternative is appending whatever else on
another page looks like the same table — which is how an earnings release had
its operating-earnings table (page 2) glued under its earnings table (page 1),
and a utility bill had its glossary glued under its charges. A short table can
be seen; a merged lookalike cannot. Letting a continuation through when the
next page repeats the column headings does not work either: the two Berkshire
tables have *identical* headings.

**What to do.** Check any document marked "regions matched" — the rows left out
are listed. Extracting the continuation page on its own recovers them.

## A template aimed at the second of two lookalike tables is unverified

**UNVERIFIED.** When two tables in a document share a shape — an earnings release
with one table on page 1 and another on page 2 — only one is written, and the one
kept is the page the model's answer *begins* on. For a template aimed at the
page-1 table this is verified on a live run. For a template aimed at the
**page-2** table it is not: on the one live run so far, the model returned only
page-2 rows, so no choice was ever made. If the model returns both tables with
page 1 first, a page-2 template gets page 1's table.

It would not be silent — the document is marked for review and the warning names
both pages — but the values written would be the wrong table's.

**What to do.** When a document is marked "regions matched", check that the kept
page is the table the template describes.

## An invoice and the cheque paying it are read as one document

**ABSENT — and a realistic production shape, not a test-file oddity.** A merged
file splits where the reference number changes. A cheque that quotes the
purchase order its invoice also quotes shares that number, so an invoice
uploaded together with the cheque that pays it comes back as **one** document:
only the invoice's values are extracted, and the cheque's — payee, amount,
cheque number, routing and account — are not. Cheques are central to this
workflow, so expect this whenever payment paperwork is scanned or merged as a
pair.

Measured on the test set: `INV-2024-0031` followed by `CHQ-001847` (both quote
`PO-2024-0018`) no longer splits. It did before round-2 I1, when a page reading
as a different kind of document started a new one by itself — the rule that cut
a utility bill in two at its glossary page.

**What to do.** Upload the invoice and the cheque as separate files.

## Deciding what kind of page it is uses keywords, and the keywords are weak

**ABSENT.** Where a file splits depends partly on a quick keyword guess at each
page's document type, made without reading the page properly. The guess is
easily wrong: the single word "continued" reads as a **tax form**, and a utility
bill's meter-and-glossary page read as a tax form too. That weakness is what cut
the ENGIE bill in two. A type change no longer splits a file on its own, which
contains the damage, but the guess itself is unchanged and still feeds the
decision — a page that happens to carry a new reference number and a
misleading keyword can still start a document.

## A form field printed across several lines, in a crowded layout

**ABSENT.** Where a value wraps onto a second line, it is joined correctly. What
it will **not** do is reach onto the next line and take words the model did not
claim. That is deliberate: a field that helps itself to the line below is how a
"Name" ends up containing an address, and a short value is something you can
see, where a swallowed one is not.

Occasionally a value comes back shorter than the printed one.

## Two side-by-side blocks merged into one answer

**ABSENT (flagged).** On a page with two columns of notes side by side, an
answer can occasionally run across the gap and pick up both. This is **detected**
— the cell is marked low confidence and appears in the review list with the
reason. The value is kept rather than trimmed, because which half you wanted
cannot be worked out automatically.

## Very large merged files: page pictures stop after 20 pages

**ABSENT (no measured cost).** As well as reading the text, the system converts
the first 20 pages to images. In a file with more than about 20 documents, the
later ones are read from their text only.

We measured this on a 25-document file: **all 25 came back complete**, with the
same number of filled cells as the first twenty. It is written down because it
is a real difference in how later documents are handled, not because it cost
anything.

## Large uploads take proportionally longer, and cost proportionally more

**ABSENT.** Each document in a merged file is processed separately, which is why
twenty invoices produce twenty results instead of one. Measured: **20 documents
in 76 seconds**, about 3.6 seconds each. So roughly 3 minutes for 50, 6 for 100,
12 for 200.

Nothing times out — the upload returns straight away and the page polls for
progress. But a 200-page file is 200 documents' worth of processing and cost,
and nothing warns you before you start.

## A job interrupted by a server restart

**ABSENT (fixed to fail rather than hang).** If the server restarts mid-run — a
deployment, for instance — that run is lost. It now reports **"Interrupted by a
server restart before it finished. Nothing was saved for this job — upload the
files again."** rather than sitting at *processing* for ever.

Nothing partial is kept, so there is no half-finished spreadsheet to mistake for
a finished one.

## Templates: a table with no column headings is refused

**ABSENT (by design).** If you mark a table but leave its heading row empty, the
save is blocked with a message: the system would be asking for columns it cannot
name. Type a heading in each column.

If **one** column is missing a heading you get a warning and the save goes
through — the value in that column is likely to come back blank.

**A caveat we would rather state.** These checks fire on none of the 23 real
templates we have, but every one of those was drawn by us. If one of yours is
blocked and it looks perfectly reasonable, the check is more likely wrong than
your template — tell us.

## A reference number in an unlabelled cell may be read as a number

**ABSENT (visible in the cell).** A cell holding something like an NMLS ID or a
licence number stays text — and keeps its exact digits — when its column says so:
headed `NMLS ID`, `Account No`, `Policy`, `Ref`, and so on. Money columns are
unaffected: `Account Balance` and `Invoice Total` are still numbers you can add
up.

Where a column heading gives no clue, a 6-to-8 digit reference with no leading
zero is still read as a number, so it may show as `222222` with Excel's
right-alignment rather than as text. **The digits are not changed.** Longer
references and anything starting with a zero — routing numbers, account numbers
— are safe whatever the heading says.

**What to do.** Name the column for what it holds: `NMLS ID` rather than `NMLS`.

## Confidence is worked out per cell but only shown per document

**ABSENT (from the screen, not from the data).** Every value carries its own
confidence, and low-confidence cells are listed for review. The results grid
shows a document-level status rather than colouring each cell. The information
exists; it is not all on screen yet.

## Cancelling a running job does not stop it

**ABSENT.** The cancel button marks the job cancelled in the list, but work
already under way runs to completion in the background. Nothing is corrupted —
you simply do not get the time or cost back.

## Editing a template's rows and columns

**ABSENT.** The template editor can change cells in place but cannot insert or
delete whole rows and columns. If that is added without care, any table you have
marked would point at the wrong cells afterwards — so it is deliberately not
there yet.

---

# Never tried

No test covers these. We are not claiming they work **or** that they fail.

| | |
|---|---|
| A table that runs across a page break | untested |
| Documents in more than one currency | untested |
| Rotated or landscape pages | untested |
| Colour or shading that carries meaning | untested — no colour is read |
| Footnote markers attached to figures (`1,234 *`) | untested |
| A value split across merged cells | untested |
| Right-to-left or non-Latin scripts | untested |
| Negative figures in brackets, `(1,234.50)` | handled on export; not tested end to end |

---

# Recently fixed

Listed because each of these produced a **wrong** answer that looked right, so
anyone who saw the old behaviour should know it changed.

| Was | Now |
|---|---|
| **A multi-page form was cut into pieces.** A six-page Closing Disclosure came back as two blocks — page 1, then a near-empty repeat with only the lender, title company and loan ID. The whole Contact Information page, about thirty values, was never extracted. | A repeated heading is no longer a boundary on its own: the reference number must change too, and a document that prints “Page 3 of 5” is taken at its word. Verified on the real form — one document, and the contact matrix comes back as a full five-by-nine grid. |
| **A table was filled from every lookalike in the document.** An earnings release's page-1 earnings table and page-2 operating-earnings table came back as one sixteen-row table; a utility bill's glossary was appended to its charges under a second copy of the heading row. | A table is filled from one region and never across a page. When more than one matched, the document says how many and on which pages, and lists what was left out. |
| **A utility bill was cut into two documents at its glossary page**, so the bill header and the charges table each came back twice. | A page reading as another kind of document no longer starts one on its own; the reference number must change, and a page printing its own number (“Page 4”) is taken at its word. |
| **Only the first document in a merged file was read.** Three invoices in one PDF produced one result; the other two vanished with no message. | Each document is found and processed separately. 13 of 14 merged test files split at exactly the right pages (the fourteenth is the invoice-and-cheque case above); no single document is ever split. |
| **Figures printed inside narrow boxes were cut in half.** On a W-2, `$1,268.75` was read as `5`. Eleven of twelve figures were wrong and all eleven were reported as confident. | All twelve correct. The two halves are rejoined by their position on the page. |
| **A figure could land in the wrong column** — a payment reported as a receipt — and still be marked confident, because the check only asked whether the number was on the page. | The column a figure sits under is now checked. A misplaced one is flagged and named. |
| **Rows were deleted for quoting the same line as an earlier row**, so repeated headings and group totals silently cost you rows — worst in exactly the merged files this is built for. | Rows are told apart by where they sit on the page. Anything still dropped is listed with its contents. |
| **Currency symbols and pence disappeared on export.** | The cell keeps `$7,750.00` on screen and still adds up as a number. |
| **A wrapped email address came back with a space in it** — `sarah@ epsilontitle.com`. It looked ordinary in the spreadsheet and would have bounced. | Joined the way the page joins it: no space when the break falls inside a word or an address, a space when it falls between words. |
| **Reference numbers were turned into figures on export** — an NMLS ID of 222222 became 222222.0. | A cell whose column names it as a reference keeps its digits exactly. Quantities are untouched. |
| **Column widths were applied inconsistently**, so labels you typed came back truncated. | Every written column is sized; a width you set yourself is kept as you set it. |
| **Merging, centring, shading and borders were lost on export.** | The formatting you drew comes back with the values. |
| **Tick-boxes in proper fillable forms were guessed at.** | Read from the file itself. |
