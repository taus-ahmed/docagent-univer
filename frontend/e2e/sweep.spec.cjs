// Part A8: every main page, laptop and tablet — console errors, failing
// requests, horizontal overflow, blank pages. Screenshots go to E2E_OUT.
const path = require("path");
const { test, expect } = require("@playwright/test");
const { login, watchConsole, creds } = require("./helpers.cjs");

const PAGES = ["/extract", "/history", "/templates", "/templates/new", "/admin", "/analytics"];
const SIZES = { laptop: { width: 1280, height: 800 }, tablet: { width: 820, height: 1180 } };
// "Failed to fetch RSC payload": next dev aborting a prefetch when the test navigates away
const IGNORE = /favicon|DevTools|Download the React|Failed to fetch RSC payload/;

for (const [size, vp] of Object.entries(SIZES)) {
  test(`every page renders cleanly (${size})`, async ({ page }) => {
    await page.setViewportSize(vp);
    const errors = watchConsole(page);
    await login(page);
    const problems = [];
    for (const p of PAGES) {
      await page.goto(p);
      await page.waitForLoadState("networkidle", { timeout: 60000 }).catch(() => {});
      await page.waitForTimeout(500);
      const text = (await page.locator("body").innerText()).trim();
      if (text.length < 20) problems.push(`${p}: page is blank`);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (overflow > 2) problems.push(`${p}: scrolls sideways by ${overflow}px`);
      await page.screenshot({ path: path.join(process.env.E2E_OUT || ".", "shots", `${size}${p.replace(/\//g, "_")}.png`) });
    }
    const bad = errors.filter(e => !IGNORE.test(e));
    expect({ problems, errors: bad }).toEqual({ problems: [], errors: [] });
  });
}

test("a one-time password forces a change before anything else", async ({ page }) => {
  const errors = watchConsole(page);
  await login(page, "one_time");
  await expect(page.getByText(/choose a new password|change your password|new password/i).first())
    .toBeVisible({ timeout: 30000 });
  expect(errors.filter(e => !IGNORE.test(e) && !/HTTP 403/.test(e))).toEqual([]);
});
