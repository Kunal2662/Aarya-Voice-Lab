// Client-side human-evaluation state (VL-D6). Mirrors
// pipeline.evaluation / pipeline.evaluation_aggregation's vocabulary,
// validation, and honesty rules exactly, but this is a session-scoped,
// in-memory simulation over state/synthetic-fixtures.js data -- there is
// still no execution transport (state/command-executor.js) to persist
// an evaluation beyond the session. identity.preview.PreviewFeedback and
// state/generation-model.js's PreviewFeedbackStore are untouched by this
// module -- VL-D6 is the genuinely broader, multi-dimension, multi-
// reviewer evaluation concern those single-outcome records cannot
// express, not a replacement for them.
//
// Same field-naming convention as generation-model.js: records shaped
// like a backend `to_dict()` keep that exact snake_case shape (so a real
// backend response could be dropped in unchanged); store/method names
// stay camelCase, the normal JS convention for this file's own surface.

// Mirrors pipeline.evaluation.VoiceQualityDimension exactly (VL-D6).
// Seven names reused verbatim from PreviewFeedbackCategory
// (NATURALNESS/CLARITY/PRONUNCIATION/PROSODY/PACE/ARTIFACTS/OVERALL);
// four new (INTELLIGIBILITY/EXPRESSIVENESS/CONSISTENCY/NOISE). Rhythm
// folds into PROSODY, Stability folds into CONSISTENCY -- neither is a
// separate dimension.
export const VoiceQualityDimension = Object.freeze({
  NATURALNESS: "NATURALNESS",
  CLARITY: "CLARITY",
  INTELLIGIBILITY: "INTELLIGIBILITY",
  PRONUNCIATION: "PRONUNCIATION",
  PROSODY: "PROSODY",
  PACE: "PACE",
  EXPRESSIVENESS: "EXPRESSIVENESS",
  CONSISTENCY: "CONSISTENCY",
  ARTIFACTS: "ARTIFACTS",
  NOISE: "NOISE",
  OVERALL: "OVERALL",
});

export const EvaluationCompletionState = Object.freeze({
  IN_PROGRESS: "IN_PROGRESS",
  COMPLETED: "COMPLETED",
  CANNOT_JUDGE: "CANNOT_JUDGE",
  ABANDONED: "ABANDONED",
});

// Deliberately separate from generation-model.js's PreviewFeedbackOutcome
// -- a comparison between two outputs is a different judgement from one
// output's accept/reject fate.
export const ABDecision = Object.freeze({
  PREFER_A: "PREFER_A",
  PREFER_B: "PREFER_B",
  NO_PREFERENCE: "NO_PREFERENCE",
  CANNOT_JUDGE: "CANNOT_JUDGE",
});

export const MIN_SCORE = 1;
export const MAX_SCORE = 5;

/** Mirrors pipeline.evaluation_aggregation's constants exactly. */
export const MIN_EVALUATIONS_FOR_DISAGREEMENT = 2;
export const DISAGREEMENT_SPREAD_THRESHOLD = 2;

const DECISIONS_REQUIRING_BOTH_LISTENED = new Set([ABDecision.PREFER_A, ABDecision.PREFER_B, ABDecision.NO_PREFERENCE]);

/** Mirrors pipeline.evaluation.UnlistenedEvaluationError: an evaluation
 * marked COMPLETED, or an A/B decision requiring both sides, without
 * the relevant output(s) having actually been listened to. */
export class UnlistenedEvaluationError extends Error {}

/** Mirrors pipeline.evaluation.InvalidDimensionScoreError. */
export class InvalidDimensionScoreError extends Error {}

/** A honest, browser-measurable listening-state object -- mirrors
 * pipeline.evaluation.ListeningState.to_dict() exactly.
 * furthest_position_seconds is deliberately not "time listened": a
 * reviewer can seek, so this is only the furthest playback position
 * reached. */
export function buildListeningState({
  listened = false,
  firstListenedAt = null,
  replayCount = 0,
  furthestPositionSeconds = null,
  completedPlayback = false,
} = {}) {
  return {
    listened,
    first_listened_at: firstListenedAt,
    replay_count: replayCount,
    furthest_position_seconds: furthestPositionSeconds,
    completed_playback: completedPlayback,
  };
}

/** Mirrors pipeline.evaluation._validate_dimension_scores. */
export function validateDimensionScores(dimensionScores, cannotJudgeDimensions = []) {
  const known = new Set(Object.values(VoiceQualityDimension));
  for (const [dimension, score] of Object.entries(dimensionScores || {})) {
    if (!known.has(dimension)) throw new InvalidDimensionScoreError(`unknown VoiceQualityDimension: ${dimension}`);
    if (score < MIN_SCORE || score > MAX_SCORE) {
      throw new InvalidDimensionScoreError(`score for ${dimension} must be within ${MIN_SCORE}..${MAX_SCORE}, got ${score}`);
    }
  }
  for (const dimension of cannotJudgeDimensions) {
    if (!known.has(dimension)) throw new InvalidDimensionScoreError(`unknown VoiceQualityDimension: ${dimension}`);
    if (dimension in (dimensionScores || {})) {
      throw new InvalidDimensionScoreError(`${dimension} cannot be both scored and marked cannot-judge`);
    }
  }
}

let _evaluationCounter = 0;

/** Session-only, append-only evaluation log. Mirrors
 * pipeline.evaluation.EvaluationLog/record_evaluation exactly, including
 * the listened-before-COMPLETED gate. A second evaluation of the same
 * output_id (same or different reviewer) is always a new record, never
 * an edit -- that is how reviewer disagreement is represented. */
export class EvaluationStore extends EventTarget {
  constructor() {
    super();
    /** @type {object[]} */
    this._records = [];
  }

  record({
    outputId,
    reviewer,
    listening,
    dimensionScores = {},
    cannotJudgeDimensions = [],
    confidence = null,
    completionState = EvaluationCompletionState.COMPLETED,
    comment = null,
    voiceProfileId = null,
    modelId = null,
    configHash = null,
    outputSha256 = null,
    supersedes = null,
    evaluationVersion = 1,
  }) {
    validateDimensionScores(dimensionScores, cannotJudgeDimensions);
    if (confidence !== null && (confidence < MIN_SCORE || confidence > MAX_SCORE)) {
      throw new InvalidDimensionScoreError(`confidence must be within ${MIN_SCORE}..${MAX_SCORE}, got ${confidence}`);
    }
    if (completionState === EvaluationCompletionState.COMPLETED && !listening.listened) {
      throw new UnlistenedEvaluationError(
        `cannot mark evaluation of ${outputId} COMPLETED — the output must be listened to first`,
      );
    }

    _evaluationCounter += 1;
    const record = {
      evaluation_id: `eval-${String(_evaluationCounter).padStart(5, "0")}`,
      output_id: outputId,
      reviewer,
      listening,
      dimension_scores: { ...dimensionScores },
      cannot_judge_dimensions: [...cannotJudgeDimensions],
      confidence,
      completion_state: completionState,
      comment,
      voice_profile_id: voiceProfileId,
      model_id: modelId,
      config_hash: configHash,
      output_sha256: outputSha256,
      evaluation_version: evaluationVersion,
      supersedes,
      created_at: new Date().toISOString(),
    };
    this._records.push(record);
    this._announce(record);
    return record;
  }

  evaluationsFor(outputId) {
    return this._records.filter((r) => r.output_id === outputId);
  }

  reviewersFor(outputId) {
    return this.evaluationsFor(outputId).map((r) => r.reviewer);
  }

  get(evaluationId) {
    return this._records.find((r) => r.evaluation_id === evaluationId) || null;
  }

  list() {
    return [...this._records];
  }

  _announce(record) {
    this.dispatchEvent(new CustomEvent("change", { detail: { record } }));
  }
}

let _abEvaluationCounter = 0;

/** Session-only A/B evaluation log. Mirrors
 * pipeline.evaluation.ABEvaluationLog/record_ab_evaluation exactly.
 * CANNOT_JUDGE never requires listening (a reviewer may reach it
 * precisely because playback failed); PREFER_A/PREFER_B/NO_PREFERENCE
 * all require both outputs to have been listened to. */
export class ABEvaluationStore extends EventTarget {
  constructor() {
    super();
    /** @type {object[]} */
    this._records = [];
  }

  record({ outputIdA, outputIdB, reviewer, listenedA, listenedB, decision, blinded = false, comment = null }) {
    if (DECISIONS_REQUIRING_BOTH_LISTENED.has(decision) && !(listenedA && listenedB)) {
      throw new UnlistenedEvaluationError(
        `cannot record ${decision} between ${outputIdA} and ${outputIdB} — both outputs must be listened to first`,
      );
    }

    _abEvaluationCounter += 1;
    const record = {
      ab_evaluation_id: `ab-eval-${String(_abEvaluationCounter).padStart(5, "0")}`,
      output_id_a: outputIdA,
      output_id_b: outputIdB,
      reviewer,
      listened_a: listenedA,
      listened_b: listenedB,
      decision,
      blinded,
      comment,
      created_at: new Date().toISOString(),
    };
    this._records.push(record);
    this._announce(record);
    return record;
  }

  abEvaluationsFor(outputId) {
    return this._records.filter((r) => r.output_id_a === outputId || r.output_id_b === outputId);
  }

  list() {
    return [...this._records];
  }

  _announce(record) {
    this.dispatchEvent(new CustomEvent("change", { detail: { record } }));
  }
}

// ---------------------------------------------------------------------
// Aggregation + disagreement -- mirrors pipeline.evaluation_aggregation
// exactly: pure functions over already-recorded evaluations, empty/small
// input yields an honest None/false, never a fabricated statistic.
// ---------------------------------------------------------------------

function mean(values) {
  return values.reduce((a, b) => a + b, 0) / values.length;
}

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function sampleVariance(values) {
  const m = mean(values);
  return values.reduce((sum, v) => sum + (v - m) ** 2, 0) / (values.length - 1);
}

export function summarizeDimension(scores, dimension) {
  if (!scores.length) {
    return { dimension, sample_count: 0, mean: null, median: null, variance: null, min_score: null, max_score: null };
  }
  return {
    dimension,
    sample_count: scores.length,
    mean: Math.round(mean(scores) * 1000) / 1000,
    median: median(scores),
    variance: scores.length >= 2 ? Math.round(sampleVariance(scores) * 1000) / 1000 : null,
    min_score: Math.min(...scores),
    max_score: Math.max(...scores),
  };
}

function hasDimensionDisagreement(stats) {
  if (stats.sample_count < MIN_EVALUATIONS_FOR_DISAGREEMENT) return false;
  return stats.max_score - stats.min_score >= DISAGREEMENT_SPREAD_THRESHOLD;
}

/** `evaluations` must already be filtered to one output_id (see
 * EvaluationStore.evaluationsFor()) -- this function performs no
 * filtering of its own, only aggregation, mirroring the Python side. */
export function summarizeOutputEvaluations(evaluations, outputId) {
  if (!evaluations.length) {
    const dimensionStatistics = {};
    for (const dimension of Object.values(VoiceQualityDimension)) {
      dimensionStatistics[dimension] = summarizeDimension([], dimension);
    }
    return {
      output_id: outputId,
      evaluation_count: 0,
      reviewer_count: 0,
      completed_count: 0,
      cannot_judge_count: 0,
      dimension_statistics: dimensionStatistics,
      has_disagreement: false,
      disagreement_dimensions: [],
      note: "No evaluations recorded for this output yet.",
    };
  }

  const dimensionStatistics = {};
  for (const dimension of Object.values(VoiceQualityDimension)) {
    const scores = evaluations
      .filter((e) => dimension in (e.dimension_scores || {}))
      .map((e) => e.dimension_scores[dimension]);
    dimensionStatistics[dimension] = summarizeDimension(scores, dimension);
  }

  const disagreementDimensions = Object.keys(dimensionStatistics).filter((d) =>
    hasDimensionDisagreement(dimensionStatistics[d]),
  );
  const reviewerCount = new Set(evaluations.map((e) => e.reviewer)).size;
  const completedCount = evaluations.filter((e) => e.completion_state === EvaluationCompletionState.COMPLETED).length;
  const cannotJudgeCount = evaluations.filter((e) => e.completion_state === EvaluationCompletionState.CANNOT_JUDGE).length;

  const note =
    `${evaluations.length} evaluation(s) from ${reviewerCount} reviewer(s) — ` +
    (evaluations.length < MIN_EVALUATIONS_FOR_DISAGREEMENT
      ? "too few to assess disagreement (needs >=2)."
      : disagreementDimensions.length
        ? "disagreement detected."
        : "no disagreement detected.");

  return {
    output_id: outputId,
    evaluation_count: evaluations.length,
    reviewer_count: reviewerCount,
    completed_count: completedCount,
    cannot_judge_count: cannotJudgeCount,
    dimension_statistics: dimensionStatistics,
    has_disagreement: disagreementDimensions.length > 0,
    disagreement_dimensions: disagreementDimensions,
    note,
  };
}

/** Every distinct output_id with >=2 evaluations and a disagreeing
 * dimension -- mirrors pipeline.evaluation_aggregation.outputs_with_disagreement. */
export function outputsWithDisagreement(evaluationStore) {
  const byOutput = new Map();
  for (const record of evaluationStore.list()) {
    if (!byOutput.has(record.output_id)) byOutput.set(record.output_id, []);
    byOutput.get(record.output_id).push(record);
  }
  const result = [];
  for (const [outputId, records] of byOutput) {
    if (summarizeOutputEvaluations(records, outputId).has_disagreement) result.push(outputId);
  }
  return result;
}

/** `abEvaluations` must already be filtered to this exact (A, B) pair. */
export function summarizeAbPreferences(abEvaluations, outputIdA, outputIdB) {
  const preferA = abEvaluations.filter((e) => e.decision === ABDecision.PREFER_A).length;
  const preferB = abEvaluations.filter((e) => e.decision === ABDecision.PREFER_B).length;
  const noPreference = abEvaluations.filter((e) => e.decision === ABDecision.NO_PREFERENCE).length;
  const cannotJudge = abEvaluations.filter((e) => e.decision === ABDecision.CANNOT_JUDGE).length;
  const decided = preferA + preferB;

  return {
    output_id_a: outputIdA,
    output_id_b: outputIdB,
    total_decisions: abEvaluations.length,
    prefer_a_count: preferA,
    prefer_b_count: preferB,
    no_preference_count: noPreference,
    cannot_judge_count: cannotJudge,
    preference_rate_a: decided ? Math.round((preferA / decided) * 1000) / 1000 : null,
    note: abEvaluations.length
      ? `${abEvaluations.length} A/B decision(s), ${decided} with a stated preference.`
      : "No A/B decisions recorded for this pair yet.",
  };
}

/** Mirrors pipeline.evaluation_aggregation.summarize_calibration_signals
 * -- real counts only, never a computed score. */
export function summarizeCalibrationSignals(evaluationStore) {
  const records = evaluationStore.list();
  return {
    total_evaluations: records.length,
    total_outputs_evaluated: new Set(records.map((r) => r.output_id)).size,
    total_reviewers: new Set(records.map((r) => r.reviewer)).size,
    disagreement_output_count: outputsWithDisagreement(evaluationStore).length,
    completed_count: records.filter((r) => r.completion_state === EvaluationCompletionState.COMPLETED).length,
    cannot_judge_count: records.filter((r) => r.completion_state === EvaluationCompletionState.CANNOT_JUDGE).length,
    note: "Raw counts for a future calibration step to read — never a computed score, and never used here to declare a voice calibrated.",
  };
}

export function exportEvaluationPlan(evaluationStore, abEvaluationStore) {
  return {
    is_synthetic: true,
    generated_by: "frontend client-side evaluation model (session-only, not authoritative)",
    evaluations: evaluationStore.list(),
    ab_evaluations: abEvaluationStore.list(),
  };
}
