# Review flow — manual check on staging (Run G)

A click-by-click check of the review and edit flow, for a person with a
browser. Nothing here was run by the engineer who wrote it: the code paths are
covered by `tests/test_review_flow_spec.py`, `tests/test_run_g_review.py` and
`frontend/lib/reviewActions.test.ts`, but no browser was available. Record a
step that does not behave as written, with its number.

**You need:** a staging login with the reviewer (or admin) role, and a
template whose document has at least one flagged value, one table and, ideally,
a completeness reason. A bank statement or an invoice with a low-confidence
cell works. Use a fresh extraction job for each run of this list.

## A. The results grid

1. Open **Extract**, run a job, wait for **completed**.
   *Expected:* the results grid appears, and its first (pinned) column holds a
   **Review** button on every row. The hint line reads "Click a cell to select
   it · double-click a value to edit it · Review opens the page and the review
   actions".
2. Click once on any value cell, for example an Invoice Number.
   *Expected:* the cell is selected (outlined). **No dialog opens.**
3. Double-click the same cell, change the text, press Enter.
   *Expected:* the cell turns into an input on the double-click. After Enter a
   "Saved" toast appears, the badge becomes **Edited**, and still no dialog
   opens.
4. Click the **Rows** count on a row that has line items.
   *Expected:* the Line Items panel opens below the grid. No dialog opens.
5. Click **Review** on a row whose Status says **Review (n)**.
   *Expected:* the review dialog opens on that document, with the page image on
   the left and the values on the right. The first value needing review is
   selected and its box is drawn on the page.

## B. The three actions on a flagged value

6. In the dialog, select a value whose badge is **Low**, **Unverified** or
   **Empty, flagged**.
   *Expected:* three buttons under it: **Accept as is (a)**, **Correct (c)**,
   **Mark empty (m)**. There is no Edit button while the value is unresolved.
7. Click **Accept as is**.
   *Expected:* the toast says "Accepted as is". The value's badge turns to the
   reviewed style, the buttons disappear, "Accepted as is" is shown next to it,
   and the header's "n values need review" drops by one.
8. Select another flagged value and click **Correct**.
   *Expected:* an input appears holding the current value, with **Save and
   accept** and **Cancel**.
9. Type a new value and click **Save and accept**.
   *Expected:* the toast says "Corrected and accepted". The value shows the new
   text with the **Edited** badge and "Corrected", and the count drops by one.
   This is one request: reload the page (F5), reopen Review, and the value and
   the mark are both still there.
10. Select a flagged value that should really be blank and click **Mark empty**.
    *Expected:* the toast says "Marked empty". The value shows *empty*,
    "Confirmed empty" is shown, and the count drops by one.
11. Select a table-cell value (label "table row 1: Amount" or similar) that is
    flagged, and click **Accept as is**.
    *Expected:* only that cell is accepted. The other flagged cells of the SAME
    row still show their three buttons.
12. On a value that owes nothing (Verified / Grounded / Edited), check the buttons.
    *Expected:* only **Edit (e)**. Clicking it opens an input with **Save**, and
    saving gives "Saved — marked as edited".
13. Keyboard check: select a flagged value and press `c`, then Esc. Then press
    `a` on another flagged value, and `m` on a third.
    *Expected:* `c` opens the Correct input and Esc cancels it; `a` accepts as
    is; `m` marks empty. Typing in any input never triggers these keys.

## C. Adding a missing row

14. Scroll to the bottom of the value list.
    *Expected:* one **Add row to &lt;table&gt;** button per table of the template.
15. Click **Add row to &lt;table&gt;**.
    *Expected:* a form with one input per column of that table. If the document
    has an open completeness reason, an **Answers** dropdown lists it.
16. Leave every input blank and click **Add row**.
    *Expected:* the toast says "Type at least one value for the new row" and
    nothing is added.
17. Fill the inputs (for example Description "Test row", Amount "1.00"), choose
    the completeness reason in **Answers** if offered, and click **Add row**.
    *Expected:* the toast says "Row added", or "Row added — check B… : the
    total no longer matches" when a total slot no longer sums. The new row's
    cells appear in the value list as **Edited**. If you chose a reason, it now
    reads "Entered by hand — &lt;your name&gt;".
18. If the toast named a total, select that total value.
    *Expected:* it is flagged again (Low, reason "Invoice totals do not add
    up"). Its value has **not** been changed. Settle it with one of the three
    actions.

## D. History

19. Click **History** in the dialog header.
    *Expected:* a read-only "History" panel opens above the values, listing one
    line per change in time order, each with your user name and a UTC time: the
    edit from step 3, the accept from step 7, the correction from step 9 with
    "old" → "new", the mark-empty from step 10, the cell accept from step 11,
    and "added a row to &lt;table&gt;" from step 17.
20. With History open, accept one more flagged value.
    *Expected:* a new line appears at the bottom of the History panel without
    closing it.
21. Click **Hide history**.
    *Expected:* the panel closes. Nothing in it could be edited.

## E. One review state, and the download

22. While at least one value still needs review, close the dialog and download
    the export (Export / Download Excel).
    *Expected:* the confirmation says values still need review "and the file
    will be named _DRAFT until every value is settled". The file name ends
    `_DRAFT.xlsx`.
23. Open that file.
    *Expected:* the corrected value from step 9 shows its new text, lavender
    fill and **no** comment. The slot from step 10 is a plain empty cell with no
    fill and no comment. The row from step 17 is in its table, and the Legend
    sheet lists it under "Rows added by hand". Unresolved values keep a coloured
    fill and a "NEEDS REVIEW" comment.
24. Reopen **Review** and settle every remaining value, either one by one or
    with **Mark document reviewed**, and settle every completeness reason.
    *Expected:* the header reads "Nothing in this document needs review" and
    the grid's Status column shows **OK**.
25. Download again.
    *Expected:* no confirmation, the file name has **no** `_DRAFT`, the Legend
    sheet's first line reads "Nothing needs review", and no comment anywhere
    starts with "NEEDS REVIEW".
26. API check (optional, any HTTP client with your token): on a document that
    still has an unresolved value, call `POST /api/jobs/{job}/docs/{doc}/approve`.
    *Expected:* HTTP 409 with a message saying how many values still need
    review. On a settled document it is HTTP 200 and the review screen shows
    the document as reviewed.
27. API check (optional): `GET /api/jobs/{job}/docs/{doc}/history`.
    *Expected:* HTTP 200 with `events`, the same entries as the History panel.
    Another firm's job id answers 404.
