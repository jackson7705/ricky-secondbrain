/**
 * Upload a PDF to QuickBooks and link it to a bill.
 *
 * Run via `composio run --file qbo_upload.ts`, which injects `proxy()` — a
 * fetch() already bound to the connected QuickBooks account. This exists
 * because neither route below works:
 *   - Composio has no QuickBooks upload tool (UPDATE_ATTACHABLE only edits
 *     metadata on an attachment that already exists).
 *   - `composio proxy` JSON-encodes its request body, so it cannot send the
 *     multipart/form-data the upload endpoint requires.
 *
 * Config is read from qbo_upload_input.json so no data is passed on argv.
 */

const input = await Bun.file("qbo_upload_input.json").json();
const { companyId, billId, filePath, fileName, note } = input;

const bytes = await Bun.file(filePath).arrayBuffer();

const metadata = {
  AttachableRef: [{ EntityRef: { type: "Bill", value: String(billId) } }],
  FileName: fileName,
  ContentType: "application/pdf",
  Category: "Document",
  ...(note ? { Note: note } : {}),
};

// Build the multipart body by hand. Handing fetch() a FormData lets the proxy
// wrapper replace the auto-generated Content-Type, which QuickBooks rejects
// with 415 — so the boundary is declared explicitly instead.
// QuickBooks pairs the parts by their shared _01 suffix.
const boundary = `----airsense${crypto.randomUUID().replace(/-/g, "")}`;
const encoder = new TextEncoder();

const head = (disposition: string, contentType: string) =>
  encoder.encode(
    `--${boundary}\r\nContent-Disposition: ${disposition}\r\nContent-Type: ${contentType}\r\n\r\n`,
  );

const chunks: Uint8Array[] = [
  head('form-data; name="file_metadata_01"', "application/json"),
  encoder.encode(JSON.stringify(metadata)),
  encoder.encode("\r\n"),
  head(
    `form-data; name="file_content_01"; filename="${fileName}"`,
    "application/pdf",
  ),
  new Uint8Array(bytes),
  encoder.encode(`\r\n--${boundary}--\r\n`),
];

const body = new Uint8Array(chunks.reduce((n, c) => n + c.length, 0));
let offset = 0;
for (const chunk of chunks) {
  body.set(chunk, offset);
  offset += chunk.length;
}

const qbo = await proxy("quickbooks");
const response = await qbo(
  `https://quickbooks.api.intuit.com/v3/company/${companyId}/upload?minorversion=75`,
  {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": `multipart/form-data; boundary=${boundary}`,
    },
    body,
  },
);

const text = await response.text();
let parsed: any;
try {
  parsed = JSON.parse(text);
} catch {
  console.log(JSON.stringify({ ok: false, status: response.status, body: text.slice(0, 400) }));
  process.exit(1);
}

const entry = parsed?.AttachableResponse?.[0];
if (entry?.Attachable?.Id) {
  console.log(JSON.stringify({ ok: true, attachableId: entry.Attachable.Id }));
} else {
  console.log(
    JSON.stringify({ ok: false, status: response.status, fault: entry?.Fault ?? parsed }),
  );
  process.exit(1);
}
