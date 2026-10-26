// Part A7: the template editor's keyboard and save behaviour, in a browser.
const { test, expect } = require("@playwright/test");
const { login, watchConsole } = require("./helpers.cjs");

test("Tab moves between cells, Enter commits, the grid keeps focus", async ({ page }) => {
  const errors = watchConsole(page);
  await login(page);
  await page.goto("/templates/new");
  const grid = page.getByRole("grid", { name: /Template grid/ });
  await expect(grid).toBeVisible({ timeout: 60000 });
  await grid.locator("td").nth(1).click();          // A1
  await page.keyboard.type("Invoice No");
  await page.keyboard.press("Tab");                 // commit, move to B1
  await page.keyboard.press("Tab");                 // C1
  await page.keyboard.type("Total");
  await page.keyboard.press("Enter");               // commit, move down
  // focus stayed in the editor, no tab character was inserted anywhere
  const active = await page.evaluate(() => document.activeElement?.getAttribute("role"));
  expect(active).toBe("grid");
  const texts = await grid.locator("td").allInnerTexts();
  expect(texts.join("|")).toContain("Invoice No");
  expect(texts.join("|")).toContain("Total");
  expect(texts.join("|")).not.toContain("\t");
  expect(errors.filter(e => !/favicon|DevTools/.test(e))).toEqual([]);
});

test("Shift+Tab at the first column lets focus leave (no trap)", async ({ page }) => {
  await login(page);
  await page.goto("/templates/new");
  const grid = page.getByRole("grid", { name: /Template grid/ });
  await expect(grid).toBeVisible({ timeout: 60000 });
  await grid.locator("td").nth(1).click();
  await page.keyboard.press("Shift+Tab");
  const role = await page.evaluate(() => document.activeElement?.getAttribute("role"));
  expect(role).not.toBe("grid");
});

test("Enter on Save saves (the grid does not swallow it); errors show by the field", async ({ page }) => {
  await login(page);
  await page.goto("/templates/new");
  const grid = page.getByRole("grid", { name: /Template grid/ });
  await expect(grid).toBeVisible({ timeout: 60000 });
  await page.getByLabel("Template name").fill("");
  await page.getByRole("button", { name: /Save template/ }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("alert").filter({ hasText: "Give the template a name" })).toBeVisible();
});

test("leaving with unsaved edits asks first", async ({ page }) => {
  await login(page);
  await page.goto("/templates/new");
  const grid = page.getByRole("grid", { name: /Template grid/ });
  await expect(grid).toBeVisible({ timeout: 60000 });
  await grid.locator("td").nth(1).click();
  await page.keyboard.type("Label");
  await page.keyboard.press("Enter");
  let asked = "";
  page.once("dialog", d => { asked = d.message(); d.dismiss(); });
  await page.getByRole("button", { name: "Cancel" }).click();
  expect(asked).toMatch(/unsaved/);
  await expect(page).toHaveURL(/templates\/new/);
});
