# Accuracy report — 2026-08-18 01:33:47

- git: `0feb483`  mode: **replay**  repeat: 1
- config: {"USE_NEW_EXTRACTOR": "true", "PRIMARY_LLM": "gemini", "GEMINI_MODEL": "gemini-2.5-flash-lite"}

## Overall

| metric | value |
|---|---|
| **accuracy (correct / gold-valued)** | **62.7%** |
| **hallucination rate (hallucinated / extracted)** | **52.6%** |
| **└ invention rate (value found NOWHERE in the PDF)** | **0.6%** |
| └ misplacement (real content, slot gold leaves empty) | 41.3% |
| hallucinated values | 271 (invented 3, misplaced 268) |
| near misses | 4 |
| outcome counts | {"wrong": 3, "correct": 237, "missed": 134, "hallucinated": 271, "near": 4, "empty_ok": 12} |

## By document type

| document type | accuracy | halluc. rate | invented | correct | near | wrong | missed | halluc. |
|---|---|---|---|---|---|---|---|---|
| balance_sheet | 80.4% | 51.9% | 0 | 37 | 0 | 1 | 8 | 41 |
| bank_statement | 100.0% | 0.0% | 0 | 70 | 0 | 0 | 0 | 0 |
| cheque | 72.7% | 0.0% | 0 | 8 | 3 | 0 | 0 | 0 |
| expense_report | 7.4% | 90.7% | 3 | 4 | 0 | 0 | 50 | 39 |
| income_statement | 100.0% | 0.0% | 0 | 25 | 0 | 0 | 0 | 0 |
| payslip | 62.9% | 56.6% | 0 | 44 | 0 | 2 | 24 | 60 |
| purchase_order | 96.8% | 49.2% | 0 | 30 | 1 | 0 | 0 | 30 |
| sales_invoice | 26.8% | 84.2% | 0 | 19 | 0 | 0 | 52 | 101 |

## By field type

| field type | accuracy | halluc. rate | invented | correct | near | wrong | missed | halluc. |
|---|---|---|---|---|---|---|---|---|
| date | 70.0% | 0.0% | 0 | 21 | 0 | 0 | 9 | 0 |
| money | 71.4% | 10.8% | 0 | 115 | 0 | 1 | 45 | 14 |
| number | 25.0% | 0.0% | 0 | 3 | 0 | 0 | 9 | 0 |
| string | 56.0% | 71.2% | 3 | 98 | 4 | 2 | 71 | 257 |

## Per document

| document | type | accuracy | halluc. | invented | route | notes |
|---|---|---|---|---|---|---|
| BS-2024-Q1 | balance_sheet | 80.4% | 41 | 0 | BS-2024-Q1.pdf: file_type=digital_pdf pages=2 text_len=1242 |  |
| CHQ-001847 | cheque | 72.7% | 0 | 0 | CHQ-001847.pdf: file_type=digital_pdf pages=1 text_len=501 |  |
| EXP-2024-0081 | expense_report | 7.4% | 39 | 3 | EXP-2024-0081.pdf: file_type=digital_pdf pages=1 text_len=11 |  |
| INV-2024-0031 | sales_invoice | 30.3% | 52 | 0 | INV-2024-0031.pdf: file_type=digital_pdf pages=1 text_len=97 |  |
| INV-2024-0047 | sales_invoice | 23.7% | 49 | 0 | INV-2024-0047.pdf: file_type=digital_pdf pages=1 text_len=10 |  |
| IS-2024-Q4 | income_statement | 100.0% | 0 | 0 | IS-2024-Q4.pdf: file_type=digital_pdf pages=2 text_len=970 |  |
| PAYSLIP-EMP-0007-APR2024 | payslip | 32.4% | 0 | 0 | PAYSLIP-EMP-0007-APR2024.pdf: file_type=digital_pdf pages=2  | FELL BACK TO LEGACY ENGINE |
| PAYSLIP-EMP-0012-APR2024 | payslip | 97.0% | 60 | 0 | PAYSLIP-EMP-0012-APR2024.pdf: file_type=digital_pdf pages=2  |  |
| PO-2024-0018 | purchase_order | 96.8% | 30 | 0 | PO-2024-0018.pdf: file_type=digital_pdf pages=1 text_len=104 |  |
| STMT-2024-01 | bank_statement | 100.0% | 0 | 0 | STMT-2024-01.pdf: file_type=digital_pdf pages=1 text_len=140 |  |

## Mismatches (everything not correct)

| document | field | outcome | expected | actual |
|---|---|---|---|---|
| BS-2024-Q1 | Total Current Assets | wrong | 1129003 | 8,800 |
| BS-2024-Q1 | TOTAL ASSETS | missed | 1365503 | None |
| BS-2024-Q1 | TOTAL LIABILITIES | missed | 550600 | None |
| BS-2024-Q1 | Total Equity | missed | 698104 | None |
| BS-2024-Q1 | TOTAL LIABILITIES & EQUITY | missed | 1248704 | None |
| BS-2024-Q1 | Cash & Cash Equivalents | hallucinated (misplaced) | None | 143,803 |
| BS-2024-Q1 | Accounts Receivable (net) | hallucinated (misplaced) | None | 348,200 |
| BS-2024-Q1 | Inventory | hallucinated (misplaced) | None | 612,000 |
| BS-2024-Q1 | Prepaid Expenses | hallucinated (misplaced) | None | 16,200 |
| BS-2024-Q1 | Property & Equipment (gross) | hallucinated (misplaced) | None | 240,000 |
| BS-2024-Q1 | Less: Accum. Depreciation | hallucinated (misplaced) | None | 108,500 |
| BS-2024-Q1 | Security Deposits | hallucinated (misplaced) | None | 85,000 |
| BS-2024-Q1 | Intangibles (net) | hallucinated (misplaced) | None | 20,000 |
| BS-2024-Q1 | Accounts Payable | hallucinated (misplaced) | None | 254,800 |
| BS-2024-Q1 | Accrued Liabilities | hallucinated (misplaced) | None | 44,200 |
| BS-2024-Q1 | Short-term Loan — First National Bank | hallucinated (misplaced) | None | 80,000 |
| BS-2024-Q1 | Deferred Revenue | hallucinated (misplaced) | None | 18,200 |
| BS-2024-Q1 | Current Portion of Long-term Debt | hallucinated (misplaced) | None | 24,000 |
| BS-2024-Q1 | Long-term Loan — First National Bank | hallucinated (misplaced) | None | 121,000 |
| BS-2024-Q1 | Deferred Tax Liability | hallucinated (misplaced) | None | 8,400 |
| BS-2024-Q1 | Common Stock (100 shares @ $1,000 par) | hallucinated (misplaced) | None | 100,000 |
| BS-2024-Q1 | Retained Earnings | hallucinated (misplaced) | None | 550,751 |
| BS-2024-Q1 | B7 | hallucinated (misplaced) | None | 1,129,003 |
| BS-2024-Q1 | B14 | hallucinated (misplaced) | None | 236,500 |
| BS-2024-Q1 | B24 | hallucinated (misplaced) | None | 421,200 |
| BS-2024-Q1 | B29 | hallucinated (misplaced) | None | 129,400 |
| BS-2024-Q1 | current_assets[pred_row 5].Label | hallucinated (misplaced) | None | Cash & Cash Equivalents |
| BS-2024-Q1 | current_assets[pred_row 5].Amount | hallucinated (misplaced) | None | 143,803 |
| BS-2024-Q1 | current_assets[pred_row 6].Label | hallucinated (misplaced) | None | Property & Equipment (gross) |
| BS-2024-Q1 | current_assets[pred_row 6].Amount | hallucinated (misplaced) | None | 240,000 |
| BS-2024-Q1 | current_liabilities[pred_row 5].Label | hallucinated (misplaced) | None | Accounts Payable |
| BS-2024-Q1 | current_liabilities[pred_row 5].Amount | hallucinated (misplaced) | None | 254,800 |
| BS-2024-Q1 | long_term_liabilities[pred_row 2].Label | hallucinated (misplaced) | None | Long-term Loan — First National Bank |
| BS-2024-Q1 | long_term_liabilities[pred_row 2].Amount | hallucinated (misplaced) | None | 121,000 |
| BS-2024-Q1 | shareholders_equity[row 1].Label | missed | Retained Earnings | None |
| BS-2024-Q1 | shareholders_equity[row 1].Amount | missed | 550751 | None |
| BS-2024-Q1 | shareholders_equity[row 2].Label | missed | Net Income YTD Q1 | None |
| BS-2024-Q1 | shareholders_equity[row 2].Amount | missed | 47353 | None |
| BS-2024-Q1 | TOTAL ASSETS[pred_row 0].Label | hallucinated (misplaced) | None | Cash & Cash Equivalents |
| BS-2024-Q1 | TOTAL ASSETS[pred_row 0].Value | hallucinated (misplaced) | None | 143,803 |
| BS-2024-Q1 | TOTAL LIABILITIES[pred_row 0].Label | hallucinated (misplaced) | None | Accounts Payable |
| BS-2024-Q1 | TOTAL LIABILITIES[pred_row 0].Value | hallucinated (misplaced) | None | 254,800 |
| BS-2024-Q1 | Retained Earnings[pred_row 0].Label | hallucinated (misplaced) | None | Retained Earnings |
| BS-2024-Q1 | Retained Earnings[pred_row 0].Value | hallucinated (misplaced) | None | 550,751 |
| BS-2024-Q1 | Net Income YTD Q1[pred_row 0].Label | hallucinated (misplaced) | None | Retained Earnings |
| BS-2024-Q1 | Net Income YTD Q1[pred_row 0].Value | hallucinated (misplaced) | None | 550,751 |
| BS-2024-Q1 | Total Equity[pred_row 0].Label | hallucinated (misplaced) | None | Retained Earnings |
| BS-2024-Q1 | Total Equity[pred_row 0].Value | hallucinated (misplaced) | None | 550,751 |
| BS-2024-Q1 | TOTAL LIABILITIES & EQUITY[pred_row 0].Label | hallucinated (misplaced) | None | Retained Earnings |
| BS-2024-Q1 | TOTAL LIABILITIES & EQUITY[pred_row 0].Value | hallucinated (misplaced) | None | 550,751 |
| CHQ-001847 | Amount in Words | near | Eight Thousand Four Hundred Ten and 00/100 *** U.S. DOLLARS  | Eight Thousand Four Hundred Ten and 00/100 |
| CHQ-001847 | Routing Number | near | 021000021 | A021000021A |
| CHQ-001847 | Account Number | near | 7743882201 | C7743882201C |
| EXP-2024-0081 | Report No | missed | EXP-2024-0081 | None |
| EXP-2024-0081 | Manager | missed | Janet Wu | None |
| EXP-2024-0081 | Period | missed | March 15–22, 2024 | None |
| EXP-2024-0081 | Purpose | missed | Supplier site visit – Pacific Steel, Los Angeles | None |
| EXP-2024-0081 | Status | missed | APPROVED | None |
| EXP-2024-0081 | MERCHANT NAME | hallucinated (misplaced) | None | NEXUS GLOBAL TRADING LLC |
| EXP-2024-0081 | Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| EXP-2024-0081 | Phone | hallucinated (misplaced) | None | (212) 555-0148 |
| EXP-2024-0081 | 03/15 | hallucinated (misplaced) | None | 03/15 |
| EXP-2024-0081 | 03/16 | hallucinated (misplaced) | None | 03/16 |
| EXP-2024-0081 | 03/17 | hallucinated (misplaced) | None | 03/17 |
| EXP-2024-0081 | 03/18 | hallucinated (misplaced) | None | 03/18 |
| EXP-2024-0081 | expenses[row 0].Date | missed | 03/15 | None |
| EXP-2024-0081 | expenses[row 0].Type | missed | Airfare | None |
| EXP-2024-0081 | expenses[row 0].Description | missed | Delta Airlines JFK–LAX round trip | None |
| EXP-2024-0081 | expenses[row 0].Category | missed | Travel | None |
| EXP-2024-0081 | expenses[row 0].Amount | missed | 842.0 | None |
| EXP-2024-0081 | expenses[row 1].Date | missed | 03/15 | None |
| EXP-2024-0081 | expenses[row 1].Type | missed | Taxi | None |
| EXP-2024-0081 | expenses[row 1].Description | missed | Airport to hotel LAX | None |
| EXP-2024-0081 | expenses[row 1].Category | missed | Travel | None |
| EXP-2024-0081 | expenses[row 1].Amount | missed | 38.5 | None |
| EXP-2024-0081 | expenses[row 2].Date | missed | 03/15 | None |
| EXP-2024-0081 | expenses[row 2].Type | missed | Hotel | None |
| EXP-2024-0081 | expenses[row 2].Description | missed | Hilton LAX – 2 nights | None |
| EXP-2024-0081 | expenses[row 2].Category | missed | Lodging | None |
| EXP-2024-0081 | expenses[row 2].Amount | missed | 389.0 | None |
| EXP-2024-0081 | expenses[row 3].Date | missed | 03/16 | None |
| EXP-2024-0081 | expenses[row 3].Type | missed | Meals | None |
| EXP-2024-0081 | expenses[row 3].Description | missed | Hotel breakfast | None |
| EXP-2024-0081 | expenses[row 3].Category | missed | Meals | None |
| EXP-2024-0081 | expenses[row 3].Amount | missed | 24.75 | None |
| EXP-2024-0081 | expenses[row 4].Date | missed | 03/16 | None |
| EXP-2024-0081 | expenses[row 4].Type | missed | M&E | None |
| EXP-2024-0081 | expenses[row 4].Description | missed | Client lunch w/ Pacific Steel (4 pax) | None |
| EXP-2024-0081 | expenses[row 4].Category | missed | Meals & Entmt | None |
| EXP-2024-0081 | expenses[row 4].Amount | missed | 187.4 | None |
| EXP-2024-0081 | expenses[row 5].Date | missed | 03/16 | None |
| EXP-2024-0081 | expenses[row 5].Type | missed | Taxi | None |
| EXP-2024-0081 | expenses[row 5].Description | missed | Hotel to Pacific Steel facility | None |
| EXP-2024-0081 | expenses[row 5].Category | missed | Travel | None |
| EXP-2024-0081 | expenses[row 5].Amount | missed | 22.0 | None |
| EXP-2024-0081 | expenses[row 6].Date | missed | 03/17 | None |
| EXP-2024-0081 | expenses[row 6].Type | missed | Meals | None |
| EXP-2024-0081 | expenses[row 6].Description | missed | Team dinner (2 pax) | None |
| EXP-2024-0081 | expenses[row 6].Category | missed | Meals | None |
| EXP-2024-0081 | expenses[row 6].Amount | missed | 95.6 | None |
| EXP-2024-0081 | expenses[row 7].Date | missed | 03/18 | None |
| EXP-2024-0081 | expenses[row 7].Type | missed | Taxi | None |
| EXP-2024-0081 | expenses[row 7].Description | missed | Hotel to LAX | None |
| EXP-2024-0081 | expenses[row 7].Category | missed | Travel | None |
| EXP-2024-0081 | expenses[row 7].Amount | missed | 41.0 | None |
| EXP-2024-0081 | expenses[row 8].Date | missed | 03/18 | None |
| EXP-2024-0081 | expenses[row 8].Type | missed | Parking | None |
| EXP-2024-0081 | expenses[row 8].Description | missed | JFK long-term parking 3 days | None |
| EXP-2024-0081 | expenses[row 8].Category | missed | Travel | None |
| EXP-2024-0081 | expenses[row 8].Amount | missed | 87.0 | None |
| EXP-2024-0081 | NEXUS GLOBAL TRADING LLC[pred_row 0].Label | INVENTED | None | MERCHANT NAME |
| EXP-2024-0081 | NEXUS GLOBAL TRADING LLC[pred_row 0].Value | hallucinated (misplaced) | None | NEXUS GLOBAL TRADING LLC |
| EXP-2024-0081 | NEXUS GLOBAL TRADING LLC[pred_row 1].Label | INVENTED | None | Address |
| EXP-2024-0081 | NEXUS GLOBAL TRADING LLC[pred_row 1].Value | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| EXP-2024-0081 | NEXUS GLOBAL TRADING LLC[pred_row 2].Label | INVENTED | None | Phone |
| EXP-2024-0081 | NEXUS GLOBAL TRADING LLC[pred_row 2].Value | hallucinated (misplaced) | None | (212) 555-0148 |
| EXP-2024-0081 | Employee:[pred_row 0].Label | hallucinated (misplaced) | None | Employee: |
| EXP-2024-0081 | Employee:[pred_row 0].Value | hallucinated (misplaced) | None | Marcus A. Thompson |
| EXP-2024-0081 | Employee:[pred_row 1].Label | hallucinated (misplaced) | None | Employee ID: |
| EXP-2024-0081 | Employee:[pred_row 1].Value | hallucinated (misplaced) | None | EMP-0012 |
| EXP-2024-0081 | Employee:[pred_row 2].Label | hallucinated (misplaced) | None | Department: |
| EXP-2024-0081 | Employee:[pred_row 2].Value | hallucinated (misplaced) | None | Procurement |
| EXP-2024-0081 | Date[pred_row 0].Label | hallucinated (misplaced) | None | 03/15 |
| EXP-2024-0081 | Date[pred_row 0].Value | hallucinated (misplaced) | None | 03/15 |
| EXP-2024-0081 | Date[pred_row 1].Label | hallucinated (misplaced) | None | 03/15 |
| EXP-2024-0081 | Date[pred_row 1].Value | hallucinated (misplaced) | None | 03/15 |
| EXP-2024-0081 | Date[pred_row 2].Label | hallucinated (misplaced) | None | 03/15 |
| EXP-2024-0081 | Date[pred_row 2].Value | hallucinated (misplaced) | None | 03/15 |
| EXP-2024-0081 | Date[pred_row 3].Label | hallucinated (misplaced) | None | 03/16 |
| EXP-2024-0081 | Date[pred_row 3].Value | hallucinated (misplaced) | None | 03/16 |
| EXP-2024-0081 | Date[pred_row 4].Label | hallucinated (misplaced) | None | 03/16 |
| EXP-2024-0081 | Date[pred_row 4].Value | hallucinated (misplaced) | None | 03/16 |
| EXP-2024-0081 | Date[pred_row 5].Label | hallucinated (misplaced) | None | 03/16 |
| EXP-2024-0081 | Date[pred_row 5].Value | hallucinated (misplaced) | None | 03/16 |
| EXP-2024-0081 | Date[pred_row 6].Label | hallucinated (misplaced) | None | 03/17 |
| EXP-2024-0081 | Date[pred_row 6].Value | hallucinated (misplaced) | None | 03/17 |
| EXP-2024-0081 | Date[pred_row 7].Label | hallucinated (misplaced) | None | 03/18 |
| EXP-2024-0081 | Date[pred_row 7].Value | hallucinated (misplaced) | None | 03/18 |
| EXP-2024-0081 | Date[pred_row 8].Label | hallucinated (misplaced) | None | 03/18 |
| EXP-2024-0081 | Date[pred_row 8].Value | hallucinated (misplaced) | None | 03/18 |
| EXP-2024-0081 | TOTAL CLAIMED:[pred_row 0].Label | hallucinated (misplaced) | None | TOTAL CLAIMED: |
| EXP-2024-0081 | TOTAL CLAIMED:[pred_row 0].Value | hallucinated (misplaced) | None | 1,727.25 |
| INV-2024-0031 | Bill To Address | missed | 500 Commerce Drive, Chicago, IL 60601 | None |
| INV-2024-0031 | Bill To Contact | missed | Mr. Robert Chen | None |
| INV-2024-0031 | Status | missed | PAID | None |
| INV-2024-0031 | NEXUS GLOBAL TRADING LLC | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| INV-2024-0031 | Steel Wire Coils Grade A 500m | hallucinated (misplaced) | None | 40 pcs $185.00 $7,400.00 |
| INV-2024-0031 | Industrial Lubricant 5L Drum | hallucinated (misplaced) | None | 25 drums $68.00 $1,700.00 |
| INV-2024-0031 | Safety Gloves Heavy Duty Box/12 | hallucinated (misplaced) | None | 60 boxes $22.50 $1,350.00 |
| INV-2024-0031 | Hex Bolt Set M10 Qty-500 | hallucinated (misplaced) | None | 30 sets $14.75 $442.50 |
| INV-2024-0031 | Wire: First National Bank of New York | hallucinated (misplaced) | None | Wire: First National Bank of New York |
| INV-2024-0031 | ABA: 021000021 Account: 7743882201 | hallucinated (misplaced) | None | ABA: 021000021 Account: 7743882201 |
| INV-2024-0031 | Cheque payable to: Nexus Global Trading LLC | hallucinated (misplaced) | None | Cheque payable to: Nexus Global Trading LLC |
| INV-2024-0031 | Payment received via wire transfer Feb 10, 2024. Ref: | hallucinated (misplaced) | None | WT-20240210-4421. |
| INV-2024-0031 | line_items[row 0].Description | missed | Steel Wire Coils Grade A 500m | None |
| INV-2024-0031 | line_items[row 0].Qty | missed | 40 | None |
| INV-2024-0031 | line_items[row 0].Unit | missed | pcs | None |
| INV-2024-0031 | line_items[row 0].Unit Price | missed | 185.0 | None |
| INV-2024-0031 | line_items[row 0].Amount | missed | 7400.0 | None |
| INV-2024-0031 | line_items[row 1].Description | missed | Industrial Lubricant 5L Drum | None |
| INV-2024-0031 | line_items[row 1].Qty | missed | 25 | None |
| INV-2024-0031 | line_items[row 1].Unit | missed | drums | None |
| INV-2024-0031 | line_items[row 1].Unit Price | missed | 68.0 | None |
| INV-2024-0031 | line_items[row 1].Amount | missed | 1700.0 | None |
| INV-2024-0031 | line_items[row 2].Description | missed | Safety Gloves Heavy Duty Box/12 | None |
| INV-2024-0031 | line_items[row 2].Qty | missed | 60 | None |
| INV-2024-0031 | line_items[row 2].Unit | missed | boxes | None |
| INV-2024-0031 | line_items[row 2].Unit Price | missed | 22.5 | None |
| INV-2024-0031 | line_items[row 2].Amount | missed | 1350.0 | None |
| INV-2024-0031 | line_items[row 3].Description | missed | Hex Bolt Set M10 Qty-500 | None |
| INV-2024-0031 | line_items[row 3].Qty | missed | 30 | None |
| INV-2024-0031 | line_items[row 3].Unit | missed | sets | None |
| INV-2024-0031 | line_items[row 3].Unit Price | missed | 14.75 | None |
| INV-2024-0031 | line_items[row 3].Amount | missed | 442.5 | None |
| INV-2024-0031 | NEXUS GLOBAL TRADING LLC[pred_row 0].Label | hallucinated (misplaced) | None | NEXUS GLOBAL TRADING LLC |
| INV-2024-0031 | NEXUS GLOBAL TRADING LLC[pred_row 0].Value | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| INV-2024-0031 | NEXUS GLOBAL TRADING LLC[pred_row 1].Label | hallucinated (misplaced) | None | (212) 555-0148 \| EIN: 47-3821654 |
| INV-2024-0031 | NEXUS GLOBAL TRADING LLC[pred_row 2].Label | hallucinated (misplaced) | None | Steel Wire Coils Grade A 500m |
| INV-2024-0031 | NEXUS GLOBAL TRADING LLC[pred_row 2].Value | hallucinated (misplaced) | None | 40 |
| INV-2024-0031 | Bill To:[pred_row 0].Label | hallucinated (misplaced) | None | Bill To: |
| INV-2024-0031 | Bill To:[pred_row 0].Value | hallucinated (misplaced) | None | Apex Industrial Supplies Inc. |
| INV-2024-0031 | Bill To:[pred_row 1].Value | hallucinated (misplaced) | None | 500 Commerce Drive, Chicago, IL 60601 |
| INV-2024-0031 | Bill To:[pred_row 2].Value | hallucinated (misplaced) | None | Mr. Robert Chen — rchen@apexindustrial.com |
| INV-2024-0031 | Invoice:[pred_row 0].Label | hallucinated (misplaced) | None | Invoice: |
| INV-2024-0031 | Invoice:[pred_row 0].Value | hallucinated (misplaced) | None | INV-2024-0031 |
| INV-2024-0031 | Invoice:[pred_row 1].Label | hallucinated (misplaced) | None | Date: |
| INV-2024-0031 | Invoice:[pred_row 1].Value | hallucinated (misplaced) | None | January 15, 2024 |
| INV-2024-0031 | Invoice:[pred_row 2].Label | hallucinated (misplaced) | None | Due: |
| INV-2024-0031 | Invoice:[pred_row 2].Value | hallucinated (misplaced) | None | February 14, 2024 |
| INV-2024-0031 | Invoice:[pred_row 3].Label | hallucinated (misplaced) | None | PO Ref: |
| INV-2024-0031 | Invoice:[pred_row 3].Value | hallucinated (misplaced) | None | PO-2024-0018 |
| INV-2024-0031 | Invoice:[pred_row 4].Label | hallucinated (misplaced) | None | Terms: |
| INV-2024-0031 | Invoice:[pred_row 4].Value | hallucinated (misplaced) | None | Net 30 |
| INV-2024-0031 | Description[pred_row 0].Label | hallucinated (misplaced) | None | Steel Wire Coils Grade A 500m |
| INV-2024-0031 | Description[pred_row 0].Value | hallucinated (misplaced) | None | 40 pcs $185.00 $7,400.00 |
| INV-2024-0031 | Description[pred_row 1].Label | hallucinated (misplaced) | None | Industrial Lubricant 5L Drum |
| INV-2024-0031 | Description[pred_row 1].Value | hallucinated (misplaced) | None | 25 drums $68.00 $1,700.00 |
| INV-2024-0031 | Description[pred_row 2].Label | hallucinated (misplaced) | None | Safety Gloves Heavy Duty Box/12 |
| INV-2024-0031 | Description[pred_row 2].Value | hallucinated (misplaced) | None | 60 boxes $22.50 $1,350.00 |
| INV-2024-0031 | Description[pred_row 3].Label | hallucinated (misplaced) | None | Hex Bolt Set M10 Qty-500 |
| INV-2024-0031 | Description[pred_row 3].Value | hallucinated (misplaced) | None | 30 sets $14.75 $442.50 |
| INV-2024-0031 | Subtotal:[pred_row 0].Label | hallucinated (misplaced) | None | Subtotal: |
| INV-2024-0031 | Subtotal:[pred_row 0].Value | hallucinated (misplaced) | None | 10,892.50 |
| INV-2024-0031 | Subtotal:[pred_row 1].Label | hallucinated (misplaced) | None | Shipping & Handling: |
| INV-2024-0031 | Subtotal:[pred_row 1].Value | hallucinated (misplaced) | None | 320.00 |
| INV-2024-0031 | Subtotal:[pred_row 2].Label | hallucinated (misplaced) | None | Sales Tax (8.88%): |
| INV-2024-0031 | Subtotal:[pred_row 2].Value | hallucinated (misplaced) | None | 966.71 |
| INV-2024-0031 | Subtotal:[pred_row 3].Label | hallucinated (misplaced) | None | TOTAL DUE: |
| INV-2024-0031 | Subtotal:[pred_row 3].Value | hallucinated (misplaced) | None | 12,179.21 |
| INV-2024-0031 | Payment Instructions[pred_row 0].Label | hallucinated (misplaced) | None | Wire: First National Bank of New York |
| INV-2024-0031 | Payment Instructions[pred_row 0].Value | hallucinated (misplaced) | None | Wire: First National Bank of New York |
| INV-2024-0031 | Payment Instructions[pred_row 1].Label | hallucinated (misplaced) | None | ABA: 021000021 Account: 7743882201 |
| INV-2024-0031 | Payment Instructions[pred_row 1].Value | hallucinated (misplaced) | None | ABA: 021000021 Account: 7743882201 |
| INV-2024-0031 | Payment Instructions[pred_row 2].Label | hallucinated (misplaced) | None | Cheque payable to: Nexus Global Trading LLC |
| INV-2024-0031 | Payment Instructions[pred_row 2].Value | hallucinated (misplaced) | None | Cheque payable to: Nexus Global Trading LLC |
| INV-2024-0031 | Notes[pred_row 0].Label | hallucinated (misplaced) | None | Payment received via wire transfer Feb 10, 2024. Ref: |
| INV-2024-0031 | Notes[pred_row 0].Value | hallucinated (misplaced) | None | WT-20240210-4421. |
| INV-2024-0047 | Bill To Company | missed | Pinnacle Electronics Corp. | None |
| INV-2024-0047 | Bill To Address | missed | 3800 Tech Boulevard Floor 5, Austin, TX 78701 | None |
| INV-2024-0047 | Bill To Contact | missed | Ms. Sarah Johnson | None |
| INV-2024-0047 | Status | missed | OUTSTANDING | None |
| INV-2024-0047 | NEXUS GLOBAL TRADING LLC | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| INV-2024-0047 | USB-C Hub 7-Port Model HB-720 | hallucinated (misplaced) | None | 150 units $34.50 $5,175.00 |
| INV-2024-0047 | Wireless Mouse M300 Series | hallucinated (misplaced) | None | 200 units $18.75 $3,750.00 |
| INV-2024-0047 | Laptop Cooling Stand Aluminium | hallucinated (misplaced) | None | 80 units $27.00 $2,160.00 |
| INV-2024-0047 | HDMI 2.1 Cable 2m Pack/5 | hallucinated (misplaced) | None | 120 packs $16.20 $1,944.00 |
| INV-2024-0047 | Webcam HD 1080p w/ Mic | hallucinated (misplaced) | None | 60 units $42.00 $2,520.00 |
| INV-2024-0047 | Balance due March 4, 2024. Late payments subject to 1.5% | hallucinated (misplaced) | None | monthly interest. |
| INV-2024-0047 | line_items[row 0].Description | missed | USB-C Hub 7-Port Model HB-720 | None |
| INV-2024-0047 | line_items[row 0].Qty | missed | 150 | None |
| INV-2024-0047 | line_items[row 0].Unit | missed | units | None |
| INV-2024-0047 | line_items[row 0].Unit Price | missed | 34.5 | None |
| INV-2024-0047 | line_items[row 0].Amount | missed | 5175.0 | None |
| INV-2024-0047 | line_items[row 1].Description | missed | Wireless Mouse M300 Series | None |
| INV-2024-0047 | line_items[row 1].Qty | missed | 200 | None |
| INV-2024-0047 | line_items[row 1].Unit | missed | units | None |
| INV-2024-0047 | line_items[row 1].Unit Price | missed | 18.75 | None |
| INV-2024-0047 | line_items[row 1].Amount | missed | 3750.0 | None |
| INV-2024-0047 | line_items[row 2].Description | missed | Laptop Cooling Stand Aluminium | None |
| INV-2024-0047 | line_items[row 2].Qty | missed | 80 | None |
| INV-2024-0047 | line_items[row 2].Unit | missed | units | None |
| INV-2024-0047 | line_items[row 2].Unit Price | missed | 27.0 | None |
| INV-2024-0047 | line_items[row 2].Amount | missed | 2160.0 | None |
| INV-2024-0047 | line_items[row 3].Description | missed | HDMI 2.1 Cable 2m Pack/5 | None |
| INV-2024-0047 | line_items[row 3].Qty | missed | 120 | None |
| INV-2024-0047 | line_items[row 3].Unit | missed | packs | None |
| INV-2024-0047 | line_items[row 3].Unit Price | missed | 16.2 | None |
| INV-2024-0047 | line_items[row 3].Amount | missed | 1944.0 | None |
| INV-2024-0047 | line_items[row 4].Description | missed | Webcam HD 1080p w/ Mic | None |
| INV-2024-0047 | line_items[row 4].Qty | missed | 60 | None |
| INV-2024-0047 | line_items[row 4].Unit | missed | units | None |
| INV-2024-0047 | line_items[row 4].Unit Price | missed | 42.0 | None |
| INV-2024-0047 | line_items[row 4].Amount | missed | 2520.0 | None |
| INV-2024-0047 | NEXUS GLOBAL TRADING LLC[pred_row 0].Label | hallucinated (misplaced) | None | NEXUS GLOBAL TRADING LLC |
| INV-2024-0047 | NEXUS GLOBAL TRADING LLC[pred_row 0].Value | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| INV-2024-0047 | NEXUS GLOBAL TRADING LLC[pred_row 1].Label | hallucinated (misplaced) | None | (212) 555-0148 \| EIN: 47-3821654 |
| INV-2024-0047 | NEXUS GLOBAL TRADING LLC[pred_row 2].Label | hallucinated (misplaced) | None | Bill To: |
| INV-2024-0047 | NEXUS GLOBAL TRADING LLC[pred_row 2].Value | hallucinated (misplaced) | None | Pinnacle Electronics Corp. |
| INV-2024-0047 | Bill To:[pred_row 0].Label | hallucinated (misplaced) | None | Bill To: |
| INV-2024-0047 | Bill To:[pred_row 1].Label | hallucinated (misplaced) | None | Pinnacle Electronics Corp. |
| INV-2024-0047 | Bill To:[pred_row 2].Label | hallucinated (misplaced) | None | 3800 Tech Boulevard Floor 5, Austin, TX 78701 |
| INV-2024-0047 | Bill To:[pred_row 3].Label | hallucinated (misplaced) | None | Ms. Sarah Johnson — sjohnson@pinnacleelec.com |
| INV-2024-0047 | Invoice:[pred_row 0].Label | hallucinated (misplaced) | None | Invoice: |
| INV-2024-0047 | Invoice:[pred_row 0].Value | hallucinated (misplaced) | None | INV-2024-0047 |
| INV-2024-0047 | Invoice:[pred_row 1].Label | hallucinated (misplaced) | None | Date: |
| INV-2024-0047 | Invoice:[pred_row 1].Value | hallucinated (misplaced) | None | February 3, 2024 |
| INV-2024-0047 | Invoice:[pred_row 2].Label | hallucinated (misplaced) | None | Due: |
| INV-2024-0047 | Invoice:[pred_row 2].Value | hallucinated (misplaced) | None | March 4, 2024 |
| INV-2024-0047 | Invoice:[pred_row 3].Label | hallucinated (misplaced) | None | PO Ref: |
| INV-2024-0047 | Invoice:[pred_row 3].Value | hallucinated (misplaced) | None | PO-2024-0029 |
| INV-2024-0047 | Invoice:[pred_row 4].Label | hallucinated (misplaced) | None | Terms: |
| INV-2024-0047 | Invoice:[pred_row 4].Value | hallucinated (misplaced) | None | Net 30 |
| INV-2024-0047 | Description[pred_row 0].Label | hallucinated (misplaced) | None | USB-C Hub 7-Port Model HB-720 |
| INV-2024-0047 | Description[pred_row 0].Value | hallucinated (misplaced) | None | 150 units $34.50 $5,175.00 |
| INV-2024-0047 | Description[pred_row 1].Label | hallucinated (misplaced) | None | Wireless Mouse M300 Series |
| INV-2024-0047 | Description[pred_row 1].Value | hallucinated (misplaced) | None | 200 units $18.75 $3,750.00 |
| INV-2024-0047 | Description[pred_row 2].Label | hallucinated (misplaced) | None | Laptop Cooling Stand Aluminium |
| INV-2024-0047 | Description[pred_row 2].Value | hallucinated (misplaced) | None | 80 units $27.00 $2,160.00 |
| INV-2024-0047 | Description[pred_row 3].Label | hallucinated (misplaced) | None | HDMI 2.1 Cable 2m Pack/5 |
| INV-2024-0047 | Description[pred_row 3].Value | hallucinated (misplaced) | None | 120 packs $16.20 $1,944.00 |
| INV-2024-0047 | Description[pred_row 4].Label | hallucinated (misplaced) | None | Webcam HD 1080p w/ Mic |
| INV-2024-0047 | Description[pred_row 4].Value | hallucinated (misplaced) | None | 60 units $42.00 $2,520.00 |
| INV-2024-0047 | Subtotal:[pred_row 0].Label | hallucinated (misplaced) | None | Subtotal: |
| INV-2024-0047 | Subtotal:[pred_row 0].Value | hallucinated (misplaced) | None | 15,549.00 |
| INV-2024-0047 | Subtotal:[pred_row 1].Label | hallucinated (misplaced) | None | Shipping & Handling: |
| INV-2024-0047 | Subtotal:[pred_row 1].Value | hallucinated (misplaced) | None | 580.00 |
| INV-2024-0047 | Subtotal:[pred_row 2].Label | hallucinated (misplaced) | None | Sales Tax (8.25%): |
| INV-2024-0047 | Subtotal:[pred_row 2].Value | hallucinated (misplaced) | None | 1,282.79 |
| INV-2024-0047 | Subtotal:[pred_row 3].Label | hallucinated (misplaced) | None | TOTAL DUE: |
| INV-2024-0047 | Subtotal:[pred_row 3].Value | hallucinated (misplaced) | None | 17,411.79 |
| INV-2024-0047 | Payment Instructions[pred_row 0].Label | hallucinated (misplaced) | None | Wire: First National Bank of New York |
| INV-2024-0047 | Payment Instructions[pred_row 1].Label | hallucinated (misplaced) | None | ABA: 021000021 Account: 7743882201 |
| INV-2024-0047 | Payment Instructions[pred_row 2].Label | hallucinated (misplaced) | None | Cheque payable to: Nexus Global Trading LLC |
| INV-2024-0047 | Notes[pred_row 0].Label | hallucinated (misplaced) | None | Balance due March 4, 2024. Late payments subject to 1.5% |
| INV-2024-0047 | Notes[pred_row 0].Value | hallucinated (misplaced) | None | monthly interest. |
| PAYSLIP-EMP-0007-APR2024 | Pay Period | wrong | April 1–30, 2024 | 2024-04-01 to 2024-04-30 |
| PAYSLIP-EMP-0007-APR2024 | earnings[row 0].Description | missed | Base Salary | None |
| PAYSLIP-EMP-0007-APR2024 | earnings[row 0].Amount | missed | 12083.33 | None |
| PAYSLIP-EMP-0007-APR2024 | earnings[row 1].Description | missed | Car Allowance | None |
| PAYSLIP-EMP-0007-APR2024 | earnings[row 1].Amount | missed | 500.0 | None |
| PAYSLIP-EMP-0007-APR2024 | earnings[row 2].Description | missed | Executive Bonus | None |
| PAYSLIP-EMP-0007-APR2024 | earnings[row 2].Amount | missed | 2000.0 | None |
| PAYSLIP-EMP-0007-APR2024 | deductions[row 0].Description | missed | Federal Income Tax | None |
| PAYSLIP-EMP-0007-APR2024 | deductions[row 0].Amount | missed | -3240.0 | None |
| PAYSLIP-EMP-0007-APR2024 | deductions[row 1].Description | missed | Social Security (6.2%) | None |
| PAYSLIP-EMP-0007-APR2024 | deductions[row 1].Amount | missed | -904.17 | None |
| PAYSLIP-EMP-0007-APR2024 | deductions[row 2].Description | missed | Medicare (1.45%) | None |
| PAYSLIP-EMP-0007-APR2024 | deductions[row 2].Amount | missed | -211.46 | None |
| PAYSLIP-EMP-0007-APR2024 | deductions[row 3].Description | missed | NY State Income Tax | None |
| PAYSLIP-EMP-0007-APR2024 | deductions[row 3].Amount | missed | -880.0 | None |
| PAYSLIP-EMP-0007-APR2024 | deductions[row 4].Description | missed | NY City Tax | None |
| PAYSLIP-EMP-0007-APR2024 | deductions[row 4].Amount | missed | -395.0 | None |
| PAYSLIP-EMP-0007-APR2024 | deductions[row 5].Description | missed | Health Insurance (Family) | None |
| PAYSLIP-EMP-0007-APR2024 | deductions[row 5].Amount | missed | -380.0 | None |
| PAYSLIP-EMP-0007-APR2024 | deductions[row 6].Description | missed | 401(k) Contribution (8%) | None |
| PAYSLIP-EMP-0007-APR2024 | deductions[row 6].Amount | missed | -966.67 | None |
| PAYSLIP-EMP-0007-APR2024 | deductions[row 7].Description | missed | Dental & Vision | None |
| PAYSLIP-EMP-0007-APR2024 | deductions[row 7].Amount | missed | -65.0 | None |
| PAYSLIP-EMP-0007-APR2024 | deductions[row 8].Description | missed | Life Insurance | None |
| PAYSLIP-EMP-0007-APR2024 | deductions[row 8].Amount | missed | -28.0 | None |
| PAYSLIP-EMP-0012-APR2024 | Pay Period | wrong | April 1–30, 2024 | 2024-04-01 - 2024-04-30 |
| PAYSLIP-EMP-0012-APR2024 | earnings[pred_row 2].Description | hallucinated (misplaced) | None | Federal Income Tax |
| PAYSLIP-EMP-0012-APR2024 | earnings[pred_row 2].Amount | hallucinated (misplaced) | None | -1245.0 |
| PAYSLIP-EMP-0012-APR2024 | earnings[pred_row 3].Description | hallucinated (misplaced) | None | Social Security (6.2%) |
| PAYSLIP-EMP-0012-APR2024 | earnings[pred_row 3].Amount | hallucinated (misplaced) | None | -515.0 |
| PAYSLIP-EMP-0012-APR2024 | earnings[pred_row 4].Description | hallucinated (misplaced) | None | Medicare (1.45%) |
| PAYSLIP-EMP-0012-APR2024 | earnings[pred_row 4].Amount | hallucinated (misplaced) | None | -120.35 |
| PAYSLIP-EMP-0012-APR2024 | earnings[pred_row 5].Description | hallucinated (misplaced) | None | NY State Income Tax |
| PAYSLIP-EMP-0012-APR2024 | earnings[pred_row 5].Amount | hallucinated (misplaced) | None | -412.0 |
| PAYSLIP-EMP-0012-APR2024 | earnings[pred_row 6].Description | hallucinated (misplaced) | None | NY City Tax |
| PAYSLIP-EMP-0012-APR2024 | earnings[pred_row 6].Amount | hallucinated (misplaced) | None | -185.0 |
| PAYSLIP-EMP-0012-APR2024 | earnings[pred_row 7].Description | hallucinated (misplaced) | None | Health Insurance (Medical) |
| PAYSLIP-EMP-0012-APR2024 | earnings[pred_row 7].Amount | hallucinated (misplaced) | None | -220.0 |
| PAYSLIP-EMP-0012-APR2024 | earnings[pred_row 8].Description | hallucinated (misplaced) | None | 401(k) Contribution (5%) |
| PAYSLIP-EMP-0012-APR2024 | earnings[pred_row 8].Amount | hallucinated (misplaced) | None | -375.0 |
| PAYSLIP-EMP-0012-APR2024 | earnings[pred_row 9].Description | hallucinated (misplaced) | None | Dental & Vision |
| PAYSLIP-EMP-0012-APR2024 | earnings[pred_row 9].Amount | hallucinated (misplaced) | None | -45.0 |
| PAYSLIP-EMP-0012-APR2024 | deductions[pred_row 0].Description | hallucinated (misplaced) | None | Base Salary |
| PAYSLIP-EMP-0012-APR2024 | deductions[pred_row 0].Amount | hallucinated (misplaced) | None | 7500.0 |
| PAYSLIP-EMP-0012-APR2024 | deductions[pred_row 1].Description | hallucinated (misplaced) | None | Performance Bonus |
| PAYSLIP-EMP-0012-APR2024 | deductions[pred_row 1].Amount | hallucinated (misplaced) | None | 800.0 |
| PAYSLIP-EMP-0012-APR2024 | table[pred_row 0].Description | hallucinated (misplaced) | None | Base Salary |
| PAYSLIP-EMP-0012-APR2024 | table[pred_row 0].Amount | hallucinated (misplaced) | None | 7500.0 |
| PAYSLIP-EMP-0012-APR2024 | table[pred_row 1].Description | hallucinated (misplaced) | None | Performance Bonus |
| PAYSLIP-EMP-0012-APR2024 | table[pred_row 1].Amount | hallucinated (misplaced) | None | 800.0 |
| PAYSLIP-EMP-0012-APR2024 | table[pred_row 2].Description | hallucinated (misplaced) | None | Federal Income Tax |
| PAYSLIP-EMP-0012-APR2024 | table[pred_row 2].Amount | hallucinated (misplaced) | None | -1245.0 |
| PAYSLIP-EMP-0012-APR2024 | table[pred_row 3].Description | hallucinated (misplaced) | None | Social Security (6.2%) |
| PAYSLIP-EMP-0012-APR2024 | table[pred_row 3].Amount | hallucinated (misplaced) | None | -515.0 |
| PAYSLIP-EMP-0012-APR2024 | table[pred_row 4].Description | hallucinated (misplaced) | None | Medicare (1.45%) |
| PAYSLIP-EMP-0012-APR2024 | table[pred_row 4].Amount | hallucinated (misplaced) | None | -120.35 |
| PAYSLIP-EMP-0012-APR2024 | table[pred_row 5].Description | hallucinated (misplaced) | None | NY State Income Tax |
| PAYSLIP-EMP-0012-APR2024 | table[pred_row 5].Amount | hallucinated (misplaced) | None | -412.0 |
| PAYSLIP-EMP-0012-APR2024 | table[pred_row 6].Description | hallucinated (misplaced) | None | NY City Tax |
| PAYSLIP-EMP-0012-APR2024 | table[pred_row 6].Amount | hallucinated (misplaced) | None | -185.0 |
| PAYSLIP-EMP-0012-APR2024 | table[pred_row 7].Description | hallucinated (misplaced) | None | Health Insurance (Medical) |
| PAYSLIP-EMP-0012-APR2024 | table[pred_row 7].Amount | hallucinated (misplaced) | None | -220.0 |
| PAYSLIP-EMP-0012-APR2024 | table[pred_row 8].Description | hallucinated (misplaced) | None | 401(k) Contribution (5%) |
| PAYSLIP-EMP-0012-APR2024 | table[pred_row 8].Amount | hallucinated (misplaced) | None | -375.0 |
| PAYSLIP-EMP-0012-APR2024 | table[pred_row 9].Description | hallucinated (misplaced) | None | Dental & Vision |
| PAYSLIP-EMP-0012-APR2024 | table[pred_row 9].Amount | hallucinated (misplaced) | None | -45.0 |
| PAYSLIP-EMP-0012-APR2024 | cbm_table[pred_row 0].Description | hallucinated (misplaced) | None | Base Salary |
| PAYSLIP-EMP-0012-APR2024 | cbm_table[pred_row 0].Amount | hallucinated (misplaced) | None | 7500.00 |
| PAYSLIP-EMP-0012-APR2024 | cbm_table[pred_row 1].Description | hallucinated (misplaced) | None | Performance Bonus |
| PAYSLIP-EMP-0012-APR2024 | cbm_table[pred_row 1].Amount | hallucinated (misplaced) | None | 800.00 |
| PAYSLIP-EMP-0012-APR2024 | cbm_table[pred_row 2].Description | hallucinated (misplaced) | None | Federal Income Tax |
| PAYSLIP-EMP-0012-APR2024 | cbm_table[pred_row 2].Amount | hallucinated (misplaced) | None | -1245.00 |
| PAYSLIP-EMP-0012-APR2024 | cbm_table[pred_row 3].Description | hallucinated (misplaced) | None | Social Security (6.2%) |
| PAYSLIP-EMP-0012-APR2024 | cbm_table[pred_row 3].Amount | hallucinated (misplaced) | None | -515.00 |
| PAYSLIP-EMP-0012-APR2024 | cbm_table[pred_row 4].Description | hallucinated (misplaced) | None | Medicare (1.45%) |
| PAYSLIP-EMP-0012-APR2024 | cbm_table[pred_row 4].Amount | hallucinated (misplaced) | None | -120.35 |
| PAYSLIP-EMP-0012-APR2024 | cbm_table[pred_row 5].Description | hallucinated (misplaced) | None | NY State Income Tax |
| PAYSLIP-EMP-0012-APR2024 | cbm_table[pred_row 5].Amount | hallucinated (misplaced) | None | -412.00 |
| PAYSLIP-EMP-0012-APR2024 | cbm_table[pred_row 6].Description | hallucinated (misplaced) | None | NY City Tax |
| PAYSLIP-EMP-0012-APR2024 | cbm_table[pred_row 6].Amount | hallucinated (misplaced) | None | -185.00 |
| PAYSLIP-EMP-0012-APR2024 | cbm_table[pred_row 7].Description | hallucinated (misplaced) | None | Health Insurance (Medical) |
| PAYSLIP-EMP-0012-APR2024 | cbm_table[pred_row 7].Amount | hallucinated (misplaced) | None | -220.00 |
| PAYSLIP-EMP-0012-APR2024 | cbm_table[pred_row 8].Description | hallucinated (misplaced) | None | 401(k) Contribution (5%) |
| PAYSLIP-EMP-0012-APR2024 | cbm_table[pred_row 8].Amount | hallucinated (misplaced) | None | -375.00 |
| PAYSLIP-EMP-0012-APR2024 | cbm_table[pred_row 9].Description | hallucinated (misplaced) | None | Dental & Vision |
| PAYSLIP-EMP-0012-APR2024 | cbm_table[pred_row 9].Amount | hallucinated (misplaced) | None | -45.00 |
| PO-2024-0018 | Vendor Contact | near | Ms. Linda Zhao | Ms. Linda Zhao \| (310) 555-0233 |
| PO-2024-0018 | table_1[pred_row 0].Item / Description | hallucinated (misplaced) | None | Steel Wire Coils Grade A 500m (SW-500A) |
| PO-2024-0018 | table_1[pred_row 0].Qty | hallucinated (misplaced) | None | 50 |
| PO-2024-0018 | table_1[pred_row 0].Unit | hallucinated (misplaced) | None | pcs |
| PO-2024-0018 | table_1[pred_row 0].Unit Cost | hallucinated (misplaced) | None | 155.0 |
| PO-2024-0018 | table_1[pred_row 0].Total | hallucinated (misplaced) | None | 7750.0 |
| PO-2024-0018 | table_1[pred_row 1].Item / Description | hallucinated (misplaced) | None | Steel Sheet 2mm 1200x2400 (SS-2MM) |
| PO-2024-0018 | table_1[pred_row 1].Qty | hallucinated (misplaced) | None | 30 |
| PO-2024-0018 | table_1[pred_row 1].Unit | hallucinated (misplaced) | None | sheets |
| PO-2024-0018 | table_1[pred_row 1].Unit Cost | hallucinated (misplaced) | None | 88.0 |
| PO-2024-0018 | table_1[pred_row 1].Total | hallucinated (misplaced) | None | 2640.0 |
| PO-2024-0018 | table_1[pred_row 2].Item / Description | hallucinated (misplaced) | None | Mild Steel Round Bar 20mm x 3m (RB-20) |
| PO-2024-0018 | table_1[pred_row 2].Qty | hallucinated (misplaced) | None | 40 |
| PO-2024-0018 | table_1[pred_row 2].Unit | hallucinated (misplaced) | None | lengths |
| PO-2024-0018 | table_1[pred_row 2].Unit Cost | hallucinated (misplaced) | None | 42.5 |
| PO-2024-0018 | table_1[pred_row 2].Total | hallucinated (misplaced) | None | 1700.0 |
| PO-2024-0018 | cbm_table[pred_row 0].Item / Description | hallucinated (misplaced) | None | Steel Wire Coils Grade A 500m (SW-500A) |
| PO-2024-0018 | cbm_table[pred_row 0].Qty | hallucinated (misplaced) | None | 50 |
| PO-2024-0018 | cbm_table[pred_row 0].Unit | hallucinated (misplaced) | None | pcs |
| PO-2024-0018 | cbm_table[pred_row 0].Unit Cost | hallucinated (misplaced) | None | 155.00 |
| PO-2024-0018 | cbm_table[pred_row 0].Total | hallucinated (misplaced) | None | 7750.00 |
| PO-2024-0018 | cbm_table[pred_row 1].Item / Description | hallucinated (misplaced) | None | Steel Sheet 2mm 1200x2400 (SS-2MM) |
| PO-2024-0018 | cbm_table[pred_row 1].Qty | hallucinated (misplaced) | None | 30 |
| PO-2024-0018 | cbm_table[pred_row 1].Unit | hallucinated (misplaced) | None | sheets |
| PO-2024-0018 | cbm_table[pred_row 1].Unit Cost | hallucinated (misplaced) | None | 88.00 |
| PO-2024-0018 | cbm_table[pred_row 1].Total | hallucinated (misplaced) | None | 2640.00 |
| PO-2024-0018 | cbm_table[pred_row 2].Item / Description | hallucinated (misplaced) | None | Mild Steel Round Bar 20mm x 3m (RB-20) |
| PO-2024-0018 | cbm_table[pred_row 2].Qty | hallucinated (misplaced) | None | 40 |
| PO-2024-0018 | cbm_table[pred_row 2].Unit | hallucinated (misplaced) | None | lengths |
| PO-2024-0018 | cbm_table[pred_row 2].Unit Cost | hallucinated (misplaced) | None | 42.50 |
| PO-2024-0018 | cbm_table[pred_row 2].Total | hallucinated (misplaced) | None | 1700.00 |
