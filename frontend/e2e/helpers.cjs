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
  page.on("response", r => { if (r.status() >= 400) errors.push(`HTTP ${r.status()} ${new URL(r.url()).pathname}`); });
  return errors;
}

module.exports = { creds, login, watchConsole };

/** A one-page PDF whose text is `lines` (Helvetica), built by hand: no
 *  dependency, and nothing but synthetic text. */
function makePdf(lines) {
  const esc = s => s.replace(/[\()]/g, m => "\\" + m);
  const body = "BT /F1 11 Tf " + lines.map((l, i) => `1 0 0 1 72 ${740 - 22 * i} Tm (${esc(l)}) Tj`).join(" ") + " ET";
  const objs = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    `<< /Length ${body.length} >>\nstream\n${body}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let out = "%PDF-1.4\n";
  const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` +
    offs.map(o => String(o).padStart(10, "0") + " 00000 n \n").join("") +
    `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  return Buffer.from(out, "latin1");
}

const INVOICE = ["ACME TRADING LTD", "Invoice No: INV-9001", "Invoice Date: 2024-03-15",
  "Bill To: Globex Corporation", "Total: $125.00"];

module.exports.makePdf = makePdf;
module.exports.INVOICE = INVOICE;

/** A multi-page PDF: one page per entry of `pages` (each a list of lines). */
function makePdfPages(pages) {
  const esc = s => s.replace(/[\()]/g, m => "\\" + m);
  const objs = ["<< /Type /Catalog /Pages 2 0 R >>", null,
                "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"];
  const kids = [];
  for (const lines of pages) {
    const body = "BT /F1 11 Tf " + lines.map((l, i) => `1 0 0 1 72 ${740 - 22 * i} Tm (${esc(l)}) Tj`).join(" ") + " ET";
    objs.push(`<< /Length ${body.length} >>\nstream\n${body}\nendstream`);
    const contents = objs.length;
    objs.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents ${contents} 0 R /Resources << /Font << /F1 3 0 R >> >> >>`);
    kids.push(`${objs.length} 0 R`);
  }
  objs[1] = `<< /Type /Pages /Kids [${kids.join(" ")}] /Count ${kids.length} >>`;
  let out = "%PDF-1.4\n";
  const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` +
    offs.map(o => String(o).padStart(10, "0") + " 00000 n \n").join("") +
    `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  return Buffer.from(out, "latin1");
}

/** The signed-in user's bearer token, read from the app's own storage. */
async function token(page) {
  return page.evaluate(() => localStorage.getItem("da_token"));
}

module.exports.makePdfPages = makePdfPages;
module.exports.token = token;
