// Part A6: the Additional options panel — keyboard, prerequisites, memory.
const { test, expect } = require("@playwright/test");
const { login, watchConsole } = require("./helpers.cjs");

test("options toggle from the keyboard, explain prerequisites and are remembered", async ({ page }) => {
  const errors = watchConsole(page);
  await login(page);
  await page.goto("/extract");
  const group = page.getByRole("group", { name: "Additional options" });
  await expect(group).toBeVisible({ timeout: 60000 });
  const narrative = group.getByRole("checkbox").nth(3);
  await expect(narrative).toBeDisabled();
  await expect(group.getByText(/Turn on Summary first/)).toBeVisible();
  const summary = group.getByRole("checkbox").nth(2);
  await summary.focus();
  await page.keyboard.press("Space");
  await expect(summary).toBeChecked();
  await expect(narrative).toBeEnabled();
  await page.reload();
  await expect(page.getByRole("group", { name: "Additional options" }).getByRole("checkbox").nth(2))
    .toBeChecked({ timeout: 60000 });
  expect(errors.filter(e => !/favicon|DevTools|Download the React/.test(e))).toEqual([]);
});
