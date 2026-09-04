# Accuracy report — 2026-09-04 11:54:24

- git: `11f5c8b`  mode: **record**  repeat: 1
- config: {"PRIMARY_LLM": "gemini", "GEMINI_MODEL": "gemini-2.5-flash-lite"}

## Overall

| metric | value |
|---|---|
| **accuracy (correct / gold-valued)** | **98.2%** |
| **accuracy RAW (all adapter widenings off)** | **71.1%** |
| **accuracy CONTENT (container-blind)** | **97.1%** |
| **structure FIDELITY (gold tables returned as tables)** | **100.0%** (17/17; 14 with exact row count) |
| **hallucination rate (hallucinated / extracted)** | **14.3%** |
| **├ INVENTED — value found NOWHERE in the PDF** | **0** (0.0%) |
| ├ misfiled — real content in a slot gold says is EMPTY | 6 |
| └ out-of-schema — real content, name gold has no field for | 60 *(not a defect)* |
| **DEFECT RATE (invented + misfiled / extracted)** | **1.3%** |
| hallucinated values | 66 |
| near misses | 4 |
| **renamed (right value, different field name)** | **3** (0.8%) |
| outcome counts | {"correct": 387, "hallucinated": 66, "renamed": 3, "near": 4, "empty_ok": 12} |

## By document type

| document type | accuracy | halluc. rate | invented | correct | near | renamed | wrong | missed | halluc. |
|---|---|---|---|---|---|---|---|---|---|
| balance_sheet | 100.0% | 11.5% | 0 | 46 | 0 | 0 | 0 | 0 | 6 |
| bank_statement | 100.0% | 2.8% | 0 | 70 | 0 | 0 | 0 | 0 | 2 |
| cheque | 100.0% | 31.2% | 0 | 11 | 0 | 0 | 0 | 0 | 5 |
| expense_report | 98.1% | 11.5% | 0 | 53 | 0 | 1 | 0 | 0 | 7 |
| income_statement | 100.0% | 22.6% | 0 | 41 | 0 | 0 | 0 | 0 | 12 |
| payslip | 94.3% | 5.4% | 0 | 66 | 2 | 2 | 0 | 0 | 4 |
| purchase_order | 96.8% | 29.5% | 0 | 30 | 1 | 0 | 0 | 0 | 13 |
| sales_invoice | 98.6% | 19.3% | 0 | 70 | 1 | 0 | 0 | 0 | 17 |

## By field type

| field type | accuracy | halluc. rate | invented | correct | near | renamed | wrong | missed | halluc. |
|---|---|---|---|---|---|---|---|---|---|
| date | 100.0% | 0.0% | 0 | 30 | 0 | 0 | 0 | 0 | 0 |
| money | 100.0% | 1.8% | 0 | 161 | 0 | 0 | 0 | 0 | 3 |
| number | 100.0% | 0.0% | 0 | 12 | 0 | 0 | 0 | 0 | 0 |
| string | 96.3% | 24.8% | 0 | 184 | 4 | 3 | 0 | 0 | 63 |

## Per document

| document | type | accuracy | raw | halluc. | invented | route | notes |
|---|---|---|---|---|---|---|---|
| BS-2024-Q1 | balance_sheet | 100.0% | 58.7% | 6 | 0 | BS-2024-Q1.pdf: file_type=digital_pdf pages=2 text_len=1242 |  |
| CHQ-001847 | cheque | 100.0% | 90.9% | 5 | 0 | CHQ-001847.pdf: file_type=digital_pdf pages=1 text_len=501 |  |
| EXP-2024-0081 | expense_report | 98.1% | 98.1% | 7 | 0 | EXP-2024-0081.pdf: file_type=digital_pdf pages=1 text_len=11 |  |
| INV-2024-0031 | sales_invoice | 97.0% | 30.3% | 7 | 0 | INV-2024-0031.pdf: file_type=digital_pdf pages=1 text_len=97 |  |
| INV-2024-0047 | sales_invoice | 100.0% | 31.6% | 10 | 0 | INV-2024-0047.pdf: file_type=digital_pdf pages=1 text_len=10 |  |
| IS-2024-Q4 | income_statement | 100.0% | 51.2% | 12 | 0 | IS-2024-Q4.pdf: file_type=digital_pdf pages=2 text_len=970 |  |
| PAYSLIP-EMP-0007-APR2024 | payslip | 94.6% | 94.6% | 2 | 0 | PAYSLIP-EMP-0007-APR2024.pdf: file_type=digital_pdf pages=2  |  |
| PAYSLIP-EMP-0012-APR2024 | payslip | 93.9% | 93.9% | 2 | 0 | PAYSLIP-EMP-0012-APR2024.pdf: file_type=digital_pdf pages=2  |  |
| PO-2024-0018 | purchase_order | 96.8% | 45.2% | 13 | 0 | PO-2024-0018.pdf: file_type=digital_pdf pages=1 text_len=104 |  |
| STMT-2024-01 | bank_statement | 100.0% | 95.7% | 2 | 0 | STMT-2024-01.pdf: file_type=digital_pdf pages=1 text_len=140 |  |

## Mismatches (everything not correct)

| document | field | outcome | expected | actual |
|---|---|---|---|---|
| BS-2024-Q1 | Company Name | hallucinated (misplaced) | None | Nexus Global Trading LLC |
| BS-2024-Q1 | Company Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| BS-2024-Q1 | Company Identifier | hallucinated (misplaced) | None | 47-3821654 |
| BS-2024-Q1 | As of Date | hallucinated (misplaced) | None | March 31, 2024 |
| BS-2024-Q1 | Doc No | hallucinated (misplaced) | None | BS-2024-Q1 |
| BS-2024-Q1 | Prepared by | hallucinated (misplaced) | None | Meridian & Associates CPA |
| CHQ-001847 | Bank Address | hallucinated (misplaced) | None | 330 Madison Ave, New York, NY 10017 |
| CHQ-001847 | Drawer Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| CHQ-001847 | Drawer EIN | hallucinated (misplaced) | None | 47-3821654 |
| CHQ-001847 | Drawer Phone | hallucinated (misplaced) | None | (212) 555-0148 |
| CHQ-001847 | MICR Line | hallucinated (misplaced) | None | A021000021A C7743882201C 001847D |
| EXP-2024-0081 | Employee Name | renamed | Marcus A. Thompson | Marcus A. Thompson |
| EXP-2024-0081 | Manager Approval Signature | hallucinated (misplaced) | None | Janet Wu |
| EXP-2024-0081 | Company Name | hallucinated (misplaced) | None | NEXUS GLOBAL TRADING LLC |
| EXP-2024-0081 | Company Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| EXP-2024-0081 | Company Phone | hallucinated (misplaced) | None | (212) 555-0148 |
| EXP-2024-0081 | Company EIN | hallucinated (misplaced) | None | 47-3821654 |
| EXP-2024-0081 | Employee Signature | hallucinated (misplaced) | None | Marcus A. Thompson |
| EXP-2024-0081 | Finance Approval Signature | hallucinated (misplaced) | None | Finance Dept. |
| INV-2024-0031 | Bill To Contact | near | Mr. Robert Chen | Mr. Robert Chen — rchen@apexindustrial.com |
| INV-2024-0031 | Vendor Name | hallucinated (misplaced) | None | NEXUS GLOBAL TRADING LLC |
| INV-2024-0031 | Vendor Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| INV-2024-0031 | Vendor Phone | hallucinated (misplaced) | None | (212) 555-0148 |
| INV-2024-0031 | Vendor Tax ID | hallucinated (misplaced) | None | 47-3821654 |
| INV-2024-0031 | Payment Instructions Notes | hallucinated (misplaced) | None | Wire: First National Bank of New York Payment received via w |
| INV-2024-0031 | Payment Received Date | hallucinated (misplaced) | None | Feb 10, 2024 |
| INV-2024-0031 | Payment Reference | hallucinated (misplaced) | None | WT-20240210-4421. |
| INV-2024-0047 | Vendor Name | hallucinated (misplaced) | None | NEXUS GLOBAL TRADING LLC |
| INV-2024-0047 | Vendor Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| INV-2024-0047 | Vendor Phone | hallucinated (misplaced) | None | (212) 555-0148 |
| INV-2024-0047 | Vendor Tax ID | hallucinated (misplaced) | None | 47-3821654 |
| INV-2024-0047 | Bill To Email | hallucinated (misplaced) | None | sjohnson@pinnacleelec.com |
| INV-2024-0047 | Wire Bank Name | hallucinated (misplaced) | None | First National Bank of New York |
| INV-2024-0047 | Wire ABA | hallucinated (misplaced) | None | 021000021 |
| INV-2024-0047 | Wire Account Number | hallucinated (misplaced) | None | 7743882201 |
| INV-2024-0047 | Cheque Payable To | hallucinated (misplaced) | None | Nexus Global Trading LLC |
| INV-2024-0047 | Notes | hallucinated (misplaced) | None | Balance due March 4, 2024. Late payments subject to 1.5% mon |
| IS-2024-Q4 | Company Name | hallucinated (misplaced) | None | Nexus Global Trading LLC |
| IS-2024-Q4 | Company Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| IS-2024-Q4 | Company Identifier | hallucinated (misplaced) | None | 47-3821654 |
| IS-2024-Q4 | Period To | hallucinated (misplaced) | None | December 31, 2024 |
| IS-2024-Q4 | Doc No | hallucinated (misplaced) | None | IS-2024-Q4 |
| IS-2024-Q4 | Prepared by | hallucinated (misplaced) | None | Meridian & Associates CPA |
| IS-2024-Q4 | revenue[pred_row 2].Label | hallucinated (misplaced) | None | Net Revenue |
| IS-2024-Q4 | revenue[pred_row 2].Amount | hallucinated (misplaced) | None | $1,951,400 |
| IS-2024-Q4 | cost_of_goods_sold[pred_row 4].Label | hallucinated (misplaced) | None | Total COGS |
| IS-2024-Q4 | cost_of_goods_sold[pred_row 4].Amount | hallucinated (misplaced) | None | $1,256,000 |
| IS-2024-Q4 | operating_expenses[pred_row 10].Label | hallucinated (misplaced) | None | Total Operating Expenses |
| IS-2024-Q4 | operating_expenses[pred_row 10].Amount | hallucinated (misplaced) | None | $359,250 |
| PAYSLIP-EMP-0007-APR2024 | Employer Name | near | Nexus Global Trading LLC | NEXUS GLOBAL TRADING |
| PAYSLIP-EMP-0007-APR2024 | Title / Department | renamed | VP Operations – Executive | VP Operations – Executive |
| PAYSLIP-EMP-0007-APR2024 | Employer Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| PAYSLIP-EMP-0007-APR2024 | Employer EIN | hallucinated (misplaced) | None | 47-3821654 |
| PAYSLIP-EMP-0012-APR2024 | Employer Name | near | Nexus Global Trading LLC | NEXUS GLOBAL TRADING |
| PAYSLIP-EMP-0012-APR2024 | Title / Department | renamed | Purchasing Manager – Procurement | Purchasing Manager – Procurement |
| PAYSLIP-EMP-0012-APR2024 | Employer Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| PAYSLIP-EMP-0012-APR2024 | Employer EIN | hallucinated (misplaced) | None | 47-3821654 |
| PO-2024-0018 | Authorised By | near | Janet Wu – VP Operations | Janet Wu |
| PO-2024-0018 | Authorised By Title | hallucinated (misplaced) | None | VP Operations |
| PO-2024-0018 | Buyer Signature Name | hallucinated (misplaced) | None | Marcus A. Thompson |
| PO-2024-0018 | Buyer Signature Title | hallucinated (misplaced) | None | Purchasing Manager |
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
| STMT-2024-01 | ABA | hallucinated (misplaced) | None | 021000021 |

## Changes vs previous run

- PAYSLIP-EMP-0012-APR2024 :: Net Pay: wrong -> correct
