# Round-2 templates — RECONSTRUCTIONS

The templates used in the round-2 manual runs (`docs/DocAgent_round2_report.md`)
were never saved. These were rebuilt on 2026-09-13 from the report's own
descriptions so the I1 evidence could run the real documents. Each file's
`_reconstruction` key says what the report stated and what was guessed.

| file | stands for | document |
|---|---|---|
| `B1_earnings_table.json` | run 1 (B1 — earnings table, 5 col) | `round2/feb2225.pdf` (Berkshire) |
| `E1_bill_header.json` | run 4 (E1 — bill header, key-value) | `round2/SampleBill.pdf` (ENGIE) |
| `E3_itemised_charges.json` | run 6 (E3 — itemised charges, 2 col) | `round2/SampleBill.pdf` (ENGIE) |

A result from one of these is evidence about the mechanism, not a reproduction
of the original run's exact output. Do not edit them to make a test pass —
record a new run instead (`python -m tests.harness.round2`).
