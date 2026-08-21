// Client-side technical candidate review + feedback state (VL-D3 §12–§16,
// §26). Mirrors pipeline.candidate_review / pipeline.feedback's
// vocabulary and append-only semantics exactly, but this is a
// session-scoped, in-memory store — there is still no execution
// transport to persist a review into
// data/review/candidate_review.jsonl (see state/command-executor.js,
// unchanged since VL-D1). `exportReviewPlan()` bridges the same way
// VL-D2's `exportImportPlan()` does: a JSON shape close enough to the
// backend's `CandidateReviewLog`/`FeedbackLog` records that an operator
// can hand it to a future CLI command, never a claim that anything was
// actually written to disk.

export const CandidateReviewDecision = Object.freeze({
  PENDING: "PENDING",
  ACCEPTED: "ACCEPTED",
  REJECTED: "REJECTED",
  NEEDS_REVIEW: "NEEDS_REVIEW",
});

export const CandidateReviewReason = Object.freeze({
  QUALITY_ISSUE: "quality_issue",
  SEGMENTATION_ISSUE: "segmentation_issue",
  OVERLAP_ISSUE: "overlap_issue",
  DURATION_ISSUE: "duration_issue",
  TECHNICAL_USABILITY: "technical_usability",
  OTHER: "other",
});

export const FeedbackType = Object.freeze({
  QUALITY_FEEDBACK: "QUALITY_FEEDBACK",
  SEGMENT_FEEDBACK: "SEGMENT_FEEDBACK",
  CANDIDATE_FEEDBACK: "CANDIDATE_FEEDBACK",
  PLAYBACK_FEEDBACK: "PLAYBACK_FEEDBACK",
  // VL-D4 §28 — mirrors pipeline.feedback.FeedbackType exactly.
  PROCESSING_FEEDBACK: "PROCESSING_FEEDBACK",
});

let _reviewCounter = 0;
let _feedbackCounter = 0;

/** In-memory, append-only technical review history. Never edits or
 * removes a prior decision — a correction supersedes it, exactly like
 * pipeline.candidate_review's persisted records. */
export class CandidateReviewStore extends EventTarget {
  constructor() {
    super();
    /** @type {Array<object>} */
    this._records = [];
  }

  record({ segmentId, decision, reasonCode, reviewer = "operator", notes = null, supersedes = null }) {
    if (!Object.values(CandidateReviewDecision).includes(decision)) {
      throw new Error(`unknown CandidateReviewDecision: ${decision}`);
    }
    if (!Object.values(CandidateReviewReason).includes(reasonCode)) {
      throw new Error(`unknown CandidateReviewReason: ${reasonCode}`);
    }
    _reviewCounter += 1;
    const record = {
      reviewId: `review-${String(_reviewCounter).padStart(4, "0")}`,
      segmentId,
      decision,
      reasonCode,
      reviewer,
      notes,
      supersedes,
      reviewType: "technical",
      createdAt: new Date().toISOString(),
    };
    this._records.push(record);
    this.dispatchEvent(new CustomEvent("change", { detail: { record } }));
    return record;
  }

  history(segmentId) {
    return this._records.filter((r) => r.segmentId === segmentId);
  }

  current(segmentId) {
    const records = this.history(segmentId);
    return records.length ? records[records.length - 1] : null;
  }

  all() {
    return [...this._records];
  }

  disagreementCount() {
    const bySegment = new Map();
    for (const record of this._records) {
      if (!bySegment.has(record.segmentId)) bySegment.set(record.segmentId, new Set());
      bySegment.get(record.segmentId).add(record.decision);
    }
    return [...bySegment.values()].filter((decisions) => decisions.size > 1).length;
  }

  /** VL-D9 -- restores a previously-exported, already-validated review
   * history verbatim (see exportReviewPlan()). Every field here was
   * already reviewed as safe: reviewer is an operator label, not a
   * speaker identity; notes/comment are free text the operator typed
   * about a *segment decision*, never audio or a speaker attribute. Any
   * individual record missing reviewId/segmentId or carrying an unknown
   * decision/reasonCode is dropped rather than restored -- a malformed
   * entry is excluded, not guessed at. Replaces (never merges with) the
   * in-memory history; only ever called once, at startup, before the
   * user records a new decision (see app/main.js). Returns true only if
   * at least one record was restored. */
  hydrate(records) {
    if (!Array.isArray(records)) return false;
    const restored = records
      .filter(
        (r) =>
          r &&
          typeof r.reviewId === "string" &&
          typeof r.segmentId === "string" &&
          Object.values(CandidateReviewDecision).includes(r.decision) &&
          Object.values(CandidateReviewReason).includes(r.reasonCode),
      )
      .map((r) => ({ ...r }));
    if (!restored.length) return false;
    this._records = restored;
    const maxCounter = Math.max(0, ...restored.map((r) => parseInt((r.reviewId || "").split("-")[1] || "0", 10) || 0));
    if (maxCounter > _reviewCounter) _reviewCounter = maxCounter;
    return true;
  }

  /** VL-D9 -- clears this store's in-memory history in place (same
   * object identity, so existing listeners/service references stay
   * valid) and announces a detail-less "change" so mounted UI re-renders
   * immediately. Backs the explicit "Clear session data" control (see
   * components/workspace-settings.js) -- never called automatically. */
  reset() {
    this._records = [];
    this.dispatchEvent(new CustomEvent("change", { detail: {} }));
  }
}

export class FeedbackStore extends EventTarget {
  constructor() {
    super();
    this._records = [];
  }

  record({ feedbackType, targetId, reviewer = "operator", comment = null, attributes = {} }) {
    if (!Object.values(FeedbackType).includes(feedbackType)) {
      throw new Error(`unknown FeedbackType: ${feedbackType}`);
    }
    _feedbackCounter += 1;
    const record = {
      feedbackId: `feedback-${String(_feedbackCounter).padStart(4, "0")}`,
      feedbackType,
      targetId,
      reviewer,
      comment,
      attributes,
      createdAt: new Date().toISOString(),
    };
    this._records.push(record);
    this.dispatchEvent(new CustomEvent("change", { detail: { record } }));
    return record;
  }

  forTarget(targetId) {
    return this._records.filter((r) => r.targetId === targetId);
  }

  all() {
    return [...this._records];
  }

  countsByType() {
    const counts = Object.fromEntries(Object.values(FeedbackType).map((t) => [t, 0]));
    for (const record of this._records) counts[record.feedbackType] += 1;
    return counts;
  }

  /** VL-D9 -- see CandidateReviewStore.hydrate() above for the general
   * pattern. `attributes` is restored as-is: it is a small,
   * caller-supplied key/value bag already scoped to review/quality
   * feedback (see components that call FeedbackStore.record()), never a
   * place secrets, paths, or speaker fields have ever been put. */
  hydrate(records) {
    if (!Array.isArray(records)) return false;
    const restored = records
      .filter(
        (r) =>
          r &&
          typeof r.feedbackId === "string" &&
          typeof r.targetId === "string" &&
          Object.values(FeedbackType).includes(r.feedbackType),
      )
      .map((r) => ({ ...r }));
    if (!restored.length) return false;
    this._records = restored;
    const maxCounter = Math.max(
      0,
      ...restored.map((r) => parseInt((r.feedbackId || "").split("-")[1] || "0", 10) || 0),
    );
    if (maxCounter > _feedbackCounter) _feedbackCounter = maxCounter;
    return true;
  }

  /** VL-D9 -- see CandidateReviewStore.reset() above. */
  reset() {
    this._records = [];
    this.dispatchEvent(new CustomEvent("change", { detail: {} }));
  }
}

export function exportReviewPlan(reviewStore, feedbackStore) {
  return {
    is_synthetic: true,
    generated_by: "frontend client-side review model (session-only, not authoritative)",
    review_decisions: reviewStore.all(),
    feedback: feedbackStore.all(),
  };
}

/** VL-D9 -- restores both stores from a previously exportReviewPlan()'d
 * payload. Returns true if either store restored at least one record. */
export function hydrateReviewPlan(reviewStore, feedbackStore, plan) {
  if (!plan || typeof plan !== "object") return false;
  const a = reviewStore.hydrate(plan.review_decisions);
  const b = feedbackStore.hydrate(plan.feedback);
  return a || b;
}
