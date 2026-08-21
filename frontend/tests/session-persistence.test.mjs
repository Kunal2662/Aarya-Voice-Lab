// Tests for state/session-persistence.js (VL-D9's local-only persistence
// adapter) and the hydrate()/reset() methods it drives on all six
// domain stores. Node has no browser localStorage global by default, so
// this file installs a minimal, real Web-Storage-compatible in-memory
// implementation before importing anything -- the adapter's own
// save/load/clear/version/malformed-data logic all runs for real against
// it; only the underlying storage medium is swapped for an equivalent
// in-memory Map, the same technique frontend/tools/serve.mjs's consumers
// use for anything else that needs a browser-only global under `node
// --test`.
import { test } from "node:test";
import assert from "node:assert/strict";

class FakeStorage {
  constructor() {
    this._data = new Map();
  }
  getItem(key) {
    return this._data.has(key) ? this._data.get(key) : null;
  }
  setItem(key, value) {
    this._data.set(key, String(value));
  }
  removeItem(key) {
    this._data.delete(key);
  }
  clear() {
    this._data.clear();
  }
}

globalThis.localStorage = new FakeStorage();

const {
  SessionPersistence,
  SessionNamespace,
  SESSION_SCHEMA_VERSION,
  isPersistenceAvailable,
  clearAllSessionData,
  hasAnySessionData,
} = await import("../state/session-persistence.js");

function resetStorage() {
  globalThis.localStorage = new FakeStorage();
}

// ---------------------------------------------------------------------
// SessionPersistence adapter
// ---------------------------------------------------------------------

test("SessionPersistence: save then load round-trips the exact payload", () => {
  resetStorage();
  const p = new SessionPersistence(SessionNamespace.IMPORT);
  const payload = { is_synthetic: true, items: [{ item_id: "a" }], counts: { accepted: 1 } };
  assert.equal(p.save(payload), true);
  assert.deepEqual(p.load(), payload);
});

test("SessionPersistence: load on an empty store returns null (honest empty state)", () => {
  resetStorage();
  const p = new SessionPersistence(SessionNamespace.REVIEW);
  assert.equal(p.load(), null);
  assert.equal(p.hasSession(), false);
});

test("SessionPersistence: clear removes the saved envelope", () => {
  resetStorage();
  const p = new SessionPersistence(SessionNamespace.PROCESSING);
  p.save({ processing_items: [] });
  assert.equal(p.hasSession(), true);
  assert.equal(p.clear(), true);
  assert.equal(p.hasSession(), false);
  assert.equal(p.load(), null);
});

test("SessionPersistence: malformed JSON in storage is refused, not thrown", () => {
  resetStorage();
  const p = new SessionPersistence(SessionNamespace.GENERATION);
  localStorage.setItem("avl-session-v1:generation", "{not valid json");
  assert.doesNotThrow(() => p.load());
  assert.equal(p.load(), null);
});

test("SessionPersistence: an envelope with the wrong shape is refused", () => {
  resetStorage();
  const p = new SessionPersistence(SessionNamespace.EVALUATION);
  localStorage.setItem("avl-session-v1:evaluation", JSON.stringify(["not", "an", "envelope"]));
  assert.equal(p.load(), null);

  localStorage.setItem("avl-session-v1:evaluation", JSON.stringify({ schema_version: SESSION_SCHEMA_VERSION }));
  assert.equal(p.load(), null, "an envelope missing `payload` must be refused");
});

test("SessionPersistence: an incompatible schema_version is refused, never guessed at", () => {
  resetStorage();
  const p = new SessionPersistence(SessionNamespace.CALIBRATION);
  localStorage.setItem(
    "avl-session-v1:calibration",
    JSON.stringify({ schema_version: SESSION_SCHEMA_VERSION + 1, namespace: "calibration", payload: { x: 1 } }),
  );
  assert.equal(p.load(), null);
});

test("SessionPersistence: an envelope written under a different namespace key is refused", () => {
  resetStorage();
  const p = new SessionPersistence(SessionNamespace.IMPORT);
  localStorage.setItem(
    "avl-session-v1:import",
    JSON.stringify({ schema_version: SESSION_SCHEMA_VERSION, namespace: "review", payload: { x: 1 } }),
  );
  assert.equal(p.load(), null);
});

test("SessionPersistence: unavailable localStorage degrades to honest false/null, never throws", () => {
  const savedStorage = globalThis.localStorage;
  try {
    // A storage object that exists but throws on every real operation --
    // e.g. Safari private browsing's historical behaviour.
    globalThis.localStorage = {
      getItem() {
        throw new Error("storage disabled");
      },
      setItem() {
        throw new Error("storage disabled");
      },
      removeItem() {
        throw new Error("storage disabled");
      },
    };
    const p = new SessionPersistence(SessionNamespace.IMPORT);
    assert.equal(isPersistenceAvailable(), false);
    assert.equal(p.isAvailable(), false);
    assert.doesNotThrow(() => p.save({ a: 1 }));
    assert.equal(p.save({ a: 1 }), false);
    assert.doesNotThrow(() => p.load());
    assert.equal(p.load(), null);
    assert.equal(p.hasSession(), false);
    assert.equal(p.clear(), false);

    delete globalThis.localStorage;
    assert.equal(isPersistenceAvailable(), false);
  } finally {
    globalThis.localStorage = savedStorage;
  }
});

test("SessionPersistence: saving the same payload twice is deterministic (same restored shape)", () => {
  resetStorage();
  const p = new SessionPersistence(SessionNamespace.PROCESSING);
  const payload = { processing_items: [{ itemId: "p-1", status: "SUCCESS" }], processing_history: [] };
  p.save(payload);
  const first = p.load();
  p.save(payload);
  const second = p.load();
  assert.deepEqual(first, second);
});

test("SessionPersistence: namespaces are isolated -- one store's data/clear never touches another's", () => {
  resetStorage();
  const importP = new SessionPersistence(SessionNamespace.IMPORT);
  const reviewP = new SessionPersistence(SessionNamespace.REVIEW);
  importP.save({ items: [1] });
  reviewP.save({ review_decisions: [2] });
  assert.notDeepEqual(importP.load(), reviewP.load());

  importP.clear();
  assert.equal(importP.load(), null);
  assert.deepEqual(reviewP.load(), { review_decisions: [2] }, "clearing one namespace must not clear another");
});

test("SessionPersistence.migrate: no schema version predates v1, so it is a documented no-op today", () => {
  resetStorage();
  const p = new SessionPersistence(SessionNamespace.CALIBRATION);
  assert.equal(p.migrate({ schema_version: 0, payload: {} }), null);
});

test("clearAllSessionData / hasAnySessionData: bounded to exactly this app's own namespaces", () => {
  resetStorage();
  new SessionPersistence(SessionNamespace.IMPORT).save({ a: 1 });
  new SessionPersistence(SessionNamespace.CALIBRATION).save({ b: 2 });
  localStorage.setItem("some-unrelated-app-key", "untouched");

  assert.equal(hasAnySessionData(), true);
  assert.equal(clearAllSessionData(), true);
  assert.equal(hasAnySessionData(), false);
  assert.equal(localStorage.getItem("some-unrelated-app-key"), "untouched", "must never remove an unrelated key");
});

// ---------------------------------------------------------------------
// Import store hydrate()/reset()
// ---------------------------------------------------------------------

test("ImportQueue.hydrate: restores only terminal items, excludes in-flight ones", async () => {
  resetStorage();
  const { ImportQueue, ImportItemStatus, exportImportPlan } = await import("../state/import-engine.js");
  const plan = {
    batch_id: "batch-restored",
    source: "local_files",
    items: [
      { item_id: "import-0001", original_filename: "a.wav", status: ImportItemStatus.ACCEPTED, sha256: "abc" },
      { item_id: "import-0002", original_filename: "b.wav", status: ImportItemStatus.HASHING },
      { item_id: "import-0003", original_filename: "/etc/passwd-looking-but-basename-only.wav", status: ImportItemStatus.FAILED, errors: ["x"] },
    ],
    counts: {},
  };
  const queue = new ImportQueue({ batchId: "batch-001", source: "local_files" });
  assert.equal(queue.hydrate(plan), true);
  assert.equal(queue.list().length, 2, "the mid-flight HASHING item must be excluded");
  assert.equal(queue.batchId, "batch-restored");
  const restored = queue.list().find((i) => i.itemId === "import-0001");
  assert.equal(restored.restored, true);

  // A restored item has no backing File -- retry() must refuse, not throw.
  const retried = await queue.retry("import-0003");
  assert.equal(retried, false);
  assert.match(queue.items.get("import-0003").errors.at(-1), /restored item/);

  queue.reset();
  assert.equal(queue.list().length, 0);

  // exportImportPlan() on an empty queue is itself a valid (empty) plan.
  assert.deepEqual(exportImportPlan(queue).items, []);
});

test("ImportQueue.hydrate: rejects a non-array/malformed plan", async () => {
  const { ImportQueue } = await import("../state/import-engine.js");
  const queue = new ImportQueue({ batchId: "b", source: "local_files" });
  assert.equal(queue.hydrate(null), false);
  assert.equal(queue.hydrate({ items: "not-an-array" }), false);
  assert.equal(queue.hydrate({ items: [{ status: "accepted" }] }), false, "an item missing item_id must be dropped");
});

// ---------------------------------------------------------------------
// Review / Feedback hydrate()/reset()
// ---------------------------------------------------------------------

test("hydrateReviewPlan: restores valid records, rejects malformed ones", async () => {
  const {
    CandidateReviewStore,
    FeedbackStore,
    CandidateReviewDecision,
    CandidateReviewReason,
    FeedbackType,
    exportReviewPlan,
    hydrateReviewPlan,
  } = await import("../state/review-model.js");

  const reviewStore = new CandidateReviewStore();
  const feedbackStore = new FeedbackStore();
  reviewStore.record({ segmentId: "seg-1", decision: CandidateReviewDecision.ACCEPTED, reasonCode: CandidateReviewReason.OTHER });
  feedbackStore.record({ feedbackType: FeedbackType.QUALITY_FEEDBACK, targetId: "seg-1" });
  const plan = exportReviewPlan(reviewStore, feedbackStore);

  const freshReview = new CandidateReviewStore();
  const freshFeedback = new FeedbackStore();
  assert.equal(hydrateReviewPlan(freshReview, freshFeedback, plan), true);
  assert.equal(freshReview.all().length, 1);
  assert.equal(freshFeedback.all().length, 1);

  // A new record after hydration must not collide with a restored id.
  const next = freshReview.record({ segmentId: "seg-2", decision: CandidateReviewDecision.PENDING, reasonCode: CandidateReviewReason.OTHER });
  assert.notEqual(next.reviewId, plan.review_decisions[0].reviewId);

  freshReview.reset();
  freshFeedback.reset();
  assert.equal(freshReview.all().length, 0);
  assert.equal(freshFeedback.all().length, 0);

  assert.equal(hydrateReviewPlan(new CandidateReviewStore(), new FeedbackStore(), null), false);
  assert.equal(
    new CandidateReviewStore().hydrate([{ reviewId: "review-0001", segmentId: "s", decision: "NOT_REAL", reasonCode: CandidateReviewReason.OTHER }]),
    false,
    "an unknown decision value must be dropped, and an all-dropped restore reports false",
  );
});

// ---------------------------------------------------------------------
// Processing hydrate()/reset()
// ---------------------------------------------------------------------

test("hydrateProcessingPlan: excludes non-terminal queue items, restores history", async () => {
  const { ProcessingQueueStore, ProcessingHistoryStore, ProcessingStatus, exportProcessingPlan, hydrateProcessingPlan } =
    await import("../state/processing-model.js");

  const queueStore = new ProcessingQueueStore();
  const historyStore = new ProcessingHistoryStore();
  const item = { itemId: "session-proc-0001", recordingId: "rec-1", profileId: "p", status: ProcessingStatus.SUCCESS, progress: 1, currentOperation: null, warnings: [], errors: [], decision: "NO_PROCESSING", processingDurationSeconds: 0.1, derivedArtifact: null, qualityBefore: null, qualityAfter: null };
  queueStore._items.push(item);
  historyStore.record({ recordingId: "rec-1", item });
  const plan = exportProcessingPlan(queueStore, historyStore);
  // Simulate an in-flight item that must never survive a restore.
  plan.processing_items.push({ itemId: "session-proc-0002", recordingId: "rec-2", status: ProcessingStatus.PROCESSING });

  const freshQueue = new ProcessingQueueStore();
  const freshHistory = new ProcessingHistoryStore();
  assert.equal(hydrateProcessingPlan(freshQueue, freshHistory, plan), true);
  assert.equal(freshQueue.list().length, 1, "the PROCESSING item must be excluded as non-terminal");
  assert.equal(freshHistory.all().length, 1);

  freshQueue.reset();
  freshHistory.reset();
  assert.equal(freshQueue.list().length, 0);
  assert.equal(freshHistory.all().length, 0);
});

// ---------------------------------------------------------------------
// Generation hydrate()/reset()
// ---------------------------------------------------------------------

test("hydrateGenerationPlan: excludes non-terminal items, bumps counters past restored ids", async () => {
  const {
    GenerationQueueStore,
    GenerationModelStore,
    PreviewHistoryStore,
    PreviewFeedbackStore,
    GenerationStatus,
    buildPreviewRequest,
    exportGenerationPlan,
    hydrateGenerationPlan,
  } = await import("../state/generation-model.js");

  const modelStore = new GenerationModelStore();
  const queueStore = new GenerationQueueStore({ modelStore });
  const historyStore = new PreviewHistoryStore();
  const feedbackStore = new PreviewFeedbackStore();

  const request = buildPreviewRequest({ text: "hello", voiceProfileId: "vp-1", modelId: "m-1" });
  const readyItem = queueStore.enqueue(request);
  readyItem.status = GenerationStatus.READY;
  readyItem.artifact = { preview_id: "preview-1" };
  const plan = exportGenerationPlan(queueStore, historyStore, feedbackStore);
  plan.generation_items.push({ item_id: "gen-9999-preview-req-99999", request: buildPreviewRequest({ text: "mid-flight", voiceProfileId: "vp-1", modelId: "m-1" }), status: GenerationStatus.GENERATING });

  const freshQueue = new GenerationQueueStore({ modelStore });
  const freshHistory = new PreviewHistoryStore();
  const freshFeedback = new PreviewFeedbackStore();
  assert.equal(hydrateGenerationPlan(freshQueue, freshHistory, freshFeedback, plan), true);
  assert.equal(freshQueue.list().length, 1, "the GENERATING item must be excluded as non-terminal");

  const nextRequest = buildPreviewRequest({ text: "after restore", voiceProfileId: "vp-1", modelId: "m-1" });
  assert.notEqual(nextRequest.request_id, request.request_id, "the request-id counter must have advanced past the restored item");

  freshQueue.reset();
  assert.equal(freshQueue.list().length, 0);
});

// ---------------------------------------------------------------------
// Evaluation hydrate()/reset()
// ---------------------------------------------------------------------

test("hydrateEvaluationPlan: never restores a COMPLETED evaluation that wasn't actually listened to", async () => {
  const {
    EvaluationStore,
    ABEvaluationStore,
    EvaluationCompletionState,
    ABDecision,
    buildListeningState,
    exportEvaluationPlan,
    hydrateEvaluationPlan,
  } = await import("../state/evaluation-model.js");

  const evaluationStore = new EvaluationStore();
  const abEvaluationStore = new ABEvaluationStore();
  evaluationStore.record({ outputId: "out-1", reviewer: "operator", listening: buildListeningState({ listened: true }), dimensionScores: { OVERALL: 4 } });
  abEvaluationStore.record({ outputIdA: "out-1", outputIdB: "out-2", reviewer: "operator", listenedA: true, listenedB: true, decision: ABDecision.PREFER_A });
  const plan = exportEvaluationPlan(evaluationStore, abEvaluationStore);
  // A tampered/corrupted record that record() itself could never produce.
  plan.evaluations.push({ evaluation_id: "eval-99999", output_id: "out-3", completion_state: EvaluationCompletionState.COMPLETED, listening: buildListeningState({ listened: false }) });
  plan.ab_evaluations.push({ ab_evaluation_id: "ab-eval-99999", output_id_a: "out-3", output_id_b: "out-4", decision: ABDecision.PREFER_A, listened_a: false, listened_b: true });

  const freshEvaluation = new EvaluationStore();
  const freshAb = new ABEvaluationStore();
  assert.equal(hydrateEvaluationPlan(freshEvaluation, freshAb, plan), true);
  assert.equal(freshEvaluation.list().length, 1, "the unlistened COMPLETED record must be dropped");
  assert.equal(freshAb.list().length, 1, "the PREFER_A decision without both sides listened must be dropped");

  freshEvaluation.reset();
  freshAb.reset();
  assert.equal(freshEvaluation.list().length, 0);
  assert.equal(freshAb.list().length, 0);
});

// ---------------------------------------------------------------------
// Calibration hydrate()/reset()
// ---------------------------------------------------------------------

test("exportCalibrationPlan/hydrate: round-trips the three-axis state, bumps the profile counter", async () => {
  const { CalibrationProfileStore, ApplicationState, exportCalibrationPlan } = await import(
    "../state/calibration-engine-model.js"
  );

  const store = new CalibrationProfileStore();
  const profile = store.run({});
  const plan = exportCalibrationPlan(store);
  assert.equal(plan.calibration_profiles.length, 1);
  assert.equal(plan.calibration_profiles[0].application_state, ApplicationState.PROPOSED);

  const fresh = new CalibrationProfileStore();
  assert.equal(fresh.hydrate(plan), true);
  assert.deepEqual(fresh.history(), plan.calibration_profiles);

  const nextProfile = fresh.run({});
  assert.notEqual(nextProfile.profile_id, profile.profile_id, "the profile-id counter must have advanced past the restored profile");

  fresh.reset();
  assert.equal(fresh.history().length, 0);

  assert.equal(fresh.hydrate(null), false);
  assert.equal(fresh.hydrate({ calibration_profiles: [{ profile_id: "x" }] }), false, "a record missing required fields/enums must be dropped");
});
