# Accuracy report — 2026-11-20 14:58:26

- git: `d797fd0`  mode: **replay**  repeat: 1
- config: {"PRIMARY_LLM": "gemini", "GEMINI_MODEL": "gemini-2.5-flash-lite"}

## Overall

| metric | value |
|---|---|
| **accuracy (correct / gold-valued)** | **98.7%** |
| **accuracy RAW (all adapter widenings off)** | **48.0%** |
| **accuracy CONTENT (container-blind)** | **97.9%** |
| **structure FIDELITY (gold tables returned as tables)** | **100.0%** (17/17; 17 with exact row count) |
| **hallucination rate (hallucinated / extracted)** | **0.0%** |
| **├ INVENTED — value found NOWHERE in the PDF** | **0** (0.0%) |
| ├ misfiled — real content in a slot gold says is EMPTY | 0 |
| └ out-of-schema — real content, name gold has no field for | 0 *(not a defect)* |
| **DEFECT RATE (invented + misfiled / extracted)** | **0.0%** |
| hallucinated values | 0 |
| near misses | 5 |
| **renamed (right value, different field name)** | **0** (0.0%) |
| outcome counts | {"correct": 389, "near": 5, "empty_ok": 12} |

## By document type

| document type | accuracy | halluc. rate | invented | correct | near | renamed | wrong | missed | halluc. |
|---|---|---|---|---|---|---|---|---|---|
| balance_sheet | 100.0% | 0.0% | 0 | 46 | 0 | 0 | 0 | 0 | 0 |
| bank_statement | 100.0% | 0.0% | 0 | 70 | 0 | 0 | 0 | 0 | 0 |
| cheque | 100.0% | 0.0% | 0 | 11 | 0 | 0 | 0 | 0 | 0 |
| expense_report | 100.0% | 0.0% | 0 | 54 | 0 | 0 | 0 | 0 | 0 |
| income_statement | 100.0% | 0.0% | 0 | 41 | 0 | 0 | 0 | 0 | 0 |
| payslip | 97.1% | 0.0% | 0 | 68 | 2 | 0 | 0 | 0 | 0 |
| purchase_order | 96.8% | 0.0% | 0 | 30 | 1 | 0 | 0 | 0 | 0 |
| sales_invoice | 97.2% | 0.0% | 0 | 69 | 2 | 0 | 0 | 0 | 0 |

## By field type

| field type | accuracy | halluc. rate | invented | correct | near | renamed | wrong | missed | halluc. |
|---|---|---|---|---|---|---|---|---|---|
| date | 100.0% | 0.0% | 0 | 30 | 0 | 0 | 0 | 0 | 0 |
| money | 100.0% | 0.0% | 0 | 161 | 0 | 0 | 0 | 0 | 0 |
| number | 100.0% | 0.0% | 0 | 12 | 0 | 0 | 0 | 0 | 0 |
| string | 97.4% | 0.0% | 0 | 186 | 5 | 0 | 0 | 0 | 0 |

## Per document

| document | type | accuracy | raw | halluc. | invented | route | notes |
|---|---|---|---|---|---|---|---|
| BS-2024-Q1 | balance_sheet | 100.0% | 58.7% | 0 | 0 | doc-aa42f790f4: file_type=digital_pdf pages=2 text_len=1242 |  |
| CHQ-001847 | cheque | 100.0% | 100.0% | 0 | 0 | doc-f7ea3d6e0e: file_type=digital_pdf pages=1 text_len=501 |  |
| EXP-2024-0081 | expense_report | 100.0% | 16.7% | 0 | 0 | doc-71691073cd: file_type=digital_pdf pages=1 text_len=1107 |  |
| INV-2024-0031 | sales_invoice | 97.0% | 36.4% | 0 | 0 | doc-9f942c192f: file_type=digital_pdf pages=1 text_len=971 |  |
| INV-2024-0047 | sales_invoice | 97.4% | 31.6% | 0 | 0 | doc-eba86b7cfd: file_type=digital_pdf pages=1 text_len=1040 |  |
| IS-2024-Q4 | income_statement | 100.0% | 61.0% | 0 | 0 | doc-dd7566581f: file_type=digital_pdf pages=2 text_len=970 |  |
| PAYSLIP-EMP-0007-APR2024 | payslip | 97.3% | 97.3% | 0 | 0 | doc-c6ca0ed7a1: file_type=digital_pdf pages=2 text_len=887 |  |
| PAYSLIP-EMP-0012-APR2024 | payslip | 97.0% | 97.0% | 0 | 0 | doc-b4129481ed: file_type=digital_pdf pages=2 text_len=852 |  |
| PO-2024-0018 | purchase_order | 96.8% | 48.4% | 0 | 0 | doc-95170d496c: file_type=digital_pdf pages=1 text_len=1048 |  |
| STMT-2024-01 | bank_statement | 100.0% | 14.3% | 0 | 0 | doc-5223753b4c: file_type=digital_pdf pages=1 text_len=1403 |  |

## Mismatches (everything not correct)

| document | field | outcome | expected | actual |
|---|---|---|---|---|
| INV-2024-0031 | Bill To Contact | near | Mr. Robert Chen | Mr. Robert Chen — rchen@apexindustrial.com |
| INV-2024-0047 | Bill To Contact | near | Ms. Sarah Johnson | Ms. Sarah Johnson — sjohnson@pinnacleelec.com |
| PAYSLIP-EMP-0007-APR2024 | Employer Name | near | Nexus Global Trading LLC | NEXUS GLOBAL TRADING |
| PAYSLIP-EMP-0012-APR2024 | Employer Name | near | Nexus Global Trading LLC | NEXUS GLOBAL TRADING |
| PO-2024-0018 | Vendor Contact | near | Ms. Linda Zhao | Ms. Linda Zhao \| (310) 555-0233 |
