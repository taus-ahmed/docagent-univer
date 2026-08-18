# Accuracy report — 2026-08-18 02:48:16

- git: `2533afc`  mode: **replay**  repeat: 1
- config: {"PRIMARY_LLM": "gemini", "GEMINI_MODEL": "gemini-2.5-flash-lite"}

## Overall

| metric | value |
|---|---|
| **accuracy (correct / gold-valued)** | **89.9%** |
| **hallucination rate (hallucinated / extracted)** | **10.7%** |
| **└ invention rate (value found NOWHERE in the PDF)** | **0.0%** |
| └ misplacement (real content, slot gold leaves empty) | 9.8% |
| hallucinated values | 41 (invented 0, misplaced 41) |
| near misses | 0 |
| outcome counts | {"correct": 340, "hallucinated": 41, "missed": 37, "wrong": 1, "empty_ok": 12} |

## By document type

| document type | accuracy | halluc. rate | invented | correct | near | wrong | missed | halluc. |
|---|---|---|---|---|---|---|---|---|
| balance_sheet | 73.9% | 40.4% | 0 | 34 | 0 | 0 | 12 | 23 |
| bank_statement | 100.0% | 0.0% | 0 | 70 | 0 | 0 | 0 | 0 |
| cheque | 54.5% | 14.3% | 0 | 6 | 0 | 0 | 5 | 1 |
| expense_report | 98.1% | 0.0% | 0 | 53 | 0 | 0 | 1 | 0 |
| income_statement | 100.0% | 19.4% | 0 | 25 | 0 | 0 | 0 | 6 |
| payslip | 91.4% | 14.5% | 0 | 64 | 0 | 1 | 5 | 11 |
| purchase_order | 80.6% | 0.0% | 0 | 25 | 0 | 0 | 6 | 0 |
| sales_invoice | 88.7% | 0.0% | 0 | 63 | 0 | 0 | 8 | 0 |

## By field type

| field type | accuracy | halluc. rate | invented | correct | near | wrong | missed | halluc. |
|---|---|---|---|---|---|---|---|---|
| date | 100.0% | 0.0% | 0 | 30 | 0 | 0 | 0 | 0 |
| money | 94.4% | 5.6% | 0 | 152 | 0 | 1 | 8 | 9 |
| number | 100.0% | 0.0% | 0 | 12 | 0 | 0 | 0 | 0 |
| string | 83.4% | 18.0% | 0 | 146 | 0 | 0 | 29 | 32 |

## Per document

| document | type | accuracy | halluc. | invented | route | notes |
|---|---|---|---|---|---|---|
| BS-2024-Q1 | balance_sheet | 73.9% | 23 | 0 | BS-2024-Q1.pdf: file_type=digital_pdf pages=2 text_len=1242 |  |
| CHQ-001847 | cheque | 54.5% | 1 | 0 | CHQ-001847.pdf: file_type=digital_pdf pages=1 text_len=501 |  |
| EXP-2024-0081 | expense_report | 98.1% | 0 | 0 | EXP-2024-0081.pdf: file_type=digital_pdf pages=1 text_len=11 |  |
| INV-2024-0031 | sales_invoice | 87.9% | 0 | 0 | INV-2024-0031.pdf: file_type=digital_pdf pages=1 text_len=97 |  |
| INV-2024-0047 | sales_invoice | 89.5% | 0 | 0 | INV-2024-0047.pdf: file_type=digital_pdf pages=1 text_len=10 |  |
| IS-2024-Q4 | income_statement | 100.0% | 6 | 0 | IS-2024-Q4.pdf: file_type=digital_pdf pages=2 text_len=970 |  |
| PAYSLIP-EMP-0007-APR2024 | payslip | 89.2% | 3 | 0 | PAYSLIP-EMP-0007-APR2024.pdf: file_type=digital_pdf pages=2  |  |
| PAYSLIP-EMP-0012-APR2024 | payslip | 93.9% | 8 | 0 | PAYSLIP-EMP-0012-APR2024.pdf: file_type=digital_pdf pages=2  |  |
| PO-2024-0018 | purchase_order | 80.6% | 0 | 0 | PO-2024-0018.pdf: file_type=digital_pdf pages=1 text_len=104 |  |
| STMT-2024-01 | bank_statement | 100.0% | 0 | 0 | STMT-2024-01.pdf: file_type=digital_pdf pages=1 text_len=140 |  |

## Mismatches (everything not correct)

| document | field | outcome | expected | actual |
|---|---|---|---|---|
| BS-2024-Q1 | Company Name | hallucinated (misplaced) | None | Nexus Global Trading LLC |
| BS-2024-Q1 | Company Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| BS-2024-Q1 | Company EIN | hallucinated (misplaced) | None | 47-3821654 |
| BS-2024-Q1 | Period | hallucinated (misplaced) | None | Q1 2024 |
| BS-2024-Q1 | As of Date | hallucinated (misplaced) | None | March 31, 2024 |
| BS-2024-Q1 | Document Number | hallucinated (misplaced) | None | BS-2024-Q1 |
| BS-2024-Q1 | current_assets[pred_row 0].Label | hallucinated (misplaced) | None | CURRENT ASSETS |
| BS-2024-Q1 | current_assets[pred_row 6].Label | hallucinated (misplaced) | None | NON-CURRENT ASSETS |
| BS-2024-Q1 | current_assets[pred_row 7].Label | hallucinated (misplaced) | None | Property & Equipment (gross) |
| BS-2024-Q1 | current_assets[pred_row 7].Amount | hallucinated (misplaced) | None | $240,000 |
| BS-2024-Q1 | current_assets[pred_row 8].Label | hallucinated (misplaced) | None | Less: Accum. Depreciation |
| BS-2024-Q1 | current_assets[pred_row 8].Amount | hallucinated (misplaced) | None | $108,500 |
| BS-2024-Q1 | current_assets[pred_row 9].Label | hallucinated (misplaced) | None | Security Deposits |
| BS-2024-Q1 | current_assets[pred_row 9].Amount | hallucinated (misplaced) | None | $85,000 |
| BS-2024-Q1 | current_assets[pred_row 10].Label | hallucinated (misplaced) | None | Intangibles (net) |
| BS-2024-Q1 | current_assets[pred_row 10].Amount | hallucinated (misplaced) | None | $20,000 |
| BS-2024-Q1 | non_current_assets[row 0].Label | missed | Property & Equipment (gross) | None |
| BS-2024-Q1 | non_current_assets[row 0].Amount | missed | 240000 | None |
| BS-2024-Q1 | non_current_assets[row 1].Label | missed | Less: Accum. Depreciation | None |
| BS-2024-Q1 | non_current_assets[row 1].Amount | missed | 108500 | None |
| BS-2024-Q1 | non_current_assets[row 2].Label | missed | Security Deposits | None |
| BS-2024-Q1 | non_current_assets[row 2].Amount | missed | 85000 | None |
| BS-2024-Q1 | non_current_assets[row 3].Label | missed | Intangibles (net) | None |
| BS-2024-Q1 | non_current_assets[row 3].Amount | missed | 20000 | None |
| BS-2024-Q1 | current_liabilities[pred_row 0].Label | hallucinated (misplaced) | None | CURRENT LIABILITIES |
| BS-2024-Q1 | current_liabilities[pred_row 6].Label | hallucinated (misplaced) | None | LONG-TERM LIABILITIES |
| BS-2024-Q1 | current_liabilities[pred_row 7].Label | hallucinated (misplaced) | None | Long-term Loan — First National Bank |
| BS-2024-Q1 | current_liabilities[pred_row 7].Amount | hallucinated (misplaced) | None | $121,000 |
| BS-2024-Q1 | current_liabilities[pred_row 8].Label | hallucinated (misplaced) | None | Deferred Tax Liability |
| BS-2024-Q1 | current_liabilities[pred_row 8].Amount | hallucinated (misplaced) | None | $8,400 |
| BS-2024-Q1 | long_term_liabilities[row 0].Label | missed | Long-term Loan – First National Bank | None |
| BS-2024-Q1 | long_term_liabilities[row 0].Amount | missed | 121000 | None |
| BS-2024-Q1 | long_term_liabilities[row 1].Label | missed | Deferred Tax Liability | None |
| BS-2024-Q1 | long_term_liabilities[row 1].Amount | missed | 8400 | None |
| BS-2024-Q1 | shareholders_equity[pred_row 0].Label | hallucinated (misplaced) | None | SHAREHOLDERS' EQUITY |
| CHQ-001847 | Payer Name | missed | Nexus Global Trading LLC | None |
| CHQ-001847 | Amount | missed | 8410.0 | None |
| CHQ-001847 | Authorized By | missed | Janet Wu | None |
| CHQ-001847 | Routing Number | missed | 021000021 | None |
| CHQ-001847 | Account Number | missed | 7743882201 | None |
| CHQ-001847 | Authorized Signature | hallucinated (misplaced) | None | Janet Wu |
| EXP-2024-0081 | Status | missed | APPROVED | None |
| INV-2024-0031 | Bill To Company | missed | Apex Industrial Supplies Inc. | None |
| INV-2024-0031 | Bill To Address | missed | 500 Commerce Drive, Chicago, IL 60601 | None |
| INV-2024-0031 | Bill To Contact | missed | Mr. Robert Chen | None |
| INV-2024-0031 | Status | missed | PAID | None |
| INV-2024-0047 | Bill To Company | missed | Pinnacle Electronics Corp. | None |
| INV-2024-0047 | Bill To Address | missed | 3800 Tech Boulevard Floor 5, Austin, TX 78701 | None |
| INV-2024-0047 | Bill To Contact | missed | Ms. Sarah Johnson | None |
| INV-2024-0047 | Status | missed | OUTSTANDING | None |
| IS-2024-Q4 | Company Name | hallucinated (misplaced) | None | Nexus Global Trading LLC |
| IS-2024-Q4 | Company Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| IS-2024-Q4 | Company EIN | hallucinated (misplaced) | None | 47-3821654 |
| IS-2024-Q4 | Period | hallucinated (misplaced) | None | Q4 2024 |
| IS-2024-Q4 | Date | hallucinated (misplaced) | None | December 31, 2024 |
| IS-2024-Q4 | Document Number | hallucinated (misplaced) | None | IS-2024-Q4 |
| PAYSLIP-EMP-0007-APR2024 | Employer Name | missed | Nexus Global Trading LLC | None |
| PAYSLIP-EMP-0007-APR2024 | Title / Department | missed | VP Operations – Executive | None |
| PAYSLIP-EMP-0007-APR2024 | Total Earnings | wrong | 14583.33 | $7,070.30 |
| PAYSLIP-EMP-0007-APR2024 | Total Deductions | missed | -7070.3 | None |
| PAYSLIP-EMP-0007-APR2024 | Title / Dept | hallucinated (misplaced) | None | VP Operations – Executive |
| PAYSLIP-EMP-0007-APR2024 | earnings[pred_row 3].Description | hallucinated (misplaced) | None | Total |
| PAYSLIP-EMP-0007-APR2024 | earnings[pred_row 3].Amount | hallucinated (misplaced) | None | $14,583.33 |
| PAYSLIP-EMP-0012-APR2024 | Employer Name | missed | Nexus Global Trading LLC | None |
| PAYSLIP-EMP-0012-APR2024 | Title / Department | missed | Purchasing Manager – Procurement | None |
| PAYSLIP-EMP-0012-APR2024 | Company Name | hallucinated (misplaced) | None | NEXUS GLOBAL TRADING |
| PAYSLIP-EMP-0012-APR2024 | Company Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| PAYSLIP-EMP-0012-APR2024 | Company EIN | hallucinated (misplaced) | None | 47-3821654 |
| PAYSLIP-EMP-0012-APR2024 | Title / Dept | hallucinated (misplaced) | None | Purchasing Manager – Procurement |
| PAYSLIP-EMP-0012-APR2024 | earnings[pred_row 2].Description | hallucinated (misplaced) | None | Total |
| PAYSLIP-EMP-0012-APR2024 | earnings[pred_row 2].Amount | hallucinated (misplaced) | None | $8,300.00 |
| PAYSLIP-EMP-0012-APR2024 | deductions[pred_row 8].Description | hallucinated (misplaced) | None | Total |
| PAYSLIP-EMP-0012-APR2024 | deductions[pred_row 8].Amount | hallucinated (misplaced) | None | ($3,117.35) |
| PO-2024-0018 | Vendor Name | missed | Pacific Steel & Metals Co. | None |
| PO-2024-0018 | Vendor Address | missed | 2200 Harbor Drive, Los Angeles, CA 90021 | None |
| PO-2024-0018 | Vendor Contact | missed | Ms. Linda Zhao | None |
| PO-2024-0018 | Buyer Name | missed | Marcus A. Thompson | None |
| PO-2024-0018 | Buyer Title | missed | Purchasing Manager | None |
| PO-2024-0018 | Authorised By | missed | Janet Wu – VP Operations | None |
