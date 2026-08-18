# Accuracy report — 2026-08-18 01:51:30

- git: `91e15c5`  mode: **record**  repeat: 1
- config: {"USE_NEW_EXTRACTOR": "true", "PRIMARY_LLM": "gemini", "GEMINI_MODEL": "gemini-2.5-flash-lite"}

## Overall

| metric | value |
|---|---|
| **accuracy (correct / gold-valued)** | **86.5%** |
| **hallucination rate (hallucinated / extracted)** | **39.0%** |
| **└ invention rate (value found NOWHERE in the PDF)** | **1.2%** |
| └ misplacement (real content, slot gold leaves empty) | 35.7% |
| hallucinated values | 221 (invented 7, misplaced 214) |
| near misses | 13 |
| outcome counts | {"wrong": 6, "correct": 327, "missed": 32, "hallucinated": 221, "near": 13, "empty_ok": 12} |

## By document type

| document type | accuracy | halluc. rate | invented | correct | near | wrong | missed | halluc. |
|---|---|---|---|---|---|---|---|---|
| balance_sheet | 80.4% | 51.9% | 0 | 37 | 0 | 1 | 8 | 41 |
| bank_statement | 100.0% | 0.0% | 0 | 70 | 0 | 0 | 0 | 0 |
| cheque | 72.7% | 0.0% | 0 | 8 | 3 | 0 | 0 | 0 |
| expense_report | 81.5% | 45.5% | 7 | 44 | 7 | 3 | 0 | 45 |
| income_statement | 100.0% | 0.0% | 0 | 25 | 0 | 0 | 0 | 0 |
| payslip | 62.9% | 56.6% | 0 | 44 | 0 | 2 | 24 | 60 |
| purchase_order | 96.8% | 49.2% | 0 | 30 | 1 | 0 | 0 | 30 |
| sales_invoice | 97.2% | 38.8% | 0 | 69 | 2 | 0 | 0 | 45 |

## By field type

| field type | accuracy | halluc. rate | invented | correct | near | wrong | missed | halluc. |
|---|---|---|---|---|---|---|---|---|
| date | 100.0% | 0.0% | 0 | 30 | 0 | 0 | 0 | 0 |
| money | 88.2% | 8.9% | 0 | 142 | 0 | 1 | 18 | 14 |
| number | 100.0% | 0.0% | 0 | 12 | 0 | 0 | 0 | 0 |
| string | 81.7% | 56.2% | 7 | 143 | 13 | 5 | 14 | 207 |

## Per document

| document | type | accuracy | halluc. | invented | route | notes |
|---|---|---|---|---|---|---|
| BS-2024-Q1 | balance_sheet | 80.4% | 41 | 0 | BS-2024-Q1.pdf: file_type=digital_pdf pages=2 text_len=1242 |  |
| CHQ-001847 | cheque | 72.7% | 0 | 0 | CHQ-001847.pdf: file_type=digital_pdf pages=1 text_len=501 |  |
| EXP-2024-0081 | expense_report | 81.5% | 45 | 7 | EXP-2024-0081.pdf: file_type=digital_pdf pages=1 text_len=11 |  |
| INV-2024-0031 | sales_invoice | 97.0% | 20 | 0 | INV-2024-0031.pdf: file_type=digital_pdf pages=1 text_len=97 |  |
| INV-2024-0047 | sales_invoice | 97.4% | 25 | 0 | INV-2024-0047.pdf: file_type=digital_pdf pages=1 text_len=10 |  |
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
| EXP-2024-0081 | Period | wrong | March 15–22, 2024 | 2024-03-15 to 2024-03-22 |
| EXP-2024-0081 | expenses[row 0].Category | near | Travel | Travel - Air |
| EXP-2024-0081 | expenses[row 1].Category | near | Travel | Travel - Ground |
| EXP-2024-0081 | expenses[row 2].Category | wrong | Lodging | Accommodation |
| EXP-2024-0081 | expenses[row 3].Category | near | Meals | Meals - Per Diem |
| EXP-2024-0081 | expenses[row 4].Category | wrong | Meals & Entmt | Meals & Entertainment |
| EXP-2024-0081 | expenses[row 5].Category | near | Travel | Travel - Ground |
| EXP-2024-0081 | expenses[row 6].Category | near | Meals | Meals - Per Diem |
| EXP-2024-0081 | expenses[row 7].Category | near | Travel | Travel - Ground |
| EXP-2024-0081 | expenses[row 8].Category | near | Travel | Travel - Parking |
| EXP-2024-0081 | table_1[pred_row 0].Date | hallucinated (misplaced) | None | 2024-03-15 |
| EXP-2024-0081 | table_1[pred_row 0].Type | hallucinated (misplaced) | None | Airfare |
| EXP-2024-0081 | table_1[pred_row 0].Description | hallucinated (misplaced) | None | Delta Airlines JFK–LAX round trip |
| EXP-2024-0081 | table_1[pred_row 0].Category | hallucinated (misplaced) | None | Travel - Air |
| EXP-2024-0081 | table_1[pred_row 0].Amount | hallucinated (misplaced) | None | 842.0 |
| EXP-2024-0081 | table_1[pred_row 1].Date | hallucinated (misplaced) | None | 2024-03-15 |
| EXP-2024-0081 | table_1[pred_row 1].Type | hallucinated (misplaced) | None | Taxi |
| EXP-2024-0081 | table_1[pred_row 1].Description | hallucinated (misplaced) | None | Airport to hotel LAX |
| EXP-2024-0081 | table_1[pred_row 1].Category | INVENTED | None | Travel - Ground |
| EXP-2024-0081 | table_1[pred_row 1].Amount | hallucinated (misplaced) | None | 38.5 |
| EXP-2024-0081 | table_1[pred_row 2].Date | hallucinated (misplaced) | None | 2024-03-15 |
| EXP-2024-0081 | table_1[pred_row 2].Type | hallucinated (misplaced) | None | Hotel |
| EXP-2024-0081 | table_1[pred_row 2].Description | hallucinated (misplaced) | None | Hilton LAX — 2 nights |
| EXP-2024-0081 | table_1[pred_row 2].Category | INVENTED | None | Accommodation |
| EXP-2024-0081 | table_1[pred_row 2].Amount | hallucinated (misplaced) | None | 389.0 |
| EXP-2024-0081 | table_1[pred_row 3].Date | hallucinated (misplaced) | None | 2024-03-16 |
| EXP-2024-0081 | table_1[pred_row 3].Type | hallucinated (misplaced) | None | Meals |
| EXP-2024-0081 | table_1[pred_row 3].Description | hallucinated (misplaced) | None | Hotel breakfast |
| EXP-2024-0081 | table_1[pred_row 3].Category | INVENTED | None | Meals - Per Diem |
| EXP-2024-0081 | table_1[pred_row 3].Amount | hallucinated (misplaced) | None | 24.75 |
| EXP-2024-0081 | table_1[pred_row 4].Date | hallucinated (misplaced) | None | 2024-03-16 |
| EXP-2024-0081 | table_1[pred_row 4].Type | hallucinated (misplaced) | None | M&E; |
| EXP-2024-0081 | table_1[pred_row 4].Description | hallucinated (misplaced) | None | Client lunch w/ Pacific Steel (4 pax) |
| EXP-2024-0081 | table_1[pred_row 4].Category | INVENTED | None | Meals & Entertainment |
| EXP-2024-0081 | table_1[pred_row 4].Amount | hallucinated (misplaced) | None | 187.4 |
| EXP-2024-0081 | table_1[pred_row 5].Date | hallucinated (misplaced) | None | 2024-03-16 |
| EXP-2024-0081 | table_1[pred_row 5].Type | hallucinated (misplaced) | None | Taxi |
| EXP-2024-0081 | table_1[pred_row 5].Description | hallucinated (misplaced) | None | Hotel to Pacific Steel facility |
| EXP-2024-0081 | table_1[pred_row 5].Category | INVENTED | None | Travel - Ground |
| EXP-2024-0081 | table_1[pred_row 5].Amount | hallucinated (misplaced) | None | 22.0 |
| EXP-2024-0081 | table_1[pred_row 6].Date | hallucinated (misplaced) | None | 2024-03-17 |
| EXP-2024-0081 | table_1[pred_row 6].Type | hallucinated (misplaced) | None | Meals |
| EXP-2024-0081 | table_1[pred_row 6].Description | hallucinated (misplaced) | None | Team dinner (2 pax) |
| EXP-2024-0081 | table_1[pred_row 6].Category | INVENTED | None | Meals - Per Diem |
| EXP-2024-0081 | table_1[pred_row 6].Amount | hallucinated (misplaced) | None | 95.6 |
| EXP-2024-0081 | table_1[pred_row 7].Date | hallucinated (misplaced) | None | 2024-03-18 |
| EXP-2024-0081 | table_1[pred_row 7].Type | hallucinated (misplaced) | None | Taxi |
| EXP-2024-0081 | table_1[pred_row 7].Description | hallucinated (misplaced) | None | Hotel to LAX |
| EXP-2024-0081 | table_1[pred_row 7].Category | INVENTED | None | Travel - Ground |
| EXP-2024-0081 | table_1[pred_row 7].Amount | hallucinated (misplaced) | None | 41.0 |
| EXP-2024-0081 | table_1[pred_row 8].Date | hallucinated (misplaced) | None | 2024-03-18 |
| EXP-2024-0081 | table_1[pred_row 8].Type | hallucinated (misplaced) | None | Parking |
| EXP-2024-0081 | table_1[pred_row 8].Description | hallucinated (misplaced) | None | JFK long-term parking 3 days |
| EXP-2024-0081 | table_1[pred_row 8].Category | hallucinated (misplaced) | None | Travel - Parking |
| EXP-2024-0081 | table_1[pred_row 8].Amount | hallucinated (misplaced) | None | 87.0 |
| INV-2024-0031 | Bill To Contact | near | Mr. Robert Chen | Mr. Robert Chen — rchen@apexindustrial.com |
| INV-2024-0031 | table_1[pred_row 0].Description | hallucinated (misplaced) | None | Steel Wire Coils Grade A 500m |
| INV-2024-0031 | table_1[pred_row 0].Qty | hallucinated (misplaced) | None | 40 |
| INV-2024-0031 | table_1[pred_row 0].Unit | hallucinated (misplaced) | None | pcs |
| INV-2024-0031 | table_1[pred_row 0].Unit Price | hallucinated (misplaced) | None | 185.0 |
| INV-2024-0031 | table_1[pred_row 0].Amount | hallucinated (misplaced) | None | 7400.0 |
| INV-2024-0031 | table_1[pred_row 1].Description | hallucinated (misplaced) | None | Industrial Lubricant 5L Drum |
| INV-2024-0031 | table_1[pred_row 1].Qty | hallucinated (misplaced) | None | 25 |
| INV-2024-0031 | table_1[pred_row 1].Unit | hallucinated (misplaced) | None | drums |
| INV-2024-0031 | table_1[pred_row 1].Unit Price | hallucinated (misplaced) | None | 68.0 |
| INV-2024-0031 | table_1[pred_row 1].Amount | hallucinated (misplaced) | None | 1700.0 |
| INV-2024-0031 | table_1[pred_row 2].Description | hallucinated (misplaced) | None | Safety Gloves Heavy Duty Box/12 |
| INV-2024-0031 | table_1[pred_row 2].Qty | hallucinated (misplaced) | None | 60 |
| INV-2024-0031 | table_1[pred_row 2].Unit | hallucinated (misplaced) | None | boxes |
| INV-2024-0031 | table_1[pred_row 2].Unit Price | hallucinated (misplaced) | None | 22.5 |
| INV-2024-0031 | table_1[pred_row 2].Amount | hallucinated (misplaced) | None | 1350.0 |
| INV-2024-0031 | table_1[pred_row 3].Description | hallucinated (misplaced) | None | Hex Bolt Set M10 Qty-500 |
| INV-2024-0031 | table_1[pred_row 3].Qty | hallucinated (misplaced) | None | 30 |
| INV-2024-0031 | table_1[pred_row 3].Unit | hallucinated (misplaced) | None | sets |
| INV-2024-0031 | table_1[pred_row 3].Unit Price | hallucinated (misplaced) | None | 14.75 |
| INV-2024-0031 | table_1[pred_row 3].Amount | hallucinated (misplaced) | None | 442.5 |
| INV-2024-0047 | Bill To Contact | near | Ms. Sarah Johnson | Ms. Sarah Johnson — sjohnson@pinnacleelec.com |
| INV-2024-0047 | table_1[pred_row 0].Description | hallucinated (misplaced) | None | USB-C Hub 7-Port Model HB-720 |
| INV-2024-0047 | table_1[pred_row 0].Qty | hallucinated (misplaced) | None | 150 |
| INV-2024-0047 | table_1[pred_row 0].Unit | hallucinated (misplaced) | None | units |
| INV-2024-0047 | table_1[pred_row 0].Unit Price | hallucinated (misplaced) | None | 34.5 |
| INV-2024-0047 | table_1[pred_row 0].Amount | hallucinated (misplaced) | None | 5175.0 |
| INV-2024-0047 | table_1[pred_row 1].Description | hallucinated (misplaced) | None | Wireless Mouse M300 Series |
| INV-2024-0047 | table_1[pred_row 1].Qty | hallucinated (misplaced) | None | 200 |
| INV-2024-0047 | table_1[pred_row 1].Unit | hallucinated (misplaced) | None | units |
| INV-2024-0047 | table_1[pred_row 1].Unit Price | hallucinated (misplaced) | None | 18.75 |
| INV-2024-0047 | table_1[pred_row 1].Amount | hallucinated (misplaced) | None | 3750.0 |
| INV-2024-0047 | table_1[pred_row 2].Description | hallucinated (misplaced) | None | Laptop Cooling Stand Aluminium |
| INV-2024-0047 | table_1[pred_row 2].Qty | hallucinated (misplaced) | None | 80 |
| INV-2024-0047 | table_1[pred_row 2].Unit | hallucinated (misplaced) | None | units |
| INV-2024-0047 | table_1[pred_row 2].Unit Price | hallucinated (misplaced) | None | 27.0 |
| INV-2024-0047 | table_1[pred_row 2].Amount | hallucinated (misplaced) | None | 2160.0 |
| INV-2024-0047 | table_1[pred_row 3].Description | hallucinated (misplaced) | None | HDMI 2.1 Cable 2m Pack/5 |
| INV-2024-0047 | table_1[pred_row 3].Qty | hallucinated (misplaced) | None | 120 |
| INV-2024-0047 | table_1[pred_row 3].Unit | hallucinated (misplaced) | None | packs |
| INV-2024-0047 | table_1[pred_row 3].Unit Price | hallucinated (misplaced) | None | 16.2 |
| INV-2024-0047 | table_1[pred_row 3].Amount | hallucinated (misplaced) | None | 1944.0 |
| INV-2024-0047 | table_1[pred_row 4].Description | hallucinated (misplaced) | None | Webcam HD 1080p w/ Mic |
| INV-2024-0047 | table_1[pred_row 4].Qty | hallucinated (misplaced) | None | 60 |
| INV-2024-0047 | table_1[pred_row 4].Unit | hallucinated (misplaced) | None | units |
| INV-2024-0047 | table_1[pred_row 4].Unit Price | hallucinated (misplaced) | None | 42.0 |
| INV-2024-0047 | table_1[pred_row 4].Amount | hallucinated (misplaced) | None | 2520.0 |
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

## Changes vs previous run

- EXP-2024-0081 :: Department: missed -> correct
- EXP-2024-0081 :: Employee ID: missed -> correct
- EXP-2024-0081 :: Employee Name: missed -> correct
- EXP-2024-0081 :: Manager: missed -> correct
- EXP-2024-0081 :: Period: missed -> wrong
- EXP-2024-0081 :: Purpose: missed -> correct
- EXP-2024-0081 :: Report No: missed -> correct
- EXP-2024-0081 :: Status: missed -> correct
- EXP-2024-0081 :: Total Claimed: missed -> correct
- EXP-2024-0081 :: expenses :: row_count_mismatch: -9 -> 0
- EXP-2024-0081 :: expenses[row 0].Amount: missed -> correct
- EXP-2024-0081 :: expenses[row 0].Category: missed -> near
- EXP-2024-0081 :: expenses[row 0].Date: missed -> correct
- EXP-2024-0081 :: expenses[row 0].Description: missed -> correct
- EXP-2024-0081 :: expenses[row 0].Type: missed -> correct
- EXP-2024-0081 :: expenses[row 1].Amount: missed -> correct
- EXP-2024-0081 :: expenses[row 1].Category: missed -> near
- EXP-2024-0081 :: expenses[row 1].Date: missed -> correct
- EXP-2024-0081 :: expenses[row 1].Description: missed -> correct
- EXP-2024-0081 :: expenses[row 1].Type: missed -> correct
- EXP-2024-0081 :: expenses[row 2].Amount: missed -> correct
- EXP-2024-0081 :: expenses[row 2].Category: missed -> wrong
- EXP-2024-0081 :: expenses[row 2].Date: missed -> correct
- EXP-2024-0081 :: expenses[row 2].Description: missed -> correct
- EXP-2024-0081 :: expenses[row 2].Type: missed -> correct
- EXP-2024-0081 :: expenses[row 3].Amount: missed -> correct
- EXP-2024-0081 :: expenses[row 3].Category: missed -> near
- EXP-2024-0081 :: expenses[row 3].Date: missed -> correct
- EXP-2024-0081 :: expenses[row 3].Description: missed -> correct
- EXP-2024-0081 :: expenses[row 3].Type: missed -> correct
- EXP-2024-0081 :: expenses[row 4].Amount: missed -> correct
- EXP-2024-0081 :: expenses[row 4].Category: missed -> wrong
- EXP-2024-0081 :: expenses[row 4].Date: missed -> correct
- EXP-2024-0081 :: expenses[row 4].Description: missed -> correct
- EXP-2024-0081 :: expenses[row 4].Type: missed -> correct
- EXP-2024-0081 :: expenses[row 5].Amount: missed -> correct
- EXP-2024-0081 :: expenses[row 5].Category: missed -> near
- EXP-2024-0081 :: expenses[row 5].Date: missed -> correct
- EXP-2024-0081 :: expenses[row 5].Description: missed -> correct
- EXP-2024-0081 :: expenses[row 5].Type: missed -> correct
- EXP-2024-0081 :: expenses[row 6].Amount: missed -> correct
- EXP-2024-0081 :: expenses[row 6].Category: missed -> near
- EXP-2024-0081 :: expenses[row 6].Date: missed -> correct
- EXP-2024-0081 :: expenses[row 6].Description: missed -> correct
- EXP-2024-0081 :: expenses[row 6].Type: missed -> correct
- EXP-2024-0081 :: expenses[row 7].Amount: missed -> correct
- EXP-2024-0081 :: expenses[row 7].Category: missed -> near
- EXP-2024-0081 :: expenses[row 7].Date: missed -> correct
- EXP-2024-0081 :: expenses[row 7].Description: missed -> correct
- EXP-2024-0081 :: expenses[row 7].Type: missed -> correct
- EXP-2024-0081 :: expenses[row 8].Amount: missed -> correct
- EXP-2024-0081 :: expenses[row 8].Category: missed -> near
- EXP-2024-0081 :: expenses[row 8].Date: missed -> correct
- EXP-2024-0081 :: expenses[row 8].Description: missed -> correct
- EXP-2024-0081 :: expenses[row 8].Type: missed -> correct
- EXP-2024-0081 :: table_1 :: row_count_mismatch: None -> 9
- EXP-2024-0081 :: table_1[pred_row 0].Amount: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 0].Category: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 0].Date: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 0].Description: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 0].Type: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 1].Amount: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 1].Category: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 1].Date: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 1].Description: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 1].Type: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 2].Amount: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 2].Category: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 2].Date: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 2].Description: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 2].Type: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 3].Amount: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 3].Category: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 3].Date: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 3].Description: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 3].Type: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 4].Amount: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 4].Category: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 4].Date: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 4].Description: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 4].Type: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 5].Amount: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 5].Category: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 5].Date: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 5].Description: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 5].Type: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 6].Amount: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 6].Category: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 6].Date: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 6].Description: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 6].Type: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 7].Amount: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 7].Category: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 7].Date: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 7].Description: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 7].Type: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 8].Amount: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 8].Category: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 8].Date: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 8].Description: None -> hallucinated
- EXP-2024-0081 :: table_1[pred_row 8].Type: None -> hallucinated
- INV-2024-0031 :: Bill To Address: missed -> correct
- INV-2024-0031 :: Bill To Company: missed -> correct
- INV-2024-0031 :: Bill To Contact: missed -> near
- INV-2024-0031 :: Due Date: missed -> correct
- INV-2024-0031 :: Invoice Date: missed -> correct
- INV-2024-0031 :: Invoice Number: missed -> correct
- INV-2024-0031 :: PO Reference: missed -> correct
- INV-2024-0031 :: Payment Terms: missed -> correct
- INV-2024-0031 :: Sales Tax: missed -> correct
- INV-2024-0031 :: Shipping & Handling: missed -> correct
- INV-2024-0031 :: Status: missed -> correct
- INV-2024-0031 :: Subtotal: missed -> correct
- INV-2024-0031 :: Total Due: missed -> correct
- INV-2024-0031 :: line_items :: row_count_mismatch: -4 -> 0
- INV-2024-0031 :: line_items[row 0].Amount: missed -> correct
- INV-2024-0031 :: line_items[row 0].Description: missed -> correct
- INV-2024-0031 :: line_items[row 0].Qty: missed -> correct
- INV-2024-0031 :: line_items[row 0].Unit: missed -> correct
- INV-2024-0031 :: line_items[row 0].Unit Price: missed -> correct
- INV-2024-0031 :: line_items[row 1].Amount: missed -> correct
- INV-2024-0031 :: line_items[row 1].Description: missed -> correct
- INV-2024-0031 :: line_items[row 1].Qty: missed -> correct
- INV-2024-0031 :: line_items[row 1].Unit: missed -> correct
- INV-2024-0031 :: line_items[row 1].Unit Price: missed -> correct
- INV-2024-0031 :: line_items[row 2].Amount: missed -> correct
- INV-2024-0031 :: line_items[row 2].Description: missed -> correct
- INV-2024-0031 :: line_items[row 2].Qty: missed -> correct
- INV-2024-0031 :: line_items[row 2].Unit: missed -> correct
- INV-2024-0031 :: line_items[row 2].Unit Price: missed -> correct
- INV-2024-0031 :: line_items[row 3].Amount: missed -> correct
- INV-2024-0031 :: line_items[row 3].Description: missed -> correct
- INV-2024-0031 :: line_items[row 3].Qty: missed -> correct
- INV-2024-0031 :: line_items[row 3].Unit: missed -> correct
- INV-2024-0031 :: line_items[row 3].Unit Price: missed -> correct
- INV-2024-0031 :: table_1 :: row_count_mismatch: None -> 4
- INV-2024-0031 :: table_1[pred_row 0].Amount: None -> hallucinated
- INV-2024-0031 :: table_1[pred_row 0].Description: None -> hallucinated
- INV-2024-0031 :: table_1[pred_row 0].Qty: None -> hallucinated
- INV-2024-0031 :: table_1[pred_row 0].Unit: None -> hallucinated
- INV-2024-0031 :: table_1[pred_row 0].Unit Price: None -> hallucinated
- INV-2024-0031 :: table_1[pred_row 1].Amount: None -> hallucinated
- INV-2024-0031 :: table_1[pred_row 1].Description: None -> hallucinated
- INV-2024-0031 :: table_1[pred_row 1].Qty: None -> hallucinated
- INV-2024-0031 :: table_1[pred_row 1].Unit: None -> hallucinated
- INV-2024-0031 :: table_1[pred_row 1].Unit Price: None -> hallucinated
- INV-2024-0031 :: table_1[pred_row 2].Amount: None -> hallucinated
- INV-2024-0031 :: table_1[pred_row 2].Description: None -> hallucinated
- INV-2024-0031 :: table_1[pred_row 2].Qty: None -> hallucinated
- INV-2024-0031 :: table_1[pred_row 2].Unit: None -> hallucinated
- INV-2024-0031 :: table_1[pred_row 2].Unit Price: None -> hallucinated
- INV-2024-0031 :: table_1[pred_row 3].Amount: None -> hallucinated
- INV-2024-0031 :: table_1[pred_row 3].Description: None -> hallucinated
- INV-2024-0031 :: table_1[pred_row 3].Qty: None -> hallucinated
- INV-2024-0031 :: table_1[pred_row 3].Unit: None -> hallucinated
- INV-2024-0031 :: table_1[pred_row 3].Unit Price: None -> hallucinated
- INV-2024-0047 :: Bill To Address: missed -> correct
- INV-2024-0047 :: Bill To Company: missed -> correct
- INV-2024-0047 :: Bill To Contact: missed -> near
- INV-2024-0047 :: Due Date: missed -> correct
- INV-2024-0047 :: Invoice Date: missed -> correct
- INV-2024-0047 :: Invoice Number: missed -> correct
- INV-2024-0047 :: PO Reference: missed -> correct
- INV-2024-0047 :: Payment Terms: missed -> correct
- INV-2024-0047 :: Sales Tax: missed -> correct
- INV-2024-0047 :: Shipping & Handling: missed -> correct
- INV-2024-0047 :: Status: missed -> correct
- INV-2024-0047 :: Subtotal: missed -> correct
- INV-2024-0047 :: Total Due: missed -> correct
- INV-2024-0047 :: line_items :: row_count_mismatch: -5 -> 0
- INV-2024-0047 :: line_items[row 0].Amount: missed -> correct
- INV-2024-0047 :: line_items[row 0].Description: missed -> correct
- INV-2024-0047 :: line_items[row 0].Qty: missed -> correct
- INV-2024-0047 :: line_items[row 0].Unit: missed -> correct
- INV-2024-0047 :: line_items[row 0].Unit Price: missed -> correct
- INV-2024-0047 :: line_items[row 1].Amount: missed -> correct
- INV-2024-0047 :: line_items[row 1].Description: missed -> correct
- INV-2024-0047 :: line_items[row 1].Qty: missed -> correct
- INV-2024-0047 :: line_items[row 1].Unit: missed -> correct
- INV-2024-0047 :: line_items[row 1].Unit Price: missed -> correct
- INV-2024-0047 :: line_items[row 2].Amount: missed -> correct
- INV-2024-0047 :: line_items[row 2].Description: missed -> correct
- INV-2024-0047 :: line_items[row 2].Qty: missed -> correct
- INV-2024-0047 :: line_items[row 2].Unit: missed -> correct
- INV-2024-0047 :: line_items[row 2].Unit Price: missed -> correct
- INV-2024-0047 :: line_items[row 3].Amount: missed -> correct
- INV-2024-0047 :: line_items[row 3].Description: missed -> correct
- INV-2024-0047 :: line_items[row 3].Qty: missed -> correct
- INV-2024-0047 :: line_items[row 3].Unit: missed -> correct
- INV-2024-0047 :: line_items[row 3].Unit Price: missed -> correct
- INV-2024-0047 :: line_items[row 4].Amount: missed -> correct
- INV-2024-0047 :: line_items[row 4].Description: missed -> correct
- INV-2024-0047 :: line_items[row 4].Qty: missed -> correct
- INV-2024-0047 :: line_items[row 4].Unit: missed -> correct
- INV-2024-0047 :: line_items[row 4].Unit Price: missed -> correct
- INV-2024-0047 :: table_1 :: row_count_mismatch: None -> 5
- INV-2024-0047 :: table_1[pred_row 0].Amount: None -> hallucinated
- INV-2024-0047 :: table_1[pred_row 0].Description: None -> hallucinated
- INV-2024-0047 :: table_1[pred_row 0].Qty: None -> hallucinated
- INV-2024-0047 :: table_1[pred_row 0].Unit: None -> hallucinated
- INV-2024-0047 :: table_1[pred_row 0].Unit Price: None -> hallucinated
- INV-2024-0047 :: table_1[pred_row 1].Amount: None -> hallucinated
- INV-2024-0047 :: table_1[pred_row 1].Description: None -> hallucinated
- INV-2024-0047 :: table_1[pred_row 1].Qty: None -> hallucinated
- INV-2024-0047 :: table_1[pred_row 1].Unit: None -> hallucinated
- INV-2024-0047 :: table_1[pred_row 1].Unit Price: None -> hallucinated
- INV-2024-0047 :: table_1[pred_row 2].Amount: None -> hallucinated
- INV-2024-0047 :: table_1[pred_row 2].Description: None -> hallucinated
- INV-2024-0047 :: table_1[pred_row 2].Qty: None -> hallucinated
- INV-2024-0047 :: table_1[pred_row 2].Unit: None -> hallucinated
- INV-2024-0047 :: table_1[pred_row 2].Unit Price: None -> hallucinated
- INV-2024-0047 :: table_1[pred_row 3].Amount: None -> hallucinated
- INV-2024-0047 :: table_1[pred_row 3].Description: None -> hallucinated
- INV-2024-0047 :: table_1[pred_row 3].Qty: None -> hallucinated
- INV-2024-0047 :: table_1[pred_row 3].Unit: None -> hallucinated
- INV-2024-0047 :: table_1[pred_row 3].Unit Price: None -> hallucinated
- INV-2024-0047 :: table_1[pred_row 4].Amount: None -> hallucinated
- INV-2024-0047 :: table_1[pred_row 4].Description: None -> hallucinated
- INV-2024-0047 :: table_1[pred_row 4].Qty: None -> hallucinated
- INV-2024-0047 :: table_1[pred_row 4].Unit: None -> hallucinated
- INV-2024-0047 :: table_1[pred_row 4].Unit Price: None -> hallucinated
