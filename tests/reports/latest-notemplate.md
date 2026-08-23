# Accuracy report — 2026-08-22 18:16:12

- git: `90ce63e`  mode: **replay**  repeat: 1
- config: {"PRIMARY_LLM": "gemini", "GEMINI_MODEL": "gemini-2.5-flash-lite"}

## Overall

| metric | value |
|---|---|
| **accuracy (correct / gold-valued)** | **86.8%** |
| **accuracy RAW (all adapter widenings off)** | **77.5%** |
| **accuracy CONTENT (container-blind)** | **95.0%** |
| **structure FIDELITY (gold tables returned as tables)** | **64.3%** (9/14; 7 with exact row count) |
| **hallucination rate (hallucinated / extracted)** | **26.3%** |
| **├ INVENTED — value found NOWHERE in the PDF** | **0** (0.0%) |
| ├ misfiled — real content in a slot gold says is EMPTY | 4 |
| └ out-of-schema — real content, name gold has no field for | 115 *(not a defect)* |
| **DEFECT RATE (invented + misfiled / extracted)** | **0.9%** |
| hallucinated values | 119 |
| near misses | 1 |
| **renamed (right value, different field name)** | **5** (1.3%) |
| outcome counts | {"correct": 328, "hallucinated": 119, "missed": 44, "renamed": 5, "near": 1, "empty_ok": 12} |

## By document type

| document type | accuracy | halluc. rate | invented | correct | near | renamed | wrong | missed | halluc. |
|---|---|---|---|---|---|---|---|---|---|
| balance_sheet | 17.4% | 76.5% | 0 | 8 | 0 | 0 | 0 | 38 | 26 |
| bank_statement | 100.0% | 10.3% | 0 | 70 | 0 | 0 | 0 | 0 | 8 |
| cheque | 63.6% | 52.6% | 0 | 7 | 0 | 2 | 0 | 2 | 10 |
| expense_report | 98.1% | 8.5% | 0 | 53 | 0 | 1 | 0 | 0 | 5 |
| income_statement | 100.0% | 32.4% | 0 | 25 | 0 | 0 | 0 | 0 | 12 |
| payslip | 91.4% | 19.5% | 0 | 64 | 0 | 2 | 0 | 4 | 16 |
| purchase_order | 96.8% | 34.0% | 0 | 30 | 1 | 0 | 0 | 0 | 16 |
| sales_invoice | 100.0% | 26.8% | 0 | 71 | 0 | 0 | 0 | 0 | 26 |

## By field type

| field type | accuracy | halluc. rate | invented | correct | near | renamed | wrong | missed | halluc. |
|---|---|---|---|---|---|---|---|---|---|
| date | 100.0% | 0.0% | 0 | 30 | 0 | 0 | 0 | 0 | 0 |
| money | 87.0% | 1.4% | 0 | 140 | 0 | 0 | 0 | 21 | 2 |
| number | 100.0% | 0.0% | 0 | 12 | 0 | 0 | 0 | 0 | 0 |
| string | 83.4% | 43.5% | 0 | 146 | 1 | 5 | 0 | 23 | 117 |

## Per document

| document | type | accuracy | raw | halluc. | invented | route | notes |
|---|---|---|---|---|---|---|---|
| BS-2024-Q1 | balance_sheet | 17.4% | 17.4% | 26 | 0 | BS-2024-Q1.pdf: file_type=digital_pdf pages=2 text_len=1242 |  |
| CHQ-001847 | cheque | 63.6% | 45.5% | 10 | 0 | CHQ-001847.pdf: file_type=digital_pdf pages=1 text_len=501 |  |
| EXP-2024-0081 | expense_report | 98.1% | 98.1% | 5 | 0 | EXP-2024-0081.pdf: file_type=digital_pdf pages=1 text_len=11 |  |
| INV-2024-0031 | sales_invoice | 100.0% | 84.8% | 13 | 0 | INV-2024-0031.pdf: file_type=digital_pdf pages=1 text_len=97 |  |
| INV-2024-0047 | sales_invoice | 100.0% | 97.4% | 13 | 0 | INV-2024-0047.pdf: file_type=digital_pdf pages=1 text_len=10 |  |
| IS-2024-Q4 | income_statement | 100.0% | 88.0% | 12 | 0 | IS-2024-Q4.pdf: file_type=digital_pdf pages=2 text_len=970 |  |
| PAYSLIP-EMP-0007-APR2024 | payslip | 94.6% | 86.5% | 7 | 0 | PAYSLIP-EMP-0007-APR2024.pdf: file_type=digital_pdf pages=2  |  |
| PAYSLIP-EMP-0012-APR2024 | payslip | 87.9% | 81.8% | 9 | 0 | PAYSLIP-EMP-0012-APR2024.pdf: file_type=digital_pdf pages=2  |  |
| PO-2024-0018 | purchase_order | 96.8% | 45.2% | 16 | 0 | PO-2024-0018.pdf: file_type=digital_pdf pages=1 text_len=104 |  |
| STMT-2024-01 | bank_statement | 100.0% | 95.7% | 8 | 0 | STMT-2024-01.pdf: file_type=digital_pdf pages=1 text_len=140 |  |

## Mismatches (everything not correct)

| document | field | outcome | expected | actual |
|---|---|---|---|---|
| BS-2024-Q1 | Other Current Assets | hallucinated (misplaced) | None | $8,800 |
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
| CHQ-001847 | Payer Name | renamed | Nexus Global Trading LLC | Nexus Global Trading LLC |
| CHQ-001847 | Authorized By | renamed | Janet Wu | Janet Wu |
| CHQ-001847 | Routing Number | missed | 021000021 | None |
| CHQ-001847 | Account Number | missed | 7743882201 | None |
| CHQ-001847 | Payee Name | hallucinated (misplaced) | None | Pacific Steel & Metals Co. |
| CHQ-001847 | Amount in Figures | hallucinated (misplaced) | None | $ 8,410.00 |
| CHQ-001847 | Bank Address | hallucinated (misplaced) | None | 330 Madison Ave, New York, NY 10017 |
| CHQ-001847 | Bank Member FDIC | hallucinated (misplaced) | None | Member FDIC |
| CHQ-001847 | Drawer Street Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800 |
| CHQ-001847 | Drawer City State Zip | hallucinated (misplaced) | None | New York, NY 10019 |
| CHQ-001847 | Drawer EIN | hallucinated (misplaced) | None | 47-3821654 |
| CHQ-001847 | Drawer Phone | hallucinated (misplaced) | None | (212) 555-0148 |
| CHQ-001847 | MICR Line | hallucinated (misplaced) | None | A021000021A C7743882201C 001847D |
| CHQ-001847 | Non-Negotiable Copy | hallucinated (misplaced) | None | Non-Negotiable Copy |
| EXP-2024-0081 | Employee Name | renamed | Marcus A. Thompson | Marcus A. Thompson |
| EXP-2024-0081 | TOTAL CLAIMED | hallucinated (misplaced) | None | $1,727.25 |
| EXP-2024-0081 | Company Name | hallucinated (misplaced) | None | NEXUS GLOBAL TRADING LLC |
| EXP-2024-0081 | Company Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| EXP-2024-0081 | Company Phone | hallucinated (misplaced) | None | (212) 555-0148 |
| EXP-2024-0081 | Company EIN | hallucinated (misplaced) | None | 47-3821654 |
| INV-2024-0031 | TOTAL DUE | hallucinated (misplaced) | None | $12,179.21 |
| INV-2024-0031 | Bill To Contact Email | hallucinated (misplaced) | None | rchen@apexindustrial.com |
| INV-2024-0031 | Bill To Contact Person | hallucinated (misplaced) | None | Mr. Robert Chen |
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
| INV-2024-0047 | TOTAL DUE | hallucinated (misplaced) | None | $17,411.79 |
| INV-2024-0047 | Terms | hallucinated (misplaced) | None | Net 30 |
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
| IS-2024-Q4 | GROSS PROFIT | hallucinated (misplaced) | None | $695,400 |
| IS-2024-Q4 | OPERATING INCOME (EBIT) | hallucinated (misplaced) | None | $336,150 |
| IS-2024-Q4 | Est. Income Tax Provision (21%) | hallucinated (misplaced) | None | $70,852 |
| IS-2024-Q4 | NET INCOME (LOSS) BEFORE TAX | hallucinated (misplaced) | None | $337,390 |
| IS-2024-Q4 | NET INCOME (LOSS) AFTER TAX | hallucinated (misplaced) | None | $266,538 |
| IS-2024-Q4 | Company Name | hallucinated (misplaced) | None | Nexus Global Trading LLC |
| IS-2024-Q4 | Company Street Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800 |
| IS-2024-Q4 | Company City, State, Zip | hallucinated (misplaced) | None | New York, NY 10019 |
| IS-2024-Q4 | Company EIN | hallucinated (misplaced) | None | 47-3821654 |
| IS-2024-Q4 | Period | hallucinated (misplaced) | None | Q4 2024 |
| IS-2024-Q4 | Document Number | hallucinated (misplaced) | None | IS-2024-Q4 |
| IS-2024-Q4 | Prepared by | hallucinated (misplaced) | None | Meridian & Associates CPA |
| PAYSLIP-EMP-0007-APR2024 | Employer Name | missed | Nexus Global Trading LLC | None |
| PAYSLIP-EMP-0007-APR2024 | Title / Department | renamed | VP Operations – Executive | VP Operations – Executive |
| PAYSLIP-EMP-0007-APR2024 | Earnings Total | hallucinated (misplaced) | None | $14,583.33 |
| PAYSLIP-EMP-0007-APR2024 | Deductions Total | hallucinated (misplaced) | None | ($7,070.30) |
| PAYSLIP-EMP-0007-APR2024 | NET PAY | hallucinated (misplaced) | None | $7,513.0 3 |
| PAYSLIP-EMP-0007-APR2024 | Employee SSN | hallucinated (misplaced) | None | ***-**-3317 |
| PAYSLIP-EMP-0007-APR2024 | Company Name | hallucinated (misplaced) | None | NEXUS GLOBAL TRADING |
| PAYSLIP-EMP-0007-APR2024 | Company Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| PAYSLIP-EMP-0007-APR2024 | Company EIN | hallucinated (misplaced) | None | 47-3821654 |
| PAYSLIP-EMP-0012-APR2024 | Employer Name | missed | Nexus Global Trading LLC | None |
| PAYSLIP-EMP-0012-APR2024 | Title / Department | renamed | Purchasing Manager – Procurement | Purchasing Manager – Procurement |
| PAYSLIP-EMP-0012-APR2024 | Total Earnings | missed | 8300.0 | None |
| PAYSLIP-EMP-0012-APR2024 | Total Deductions | missed | -3117.35 | None |
| PAYSLIP-EMP-0012-APR2024 | Net Pay Amount | hallucinated (misplaced) | None | $5,182.65 |
| PAYSLIP-EMP-0012-APR2024 | Employee SSN | hallucinated (misplaced) | None | ***-**-4821 |
| PAYSLIP-EMP-0012-APR2024 | Company Name | hallucinated (misplaced) | None | NEXUS GLOBAL TRADING |
| PAYSLIP-EMP-0012-APR2024 | Company Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| PAYSLIP-EMP-0012-APR2024 | Company EIN | hallucinated (misplaced) | None | 47-3821654 |
| PAYSLIP-EMP-0012-APR2024 | earnings[pred_row 2].Description | hallucinated (misplaced) | None | Total |
| PAYSLIP-EMP-0012-APR2024 | earnings[pred_row 2].Amount | hallucinated (misplaced) | None | $8,300.00 |
| PAYSLIP-EMP-0012-APR2024 | deductions[pred_row 8].Description | hallucinated (misplaced) | None | Total |
| PAYSLIP-EMP-0012-APR2024 | deductions[pred_row 8].Amount | hallucinated (misplaced) | None | ($3,117.35) |
| PO-2024-0018 | Authorised By | near | Janet Wu – VP Operations | Janet Wu |
| PO-2024-0018 | ORDER TOTAL | hallucinated (misplaced) | None | $12,570.00 |
| PO-2024-0018 | Authorised By Title | hallucinated (misplaced) | None | VP Operations |
| PO-2024-0018 | Authorised By Name | hallucinated (misplaced) | None | Janet Wu |
| PO-2024-0018 | Buyer Signature Name | hallucinated (misplaced) | None | Marcus A. Thompson |
| PO-2024-0018 | Buyer Signature Title | hallucinated (misplaced) | None | Purchasing Manager |
| PO-2024-0018 | Tax (exempt) | hallucinated (misplaced) | None | $0.00 |
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
| STMT-2024-01 | Account Holder Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| STMT-2024-01 | Type | hallucinated (misplaced) | None | Business Checking |
| STMT-2024-01 | Credits | hallucinated (misplaced) | None | $46,841.68 |
| STMT-2024-01 | Debits | hallucinated (misplaced) | None | $105,804.97 |
| STMT-2024-01 | Bank Address | hallucinated (misplaced) | None | 330 Madison Avenue, New York, NY 10017 |
| STMT-2024-01 | ABA Number | hallucinated (misplaced) | None | 021000021 |
| STMT-2024-01 | Member FDIC | hallucinated (misplaced) | None | Member FDIC |
| STMT-2024-01 | EIN | hallucinated (misplaced) | None | 47-3821654 |

## Changes vs previous run

- CHQ-001847 :: Account Number: None -> missed
- CHQ-001847 :: Amount: None -> correct
- CHQ-001847 :: Amount in Figures: None -> hallucinated
- CHQ-001847 :: Amount in Words: None -> correct
- CHQ-001847 :: Authorized By: None -> renamed
- CHQ-001847 :: Bank Address: None -> hallucinated
- CHQ-001847 :: Bank Member FDIC: None -> hallucinated
- CHQ-001847 :: Bank Name: None -> correct
- CHQ-001847 :: Cheque Number: None -> correct
- CHQ-001847 :: Date: None -> correct
- CHQ-001847 :: Drawer City State Zip: None -> hallucinated
- CHQ-001847 :: Drawer EIN: None -> hallucinated
- CHQ-001847 :: Drawer Phone: None -> hallucinated
- CHQ-001847 :: Drawer Street Address: None -> hallucinated
- CHQ-001847 :: MICR Line: None -> hallucinated
- CHQ-001847 :: Memo: None -> correct
- CHQ-001847 :: Non-Negotiable Copy: None -> hallucinated
- CHQ-001847 :: Payee: None -> correct
- CHQ-001847 :: Payee Name: None -> hallucinated
- CHQ-001847 :: Payer Name: None -> renamed
- CHQ-001847 :: Routing Number: None -> missed
- EXP-2024-0081 :: Company Address: None -> hallucinated
- EXP-2024-0081 :: Company EIN: None -> hallucinated
- EXP-2024-0081 :: Company Name: None -> hallucinated
- EXP-2024-0081 :: Company Phone: None -> hallucinated
- EXP-2024-0081 :: Department: None -> correct
- EXP-2024-0081 :: Employee ID: None -> correct
- EXP-2024-0081 :: Employee Name: None -> renamed
- EXP-2024-0081 :: Manager: None -> correct
- EXP-2024-0081 :: Period: None -> correct
- EXP-2024-0081 :: Purpose: None -> correct
- EXP-2024-0081 :: Report No: None -> correct
- EXP-2024-0081 :: Status: None -> correct
- EXP-2024-0081 :: TOTAL CLAIMED: None -> hallucinated
- EXP-2024-0081 :: Total Claimed: None -> correct
- EXP-2024-0081 :: expenses :: row_count_mismatch: None -> 0
- EXP-2024-0081 :: expenses[row 0].Amount: None -> correct
- EXP-2024-0081 :: expenses[row 0].Category: None -> correct
- EXP-2024-0081 :: expenses[row 0].Date: None -> correct
- EXP-2024-0081 :: expenses[row 0].Description: None -> correct
- EXP-2024-0081 :: expenses[row 0].Type: None -> correct
- EXP-2024-0081 :: expenses[row 1].Amount: None -> correct
- EXP-2024-0081 :: expenses[row 1].Category: None -> correct
- EXP-2024-0081 :: expenses[row 1].Date: None -> correct
- EXP-2024-0081 :: expenses[row 1].Description: None -> correct
- EXP-2024-0081 :: expenses[row 1].Type: None -> correct
- EXP-2024-0081 :: expenses[row 2].Amount: None -> correct
- EXP-2024-0081 :: expenses[row 2].Category: None -> correct
- EXP-2024-0081 :: expenses[row 2].Date: None -> correct
- EXP-2024-0081 :: expenses[row 2].Description: None -> correct
- EXP-2024-0081 :: expenses[row 2].Type: None -> correct
- EXP-2024-0081 :: expenses[row 3].Amount: None -> correct
- EXP-2024-0081 :: expenses[row 3].Category: None -> correct
- EXP-2024-0081 :: expenses[row 3].Date: None -> correct
- EXP-2024-0081 :: expenses[row 3].Description: None -> correct
- EXP-2024-0081 :: expenses[row 3].Type: None -> correct
- EXP-2024-0081 :: expenses[row 4].Amount: None -> correct
- EXP-2024-0081 :: expenses[row 4].Category: None -> correct
- EXP-2024-0081 :: expenses[row 4].Date: None -> correct
- EXP-2024-0081 :: expenses[row 4].Description: None -> correct
- EXP-2024-0081 :: expenses[row 4].Type: None -> correct
- EXP-2024-0081 :: expenses[row 5].Amount: None -> correct
- EXP-2024-0081 :: expenses[row 5].Category: None -> correct
- EXP-2024-0081 :: expenses[row 5].Date: None -> correct
- EXP-2024-0081 :: expenses[row 5].Description: None -> correct
- EXP-2024-0081 :: expenses[row 5].Type: None -> correct
- EXP-2024-0081 :: expenses[row 6].Amount: None -> correct
- EXP-2024-0081 :: expenses[row 6].Category: None -> correct
- EXP-2024-0081 :: expenses[row 6].Date: None -> correct
- EXP-2024-0081 :: expenses[row 6].Description: None -> correct
- EXP-2024-0081 :: expenses[row 6].Type: None -> correct
- EXP-2024-0081 :: expenses[row 7].Amount: None -> correct
- EXP-2024-0081 :: expenses[row 7].Category: None -> correct
- EXP-2024-0081 :: expenses[row 7].Date: None -> correct
- EXP-2024-0081 :: expenses[row 7].Description: None -> correct
- EXP-2024-0081 :: expenses[row 7].Type: None -> correct
- EXP-2024-0081 :: expenses[row 8].Amount: None -> correct
- EXP-2024-0081 :: expenses[row 8].Category: None -> correct
- EXP-2024-0081 :: expenses[row 8].Date: None -> correct
- EXP-2024-0081 :: expenses[row 8].Description: None -> correct
- EXP-2024-0081 :: expenses[row 8].Type: None -> correct
- INV-2024-0031 :: Bill To Address: None -> correct
- INV-2024-0031 :: Bill To Company: None -> correct
- INV-2024-0031 :: Bill To Contact: None -> correct
- INV-2024-0031 :: Bill To Contact Email: None -> hallucinated
- INV-2024-0031 :: Bill To Contact Person: None -> hallucinated
- INV-2024-0031 :: Company Address: None -> hallucinated
- INV-2024-0031 :: Company Name: None -> hallucinated
- INV-2024-0031 :: Company Phone: None -> hallucinated
- INV-2024-0031 :: Company Tax ID: None -> hallucinated
- INV-2024-0031 :: Due Date: None -> correct
- INV-2024-0031 :: Invoice Date: None -> correct
- INV-2024-0031 :: Invoice Number: None -> correct
- INV-2024-0031 :: Notes Payment Received: None -> hallucinated
- INV-2024-0031 :: Notes Reference: None -> hallucinated
- INV-2024-0031 :: PO Reference: None -> correct
- INV-2024-0031 :: Payment Instructions ABA: None -> hallucinated
- INV-2024-0031 :: Payment Instructions Account Number: None -> hallucinated
- INV-2024-0031 :: Payment Instructions Bank Name: None -> hallucinated
- INV-2024-0031 :: Payment Instructions Cheque Payable To: None -> hallucinated
- INV-2024-0031 :: Payment Terms: None -> correct
- INV-2024-0031 :: Sales Tax: None -> correct
- INV-2024-0031 :: Shipping & Handling: None -> correct
- INV-2024-0031 :: Status: None -> correct
- INV-2024-0031 :: Subtotal: None -> correct
- INV-2024-0031 :: TOTAL DUE: None -> hallucinated
- INV-2024-0031 :: Total Due: None -> correct
- INV-2024-0031 :: line_items :: row_count_mismatch: None -> 0
- INV-2024-0031 :: line_items[row 0].Amount: None -> correct
- INV-2024-0031 :: line_items[row 0].Description: None -> correct
- INV-2024-0031 :: line_items[row 0].Qty: None -> correct
- INV-2024-0031 :: line_items[row 0].Unit: None -> correct
- INV-2024-0031 :: line_items[row 0].Unit Price: None -> correct
- INV-2024-0031 :: line_items[row 1].Amount: None -> correct
- INV-2024-0031 :: line_items[row 1].Description: None -> correct
- INV-2024-0031 :: line_items[row 1].Qty: None -> correct
- INV-2024-0031 :: line_items[row 1].Unit: None -> correct
- INV-2024-0031 :: line_items[row 1].Unit Price: None -> correct
- INV-2024-0031 :: line_items[row 2].Amount: None -> correct
- INV-2024-0031 :: line_items[row 2].Description: None -> correct
- INV-2024-0031 :: line_items[row 2].Qty: None -> correct
- INV-2024-0031 :: line_items[row 2].Unit: None -> correct
- INV-2024-0031 :: line_items[row 2].Unit Price: None -> correct
- INV-2024-0031 :: line_items[row 3].Amount: None -> correct
- INV-2024-0031 :: line_items[row 3].Description: None -> correct
- INV-2024-0031 :: line_items[row 3].Qty: None -> correct
- INV-2024-0031 :: line_items[row 3].Unit: None -> correct
- INV-2024-0031 :: line_items[row 3].Unit Price: None -> correct
- INV-2024-0047 :: Bill To Address: None -> correct
- INV-2024-0047 :: Bill To Company: None -> correct
- INV-2024-0047 :: Bill To Contact: None -> correct
- INV-2024-0047 :: Bill To Email: None -> hallucinated
- INV-2024-0047 :: Company Address: None -> hallucinated
- INV-2024-0047 :: Company EIN: None -> hallucinated
- INV-2024-0047 :: Company Name: None -> hallucinated
- INV-2024-0047 :: Company Phone: None -> hallucinated
- INV-2024-0047 :: Due Date: None -> correct
- INV-2024-0047 :: Invoice Date: None -> correct
- INV-2024-0047 :: Invoice Number: None -> correct
- INV-2024-0047 :: Notes Balance Due: None -> hallucinated
- INV-2024-0047 :: Notes Late Payment Interest: None -> hallucinated
- INV-2024-0047 :: PO Reference: None -> correct
- INV-2024-0047 :: Payment Instructions Cheque Payable To: None -> hallucinated
- INV-2024-0047 :: Payment Instructions Wire ABA: None -> hallucinated
- INV-2024-0047 :: Payment Instructions Wire Account: None -> hallucinated
- INV-2024-0047 :: Payment Instructions Wire Bank: None -> hallucinated
- INV-2024-0047 :: Payment Terms: None -> correct
- INV-2024-0047 :: Sales Tax: None -> correct
- INV-2024-0047 :: Shipping & Handling: None -> correct
- INV-2024-0047 :: Status: None -> correct
- INV-2024-0047 :: Subtotal: None -> correct
- INV-2024-0047 :: TOTAL DUE: None -> hallucinated
- INV-2024-0047 :: Terms: None -> hallucinated
- INV-2024-0047 :: Total Due: None -> correct
- INV-2024-0047 :: line_items :: row_count_mismatch: None -> 0
- INV-2024-0047 :: line_items[row 0].Amount: None -> correct
- INV-2024-0047 :: line_items[row 0].Description: None -> correct
- INV-2024-0047 :: line_items[row 0].Qty: None -> correct
- INV-2024-0047 :: line_items[row 0].Unit: None -> correct
- INV-2024-0047 :: line_items[row 0].Unit Price: None -> correct
- INV-2024-0047 :: line_items[row 1].Amount: None -> correct
- INV-2024-0047 :: line_items[row 1].Description: None -> correct
- INV-2024-0047 :: line_items[row 1].Qty: None -> correct
- INV-2024-0047 :: line_items[row 1].Unit: None -> correct
- INV-2024-0047 :: line_items[row 1].Unit Price: None -> correct
- INV-2024-0047 :: line_items[row 2].Amount: None -> correct
- INV-2024-0047 :: line_items[row 2].Description: None -> correct
- INV-2024-0047 :: line_items[row 2].Qty: None -> correct
- INV-2024-0047 :: line_items[row 2].Unit: None -> correct
- INV-2024-0047 :: line_items[row 2].Unit Price: None -> correct
- INV-2024-0047 :: line_items[row 3].Amount: None -> correct
- INV-2024-0047 :: line_items[row 3].Description: None -> correct
- INV-2024-0047 :: line_items[row 3].Qty: None -> correct
- INV-2024-0047 :: line_items[row 3].Unit: None -> correct
- INV-2024-0047 :: line_items[row 3].Unit Price: None -> correct
- INV-2024-0047 :: line_items[row 4].Amount: None -> correct
- INV-2024-0047 :: line_items[row 4].Description: None -> correct
- INV-2024-0047 :: line_items[row 4].Qty: None -> correct
- INV-2024-0047 :: line_items[row 4].Unit: None -> correct
- INV-2024-0047 :: line_items[row 4].Unit Price: None -> correct
- IS-2024-Q4 :: Bad Debt: None -> correct
- IS-2024-Q4 :: Bank Charges & Interest: None -> correct
- IS-2024-Q4 :: Company City, State, Zip: None -> hallucinated
- IS-2024-Q4 :: Company EIN: None -> hallucinated
- IS-2024-Q4 :: Company Name: None -> hallucinated
- IS-2024-Q4 :: Company Street Address: None -> hallucinated
- IS-2024-Q4 :: Depreciation: None -> correct
- IS-2024-Q4 :: Document Number: None -> hallucinated
- IS-2024-Q4 :: Est. Income Tax Provision (21%): None -> hallucinated
- IS-2024-Q4 :: Freight In: None -> correct
- IS-2024-Q4 :: GROSS PROFIT: None -> hallucinated
- IS-2024-Q4 :: Gross Profit: None -> correct
- IS-2024-Q4 :: Gross Sales: None -> correct
- IS-2024-Q4 :: Income Tax Provision: None -> correct
- IS-2024-Q4 :: Insurance: None -> correct
- IS-2024-Q4 :: Interest Income: None -> correct
- IS-2024-Q4 :: Less: Closing Inventory: None -> correct
- IS-2024-Q4 :: Less: Returns: None -> correct
- IS-2024-Q4 :: Marketing: None -> correct
- IS-2024-Q4 :: NET INCOME (LOSS) AFTER TAX: None -> hallucinated
- IS-2024-Q4 :: NET INCOME (LOSS) BEFORE TAX: None -> hallucinated
- IS-2024-Q4 :: Net Income After Tax: None -> correct
- IS-2024-Q4 :: Net Income Before Tax: None -> correct
- IS-2024-Q4 :: Net Revenue: None -> correct
- IS-2024-Q4 :: OPERATING INCOME (EBIT): None -> hallucinated
- IS-2024-Q4 :: Office & Misc: None -> correct
- IS-2024-Q4 :: Opening Inventory: None -> correct
- IS-2024-Q4 :: Operating Income (EBIT): None -> correct
- IS-2024-Q4 :: Period: None -> hallucinated
- IS-2024-Q4 :: Prepared by: None -> hallucinated
- IS-2024-Q4 :: Professional Fees: None -> correct
- IS-2024-Q4 :: Purchases: None -> correct
- IS-2024-Q4 :: Rent: None -> correct
- IS-2024-Q4 :: Salaries & Wages: None -> correct
- IS-2024-Q4 :: Total COGS: None -> correct
- IS-2024-Q4 :: Total Operating Expenses: None -> correct
- IS-2024-Q4 :: Utilities: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: Annual Salary: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: Company Address: None -> hallucinated
- PAYSLIP-EMP-0007-APR2024 :: Company EIN: None -> hallucinated
- PAYSLIP-EMP-0007-APR2024 :: Company Name: None -> hallucinated
- PAYSLIP-EMP-0007-APR2024 :: Deductions Total: None -> hallucinated
- PAYSLIP-EMP-0007-APR2024 :: Earnings Total: None -> hallucinated
- PAYSLIP-EMP-0007-APR2024 :: Employee ID: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: Employee Name: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: Employee SSN: None -> hallucinated
- PAYSLIP-EMP-0007-APR2024 :: Employer Name: None -> missed
- PAYSLIP-EMP-0007-APR2024 :: NET PAY: None -> hallucinated
- PAYSLIP-EMP-0007-APR2024 :: Net Pay: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: Pay Date: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: Pay Period: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: SSN: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: Title / Department: None -> renamed
- PAYSLIP-EMP-0007-APR2024 :: Total Deductions: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: Total Earnings: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: YTD Gross Earnings: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: YTD Taxes Withheld: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: deductions :: row_count_mismatch: None -> 0
- PAYSLIP-EMP-0007-APR2024 :: deductions[row 0].Amount: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: deductions[row 0].Description: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: deductions[row 1].Amount: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: deductions[row 1].Description: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: deductions[row 2].Amount: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: deductions[row 2].Description: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: deductions[row 3].Amount: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: deductions[row 3].Description: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: deductions[row 4].Amount: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: deductions[row 4].Description: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: deductions[row 5].Amount: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: deductions[row 5].Description: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: deductions[row 6].Amount: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: deductions[row 6].Description: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: deductions[row 7].Amount: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: deductions[row 7].Description: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: deductions[row 8].Amount: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: deductions[row 8].Description: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: earnings :: row_count_mismatch: None -> 0
- PAYSLIP-EMP-0007-APR2024 :: earnings[row 0].Amount: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: earnings[row 0].Description: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: earnings[row 1].Amount: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: earnings[row 1].Description: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: earnings[row 2].Amount: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: earnings[row 2].Description: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: Annual Salary: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: Company Address: None -> hallucinated
- PAYSLIP-EMP-0012-APR2024 :: Company EIN: None -> hallucinated
- PAYSLIP-EMP-0012-APR2024 :: Company Name: None -> hallucinated
- PAYSLIP-EMP-0012-APR2024 :: Employee ID: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: Employee Name: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: Employee SSN: None -> hallucinated
- PAYSLIP-EMP-0012-APR2024 :: Employer Name: None -> missed
- PAYSLIP-EMP-0012-APR2024 :: Net Pay: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: Net Pay Amount: None -> hallucinated
- PAYSLIP-EMP-0012-APR2024 :: Pay Date: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: Pay Period: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: SSN: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: Title / Department: None -> renamed
- PAYSLIP-EMP-0012-APR2024 :: Total Deductions: None -> missed
- PAYSLIP-EMP-0012-APR2024 :: Total Earnings: None -> missed
- PAYSLIP-EMP-0012-APR2024 :: YTD Gross Earnings: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: YTD Taxes Withheld: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: deductions :: row_count_mismatch: None -> 1
- PAYSLIP-EMP-0012-APR2024 :: deductions[pred_row 8].Amount: None -> hallucinated
- PAYSLIP-EMP-0012-APR2024 :: deductions[pred_row 8].Description: None -> hallucinated
- PAYSLIP-EMP-0012-APR2024 :: deductions[row 0].Amount: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: deductions[row 0].Description: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: deductions[row 1].Amount: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: deductions[row 1].Description: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: deductions[row 2].Amount: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: deductions[row 2].Description: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: deductions[row 3].Amount: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: deductions[row 3].Description: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: deductions[row 4].Amount: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: deductions[row 4].Description: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: deductions[row 5].Amount: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: deductions[row 5].Description: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: deductions[row 6].Amount: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: deductions[row 6].Description: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: deductions[row 7].Amount: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: deductions[row 7].Description: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: earnings :: row_count_mismatch: None -> 1
- PAYSLIP-EMP-0012-APR2024 :: earnings[pred_row 2].Amount: None -> hallucinated
- PAYSLIP-EMP-0012-APR2024 :: earnings[pred_row 2].Description: None -> hallucinated
- PAYSLIP-EMP-0012-APR2024 :: earnings[row 0].Amount: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: earnings[row 0].Description: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: earnings[row 1].Amount: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: earnings[row 1].Description: None -> correct
- PO-2024-0018 :: Authorised By: None -> near
- PO-2024-0018 :: Authorised By Name: None -> hallucinated
- PO-2024-0018 :: Authorised By Title: None -> hallucinated
- PO-2024-0018 :: Buyer Email: None -> hallucinated
- PO-2024-0018 :: Buyer Name: None -> correct
- PO-2024-0018 :: Buyer Phone: None -> hallucinated
- PO-2024-0018 :: Buyer Signature Email: None -> hallucinated
- PO-2024-0018 :: Buyer Signature Name: None -> hallucinated
- PO-2024-0018 :: Buyer Signature Phone: None -> hallucinated
- PO-2024-0018 :: Buyer Signature Title: None -> hallucinated
- PO-2024-0018 :: Buyer Title: None -> correct
- PO-2024-0018 :: Company Address: None -> hallucinated
- PO-2024-0018 :: Company Name: None -> hallucinated
- PO-2024-0018 :: Company Phone: None -> hallucinated
- PO-2024-0018 :: Company Tax ID: None -> hallucinated
- PO-2024-0018 :: Date: None -> correct
- PO-2024-0018 :: Freight: None -> correct
- PO-2024-0018 :: ORDER TOTAL: None -> hallucinated
- PO-2024-0018 :: Order Total: None -> correct
- PO-2024-0018 :: PO Number: None -> correct
- PO-2024-0018 :: Required By: None -> correct
- PO-2024-0018 :: Ship Via: None -> correct
- PO-2024-0018 :: Special Instructions: None -> hallucinated
- PO-2024-0018 :: Subtotal: None -> correct
- PO-2024-0018 :: Tax: None -> correct
- PO-2024-0018 :: Tax (exempt): None -> hallucinated
- PO-2024-0018 :: Terms: None -> correct
- PO-2024-0018 :: Vendor Address: None -> correct
- PO-2024-0018 :: Vendor Contact: None -> correct
- PO-2024-0018 :: Vendor ID: None -> correct
- PO-2024-0018 :: Vendor Name: None -> correct
- PO-2024-0018 :: Vendor Phone: None -> hallucinated
- PO-2024-0018 :: line_items :: row_count_mismatch: None -> 0
- PO-2024-0018 :: line_items[row 0].Item / Description: None -> correct
- PO-2024-0018 :: line_items[row 0].Qty: None -> correct
- PO-2024-0018 :: line_items[row 0].Total: None -> correct
- PO-2024-0018 :: line_items[row 0].Unit: None -> correct
- PO-2024-0018 :: line_items[row 0].Unit Cost: None -> correct
- PO-2024-0018 :: line_items[row 1].Item / Description: None -> correct
- PO-2024-0018 :: line_items[row 1].Qty: None -> correct
- PO-2024-0018 :: line_items[row 1].Total: None -> correct
- PO-2024-0018 :: line_items[row 1].Unit: None -> correct
- PO-2024-0018 :: line_items[row 1].Unit Cost: None -> correct
- PO-2024-0018 :: line_items[row 2].Item / Description: None -> correct
- PO-2024-0018 :: line_items[row 2].Qty: None -> correct
- PO-2024-0018 :: line_items[row 2].Total: None -> correct
- PO-2024-0018 :: line_items[row 2].Unit: None -> correct
- PO-2024-0018 :: line_items[row 2].Unit Cost: None -> correct
- STMT-2024-01 :: ABA Number: None -> hallucinated
- STMT-2024-01 :: Account Holder: None -> correct
- STMT-2024-01 :: Account Holder Address: None -> hallucinated
- STMT-2024-01 :: Account No: None -> correct
- STMT-2024-01 :: Account Type: None -> correct
- STMT-2024-01 :: Bank Address: None -> hallucinated
- STMT-2024-01 :: Bank Name: None -> correct
- STMT-2024-01 :: Closing Balance: None -> correct
- STMT-2024-01 :: Credits: None -> hallucinated
- STMT-2024-01 :: Debits: None -> hallucinated
- STMT-2024-01 :: EIN: None -> hallucinated
- STMT-2024-01 :: Member FDIC: None -> hallucinated
- STMT-2024-01 :: Opening Balance: None -> correct
- STMT-2024-01 :: Period: None -> correct
- STMT-2024-01 :: Statement No: None -> correct
- STMT-2024-01 :: Total Credits: None -> correct
- STMT-2024-01 :: Total Debits: None -> correct
- STMT-2024-01 :: Type: None -> hallucinated
- STMT-2024-01 :: transactions :: row_count_mismatch: None -> 0
- STMT-2024-01 :: transactions[row 0].Balance: None -> correct
- STMT-2024-01 :: transactions[row 0].Credit: None -> correct
- STMT-2024-01 :: transactions[row 0].Date: None -> correct
- STMT-2024-01 :: transactions[row 0].Debit: None -> empty_ok
- STMT-2024-01 :: transactions[row 0].Description: None -> correct
- STMT-2024-01 :: transactions[row 0].Type: None -> correct
- STMT-2024-01 :: transactions[row 10].Balance: None -> correct
- STMT-2024-01 :: transactions[row 10].Credit: None -> correct
- STMT-2024-01 :: transactions[row 10].Date: None -> correct
- STMT-2024-01 :: transactions[row 10].Debit: None -> empty_ok
- STMT-2024-01 :: transactions[row 10].Description: None -> correct
- STMT-2024-01 :: transactions[row 10].Type: None -> correct
- STMT-2024-01 :: transactions[row 11].Balance: None -> correct
- STMT-2024-01 :: transactions[row 11].Credit: None -> empty_ok
- STMT-2024-01 :: transactions[row 11].Date: None -> correct
- STMT-2024-01 :: transactions[row 11].Debit: None -> correct
- STMT-2024-01 :: transactions[row 11].Description: None -> correct
- STMT-2024-01 :: transactions[row 11].Type: None -> correct
- STMT-2024-01 :: transactions[row 1].Balance: None -> correct
- STMT-2024-01 :: transactions[row 1].Credit: None -> empty_ok
- STMT-2024-01 :: transactions[row 1].Date: None -> correct
- STMT-2024-01 :: transactions[row 1].Debit: None -> correct
- STMT-2024-01 :: transactions[row 1].Description: None -> correct
- STMT-2024-01 :: transactions[row 1].Type: None -> correct
- STMT-2024-01 :: transactions[row 2].Balance: None -> correct
- STMT-2024-01 :: transactions[row 2].Credit: None -> empty_ok
- STMT-2024-01 :: transactions[row 2].Date: None -> correct
- STMT-2024-01 :: transactions[row 2].Debit: None -> correct
- STMT-2024-01 :: transactions[row 2].Description: None -> correct
- STMT-2024-01 :: transactions[row 2].Type: None -> correct
- STMT-2024-01 :: transactions[row 3].Balance: None -> correct
- STMT-2024-01 :: transactions[row 3].Credit: None -> correct
- STMT-2024-01 :: transactions[row 3].Date: None -> correct
- STMT-2024-01 :: transactions[row 3].Debit: None -> empty_ok
- STMT-2024-01 :: transactions[row 3].Description: None -> correct
- STMT-2024-01 :: transactions[row 3].Type: None -> correct
- STMT-2024-01 :: transactions[row 4].Balance: None -> correct
- STMT-2024-01 :: transactions[row 4].Credit: None -> empty_ok
- STMT-2024-01 :: transactions[row 4].Date: None -> correct
- STMT-2024-01 :: transactions[row 4].Debit: None -> correct
- STMT-2024-01 :: transactions[row 4].Description: None -> correct
- STMT-2024-01 :: transactions[row 4].Type: None -> correct
- STMT-2024-01 :: transactions[row 5].Balance: None -> correct
- STMT-2024-01 :: transactions[row 5].Credit: None -> empty_ok
- STMT-2024-01 :: transactions[row 5].Date: None -> correct
- STMT-2024-01 :: transactions[row 5].Debit: None -> correct
- STMT-2024-01 :: transactions[row 5].Description: None -> correct
- STMT-2024-01 :: transactions[row 5].Type: None -> correct
- STMT-2024-01 :: transactions[row 6].Balance: None -> correct
- STMT-2024-01 :: transactions[row 6].Credit: None -> empty_ok
- STMT-2024-01 :: transactions[row 6].Date: None -> correct
- STMT-2024-01 :: transactions[row 6].Debit: None -> correct
- STMT-2024-01 :: transactions[row 6].Description: None -> correct
- STMT-2024-01 :: transactions[row 6].Type: None -> correct
- STMT-2024-01 :: transactions[row 7].Balance: None -> correct
- STMT-2024-01 :: transactions[row 7].Credit: None -> correct
- STMT-2024-01 :: transactions[row 7].Date: None -> correct
- STMT-2024-01 :: transactions[row 7].Debit: None -> empty_ok
- STMT-2024-01 :: transactions[row 7].Description: None -> correct
- STMT-2024-01 :: transactions[row 7].Type: None -> correct
- STMT-2024-01 :: transactions[row 8].Balance: None -> correct
- STMT-2024-01 :: transactions[row 8].Credit: None -> empty_ok
- STMT-2024-01 :: transactions[row 8].Date: None -> correct
- STMT-2024-01 :: transactions[row 8].Debit: None -> correct
- STMT-2024-01 :: transactions[row 8].Description: None -> correct
- STMT-2024-01 :: transactions[row 8].Type: None -> correct
- STMT-2024-01 :: transactions[row 9].Balance: None -> correct
- STMT-2024-01 :: transactions[row 9].Credit: None -> empty_ok
- STMT-2024-01 :: transactions[row 9].Date: None -> correct
- STMT-2024-01 :: transactions[row 9].Debit: None -> correct
- STMT-2024-01 :: transactions[row 9].Description: None -> correct
- STMT-2024-01 :: transactions[row 9].Type: None -> correct
