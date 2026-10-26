const fs = require("fs");
const creds = () => JSON.parse(fs.readFileSync(process.env.E2E_CREDS, "utf-8"));

/** Sign in through the real form and wait for the app. */
async function login(page, who = "e2e_a") {
  const c = creds()[who];
  await page.goto("/login");
  await page.getByPlaceholder("admin").fill(c.username);
  await page.locator('input[type="password"]').first().fill(c.password);
  await page.locator("button.login-submit").click();
  await page.waitForURL(u => !u.pathname.startsWith("/login"), { timeout: 60000 });
}

/** Every console error and page error of a page, for "no console errors". */
function watchConsole(page) {
  const errors = [];
  page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", e => errors.push(String(e)));
  return errors;
}

module.exports = { creds, login, watchConsole };
