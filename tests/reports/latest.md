# Accuracy report — 2026-08-21 01:04:19

- git: `6b128f2`  mode: **replay**  repeat: 1
- config: {"PRIMARY_LLM": "gemini", "GEMINI_MODEL": "gemini-2.5-flash-lite"}

## Overall

| metric | value |
|---|---|
| **accuracy (correct / gold-valued)** | **97.9%** |
| **accuracy RAW (all adapter widenings off)** | **49.2%** |
| **hallucination rate (hallucinated / extracted)** | **0.0%** |
| **└ invention rate (value found NOWHERE in the PDF)** | **0.0%** |
| └ misplacement (real content, slot gold leaves empty) | 0.0% |
| hallucinated values | 0 (invented 0, misplaced 0) |
| near misses | 5 |
| outcome counts | {"correct": 370, "missed": 2, "near": 5, "wrong": 1, "empty_ok": 12} |

## By document type

| document type | accuracy | halluc. rate | invented | correct | near | wrong | missed | halluc. |
|---|---|---|---|---|---|---|---|---|
| balance_sheet | 100.0% | 0.0% | 0 | 46 | 0 | 0 | 0 | 0 |
| bank_statement | 100.0% | 0.0% | 0 | 70 | 0 | 0 | 0 | 0 |
| cheque | 81.8% | 0.0% | 0 | 9 | 0 | 0 | 2 | 0 |
| expense_report | 100.0% | 0.0% | 0 | 54 | 0 | 0 | 0 | 0 |
| income_statement | 100.0% | 0.0% | 0 | 25 | 0 | 0 | 0 | 0 |
| payslip | 95.7% | 0.0% | 0 | 67 | 2 | 1 | 0 | 0 |
| purchase_order | 96.8% | 0.0% | 0 | 30 | 1 | 0 | 0 | 0 |
| sales_invoice | 97.2% | 0.0% | 0 | 69 | 2 | 0 | 0 | 0 |

## By field type

| field type | accuracy | halluc. rate | invented | correct | near | wrong | missed | halluc. |
|---|---|---|---|---|---|---|---|---|
| date | 100.0% | 0.0% | 0 | 30 | 0 | 0 | 0 | 0 |
| money | 99.4% | 0.0% | 0 | 160 | 0 | 1 | 0 | 0 |
| number | 100.0% | 0.0% | 0 | 12 | 0 | 0 | 0 | 0 |
| string | 96.0% | 0.0% | 0 | 168 | 5 | 0 | 2 | 0 |

## Per document

| document | type | accuracy | raw | halluc. | invented | route | notes |
|---|---|---|---|---|---|---|---|
| BS-2024-Q1 | balance_sheet | 100.0% | 58.7% | 0 | 0 | BS-2024-Q1.pdf: file_type=digital_pdf pages=2 text_len=1242 |  |
| CHQ-001847 | cheque | 81.8% | 81.8% | 0 | 0 | CHQ-001847.pdf: file_type=digital_pdf pages=1 text_len=501 |  |
| EXP-2024-0081 | expense_report | 100.0% | 16.7% | 0 | 0 | EXP-2024-0081.pdf: file_type=digital_pdf pages=1 text_len=11 |  |
| INV-2024-0031 | sales_invoice | 97.0% | 36.4% | 0 | 0 | INV-2024-0031.pdf: file_type=digital_pdf pages=1 text_len=97 |  |
| INV-2024-0047 | sales_invoice | 97.4% | 31.6% | 0 | 0 | INV-2024-0047.pdf: file_type=digital_pdf pages=1 text_len=10 |  |
| IS-2024-Q4 | income_statement | 100.0% | 100.0% | 0 | 0 | IS-2024-Q4.pdf: file_type=digital_pdf pages=2 text_len=970 |  |
| PAYSLIP-EMP-0007-APR2024 | payslip | 94.6% | 94.6% | 0 | 0 | PAYSLIP-EMP-0007-APR2024.pdf: file_type=digital_pdf pages=2  |  |
| PAYSLIP-EMP-0012-APR2024 | payslip | 97.0% | 97.0% | 0 | 0 | PAYSLIP-EMP-0012-APR2024.pdf: file_type=digital_pdf pages=2  |  |
| PO-2024-0018 | purchase_order | 96.8% | 48.4% | 0 | 0 | PO-2024-0018.pdf: file_type=digital_pdf pages=1 text_len=104 |  |
| STMT-2024-01 | bank_statement | 100.0% | 14.3% | 0 | 0 | STMT-2024-01.pdf: file_type=digital_pdf pages=1 text_len=140 |  |

## Mismatches (everything not correct)

| document | field | outcome | expected | actual |
|---|---|---|---|---|
| CHQ-001847 | Routing Number | missed | 021000021 | None |
| CHQ-001847 | Account Number | missed | 7743882201 | None |
| INV-2024-0031 | Bill To Contact | near | Mr. Robert Chen | Mr. Robert Chen — rchen@apexindustrial.com |
| INV-2024-0047 | Bill To Contact | near | Ms. Sarah Johnson | Ms. Sarah Johnson — sjohnson@pinnacleelec.com |
| PAYSLIP-EMP-0007-APR2024 | Employer Name | near | Nexus Global Trading LLC | NEXUS GLOBAL TRADING |
| PAYSLIP-EMP-0007-APR2024 | Net Pay | wrong | 7513.03 | $7,513.0 |
| PAYSLIP-EMP-0012-APR2024 | Employer Name | near | Nexus Global Trading LLC | NEXUS GLOBAL TRADING |
| PO-2024-0018 | Vendor Contact | near | Ms. Linda Zhao | Ms. Linda Zhao \| (310) 555-0233 |
