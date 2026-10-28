# Locales and families: what DocAgent supports, flags, and does not do yet

DocAgent is a global document-to-spreadsheet engine. Extraction (one
addressed slot per template cell, grounded on the page) does not depend on
the country, the currency or the kind of document. What does depend on them
lives behind small interfaces:

- the shared notation parsers;
- the identifier plug-ins;
- the family checks;
- the declared rules.

**The rule throughout: ambiguity is flagged, never guessed. A failed check
makes a value `low`. Nothing vanishes or merges silently.**

## Numbers and currencies (`engine/amounts.py`)

| Handled | Examples |
|---|---|
| Grouping with `,` `.` `'` `’`, a space, a no-break space or a thin space | `1,234.56` `1.234,56` `1'234.56` `1 234,56` |
| Indian grouping | `12,34,567.00` |
| `/-` for whole rupees | `Rs. 1,500/-` |
| Negative amounts | `(1,234.00)`, `-1,234.00`, `1,234.00-`, `1,234.00 Dr` / `Cr` |
| Every ISO 4217 code, with its decimal places | JPY 0, KWD 3 |
| Currency symbols | `$ US$ C$ A$ HK$ S$ NZ$ R$ MX$ £ € ¥ ₹ Rs. ₨ د.إ ₩ ₽ ₺ ₪ ₱ ฿ ₫ Fr.` (a bare `$` or `¥` names no single currency) |
| A currency code before or after the amount | |

**How an ambiguous amount is resolved.** `1,234` and `1.234` are a thousand in
one locale and one-and-a-bit in another. The parser tries these, in order, and
stops at the first that settles it:

1. the template's `locale`;
2. the firm's `locale:` in its YAML;
3. the document's own unambiguous numbers;
4. a zero-decimal currency (JPY, KRW, …).

If none settles it, the value gets `number_ambiguous` and the export keeps the
printed text rather than a guessed number.

**Flagged:**

| Reason | When |
|---|---|
| `number_ambiguous` | the amount's notation could not be settled |
| `minor_units_mismatch` | the decimals don't match the currency (e.g. `JPY 1,234.56`) |
| `currency_mismatch` | a sum or comparison over two currencies |
| `currency_ambiguous` | a sum over symbols that may name different currencies (`$` alone) |

## Dates (`engine/dates.py`)

- **Formats:** ISO (`2024-04-18`), numeric DMY / MDY / YMD with `/ . -`,
  two-digit years, and English month names and abbreviations.
- **Order:** taken from the template's or the firm's locale. MDY is used for
  `en-US` and its peers, DMY for other locales. Without a locale, the order
  comes from the document's own unambiguous dates.
- **Flagged:**
  - `date_ambiguous`: e.g. `03/04/2024` with nothing to decide the order;
  - `date_unreadable`.
- **A declared `date_order` rule** never guesses an order either.

## Languages and scripts (`engine/writing_systems.py`, `language_validators.py`)

**Native PDFs in any script are read and grounded.** The script of each page is
detected: Latin, Greek, Cyrillic, Hebrew, Arabic, Devanagari and the other
Indic scripts, Thai, Kana, Han and Hangul.

A page whose function words are German, French, Spanish, Italian, Dutch or
Portuguese, or which is in a non-Latin script, gets `non_english_text` on its
values: the template labels are English, so the model's mapping deserves a
look.

**OCR (scans and images) is English only:** Tesseract `eng` + `osd` are what
the image installs. A non-English scan is read badly, and is flagged by
grounding and OCR origin rather than read correctly.

## Identifiers (`engine/identifiers/`, one plug-in each)

| `id_type` | Check | Reason on failure |
|---|---|---|
| `aba` | US routing number checksum | `checksum_failed` |
| `iban` | registry country and length, ISO 13616 mod-97, and the account part's per-country format (letters/digits by position) for every registry country — none is checksum-only | `iban_invalid` |
| `bic` / `swift` | format | `swift_invalid` |
| `uk_sort_code` | format | `sort_code_invalid` |
| `gstin` | India GSTIN check character | `gstin_invalid` |
| `pan` | India PAN format; must match its GSTIN | `pan_invalid`, `pan_gstin_mismatch` |
| `ifsc` | India IFSC format | `ifsc_invalid` |
| `vat` | EU and UK VAT formats; UK (GB/XI) also the HMRC check digits (mod 97, and the 97-55 scheme from 100 0000 up) and GD/HA ranges; other EU countries are format-only | `vat_format_invalid` |
| `trn` | UAE TRN format | `trn_invalid` |
| `ein` | US EIN format | `ein_invalid` |

There are two ways to apply a plug-in:

- **On a cell:** set `id_type` on the cell in the template grid.
- **As a rule:** an `id_type` rule (`docs/ADDING-A-DOCUMENT-FAMILY.md`).

## Document families

| Family | Coded checks | Reasons |
|---|---|---|
| invoice | lines → subtotal; subtotal + charges + tax − discount → total | `totals_mismatch`, `totals_unreadable` |
| receipt | the same, with receipt roles | `receipt_mismatch`, `receipt_unreadable` |
| bank statement | opening + credits − debits = closing; running balance per row; Dr/Cr single amount column; the stated transaction count | `balance_mismatch`, `balance_unreadable`, `row_count_mismatch` |
| payslip | gross − deductions = net; listed deductions → their total | `payslip_mismatch`, `payslip_unreadable` |
| cheque | figures vs words (including lakh/crore); MICR parsed; ABA checksum | `amount_mismatch`, `amount_unreadable`, `checksum_failed`, `micr_band_unreadable` |
| **any** | template-declared rules: `sum_equals`, `equals`, `product`, `range`, `regex`, `id_type`, `date_order`, `count_matches`, `currency_same`, `required_if` | `rule_failed:<name>`, `rule_unreadable:<name>` |

Any other type (settlement, claim, purchase order, tax form, …) extracts
through the same engine, and gets arithmetic from declared rules.

**Locales measured end to end** (`tests/test_locale_fixtures.py`, synthetic,
known truth): US, UK, EU (de-DE), India (en-IN, lakhs, Dr/Cr), UAE and Japan
(yen). Every clean document comes out whole with no defect flag. Every
corruption (a wrong digit, a dropped row, a swapped debit/credit, mixed
currency, ambiguous dates) raises its own flag.

## Across all documents

| Situation | What happens |
|---|---|
| several documents in one file | split where a new reference corroborates a candidate. Where nothing can decide: ONE record, `possible_multiple_documents`, with the pages |
| stamped VOID / SPECIMEN / COPY / DUPLICATE / NON-NEGOTIABLE / CANCELLED / TEST ONLY | `void_marker` on every value, review |
| stamped PAID | `paid_marker` on every value, review |
| painted over, or too dark to read | on a native page, a value from beneath a dark filled rectangle is blanked; a near-black or grey-washed scan page counts too; empty slots carry `redacted_or_obscured`. A bar on a scan is not detected (its words are unreadable to OCR as well, and come back empty) |
| password-protected PDF | opened with the password given at upload, per file; never stored |
| a table continued over pages | kept whole only when the document numbers the next page of the run **and** reprints the heading; otherwise the other pages' rows are left out, one flag each |
| a table's own total line | left out when its amounts equal the sum of the rows above, and flagged |

## Not supported yet

- **OCR of languages other than English**, and of handwriting.
- **E-invoice verification:** India IRN / signed QR, EU Peppol / XRechnung,
  ZATCA. The QR is not read and the signature is not checked.
- **Import into accounting systems** (Tally, Zoho Books, QuickBooks, Xero):
  the output is Excel only.
- **Regional filing formats** (GST returns, VAT returns, 1099 e-file).
- **Month names other than English**, and non-Gregorian calendars.
- **A running balance as a declared rule** (it needs the previous row). It
  remains a coded bank-statement check.
- **Right-to-left table layout.** Arabic and Hebrew text is read; column
  placement on an RTL table is not verified.
