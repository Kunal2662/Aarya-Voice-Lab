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
}

export function exportReviewPlan(reviewStore, feedbackStore) {
  return {
    is_synthetic: true,
    generated_by: "frontend client-side review model (session-only, not authoritative)",
    review_decisions: reviewStore.all(),
    feedback: feedbackStore.all(),
  };
}
