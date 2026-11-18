# Frozen acceptance fixtures

These files are local, immutable inputs for the DocAgent acceptance suite.

- `source_docs/` contains every document referenced by a golden truth file, plus the scan/photo inputs used only by the offline input-lane tests.
- `job_records/` contains the four recorded API results supplied for jobs 15, 19, 21, and 25.
- `templates/DocAgent_templates_v2.xlsx` is the supplied 43-template workbook. Its `Answers` sheet was used as an independent cross-check, never as generated model output.

Normal pytest and CI runs must not make model calls. The recorded results are deliberately kept unchanged, including defects. Do not replace them with newly generated output to make a test pass.

The original `local_docs/` directory is ignored. It may contain additional owner-only material and must not be committed wholesale.
