// Pure-logic unit tests for VL-D6's Voice Feedback / Human Evaluation
// state layer: state/evaluation-model.js's EvaluationStore/
// ABEvaluationStore, buildListeningState/validateDimensionScores,
// summarizeDimension/summarizeOutputEvaluations/outputsWithDisagreement/
// summarizeAbPreferences/summarizeCalibrationSignals/exportEvaluationPlan.
// No browser needed — see feedback.test.mjs for the real-browser
// workspace/component scenarios.
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  VoiceQualityDimension,
  EvaluationCompletionState,
  ABDecision,
  MIN_SCORE,
  MAX_SCORE,
  MIN_EVALUATIONS_FOR_DISAGREEMENT,
  DISAGREEMENT_SPREAD_THRESHOLD,
  UnlistenedEvaluationError,
  InvalidDimensionScoreError,
  buildListeningState,
  validateDimensionScores,
  EvaluationStore,
  ABEvaluationStore,
  summarizeDimension,
  summarizeOutputEvaluations,
  outputsWithDisagreement,
  summarizeAbPreferences,
  summarizeCalibrationSignals,
  exportEvaluationPlan,
} from "../state/evaluation-model.js";
import { PreviewFeedbackOutcome } from "../state/generation-model.js";
import { syntheticEvaluations, syntheticAbEvaluations } from "../state/synthetic-fixtures.js";

const LISTENED = Object.freeze(buildListeningState({ listened: true, replayCount: 0, furthestPositionSeconds: 3, completedPlayback: true }));
const NOT_LISTENED = Object.freeze(buildListeningState());

test("VoiceQualityDimension is a bounded 11-value vocabulary, reusing 7 PreviewFeedbackCategory names and adding 4 new ones", () => {
  const values = Object.values(VoiceQualityDimension);
  assert.equal(values.length, 11);
  for (const reused of ["NATURALNESS", "CLARITY", "PRONUNCIATION", "PROSODY", "PACE", "ARTIFACTS", "OVERALL"]) {
    assert.ok(values.includes(reused), `expected reused dimension: ${reused}`);
  }
  for (const added of ["INTELLIGIBILITY", "EXPRESSIVENESS", "CONSISTENCY", "NOISE"]) {
    assert.ok(values.includes(added), `expected new dimension: ${added}`);
  }
  // Rhythm and Stability were deliberately folded, never added as their own dimension.
  assert.ok(!values.includes("RHYTHM"));
  assert.ok(!values.includes("STABILITY"));
});

test("ABDecision is structurally separate from PreviewFeedbackOutcome — zero value overlap", () => {
  const abValues = new Set(Object.values(ABDecision));
  const previewValues = new Set(Object.values(PreviewFeedbackOutcome));
  for (const value of abValues) assert.ok(!previewValues.has(value), `unexpected overlap: ${value}`);
});

test("MIN_SCORE/MAX_SCORE are 1..5", () => {
  assert.equal(MIN_SCORE, 1);
  assert.equal(MAX_SCORE, 5);
});

test("buildListeningState defaults are honest — never fabricated", () => {
  const state = buildListeningState();
  assert.equal(state.listened, false);
  assert.equal(state.first_listened_at, null);
  assert.equal(state.replay_count, 0);
  assert.equal(state.furthest_position_seconds, null);
  assert.equal(state.completed_playback, false);
});

test("validateDimensionScores accepts a valid score and rejects an unknown dimension", () => {
  assert.doesNotThrow(() => validateDimensionScores({ NATURALNESS: 4 }));
  assert.throws(() => validateDimensionScores({ WARMTH: 3 }), InvalidDimensionScoreError);
});

test("validateDimensionScores rejects an out-of-range score", () => {
  assert.throws(() => validateDimensionScores({ CLARITY: 0 }), InvalidDimensionScoreError);
  assert.throws(() => validateDimensionScores({ CLARITY: 6 }), InvalidDimensionScoreError);
});

test("validateDimensionScores rejects a dimension that is both scored and marked cannot-judge", () => {
  assert.throws(() => validateDimensionScores({ CLARITY: 3 }, ["CLARITY"]), InvalidDimensionScoreError);
});

test("EvaluationStore.record refuses COMPLETED without listening, but allows CANNOT_JUDGE/ABANDONED", () => {
  const store = new EvaluationStore();
  assert.throws(
    () => store.record({ outputId: "out-1", reviewer: "alice", listening: NOT_LISTENED, completionState: EvaluationCompletionState.COMPLETED }),
    UnlistenedEvaluationError,
  );
  assert.doesNotThrow(() =>
    store.record({ outputId: "out-1", reviewer: "alice", listening: NOT_LISTENED, completionState: EvaluationCompletionState.CANNOT_JUDGE }),
  );
  assert.doesNotThrow(() =>
    store.record({ outputId: "out-1", reviewer: "alice", listening: NOT_LISTENED, completionState: EvaluationCompletionState.ABANDONED }),
  );
});

test("EvaluationStore.record rejects an out-of-range confidence", () => {
  const store = new EvaluationStore();
  assert.throws(
    () => store.record({ outputId: "out-1", reviewer: "alice", listening: LISTENED, confidence: 9 }),
    InvalidDimensionScoreError,
  );
});

test("EvaluationStore.record assigns a unique id and an honest created_at, never touching input objects", () => {
  const store = new EvaluationStore();
  const scores = { NATURALNESS: 4 };
  const record = store.record({ outputId: "out-1", reviewer: "alice", listening: LISTENED, dimensionScores: scores });
  assert.match(record.evaluation_id, /^eval-\d{5}$/);
  assert.ok(record.created_at);
  assert.deepEqual(record.dimension_scores, scores);
  assert.notEqual(record.dimension_scores, scores, "must be a copy, not the same reference");
});

test("EvaluationStore.evaluationsFor/reviewersFor/get/list reflect real records", () => {
  const store = new EvaluationStore();
  const r1 = store.record({ outputId: "out-1", reviewer: "alice", listening: LISTENED });
  store.record({ outputId: "out-2", reviewer: "bob", listening: LISTENED });
  assert.equal(store.evaluationsFor("out-1").length, 1);
  assert.deepEqual(store.reviewersFor("out-1"), ["alice"]);
  assert.equal(store.get(r1.evaluation_id).evaluation_id, r1.evaluation_id);
  assert.equal(store.get("no-such-id"), null);
  assert.equal(store.list().length, 2);
});

test("a second evaluation of the same output is always a new append-only record, never an edit — this IS how disagreement is represented", () => {
  const store = new EvaluationStore();
  store.record({ outputId: "out-1", reviewer: "alice", listening: LISTENED, dimensionScores: { CLARITY: 5 } });
  store.record({ outputId: "out-1", reviewer: "bob", listening: LISTENED, dimensionScores: { CLARITY: 1 } });
  const records = store.evaluationsFor("out-1");
  assert.equal(records.length, 2);
  assert.notEqual(records[0].evaluation_id, records[1].evaluation_id);
});

test("summarizeDimension is honest about small samples: empty -> all null, n=1 -> variance null, n>=2 -> a real variance", () => {
  const empty = summarizeDimension([], "CLARITY");
  assert.equal(empty.sample_count, 0);
  assert.equal(empty.mean, null);
  assert.equal(empty.variance, null);

  const single = summarizeDimension([4], "CLARITY");
  assert.equal(single.sample_count, 1);
  assert.equal(single.mean, 4);
  assert.equal(single.variance, null, "variance is mathematically undefined at n=1, must not be fabricated as 0");

  const pair = summarizeDimension([2, 4], "CLARITY");
  assert.equal(pair.sample_count, 2);
  assert.ok(pair.variance !== null);
});

test("summarizeOutputEvaluations never claims disagreement from a single evaluation, regardless of the score", () => {
  const store = new EvaluationStore();
  store.record({ outputId: "out-1", reviewer: "alice", listening: LISTENED, dimensionScores: { CLARITY: 1 } });
  const summary = summarizeOutputEvaluations(store.evaluationsFor("out-1"), "out-1");
  assert.equal(summary.evaluation_count, 1);
  assert.equal(summary.has_disagreement, false);
  assert.deepEqual(summary.disagreement_dimensions, []);
});

test("summarizeOutputEvaluations detects disagreement only when sample_count >= threshold AND spread >= DISAGREEMENT_SPREAD_THRESHOLD", () => {
  const store = new EvaluationStore();
  store.record({ outputId: "out-1", reviewer: "alice", listening: LISTENED, dimensionScores: { CLARITY: 5 } });
  store.record({ outputId: "out-1", reviewer: "bob", listening: LISTENED, dimensionScores: { CLARITY: 4 } });
  const smallSpread = summarizeOutputEvaluations(store.evaluationsFor("out-1"), "out-1");
  assert.equal(smallSpread.has_disagreement, false, `spread of 1 is below DISAGREEMENT_SPREAD_THRESHOLD=${DISAGREEMENT_SPREAD_THRESHOLD}`);

  const store2 = new EvaluationStore();
  store2.record({ outputId: "out-2", reviewer: "alice", listening: LISTENED, dimensionScores: { CLARITY: 5 } });
  store2.record({ outputId: "out-2", reviewer: "bob", listening: LISTENED, dimensionScores: { CLARITY: 2 } });
  const bigSpread = summarizeOutputEvaluations(store2.evaluationsFor("out-2"), "out-2");
  assert.equal(bigSpread.has_disagreement, true);
  assert.ok(bigSpread.disagreement_dimensions.includes("CLARITY"));
  assert.equal(MIN_EVALUATIONS_FOR_DISAGREEMENT, 2);
});

test("summarizeOutputEvaluations on zero evaluations returns an honest empty summary, not an error or a fabricated stat", () => {
  const summary = summarizeOutputEvaluations([], "never-evaluated");
  assert.equal(summary.evaluation_count, 0);
  assert.equal(summary.has_disagreement, false);
  assert.match(summary.note, /No evaluations recorded/);
});

test("outputsWithDisagreement scans the whole log and returns only the disagreeing output ids", () => {
  const store = new EvaluationStore();
  store.record({ outputId: "agree", reviewer: "alice", listening: LISTENED, dimensionScores: { CLARITY: 4 } });
  store.record({ outputId: "agree", reviewer: "bob", listening: LISTENED, dimensionScores: { CLARITY: 4 } });
  store.record({ outputId: "disagree", reviewer: "alice", listening: LISTENED, dimensionScores: { CLARITY: 5 } });
  store.record({ outputId: "disagree", reviewer: "bob", listening: LISTENED, dimensionScores: { CLARITY: 1 } });
  assert.deepEqual(outputsWithDisagreement(store), ["disagree"]);
});

test("ABEvaluationStore.record requires both sides listened for PREFER_A/PREFER_B/NO_PREFERENCE, but not for CANNOT_JUDGE", () => {
  const store = new ABEvaluationStore();
  for (const decision of [ABDecision.PREFER_A, ABDecision.PREFER_B, ABDecision.NO_PREFERENCE]) {
    assert.throws(
      () => store.record({ outputIdA: "a", outputIdB: "b", reviewer: "alice", listenedA: true, listenedB: false, decision }),
      UnlistenedEvaluationError,
      `${decision} must require both sides listened`,
    );
  }
  assert.doesNotThrow(() =>
    store.record({ outputIdA: "a", outputIdB: "b", reviewer: "alice", listenedA: false, listenedB: false, decision: ABDecision.CANNOT_JUDGE }),
  );
});

test("ABEvaluationStore.abEvaluationsFor matches either side of the pair", () => {
  const store = new ABEvaluationStore();
  store.record({ outputIdA: "a", outputIdB: "b", reviewer: "alice", listenedA: true, listenedB: true, decision: ABDecision.PREFER_A });
  assert.equal(store.abEvaluationsFor("a").length, 1);
  assert.equal(store.abEvaluationsFor("b").length, 1);
  assert.equal(store.abEvaluationsFor("c").length, 0);
});

test("summarizeAbPreferences is honest about an undecided pair — preference_rate_a is null, never a fabricated 0.5", () => {
  const cannotJudgeOnly = [{ decision: ABDecision.CANNOT_JUDGE }];
  const summary = summarizeAbPreferences(cannotJudgeOnly, "a", "b");
  assert.equal(summary.preference_rate_a, null);
  assert.equal(summary.cannot_judge_count, 1);
});

test("summarizeAbPreferences computes real pairwise counts once decisions exist", () => {
  const decisions = [
    { decision: ABDecision.PREFER_A },
    { decision: ABDecision.PREFER_A },
    { decision: ABDecision.PREFER_B },
    { decision: ABDecision.NO_PREFERENCE },
  ];
  const summary = summarizeAbPreferences(decisions, "a", "b");
  assert.equal(summary.total_decisions, 4);
  assert.equal(summary.prefer_a_count, 2);
  assert.equal(summary.prefer_b_count, 1);
  assert.equal(summary.no_preference_count, 1);
  assert.equal(summary.preference_rate_a, Math.round((2 / 3) * 1000) / 1000);
});

test("summarizeCalibrationSignals reports real counts and never declares calibration", () => {
  const store = new EvaluationStore();
  store.record({ outputId: "out-1", reviewer: "alice", listening: LISTENED, dimensionScores: { CLARITY: 5 } });
  store.record({ outputId: "out-1", reviewer: "bob", listening: LISTENED, dimensionScores: { CLARITY: 1 } });
  store.record({ outputId: "out-1", reviewer: "carol", listening: NOT_LISTENED, completionState: EvaluationCompletionState.CANNOT_JUDGE });
  const signals = summarizeCalibrationSignals(store);
  assert.equal(signals.total_evaluations, 3);
  assert.equal(signals.total_outputs_evaluated, 1);
  assert.equal(signals.total_reviewers, 3);
  assert.equal(signals.disagreement_output_count, 1);
  assert.equal(signals.completed_count, 2);
  assert.equal(signals.cannot_judge_count, 1);
  // The note may honestly mention calibration in a negation ("never...
  // declare a voice calibrated") -- what must never appear is a
  // calibration_state field or a positive claim of being calibrated.
  assert.ok(!("calibration_state" in signals));
  assert.doesNotMatch(signals.note.toLowerCase(), /\bis calibrated\b/);
});

test("exportEvaluationPlan is an honest, non-authoritative session bridge", () => {
  const evaluationStore = new EvaluationStore();
  evaluationStore.record({ outputId: "out-1", reviewer: "alice", listening: LISTENED });
  const abStore = new ABEvaluationStore();
  abStore.record({ outputIdA: "out-1", outputIdB: "out-2", reviewer: "alice", listenedA: false, listenedB: false, decision: ABDecision.CANNOT_JUDGE });

  const plan = exportEvaluationPlan(evaluationStore, abStore);
  assert.equal(plan.is_synthetic, true);
  assert.match(plan.generated_by, /session-only, not authoritative/);
  assert.equal(plan.evaluations.length, 1);
  assert.equal(plan.ab_evaluations.length, 1);
});

test("synthetic evaluation fixtures demonstrate a real, detectable disagreement on the same output", () => {
  const fixtures = syntheticEvaluations();
  assert.equal(fixtures.length, 2);
  assert.equal(fixtures[0].output_id, fixtures[1].output_id);
  assert.notEqual(fixtures[0].reviewer, fixtures[1].reviewer);
  const summary = summarizeOutputEvaluations(fixtures, fixtures[0].output_id);
  assert.equal(summary.has_disagreement, true);
});

test("synthetic A/B evaluation fixture is well-formed and blinding is off by default", () => {
  const fixtures = syntheticAbEvaluations();
  assert.equal(fixtures.length, 1);
  assert.equal(fixtures[0].blinded, false);
  assert.ok(Object.values(ABDecision).includes(fixtures[0].decision));
});

test("no Evaluation/ABEvaluation record can express a speaker-identity field", () => {
  const store = new EvaluationStore();
  const record = store.record({ outputId: "out-1", reviewer: "alice", listening: LISTENED, dimensionScores: { OVERALL: 3 } });
  const keys = Object.keys(record);
  for (const forbidden of ["speaker", "target_speaker", "identity", "accent"]) {
    assert.ok(!keys.some((k) => k.toLowerCase().includes(forbidden)), `unexpected field on Evaluation: ${forbidden}`);
  }
});
