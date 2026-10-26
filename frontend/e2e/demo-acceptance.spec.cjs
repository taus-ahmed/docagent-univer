// Part A9: the whole demo flow with the stub model. Any broken step fails.
// login -> template from scratch -> a two-invoice file with every option on
// -> extraction (split into two documents) -> review edit -> mark reviewed
// -> export -> firm B sees none of it.
const { test, expect } = require("@playwright/test");
const { login, watchConsole, makePdfPages, token, creds } = require("./helpers.cjs");

const TWO_INVOICES = [
  ["ACME TRADING LTD", "INVOICE", "Invoice No: INV-9001", "Invoice Date: 2024-03-15",
   "Bill To: Globex Corporation", "Total: $125.00"],
  ["ACME TRADING LTD", "INVOICE", "Invoice No: INV-9002", "Invoice Date: 2024-03-22",
   "Bill To: Initech Ltd", "Total: $310.40"],
];

test("demo acceptance: template, multi-document upload, options, review, export, isolation", async ({ page, browser }) => {
  const errors = watchConsole(page);
  const api = creds().api;
  await login(page, "e2e_a");

  // 1. a template from scratch
  await page.goto("/templates/new");
  const grid = page.getByRole("grid", { name: /Template grid/ });
  await expect(grid).toBeVisible({ timeout: 60000 });
  const name = `Acceptance ${Date.now()}`;
  await page.getByLabel("Template name").fill(name);
  await grid.locator("td").nth(1).click();
  for (const label of ["Invoice No", "Invoice Date", "Bill To", "Total"]) {
    await page.keyboard.type(label);
    await page.keyboard.press("Enter");
  }
  await page.getByRole("button", { name: /Save template/ }).click();
  await page.waitForURL(/\/templates$/, { timeout: 30000 });

  // 2. every option on, a two-invoice file
  await page.goto("/extract");
  await page.getByText(name).first().click();
  const opts = page.getByRole("group", { name: "Additional options" });
  for (const i of [0, 1, 2, 4]) await opts.getByRole("checkbox").nth(i).check({ force: true });
  await opts.getByRole("checkbox").nth(3).check({ force: true });   // narrative, after summary
  await page.locator('input[type="file"]').first().setInputFiles(
    { name: "two-invoices.pdf", mimeType: "application/pdf", buffer: makePdfPages(TWO_INVOICES) });
  await page.getByRole("button", { name: /^Extract/ }).click();
  // the page-selection dialog (restored route) offers both pages
  await page.getByRole("button", { name: /Extract \(2 pages\)/ }).click();
  await expect(page.getByText("INV-9001").first()).toBeVisible({ timeout: 120000 });
  await expect(page.getByText("INV-9002").first()).toBeVisible();

  // 3. the job, through the API with this user's own token
  const auth = { Authorization: `Bearer ${await token(page)}` };
  const jobs = await (await page.request.get(`${api}/api/jobs`, { headers: auth })).json();
  const job = (jobs.jobs || jobs)[0];
  const review = await (await page.request.get(`${api}/api/jobs/${job.id}/review`, { headers: auth })).json();
  expect(review.documents.length).toBe(2);                     // split into two documents
  const doc = review.documents[0];
  const field = doc.values.find(v => v.kind === "field" && v.value);

  // 4. review edit, then mark the document reviewed
  const edit = await page.request.patch(`${api}/api/jobs/${job.id}/docs/${doc.doc_id}/fields/${field.ref}`,
    { headers: auth, data: { value: String(field.value) + " (checked)" } });
  expect(edit.ok()).toBeTruthy();
  const mark = await page.request.post(`${api}/api/jobs/${job.id}/docs/${doc.doc_id}/review`,
    { headers: auth, data: { scope: "document" } });
  expect(mark.ok()).toBeTruthy();

  // 5. export: a workbook with the review legend and the charts sheet
  const exp = await page.request.get(`${api}/api/jobs/${job.id}/export`, { headers: auth });
  expect(exp.ok()).toBeTruthy();
  const body = await exp.body();
  expect(body.slice(0, 2).toString()).toBe("PK");             // an .xlsx (zip)
  expect(body.length).toBeGreaterThan(4000);                  // sheets are compressed inside
  const charts = await (await page.request.get(`${api}/api/jobs/${job.id}/charts`, { headers: auth })).json();
  // a fields-only template has no rows to chart: the route says so instead of drawing
  expect(charts.values >= 2 || /Not enough/.test(charts.message || "")).toBeTruthy();

  // 6. firm B: the job does not exist for it
  const ctxB = await browser.newContext({ baseURL: creds().web });
  const pageB = await ctxB.newPage();
  await login(pageB, "e2e_b");
  const authB = { Authorization: `Bearer ${await token(pageB)}` };
  expect((await pageB.request.get(`${api}/api/jobs/${job.id}/review`, { headers: authB })).status()).toBe(404);
  expect((await pageB.request.get(`${api}/api/jobs/${job.id}/export`, { headers: authB })).status()).toBe(404);
  const bJobs = await (await pageB.request.get(`${api}/api/jobs`, { headers: authB })).json();
  expect((bJobs.jobs || bJobs).map(j => j.id)).not.toContain(job.id);
  await ctxB.close();

  expect(errors.filter(e => !/favicon|DevTools|Download the React|Failed to fetch RSC payload/.test(e))).toEqual([]);
});
