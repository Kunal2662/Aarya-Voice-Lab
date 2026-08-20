// Pure-logic unit tests for VL-D3's Dataset Review state layer:
// review-model.js (CandidateReviewStore/FeedbackStore), quality-summary.js,
// review-summary.js, and the buildReviewClaudeContext() addition to
// claude-context.js. No browser needed — see dataset-review.test.mjs for
// the real-browser component/workspace scenarios (VL-D3 §36).
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  CandidateReviewDecision,
  CandidateReviewReason,
  CandidateReviewStore,
  FeedbackType,
  FeedbackStore,
  exportReviewPlan,
} from "../state/review-model.js";
import { summarizeQuality } from "../state/quality-summary.js";
import { summarizeReviewState } from "../state/review-summary.js";
import { buildReviewClaudeContext } from "../state/claude-context.js";
import { syntheticSegments } from "../state/synthetic-fixtures.js";

test("CandidateReviewStore rejects unknown decisions and reason codes", () => {
  const store = new CandidateReviewStore();
  assert.throws(() => store.record({ segmentId: "s1", decision: "MAYBE", reasonCode: CandidateReviewReason.OTHER }));
  assert.throws(() => store.record({ segmentId: "s1", decision: CandidateReviewDecision.ACCEPTED, reasonCode: "speaker_is_aarya" }));
});

test("CandidateReviewStore never overwrites history — a correction appends a new record", () => {
  const store = new CandidateReviewStore();
  const first = store.record({
    segmentId: "seg-x",
    decision: CandidateReviewDecision.NEEDS_REVIEW,
    reasonCode: CandidateReviewReason.QUALITY_ISSUE,
  });
  const second = store.record({
    segmentId: "seg-x",
    decision: CandidateReviewDecision.ACCEPTED,
    reasonCode: CandidateReviewReason.TECHNICAL_USABILITY,
    supersedes: first.reviewId,
  });
  assert.equal(store.history("seg-x").length, 2);
  assert.equal(store.current("seg-x").reviewId, second.reviewId);
  assert.equal(store.history("seg-x")[0].reviewId, first.reviewId, "the original record must still be present");
});

test("CandidateReviewStore.disagreementCount only counts segments with conflicting decisions", () => {
  const store = new CandidateReviewStore();
  store.record({ segmentId: "s1", decision: CandidateReviewDecision.ACCEPTED, reasonCode: CandidateReviewReason.OTHER });
  store.record({ segmentId: "s1", decision: CandidateReviewDecision.ACCEPTED, reasonCode: CandidateReviewReason.OTHER });
  store.record({ segmentId: "s2", decision: CandidateReviewDecision.ACCEPTED, reasonCode: CandidateReviewReason.OTHER });
  store.record({ segmentId: "s2", decision: CandidateReviewDecision.REJECTED, reasonCode: CandidateReviewReason.QUALITY_ISSUE });
  assert.equal(store.disagreementCount(), 1);
});

test("CandidateReviewStore fires a change event with the recorded record", () => {
  const store = new CandidateReviewStore();
  let seen = null;
  store.addEventListener("change", (event) => {
    seen = event.detail.record;
  });
  store.record({ segmentId: "s1", decision: CandidateReviewDecision.PENDING, reasonCode: CandidateReviewReason.OTHER });
  assert.ok(seen);
  assert.equal(seen.segmentId, "s1");
  assert.equal(seen.reviewType, "technical");
});

test("FeedbackStore rejects unknown feedback types and is retrievable by target", () => {
  const store = new FeedbackStore();
  assert.throws(() => store.record({ feedbackType: "NOT_A_TYPE", targetId: "rec-1" }));
  const record = store.record({ feedbackType: FeedbackType.QUALITY_FEEDBACK, targetId: "rec-1", comment: "too quiet" });
  assert.deepEqual(store.forTarget("rec-1"), [record]);
  assert.equal(store.forTarget("rec-2").length, 0);
});

test("FeedbackStore.countsByType covers every FeedbackType key, even at zero", () => {
  const store = new FeedbackStore();
  store.record({ feedbackType: FeedbackType.SEGMENT_FEEDBACK, targetId: "seg-1" });
  const counts = store.countsByType();
  assert.deepEqual(Object.keys(counts).sort(), Object.values(FeedbackType).sort());
  assert.equal(counts[FeedbackType.SEGMENT_FEEDBACK], 1);
  assert.equal(counts[FeedbackType.PLAYBACK_FEEDBACK], 0);
});

test("exportReviewPlan is an honest, non-authoritative session bridge, never a persistence claim", () => {
  const reviewStore = new CandidateReviewStore();
  const feedbackStore = new FeedbackStore();
  reviewStore.record({ segmentId: "s1", decision: CandidateReviewDecision.ACCEPTED, reasonCode: CandidateReviewReason.OTHER });
  feedbackStore.record({ feedbackType: FeedbackType.QUALITY_FEEDBACK, targetId: "rec-1" });
  const plan = exportReviewPlan(reviewStore, feedbackStore);
  assert.equal(plan.is_synthetic, true);
  assert.match(plan.generated_by, /session-only, not authoritative/);
  assert.equal(plan.review_decisions.length, 1);
  assert.equal(plan.feedback.length, 1);
});

test("summarizeQuality computes real distributions from the synthetic fixtures, never fabricated", () => {
  const summary = summarizeQuality();
  assert.equal(summary.recordingCount, 3);
  assert.equal(summary.decisionDistribution.PASS, 1);
  assert.equal(summary.decisionDistribution.REVIEW, 1);
  assert.equal(summary.decisionDistribution.FAIL, 1);
  assert.equal(summary.overlapCandidateCount, 1);
  assert.equal(summary.narrowbandCount, 0, "synthetic-rec-0002 is exactly 16000Hz, not below it");
  assert.ok(summary.averageDurationSeconds > 0);
  assert.ok(summary.medianDurationSeconds > 0);
});

test("summarizeReviewState honestly reflects fixture defaults when no reviewStore is supplied", () => {
  const summary = summarizeReviewState(null);
  const totalSpeechSegments = ["synthetic-rec-0001", "synthetic-rec-0002", "synthetic-rec-0003"]
    .flatMap((id) => syntheticSegments(id))
    .filter((s) => s.kind === "speech").length;
  assert.equal(summary.reviewQueueCount + 2, totalSpeechSegments, "2 segments start ACCEPTED/REJECTED in the fixtures");
  assert.equal(summary.failedAnalyses, 1);
  assert.equal(summary.recentAnalysisCount, 3);
});

test("summarizeReviewState reflects live CandidateReviewStore decisions, not just fixture defaults", () => {
  const store = new CandidateReviewStore();
  const before = summarizeReviewState(store);
  store.record({ segmentId: "seg-0002-03", decision: CandidateReviewDecision.ACCEPTED, reasonCode: CandidateReviewReason.OTHER });
  const after = summarizeReviewState(store);
  assert.equal(after.reviewQueueCount, before.reviewQueueCount - 1);
});

test("buildReviewClaudeContext is bounded to exactly the VL-D3 §25 fields and redacts opaque values", () => {
  const context = buildReviewClaudeContext({
    recordingId: "synthetic-rec-0002",
    batchId: "synthetic-batch-001",
    stage: "quality_analysis",
    metric: { name: "estimated_snr_db", value: 5.8 },
    warning: "estimated SNR is low",
    provenance: { sourceSha256: "b2".repeat(32), configHash: null },
  });
  assert.deepEqual(Object.keys(context).sort(), [
    "batch_id",
    "config",
    "error",
    "metric",
    "permissions",
    "provenance",
    "recording_id",
    "stage",
    "warning",
  ]);
  assert.equal(context.permissions.max_risk_tier, "read_only");
  assert.match(context.provenance.sourceSha256, /<redacted>/, "a 64-char hex run must be redacted regardless of field name");
  // Nothing speaker-identity-shaped can even be expressed by this shape.
  assert.equal("speaker_id" in context, false);
  assert.equal("is_aarya" in context, false);
});
