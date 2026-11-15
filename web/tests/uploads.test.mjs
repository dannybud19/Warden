import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { load } from "./load-typescript.mjs";

const { UploadQueue, prepareInitialUploads } = load("../src/lib/uploadQueue.ts");
const { UploadStatus } = load("../src/components/warden/UploadStatus.tsx");
const file = (name) => new File(["example evidence"], name, { type: "text/plain" });
const input = (name, kind = "document") => ({ file: file(name), kind, studentName: "Sam" });
const receipt = (id = "ev_1", error = null) => ({ case: {}, evidence_id: id, read_error: error });
const tick = () => new Promise((resolve) => setImmediate(resolve));
const ids = () => { let n = 0; return () => `00000000-0000-4000-8000-${String(++n).padStart(12, "0")}`; };
const storage = () => {
  const items = new Map();
  return { getItem: (key) => items.get(key) ?? null, setItem: (key, value) => items.set(key, value) };
};

test("partial failure keeps every filename visible and retry resends only the failed attachment", async () => {
  const calls = [];
  let fail = true;
  const queue = new UploadQueue(async (caseId, data) => {
    calls.push([caseId, data.file.name, data.requestId]);
    if (fail && data.file.name === "contract.txt") throw new TypeError("Failed to fetch");
    return receipt(`ev_${data.file.name}`);
  }, ids());
  queue.add("case_new", [input("chat.txt", "chat_export"), input("contract.txt", "contract")]);
  await tick();
  const [chat, contract] = queue.getSnapshot();
  assert.equal(chat.state, "saved");
  assert.equal(chat.hasFile, false);
  assert.equal(contract.state, "failed");
  assert.equal(contract.hasFile, false);
  assert.match(contract.message, /other uploads are kept/);
  fail = false;
  await queue.retry(contract.id);
  assert.equal(calls.length, 2); // the user must select the file again, even without a reload
  await queue.retry(contract.id, file("contract.txt"));
  assert.equal(queue.getSnapshot()[1].state, "saved");
  assert.deepEqual(calls.map((c) => c[1]), ["chat.txt", "contract.txt", "contract.txt"]);
  assert.equal(calls[1][2], calls[2][2]); // the server can recognise a lost-response retry
});

test("a second Retry click cannot start another request while one is in progress", async () => {
  let calls = 0;
  let complete;
  const queue = new UploadQueue(async () => {
    calls++;
    if (calls === 1) throw new Error("offline");
    return new Promise((resolve) => { complete = resolve; });
  }, ids());
  queue.add("case_1", [input("notes.txt")]);
  await tick();
  const id = queue.getSnapshot()[0].id;
  const retry = queue.retry(id, file("notes.txt"));
  await queue.retry(id, file("notes.txt"));
  assert.equal(calls, 2);
  complete(receipt());
  await retry;
});

test("reload preserves failures and labels, never file bytes, and requires reselection", async () => {
  const store = storage();
  const original = new UploadQueue(async () => { throw new Error("offline"); }, ids());
  original.restore(store);
  original.add("case_1", [input("email.pdf", "email")]);
  await tick();
  let calls = 0;
  const recovered = new UploadQueue(async () => { calls++; return receipt(); }, ids());
  recovered.restore(store);
  const row = recovered.getSnapshot()[0];
  assert.equal(row.hasFile, false);
  assert.equal(row.name, "email.pdf");
  await recovered.retry(row.id);
  assert.equal(calls, 0);
  await recovered.retry(row.id, file("different.pdf"));
  assert.equal(calls, 0);
  await recovered.retry(row.id, file("email.pdf"));
  assert.equal(calls, 1);
  assert.equal(recovered.getSnapshot()[0].state, "saved");
});

test("a reload during a request marks it interrupted without blindly uploading again", () => {
  const store = storage();
  const original = new UploadQueue(() => new Promise(() => {}), ids());
  original.restore(store);
  original.add("case_1", [input("chat.txt")]);
  const recovered = new UploadQueue(async () => assert.fail("no automatic reupload"), ids());
  recovered.restore(store);
  assert.equal(recovered.getSnapshot()[0].state, "interrupted");
  assert.equal(recovered.getSnapshot()[0].hasFile, false);
});

test("HTTP success with an extraction error is visibly unreadable, not successfully read", async () => {
  const queue = new UploadQueue(async () => receipt("ev_bad", "Upload a PDF with selectable text."), ids());
  queue.add("case_existing", [input("scan.pdf", "email")]);
  await tick();
  const row = queue.getSnapshot()[0];
  assert.equal(row.state, "unreadable");
  assert.equal(row.message, "Upload a PDF with selectable text.");
  assert.equal(row.evidenceId, "ev_bad");
});

test("a 409 shows the server's reason (an attachment conflict) and never claims a final decision", async () => {
  const reason = "This file does not match the initial attachment, or it was skipped.";
  const queue = new UploadQueue(async () => { throw Object.assign(new Error(reason), { status: 409 }); }, ids());
  queue.add("case_1", [input("contract.pdf", "contract")]);
  await tick();
  assert.equal(queue.getSnapshot()[0].state, "failed");
  assert.equal(queue.getSnapshot()[0].message, reason);
  assert.doesNotMatch(queue.getSnapshot()[0].message, /final decision|decided|verdict/i);
});

test("files added one after another, the same file twice, and several at once are all sent", async () => {
  const sent = [];
  const queue = new UploadQueue(async (_caseId, data) => {
    sent.push(data.file.name);
    return receipt(`ev_${sent.length}`);
  }, ids());
  queue.add("case_1", [input("chat.txt", "chat_export")]);
  await tick();
  queue.add("case_1", [input("chat.txt", "chat_export")]); // the same file picked again
  queue.add("case_1", [input("email.pdf", "email"), input("contract.pdf", "contract"), input("photo.png")]);
  await tick();
  assert.deepEqual(sent, ["chat.txt", "chat.txt", "email.pdf", "contract.pdf", "photo.png"]);
  assert.deepEqual(queue.getSnapshot().map((r) => r.state), ["saved", "saved", "saved", "saved", "saved"]);
});

test("stored video and audio do not claim that media analysis happened", async () => {
  const queue = new UploadQueue(async () => receipt(), ids());
  queue.add("case_1", [input("viewing.mp4", "video"), input("call.wav", "call_recording")]);
  await tick();
  assert.ok(queue.getSnapshot().every((row) => row.state === "saved" && /not available/.test(row.message)));
});

test("unavailable session storage does not prevent an upload", async () => {
  const queue = new UploadQueue(async () => receipt(), ids());
  queue.restore({ getItem() { throw new Error("denied"); }, setItem() { throw new Error("quota"); } });
  queue.add("case_1", [input("notes.txt")]);
  await tick();
  assert.equal(queue.getSnapshot()[0].state, "saved");
});

test("the live API path sends retry identity and reads an unreadable-file receipt", async (t) => {
  const { uploadEvidenceReceipt } = load("../src/lib/api.ts");
  const data = { ...input("scan.pdf", "email"), requestId: ids()(), note: "An email PDF", retryRead: true };
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.match(url, /\/cases\/case_1\/evidence\?include_receipt=true$/);
    assert.equal(options.method, "POST");
    assert.equal(options.body.get("kind"), "email");
    assert.equal(options.body.get("request_id"), data.requestId);
    assert.equal(options.body.get("student_name"), "Sam");
    assert.equal(options.body.get("note"), "An email PDF");
    assert.equal(options.body.get("retry_read"), "true");
    assert.equal(options.body.get("file").name, "scan.pdf");
    assert.equal(options.headers, undefined); // the browser supplies the multipart boundary
    assert.ok(options.signal instanceof AbortSignal);
    return Response.json(receipt("ev_scan", "Please upload selectable text."));
  });
  assert.equal((await uploadEvidenceReceipt("case_1", data)).read_error, "Please upload selectable text.");
});

test("initial files are reserved before case creation and uploads reuse exactly those identities", async () => {
  const prepared = prepareInitialUploads([input("chat.txt", "chat_export"), input("scan.pdf", "email")], ids());
  assert.equal(prepared.manifest.length, 2);
  assert.equal(new Set(prepared.manifest.map((r) => r.request_id)).size, 2);
  const sent = [];
  const queue = new UploadQueue(async (_, input) => { sent.push(input.requestId); return receipt(); });
  queue.add("case_1", prepared.inputs, true);
  assert.ok(queue.getSnapshot().every((r) => r.initial && r.pending));
  await tick();
  assert.deepEqual(sent, prepared.manifest.map((r) => r.request_id));
  assert.ok(queue.getSnapshot().every((r) => !r.pending));
});

test("server manifest restores a failed initial file without browser storage and only explicit skip releases it", async () => {
  const [item] = prepareInitialUploads([input("scan.pdf", "email")], ids()).manifest;
  const pending = { ...item, state: "pending", evidence_id: "ev_bad", read_error: "Could not read every page." };
  let skips = 0;
  const queue = new UploadQueue(async () => assert.fail("must not upload automatically"), ids(), async (caseId, id) => {
    skips++;
    assert.equal(caseId, "case_1");
    assert.equal(id, item.request_id);
    return [{ ...pending, state: "skipped" }];
  });
  queue.syncInitial("case_1", [pending]);
  const row = queue.getSnapshot()[0];
  assert.equal(row.state, "unreadable");
  assert.equal(row.pending, true);
  assert.equal(row.hasFile, false);
  assert.equal(skips, 0);
  await queue.continueWithout(row.id);
  assert.equal(skips, 1);
  assert.equal(queue.getSnapshot()[0].state, "skipped");
  assert.equal(queue.getSnapshot()[0].pending, false);
});

test("a failed skip keeps the hold and can be retried without reuploading successful files", async () => {
  const [item] = prepareInitialUploads([input("notes.txt")], ids()).manifest;
  const queue = new UploadQueue(async () => receipt(), ids(), async () => { throw new Error("offline"); });
  queue.syncInitial("case_1", [{ ...item, state: "pending", evidence_id: null, read_error: null }]);
  await queue.continueWithout(item.request_id);
  assert.equal(queue.getSnapshot()[0].pending, true);
  assert.match(queue.getSnapshot()[0].message, /case stays open/);
});

test("a lost response is recovered from the server without a duplicate upload", async () => {
  const prepared = prepareInitialUploads([input("notes.txt")], ids());
  const queue = new UploadQueue(async () => { throw new Error("lost response"); }, ids());
  queue.add("case_1", prepared.inputs, true);
  await tick();
  assert.equal(queue.getSnapshot()[0].state, "failed");
  queue.syncInitial("case_1", [{ ...prepared.manifest[0], state: "accepted", evidence_id: "ev_saved", read_error: null }]);
  assert.equal(queue.getSnapshot()[0].state, "saved");
  assert.equal(queue.getSnapshot()[0].pending, false);
  assert.equal(queue.getSnapshot()[0].evidenceId, "ev_saved");
  // An older GET finishing later must not resurrect a hold.
  queue.syncInitial("case_1", [{ ...prepared.manifest[0], state: "pending", evidence_id: null, read_error: null }]);
  assert.equal(queue.getSnapshot()[0].pending, false);
});

test("an unreadable file requires reselection and explicitly asks the backend to try extraction again", async () => {
  const calls = [];
  const queue = new UploadQueue(async (_, data) => {
    calls.push(data);
    return calls.length === 1 ? receipt("ev_1", "OCR unavailable") : receipt();
  }, ids());
  queue.add("case_1", [input("scan.pdf", "email")], true);
  await tick();
  const id = queue.getSnapshot()[0].id;
  await queue.retry(id);
  assert.equal(calls.length, 1);
  await queue.retry(id, file("scan.pdf"));
  assert.equal(calls[1].retryRead, true);
  assert.equal(queue.getSnapshot()[0].pending, false);
});

test("the attachment panel is collapsed by default: header, description, count and a chevron button", () => {
  const base = { id: "one", caseId: "case_1", name: "scan.pdf", size: 100, kind: "email", hasFile: false, initial: false, pending: false, message: null };
  const html = renderToStaticMarkup(createElement(UploadStatus, {
    rows: [{ ...base, state: "saved" }, { ...base, id: "two", name: "chat.txt", state: "saved" }],
    onRetry() {}, onSkip() {},
  }));
  assert.match(html, /<h2[^>]*><button type="button" aria-expanded="false" aria-controls="[^"]+"/);
  assert.match(html, /Your attachments/);
  assert.match(html, /Each file is listed here as it is added\./);
  assert.match(html, /2 files/);
  assert.match(html, /lucide-chevron-down/);
  assert.doesNotMatch(html, /scan\.pdf|chat\.txt/); // the list opens on click
});

test("the production attachment panel renders filenames, mandatory file pickers, and explicit skip controls", () => {
  const base = { id: "one", caseId: "case_1", name: "scan.pdf", size: 100, kind: "email", hasFile: false, initial: true, pending: true, message: "Could not read every page." };
  const html = renderToStaticMarkup(createElement(UploadStatus, {
    defaultOpen: true,
    rows: [
      { ...base, state: "unreadable" },
      { ...base, id: "two", name: "chat.txt", state: "saved", pending: false, message: "File added and text read." },
    ], onRetry() {}, onSkip() {},
  }));
  assert.match(html, /scan.pdf/);
  assert.match(html, /chat.txt/);
  assert.match(html, /Retry each file that needs attention, or continue without it/);
  assert.match(html, /Saved, but could not read/);
  assert.equal((html.match(/type="file"/g) ?? []).length, 1);
  assert.match(html, /aria-label="Select scan.pdf to retry"/);
  assert.match(html, /aria-label="Continue without scan.pdf"/);
  assert.doesNotMatch(html, /Continue without chat.txt/);
});
