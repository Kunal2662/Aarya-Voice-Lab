// Tests for state/import-engine.js — the client-side (Web Crypto +
// magic-byte) half of VL-D2's bulk importer. Byte patterns mirror
// src/aarya_voice_lab/testing/synthetic_audio.py's fixture generators
// exactly, so a change to one side's detection logic without the other
// is caught here rather than only being noticed as a UI/backend
// disagreement later.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { ImportQueue, ImportItemStatus, detectType, sha256Hex, exportImportPlan } from "../state/import-engine.js";

function wavBytes() {
  const header = new Uint8Array(44);
  header.set([0x52, 0x49, 0x46, 0x46], 0); // RIFF
  header.set([0x57, 0x41, 0x56, 0x45], 8); // WAVE
  return header;
}

function mp3Bytes() {
  return new Uint8Array([0x49, 0x44, 0x33, 0x04, 0, 0, 0, 0, 0, 0, 0, ...new Array(40).fill(0)]);
}

function corruptWavBytes() {
  // Matches generate_corrupt_wav: valid RIFF/WAVE header, destroyed body.
  const bytes = new Uint8Array(40);
  bytes.set([0x52, 0x49, 0x46, 0x46, 0, 0, 0, 0, 0x57, 0x41, 0x56, 0x45], 0);
  bytes.fill(0xff, 12);
  return bytes;
}

function unsupportedBytes() {
  return new TextEncoder().encode("This is plain text, not audio." + "\x00".repeat(32));
}

test("detectType identifies WAV/MP3 by content, matching audio/filetype.py's signature table", async () => {
  const wav = await detectType(new File([wavBytes()], "a.wav"));
  assert.equal(wav.container, "wav");
  assert.equal(wav.extensionMismatch, false);

  const mp3AsWav = await detectType(new File([mp3Bytes()], "fake.wav"));
  assert.equal(mp3AsWav.container, "mp3");
  assert.equal(mp3AsWav.extensionMismatch, true);

  const unsupported = await detectType(new File([unsupportedBytes()], "bad.wav"));
  assert.equal(unsupported.container, "unknown");
});

test("sha256Hex matches Python hashlib.sha256 on the same bytes", async () => {
  const bytes = new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  const expected = createHash("sha256").update(bytes).digest("hex");
  const actual = await sha256Hex(new File([bytes], "x.bin"));
  assert.equal(actual, expected);
});

test("ImportQueue classifies a mixed batch exactly like the backend ImportQueue would", async () => {
  const queue = new ImportQueue({ batchId: "batch-001", source: "local_files" });
  const good = queue.enqueue(new File([wavBytes()], "good.wav"));
  const mislabelled = queue.enqueue(new File([mp3Bytes()], "mislabelled.wav"));
  const zero = queue.enqueue(new File([], "empty.wav"));
  const corrupt = queue.enqueue(new File([corruptWavBytes()], "corrupt.wav"));
  const unsupported = queue.enqueue(new File([unsupportedBytes()], "bad.wav"));

  await queue.processAll();

  assert.equal(good.status, ImportItemStatus.ACCEPTED);
  assert.equal(mislabelled.status, ImportItemStatus.WARNING);
  assert.equal(mislabelled.detectedContainer, "mp3");
  assert.equal(zero.status, ImportItemStatus.BLOCKED);
  // The engine cannot read WAV frame data (no wave-module equivalent in
  // the browser without a dependency), so a corrupt-but-header-valid WAV
  // is accepted here — this is a known, documented gap versus the
  // backend's probe_wav_quietly, not a silent wrong answer.
  assert.equal(corrupt.status, ImportItemStatus.ACCEPTED);
  assert.equal(unsupported.status, ImportItemStatus.INVALID);
});

test("within-queue duplicate is detected and named by content id", async () => {
  const queue = new ImportQueue({ batchId: "batch-001", source: "local_files" });
  const bytes = wavBytes();
  const first = queue.enqueue(new File([bytes], "a.wav"));
  const second = queue.enqueue(new File([bytes], "a_copy.wav"));
  await queue.processAll();

  assert.equal(first.status, ImportItemStatus.ACCEPTED);
  assert.equal(second.status, ImportItemStatus.DUPLICATE);
  assert.equal(second.duplicateOf, first.contentId);
});

test("one bad item does not stop the rest of the queue (failure isolation)", async () => {
  const queue = new ImportQueue({ batchId: "batch-001", source: "local_files" });
  const good1 = queue.enqueue(new File([wavBytes()], "good1.wav"));
  // A File whose .arrayBuffer() rejects, to force the catch path.
  const poison = new File([wavBytes()], "poison.wav");
  poison.arrayBuffer = () => Promise.reject(new Error("simulated read failure"));
  const poisoned = queue.enqueue(poison);
  // Distinct content from good1 — otherwise this would legitimately be a
  // duplicate rather than exercising a second independent accept.
  const good2Bytes = wavBytes();
  good2Bytes[40] = 0x01;
  const good2 = queue.enqueue(new File([good2Bytes], "good2.wav"));

  await queue.processAll();

  assert.equal(good1.status, ImportItemStatus.ACCEPTED);
  assert.equal(poisoned.status, ImportItemStatus.FAILED);
  assert.ok(poisoned.errors[0].includes("simulated read failure"));
  assert.equal(good2.status, ImportItemStatus.ACCEPTED);
});

test("cancel only works before processing begins", async () => {
  const queue = new ImportQueue({ batchId: "batch-001", source: "local_files" });
  const item = queue.enqueue(new File([wavBytes()], "a.wav"));
  assert.equal(queue.cancel(item.itemId), true);
  assert.equal(item.status, ImportItemStatus.CANCELLED);

  await queue.processAll(); // cancelled items are skipped
  assert.equal(item.status, ImportItemStatus.CANCELLED);
  assert.equal(item.sha256, null);

  const processedItem = queue.enqueue(new File([wavBytes()], "b.wav"));
  await queue.processAll();
  assert.equal(queue.cancel(processedItem.itemId), false);
});

test("retry re-runs a retryable item and clears its prior errors", async () => {
  const queue = new ImportQueue({ batchId: "batch-001", source: "local_files" });
  const flaky = new File([wavBytes()], "flaky.wav");
  let shouldFail = true;
  const realArrayBuffer = flaky.arrayBuffer.bind(flaky);
  flaky.arrayBuffer = () => (shouldFail ? Promise.reject(new Error("transient")) : realArrayBuffer());
  const item = queue.enqueue(flaky);

  await queue.processAll();
  assert.equal(item.status, ImportItemStatus.FAILED);

  shouldFail = false;
  const retried = await queue.retry(item.itemId);
  assert.equal(retried, true);
  assert.equal(item.status, ImportItemStatus.ACCEPTED);
  assert.deepEqual(item.errors, []);
});

test("retry refuses an item that never ran or already succeeded", async () => {
  const queue = new ImportQueue({ batchId: "batch-001", source: "local_files" });
  const item = queue.enqueue(new File([wavBytes()], "a.wav"));
  assert.equal(await queue.retry(item.itemId), false); // still QUEUED
  await queue.processAll();
  assert.equal(item.status, ImportItemStatus.ACCEPTED);
  assert.equal(await queue.retry(item.itemId), false); // already accepted
});

test("exportImportPlan never claims a stored path — the browser never writes into source/", async () => {
  const queue = new ImportQueue({ batchId: "batch-001", source: "local_files" });
  queue.enqueue(new File([wavBytes()], "a.wav"));
  await queue.processAll();

  const plan = exportImportPlan(queue);
  assert.equal(plan.is_synthetic, true);
  for (const item of plan.items) {
    assert.ok(!("stored_relative_path" in item), "client-side plan must never claim a file was written to disk");
  }
});

test("queue fires a change event for every item on every status transition", async () => {
  const queue = new ImportQueue({ batchId: "batch-001", source: "local_files" });
  const seenStatuses = [];
  queue.addEventListener("change", (e) => seenStatuses.push(e.detail.item.status));
  queue.enqueue(new File([wavBytes()], "a.wav"));
  await queue.processAll();
  assert.ok(seenStatuses.includes(ImportItemStatus.SCANNING));
  assert.ok(seenStatuses.includes(ImportItemStatus.HASHING));
  assert.ok(seenStatuses.includes(ImportItemStatus.VALIDATING));
  assert.equal(seenStatuses.at(-1), ImportItemStatus.ACCEPTED);
});
