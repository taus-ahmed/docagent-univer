# DocAgent UI reapplication on `ui/extract-run-r`

## Changes

- Fresh Extract shows Documents and Additional options in equal cards across the top, with the searchable template selector and spreadsheet preview below. The desktop workspace fits the viewport. The preview preserves merges, row positions and line-item markers. It shows wider columns and wraps long labels, with scrolling inside the preview.
- Extract results and History job detail use `JobResultsLayout` for the same ordered boxes. The boxes show Template used, Status, Download Organized, Download Excel, New extraction, and Download with audit columns. ZIP remains available for jobs with more than one document. History retains its document search, details, and link to the review grid. Extract retains job-based result columns, plain status, the model name, failure details, and accepted-after-Low counts.
- The shared template lookup uses the job's `schema_id`. The Extract page can reuse a matching template from its list. Both pages can resolve an ID through the template detail endpoint. Only an explicit `null` produces “No template, layout inferred from the document.” A missing ID or an unavailable name has its own message.
- Download Organized requests `layout=organized` through the existing Next.js proxy, which preserves the workbook filename. The client checks the XLSX archive and detects the API's skipped-only workbook. An error, a regular workbook, or a skipped-only reply shows an inline message pointing to Download Excel. A partially organized workbook with usable sheets still downloads with the server's report for skipped documents.

## Checks run

- Reviewed the current conflicting files and `git show c2b8de0 --stat`. The old commit changed `package.json` to add `jobPresentation.test.ts` and `templatePreview.test.ts` to the Node test script. This reapplication preserved the branch's test entries and added `organizedExport.test.ts`. It added zero dependencies.
- `npm.cmd test` in `frontend/` passed **97 tests before changes**. Updated the existing assertions that required the old top-bar layout, added the organized workbook cases, and observed the new expectations fail before implementing them. The final run passed **100 tests**.
- `npm.cmd run type-check`, `npm.cmd run build`, and `git diff --check` passed.
- Verified the API contract in the current branch's upload, job-detail, job-list, and template-detail routes and response models. Upload stores the selected template ID as `schema_id` or `null`. The job endpoints serialize that field, and template detail supplies the name. The export route uses an `_organized.xlsx` filename for organized output and can return a `Not organized` sheet when it cannot lay out a source.
- Playwright and Next.js dev passed at **1366×768** and **1920×1080** with synthetic API responses using the branch's `schema_id` shape. The checks covered viewport fit with and without a template, equal top cards, readable wrapping in an 11-column preview, and sidebar resizing. They also exercised upload and polling, the History detail and reopened job, the fresh Extract action, the regular and audit downloads, and the real Next.js proxy forwarding the organized request to a local fixture server. HTTP errors, regular workbooks, truncated workbooks and skipped-only workbooks showed the inline message without downloading. The organized success case downloaded.

## Verification limits

- The backend test suite and authenticated requests to the deployed API were outside this frontend run. The browser fixtures exercised the contract without running a live extraction or calling a model.
- Deployment verification remains for authentic job responses and template permissions, plus generated organized workbooks on the configured backend. The deployed Next.js proxy needs its existing `BACKEND_URL` pointing at that backend. Live document coverage, including the mix of supported text PDFs and skipped sources, depends on server-generated output.
- No screenshots or `local_docs` files were added. Changes are uncommitted.

## Files changed

- `frontend/app/extract/page.tsx`, `frontend/app/history/page.tsx`, `frontend/app/globals.css`
- `frontend/components/extract/JobResultsLayout.tsx`, `NewExtractionButton.tsx`, `ResultsGrid.tsx`, `TemplatePreview.tsx`
- `frontend/components/layout/AppLayout.tsx`
- `frontend/lib/api.ts`, `jobTemplate.ts`, `useJobTemplate.ts`, `organizedExport.ts`
- `frontend/lib/jobTemplate.test.ts`, `resultsPage.test.ts`, `organizedExport.test.ts`, `frontend/package.json`
- `docs/UI_CHANGES_RUN.md`
