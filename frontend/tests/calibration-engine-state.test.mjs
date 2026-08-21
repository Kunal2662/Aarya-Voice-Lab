// Pure-logic tests for VL-D7's client-side calibration engine state
// (state/calibration-engine-model.js). Mirrors tests/test_calibration_engine.py's
// scenarios: zero/insufficient/sufficient evidence, strategy selection,
// hardware snapshot honesty, run-state/evidence-state independence,
// bounded parameter enforcement, append-only rollback, and provenance.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  CalibrationProfileStore,
  CalibrationRunState,
  CalibrationStrategy,
  CalibrationState,
  MIN_EVIDENCE_FOR_PROVISIONAL,
  ParameterBoundsError,
  RollbackTargetNotFound,
  buildParameterAdjustment,
  captureHardwareSnapshot,
  proposeHardwareAdjustments,
  assessReadiness,
  selectStrategy,
  agreementRate,
} from "../state/calibration-engine-model.js";
import { EvaluationStore, EvaluationCompletionState, outputsWithDisagreement } from "../state/evaluation-model.js";
import { syntheticHardwareCapabilities } from "../state/synthetic-fixtures.js";

const LISTENING = { listened: true, first_listened_at: null, replay_count: 0, furthest_position_seconds: 3, completed_playback: true };

function addEvaluations(store, outputId, scoresByReviewer) {
  for (const [reviewer, score] of Object.entries(scoresByReviewer)) {
    store.record({
      outputId,
      reviewer,
      listening: LISTENING,
      dimensionScores: { NATURALNESS: score },
      completionState: EvaluationCompletionState.COMPLETED,
    });
  }
}

test("CalibrationRunState mirrors the frontend hardware_calibration status domain exactly", () => {
  assert.deepEqual(new Set(Object.values(CalibrationRunState)), new Set(["UNCALIBRATED", "NOT_TESTED", "CALIBRATING", "CALIBRATED", "FAILED", "UNKNOWN"]));
});

test("zero evidence produces UNCALIBRATED evidence state and HARDWARE_ONLY strategy", () => {
  const store = new CalibrationProfileStore();
  const profile = store.run({ capabilities: syntheticHardwareCapabilities(), evaluationSummary: { total_evaluations: 0, total_outputs_evaluated: 0 } });
  assert.equal(profile.run_state, CalibrationRunState.CALIBRATED);
  assert.equal(profile.calibration_state, CalibrationState.UNCALIBRATED);
  assert.equal(profile.strategy, CalibrationStrategy.HARDWARE_ONLY);
  assert.equal(profile.agreement_rate, null);
  assert.ok(profile.limitations.join(" ").includes("no human evaluations recorded yet"));
});

test("insufficient evidence (single evaluation) stays UNCALIBRATED", () => {
  const evalStore = new EvaluationStore();
  addEvaluations(evalStore, "out-1", { alice: 4 });
  const store = new CalibrationProfileStore();
  const profile = store.run({
    capabilities: syntheticHardwareCapabilities(),
    evaluationStore: evalStore,
    evaluationSummary: { total_evaluations: 1, total_outputs_evaluated: 1 },
    outputsWithDisagreementFn: outputsWithDisagreement,
  });
  assert.equal(profile.calibration_state, CalibrationState.UNCALIBRATED);
  assert.ok(profile.limitations.some((l) => l.includes(String(MIN_EVIDENCE_FOR_PROVISIONAL))));
});

test("sufficient evidence reaches PROVISIONAL, never CALIBRATED", () => {
  const evalStore = new EvaluationStore();
  addEvaluations(evalStore, "out-1", { alice: 4, bob: 4 });
  const store = new CalibrationProfileStore();
  const profile = store.run({
    capabilities: syntheticHardwareCapabilities(),
    evaluationStore: evalStore,
    evaluationSummary: { total_evaluations: 2, total_outputs_evaluated: 1 },
    outputsWithDisagreementFn: outputsWithDisagreement,
  });
  assert.equal(profile.calibration_state, CalibrationState.PROVISIONAL);
  assert.equal(profile.agreement_rate, 1);
  assert.notEqual(profile.calibration_state, CalibrationState.CALIBRATED);
});

test("disagreement lowers agreement_rate but never claims CALIBRATED", () => {
  const evalStore = new EvaluationStore();
  addEvaluations(evalStore, "out-1", { alice: 5, bob: 1 });
  addEvaluations(evalStore, "out-2", { alice: 4, bob: 4 });
  const rate = agreementRate(evalStore, outputsWithDisagreement);
  assert.equal(rate, 0.5);
});

test("assessReadiness/selectStrategy pick HARDWARE_ONLY vs HARDWARE_AND_FEEDBACK correctly", () => {
  const insufficient = assessReadiness({ evaluationSummary: { total_evaluations: 0, total_outputs_evaluated: 0 } });
  const sufficient = assessReadiness({ evaluationSummary: { total_evaluations: 2, total_outputs_evaluated: 1 } });
  assert.equal(selectStrategy(insufficient), CalibrationStrategy.HARDWARE_ONLY);
  assert.equal(selectStrategy(sufficient), CalibrationStrategy.HARDWARE_AND_FEEDBACK);
});

test("hardware snapshot never claims a confirmed accelerator without evidence", () => {
  const snap = captureHardwareSnapshot(syntheticHardwareCapabilities());
  assert.equal(snap.accelerator_confirmed, false);
  assert.equal(snap.detected_backend, null);
  assert.match(snap.limitation, /nvidia-smi/i);
});

test("hardware snapshot confirms cuda only when both GPU and CUDA capabilities are AVAILABLE", () => {
  const caps = [
    { name: "NVIDIA GPU", state: "AVAILABLE", detail: "1 device", version: null },
    { name: "CUDA runtime", state: "AVAILABLE", detail: "", version: "12.1" },
  ];
  const snap = captureHardwareSnapshot(caps);
  assert.equal(snap.accelerator_confirmed, true);
  assert.equal(snap.detected_backend, "cuda");
});

test("proposeHardwareAdjustments returns bounded values only", () => {
  const snap = captureHardwareSnapshot(syntheticHardwareCapabilities());
  const adjustments = proposeHardwareAdjustments(snap);
  assert.equal(adjustments.length, 1);
  const adj = adjustments[0];
  assert.ok(adj.proposed_value >= adj.min_bound && adj.proposed_value <= adj.max_bound);
  assert.match(adj.evidence_reference, /^hardware_snapshot:/);
});

test("buildParameterAdjustment rejects an out-of-bounds proposal", () => {
  assert.throws(
    () => buildParameterAdjustment({ parameterName: "p", previousValue: 1, proposedValue: 99, minBound: 0, maxBound: 8, rationale: "r", evidenceReference: "e" }),
    ParameterBoundsError,
  );
});

test("buildParameterAdjustment rejects inverted bounds", () => {
  assert.throws(
    () => buildParameterAdjustment({ parameterName: "p", previousValue: 1, proposedValue: 4, minBound: 10, maxBound: 0, rationale: "r", evidenceReference: "e" }),
    ParameterBoundsError,
  );
});

test("buildParameterAdjustment accepts an in-bounds proposal", () => {
  const adj = buildParameterAdjustment({ parameterName: "p", previousValue: 1, proposedValue: 4, minBound: 0, maxBound: 8, rationale: "r", evidenceReference: "e" });
  assert.equal(adj.proposed_value, 4);
});

test("run_state CALIBRATED can pair with calibration_state UNCALIBRATED or PROVISIONAL -- never conflated", () => {
  const store = new CalibrationProfileStore();
  const zeroEvidence = store.run({ capabilities: syntheticHardwareCapabilities(), evaluationSummary: { total_evaluations: 0, total_outputs_evaluated: 0 } });
  assert.equal(zeroEvidence.run_state, "CALIBRATED");
  assert.equal(zeroEvidence.calibration_state, "UNCALIBRATED");

  const evalStore = new EvaluationStore();
  addEvaluations(evalStore, "out-1", { alice: 4, bob: 4 });
  const withEvidence = store.run({
    capabilities: syntheticHardwareCapabilities(),
    evaluationStore: evalStore,
    evaluationSummary: { total_evaluations: 2, total_outputs_evaluated: 1 },
    outputsWithDisagreementFn: outputsWithDisagreement,
  });
  assert.equal(withEvidence.run_state, "CALIBRATED");
  assert.equal(withEvidence.calibration_state, "PROVISIONAL");
});

test("profile versions increment and the log is append-only", () => {
  const store = new CalibrationProfileStore();
  const p1 = store.run({ capabilities: syntheticHardwareCapabilities() });
  const p2 = store.run({ capabilities: syntheticHardwareCapabilities() });
  assert.equal(p1.profile_version, 1);
  assert.equal(p2.profile_version, 2);
  assert.equal(store.history().length, 2);
});

test("rollback appends a new record, never deletes or mutates history", () => {
  const store = new CalibrationProfileStore();
  const p1 = store.run({ capabilities: syntheticHardwareCapabilities() });
  const p2 = store.run({ capabilities: syntheticHardwareCapabilities() });
  const rolled = store.rollback(p1.profile_id);

  assert.equal(store.history().length, 3);
  assert.equal(rolled.is_rollback, true);
  assert.equal(rolled.supersedes, p2.profile_id);
  assert.equal(rolled.run_state, p1.run_state);
  assert.deepEqual(store.history()[0], p1);
});

test("rollback to an unknown profile id throws RollbackTargetNotFound", () => {
  const store = new CalibrationProfileStore();
  assert.throws(() => store.rollback("nope"), RollbackTargetNotFound);
});

test("profile carries provenance fields", () => {
  const store = new CalibrationProfileStore();
  const profile = store.run({ capabilities: syntheticHardwareCapabilities() });
  for (const field of ["profile_id", "created_at", "hardware_snapshot", "evidence_counts"]) {
    assert.ok(profile[field], `expected ${field} to be present`);
  }
});

test("calibration profile has no speaker-identity fields", () => {
  const store = new CalibrationProfileStore();
  const profile = store.run({ capabilities: syntheticHardwareCapabilities() });
  for (const forbidden of ["speaker_id", "target_speaker", "voice_id", "embedding", "speaker_name"]) {
    assert.equal(Object.prototype.hasOwnProperty.call(profile, forbidden), false);
  }
});
