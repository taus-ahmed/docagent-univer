const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

// XLSX is a ZIP archive. Read just the requested entry instead of unpacking
// every worksheet. openpyxl writes stored or raw-deflate entries.
async function openWorkbook(blob: Blob) {
  const tailOffset = Math.max(0, blob.size - 65557);
  const tail = new DataView(await blob.slice(tailOffset).arrayBuffer());
  for (let end = tail.byteLength - 22; end >= 0; end--) {
    if (tail.getUint32(end, true) !== 0x06054b50 || end + 22 + tail.getUint16(end + 20, true) !== tail.byteLength) continue;
    const size = tail.getUint32(end + 12, true);
    const offset = tail.getUint32(end + 16, true);
    if (size < 46 || offset + size !== tailOffset + end) break;
    return { offset, directory: new DataView(await blob.slice(offset, offset + size).arrayBuffer()) };
  }
  throw new Error("Invalid workbook archive");
}

async function workbookEntry(blob: Blob, archive: Awaited<ReturnType<typeof openWorkbook>>, path: string) {
  const { directory, offset } = archive;
  for (let at = 0; at + 46 <= directory.byteLength;) {
    if (directory.getUint32(at, true) !== 0x02014b50) break;
    const nameLength = directory.getUint16(at + 28, true);
    const name = new TextDecoder().decode(new Uint8Array(directory.buffer, at + 46, nameLength));
    if (name === path) {
      const local = directory.getUint32(at + 42, true);
      const header = new DataView(await blob.slice(local, local + 30).arrayBuffer());
      if (header.getUint32(0, true) !== 0x04034b50) break;
      const start = local + 30 + header.getUint16(26, true) + header.getUint16(28, true);
      const end = start + directory.getUint32(at + 20, true);
      if (end > offset) break;
      const data = blob.slice(start, end);
      const compression = directory.getUint16(at + 10, true);
      if (compression === 0) return data.text();
      if (compression === 8) return new Response(data.stream().pipeThrough(new DecompressionStream("deflate-raw"))).text();
      break;
    }
    at += 46 + nameLength + directory.getUint16(at + 30, true) + directory.getUint16(at + 32, true);
  }
  throw new Error("Missing workbook entry");
}

export async function organizedWorkbookAvailable(blob: Blob, disposition?: string): Promise<boolean> {
  if (blob.type !== XLSX || !/\bfilename\s*=\s*"?job_\d+_organized\.xlsx"?\s*(?:;|$)/i.test(disposition ?? "")) return false;
  try {
    const archive = await openWorkbook(blob);
    const workbook = await workbookEntry(blob, archive, "xl/workbook.xml");
    const names = Array.from(workbook.matchAll(/<sheet\s+[^>]*\bname="([^"]*)"/g), match => match[1]);
    if (!names.includes("Not organized")) return names.length > 0;
    if (names.some(name => name !== "Not organized" && name !== "Legend")) return true;
    // The only sheets in an all-skipped export are the report and optional
    // legend. A real PDF named "Not organized.pdf" can use the same tab name.
    const sheet = await workbookEntry(blob, archive, "xl/worksheets/sheet1.xml");
    return /<t(?:\s[^>]*)?>[^<]+<\/t>/.test(sheet) && !sheet.includes("Not laid out from the page");
  } catch {
    return false;
  }
}

/** Why "Download Organized" produced no file, in the words the server gave.
 *  `status` is the HTTP status (undefined: no reply), `body` the error reply. */
export async function organizedFailureMessage(status?: number, body?: unknown): Promise<string> {
  let detail: unknown;
  try {
    const text = body instanceof Blob ? await body.text() : typeof body === "string" ? body : JSON.stringify(body ?? null);
    detail = (JSON.parse(text) as { detail?: unknown })?.detail;
  } catch { detail = undefined; }
  const code = typeof detail === "object" && detail ? (detail as { code?: unknown }).code : undefined;
  if (status === 422 && code === "no_text_layer") return "This document has no text layer (a scan or image), so it can't be laid out. Use Download Excel.";
  if (status === 422 && code === "source_missing") return "The uploaded file is no longer stored on the server, so it can't be laid out. Upload it again, or use Download Excel.";
  if (status === 422 && code === "unreadable") return "The uploaded file could not be read, so it can't be laid out. Use Download Excel.";
  if (typeof detail === "string" && status && status < 500) return detail;
  return "The server could not build the organized layout. Try again, or use Download Excel.";
}
