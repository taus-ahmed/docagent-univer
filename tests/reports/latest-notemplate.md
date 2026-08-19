# Accuracy report — 2026-08-18 17:11:41

- git: `6430bdc`  mode: **replay**  repeat: 1
- config: {"PRIMARY_LLM": "gemini", "GEMINI_MODEL": "gemini-2.5-flash-lite"}

## Overall

| metric | value |
|---|---|
| **accuracy (correct / gold-valued)** | **86.5%** |
| **accuracy RAW (all adapter widenings off)** | **78.0%** |
| **hallucination rate (hallucinated / extracted)** | **22.2%** |
| **└ invention rate (value found NOWHERE in the PDF)** | **0.0%** |
| └ misplacement (real content, slot gold leaves empty) | 19.9% |
| hallucinated values | 94 (invented 0, misplaced 94) |
| near misses | 1 |
| outcome counts | {"wrong": 1, "correct": 327, "hallucinated": 94, "missed": 49, "near": 1, "empty_ok": 12} |

## By document type

| document type | accuracy | halluc. rate | invented | correct | near | wrong | missed | halluc. |
|---|---|---|---|---|---|---|---|---|
| balance_sheet | 15.2% | 75.8% | 0 | 7 | 0 | 1 | 38 | 25 |
| bank_statement | 100.0% | 5.4% | 0 | 70 | 0 | 0 | 0 | 4 |
| cheque | 63.6% | 58.8% | 0 | 7 | 0 | 0 | 4 | 10 |
| expense_report | 98.1% | 8.6% | 0 | 53 | 0 | 0 | 1 | 5 |
| income_statement | 100.0% | 21.9% | 0 | 25 | 0 | 0 | 0 | 7 |
| payslip | 91.4% | 15.8% | 0 | 64 | 0 | 0 | 6 | 12 |
| purchase_order | 96.8% | 24.4% | 0 | 30 | 1 | 0 | 0 | 10 |
| sales_invoice | 100.0% | 22.8% | 0 | 71 | 0 | 0 | 0 | 21 |

## By field type

| field type | accuracy | halluc. rate | invented | correct | near | wrong | missed | halluc. |
|---|---|---|---|---|---|---|---|---|
| date | 100.0% | 0.0% | 0 | 30 | 0 | 0 | 0 | 0 |
| money | 86.3% | 1.4% | 0 | 139 | 0 | 1 | 21 | 2 |
| number | 100.0% | 0.0% | 0 | 12 | 0 | 0 | 0 | 0 |
| string | 83.4% | 38.5% | 0 | 146 | 1 | 0 | 28 | 92 |

## Per document

| document | type | accuracy | raw | halluc. | invented | route | notes |
|---|---|---|---|---|---|---|---|
| BS-2024-Q1 | balance_sheet | 15.2% | 17.4% | 25 | 0 | BS-2024-Q1.pdf: file_type=digital_pdf pages=2 text_len=1242 |  |
| CHQ-001847 | cheque | 63.6% | 45.5% | 10 | 0 | CHQ-001847.pdf: file_type=digital_pdf pages=1 text_len=501 |  |
| EXP-2024-0081 | expense_report | 98.1% | 98.1% | 5 | 0 | EXP-2024-0081.pdf: file_type=digital_pdf pages=1 text_len=11 |  |
| INV-2024-0031 | sales_invoice | 100.0% | 84.8% | 10 | 0 | INV-2024-0031.pdf: file_type=digital_pdf pages=1 text_len=97 |  |
| INV-2024-0047 | sales_invoice | 100.0% | 97.4% | 11 | 0 | INV-2024-0047.pdf: file_type=digital_pdf pages=1 text_len=10 |  |
| IS-2024-Q4 | income_statement | 100.0% | 88.0% | 7 | 0 | IS-2024-Q4.pdf: file_type=digital_pdf pages=2 text_len=970 |  |
| PAYSLIP-EMP-0007-APR2024 | payslip | 94.6% | 86.5% | 4 | 0 | PAYSLIP-EMP-0007-APR2024.pdf: file_type=digital_pdf pages=2  |  |
| PAYSLIP-EMP-0012-APR2024 | payslip | 87.9% | 87.9% | 8 | 0 | PAYSLIP-EMP-0012-APR2024.pdf: file_type=digital_pdf pages=2  |  |
| PO-2024-0018 | purchase_order | 96.8% | 45.2% | 10 | 0 | PO-2024-0018.pdf: file_type=digital_pdf pages=1 text_len=104 |  |
| STMT-2024-01 | bank_statement | 100.0% | 95.7% | 4 | 0 | STMT-2024-01.pdf: file_type=digital_pdf pages=1 text_len=140 |  |

## Mismatches (everything not correct)

| document | field | outcome | expected | actual |
|---|---|---|---|---|
| BS-2024-Q1 | Total Current Assets | wrong | 1129003 | $8,800 |
| BS-2024-Q1 | Company Name | hallucinated (misplaced) | None | Nexus Global Trading LLC |
| BS-2024-Q1 | Company Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| BS-2024-Q1 | Company City, State, Zip | hallucinated (misplaced) | None | New York, NY 10019 |
| BS-2024-Q1 | Company EIN | hallucinated (misplaced) | None | 47-3821654 |
| BS-2024-Q1 | As of Date | hallucinated (misplaced) | None | March 31, 2024 |
| BS-2024-Q1 | Document Number | hallucinated (misplaced) | None | BS-2024-Q1 |
| BS-2024-Q1 | Cash & Cash Equivalents | hallucinated (misplaced) | None | $143,803 |
| BS-2024-Q1 | Accounts Receivable (net) | hallucinated (misplaced) | None | $348,200 |
| BS-2024-Q1 | Inventory | hallucinated (misplaced) | None | $612,000 |
| BS-2024-Q1 | Prepaid Expenses | hallucinated (misplaced) | None | $16,200 |
| BS-2024-Q1 | Property & Equipment (gross) | hallucinated (misplaced) | None | $240,000 |
| BS-2024-Q1 | Less: Accum. Depreciation | hallucinated (misplaced) | None | $108,500 |
| BS-2024-Q1 | Security Deposits | hallucinated (misplaced) | None | $85,000 |
| BS-2024-Q1 | Intangibles (net) | hallucinated (misplaced) | None | $20,000 |
| BS-2024-Q1 | Accounts Payable | hallucinated (misplaced) | None | $254,800 |
| BS-2024-Q1 | Accrued Liabilities | hallucinated (misplaced) | None | $44,200 |
| BS-2024-Q1 | Short-term Loan — First National Bank | hallucinated (misplaced) | None | $80,000 |
| BS-2024-Q1 | Deferred Revenue | hallucinated (misplaced) | None | $18,200 |
| BS-2024-Q1 | Current Portion of Long-term Debt | hallucinated (misplaced) | None | $24,000 |
| BS-2024-Q1 | Long-term Loan — First National Bank | hallucinated (misplaced) | None | $121,000 |
| BS-2024-Q1 | Deferred Tax Liability | hallucinated (misplaced) | None | $8,400 |
| BS-2024-Q1 | Common Stock (100 shares @ $1,000 par) | hallucinated (misplaced) | None | $100,000 |
| BS-2024-Q1 | Retained Earnings | hallucinated (misplaced) | None | $550,751 |
| BS-2024-Q1 | Net Income YTD Q1 | hallucinated (misplaced) | None | $47,353 |
| BS-2024-Q1 | Prepared by | hallucinated (misplaced) | None | Meridian & Associates CPA |
| BS-2024-Q1 | current_assets[row 0].Label | missed | Cash & Cash Equivalents | None |
| BS-2024-Q1 | current_assets[row 0].Amount | missed | 143803 | None |
| BS-2024-Q1 | current_assets[row 1].Label | missed | Accounts Receivable (net) | None |
| BS-2024-Q1 | current_assets[row 1].Amount | missed | 348200 | None |
| BS-2024-Q1 | current_assets[row 2].Label | missed | Inventory | None |
| BS-2024-Q1 | current_assets[row 2].Amount | missed | 612000 | None |
| BS-2024-Q1 | current_assets[row 3].Label | missed | Prepaid Expenses | None |
| BS-2024-Q1 | current_assets[row 3].Amount | missed | 16200 | None |
| BS-2024-Q1 | current_assets[row 4].Label | missed | Other Current Assets | None |
| BS-2024-Q1 | current_assets[row 4].Amount | missed | 8800 | None |
| BS-2024-Q1 | non_current_assets[row 0].Label | missed | Property & Equipment (gross) | None |
| BS-2024-Q1 | non_current_assets[row 0].Amount | missed | 240000 | None |
| BS-2024-Q1 | non_current_assets[row 1].Label | missed | Less: Accum. Depreciation | None |
| BS-2024-Q1 | non_current_assets[row 1].Amount | missed | 108500 | None |
| BS-2024-Q1 | non_current_assets[row 2].Label | missed | Security Deposits | None |
| BS-2024-Q1 | non_current_assets[row 2].Amount | missed | 85000 | None |
| BS-2024-Q1 | non_current_assets[row 3].Label | missed | Intangibles (net) | None |
| BS-2024-Q1 | non_current_assets[row 3].Amount | missed | 20000 | None |
| BS-2024-Q1 | current_liabilities[row 0].Label | missed | Accounts Payable | None |
| BS-2024-Q1 | current_liabilities[row 0].Amount | missed | 254800 | None |
| BS-2024-Q1 | current_liabilities[row 1].Label | missed | Accrued Liabilities | None |
| BS-2024-Q1 | current_liabilities[row 1].Amount | missed | 44200 | None |
| BS-2024-Q1 | current_liabilities[row 2].Label | missed | Short-term Loan – First National Bank | None |
| BS-2024-Q1 | current_liabilities[row 2].Amount | missed | 80000 | None |
| BS-2024-Q1 | current_liabilities[row 3].Label | missed | Deferred Revenue | None |
| BS-2024-Q1 | current_liabilities[row 3].Amount | missed | 18200 | None |
| BS-2024-Q1 | current_liabilities[row 4].Label | missed | Current Portion of Long-term Debt | None |
| BS-2024-Q1 | current_liabilities[row 4].Amount | missed | 24000 | None |
| BS-2024-Q1 | long_term_liabilities[row 0].Label | missed | Long-term Loan – First National Bank | None |
| BS-2024-Q1 | long_term_liabilities[row 0].Amount | missed | 121000 | None |
| BS-2024-Q1 | long_term_liabilities[row 1].Label | missed | Deferred Tax Liability | None |
| BS-2024-Q1 | long_term_liabilities[row 1].Amount | missed | 8400 | None |
| BS-2024-Q1 | shareholders_equity[row 0].Label | missed | Common Stock (100 shares @ $1,000 par) | None |
| BS-2024-Q1 | shareholders_equity[row 0].Amount | missed | 100000 | None |
| BS-2024-Q1 | shareholders_equity[row 1].Label | missed | Retained Earnings | None |
| BS-2024-Q1 | shareholders_equity[row 1].Amount | missed | 550751 | None |
| BS-2024-Q1 | shareholders_equity[row 2].Label | missed | Net Income YTD Q1 | None |
| BS-2024-Q1 | shareholders_equity[row 2].Amount | missed | 47353 | None |
| CHQ-001847 | Payer Name | missed | Nexus Global Trading LLC | None |
| CHQ-001847 | Authorized By | missed | Janet Wu | None |
| CHQ-001847 | Routing Number | missed | 021000021 | None |
| CHQ-001847 | Account Number | missed | 7743882201 | None |
| CHQ-001847 | Bank Address | hallucinated (misplaced) | None | 330 Madison Ave, New York, NY 10017 |
| CHQ-001847 | Bank Member FDIC | hallucinated (misplaced) | None | Member FDIC |
| CHQ-001847 | Drawer Company Name | hallucinated (misplaced) | None | Nexus Global Trading LLC |
| CHQ-001847 | Drawer Street Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800 |
| CHQ-001847 | Drawer City State Zip | hallucinated (misplaced) | None | New York, NY 10019 |
| CHQ-001847 | Drawer EIN | hallucinated (misplaced) | None | 47-3821654 |
| CHQ-001847 | Drawer Phone | hallucinated (misplaced) | None | (212) 555-0148 |
| CHQ-001847 | Authorized Signature Name | hallucinated (misplaced) | None | Janet Wu |
| CHQ-001847 | MICR Line | hallucinated (misplaced) | None | A021000021A C7743882201C 001847D |
| CHQ-001847 | Non-Negotiable Copy | hallucinated (misplaced) | None | Non-Negotiable Copy |
| EXP-2024-0081 | Employee Name | missed | Marcus A. Thompson | None |
| EXP-2024-0081 | Company Name | hallucinated (misplaced) | None | NEXUS GLOBAL TRADING LLC |
| EXP-2024-0081 | Company Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| EXP-2024-0081 | Company Phone | hallucinated (misplaced) | None | (212) 555-0148 |
| EXP-2024-0081 | Company EIN | hallucinated (misplaced) | None | 47-3821654 |
| EXP-2024-0081 | Employee | hallucinated (misplaced) | None | Marcus A. Thompson |
| INV-2024-0031 | Company Name | hallucinated (misplaced) | None | NEXUS GLOBAL TRADING LLC |
| INV-2024-0031 | Company Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| INV-2024-0031 | Company Phone | hallucinated (misplaced) | None | (212) 555-0148 |
| INV-2024-0031 | Company Tax ID | hallucinated (misplaced) | None | 47-3821654 |
| INV-2024-0031 | Payment Instructions Bank Name | hallucinated (misplaced) | None | First National Bank of New York |
| INV-2024-0031 | Payment Instructions ABA | hallucinated (misplaced) | None | 021000021 |
| INV-2024-0031 | Payment Instructions Account Number | hallucinated (misplaced) | None | 7743882201 |
| INV-2024-0031 | Payment Instructions Cheque Payable To | hallucinated (misplaced) | None | Nexus Global Trading LLC |
| INV-2024-0031 | Notes Payment Received | hallucinated (misplaced) | None | Payment received via wire transfer Feb 10, 2024. |
| INV-2024-0031 | Notes Reference | hallucinated (misplaced) | None | WT-20240210-4421. |
| INV-2024-0047 | Company Name | hallucinated (misplaced) | None | NEXUS GLOBAL TRADING LLC |
| INV-2024-0047 | Company Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| INV-2024-0047 | Company Phone | hallucinated (misplaced) | None | (212) 555-0148 |
| INV-2024-0047 | Company EIN | hallucinated (misplaced) | None | 47-3821654 |
| INV-2024-0047 | Bill To Email | hallucinated (misplaced) | None | sjohnson@pinnacleelec.com |
| INV-2024-0047 | Payment Instructions Wire Bank | hallucinated (misplaced) | None | First National Bank of New York |
| INV-2024-0047 | Payment Instructions Wire ABA | hallucinated (misplaced) | None | 021000021 |
| INV-2024-0047 | Payment Instructions Wire Account | hallucinated (misplaced) | None | 7743882201 |
| INV-2024-0047 | Payment Instructions Cheque Payable To | hallucinated (misplaced) | None | Nexus Global Trading LLC |
| INV-2024-0047 | Notes Balance Due | hallucinated (misplaced) | None | Balance due March 4, 2024. |
| INV-2024-0047 | Notes Late Payment Interest | hallucinated (misplaced) | None | 1.5% |
| IS-2024-Q4 | Company Name | hallucinated (misplaced) | None | Nexus Global Trading LLC |
| IS-2024-Q4 | Company Street Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800 |
| IS-2024-Q4 | Company City, State, Zip | hallucinated (misplaced) | None | New York, NY 10019 |
| IS-2024-Q4 | Company EIN | hallucinated (misplaced) | None | 47-3821654 |
| IS-2024-Q4 | Period | hallucinated (misplaced) | None | Q4 2024 |
| IS-2024-Q4 | Doc No | hallucinated (misplaced) | None | IS-2024-Q4 |
| IS-2024-Q4 | Prepared by | hallucinated (misplaced) | None | Meridian & Associates CPA |
| PAYSLIP-EMP-0007-APR2024 | Employer Name | missed | Nexus Global Trading LLC | None |
| PAYSLIP-EMP-0007-APR2024 | Title / Department | missed | VP Operations – Executive | None |
| PAYSLIP-EMP-0007-APR2024 | Company Name | hallucinated (misplaced) | None | NEXUS GLOBAL TRADING |
| PAYSLIP-EMP-0007-APR2024 | Company Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| PAYSLIP-EMP-0007-APR2024 | Company EIN | hallucinated (misplaced) | None | 47-3821654 |
| PAYSLIP-EMP-0007-APR2024 | Employee Title / Dept | hallucinated (misplaced) | None | VP Operations – Executive |
| PAYSLIP-EMP-0012-APR2024 | Employer Name | missed | Nexus Global Trading LLC | None |
| PAYSLIP-EMP-0012-APR2024 | Title / Department | missed | Purchasing Manager – Procurement | None |
| PAYSLIP-EMP-0012-APR2024 | Total Earnings | missed | 8300.0 | None |
| PAYSLIP-EMP-0012-APR2024 | Total Deductions | missed | -3117.35 | None |
| PAYSLIP-EMP-0012-APR2024 | Company Name | hallucinated (misplaced) | None | NEXUS GLOBAL TRADING |
| PAYSLIP-EMP-0012-APR2024 | Company Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| PAYSLIP-EMP-0012-APR2024 | Company EIN | hallucinated (misplaced) | None | 47-3821654 |
| PAYSLIP-EMP-0012-APR2024 | Title / Dept | hallucinated (misplaced) | None | Purchasing Manager – Procurement |
| PAYSLIP-EMP-0012-APR2024 | earnings[pred_row 2].Description | hallucinated (misplaced) | None | Total |
| PAYSLIP-EMP-0012-APR2024 | earnings[pred_row 2].Amount | hallucinated (misplaced) | None | $8,300.00 |
| PAYSLIP-EMP-0012-APR2024 | deductions[pred_row 8].Description | hallucinated (misplaced) | None | Total |
| PAYSLIP-EMP-0012-APR2024 | deductions[pred_row 8].Amount | hallucinated (misplaced) | None | ($3,117.35) |
| PO-2024-0018 | Authorised By | near | Janet Wu – VP Operations | Janet Wu |
| PO-2024-0018 | Company Name | hallucinated (misplaced) | None | NEXUS GLOBAL TRADING LLC |
| PO-2024-0018 | Company Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| PO-2024-0018 | Company Phone | hallucinated (misplaced) | None | (212) 555-0148 |
| PO-2024-0018 | Company Tax ID | hallucinated (misplaced) | None | 47-3821654 |
| PO-2024-0018 | Vendor Phone | hallucinated (misplaced) | None | (310) 555-0233 |
| PO-2024-0018 | Buyer Phone | hallucinated (misplaced) | None | (212) 555-0148 |
| PO-2024-0018 | Buyer Email | hallucinated (misplaced) | None | purchasing@nexusglobaltrading.com |
| PO-2024-0018 | Special Instructions | hallucinated (misplaced) | None | Deliver with packing list and COA. Partial shipments not acc |
| PO-2024-0018 | Buyer Signature Email | hallucinated (misplaced) | None | purchasing@nexusglobaltrading.com |
| PO-2024-0018 | Buyer Signature Phone | hallucinated (misplaced) | None | (212) 555-0148 |
| STMT-2024-01 | Bank Address | hallucinated (misplaced) | None | 330 Madison Avenue, New York, NY 10017 |
| STMT-2024-01 | ABA Number | hallucinated (misplaced) | None | 021000021 |
| STMT-2024-01 | Member FDIC | hallucinated (misplaced) | None | Member FDIC |
| STMT-2024-01 | EIN | hallucinated (misplaced) | None | 47-3821654 |
