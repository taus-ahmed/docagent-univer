# Cheque trial — running real cheques under supervision

**Status:** checklist for the first supervised trial. Nothing here is
automated, and nothing here may put a real document, a real value or a real
name into the repository.

The question the trial answers is not "what is the accuracy" but **"how many
wrong values reach the accountant without anything telling him to look"**.
Accuracy is the second number. A wrong value marked `low` is the system
working; a wrong value marked `Verified` is the failure this product must not
have.

## 1. Staging environment (set up once, before any real cheque)

| Item | Setting | Why |
|---|---|---|
| Railway | a **separate project** (or at least a separate environment) named `docagent-staging`, deployed from a tagged commit of `integration/ocr-hardening`, never from `main` auto-deploy | a trial must not move when someone pushes |
| Database | its **own** PostgreSQL service. Never the production database, never the shared demo's | trial data must be deletable as a whole |
| File storage | its own R2 bucket (`docagent-staging-files`), **versioning off**, lifecycle rule deleting objects after 30 days | deleted means deleted (see `proposals/retention.md`) |
| Model key | a **separate** Gemini API key on a **paid** (billing-enabled) Google Cloud project, with a **budget alert and a hard cap** (e.g. $25/month) | the paid tier's terms exclude training on prompts (⚠ VERIFY current terms); a cap bounds a runaway batch |
| `ENVIRONMENT` | `production` (Swagger off, placeholder `SECRET_KEY` refused at boot) | staging should fail the way production fails |
| `SECRET_KEY` | its own, not production's | a staging token must not open production |
| Logs | Railway log retention at the minimum; the app logs ids, counts and reason codes only (`SECURITY.md`, "Logging") | logs leave the tenant boundary |
| Accounts | one tenant (`client_id` e.g. `trial_001`), one tenant admin for us, one `client` account for the accountant. No super-admin used during the trial | the accountant sees only his tenant |
| Shared demo | **no real client data in the demo tenant, ever.** The demo uses the bundled sample documents only | the demo is shown to people outside the firm |
| Drive | off for the trial (no watch folders) | one ingestion path to supervise |

Before the first upload, verify: `GET /health` answers; the tenant's schema
exists; the cheque template is saved and its preview shows the 11 slots below;
a synthetic cheque (`tests/test_pdfs/CHQ-001847.pdf`) extracts end to end.

## 2. The template

The trial uses the gold cheque template (`tests/gold/templates/cheque.json`)
recreated in the editor: Cheque Number, Date, Bank Name, Drawer Name, Payee,
Amount in Figures, Amount in Words, Memo, Authorized By, Routing Number,
Account Number. Do not add fields during the trial — a changed template makes
the first and second half of the batch incomparable.

## 3. Running a batch (supervised)

1. **Consent and selection.** The accountant chooses the cheques (aim for 50,
   including scans, phone photos, several cheques on one page, and at least
   two cheques scanned twice). He confirms the client has agreed to the trial.
2. **Batch size.** 10 files per upload. Note the job id of each.
3. **Upload** on the Extract page with the cheque template selected. No
   options (categorise / summary / anomaly) — they are not under test.
4. **Wait** for the job to finish. A job that ends `partial` or `failed`
   names each failed file and why; record those rows too (step 5), with
   `level` = `failed`.
5. **Review, value by value**, on the Review page, before anything is
   exported. The accountant compares each value with the page image beside it
   and records the outcome (section 5) **before** correcting it, then corrects
   it in the app.
6. **Export** once the batch is reviewed, and check the file opens with the
   corrected values, the *Review status* column and the *Legend* sheet.
7. **Stop rule.** If two values in one batch are wrong while marked
   `Verified`, stop the trial and report — that is a defect, not a statistic.

One of us sits with the accountant for the first batch, then is on call.

## 4. What the accountant sees

| Where | What it says |
|---|---|
| Results grid | each value with its level: **Verified** (found on the page as quoted, under a label you wrote), **Grounded** (found on the page; the label was named by the model), **Unverified** (machine-read from a scan or image — compare with the page), **Low** (a check failed — probably wrong), **Edited** (typed by a person) |
| Review page | the page image with the quoted words outlined, the level, and the reasons: `ocr_origin` (read by OCR), `grounding_failed` (the quote is not on the page), `placement_failed`, `content_check_failed`, `checksum_failed` (routing number fails the ABA checksum), `amount_mismatch` (figures and words disagree), `amount_unreadable`, `micr_band_unreadable` |
| Several cheques on one page | one record per cheque, each named with its page region |
| A cheque scanned twice | **both** records kept and flagged as possible duplicates — never merged |
| Export | values as typed numbers where they are amounts, identifiers kept as text; a *Review status* column; the *Legend* sheet; a comment on each value quoting the words it was read from |

Scans and photos are `Unverified` at best by design: there is no text layer to
check a quote against.

## 5. Recording outcomes

Copy `docs/cheque-trial-outcomes-template.csv`, one file per batch, **kept on
the accountant's machine or the firm's share — never in this repository and
never sent to us unredacted.** One row per field per cheque, including fields
the system left empty:

| Column | Content |
|---|---|
| `file` | the file name as uploaded (stays on the firm's side; see redaction) |
| `page` | page number in the file |
| `field` | the template label, e.g. `Amount in Figures` |
| `machine value` | what the system showed, before correction; empty if none |
| `level` | `verified`, `grounded`, `unverified`, `low`, `empty`, `empty_flagged` or `failed` |
| `reasons` | the reason codes shown, separated by `;` |
| `true value` | what the cheque says |
| `correct yes/no` | `yes` if the machine value equals the true value as the accountant would enter it (notation differences such as `$1,250.00` vs `1250.00` count as `yes`); `no` otherwise, including a value where the cheque has none |

The numbers we take from it: wrong-and-`verified` (must be 0), wrong-and-
`grounded`, wrong-and-`unverified`, right-and-`low` (noise that costs him
time), empty-but-present, and accuracy per field.

An optional `cheque` column gives the *k* of a record named `file [k of N]`
(several cheques in one file); without it every row is cheque 1.

### The report: `scripts/trial_report.py`

```
python scripts/trial_report.py --truth outcomes.csv --results results.json --out batch-1
```

* `--truth` — the outcomes CSV above.
* `--results` — optional: the job's results saved from
  `GET /api/jobs/{id}/results` (JSON). When given, the machine value, level
  and reasons are taken from it and cheques found are counted from its
  records; the accountant's *correct yes/no* is used only where his machine
  value matches it, otherwise the value is re-judged against the true value
  (notation-blind). Without it, the CSV's own machine columns are used. The
  exported workbook is not read: it holds the same data less unambiguously.
* Writes `batch-1.md` (explained in plain words at the top) and `batch-1.csv`.
  Run it on the firm's machine; nothing is sent anywhere.

It reports, per field and per level (high/verified, grounded, unverified, low,
edited, empty-flagged, empty, failed): count, correct, wrong, accuracy; the
**silent-wrong rate** (wrong ÷ values labelled high or grounded — must be 0);
**wrong with no flag**; **false alarms** (correct but flagged); **cheques found
vs truth** (dropped or merged / split or duplicated); and the **precision of
each reason code** (how often the value it fired on was really wrong).
Synthetic example data: `tests/fixtures/trial/`.

## 6. Turning his corrections into fixtures — without exposing real data

**Real cheques are never committed, never attached to an issue, never pasted
into a chat or a prompt, and never put in `tests/`.** What crosses to us is a
redacted outcomes file and, for each failure worth keeping, a synthetic
reproduction.

Redaction, done by the accountant (or by us on his machine, supervised)
before the CSV leaves the firm:

1. `file` → `chq-NN` (a sequence number); keep the mapping on the firm's side.
2. Names (payee, drawer, signatory), addresses and memo text → `PERSON-1`,
   `ADDR-1`, `MEMO-1`, consistently within one cheque so "payee printed in the
   drawer field" is still visible.
3. Account and routing numbers → the same number of digits, digits replaced,
   **checksum state preserved** (a routing number that passed ABA keeps
   passing, one that failed keeps failing) — the checksum is under test.
4. Cheque numbers → a fresh number of the same length.
5. Amounts → keep. An amount alone identifies nobody, and the figures/words
   agreement is under test. If the firm objects, scale every amount on one
   cheque by the same factor and keep the words consistent.
6. Dates → shift every date on a cheque by the same number of days.
7. `machine value` and `true value` are redacted with the same substitutions,
   so a wrong value stays wrong in the same way.

For a failure worth a regression test, we build a **synthetic** cheque that
reproduces the failure's *shape* — the layout, the font size, the split field,
the overprint — with invented values, using the same generators as the
committed fixtures (`tests/fixtures/make_fillable_form.py` is the pattern: the
script is committed with the PDF so it can be read). Its gold label is written
by hand from the invented values, never from engine output (`CLAUDE.md`, "Gold
labels are never regenerated from engine output"). The redacted CSV row is
cited in the fixture's docstring by `chq-NN` and field.

A scan or photo cannot be reproduced synthetically with fidelity. For those we
keep only the redacted outcome rows and the counts, and file the failure as a
measured limit in `KNOWN-LIMITATIONS.md`.

## 7. After the trial

- Purge the trial tenant: delete the staging database and empty the bucket
  (there is no per-job deletion yet — `proposals/retention.md`). Record the
  date it was done.
- Revoke the staging model key.
- Write up the six numbers in section 5 per document kind (native PDF, scan,
  photo, multi-cheque page), with the stop-rule outcome.
