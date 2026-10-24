# Review screen screenshots

Taken with Playwright (Chromium) against a throwaway local backend and SQLite
database seeded with the **synthetic** cheques in `tests/test_OCR/`
(generated test images, not client documents). Laptop 1366×820, tablet
820×1100.

| file | shows |
|---|---|
| `results-table-laptop.png` | one row per cheque record (`[k of N]`, page), status, a badge per value, counts and filters |
| `results-table-low-only-laptop.png` | the "Low only" filter |
| `results-table-tablet.png` | the table at tablet width |
| `review-panel-laptop.png` | the review panel: the straightened scan the reader saw, the selected value's box, reasons as labels |
| `review-panel-tablet.png` | the panel stacked at tablet width |
