// Pure-logic unit tests for VL-D5's Voice Preview + Generation state
// layer: state/generation-model.js's VoiceProfileStore/
// GenerationModelStore/GenerationQueueStore/PreviewHistoryStore/
// PreviewFeedbackStore, buildPreviewRequest/validateGenerationRequest/
// estimateGenerationRequirements/buildAbComparison. No browser needed —
// see preview.test.mjs for the real-browser workspace/component
// scenarios (VL-D5 §36).
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  VoiceProfileStore,
  GenerationModelStore,
  GenerationQueueStore,
  PreviewHistoryStore,
  PreviewFeedbackStore,
  GenerationBackendState,
  GenerationStatus,
  VoiceProfileState,
  PreviewFeedbackOutcome,
  PreviewFeedbackCategory,
  UnlistenedFeedbackError,
  GENERATION_CONTROLS,
  MAX_TEXT_LENGTH,
  SUPPORTED_SAMPLE_RATES,
  buildPreviewRequest,
  validateGenerationRequest,
  estimateGenerationRequirements,
  buildAbComparison,
  isTerminalGenerationStatus,
  exportGenerationPlan,
} from "../state/generation-model.js";

const AVAILABLE_MODEL = Object.freeze({
  model_id: "synthetic-tone-v1",
  name: "Synthetic Tone",
  version: "0.1.0",
  backend: "cpu",
  capabilities: ["speed", "seed", "output_format"],
  requirements: null,
  status: GenerationBackendState.AVAILABLE,
});

const UNAVAILABLE_MODEL = Object.freeze({
  model_id: "unavailable-model-v1",
  name: "Example Unavailable Backend",
  version: "0.0.0",
  backend: "cpu",
  capabilities: [],
  requirements: null,
  status: GenerationBackendState.UNAVAILABLE,
});

function modelStoreWithFixtures() {
  const store = new GenerationModelStore();
  store.register(AVAILABLE_MODEL);
  store.register(UNAVAILABLE_MODEL);
  return store;
}

test("VoiceProfileStore.create refuses a duplicate name", () => {
  const store = new VoiceProfileStore();
  store.create("demo-voice");
  assert.throws(() => store.create("demo-voice"), /already exists/);
});

test("VoiceProfileStore.createVersion always appends, never edits", () => {
  const store = new VoiceProfileStore();
  const v1 = store.create("demo-voice", { notes: "first" });
  const v2 = store.createVersion("demo-voice", { notes: "second" });
  assert.equal(v1.version, 1);
  assert.equal(v2.version, 2);
  assert.equal(store.history("demo-voice").length, 2);
  assert.equal(v1.notes, "first", "the original object must be untouched");
});

test("VoiceProfileStore.create defaults to SYNTHETIC_PROFILE and carries no speaker field", () => {
  const store = new VoiceProfileStore();
  const profile = store.create("demo-voice");
  assert.equal(profile.state, VoiceProfileState.SYNTHETIC_PROFILE);
  const keys = Object.keys(profile);
  for (const forbidden of ["speaker", "accent", "pronunciation", "prosody"]) {
    assert.ok(!keys.some((k) => k.toLowerCase().includes(forbidden)), `unexpected field: ${forbidden}`);
  }
});

test("GenerationModelStore.capabilitiesFor reports honest state for a registered and an unknown model", () => {
  const store = modelStoreWithFixtures();
  assert.equal(store.capabilitiesFor("synthetic-tone-v1").backend_state, GenerationBackendState.AVAILABLE);
  assert.equal(store.capabilitiesFor("unavailable-model-v1").backend_state, GenerationBackendState.UNAVAILABLE);
  assert.equal(store.capabilitiesFor("no-such-model").backend_state, GenerationBackendState.NOT_CONFIGURED);
});

test("GenerationModelStore.listByBackend filters by the vendor-neutral ComputeBackend value", () => {
  const store = modelStoreWithFixtures();
  assert.equal(store.listByBackend("cpu").length, 2);
  assert.equal(store.listByBackend("gpu").length, 0);
});

test("buildPreviewRequest produces the same config_hash for identical config regardless of request_id", () => {
  const a = buildPreviewRequest({ text: "hello", voiceProfileId: "p-1", modelId: "synthetic-tone-v1", seed: 7 });
  const b = buildPreviewRequest({ text: "different text", voiceProfileId: "p-1", modelId: "synthetic-tone-v1", seed: 7 });
  assert.notEqual(a.request_id, b.request_id, "request_id must never be reused");
  assert.equal(a.config_hash, b.config_hash, "config_hash must depend only on the config, not the text or request id");
});

test("validateGenerationRequest rejects an unavailable backend before checking anything else", () => {
  const capabilities = modelStoreWithFixtures().capabilitiesFor("unavailable-model-v1");
  const request = buildPreviewRequest({ text: "hello", voiceProfileId: "p-1", modelId: "unavailable-model-v1" });
  const errors = validateGenerationRequest(request, capabilities);
  assert.ok(errors.some((e) => /unavailable/.test(e)));
});

test("validateGenerationRequest rejects empty text, oversized text, unsupported sample rate, and unsupported controls", () => {
  const capabilities = modelStoreWithFixtures().capabilitiesFor("synthetic-tone-v1");

  const empty = buildPreviewRequest({ text: "   ", voiceProfileId: "p-1", modelId: "synthetic-tone-v1" });
  assert.ok(validateGenerationRequest(empty, capabilities).some((e) => /must not be empty/.test(e)));

  const tooLong = buildPreviewRequest({ text: "a".repeat(MAX_TEXT_LENGTH + 1), voiceProfileId: "p-1", modelId: "synthetic-tone-v1" });
  assert.ok(validateGenerationRequest(tooLong, capabilities).some((e) => /exceeds/.test(e)));

  const badRate = buildPreviewRequest({ text: "hi", voiceProfileId: "p-1", modelId: "synthetic-tone-v1", sampleRate: 8000 });
  assert.ok(validateGenerationRequest(badRate, capabilities).some((e) => /sample_rate/.test(e)));
  assert.ok(SUPPORTED_SAMPLE_RATES.includes(16000));

  const badControl = buildPreviewRequest({ text: "hi", voiceProfileId: "p-1", modelId: "synthetic-tone-v1", controls: { pitch: "high" } });
  assert.ok(validateGenerationRequest(badControl, capabilities).some((e) => /unsupported control/.test(e)));
});

test("estimateGenerationRequirements is an honest heuristic, never an exact claim", () => {
  const capabilities = modelStoreWithFixtures().capabilitiesFor("synthetic-tone-v1");
  const request = buildPreviewRequest({ text: "one two three four five", voiceProfileId: "p-1", modelId: "synthetic-tone-v1" });
  const info = estimateGenerationRequirements(request, capabilities);
  assert.equal(info.word_count, 5);
  assert.match(info.estimate_basis, /heuristic/);

  const unavailableCapabilities = modelStoreWithFixtures().capabilitiesFor("unavailable-model-v1");
  const unavailableInfo = estimateGenerationRequirements(request, unavailableCapabilities);
  assert.match(unavailableInfo.estimate_basis, /not available/);
});

test("GENERATION_CONTROLS is the full VL-D5 §12 surface", () => {
  assert.deepEqual(
    [...GENERATION_CONTROLS].sort(),
    ["expressiveness", "model", "output_format", "pitch", "seed", "speed", "style", "voice"],
  );
});

test("GenerationQueueStore.enqueue starts an item as QUEUED with zero progress", () => {
  const modelStore = modelStoreWithFixtures();
  const queue = new GenerationQueueStore({ modelStore });
  const request = buildPreviewRequest({ text: "hello", voiceProfileId: "p-1", modelId: "synthetic-tone-v1" });
  const item = queue.enqueue(request);
  assert.equal(item.status, GenerationStatus.QUEUED);
  assert.equal(item.progress, 0);
  assert.equal(isTerminalGenerationStatus(item.status), false);
});

test("GenerationQueueStore.processOne succeeds for a valid request against an available backend", async () => {
  const modelStore = modelStoreWithFixtures();
  const queue = new GenerationQueueStore({ modelStore });
  const request = buildPreviewRequest({ text: "hello world", voiceProfileId: "p-1", modelId: "synthetic-tone-v1", seed: 1 });
  const item = queue.enqueue(request);
  const result = await queue.processOne(item.item_id, { stepDelayMs: 1 });
  assert.equal(result.status, GenerationStatus.READY);
  assert.ok(result.artifact);
  assert.equal(result.artifact.kind, "synthetic_fixture");
  assert.equal(result.artifact.is_synthetic, true);
  assert.notEqual(result.artifact.kind, "generated_speech", "synthetic output must never be tagged GENERATED_SPEECH");
});

test("GenerationQueueStore.processOne reports BLOCKED, never a fabricated success, for an unavailable backend", async () => {
  const modelStore = modelStoreWithFixtures();
  const queue = new GenerationQueueStore({ modelStore });
  const request = buildPreviewRequest({ text: "hello", voiceProfileId: "p-1", modelId: "unavailable-model-v1" });
  const item = queue.enqueue(request);
  const result = await queue.processOne(item.item_id, { stepDelayMs: 1 });
  assert.equal(result.status, GenerationStatus.BLOCKED);
  assert.equal(result.artifact, null);
  assert.ok(result.errors.length);
});

test("GenerationQueueStore.processOne reports BLOCKED for an unregistered model id, never a silent success", async () => {
  const modelStore = new GenerationModelStore();
  const queue = new GenerationQueueStore({ modelStore });
  const request = buildPreviewRequest({ text: "hello", voiceProfileId: "p-1", modelId: "no-such-model" });
  const item = queue.enqueue(request);
  const result = await queue.processOne(item.item_id, { stepDelayMs: 1 });
  assert.equal(result.status, GenerationStatus.BLOCKED);
});

test("GenerationQueueStore.cancel only affects a still-queued item", async () => {
  const modelStore = modelStoreWithFixtures();
  const queue = new GenerationQueueStore({ modelStore });
  const request = buildPreviewRequest({ text: "hello", voiceProfileId: "p-1", modelId: "synthetic-tone-v1" });
  const item = queue.enqueue(request);
  const cancelled = queue.cancel(item.item_id);
  assert.equal(cancelled.status, GenerationStatus.CANCELLED);
  const afterProcess = await queue.processOne(item.item_id, { stepDelayMs: 1 });
  assert.equal(afterProcess.status, GenerationStatus.CANCELLED, "processOne must be a no-op on a cancelled item");
});

test("GenerationQueueStore.retry re-queues and re-runs a blocked item", async () => {
  const modelStore = modelStoreWithFixtures();
  const queue = new GenerationQueueStore({ modelStore });
  const request = buildPreviewRequest({ text: "hello", voiceProfileId: "p-1", modelId: "unavailable-model-v1" });
  const item = queue.enqueue(request);
  await queue.processOne(item.item_id, { stepDelayMs: 1 });
  assert.equal(queue.get(item.item_id).status, GenerationStatus.BLOCKED);
  const retried = await queue.retry(item.item_id);
  assert.equal(retried.status, GenerationStatus.BLOCKED, "the backend is still unavailable after retry");
});

test("GenerationQueueStore: one item's failure never stops the rest of the queue", async () => {
  const modelStore = modelStoreWithFixtures();
  const queue = new GenerationQueueStore({ modelStore });
  const bad = queue.enqueue(buildPreviewRequest({ text: "hello", voiceProfileId: "p-1", modelId: "unavailable-model-v1" }));
  const good = queue.enqueue(buildPreviewRequest({ text: "hello", voiceProfileId: "p-1", modelId: "synthetic-tone-v1" }));
  await queue.processOne(bad.item_id, { stepDelayMs: 1 });
  const result = await queue.processOne(good.item_id, { stepDelayMs: 1 });
  assert.equal(result.status, GenerationStatus.READY);
});

test("GenerationQueueStore.counts reflects real item statuses", async () => {
  const modelStore = modelStoreWithFixtures();
  const queue = new GenerationQueueStore({ modelStore });
  const ok = queue.enqueue(buildPreviewRequest({ text: "hello", voiceProfileId: "p-1", modelId: "synthetic-tone-v1" }));
  const blocked = queue.enqueue(buildPreviewRequest({ text: "hello", voiceProfileId: "p-1", modelId: "unavailable-model-v1" }));
  await queue.processOne(ok.item_id, { stepDelayMs: 1 });
  await queue.processOne(blocked.item_id, { stepDelayMs: 1 });
  const counts = queue.counts();
  assert.equal(counts[GenerationStatus.READY], 1);
  assert.equal(counts[GenerationStatus.BLOCKED], 1);
});

test("PreviewHistoryStore is append-only across regenerations, chained via supersedes", async () => {
  const modelStore = modelStoreWithFixtures();
  const queue = new GenerationQueueStore({ modelStore });
  const history = new PreviewHistoryStore();

  const item1 = queue.enqueue(buildPreviewRequest({ text: "first", voiceProfileId: "profile-a", modelId: "synthetic-tone-v1" }));
  const result1 = await queue.processOne(item1.item_id, { stepDelayMs: 1 });
  const rec1 = history.record(result1, { voiceProfileId: "profile-a" });

  const item2 = queue.enqueue(buildPreviewRequest({ text: "second", voiceProfileId: "profile-a", modelId: "synthetic-tone-v1" }));
  const result2 = await queue.processOne(item2.item_id, { stepDelayMs: 1 });
  const rec2 = history.record(result2, { voiceProfileId: "profile-a" });

  assert.equal(history.history("profile-a").length, 2);
  assert.equal(history.current("profile-a").record_id, rec2.record_id);
  assert.equal(rec2.supersedes, rec1.record_id);
  assert.equal(rec1.supersedes, null, "the first generation supersedes nothing");
  assert.equal(history.regenerationCount("profile-a"), 1);
});

test("PreviewHistoryStore.current is null for a voice profile that has never generated", () => {
  const history = new PreviewHistoryStore();
  assert.equal(history.current("never-generated"), null);
  assert.equal(history.regenerationCount("never-generated"), 0);
});

test("PreviewFeedbackStore refuses an ACCEPTED/REJECTED outcome recorded without listening", () => {
  const store = new PreviewFeedbackStore();
  assert.throws(
    () => store.record({ preview_id: "preview-1", listener: "operator", outcome: PreviewFeedbackOutcome.ACCEPTED, listened: false }),
    UnlistenedFeedbackError,
  );
  assert.throws(
    () => store.record({ preview_id: "preview-1", listener: "operator", outcome: PreviewFeedbackOutcome.REJECTED, listened: false }),
    UnlistenedFeedbackError,
  );
});

test("PreviewFeedbackStore allows REGENERATE/UNCERTAIN without listening first", () => {
  const store = new PreviewFeedbackStore();
  const regen = store.record({ preview_id: "preview-1", listener: "operator", outcome: PreviewFeedbackOutcome.REGENERATE, listened: false });
  assert.equal(regen.requests_regeneration, true);
  const uncertain = store.record({ preview_id: "preview-1", listener: "operator", outcome: PreviewFeedbackOutcome.UNCERTAIN, listened: false });
  assert.equal(uncertain.requests_regeneration, false);
});

test("PreviewFeedbackStore records a valid category and rejects an unknown one", () => {
  const store = new PreviewFeedbackStore();
  const record = store.record({
    preview_id: "preview-1",
    listener: "operator",
    outcome: PreviewFeedbackOutcome.ACCEPTED,
    listened: true,
    category: PreviewFeedbackCategory.NATURALNESS,
    rating: 4,
  });
  assert.equal(record.attributes.category, "NATURALNESS");
  assert.equal(record.attributes.rating, "4");
  assert.throws(() =>
    store.record({ preview_id: "preview-1", listener: "operator", outcome: PreviewFeedbackOutcome.ACCEPTED, listened: true, category: "NOT_REAL" }),
  );
});

test("PreviewFeedbackStore.countsByOutcome/countsByCategory reflect real records", () => {
  const store = new PreviewFeedbackStore();
  store.record({ preview_id: "p1", listener: "op", outcome: PreviewFeedbackOutcome.ACCEPTED, listened: true, category: PreviewFeedbackCategory.CLARITY });
  store.record({ preview_id: "p2", listener: "op", outcome: PreviewFeedbackOutcome.REJECTED, listened: true, category: PreviewFeedbackCategory.CLARITY });
  store.record({ preview_id: "p3", listener: "op", outcome: PreviewFeedbackOutcome.UNCERTAIN, listened: false });
  const byOutcome = store.countsByOutcome();
  assert.equal(byOutcome.accepted, 1);
  assert.equal(byOutcome.rejected, 1);
  assert.equal(byOutcome.uncertain, 1);
  const byCategory = store.countsByCategory();
  assert.equal(byCategory.CLARITY, 2);
});

test("buildAbComparison is metadata-only and never claims acoustic similarity", () => {
  const a = { duration_seconds: 4.0, sample_rate: 16000, kind: "synthetic_fixture", is_synthetic: true };
  const b = { duration_seconds: 4.4, sample_rate: 16000, kind: "synthetic_fixture", is_synthetic: true };
  const comparison = buildAbComparison(a, b);
  assert.equal(comparison.sample_rate_match, true);
  assert.equal(comparison.kind_match, true);
  assert.equal(comparison.both_synthetic, true);
  assert.match(comparison.duration_diff_seconds.toFixed(1), /0\.4/);
  assert.match(comparison.note, /no acoustic similarity claim/);
  assert.doesNotMatch(JSON.stringify(comparison).toLowerCase(), /similarity_score|match_percent/);
});

test("exportGenerationPlan is an honest, non-authoritative session bridge", async () => {
  const modelStore = modelStoreWithFixtures();
  const queue = new GenerationQueueStore({ modelStore });
  const history = new PreviewHistoryStore();
  const feedback = new PreviewFeedbackStore();

  const item = queue.enqueue(buildPreviewRequest({ text: "hello", voiceProfileId: "p-1", modelId: "synthetic-tone-v1" }));
  const result = await queue.processOne(item.item_id, { stepDelayMs: 1 });
  history.record(result, { voiceProfileId: "p-1" });
  feedback.record({ preview_id: result.artifact.preview_id, listener: "operator", outcome: PreviewFeedbackOutcome.UNCERTAIN, listened: false });

  const plan = exportGenerationPlan(queue, history, feedback);
  assert.equal(plan.is_synthetic, true);
  assert.match(plan.generated_by, /session-only, not authoritative/);
  assert.equal(plan.generation_items.length, 1);
  assert.equal(plan.preview_history.length, 1);
  assert.equal(plan.preview_feedback.length, 1);
});
