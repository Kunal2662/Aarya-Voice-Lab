// Overview-only aggregate for Command Center's REVIEW panel (VL-D3 §24).
// Deliberately shallow — counts only, computed from the same fixture
// data and CandidateReviewStore the Dataset Review workspace uses. The
// Dataset Review workspace itself remains the detailed surface; this
// module exists so Command Center never re-implements that detail, only
// summarizes it.
import { syntheticRecordings, syntheticQualityAssessments, syntheticSegments } from "./synthetic-fixtures.js";

const DECIDED_STATES = new Set(["ACCEPTED", "REJECTED"]);

export function summarizeReviewState(reviewStore) {
  const recordings = syntheticRecordings();
  const assessments = syntheticQualityAssessments();

  let pendingCandidates = 0;
  let qualityWarnings = 0;
  let failedAnalyses = 0;
  let analyzedCount = 0;
  const batchProgress = {};

  for (const recording of recordings) {
    const assessment = assessments[recording.id] || null;
    if (assessment) {
      analyzedCount += 1;
      qualityWarnings += assessment.findings.length;
      if (assessment.decision === "FAIL") failedAnalyses += 1;
    }

    if (!batchProgress[recording.batchId]) batchProgress[recording.batchId] = { total: 0, decided: 0 };
    for (const segment of syntheticSegments(recording.id)) {
      if (segment.kind !== "speech") continue;
      batchProgress[recording.batchId].total += 1;
      const current = reviewStore ? reviewStore.current(segment.segmentId) : null;
      const state = current ? current.decision : segment.candidateState;
      if (DECIDED_STATES.has(state)) {
        batchProgress[recording.batchId].decided += 1;
      } else {
        pendingCandidates += 1;
      }
    }
  }

  let currentBatchReview = null;
  for (const [batchId, progress] of Object.entries(batchProgress)) {
    if (progress.decided < progress.total) {
      currentBatchReview = { batchId, decided: progress.decided, total: progress.total };
      break;
    }
  }

  return {
    reviewQueueCount: pendingCandidates,
    pendingCandidates,
    qualityWarnings,
    recentAnalysisCount: analyzedCount,
    failedAnalyses,
    currentBatchReview,
    // FE-4 -- CandidateReviewStore.disagreementCount() (segments where a
    // re-review produced a different decision than a prior review) was
    // already implemented but never surfaced anywhere in the UI.
    disagreementCount: reviewStore ? reviewStore.disagreementCount() : 0,
  };
}
