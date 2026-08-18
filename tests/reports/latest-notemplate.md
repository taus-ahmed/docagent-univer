# Accuracy report — 2026-08-18 03:39:13

- git: `c50b2b9`  mode: **record**  repeat: 1
- config: {"PRIMARY_LLM": "gemini", "GEMINI_MODEL": "gemini-2.5-flash-lite"}

## Overall

| metric | value |
|---|---|
| **accuracy (correct / gold-valued)** | **88.1%** |
| **accuracy RAW (all adapter widenings off)** | **68.5%** |
| **hallucination rate (hallucinated / extracted)** | **12.8%** |
| **└ invention rate (value found NOWHERE in the PDF)** | **0.0%** |
| └ misplacement (real content, slot gold leaves empty) | 11.5% |
| hallucinated values | 49 (invented 0, misplaced 49) |
| near misses | 0 |
| outcome counts | {"correct": 333, "hallucinated": 49, "missed": 45, "empty_ok": 12} |

## By document type

| document type | accuracy | halluc. rate | invented | correct | near | wrong | missed | halluc. |
|---|---|---|---|---|---|---|---|---|
| balance_sheet | 73.9% | 40.4% | 0 | 34 | 0 | 0 | 12 | 23 |
| bank_statement | 100.0% | 0.0% | 0 | 70 | 0 | 0 | 0 | 0 |
| cheque | 54.5% | 14.3% | 0 | 6 | 0 | 0 | 5 | 1 |
| expense_report | 96.3% | 1.9% | 0 | 52 | 0 | 0 | 2 | 1 |
| income_statement | 100.0% | 19.4% | 0 | 25 | 0 | 0 | 0 | 6 |
| payslip | 90.0% | 17.1% | 0 | 63 | 0 | 0 | 7 | 13 |
| purchase_order | 80.6% | 0.0% | 0 | 25 | 0 | 0 | 6 | 0 |
| sales_invoice | 81.7% | 7.9% | 0 | 58 | 0 | 0 | 13 | 5 |

## By field type

| field type | accuracy | halluc. rate | invented | correct | near | wrong | missed | halluc. |
|---|---|---|---|---|---|---|---|---|
| date | 86.7% | 0.0% | 0 | 26 | 0 | 0 | 4 | 0 |
| money | 94.4% | 5.6% | 0 | 152 | 0 | 0 | 9 | 9 |
| number | 100.0% | 0.0% | 0 | 12 | 0 | 0 | 0 | 0 |
| string | 81.7% | 21.9% | 0 | 143 | 0 | 0 | 32 | 40 |

## Per document

| document | type | accuracy | raw | halluc. | invented | route | notes |
|---|---|---|---|---|---|---|---|
| BS-2024-Q1 | balance_sheet | 73.9% | 17.4% | 23 | 0 | BS-2024-Q1.pdf: file_type=digital_pdf pages=2 text_len=1242 |  |
| CHQ-001847 | cheque | 54.5% | 45.5% | 1 | 0 | CHQ-001847.pdf: file_type=digital_pdf pages=1 text_len=501 |  |
| EXP-2024-0081 | expense_report | 96.3% | 96.3% | 1 | 0 | EXP-2024-0081.pdf: file_type=digital_pdf pages=1 text_len=11 |  |
| INV-2024-0031 | sales_invoice | 78.8% | 69.7% | 3 | 0 | INV-2024-0031.pdf: file_type=digital_pdf pages=1 text_len=97 |  |
| INV-2024-0047 | sales_invoice | 84.2% | 76.3% | 2 | 0 | INV-2024-0047.pdf: file_type=digital_pdf pages=1 text_len=10 |  |
| IS-2024-Q4 | income_statement | 100.0% | 12.0% | 6 | 0 | IS-2024-Q4.pdf: file_type=digital_pdf pages=2 text_len=970 |  |
| PAYSLIP-EMP-0007-APR2024 | payslip | 86.5% | 86.5% | 5 | 0 | PAYSLIP-EMP-0007-APR2024.pdf: file_type=digital_pdf pages=2  |  |
| PAYSLIP-EMP-0012-APR2024 | payslip | 93.9% | 93.9% | 8 | 0 | PAYSLIP-EMP-0012-APR2024.pdf: file_type=digital_pdf pages=2  |  |
| PO-2024-0018 | purchase_order | 80.6% | 29.0% | 0 | 0 | PO-2024-0018.pdf: file_type=digital_pdf pages=1 text_len=104 |  |
| STMT-2024-01 | bank_statement | 100.0% | 95.7% | 0 | 0 | STMT-2024-01.pdf: file_type=digital_pdf pages=1 text_len=140 |  |

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
| EXP-2024-0081 | Employee Name | missed | Marcus A. Thompson | None |
| EXP-2024-0081 | Status | missed | APPROVED | None |
| EXP-2024-0081 | Employee | hallucinated (misplaced) | None | Marcus A. Thompson |
| INV-2024-0031 | Invoice Number | missed | INV-2024-0031 | None |
| INV-2024-0031 | Invoice Date | missed | 2024-01-15 | None |
| INV-2024-0031 | Due Date | missed | 2024-02-14 | None |
| INV-2024-0031 | Bill To Company | missed | Apex Industrial Supplies Inc. | None |
| INV-2024-0031 | Bill To Address | missed | 500 Commerce Drive, Chicago, IL 60601 | None |
| INV-2024-0031 | Bill To Contact | missed | Mr. Robert Chen | None |
| INV-2024-0031 | Status | missed | PAID | None |
| INV-2024-0031 | Invoice | hallucinated (misplaced) | None | INV-2024-0031 |
| INV-2024-0031 | Date | hallucinated (misplaced) | None | January 15, 2024 |
| INV-2024-0031 | Due | hallucinated (misplaced) | None | February 14, 2024 |
| INV-2024-0047 | Invoice Date | missed | 2024-02-03 | None |
| INV-2024-0047 | Due Date | missed | 2024-03-04 | None |
| INV-2024-0047 | Bill To Company | missed | Pinnacle Electronics Corp. | None |
| INV-2024-0047 | Bill To Address | missed | 3800 Tech Boulevard Floor 5, Austin, TX 78701 | None |
| INV-2024-0047 | Bill To Contact | missed | Ms. Sarah Johnson | None |
| INV-2024-0047 | Status | missed | OUTSTANDING | None |
| INV-2024-0047 | Date | hallucinated (misplaced) | None | February 3, 2024 |
| INV-2024-0047 | Due | hallucinated (misplaced) | None | March 4, 2024 |
| IS-2024-Q4 | Company Name | hallucinated (misplaced) | None | Nexus Global Trading LLC |
| IS-2024-Q4 | Company Address | hallucinated (misplaced) | None | 142 West 57th Street, Suite 1800, New York, NY 10019 |
| IS-2024-Q4 | Company EIN | hallucinated (misplaced) | None | 47-3821654 |
| IS-2024-Q4 | Period | hallucinated (misplaced) | None | Q4 2024 |
| IS-2024-Q4 | Date | hallucinated (misplaced) | None | December 31, 2024 |
| IS-2024-Q4 | Document Number | hallucinated (misplaced) | None | IS-2024-Q4 |
| PAYSLIP-EMP-0007-APR2024 | Employer Name | missed | Nexus Global Trading LLC | None |
| PAYSLIP-EMP-0007-APR2024 | Employee Name | missed | Janet L. Wu | None |
| PAYSLIP-EMP-0007-APR2024 | Title / Department | missed | VP Operations – Executive | None |
| PAYSLIP-EMP-0007-APR2024 | Total Earnings | missed | 14583.33 | None |
| PAYSLIP-EMP-0007-APR2024 | Total Deductions | missed | -7070.3 | None |
| PAYSLIP-EMP-0007-APR2024 | Employee | hallucinated (misplaced) | None | Janet L. Wu |
| PAYSLIP-EMP-0007-APR2024 | Title / Dept | hallucinated (misplaced) | None | VP Operations – Executive |
| PAYSLIP-EMP-0007-APR2024 | Total | hallucinated (misplaced) | None | $7,070.30 |
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
