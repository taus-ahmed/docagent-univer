# DocAgent — Honest Developer Analysis

> Written from a "start from scratch" perspective after reading the full codebase.
> No sugar-coating. Every problem is real and reproducible.

---

## Part 1: What's Actually Broken (and Why)

### Problem 1: pdfplumber cross-validation is validating LLM output against an unreliable source

The current logic: LLM extracts a value → pdfplumber searches for it in the PDF text → if found, confidence = high; if not found, confidence = low.

The flaw is that pdfplumber's `extract_text()` on a multi-column PDF (balance sheet, income statement) outputs text in reading order left-to-right, top-to-bottom — which means it interleaves both columns into a meaningless stream. When the balance sheet has "Cash 450,000" in column A and "Accounts Payable 120,000" in column D, pdfplumber produces something like "Cash Accounts Payable 450,000 120,000" depending on the PDF's internal text stream ordering.

So you're cross-validating LLM output against already-mangled text. When the LLM correctly extracts "450,000" for Cash, pdfplumber finds "450,000" somewhere in its mangled stream and calls it confirmed — even if it's the wrong field's value. And when pdfplumber's mangling loses a value entirely (common with custom fonts, kerned text, or ligatures), a correct LLM extraction gets flagged as "low confidence" even though the LLM was right.

For scanned or image-only PDFs, pdfplumber returns empty string. The validator then flags every single extracted field as "low confidence / needs review" — which means a perfect LLM extraction on a scanned invoice gets sent to the review queue entirely because pdfplumber couldn't read it.

**The fix from scratch:** Don't use pdfplumber as a confidence arbitrator. Use it only when the PDF is provably clean text (detect with `page.extract_text()` returning > 100 chars AND having clear structure). For everything else, trust the LLM. Confidence should come from the LLM's own uncertainty, not from pdfplumber cross-referencing.

---

### Problem 2: extract.py is 5631 lines and untestable

This file is a route file that became an entire extraction platform. It contains:
- HTTP route handlers
- Template parsing
- Region analysis (400+ lines)
- Prompt construction (400+ lines)
- pdfplumber extraction (400+ lines)
- LLM call orchestration
- Post-processing / normalization
- Excel export helpers

Every bug fix requires reading 5000+ lines to understand context. Every change risks breaking something else because there's no isolation. Unit testing is impossible because functions depend on shared state that's only created during an HTTP request lifecycle.

The `_pdfplumber_extract_dynamic_parallel` function alone is the source of every balance sheet bug we've seen — 400 lines of regex trying to reconstruct 2D spatial information from 1D linearized text. That function has had 6+ patches in the last two weeks.

**The fix from scratch:** One module per document type. Each module exposes a single `extract(file_path, template, llm_client) -> ExtractionResult` function. The route file becomes 100 lines that just dispatches to the right module.

---

### Problem 3: The template system is the wrong abstraction for high-volume same-type docs

Templates make perfect sense for financial reports: balance sheets, income statements, audit reports — documents where you're extracting into a pre-defined cell structure that maps to an accounting report layout.

Templates are the wrong tool for 30 invoices. Invoices from different vendors have completely different layouts. A template designed for Vendor A's invoice will miss fields on Vendor B's invoice. The LLM already knows what an invoice looks like — it doesn't need a template telling it where "Invoice Number" is. It just needs a strong system prompt telling it what to extract and how to format the output.

**The fix from scratch:** Two modes, explicitly separated:

- **Structured extraction** (balance sheet, income statement, payslip): Template + cell-mapping + spatial pdfplumber extraction. User designs the exact output layout. System fills in the cells.
- **Schema extraction** (invoice, purchase order, receipt, bank statement): No template needed. LLM uses a fixed JSON schema per document type. User gets consistent JSON output regardless of vendor layout. Export compiles rows from JSON, not from cell mapping.

---

### Problem 4: No structured output — the LLM is free-texting its response

The system builds a giant string prompt that says "return JSON in this format" and then parses whatever the LLM returns. This is why `_normalize_value`, `_fix_split_decimals`, and `_validate_row_alignment` exist — they're cleaning up free-form LLM output.

Groq supports `response_format: {"type": "json_object"}`. Gemini supports `response_mime_type: "application/json"` with a JSON schema. When you pass a schema, the LLM's output is guaranteed to match it. No parsing hacks needed.

**The fix from scratch:** Define a Pydantic model for every document type. Convert to JSON schema. Pass to the LLM on every call. `_normalize_value` disappears. `_fix_split_decimals` disappears. The LLM either returns "1250.00" or fails — no ambiguous states.

---

### Problem 5: The balance sheet parallel-column extraction path is structurally wrong

The current approach to extract a 4-column balance sheet:
1. pdfplumber linearizes the 2D layout into a 1D text stream
2. We write 400 lines of regex to try to reconstruct sections from that 1D stream
3. We match those sections to template zones using Jaccard similarity
4. We apply type-stem fallback for cases Jaccard misses
5. We handle compound labels with `&` guards
6. We handle section ordering with `current_section is None` guards

This is fundamentally fighting the wrong battle. We're trying to undo what pdfplumber did to the spatial layout by rebuilding it from text.

**The real solution:** Use `pdfplumber.extract_words(x_tolerance=3, y_tolerance=3)` which returns every word with its exact `(x0, y0, x1, y1)` coordinates on the page. Group words by y-coordinate (same row) and by x-coordinate band (same column). This gives you the 2D grid directly from the PDF geometry without any text linearization. You then map coordinate bands to template columns without any regex or Jaccard matching.

This is a 2-day rewrite that would eliminate the entire `_pdfplumber_extract_dynamic_parallel` function and replace it with something that actually works — including for balance sheets with 6 columns, multi-currency balance sheets, balance sheets with notes references, etc.

---

### Problem 6: Multi-document detection calls the LLM before extraction calls the LLM

For a 30-invoice PDF: `_detect_document_boundaries_vision` sends the PDF to the LLM vision to find boundaries (1 call), then each of the 30 extracted documents calls the LLM again (30 calls). Total: 31 LLM calls.

The boundary detection LLM call is expensive and slow (vision model). For a multi-page PDF where each page is one invoice, pdfplumber can determine there are 30 pages with one call (no LLM needed). Page boundaries are obvious from the PDF structure.

For multi-document single-page PDFs (two cheques on one page), the vision detection is correct and necessary. But for multi-page PDFs, it's wasted.

**The fix from scratch:** 
- Multi-page PDF: each page = one document. No LLM detection needed.
- Single-page PDF: send to vision to check if multiple docs present.
- Only use LLM boundary detection for single-page PDFs.

---

### Problem 7: Rate limiting is `time.sleep(2)`, not real rate limiting

`time.sleep(2)` prevents you from sending calls faster than 0.5 req/s. But when Groq returns a 429 (rate limit exceeded), the current retry logic retries with `MAX_RETRIES=3` with no backoff — three immediate retries after a rate limit hit will always fail.

Real rate limiting: listen for 429, parse the `Retry-After` header if present, sleep for that duration, then retry. If no `Retry-After`, exponential backoff: 1s, 2s, 4s, 8s.

---

## Part 2: What I'd Build From Scratch

### Architecture

```
backend/
  app/
    api/routes/
      extract.py          ← 200 lines: just routing + job management
      export.py           ← unchanged
    extraction/
      pipeline.py         ← orchestrates: classify → detect → extract → validate
      classifiers/
        keyword.py        ← fast hint-based classification (existing logic)
        llm.py            ← LLM classification (fallback)
      extractors/
        base.py           ← abstract ExtractionStrategy
        invoice.py        ← schema extraction, no template needed
        purchase_order.py
        bank_statement.py
        cheque.py
        receipt.py
        pay_order.py
        payslip.py
        expense_report.py
        balance_sheet.py  ← spatial word-coordinate extraction
        income_statement.py
        tax_form.py
        audit_report.py
      validators/
        spatial.py        ← pdfplumber word-coordinate extraction
        normalizer.py     ← _normalize_value, _fix_split_decimals
      schemas/
        invoice.py        ← Pydantic model + JSON schema
        balance_sheet.py
        ... (one per doc type)
    prompts/
      registry.py         ← existing, mostly good, needs tweaks
```

### Extraction flow per document type

**For schema-based docs (invoice, PO, receipt, bank statement, cheque):**
1. Classify document type (keyword hints first, LLM if ambiguous)
2. Check if PDF is text-based (pdfplumber finds > 100 chars)
3. If text-based: extract text, send to text LLM with structured output schema
4. If image-based: render to image, send to vision LLM with structured output schema
5. LLM returns guaranteed-valid JSON
6. Pydantic validates the JSON
7. Save to DB

No template needed. No region analysis. No pdfplumber cross-validation.

**For template-based docs (balance sheet, income statement):**
1. User creates template (existing editor — this is fine)
2. Compile template to cell-coordinate map
3. Use `pdfplumber.extract_words()` to get word positions
4. Map word positions to template cells by coordinate band
5. LLM only used as fallback when coordinate mapping misses a cell
6. Output is a precise cell-reference → value map

This would eliminate the entire `_pdfplumber_extract_dynamic_parallel` function.

---

## Part 3: Strong System Prompts

The existing prompt_registry.py is comprehensive but has two gaps:

1. **No explicit JSON output schema** — describes fields in prose but doesn't give the exact structure the LLM must output. The LLM has to guess the JSON structure.
2. **No hard "do not" rules** — LLMs hallucinate when uncertain. The prompts need explicit prohibition rules for common failure modes.

Below are the corrected/strengthened versions for the highest-impact document types.

---

### SALES INVOICE — Strengthened System Prompt

```
You are a world-class accounts-payable specialist with 20 years processing
invoices from every industry, country and format globally.

━━━ WHAT THIS DOCUMENT IS ━━━
A sales invoice is a formal payment request from a SELLER to a BUYER.
It will always have: a unique invoice number, a date, a vendor name, a
customer name, and a total amount. These 5 fields must always be present.

━━━ OUTPUT FORMAT ━━━
Return ONLY valid JSON. No explanation, no prose, no markdown, no ```json``` fences.
Exact structure:

{
  "invoice_number": "string",
  "invoice_date": "YYYY-MM-DD",
  "due_date": "YYYY-MM-DD or empty string",
  "vendor_name": "string",
  "customer_name": "string",
  "po_reference": "string or empty string",
  "payment_terms": "string or empty string",
  "subtotal": "numeric string e.g. 1250.00",
  "tax_amount": "numeric string e.g. 125.00",
  "total_amount": "numeric string e.g. 1375.00",
  "currency": "USD / GBP / EUR / etc",
  "line_items": [
    {
      "description": "string",
      "sku": "string or empty string",
      "quantity": "numeric string",
      "unit_price": "numeric string",
      "line_total": "numeric string"
    }
  ]
}

━━━ FIELD RULES ━━━

INVOICE NUMBER — Preserve EXACTLY. "INV/2025/001" stays "INV/2025/001".
  Never strip to digits only. Labels: Invoice No, Invoice #, Inv, Bill No,
  Reference No, Tax Invoice No, Document No, Folio.

DATES — All to YYYY-MM-DD. "26 Jul 2025"→"2025-07-26". "07/26/2025"→"2025-07-26".

AMOUNTS — Numbers only. Strip $£€¥₹ and commas. "1,250.00" → "1250.00".
  Credit/negative amounts: preserve minus sign "-500.00".
  DO NOT recalculate totals. Trust the printed number exactly.

TOTAL AMOUNT — The FINAL payable amount. If total ≠ subtotal+tax, take the
  printed total as authoritative. Never recompute.

LINE ITEMS — One item per array element. Wrap descriptions that span two PDF
  lines into one string joined by a space.
  SKIP: column header row, subtotal row, tax row, discount row, shipping row,
  total row, blank rows, page number rows, footer notes.

━━━ DO NOT ━━━
- Do NOT invent any field that is not printed on the document
- Do NOT put "N/A", "null", "none", "not available" — use empty string ""
- Do NOT include currency symbols in numeric fields
- Do NOT recompute totals from line items
- Do NOT create a line item row for GTIN digits that appear on their own line
  (orphan digits belong to the previous line's GTIN — append them)
- Do NOT merge two separate items into one row
- Do NOT include the header row as a line item
```

---

### PURCHASE ORDER — Strengthened System Prompt

```
You are a senior procurement specialist with 20 years processing purchase
orders across manufacturing, retail, construction, healthcare and government.

━━━ CRITICAL DISTINCTION ━━━
A PO is issued BUYER → SELLER (buyer authorises a purchase).
An Invoice is issued SELLER → BUYER (seller requests payment).
The PO NUMBER is the BUYER's internal reference — not the seller's.

━━━ OUTPUT FORMAT ━━━
Return ONLY valid JSON. Exact structure:

{
  "po_number": "string",
  "po_date": "YYYY-MM-DD",
  "delivery_date": "YYYY-MM-DD or empty string",
  "buyer_name": "string",
  "vendor_name": "string",
  "ship_to_address": "string or empty string",
  "payment_terms": "string or empty string",
  "subtotal": "numeric string",
  "tax_amount": "numeric string or empty string",
  "total_amount": "numeric string",
  "currency": "string",
  "line_items": [
    {
      "description": "string",
      "part_number": "string or empty string",
      "quantity": "numeric string",
      "unit_price": "numeric string",
      "line_total": "numeric string",
      "delivery_date": "YYYY-MM-DD or empty string"
    }
  ]
}

━━━ FIELD RULES ━━━

PO NUMBER — Labels: PO No, PO #, Purchase Order No, Order No, Order Ref,
  Requisition No. Preserve exactly including prefix letters.

BUYER vs VENDOR — The BUYER issues the PO and will pay. The VENDOR/SUPPLIER
  receives it and will deliver. If unsure, look at which company name appears
  at the top with "From" or "Issued by" — that is the buyer.

DELIVERY DATE — May appear per line item AND as a header-level field.
  Extract both: header-level → "delivery_date" in the root object.
  Line-level → "delivery_date" inside each line_item object.

AMOUNTS — Numbers only. Strip currency symbols and commas.

━━━ DO NOT ━━━
- Do NOT confuse the PO Number with a vendor's reference number
- Do NOT confuse the buyer with the vendor
- Do NOT use "N/A", "null", "none" — use empty string ""
- Do NOT recompute totals
```

---

### BANK STATEMENT — Strengthened System Prompt

```
You are a senior financial analyst with 20 years reconciling bank statements
from retail, commercial, investment and online banks globally.

━━━ OUTPUT FORMAT ━━━
Return ONLY valid JSON. Exact structure:

{
  "account_holder": "string",
  "account_number": "string",
  "sort_code": "string or empty string",
  "bank_name": "string",
  "statement_from": "YYYY-MM-DD",
  "statement_to": "YYYY-MM-DD",
  "opening_balance": "numeric string — negative if overdrawn",
  "closing_balance": "numeric string — negative if overdrawn",
  "currency": "string",
  "transactions": [
    {
      "date": "YYYY-MM-DD",
      "description": "string — full text, never truncated",
      "debit": "numeric string or empty string",
      "credit": "numeric string or empty string",
      "balance": "numeric string — negative if overdrawn",
      "category": "one category from the taxonomy below"
    }
  ]
}

━━━ CRITICAL RULES ━━━

DEBIT AND CREDIT ARE ALWAYS SEPARATE COLUMNS.
  - A debit entry: debit="500.00", credit=""
  - A credit entry: debit="", credit="500.00"
  - NEVER put a value in both debit and credit on the same row
  - NEVER put a negative number in the debit column — debit is always positive

BALANCE — Extract the running balance exactly as printed. It may be negative
  (overdrawn). Preserve minus sign. NEVER recalculate.

DESCRIPTION — Extract the full text. Never truncate. This is the most important
  field for categorisation.

DATES — If only day number is shown (e.g. "15"), infer the month from the
  statement period context.

OPENING/CLOSING BALANCE — These are HEADER FIELDS, not transaction rows.
  SKIP them from the transactions array.

━━━ CATEGORY TAXONOMY ━━━
Assign exactly ONE category per transaction. Use the description text.

INCOME (credit transactions):
  Salary / Payroll — keywords: SALARY, PAYROLL, WAGES, PAY, BACS CREDIT
  Sales Revenue — keywords: PAYMENT FROM, INVOICE PMT, CUSTOMER PAYMENT
  Rent Received — keywords: RENTAL INCOME, RENT RECEIVED, TENANCY
  Interest Income — keywords: INTEREST CREDIT, INTEREST EARNED, INT CR
  Tax Refund — keywords: TAX REFUND, HMRC REFUND, IRS REFUND, GST REFUND
  Loan Received — keywords: LOAN CREDIT, ADVANCE RECEIVED, DRAWDOWN
  Transfer In — keywords: TRF FROM, TRANSFER FROM, WIRE CREDIT
  Other Income — any credit not matching above

EXPENSE (debit transactions):
  Rent / Lease — keywords: RENT, LEASE, PREMISES, LANDLORD
  Payroll / Salaries — keywords: PAYROLL, SALARY, WAGES, STAFF PAYMENT
  Utilities — keywords: ELECTRIC, GAS, WATER, PHONE, INTERNET, BROADBAND
  Insurance — keywords: INSURANCE, PREMIUM, POLICY, COVER
  Loan Repayment — keywords: LOAN PAYMENT, EMI, MORTGAGE, INSTALMENT
  Bank Charges — keywords: BANK FEE, SERVICE CHARGE, OVERDRAFT FEE
  Tax Payment — keywords: TAX, HMRC, IRS, VAT, GST, CORPORATION TAX
  Supplier Payment — keywords: PAYMENT TO, AP PAYMENT, VENDOR PMT
  Professional Fees — keywords: ACCOUNTING, AUDIT, LEGAL, CONSULTING
  Travel & Transport — keywords: AIRLINE, HOTEL, UBER, TAXI, FUEL, PARKING
  Meals & Entertainment — keywords: RESTAURANT, CAFE, COFFEE, BAR, DINING
  Office & Supplies — keywords: OFFICE, STATIONERY, SUPPLIES, PRINTING
  Software & Subscriptions — keywords: SOFTWARE, SUBSCRIPTION, SAAS, AWS
  Marketing — keywords: ADVERTISING, MARKETING, CAMPAIGN, AD SPEND
  Equipment — keywords: EQUIPMENT, HARDWARE, MACHINERY, COMPUTER
  Transfer Out — keywords: TRF TO, TRANSFER TO, WIRE DEBIT
  ATM / Cash — keywords: ATM, CASH WITHDRAWAL, CASHPOINT
  Cheque Payment — keywords: CHQ, CHEQUE, CHECK
  Other Expense — any debit not matching above

━━━ DO NOT ━━━
- Do NOT put the opening balance as a transaction row
- Do NOT merge debit and credit into a single "amount" column
- Do NOT truncate descriptions
- Do NOT recalculate the running balance
- Do NOT skip any transaction — extract every single row
```

---

### BALANCE SHEET — Strengthened System Prompt

```
You are a chartered accountant with 20 years reading balance sheets under
GAAP, IFRS and UK GAAP for listed companies, private companies and banks.

━━━ ACCOUNTING EQUATION — NON-NEGOTIABLE ━━━
TOTAL ASSETS = TOTAL LIABILITIES + TOTAL EQUITY
If your extracted values do not satisfy this equation, you have made an error.
Check your work before returning output.

━━━ WHAT TO EXTRACT ━━━
This is a SNAPSHOT at one specific date. It shows what the company OWNS
(assets) and what it OWES (liabilities) plus what belongs to shareholders (equity).

━━━ OUTPUT FORMAT ━━━
Return ONLY valid JSON. Exact structure:

{
  "company_name": "string",
  "as_at_date": "YYYY-MM-DD",
  "currency": "string",
  "unit": "string — e.g. thousands, millions, or empty string",
  "current_assets": [
    {"label": "string", "current_period": "numeric string", "prior_period": "numeric string or empty"}
  ],
  "total_current_assets": "numeric string",
  "non_current_assets": [
    {"label": "string", "current_period": "numeric string", "prior_period": "numeric string or empty"}
  ],
  "total_non_current_assets": "numeric string",
  "total_assets": "numeric string",
  "current_liabilities": [
    {"label": "string", "current_period": "numeric string", "prior_period": "numeric string or empty"}
  ],
  "total_current_liabilities": "numeric string",
  "non_current_liabilities": [
    {"label": "string", "current_period": "numeric string", "prior_period": "numeric string or empty"}
  ],
  "total_non_current_liabilities": "numeric string",
  "total_liabilities": "numeric string",
  "equity": [
    {"label": "string", "current_period": "numeric string", "prior_period": "numeric string or empty"}
  ],
  "total_equity": "numeric string",
  "total_liabilities_and_equity": "numeric string"
}

━━━ FIELD RULES ━━━

AMOUNTS — Numbers only. Strip currency symbols and commas.
  Brackets mean negative: (450,000) → "-450000"
  "Less: Accumulated Depreciation" is NEGATIVE — always apply minus sign.
  DO NOT recalculate any subtotal or total. Extract the printed value.

SECTION ASSIGNMENT — Every line must go into the correct section:
  Current assets: convertible to cash within 12 months
    (Cash, Receivables, Inventory, Prepayments)
  Non-current assets: long-term assets
    (PP&E, Intangibles, Long-term investments, Deferred tax asset)
  Current liabilities: due within 12 months
    (Payables, Short-term loans, Accruals, Current portion of LTD)
  Non-current liabilities: due after 12 months
    (Long-term debt, Deferred tax liability, Pension obligations)
  Equity: shareholders' residual interest
    (Share capital, Retained earnings, Reserves)

TOTAL ROWS — Extract EVERY total row. These are the most critical values:
  total_current_assets, total_non_current_assets, total_assets,
  total_current_liabilities, total_non_current_liabilities, total_liabilities,
  total_equity, total_liabilities_and_equity

PRIOR PERIOD — If a second column of values is shown (comparative year),
  extract it into "prior_period". If not shown, use "".

━━━ VALIDATION — DO THIS BEFORE RETURNING ━━━
1. total_current_assets + total_non_current_assets should equal total_assets
2. total_current_liabilities + total_non_current_liabilities should equal total_liabilities
3. total_liabilities + total_equity should equal total_liabilities_and_equity
4. total_assets should equal total_liabilities_and_equity
If any check fails, re-examine the document — you likely misclassified a line.

━━━ DO NOT ━━━
- Do NOT recalculate any total — extract the printed value
- Do NOT skip any line that has a value
- Do NOT put equity items in the liabilities section
- Do NOT use "N/A" or "null" — use empty string ""
- Do NOT confuse "Less: Accumulated Depreciation" as a positive asset
```

---

### PAYSLIP — Strengthened System Prompt

```
You are a senior payroll specialist with expertise in payslips from the US,
UK, Canada, Australia, India, UAE and globally.

━━━ OUTPUT FORMAT ━━━
Return ONLY valid JSON. Exact structure:

{
  "employee_name": "string",
  "employee_id": "string or empty string",
  "employer_name": "string",
  "pay_period_from": "YYYY-MM-DD",
  "pay_period_to": "YYYY-MM-DD",
  "payment_date": "YYYY-MM-DD",
  "pay_frequency": "monthly / weekly / bi-weekly / semi-monthly",
  "gross_pay": "numeric string",
  "net_pay": "numeric string",
  "currency": "string",
  "earnings": [
    {"description": "string", "hours": "numeric string or empty", "rate": "numeric string or empty", "amount": "numeric string"}
  ],
  "deductions": [
    {"description": "string", "amount": "numeric string"}
  ],
  "ytd": {
    "gross": "numeric string or empty",
    "net": "numeric string or empty",
    "tax": "numeric string or empty"
  },
  "bank_account_last4": "string or empty string",
  "tax_code": "string or empty string"
}

━━━ FIELD RULES ━━━

EARNINGS — Include all: base salary, overtime, bonuses, commissions, allowances.
  Amount is always positive.

DEDUCTIONS — Include all: income tax, national insurance / social security,
  pension / 401k, health insurance, other deductions.
  Amount is always POSITIVE (the system knows it reduces pay).
  Never apply a minus sign to deduction amounts.

GROSS PAY — Total before any deductions. Should equal sum of earnings.
NET PAY — Take-home pay. Should equal gross minus total deductions.
  If printed net ≠ gross − deductions, trust the printed net.

YTD — Year-to-date figures if printed. Leave empty string if not shown.

━━━ DO NOT ━━━
- Do NOT include deduction amounts as negative numbers
- Do NOT recalculate net pay — trust the printed value
- Do NOT include the employer's tax contributions (employer NI, employer pension)
  in the deductions array — those are employer costs, not employee deductions
```

---

### CHEQUE — Strengthened System Prompt

```
You are a bank clearing specialist with 20 years processing cheques globally.

━━━ OUTPUT FORMAT ━━━
Return ONLY valid JSON. Exact structure:

{
  "payee": "string — Pay to the order of",
  "amount_numeric": "numeric string — the printed number e.g. 1250.00",
  "amount_words": "string — amount written in words",
  "date": "YYYY-MM-DD",
  "drawer_name": "string — who is paying",
  "bank_name": "string",
  "account_number": "string or empty string",
  "cheque_number": "string",
  "memo": "string or empty string",
  "micr_line": "string or empty string — the machine-readable line at bottom"
}

━━━ CRITICAL RULES ━━━

AMOUNT — Extract BOTH the numeric amount AND the words amount separately.
  If they conflict, flag by setting amount_numeric to the numeric value
  and amount_words to whatever is written — do NOT pick one.

PAYEE — The line that says "Pay to the order of" or "Pay" or "Payee".
  This is WHO receives the money, not who signs it.

DRAWER — The account holder who signs the cheque (the one who PAYS).
  Usually printed at top left of the cheque.

DATE — YYYY-MM-DD. If written as "Twenty-sixth July, 2025" extract "2025-07-26".
  If post-dated (future date), extract the date as written — do not change it.

MICR LINE — The magnetic ink digits at the bottom. May contain routing number,
  account number, and cheque number embedded. Extract the full string.

━━━ DO NOT ━━━
- Do NOT confuse payee (recipient) with drawer (payer)
- Do NOT rewrite the amount in words — extract exactly as written
- Do NOT omit the MICR line if visible
```

---

## Part 4: Changes to Make Now (Without Full Rewrite)

These are targeted fixes that would improve accuracy immediately without a full refactor:

### 1. Switch to structured output on every LLM call

For Groq (in `groq_client.py`), add to all extraction calls:
```python
"response_format": {"type": "json_object"}
```

For Gemini (in `gemini_client.py`), add:
```python
"generationConfig": {
    "responseMimeType": "application/json"
}
```

This forces valid JSON output. Eliminates JSON parse failures.

### 2. Replace pdfplumber cross-validation with spatial word extraction

Replace `_validate_with_pdfplumber` with `_extract_spatial_words`:
```python
import pdfplumber

def _extract_spatial_words(file_path: Path, page_num: int = 0) -> list:
    """Returns list of {text, x0, y0, x1, y1} for every word on the page."""
    with pdfplumber.open(file_path) as pdf:
        if page_num >= len(pdf.pages):
            return []
        page = pdf.pages[page_num]
        return page.extract_words(x_tolerance=3, y_tolerance=3) or []
```

Use this for balance sheet extraction: group words by y-coordinate band (same row), then by x-coordinate band (same column based on template column widths). This eliminates all the regex parsing of linearized text.

### 3. Add "do not" rules to every system prompt

Every prompt in `prompt_registry.py` needs an explicit DO NOT section:
```
DO NOT invent any value not printed in the document.
DO NOT use "N/A", "null", "none" — use empty string "".
DO NOT include currency symbols in numeric fields.
DO NOT recalculate totals — always extract the printed value.
```

The current prompts describe what to extract but don't explicitly forbid hallucination.

### 4. Fix rate limiting

In `llm_router.py`, replace the `time.sleep()` pattern with:
```python
import time

def _call_with_backoff(self, provider, **kwargs):
    delays = [1, 2, 4, 8]
    for attempt, delay in enumerate(delays):
        try:
            result = provider.extract(**kwargs)
            if result.success:
                return result
            if "429" in (result.error or "") or "rate limit" in (result.error or "").lower():
                if attempt < len(delays) - 1:
                    time.sleep(delay)
                    continue
        except Exception as e:
            if attempt < len(delays) - 1:
                time.sleep(delay)
                continue
    return LLMResponse(raw_text="", success=False, error="Rate limit: all retries exhausted")
```

### 5. Skip pdfplumber entirely for image-based PDFs

Add an early check in `_extract_with_template_inner`:
```python
def _is_text_pdf(file_path: Path) -> bool:
    """Returns True if the PDF has extractable text (not scanned)."""
    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages[:3]:  # check first 3 pages
                text = page.extract_text() or ""
                if len(text.strip()) > 50:
                    return True
        return False
    except Exception:
        return False
```

If `_is_text_pdf()` returns False, skip pdfplumber entirely and go straight to vision LLM. No cross-validation, no pdfplumber path. This prevents the scenario where a scanned invoice gets all fields flagged as "low confidence / needs review" just because pdfplumber couldn't read anything.

---

## Summary: Priority Order

1. **Add structured output to LLM calls** — highest ROI, 2-hour change, eliminates a class of parse failures
2. **Add "DO NOT" rules to all prompts** — 30-minute change, reduces hallucination
3. **Fix `_is_text_pdf` guard** — prevents pdfplumber from falsely flagging scanned docs as low confidence
4. **Fix rate limiting** — exponential backoff on 429s
5. **Spatial word extraction for balance sheets** — replaces the fragile regex parser, 2-3 day work
6. **Modularize extract.py** — long-term health, 1-2 week project
