# Accuracy report — 2026-08-22 22:44:49

- git: `fb9c8af`  mode: **replay**  repeat: 3
- config: {"PRIMARY_LLM": "gemini", "GEMINI_MODEL": "gemini-2.5-flash-lite"}

## Overall

| metric | value |
|---|---|
| **accuracy (correct / gold-valued)** | **96.6%** |
| **accuracy RAW (all adapter widenings off)** | **83.3%** |
| **accuracy CONTENT (container-blind)** | **94.6%** |
| **structure FIDELITY (gold tables returned as tables)** | **100.0%** (14/14; 14 with exact row count) |
| **hallucination rate (hallucinated / extracted)** | **21.5%** |
| **├ INVENTED — value found NOWHERE in the PDF** | **0** (0.0%) |
| ├ misfiled — real content in a slot gold says is EMPTY | 0 |
| └ out-of-schema — real content, name gold has no field for | 102 *(not a defect)* |
| **DEFECT RATE (invented + misfiled / extracted)** | **0.0%** |
| hallucinated values | 102 |
| near misses | 1 |
| **renamed (right value, different field name)** | **6** (1.6%) |
| outcome counts | {"correct": 365, "hallucinated": 102, "missed": 6, "renamed": 6, "near": 1, "empty_ok": 12} |

## By document type

| document type | accuracy | halluc. rate | invented | correct | near | renamed | wrong | missed | halluc. |
|---|---|---|---|---|---|---|---|---|---|
| balance_sheet | 100.0% | 16.4% | 0 | 46 | 0 | 0 | 0 | 0 | 9 |
| bank_statement | 97.1% | 13.6% | 0 | 68 | 0 | 2 | 0 | 0 | 11 |
| cheque | 54.5% | 58.8% | 0 | 6 | 0 | 1 | 0 | 4 | 10 |
| expense_report | 98.1% | 6.9% | 0 | 53 | 0 | 1 | 0 | 0 | 4 |
| income_statement | 100.0% | 30.6% | 0 | 25 | 0 | 0 | 0 | 0 | 11 |
| payslip | 94.3% | 16.0% | 0 | 66 | 0 | 2 | 0 | 2 | 13 |
| purchase_order | 96.8% | 34.0% | 0 | 30 | 1 | 0 | 0 | 0 | 16 |
| sales_invoice | 100.0% | 28.3% | 0 | 71 | 0 | 0 | 0 | 0 | 28 |

## By field type

| field type | accuracy | halluc. rate | invented | correct | near | renamed | wrong | missed | halluc. |
|---|---|---|---|---|---|---|---|---|---|
| date | 100.0% | 0.0% | 0 | 30 | 0 | 0 | 0 | 0 | 0 |
| money | 99.4% | 0.0% | 0 | 160 | 0 | 0 | 0 | 1 | 0 |
| number | 100.0% | 0.0% | 0 | 12 | 0 | 0 | 0 | 0 | 0 |
| string | 93.1% | 37.5% | 0 | 163 | 1 | 6 | 0 | 5 | 102 |

## Per document

| document | type | accuracy | raw | halluc. | invented | route | notes |
|---|---|---|---|---|---|---|---|
| BS-2024-Q1 | balance_sheet | 100.0% | 58.7% | 9 | 0 | BS-2024-Q1.pdf: file_type=digital_pdf pages=2 text_len=1242 |  |
| CHQ-001847 | cheque | 54.5% | 45.5% | 10 | 0 | CHQ-001847.pdf: file_type=digital_pdf pages=1 text_len=501 |  |
| EXP-2024-0081 | expense_report | 98.1% | 98.1% | 4 | 0 | EXP-2024-0081.pdf: file_type=digital_pdf pages=1 text_len=11 |  |
| INV-2024-0031 | sales_invoice | 100.0% | 84.8% | 15 | 0 | INV-2024-0031.pdf: file_type=digital_pdf pages=1 text_len=97 |  |
| INV-2024-0047 | sales_invoice | 100.0% | 97.4% | 13 | 0 | INV-2024-0047.pdf: file_type=digital_pdf pages=1 text_len=10 |  |
| IS-2024-Q4 | income_statement | 100.0% | 88.0% | 11 | 0 | IS-2024-Q4.pdf: file_type=digital_pdf pages=2 text_len=970 |  |
| PAYSLIP-EMP-0007-APR2024 | payslip | 94.6% | 89.2% | 6 | 0 | PAYSLIP-EMP-0007-APR2024.pdf: file_type=digital_pdf pages=2  |  |
| PAYSLIP-EMP-0012-APR2024 | payslip | 93.9% | 84.8% | 7 | 0 | PAYSLIP-EMP-0012-APR2024.pdf: file_type=digital_pdf pages=2  |  |
| PO-2024-0018 | purchase_order | 96.8% | 45.2% | 16 | 0 | PO-2024-0018.pdf: file_type=digital_pdf pages=1 text_len=104 |  |
| STMT-2024-01 | bank_statement | 97.1% | 97.1% | 11 | 0 | STMT-2024-01.pdf: file_type=digital_pdf pages=1 text_len=140 |  |

## Mismatches (everything not correct)

| document | field | outcome | expected | actual |
|---|---|---|---|---|
| BS-2024-Q1 | Company Name | hallucinated (misplaced) | None | Nexus Global Trading LLC |
| BS-2024-Q1 | Company Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| BS-2024-Q1 | Company City, State, Zip | hallucinated (misplaced) | None | New York, NY 10019 |
| BS-2024-Q1 | Company EIN | hallucinated (misplaced) | None | 47-3821654 |
| BS-2024-Q1 | Statement Date | hallucinated (misplaced) | None | March 31, 2024 |
| BS-2024-Q1 | Document Number | hallucinated (misplaced) | None | BS-2024-Q1 |
| BS-2024-Q1 | Common Stock Shares | hallucinated (misplaced) | None | 100 |
| BS-2024-Q1 | Common Stock Par Value | hallucinated (misplaced) | None | 1,000 |
| BS-2024-Q1 | Prepared by | hallucinated (misplaced) | None | Meridian & Associates CPA |
| CHQ-001847 | Payer Name | missed | Nexus Global Trading LLC | None |
| CHQ-001847 | Amount | missed | 8410.0 | None |
| CHQ-001847 | Authorized By | renamed | Janet Wu | Janet Wu |
| CHQ-001847 | Routing Number | missed | 021000021 | None |
| CHQ-001847 | Account Number | missed | 7743882201 | None |
| CHQ-001847 | Payee Street Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800 |
| CHQ-001847 | Payee City State Zip | hallucinated (misplaced) | None | New York, NY 10019 |
| CHQ-001847 | Payee EIN | hallucinated (misplaced) | None | 47-3821654 |
| CHQ-001847 | Payee Phone | hallucinated (misplaced) | None | (212) 555-0148 |
| CHQ-001847 | Payee Name | hallucinated (misplaced) | None | Janet Wu |
| CHQ-001847 | Payee Company | hallucinated (misplaced) | None | Pacific Steel & Metals Co. |
| CHQ-001847 | Bank Address | hallucinated (misplaced) | None | 330 Madison Ave, New York, NY 10017 |
| CHQ-001847 | Bank Member FDIC | hallucinated (misplaced) | None | Member FDIC |
| CHQ-001847 | MICR Line | hallucinated (misplaced) | None | A021000021A C7743882201C 001847D |
| CHQ-001847 | Non-Negotiable Copy | hallucinated (misplaced) | None | Non-Negotiable Copy |
| EXP-2024-0081 | Employee Name | renamed | Marcus A. Thompson | Marcus A. Thompson |
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
| INV-2024-0031 | Payment Instructions Wire Bank | hallucinated (misplaced) | None | First National Bank of New York |
| INV-2024-0031 | Payment Instructions Wire ABA | hallucinated (misplaced) | None | 021000021 |
| INV-2024-0031 | Payment Instructions Wire Account | hallucinated (misplaced) | None | 7743882201 |
| INV-2024-0031 | Payment Instructions Cheque Payable To | hallucinated (misplaced) | None | Nexus Global Trading LLC |
| INV-2024-0031 | Notes Payment Received Date | hallucinated (misplaced) | None | Feb 10, 2024 |
| INV-2024-0031 | Notes Payment Reference | hallucinated (misplaced) | None | WT-20240210-4421. |
| INV-2024-0031 | Contact Email | hallucinated (misplaced) | None | ar@nexusglobaltrading.com |
| INV-2024-0031 | Contact Phone | hallucinated (misplaced) | None | (212) 555-0148 |
| INV-2024-0047 | TOTAL DUE | hallucinated (misplaced) | None | $17,411.79 |
| INV-2024-0047 | Bill To Contact Email | hallucinated (misplaced) | None | sjohnson@pinnacleelec.com |
| INV-2024-0047 | Terms | hallucinated (misplaced) | None | Net 30 |
| INV-2024-0047 | Company Name | hallucinated (misplaced) | None | NEXUS GLOBAL TRADING LLC |
| INV-2024-0047 | Company Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| INV-2024-0047 | Company Phone | hallucinated (misplaced) | None | (212) 555-0148 |
| INV-2024-0047 | Company EIN | hallucinated (misplaced) | None | 47-3821654 |
| INV-2024-0047 | Payment Instructions Wire Bank | hallucinated (misplaced) | None | First National Bank of New York |
| INV-2024-0047 | Payment Instructions ABA | hallucinated (misplaced) | None | 021000021 |
| INV-2024-0047 | Payment Instructions Account | hallucinated (misplaced) | None | 7743882201 |
| INV-2024-0047 | Payment Instructions Cheque Payable To | hallucinated (misplaced) | None | Nexus Global Trading LLC |
| INV-2024-0047 | Notes Balance Due | hallucinated (misplaced) | None | Balance due March 4, 2024. |
| INV-2024-0047 | Notes Late Payment Interest | hallucinated (misplaced) | None | 1.5% |
| IS-2024-Q4 | GROSS PROFIT | hallucinated (misplaced) | None | $695,400 |
| IS-2024-Q4 | OPERATING INCOME (EBIT) | hallucinated (misplaced) | None | $336,150 |
| IS-2024-Q4 | Est. Income Tax Provision (21%) | hallucinated (misplaced) | None | $70,852 |
| IS-2024-Q4 | NET INCOME (LOSS) BEFORE TAX | hallucinated (misplaced) | None | $337,390 |
| IS-2024-Q4 | NET INCOME (LOSS) AFTER TAX | hallucinated (misplaced) | None | $266,538 |
| IS-2024-Q4 | Company Name | hallucinated (misplaced) | None | Nexus Global Trading LLC |
| IS-2024-Q4 | Company Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| IS-2024-Q4 | Company EIN | hallucinated (misplaced) | None | 47-3821654 |
| IS-2024-Q4 | Quarter Ended | hallucinated (misplaced) | None | Q4 2024 |
| IS-2024-Q4 | Document Number | hallucinated (misplaced) | None | IS-2024-Q4 |
| IS-2024-Q4 | Prepared by | hallucinated (misplaced) | None | Meridian & Associates CPA |
| PAYSLIP-EMP-0007-APR2024 | Employer Name | missed | Nexus Global Trading LLC | None |
| PAYSLIP-EMP-0007-APR2024 | Title / Department | renamed | VP Operations – Executive | VP Operations – Executive |
| PAYSLIP-EMP-0007-APR2024 | Earnings Total | hallucinated (misplaced) | None | $14,583.33 |
| PAYSLIP-EMP-0007-APR2024 | Deductions Total | hallucinated (misplaced) | None | ($7,070.30) |
| PAYSLIP-EMP-0007-APR2024 | NET PAY | hallucinated (misplaced) | None | $7,513.0 3 |
| PAYSLIP-EMP-0007-APR2024 | Company Name | hallucinated (misplaced) | None | NEXUS GLOBAL TRADING |
| PAYSLIP-EMP-0007-APR2024 | Company Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| PAYSLIP-EMP-0007-APR2024 | Company EIN | hallucinated (misplaced) | None | 47-3821654 |
| PAYSLIP-EMP-0012-APR2024 | Employer Name | missed | Nexus Global Trading LLC | None |
| PAYSLIP-EMP-0012-APR2024 | Title / Department | renamed | Purchasing Manager – Procurement | Purchasing Manager – Procurement |
| PAYSLIP-EMP-0012-APR2024 | NET PAY | hallucinated (misplaced) | None | $5,182.65 |
| PAYSLIP-EMP-0012-APR2024 | Earnings Total | hallucinated (misplaced) | None | $8,300.00 |
| PAYSLIP-EMP-0012-APR2024 | Deductions Total | hallucinated (misplaced) | None | ($3,117.35) |
| PAYSLIP-EMP-0012-APR2024 | Employee SSN | hallucinated (misplaced) | None | ***-**-4821 |
| PAYSLIP-EMP-0012-APR2024 | Company Name | hallucinated (misplaced) | None | NEXUS GLOBAL TRADING |
| PAYSLIP-EMP-0012-APR2024 | Company Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| PAYSLIP-EMP-0012-APR2024 | Company EIN | hallucinated (misplaced) | None | 47-3821654 |
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
| STMT-2024-01 | Statement No | renamed | STMT-2024-01 | STMT-2024-01 |
| STMT-2024-01 | Account No | renamed | ****7743 | ****7743 |
| STMT-2024-01 | Account Holder Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| STMT-2024-01 | Opening Balance Amount | hallucinated (misplaced) | None | $184,320.55 |
| STMT-2024-01 | Closing Balance Amount | hallucinated (misplaced) | None | $125,357.26 |
| STMT-2024-01 | Bank Address | hallucinated (misplaced) | None | 330 Madison Avenue, New York, NY 10017 |
| STMT-2024-01 | ABA Number | hallucinated (misplaced) | None | 021000021 |
| STMT-2024-01 | Member FDIC | hallucinated (misplaced) | None | Member FDIC |
| STMT-2024-01 | EIN | hallucinated (misplaced) | None | 47-3821654 |
| STMT-2024-01 | Credits Amount | hallucinated (misplaced) | None | $46,841.68 |
| STMT-2024-01 | Debits Amount | hallucinated (misplaced) | None | $105,804.97 |
| STMT-2024-01 | Customer Service Phone | hallucinated (misplaced) | None | (800) 555-0100 |
| STMT-2024-01 | Bank Website | hallucinated (misplaced) | None | fnbny.com |
