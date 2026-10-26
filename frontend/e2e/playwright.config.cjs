// Browser specs (Parts A7-A9). DEV ONLY: run against scripts/e2e/stack.py,
// with Playwright installed OUTSIDE the repo (scripts/e2e/README.md).
const path = require("path");
const fs = require("fs");
const creds = JSON.parse(fs.readFileSync(process.env.E2E_CREDS, "utf-8"));
module.exports = {
  testDir: __dirname,
  testMatch: /.*\.spec\.cjs$/,
  timeout: 120000,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: creds.web, trace: "off", screenshot: "only-on-failure" },
  outputDir: path.join(process.env.E2E_OUT || ".", "pw-results"),
};
