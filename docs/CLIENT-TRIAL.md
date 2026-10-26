# Client trial: running a firm's real documents under supervision

**Status:** a checklist for any document family: invoices, statements,
payslips, settlements, cheques or a firm's own kind. [CHEQUE-TRIAL.md](CHEQUE-TRIAL.md)
is a worked example of this checklist for cheques. Nothing here is automated,
and nothing here may put a real document, value or name into the repository.

The trial answers one question first: **how many wrong values reach the firm
without anything telling them to look?** Accuracy comes second. A wrong value
marked `Low` means the system is working. A wrong value marked `Verified` is
the failure this product must not have.

## 0. Questions to ask before anything is set up

Ask the firm these, and write down the answers. They decide the template, the
settings, and what the trial can claim.

| Ask | Why it matters |
|---|---|
| **Which document types?** (invoice, statement, payslip, settlement, claim packet, cheque, other) | One template per type. A type with no family checks still extracts. Arithmetic can be declared as rules ([ADDING-A-DOCUMENT-FAMILY.md](ADDING-A-DOCUMENT-FAMILY.md)) |
| **From which issuers?** How many layouts per type? | One template serves every issuer of a type. Ten very different layouts are ten chances for a misplaced value |
| **Scans or digital PDFs?** Phone photos? | A scan or photo is at best `Unverified` (no text layer to check a quote against). Only English OCR is installed |
| **Password-protected PDFs?** | Supported: the password is given at upload, per file, and never stored |
| **Which languages and scripts?** | Non-Latin text on a native PDF is read and flagged. Non-English OCR is not supported yet ([LOCALES-AND-FAMILIES.md](LOCALES-AND-FAMILIES.md)) |
| **Which currencies and number styles?** `1,234.56`, `1.234,56`, `1 234,56`, lakhs? | Set the firm's `locale` so an ambiguous `1,234` is resolved rather than flagged |
| **Several documents per file?** Blank separator pages? Stamps (PAID, VOID, COPY)? | Splitting is conservative and says when it cannot decide. Stamps are flagged, never hidden |
| **Volume:** files per month, pages per file | Cost and time ([OPERATIONS.md](OPERATIONS.md) §11); `MAX_PDF_PAGES` (200) and `TENANT_MONTHLY_PAGE_LIMIT` |
| **Output:** their own spreadsheet layout? Which columns must sum? | The template *is* their layout. An accounting import (Tally, Zoho, …) is not supported yet |

## 1. Staging environment (set up once, before any real document)

Use the same table as [CHEQUE-TRIAL.md §1](CHEQUE-TRIAL.md#1-staging-environment-set-up-once-before-any-real-cheque):

- a separate project or environment, deployed from a tagged commit;
- its own database and bucket;
- a separate, capped model key;
- `ENVIRONMENT=production` (or `staging`, which refuses to start on a weak
  configuration: [ENVIRONMENTS.md](ENVIRONMENTS.md));
- one tenant: an admin for us, and a normal account for the firm;
- no real data in the demo tenant, ever.

Before the first upload, check all of these:

- `python scripts/smoke_test.py --base-url <staging>` passes.
- The template's preview shows the slots you expect.
- The template's declared rules (if any) save without a blocking message.
- One synthetic document of the type extracts end to end.

## 2. The template

Build it in the editor from one real document of the type. Leave a cell empty
next to each label you want filled, and declare a table where rows repeat.

Add the arithmetic the firm already checks by hand as **rules**:

- lines sum to the subtotal;
- gross minus deductions equals net;
- the opening balance plus credits minus debits equals the closing balance;
- quantity × price equals the amount.

Each rule is one line of JSON ([ADDING-A-DOCUMENT-FAMILY.md](ADDING-A-DOCUMENT-FAMILY.md)).

**Freeze the template for the trial.** A template that changes halfway makes
the two halves of the batch incomparable.

## 3. Running a batch (supervised)

1. **Consent and selection.** Aim for 50 documents per type, including the
   hard ones: scans, multi-document files, stamped copies, the issuer with the
   odd layout, and at least two documents uploaded twice. The firm confirms
   its client has agreed.
2. **Upload** 10 files at a time with the template selected. Turn options on
   only if they are under test.
3. **Wait** for the job to finish. A `partial` or `failed` job names each
   failed file and the reason; record those rows too.
4. **Review value by value** before exporting:
   - Compare each value with the page image.
   - Record the outcome *before* correcting it (section 5).
   - Then correct it in the app.
5. **Export** and check the file: corrected values, the *Review status*
   column, the *Legend* sheet, and the comments quoting the source.
6. **Stop rule:** if two values in one batch are wrong while marked
   `Verified`, stop and report. That is a defect, not a statistic.

## 4. What the firm sees

Levels: **Verified**, **Grounded**, **Unverified**, **Low**, **Edited**
(definitions: [CHEQUE-TRIAL.md §4](CHEQUE-TRIAL.md#4-what-the-accountant-sees)).

The reason codes most likely in a trial (full list:
[OCR-READER-SEAM-DESIGN.md §12](OCR-READER-SEAM-DESIGN.md)):

| Code | Says |
|---|---|
| `ocr_origin` | read by OCR, so compare it with the page |
| `grounding_failed` | the quote is not on the page |
| `placement_failed` | the value sits under a different column in the document |
| `rule_failed:<name>` | a rule the template declares did not hold |
| `rule_unreadable:<name>` | a rule could not be decided (for example, an ambiguous amount) |
| `totals_mismatch`, `balance_mismatch`, `payslip_mismatch` | a family's arithmetic failed |
| `number_ambiguous`, `date_ambiguous`, `currency_mismatch` | notation could not be settled without guessing |
| `possible_multiple_documents` | the file may hold several documents; kept as one record, with the pages where a new one may begin |
| `void_marker`, `paid_marker` | stamped VOID / COPY / … or PAID; never hidden |
| `redacted_or_obscured` | part of the page is painted over or unreadable. The cell is empty and says why |

## 5. Recording outcomes

Use the outcomes CSV and `scripts/trial_report.py` exactly as in
[CHEQUE-TRIAL.md §5](CHEQUE-TRIAL.md#5-recording-outcomes). The columns do not
depend on the document type. For a multi-document file, the `cheque` column
holds the *k* of a record named `file [k of N]`.

The numbers to take, per document type and per form (native, scan, photo,
multi-document file):

- wrong and `verified` (must be 0);
- wrong and `grounded`;
- wrong and `unverified`;
- right and `low` (noise that costs the firm time);
- empty but present;
- documents found vs truth;
- accuracy per field.

## 6. Turning corrections into fixtures, without exposing real data

[CHEQUE-TRIAL.md §6](CHEQUE-TRIAL.md#6-turning-his-corrections-into-fixtures--without-exposing-real-data)
applies to every family:

- **Never commit or paste a real document.**
- **Redact before anything leaves the firm:**
  - names, addresses and free text become placeholders;
  - identifiers keep their length and their check-digit state;
  - dates shift by a constant;
  - amounts are kept, or scaled consistently.
- **Reproduce a failure's shape synthetically** with the committed
  generators:
  - `tests/fixtures/make_locale_fixtures.py`
  - `make_multidoc_fixtures.py`
  - `make_settlement_fixtures.py`
- **Write gold labels by hand,** never from engine output.

## 7. After the trial

- Purge the trial tenant (database and bucket) and record the date.
- Revoke the staging key.
- Write up the section 5 numbers per type and form, including the stop-rule
  outcome.
- Add any new limit to `KNOWN-LIMITATIONS.md`.
