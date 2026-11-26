import assert from "node:assert/strict";
import { test } from "node:test";
import { deflateRawSync } from "node:zlib";
import { organizedWorkbookAvailable } from "./organizedExport.ts";

const type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const organized = 'attachment; filename="job_7_organized.xlsx"';

// Build the two ZIP entries the browser reads, compressed like an openpyxl export.
function workbook(sheets: string[], firstSheetText = "Invoice 7") {
  const entries = {
    "xl/workbook.xml": `<workbook><sheets>${sheets.map(name => `<sheet name="${name}"/>`).join("")}</sheets></workbook>`,
    "xl/worksheets/sheet1.xml": `<worksheet><sheetData><row><c><is><t>${firstSheetText}</t></is></c></row></sheetData></worksheet>`,
  };
  const files: Buffer[] = [];
  const directory: Buffer[] = [];
  let offset = 0;
  for (const [path, value] of Object.entries(entries)) {
    const name = Buffer.from(path);
    const data = deflateRawSync(value);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50);
    local.writeUInt16LE(8, 8);
    local.writeUInt32LE(data.length, 18);
    local.writeUInt16LE(name.length, 26);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50);
    central.writeUInt16LE(8, 10);
    central.writeUInt32LE(data.length, 20);
    central.writeUInt16LE(name.length, 28);
    central.writeUInt32LE(offset, 42);
    files.push(local, name, data);
    directory.push(central, name);
    offset += local.length + name.length + data.length;
  }
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50);
  end.writeUInt32LE(directory.reduce((size, part) => size + part.length, 0), 12);
  end.writeUInt32LE(offset, 16);
  return new Blob([new Uint8Array(Buffer.concat([...files, ...directory, end]))], { type });
}

test("valid organized workbooks keep successful documents even when others were skipped", async () => {
  assert.equal(await organizedWorkbookAvailable(workbook(["Invoice"]), organized), true);
  assert.equal(await organizedWorkbookAvailable(workbook(["Invoice", "Not organized", "Legend"]), organized), true);
  assert.equal(await organizedWorkbookAvailable(workbook(["Not organized", "Legend"]), organized), true);
});

test("a skipped-only workbook is unavailable even when the server returns HTTP 200", async () => {
  assert.equal(await organizedWorkbookAvailable(workbook(["Not organized", "Legend"], "Not laid out from the page"), organized), false);
  assert.equal(await organizedWorkbookAvailable(workbook(["Not organized"], ""), organized), false);
});

test("regular replies, empty replies and truncated archives never download as organized", async () => {
  const blob = workbook(["Invoice"]);
  assert.equal(await organizedWorkbookAvailable(blob, 'attachment; filename="job_7_results.xlsx"'), false);
  assert.equal(await organizedWorkbookAvailable(blob), false);
  assert.equal(await organizedWorkbookAvailable(new Blob([], { type }), organized), false);
  assert.equal(await organizedWorkbookAvailable(blob.slice(0, blob.size - 22, type), organized), false);
});

test("a failed organized download says why", async () => {
  const { organizedFailureMessage } = await import("./organizedExport.ts");
  const reply = (detail: unknown) => new Blob([JSON.stringify({ detail })], { type: "application/json" });
  assert.match(await organizedFailureMessage(422, reply({ code: "no_text_layer" })), /no text layer/);
  assert.match(await organizedFailureMessage(422, reply({ code: "source_missing" })), /no longer stored/);
  assert.match(await organizedFailureMessage(422, reply({ code: "unreadable" })), /could not be read/);
  assert.match(await organizedFailureMessage(400, reply("layout is 'template' or 'organized'.")), /layout is/);
  assert.match(await organizedFailureMessage(500, reply("boom")), /server could not/);
  assert.match(await organizedFailureMessage(undefined, undefined), /server could not/);
});
