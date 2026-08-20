// Pure-logic unit tests for VL-D4's Voice Processing state layer:
// state/processing-model.js's ProcessingProfileStore/ProcessingQueueStore/
// ProcessingHistoryStore, and the PROCESSING_FEEDBACK addition to
// state/review-model.js's FeedbackStore. No browser needed — see
// processing.test.mjs for the real-browser workspace/component scenarios
// (VL-D4 §36).
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  ProcessingProfileStore,
  ProcessingQueueStore,
  ProcessingHistoryStore,
  ProcessingStatus,
  ProcessingDecision,
  ProcessingFeedbackCategory,
  isTerminalProcessingStatus,
  exportProcessingPlan,
} from "../state/processing-model.js";
import { FeedbackStore, FeedbackType } from "../state/review-model.js";

test("ProcessingProfileStore.create refuses a duplicate name", () => {
  const store = new ProcessingProfileStore();
  store.create("default");
  assert.throws(() => store.create("default"), /already exists/);
});

test("ProcessingProfileStore.createVersion always appends, never edits", () => {
  const store = new ProcessingProfileStore();
  const v1 = store.create("default", { notes: "first" });
  const v2 = store.createVersion("default", { notes: "second" });
  assert.equal(v1.version, 1);
  assert.equal(v2.version, 2);
  assert.deepEqual(store.history("default"), [v1, v2]);
  assert.equal(v1.notes, "first", "the original object must be untouched");
});

test("ProcessingProfileStore.duplicate creates an independent named profile", () => {
  const store = new ProcessingProfileStore();
  store.create("source", { notes: "original" });
  const copy = store.duplicate("source", "copy");
  assert.equal(copy.name, "copy");
  assert.equal(copy.version, 1);
  assert.equal(copy.notes, "original");
  store.createVersion("source");
  assert.equal(store.latest("copy").version, 1, "versioning one must not affect the other");
});

test("ProcessingProfileStore.setDefault/default reflect the latest version", () => {
  const store = new ProcessingProfileStore();
  store.create("a");
  store.create("b");
  store.setDefault("b");
  assert.equal(store.default().name, "b");
  store.createVersion("b");
  assert.equal(store.default().version, 2);
});

test("ProcessingQueueStore.enqueue starts an item as QUEUED with zero progress", () => {
  const store = new ProcessingQueueStore();
  const profiles = new ProcessingProfileStore();
  const profile = profiles.create("default");
  const item = store.enqueue({ recordingId: "synthetic-rec-0001", profile });
  assert.equal(item.status, ProcessingStatus.QUEUED);
  assert.equal(item.progress, 0);
  assert.equal(isTerminalProcessingStatus(item.status), false);
});

test("ProcessingQueueStore.processOne replays the fixture outcome for a known recording", async () => {
  const store = new ProcessingQueueStore();
  const profiles = new ProcessingProfileStore();
  const profile = profiles.create("default");
  const item = store.enqueue({ recordingId: "synthetic-rec-0002", profile });
  const result = await store.processOne(item.itemId, { stepDelayMs: 1 });
  assert.equal(result.status, ProcessingStatus.WARNING);
  assert.equal(result.decision, ProcessingDecision.STANDARD_CONDITIONING);
  assert.ok(result.warnings.some((w) => w.includes("normalization unavailable")));
  assert.equal(isTerminalProcessingStatus(result.status), true);
});

test("ProcessingQueueStore.processOne is an honest generic outcome for an unknown recording", async () => {
  const store = new ProcessingQueueStore();
  const profiles = new ProcessingProfileStore();
  const profile = profiles.create("default");
  const item = store.enqueue({ recordingId: "not-a-real-fixture", profile });
  const result = await store.processOne(item.itemId, { stepDelayMs: 1 });
  assert.equal(result.status, ProcessingStatus.SUCCESS);
  assert.equal(result.decision, ProcessingDecision.NO_PROCESSING);
  assert.ok(result.warnings.some((w) => w.includes("not a real result")));
});

test("ProcessingQueueStore.cancel only affects a still-queued item", async () => {
  const store = new ProcessingQueueStore();
  const profiles = new ProcessingProfileStore();
  const profile = profiles.create("default");
  const item = store.enqueue({ recordingId: "synthetic-rec-0001", profile });
  const cancelled = store.cancel(item.itemId);
  assert.equal(cancelled.status, ProcessingStatus.CANCELLED);
  const afterProcess = await store.processOne(item.itemId, { stepDelayMs: 1 });
  assert.equal(afterProcess.status, ProcessingStatus.CANCELLED, "processOne must be a no-op on a cancelled item");
});

test("ProcessingQueueStore.retry re-queues and re-runs an item, optionally with another profile", async () => {
  const store = new ProcessingQueueStore();
  const profiles = new ProcessingProfileStore();
  const profileA = profiles.create("a");
  const profileB = profiles.create("b");
  const item = store.enqueue({ recordingId: "synthetic-rec-0003", profile: profileA });
  await store.processOne(item.itemId, { stepDelayMs: 1 });
  assert.equal(store.get(item.itemId).status, ProcessingStatus.BLOCKED);

  const retried = await store.retry(item.itemId, { profile: profileB });
  assert.equal(store.get(item.itemId).profileId, profileB.profileId);
  assert.equal(retried.status, ProcessingStatus.BLOCKED, "the fixture outcome is the same regardless of profile");
});

test("ProcessingQueueStore.counts reflects real item statuses", async () => {
  const store = new ProcessingQueueStore();
  const profiles = new ProcessingProfileStore();
  const profile = profiles.create("default");
  const ok = store.enqueue({ recordingId: "synthetic-rec-0001", profile });
  const warn = store.enqueue({ recordingId: "synthetic-rec-0002", profile });
  await store.processOne(ok.itemId, { stepDelayMs: 1 });
  await store.processOne(warn.itemId, { stepDelayMs: 1 });
  const counts = store.counts();
  assert.equal(counts[ProcessingStatus.SUCCESS], 1);
  assert.equal(counts[ProcessingStatus.WARNING], 1);
});

test("ProcessingHistoryStore is append-only — a rollback never edits or deletes a prior record", async () => {
  const queue = new ProcessingQueueStore();
  const profiles = new ProcessingProfileStore();
  const profileA = profiles.create("a");
  const profileB = profiles.create("b");
  const history = new ProcessingHistoryStore();

  const item = queue.enqueue({ recordingId: "synthetic-rec-0001", profile: profileA });
  const result1 = await queue.processOne(item.itemId, { stepDelayMs: 1 });
  const rec1 = history.record({ recordingId: "synthetic-rec-0001", item: result1 });

  item.profileId = profileB.profileId;
  const result2 = await queue.processOne(item.itemId, { stepDelayMs: 1 });
  const rec2 = history.record({ recordingId: "synthetic-rec-0001", item: result2, supersedes: rec1.recordId });

  assert.equal(history.history("synthetic-rec-0001").length, 2);
  assert.equal(history.current("synthetic-rec-0001").recordId, rec2.recordId);

  const rolledBack = history.rollback("synthetic-rec-0001", rec1.recordId);
  assert.equal(rolledBack.isRollback, true);
  assert.equal(rolledBack.supersedes, rec2.recordId);
  assert.equal(history.history("synthetic-rec-0001").length, 3, "rollback appends, it never removes a record");
  assert.equal(history.current("synthetic-rec-0001").recordId, rolledBack.recordId);
});

test("ProcessingHistoryStore.rollback to an unknown record throws rather than silently no-opping", () => {
  const history = new ProcessingHistoryStore();
  assert.throws(() => history.rollback("rec-x", "does-not-exist"));
});

test("exportProcessingPlan is an honest, non-authoritative session bridge", async () => {
  const queue = new ProcessingQueueStore();
  const profiles = new ProcessingProfileStore();
  const profile = profiles.create("default");
  const item = queue.enqueue({ recordingId: "synthetic-rec-0001", profile });
  await queue.processOne(item.itemId, { stepDelayMs: 1 });
  const history = new ProcessingHistoryStore();
  history.record({ recordingId: "synthetic-rec-0001", item: queue.get(item.itemId) });

  const plan = exportProcessingPlan(queue, history);
  assert.equal(plan.is_synthetic, true);
  assert.match(plan.generated_by, /session-only, not authoritative/);
  assert.equal(plan.processing_items.length, 1);
  assert.equal(plan.processing_history.length, 1);
});

test("PROCESSING_FEEDBACK is a valid FeedbackStore type carrying a validated category", () => {
  const store = new FeedbackStore();
  const record = store.record({
    feedbackType: FeedbackType.PROCESSING_FEEDBACK,
    targetId: "proc-hist-0001",
    attributes: { category: ProcessingFeedbackCategory.OVER_PROCESSED },
  });
  assert.equal(record.feedbackType, "PROCESSING_FEEDBACK");
  assert.equal(record.attributes.category, "OVER_PROCESSED");
});

test("processing feedback is never a speaker or training field", () => {
  const store = new FeedbackStore();
  const record = store.record({
    feedbackType: FeedbackType.PROCESSING_FEEDBACK,
    targetId: "proc-hist-0001",
    attributes: { category: ProcessingFeedbackCategory.GOOD_RESULT },
  });
  const keys = JSON.stringify(record).toLowerCase();
  assert.doesNotMatch(keys, /speaker/);
  assert.doesNotMatch(keys, /training_label/);
});
