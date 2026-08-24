# Accuracy report — 2026-08-23 20:35:43

- git: `3992034`  mode: **record**  repeat: 1
- config: {"PRIMARY_LLM": "gemini", "GEMINI_MODEL": "gemini-2.5-flash-lite"}

## Overall

| metric | value |
|---|---|
| **accuracy (correct / gold-valued)** | **98.0%** |
| **accuracy RAW (all adapter widenings off)** | **70.8%** |
| **accuracy CONTENT (container-blind)** | **96.7%** |
| **structure FIDELITY (gold tables returned as tables)** | **100.0%** (17/17; 14 with exact row count) |
| **hallucination rate (hallucinated / extracted)** | **14.3%** |
| **├ INVENTED — value found NOWHERE in the PDF** | **0** (0.0%) |
| ├ misfiled — real content in a slot gold says is EMPTY | 6 |
| └ out-of-schema — real content, name gold has no field for | 60 *(not a defect)* |
| **DEFECT RATE (invented + misfiled / extracted)** | **1.3%** |
| hallucinated values | 66 |
| near misses | 4 |
| **renamed (right value, different field name)** | **3** (0.8%) |
| outcome counts | {"correct": 386, "hallucinated": 66, "renamed": 3, "near": 4, "wrong": 1, "empty_ok": 12} |

## By document type

| document type | accuracy | halluc. rate | invented | correct | near | renamed | wrong | missed | halluc. |
|---|---|---|---|---|---|---|---|---|---|
| balance_sheet | 100.0% | 11.5% | 0 | 46 | 0 | 0 | 0 | 0 | 6 |
| bank_statement | 100.0% | 2.8% | 0 | 70 | 0 | 0 | 0 | 0 | 2 |
| cheque | 100.0% | 31.2% | 0 | 11 | 0 | 0 | 0 | 0 | 5 |
| expense_report | 98.1% | 11.5% | 0 | 53 | 0 | 1 | 0 | 0 | 7 |
| income_statement | 100.0% | 22.6% | 0 | 41 | 0 | 0 | 0 | 0 | 12 |
| payslip | 92.9% | 5.4% | 0 | 65 | 2 | 2 | 1 | 0 | 4 |
| purchase_order | 96.8% | 29.5% | 0 | 30 | 1 | 0 | 0 | 0 | 13 |
| sales_invoice | 98.6% | 19.3% | 0 | 70 | 1 | 0 | 0 | 0 | 17 |

## By field type

| field type | accuracy | halluc. rate | invented | correct | near | renamed | wrong | missed | halluc. |
|---|---|---|---|---|---|---|---|---|---|
| date | 100.0% | 0.0% | 0 | 30 | 0 | 0 | 0 | 0 | 0 |
| money | 99.4% | 1.8% | 0 | 160 | 0 | 0 | 1 | 0 | 3 |
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
| PAYSLIP-EMP-0012-APR2024 | payslip | 90.9% | 90.9% | 2 | 0 | PAYSLIP-EMP-0012-APR2024.pdf: file_type=digital_pdf pages=2  |  |
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
| PAYSLIP-EMP-0012-APR2024 | Net Pay | wrong | 5182.65 | $5,182.6 |
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

- BS-2024-Q1 :: As of Date: None -> hallucinated
- BS-2024-Q1 :: Company Address: None -> hallucinated
- BS-2024-Q1 :: Company Identifier: None -> hallucinated
- BS-2024-Q1 :: Company Name: None -> hallucinated
- BS-2024-Q1 :: Doc No: None -> hallucinated
- BS-2024-Q1 :: Prepared by: None -> hallucinated
- BS-2024-Q1 :: TOTAL ASSETS: None -> correct
- BS-2024-Q1 :: TOTAL LIABILITIES: None -> correct
- BS-2024-Q1 :: TOTAL LIABILITIES & EQUITY: None -> correct
- BS-2024-Q1 :: Total Current Assets: None -> correct
- BS-2024-Q1 :: Total Current Liabilities: None -> correct
- BS-2024-Q1 :: Total Equity: None -> correct
- BS-2024-Q1 :: Total Long-Term Liabilities: None -> correct
- BS-2024-Q1 :: Total Non-Current Assets: None -> correct
- BS-2024-Q1 :: current_assets :: row_count_mismatch: None -> 0
- BS-2024-Q1 :: current_assets[row 0].Amount: None -> correct
- BS-2024-Q1 :: current_assets[row 0].Label: None -> correct
- BS-2024-Q1 :: current_assets[row 1].Amount: None -> correct
- BS-2024-Q1 :: current_assets[row 1].Label: None -> correct
- BS-2024-Q1 :: current_assets[row 2].Amount: None -> correct
- BS-2024-Q1 :: current_assets[row 2].Label: None -> correct
- BS-2024-Q1 :: current_assets[row 3].Amount: None -> correct
- BS-2024-Q1 :: current_assets[row 3].Label: None -> correct
- BS-2024-Q1 :: current_assets[row 4].Amount: None -> correct
- BS-2024-Q1 :: current_assets[row 4].Label: None -> correct
- BS-2024-Q1 :: current_liabilities :: row_count_mismatch: None -> 0
- BS-2024-Q1 :: current_liabilities[row 0].Amount: None -> correct
- BS-2024-Q1 :: current_liabilities[row 0].Label: None -> correct
- BS-2024-Q1 :: current_liabilities[row 1].Amount: None -> correct
- BS-2024-Q1 :: current_liabilities[row 1].Label: None -> correct
- BS-2024-Q1 :: current_liabilities[row 2].Amount: None -> correct
- BS-2024-Q1 :: current_liabilities[row 2].Label: None -> correct
- BS-2024-Q1 :: current_liabilities[row 3].Amount: None -> correct
- BS-2024-Q1 :: current_liabilities[row 3].Label: None -> correct
- BS-2024-Q1 :: current_liabilities[row 4].Amount: None -> correct
- BS-2024-Q1 :: current_liabilities[row 4].Label: None -> correct
- BS-2024-Q1 :: long_term_liabilities :: row_count_mismatch: None -> 0
- BS-2024-Q1 :: long_term_liabilities[row 0].Amount: None -> correct
- BS-2024-Q1 :: long_term_liabilities[row 0].Label: None -> correct
- BS-2024-Q1 :: long_term_liabilities[row 1].Amount: None -> correct
- BS-2024-Q1 :: long_term_liabilities[row 1].Label: None -> correct
- BS-2024-Q1 :: non_current_assets :: row_count_mismatch: None -> 0
- BS-2024-Q1 :: non_current_assets[row 0].Amount: None -> correct
- BS-2024-Q1 :: non_current_assets[row 0].Label: None -> correct
- BS-2024-Q1 :: non_current_assets[row 1].Amount: None -> correct
- BS-2024-Q1 :: non_current_assets[row 1].Label: None -> correct
- BS-2024-Q1 :: non_current_assets[row 2].Amount: None -> correct
- BS-2024-Q1 :: non_current_assets[row 2].Label: None -> correct
- BS-2024-Q1 :: non_current_assets[row 3].Amount: None -> correct
- BS-2024-Q1 :: non_current_assets[row 3].Label: None -> correct
- BS-2024-Q1 :: shareholders_equity :: row_count_mismatch: None -> 0
- BS-2024-Q1 :: shareholders_equity[row 0].Amount: None -> correct
- BS-2024-Q1 :: shareholders_equity[row 0].Label: None -> correct
- BS-2024-Q1 :: shareholders_equity[row 1].Amount: None -> correct
- BS-2024-Q1 :: shareholders_equity[row 1].Label: None -> correct
- BS-2024-Q1 :: shareholders_equity[row 2].Amount: None -> correct
- BS-2024-Q1 :: shareholders_equity[row 2].Label: None -> correct
- EXP-2024-0081 :: Company Address: None -> hallucinated
- EXP-2024-0081 :: Company EIN: None -> hallucinated
- EXP-2024-0081 :: Company Name: None -> hallucinated
- EXP-2024-0081 :: Company Phone: None -> hallucinated
- EXP-2024-0081 :: Department: None -> correct
- EXP-2024-0081 :: Employee ID: None -> correct
- EXP-2024-0081 :: Employee Name: None -> renamed
- EXP-2024-0081 :: Employee Signature: None -> hallucinated
- EXP-2024-0081 :: Finance Approval Signature: None -> hallucinated
- EXP-2024-0081 :: Manager: None -> correct
- EXP-2024-0081 :: Manager Approval Signature: None -> hallucinated
- EXP-2024-0081 :: Period: None -> correct
- EXP-2024-0081 :: Purpose: None -> correct
- EXP-2024-0081 :: Report No: None -> correct
- EXP-2024-0081 :: Status: None -> correct
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
- INV-2024-0031 :: Bill To Contact: None -> near
- INV-2024-0031 :: Due Date: None -> correct
- INV-2024-0031 :: Invoice Date: None -> correct
- INV-2024-0031 :: Invoice Number: None -> correct
- INV-2024-0031 :: PO Reference: None -> correct
- INV-2024-0031 :: Payment Instructions Notes: None -> hallucinated
- INV-2024-0031 :: Payment Received Date: None -> hallucinated
- INV-2024-0031 :: Payment Reference: None -> hallucinated
- INV-2024-0031 :: Payment Terms: None -> correct
- INV-2024-0031 :: Sales Tax: None -> correct
- INV-2024-0031 :: Shipping & Handling: None -> correct
- INV-2024-0031 :: Status: None -> correct
- INV-2024-0031 :: Subtotal: None -> correct
- INV-2024-0031 :: Total Due: None -> correct
- INV-2024-0031 :: Vendor Address: None -> hallucinated
- INV-2024-0031 :: Vendor Name: None -> hallucinated
- INV-2024-0031 :: Vendor Phone: None -> hallucinated
- INV-2024-0031 :: Vendor Tax ID: None -> hallucinated
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
- INV-2024-0047 :: Cheque Payable To: None -> hallucinated
- INV-2024-0047 :: Due Date: None -> correct
- INV-2024-0047 :: Invoice Date: None -> correct
- INV-2024-0047 :: Invoice Number: None -> correct
- INV-2024-0047 :: Notes: None -> hallucinated
- INV-2024-0047 :: PO Reference: None -> correct
- INV-2024-0047 :: Payment Terms: None -> correct
- INV-2024-0047 :: Sales Tax: None -> correct
- INV-2024-0047 :: Shipping & Handling: None -> correct
- INV-2024-0047 :: Status: None -> correct
- INV-2024-0047 :: Subtotal: None -> correct
- INV-2024-0047 :: Total Due: None -> correct
- INV-2024-0047 :: Vendor Address: None -> hallucinated
- INV-2024-0047 :: Vendor Name: None -> hallucinated
- INV-2024-0047 :: Vendor Phone: None -> hallucinated
- INV-2024-0047 :: Vendor Tax ID: None -> hallucinated
- INV-2024-0047 :: Wire ABA: None -> hallucinated
- INV-2024-0047 :: Wire Account Number: None -> hallucinated
- INV-2024-0047 :: Wire Bank Name: None -> hallucinated
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
- IS-2024-Q4 :: Company Address: None -> hallucinated
- IS-2024-Q4 :: Company Identifier: None -> hallucinated
- IS-2024-Q4 :: Company Name: None -> hallucinated
- IS-2024-Q4 :: Doc No: None -> hallucinated
- IS-2024-Q4 :: Gross Profit: None -> correct
- IS-2024-Q4 :: Income Tax Provision: None -> correct
- IS-2024-Q4 :: Interest Income: None -> correct
- IS-2024-Q4 :: Net Income After Tax: None -> correct
- IS-2024-Q4 :: Net Income Before Tax: None -> correct
- IS-2024-Q4 :: Net Revenue: None -> correct
- IS-2024-Q4 :: Operating Income (EBIT): None -> correct
- IS-2024-Q4 :: Period To: None -> hallucinated
- IS-2024-Q4 :: Prepared by: None -> hallucinated
- IS-2024-Q4 :: Total COGS: None -> correct
- IS-2024-Q4 :: Total Operating Expenses: None -> correct
- IS-2024-Q4 :: cost_of_goods_sold :: row_count_mismatch: None -> 1
- IS-2024-Q4 :: cost_of_goods_sold[pred_row 4].Amount: None -> hallucinated
- IS-2024-Q4 :: cost_of_goods_sold[pred_row 4].Label: None -> hallucinated
- IS-2024-Q4 :: cost_of_goods_sold[row 0].Amount: None -> correct
- IS-2024-Q4 :: cost_of_goods_sold[row 0].Label: None -> correct
- IS-2024-Q4 :: cost_of_goods_sold[row 1].Amount: None -> correct
- IS-2024-Q4 :: cost_of_goods_sold[row 1].Label: None -> correct
- IS-2024-Q4 :: cost_of_goods_sold[row 2].Amount: None -> correct
- IS-2024-Q4 :: cost_of_goods_sold[row 2].Label: None -> correct
- IS-2024-Q4 :: cost_of_goods_sold[row 3].Amount: None -> correct
- IS-2024-Q4 :: cost_of_goods_sold[row 3].Label: None -> correct
- IS-2024-Q4 :: operating_expenses :: row_count_mismatch: None -> 1
- IS-2024-Q4 :: operating_expenses[pred_row 10].Amount: None -> hallucinated
- IS-2024-Q4 :: operating_expenses[pred_row 10].Label: None -> hallucinated
- IS-2024-Q4 :: operating_expenses[row 0].Amount: None -> correct
- IS-2024-Q4 :: operating_expenses[row 0].Label: None -> correct
- IS-2024-Q4 :: operating_expenses[row 1].Amount: None -> correct
- IS-2024-Q4 :: operating_expenses[row 1].Label: None -> correct
- IS-2024-Q4 :: operating_expenses[row 2].Amount: None -> correct
- IS-2024-Q4 :: operating_expenses[row 2].Label: None -> correct
- IS-2024-Q4 :: operating_expenses[row 3].Amount: None -> correct
- IS-2024-Q4 :: operating_expenses[row 3].Label: None -> correct
- IS-2024-Q4 :: operating_expenses[row 4].Amount: None -> correct
- IS-2024-Q4 :: operating_expenses[row 4].Label: None -> correct
- IS-2024-Q4 :: operating_expenses[row 5].Amount: None -> correct
- IS-2024-Q4 :: operating_expenses[row 5].Label: None -> correct
- IS-2024-Q4 :: operating_expenses[row 6].Amount: None -> correct
- IS-2024-Q4 :: operating_expenses[row 6].Label: None -> correct
- IS-2024-Q4 :: operating_expenses[row 7].Amount: None -> correct
- IS-2024-Q4 :: operating_expenses[row 7].Label: None -> correct
- IS-2024-Q4 :: operating_expenses[row 8].Amount: None -> correct
- IS-2024-Q4 :: operating_expenses[row 8].Label: None -> correct
- IS-2024-Q4 :: operating_expenses[row 9].Amount: None -> correct
- IS-2024-Q4 :: operating_expenses[row 9].Label: None -> correct
- IS-2024-Q4 :: revenue :: row_count_mismatch: None -> 1
- IS-2024-Q4 :: revenue[pred_row 2].Amount: None -> hallucinated
- IS-2024-Q4 :: revenue[pred_row 2].Label: None -> hallucinated
- IS-2024-Q4 :: revenue[row 0].Amount: None -> correct
- IS-2024-Q4 :: revenue[row 0].Label: None -> correct
- IS-2024-Q4 :: revenue[row 1].Amount: None -> correct
- IS-2024-Q4 :: revenue[row 1].Label: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: Annual Salary: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: Employee ID: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: Employee Name: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: Employer Address: None -> hallucinated
- PAYSLIP-EMP-0007-APR2024 :: Employer EIN: None -> hallucinated
- PAYSLIP-EMP-0007-APR2024 :: Employer Name: None -> near
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
- PAYSLIP-EMP-0012-APR2024 :: Employee ID: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: Employee Name: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: Employer Address: None -> hallucinated
- PAYSLIP-EMP-0012-APR2024 :: Employer EIN: None -> hallucinated
- PAYSLIP-EMP-0012-APR2024 :: Employer Name: None -> near
- PAYSLIP-EMP-0012-APR2024 :: Net Pay: None -> wrong
- PAYSLIP-EMP-0012-APR2024 :: Pay Date: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: Pay Period: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: SSN: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: Title / Department: None -> renamed
- PAYSLIP-EMP-0012-APR2024 :: Total Deductions: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: Total Earnings: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: YTD Gross Earnings: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: YTD Taxes Withheld: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: deductions :: row_count_mismatch: None -> 0
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
- PAYSLIP-EMP-0012-APR2024 :: earnings :: row_count_mismatch: None -> 0
- PAYSLIP-EMP-0012-APR2024 :: earnings[row 0].Amount: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: earnings[row 0].Description: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: earnings[row 1].Amount: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: earnings[row 1].Description: None -> correct
- PO-2024-0018 :: Authorised By: None -> near
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
- PO-2024-0018 :: Order Total: None -> correct
- PO-2024-0018 :: PO Number: None -> correct
- PO-2024-0018 :: Required By: None -> correct
- PO-2024-0018 :: Ship Via: None -> correct
- PO-2024-0018 :: Special Instructions: None -> hallucinated
- PO-2024-0018 :: Subtotal: None -> correct
- PO-2024-0018 :: Tax: None -> correct
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
- STMT-2024-01 :: ABA: None -> hallucinated
- STMT-2024-01 :: Account Holder: None -> correct
- STMT-2024-01 :: Account No: None -> correct
- STMT-2024-01 :: Account Type: None -> correct
- STMT-2024-01 :: Bank Address: None -> hallucinated
- STMT-2024-01 :: Bank Name: None -> correct
- STMT-2024-01 :: Closing Balance: None -> correct
- STMT-2024-01 :: Opening Balance: None -> correct
- STMT-2024-01 :: Period: None -> correct
- STMT-2024-01 :: Statement No: None -> correct
- STMT-2024-01 :: Total Credits: None -> correct
- STMT-2024-01 :: Total Debits: None -> correct
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
