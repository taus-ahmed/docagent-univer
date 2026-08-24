# Accuracy report — 2026-08-23 20:35:09

- git: `3992034`  mode: **record**  repeat: 1
- config: {"PRIMARY_LLM": "gemini", "GEMINI_MODEL": "gemini-2.5-flash-lite"}

## Overall

| metric | value |
|---|---|
| **accuracy (correct / gold-valued)** | **98.5%** |
| **accuracy RAW (all adapter widenings off)** | **47.7%** |
| **accuracy CONTENT (container-blind)** | **97.5%** |
| **structure FIDELITY (gold tables returned as tables)** | **100.0%** (17/17; 15 with exact row count) |
| **hallucination rate (hallucinated / extracted)** | **1.0%** |
| **├ INVENTED — value found NOWHERE in the PDF** | **0** (0.0%) |
| ├ misfiled — real content in a slot gold says is EMPTY | 4 |
| └ out-of-schema — real content, name gold has no field for | 0 *(not a defect)* |
| **DEFECT RATE (invented + misfiled / extracted)** | **1.0%** |
| hallucinated values | 4 |
| near misses | 5 |
| **renamed (right value, different field name)** | **0** (0.0%) |
| outcome counts | {"correct": 388, "near": 5, "wrong": 1, "hallucinated": 4, "empty_ok": 12} |

## By document type

| document type | accuracy | halluc. rate | invented | correct | near | renamed | wrong | missed | halluc. |
|---|---|---|---|---|---|---|---|---|---|
| balance_sheet | 100.0% | 0.0% | 0 | 46 | 0 | 0 | 0 | 0 | 0 |
| bank_statement | 100.0% | 0.0% | 0 | 70 | 0 | 0 | 0 | 0 | 0 |
| cheque | 100.0% | 0.0% | 0 | 11 | 0 | 0 | 0 | 0 | 0 |
| expense_report | 100.0% | 0.0% | 0 | 54 | 0 | 0 | 0 | 0 | 0 |
| income_statement | 100.0% | 0.0% | 0 | 41 | 0 | 0 | 0 | 0 | 0 |
| payslip | 95.7% | 5.4% | 0 | 67 | 2 | 0 | 1 | 0 | 4 |
| purchase_order | 96.8% | 0.0% | 0 | 30 | 1 | 0 | 0 | 0 | 0 |
| sales_invoice | 97.2% | 0.0% | 0 | 69 | 2 | 0 | 0 | 0 | 0 |

## By field type

| field type | accuracy | halluc. rate | invented | correct | near | renamed | wrong | missed | halluc. |
|---|---|---|---|---|---|---|---|---|---|
| date | 100.0% | 0.0% | 0 | 30 | 0 | 0 | 0 | 0 | 0 |
| money | 99.4% | 1.2% | 0 | 160 | 0 | 0 | 1 | 0 | 2 |
| number | 100.0% | 0.0% | 0 | 12 | 0 | 0 | 0 | 0 | 0 |
| string | 97.4% | 1.0% | 0 | 186 | 5 | 0 | 0 | 0 | 2 |

## Per document

| document | type | accuracy | raw | halluc. | invented | route | notes |
|---|---|---|---|---|---|---|---|
| BS-2024-Q1 | balance_sheet | 100.0% | 58.7% | 0 | 0 | BS-2024-Q1.pdf: file_type=digital_pdf pages=2 text_len=1242 |  |
| CHQ-001847 | cheque | 100.0% | 100.0% | 0 | 0 | CHQ-001847.pdf: file_type=digital_pdf pages=1 text_len=501 |  |
| EXP-2024-0081 | expense_report | 100.0% | 16.7% | 0 | 0 | EXP-2024-0081.pdf: file_type=digital_pdf pages=1 text_len=11 |  |
| INV-2024-0031 | sales_invoice | 97.0% | 36.4% | 0 | 0 | INV-2024-0031.pdf: file_type=digital_pdf pages=1 text_len=97 |  |
| INV-2024-0047 | sales_invoice | 97.4% | 31.6% | 0 | 0 | INV-2024-0047.pdf: file_type=digital_pdf pages=1 text_len=10 |  |
| IS-2024-Q4 | income_statement | 100.0% | 61.0% | 0 | 0 | IS-2024-Q4.pdf: file_type=digital_pdf pages=2 text_len=970 |  |
| PAYSLIP-EMP-0007-APR2024 | payslip | 97.3% | 97.3% | 0 | 0 | PAYSLIP-EMP-0007-APR2024.pdf: file_type=digital_pdf pages=2  |  |
| PAYSLIP-EMP-0012-APR2024 | payslip | 93.9% | 93.9% | 4 | 0 | PAYSLIP-EMP-0012-APR2024.pdf: file_type=digital_pdf pages=2  |  |
| PO-2024-0018 | purchase_order | 96.8% | 48.4% | 0 | 0 | PO-2024-0018.pdf: file_type=digital_pdf pages=1 text_len=104 |  |
| STMT-2024-01 | bank_statement | 100.0% | 14.3% | 0 | 0 | STMT-2024-01.pdf: file_type=digital_pdf pages=1 text_len=140 |  |

## Mismatches (everything not correct)

| document | field | outcome | expected | actual |
|---|---|---|---|---|
| INV-2024-0031 | Bill To Contact | near | Mr. Robert Chen | Mr. Robert Chen — rchen@apexindustrial.com |
| INV-2024-0047 | Bill To Contact | near | Ms. Sarah Johnson | Ms. Sarah Johnson — sjohnson@pinnacleelec.com |
| PAYSLIP-EMP-0007-APR2024 | Employer Name | near | Nexus Global Trading LLC | NEXUS GLOBAL TRADING |
| PAYSLIP-EMP-0012-APR2024 | Employer Name | near | Nexus Global Trading LLC | NEXUS GLOBAL TRADING |
| PAYSLIP-EMP-0012-APR2024 | Net Pay | wrong | 5182.65 | $5,182.6 |
| PAYSLIP-EMP-0012-APR2024 | earnings[pred_row 2].Description | hallucinated (misplaced) | None | Total |
| PAYSLIP-EMP-0012-APR2024 | earnings[pred_row 2].Amount | hallucinated (misplaced) | None | $8,300.00 |
| PAYSLIP-EMP-0012-APR2024 | deductions[pred_row 8].Description | hallucinated (misplaced) | None | Total |
| PAYSLIP-EMP-0012-APR2024 | deductions[pred_row 8].Amount | hallucinated (misplaced) | None | ($3,117.35) |
| PO-2024-0018 | Vendor Contact | near | Ms. Linda Zhao | Ms. Linda Zhao \| (310) 555-0233 |

## Changes vs previous run

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
- EXP-2024-0081 :: Department: None -> correct
- EXP-2024-0081 :: Employee ID: None -> correct
- EXP-2024-0081 :: Employee Name: None -> correct
- EXP-2024-0081 :: Manager: None -> correct
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
- INV-2024-0031 :: Payment Terms: None -> correct
- INV-2024-0031 :: Sales Tax: None -> correct
- INV-2024-0031 :: Shipping & Handling: None -> correct
- INV-2024-0031 :: Status: None -> correct
- INV-2024-0031 :: Subtotal: None -> correct
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
- INV-2024-0047 :: Bill To Contact: None -> near
- INV-2024-0047 :: Due Date: None -> correct
- INV-2024-0047 :: Invoice Date: None -> correct
- INV-2024-0047 :: Invoice Number: None -> correct
- INV-2024-0047 :: PO Reference: None -> correct
- INV-2024-0047 :: Payment Terms: None -> correct
- INV-2024-0047 :: Sales Tax: None -> correct
- INV-2024-0047 :: Shipping & Handling: None -> correct
- INV-2024-0047 :: Status: None -> correct
- INV-2024-0047 :: Subtotal: None -> correct
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
- IS-2024-Q4 :: Gross Profit: None -> correct
- IS-2024-Q4 :: Income Tax Provision: None -> correct
- IS-2024-Q4 :: Interest Income: None -> correct
- IS-2024-Q4 :: Net Income After Tax: None -> correct
- IS-2024-Q4 :: Net Income Before Tax: None -> correct
- IS-2024-Q4 :: Net Revenue: None -> correct
- IS-2024-Q4 :: Operating Income (EBIT): None -> correct
- IS-2024-Q4 :: Total COGS: None -> correct
- IS-2024-Q4 :: Total Operating Expenses: None -> correct
- IS-2024-Q4 :: cost_of_goods_sold :: row_count_mismatch: None -> 0
- IS-2024-Q4 :: cost_of_goods_sold[row 0].Amount: None -> correct
- IS-2024-Q4 :: cost_of_goods_sold[row 0].Label: None -> correct
- IS-2024-Q4 :: cost_of_goods_sold[row 1].Amount: None -> correct
- IS-2024-Q4 :: cost_of_goods_sold[row 1].Label: None -> correct
- IS-2024-Q4 :: cost_of_goods_sold[row 2].Amount: None -> correct
- IS-2024-Q4 :: cost_of_goods_sold[row 2].Label: None -> correct
- IS-2024-Q4 :: cost_of_goods_sold[row 3].Amount: None -> correct
- IS-2024-Q4 :: cost_of_goods_sold[row 3].Label: None -> correct
- IS-2024-Q4 :: operating_expenses :: row_count_mismatch: None -> 0
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
- IS-2024-Q4 :: revenue :: row_count_mismatch: None -> 0
- IS-2024-Q4 :: revenue[row 0].Amount: None -> correct
- IS-2024-Q4 :: revenue[row 0].Label: None -> correct
- IS-2024-Q4 :: revenue[row 1].Amount: None -> correct
- IS-2024-Q4 :: revenue[row 1].Label: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: Annual Salary: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: Employee ID: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: Employee Name: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: Employer Name: None -> near
- PAYSLIP-EMP-0007-APR2024 :: Net Pay: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: Pay Date: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: Pay Period: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: SSN: None -> correct
- PAYSLIP-EMP-0007-APR2024 :: Title / Department: None -> correct
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
- PAYSLIP-EMP-0012-APR2024 :: Employer Name: None -> near
- PAYSLIP-EMP-0012-APR2024 :: Net Pay: None -> wrong
- PAYSLIP-EMP-0012-APR2024 :: Pay Date: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: Pay Period: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: SSN: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: Title / Department: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: Total Deductions: None -> correct
- PAYSLIP-EMP-0012-APR2024 :: Total Earnings: None -> correct
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
- PO-2024-0018 :: Authorised By: None -> correct
- PO-2024-0018 :: Buyer Name: None -> correct
- PO-2024-0018 :: Buyer Title: None -> correct
- PO-2024-0018 :: Date: None -> correct
- PO-2024-0018 :: Freight: None -> correct
- PO-2024-0018 :: Order Total: None -> correct
- PO-2024-0018 :: PO Number: None -> correct
- PO-2024-0018 :: Required By: None -> correct
- PO-2024-0018 :: Ship Via: None -> correct
- PO-2024-0018 :: Subtotal: None -> correct
- PO-2024-0018 :: Tax: None -> correct
- PO-2024-0018 :: Terms: None -> correct
- PO-2024-0018 :: Vendor Address: None -> correct
- PO-2024-0018 :: Vendor Contact: None -> near
- PO-2024-0018 :: Vendor ID: None -> correct
- PO-2024-0018 :: Vendor Name: None -> correct
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
- STMT-2024-01 :: Account Holder: None -> correct
- STMT-2024-01 :: Account No: None -> correct
- STMT-2024-01 :: Account Type: None -> correct
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
