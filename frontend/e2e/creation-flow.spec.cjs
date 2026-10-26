// Part A7: the whole creation flow in a browser, with the stub model:
// draw a template, save it, upload a document, extract, see the values.
const { test, expect } = require("@playwright/test");
const { login, watchConsole, makePdf, INVOICE } = require("./helpers.cjs");

test("draw a template, extract a document with it, see grounded values", async ({ page }) => {
  const errors = watchConsole(page);
  await login(page);
  await page.goto("/templates/new");
  const grid = page.getByRole("grid", { name: /Template grid/ });
  await expect(grid).toBeVisible({ timeout: 60000 });
  const name = `E2E invoice ${Date.now()}`;
  await page.getByLabel("Template name").fill(name);
  await grid.locator("td").nth(1).click();
  for (const label of ["Invoice No", "Invoice Date", "Bill To", "Total"]) {
    await page.keyboard.type(label);
    await page.keyboard.press("Enter");
  }
  await page.getByRole("button", { name: /Save template/ }).click();
  await page.waitForURL(/\/templates$/, { timeout: 30000 });
  await expect(page.getByText(name)).toBeVisible();

  await page.goto("/extract");
  await page.getByText(name).first().click();
  await page.locator('input[type="file"]').first().setInputFiles(
    { name: "invoice.pdf", mimeType: "application/pdf", buffer: makePdf(INVOICE) });
  await page.getByRole("button", { name: /^Extract/ }).click();
  const modalGo = page.getByRole("button", { name: /Start|Confirm|Extract now/ });
  if (await modalGo.count()) await modalGo.first().click();
  await expect(page.getByText("INV-9001").first()).toBeVisible({ timeout: 120000 });
  // (other columns are virtualised off-screen; the value grounded and says so)
  await expect(page.getByText(/^Verif/).first()).toBeVisible();
  const [download] = await Promise.all([
    page.waitForEvent("download", { timeout: 60000 }),
    page.getByRole("button", { name: /Download Excel/ }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/\.xlsx$/);
  expect(errors.filter(e => !/favicon|DevTools|Download the React/.test(e))).toEqual([]);
});
