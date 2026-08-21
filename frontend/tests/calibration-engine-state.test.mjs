// Pure-logic tests for VL-D7's client-side calibration engine state
// (state/calibration-engine-model.js), extended in VL-D8. Mirrors
// tests/test_calibration_engine.py's scenarios: zero/insufficient/
// sufficient evidence, strategy selection, hardware snapshot honesty,
// run-state/evidence-state independence, bounded parameter enforcement,
// append-only rollback, provenance, and (VL-D8) application/validation.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ApplicationState,
  AdjustmentNotFound,
  CalibrationProfileNotFound,
  CalibrationProfileStore,
  CalibrationRunState,
  CalibrationStrategy,
  CalibrationState,
  MIN_EVIDENCE_FOR_PROVISIONAL,
  ParameterBoundsError,
  RollbackTargetNotFound,
  ValidationWithoutApplicationError,
  buildParameterAdjustment,
  captureHardwareSnapshot,
  computeBatchCount,
  proposeHardwareAdjustments,
  assessReadiness,
  selectStrategy,
  agreementRate,
} from "../state/calibration-engine-model.js";
import { EvaluationStore, EvaluationCompletionState, outputsWithDisagreement } from "../state/evaluation-model.js";
import { GenerationQueueStore, GenerationModelStore, InvalidConcurrencyError } from "../state/generation-model.js";
import { syntheticHardwareCapabilities, syntheticGenerationModels } from "../state/synthetic-fixtures.js";

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

// =============================================================================
// VL-D8 -- Calibration Application & Validation Loop
// =============================================================================

function makeQueue() {
  const modelStore = new GenerationModelStore();
  for (const model of syntheticGenerationModels()) modelStore.register(model);
  return new GenerationQueueStore({ modelStore });
}

test("GenerationQueueStore defaults to null concurrency and rejects invalid values", () => {
  const queue = makeQueue();
  assert.equal(queue.maxConcurrentGenerations, null);
  for (const invalid of [0, -1, 2.5, "3"]) {
    assert.throws(() => queue.setMaxConcurrentGenerations(invalid), InvalidConcurrencyError);
  }
  queue.setMaxConcurrentGenerations(4);
  assert.equal(queue.maxConcurrentGenerations, 4);
});

test("computeBatchCount matches the backend's ceiling-division formula", () => {
  assert.equal(computeBatchCount(6, 2), 3);
  assert.equal(computeBatchCount(6, 1), 6);
  assert.equal(computeBatchCount(5, null), 1);
  assert.equal(computeBatchCount(0, 2), 0);
});

test("applyAdjustment creates a new APPLIED profile and never edits the source", () => {
  const store = new CalibrationProfileStore();
  const proposed = store.run({ capabilities: syntheticHardwareCapabilities() });

  const applied = store.applyAdjustment({ profileId: proposed.profile_id, parameterName: "max_concurrent_generations" });

  assert.equal(applied.application_state, ApplicationState.APPLIED);
  assert.equal(applied.applied_from_profile_id, proposed.profile_id);
  assert.notEqual(applied.profile_id, proposed.profile_id);
  assert.deepEqual(store.history()[0], proposed);
  assert.equal(proposed.application_state, ApplicationState.PROPOSED);
});

test("applyAdjustment actually sets the real queue value when a queue is supplied", () => {
  const store = new CalibrationProfileStore();
  const proposed = store.run({ capabilities: syntheticHardwareCapabilities() });
  const queue = makeQueue();

  const applied = store.applyAdjustment({
    profileId: proposed.profile_id,
    parameterName: "max_concurrent_generations",
    queue,
  });

  assert.equal(queue.maxConcurrentGenerations, Math.round(applied.applied_value));
});

test("applyAdjustment works without a queue, still recording APPLIED state", () => {
  const store = new CalibrationProfileStore();
  const proposed = store.run({ capabilities: syntheticHardwareCapabilities() });
  const applied = store.applyAdjustment({ profileId: proposed.profile_id, parameterName: "max_concurrent_generations" });
  assert.equal(applied.application_state, ApplicationState.APPLIED);
});

test("applyAdjustment rejects an unknown parameter name", () => {
  const store = new CalibrationProfileStore();
  const proposed = store.run({ capabilities: syntheticHardwareCapabilities() });
  assert.throws(
    () => store.applyAdjustment({ profileId: proposed.profile_id, parameterName: "nope" }),
    AdjustmentNotFound,
  );
});

test("applyAdjustment rejects an unknown profile id", () => {
  const store = new CalibrationProfileStore();
  assert.throws(
    () => store.applyAdjustment({ profileId: "cal-profile-nope", parameterName: "max_concurrent_generations" }),
    CalibrationProfileNotFound,
  );
});

test("applyAdjustment can be repeated, appending a new profile each time", () => {
  const store = new CalibrationProfileStore();
  const proposed = store.run({ capabilities: syntheticHardwareCapabilities() });
  const first = store.applyAdjustment({ profileId: proposed.profile_id, parameterName: "max_concurrent_generations" });
  const second = store.applyAdjustment({ profileId: proposed.profile_id, parameterName: "max_concurrent_generations" });

  assert.notEqual(first.profile_id, second.profile_id);
  assert.equal(second.supersedes, first.profile_id);
  assert.equal(store.history().length, 3);
});

test("validateCalibration rejects a profile that was never applied", () => {
  const store = new CalibrationProfileStore();
  const proposed = store.run({ capabilities: syntheticHardwareCapabilities() });
  assert.throws(
    () => store.validateCalibration({ profileId: proposed.profile_id }),
    ValidationWithoutApplicationError,
  );
});

test("validateCalibration rejects an unknown profile id", () => {
  const store = new CalibrationProfileStore();
  assert.throws(() => store.validateCalibration({ profileId: "cal-profile-nope" }), CalibrationProfileNotFound);
});

test("validateCalibration measures a real before/after batch-count delta", () => {
  const store = new CalibrationProfileStore();
  const proposed = store.run({ capabilities: syntheticHardwareCapabilities() });
  const applied = store.applyAdjustment({ profileId: proposed.profile_id, parameterName: "max_concurrent_generations" });

  const validated = store.validateCalibration({ profileId: applied.profile_id, fixtureItemCount: 6 });

  assert.equal(validated.application_state, ApplicationState.VALIDATED);
  const v = validated.validation;
  assert.equal(v.validated, true);
  assert.equal(v.not_measurable, false);
  assert.equal(v.before_batch_count, 6);
  assert.equal(v.after_batch_count, computeBatchCount(6, Math.round(applied.applied_value)));
  assert.equal(v.measured_delta, v.before_batch_count - v.after_batch_count);
  assert.ok(v.measured_delta > 0);
  assert.match(v.note, /voice-quality/);
});

test("validateCalibration reports NOT_MEASURABLE honestly for a too-small fixture", () => {
  const store = new CalibrationProfileStore();
  const proposed = store.run({ capabilities: syntheticHardwareCapabilities() });
  const applied = store.applyAdjustment({ profileId: proposed.profile_id, parameterName: "max_concurrent_generations" });

  const validated = store.validateCalibration({ profileId: applied.profile_id, fixtureItemCount: 1 });

  assert.equal(validated.validation.validated, false);
  assert.equal(validated.validation.not_measurable, true);
  assert.equal(validated.validation.measured_delta, null);
});

test("validateCalibration never overwrites a prior validation -- each call appends", () => {
  const store = new CalibrationProfileStore();
  const proposed = store.run({ capabilities: syntheticHardwareCapabilities() });
  const applied = store.applyAdjustment({ profileId: proposed.profile_id, parameterName: "max_concurrent_generations" });

  const firstValidation = store.validateCalibration({ profileId: applied.profile_id, fixtureItemCount: 6 });
  const secondValidation = store.validateCalibration({ profileId: applied.profile_id, fixtureItemCount: 6 });

  assert.notEqual(firstValidation.profile_id, secondValidation.profile_id);
  assert.equal(store.history().length, 4);
  assert.deepEqual(store.history()[2], firstValidation);
});

test("full propose -> apply -> validate lifecycle is append-only with independent state axes", () => {
  const store = new CalibrationProfileStore();
  const proposed = store.run({ capabilities: syntheticHardwareCapabilities() });
  const applied = store.applyAdjustment({ profileId: proposed.profile_id, parameterName: "max_concurrent_generations" });
  const validated = store.validateCalibration({ profileId: applied.profile_id, fixtureItemCount: 6 });

  const history = store.history();
  assert.deepEqual(
    history.map((r) => r.application_state),
    [ApplicationState.PROPOSED, ApplicationState.APPLIED, ApplicationState.VALIDATED],
  );
  assert.ok(history.every((r) => r.run_state === "CALIBRATED"));
  assert.ok(history.every((r) => r.calibration_state === "UNCALIBRATED"));
  assert.deepEqual(history[0], proposed);
  assert.deepEqual(history[1], applied);
  assert.deepEqual(history[2], validated);
});

test("VL-D7 default profiles default to PROPOSED application state", () => {
  const store = new CalibrationProfileStore();
  const profile = store.run({ capabilities: syntheticHardwareCapabilities() });
  assert.equal(profile.application_state, ApplicationState.PROPOSED);
  assert.equal(profile.applied_from_profile_id, null);
  assert.equal(profile.applied_value, null);
  assert.equal(profile.validation, null);
});
