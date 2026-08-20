import { test } from "node:test";
import assert from "node:assert/strict";

import { createJob, isTerminal, JobStatus, JobStore } from "../state/job-model.js";
import { createActivityEvent, ActivityStore, ActivitySource, ActivitySeverity, fromCommandCenterEntry } from "../state/activity-model.js";
import { SelectionModel } from "../state/selection-model.js";
import { DESTINATIONS } from "../state/router.js";
import { buildClaudeContext, redactDeep } from "../state/claude-context.js";
import { NullCommandExecutor, CommandExecutionOutcome } from "../state/command-executor.js";

test("createJob requires id and type, and defaults status to QUEUED", () => {
  assert.throws(() => createJob({}));
  assert.throws(() => createJob({ id: "x" }));
  const job = createJob({ id: "job-1", type: "pipeline_run" });
  assert.equal(job.status, JobStatus.QUEUED);
  assert.equal(job.progress, null);
});

test("isTerminal is true only for success/failed/cancelled", () => {
  assert.ok(isTerminal(JobStatus.SUCCESS));
  assert.ok(isTerminal(JobStatus.FAILED));
  assert.ok(isTerminal(JobStatus.CANCELLED));
  assert.ok(!isTerminal(JobStatus.RUNNING));
  assert.ok(!isTerminal(JobStatus.QUEUED));
  assert.ok(!isTerminal(JobStatus.BLOCKED));
});

test("JobStore separates current/recent/failed and fires change events", () => {
  const store = new JobStore();
  let changeCount = 0;
  store.addEventListener("change", () => changeCount++);

  store.upsert(createJob({ id: "j1", type: "t", status: JobStatus.RUNNING }));
  store.upsert(createJob({ id: "j2", type: "t", status: JobStatus.SUCCESS, endTime: "2026-01-01T00:00:00Z" }));
  store.upsert(createJob({ id: "j3", type: "t", status: JobStatus.FAILED, endTime: "2026-01-02T00:00:00Z" }));

  assert.equal(changeCount, 3);
  assert.deepEqual(store.current().map((j) => j.id), ["j1"]);
  assert.equal(store.failed().length, 1);
  assert.equal(store.recent().length, 2);
  assert.equal(store.get("j1").id, "j1");
  assert.equal(store.get("does-not-exist"), null);
});

test("createActivityEvent requires id, summary, source and defaults severity to info", () => {
  assert.throws(() => createActivityEvent({}));
  const event = createActivityEvent({ id: "a1", summary: "s", source: ActivitySource.SYSTEM });
  assert.equal(event.severity, ActivitySeverity.INFO);
  assert.ok(event.timestamp);
});

test("ActivityStore.list sorts newest-first and filters by source/severity/limit", () => {
  const store = new ActivityStore();
  store.append(createActivityEvent({ id: "a1", summary: "old", source: ActivitySource.IMPORT, timestamp: "2026-01-01T00:00:00Z" }));
  store.append(createActivityEvent({ id: "a2", summary: "new", source: ActivitySource.CLAUDE, severity: ActivitySeverity.DANGER, timestamp: "2026-01-02T00:00:00Z" }));

  const all = store.list();
  assert.deepEqual(all.map((e) => e.id), ["a2", "a1"]);
  assert.deepEqual(store.list({ source: ActivitySource.IMPORT }).map((e) => e.id), ["a1"]);
  assert.deepEqual(store.list({ severity: ActivitySeverity.DANGER }).map((e) => e.id), ["a2"]);
  assert.equal(store.list({ limit: 1 }).length, 1);
});

test("fromCommandCenterEntry reshapes an ActivityEntry.to_dict() record without inventing fields", () => {
  const entry = {
    kind: "enrollment_created",
    summary: "enrollment_created · profile-1",
    timestamp: "2026-01-01T00:00:00Z",
    subject_id: "profile-1",
    detail: {},
  };
  const event = fromCommandCenterEntry(entry);
  assert.equal(event.source, ActivitySource.SYSTEM);
  assert.equal(event.status, "enrollment_created");
  assert.equal(event.details, null);
});

test("SelectionModel.select/clear fire change events with the right detail", () => {
  const model = new SelectionModel();
  const events = [];
  model.addEventListener("change", (e) => events.push(e.detail));

  model.select("batch", "b1", { id: "b1" });
  assert.equal(model.get().kind, "batch");
  model.clear();
  assert.equal(model.get(), null);
  assert.equal(events.length, 2);
  assert.equal(events[1], null);
});

test("router DESTINATIONS matches the VL-D1 11 workspaces plus VL-D3's Dataset Review addition exactly", () => {
  assert.deepEqual(DESTINATIONS, [
    "command-center",
    "import",
    "batches",
    "recordings",
    "review",
    "pipeline",
    "voices",
    "models",
    "calibration",
    "claude",
    "activity",
    "settings",
  ]);
});

test("redactDeep masks fields whose name looks like a secret, regardless of value", () => {
  const redacted = redactDeep({ api_key: "not-actually-secret", nested: { password: "hunter2" } });
  assert.equal(redacted.api_key, "<redacted: field name suggests a secret>");
  assert.equal(redacted.nested.password, "<redacted: field name suggests a secret>");
});

test("redactDeep masks long opaque-looking string values even under an innocuous key", () => {
  const longOpaque = "a".repeat(40);
  const redacted = redactDeep({ note: `see token=${longOpaque} in the log` });
  assert.ok(redacted.note.includes("<redacted>"));
  assert.ok(!redacted.note.includes(longOpaque));
});

test("redactDeep leaves short strings (e.g. git short hashes) alone", () => {
  const redacted = redactDeep({ head_short: "510acbe" });
  assert.equal(redacted.head_short, "510acbe");
});

test("buildClaudeContext bounds recent_activity to 10 entries and only keeps the documented fields", () => {
  const manyEvents = Array.from({ length: 25 }, (_, i) =>
    createActivityEvent({ id: `a${i}`, summary: `event ${i}`, source: ActivitySource.SYSTEM, timestamp: `2026-01-${String(i + 1).padStart(2, "0")}T00:00:00Z` }),
  );
  const context = buildClaudeContext({ destination: "pipeline", recentActivity: manyEvents });
  assert.equal(context.recent_activity.length, 10);
  assert.deepEqual(Object.keys(context.recent_activity[0]).sort(), ["severity", "source", "summary", "timestamp"]);
});

test("buildClaudeContext never includes a field outside the declared context model shape", () => {
  const context = buildClaudeContext({ destination: "batches", selection: { kind: "batch", id: "b1", data: { id: "b1", secret_field: "x" } } });
  // Selection data is passed through as-is per the interface (VL-D0's
  // claude-context-model.json), but redaction still applies to it.
  assert.equal(context.selection.data.secret_field, "<redacted: field name suggests a secret>");
  assert.deepEqual(Object.keys(context).sort(), [
    "active_view",
    "error_summary",
    "git_state",
    "permissions",
    "recent_activity",
    "recent_commands",
    "selection",
    "task_id",
  ]);
});

test("NullCommandExecutor is honest: unavailable, and execute() reports NOT_AVAILABLE without fabricating output", async () => {
  const executor = new NullCommandExecutor();
  assert.equal(executor.available(), false);
  const result = await executor.execute("run the tests");
  assert.equal(result.outcome, CommandExecutionOutcome.NOT_AVAILABLE);
  assert.equal(result.output, null);
  assert.ok(result.error.length > 0);
});
