// Client-side AI Calibration Engine state (VL-D7). Mirrors
// pipeline.calibration_engine's vocabulary, validation, and honesty
// rules exactly, but this is a session-scoped, in-memory simulation over
// synthetic hardware-capability data -- there is still no execution
// transport to run a real environment.audit probe from the browser, so
// hardware facts here come from what the browser itself can honestly
// report (navigator.hardwareConcurrency, navigator.deviceMemory where
// available) plus synthetic capability fixtures, never a fabricated
// measurement.
//
// Two independent state axes, same as the backend: CalibrationRunState
// (did the engine's own run finish?) and identity.calibration's
// CalibrationState-equivalent evidence state (is there real evidence?).
// A CALIBRATED run_state next to an UNCALIBRATED or PROVISIONAL
// calibration_state is the expected, honest outcome, not a bug.
//
// Same field-naming convention as evaluation-model.js: records shaped
// like a backend `to_dict()` keep that exact snake_case shape; store and
// function names stay camelCase.

// Mirrors pipeline.calibration_engine.CalibrationRunState exactly --
// also the frontend's pre-existing hardware_calibration status domain
// (tokens/status.json), reserved since VL-D1, now finally driven by
// real (session-only) state instead of a hardcoded placeholder.
export const CalibrationRunState = Object.freeze({
  UNCALIBRATED: "UNCALIBRATED",
  NOT_TESTED: "NOT_TESTED",
  CALIBRATING: "CALIBRATING",
  CALIBRATED: "CALIBRATED",
  FAILED: "FAILED",
  UNKNOWN: "UNKNOWN",
});

export const CalibrationStrategy = Object.freeze({
  NONE: "NONE",
  HARDWARE_ONLY: "HARDWARE_ONLY",
  HARDWARE_AND_FEEDBACK: "HARDWARE_AND_FEEDBACK",
});

/** Mirrors identity.calibration.CalibrationState -- reused, not
 * reinvented, exactly as the backend engine reuses it unchanged. */
export const CalibrationState = Object.freeze({
  UNCALIBRATED: "UNCALIBRATED",
  PROVISIONAL: "PROVISIONAL",
  CALIBRATED: "CALIBRATED",
});

export const CalibrationEvidence = Object.freeze({
  NONE: "none",
  REVIEWER_FEEDBACK: "reviewer_feedback",
});

/** Mirrors pipeline.calibration_engine.MIN_EVIDENCE_FOR_PROVISIONAL. */
export const MIN_EVIDENCE_FOR_PROVISIONAL = 2;

export const HARDWARE_DETECTION_LIMITATION =
  "Accelerator detection today only actively probes for NVIDIA GPUs via nvidia-smi " +
  "(see environment.audit.check_gpu). AMD, Intel, and Apple accelerators are " +
  "architecturally representable but not yet detected. The absence of a detected " +
  "NVIDIA GPU does not confirm a CPU-only host on non-NVIDIA hardware. In the " +
  "browser, CPU core count and (where the browser exposes it) approximate memory " +
  "are the only hardware facts read directly -- everything else comes from the " +
  "synthetic capability fixture supplied to this session.";

/** Mirrors pipeline.calibration_engine.ParameterBoundsError. */
export class ParameterBoundsError extends Error {}

/** Mirrors pipeline.calibration_engine.RollbackTargetNotFound. */
export class RollbackTargetNotFound extends Error {}

/** Mirrors pipeline.calibration_engine.CalibrationParameterAdjustment --
 * refuses a proposal outside its own declared bounds rather than
 * clamping it silently. */
export function buildParameterAdjustment({
  parameterName,
  previousValue,
  proposedValue,
  minBound,
  maxBound,
  rationale,
  evidenceReference,
}) {
  if (minBound > maxBound) {
    throw new ParameterBoundsError(`${parameterName}: min_bound ${minBound} exceeds max_bound ${maxBound}`);
  }
  if (proposedValue < minBound || proposedValue > maxBound) {
    throw new ParameterBoundsError(
      `${parameterName}: proposed value ${proposedValue} is outside the declared bounds [${minBound}, ${maxBound}]`,
    );
  }
  return {
    parameter_name: parameterName,
    previous_value: previousValue,
    proposed_value: proposedValue,
    min_bound: minBound,
    max_bound: maxBound,
    rationale,
    evidence_reference: evidenceReference,
  };
}

/** Honest browser-measurable hardware facts + a supplied capability
 * list -- mirrors pipeline.calibration_engine.HardwareSnapshot.capture()
 * exactly in shape and in its "never claim a confirmed accelerator
 * without evidence" rule. `capabilities` is an array shaped like
 * aarya_voice_lab.core.capability.Capability.to_dict() (see
 * synthetic-fixtures.js's syntheticHardwareCapabilities()). */
export function captureHardwareSnapshot(capabilities = []) {
  const gpu = capabilities.find((c) => c.name === "NVIDIA GPU") || null;
  const cuda = capabilities.find((c) => c.name === "CUDA runtime") || null;
  const acceleratorConfirmed = !!gpu && gpu.state === "AVAILABLE";
  let detectedBackend = null;
  if (acceleratorConfirmed && cuda && cuda.state === "AVAILABLE") {
    detectedBackend = "cuda";
  } else if (acceleratorConfirmed) {
    detectedBackend = "other";
  }

  const logicalCores =
    typeof navigator !== "undefined" && typeof navigator.hardwareConcurrency === "number"
      ? navigator.hardwareConcurrency
      : null;
  const totalRamGb =
    typeof navigator !== "undefined" && typeof navigator.deviceMemory === "number"
      ? navigator.deviceMemory
      : null;

  return {
    captured_at: new Date().toISOString(),
    capabilities: capabilities.map((c) => ({ ...c })),
    logical_cores: logicalCores,
    total_ram_gb: totalRamGb,
    detected_backend: detectedBackend,
    accelerator_confirmed: acceleratorConfirmed,
    limitation: HARDWARE_DETECTION_LIMITATION,
  };
}

/** Mirrors pipeline.calibration_engine.propose_hardware_adjustments --
 * bounded, hardware-derived runtime-performance proposals only. Never a
 * voice-quality parameter. */
export function proposeHardwareAdjustments(snapshot) {
  const cores = snapshot.logical_cores || 1;
  const proposed = Math.max(1, Math.min(Math.floor(cores / 2), 8));
  return [
    buildParameterAdjustment({
      parameterName: "max_concurrent_generations",
      previousValue: 1,
      proposedValue: proposed,
      minBound: 1,
      maxBound: 8,
      rationale: `derived from ${cores} logical CPU core(s) detected in this browser (capped at 8 to avoid oversubscription)`,
      evidenceReference: `hardware_snapshot:${snapshot.captured_at}`,
    }),
  ];
}

/** Mirrors pipeline.calibration_engine.assess_readiness. */
export function assessReadiness({ evaluationSummary = null, previewSummary = null } = {}) {
  const totalEvaluations = evaluationSummary ? evaluationSummary.total_evaluations : 0;
  const totalOutputs = evaluationSummary ? evaluationSummary.total_outputs_evaluated : 0;
  const totalPreviewFeedback = previewSummary
    ? (previewSummary.accepted_count || 0) + (previewSummary.rejected_count || 0)
    : 0;

  const sufficient = totalEvaluations >= MIN_EVIDENCE_FOR_PROVISIONAL;
  const reasons = [];
  if (totalEvaluations === 0) {
    reasons.push("no human evaluations recorded yet");
  } else if (!sufficient) {
    reasons.push(
      `only ${totalEvaluations} evaluation(s) recorded; at least ${MIN_EVIDENCE_FOR_PROVISIONAL} are needed ` +
        "before reviewer-feedback evidence can even be considered provisional",
    );
  }

  return {
    total_evaluations: totalEvaluations,
    total_outputs_evaluated: totalOutputs,
    total_preview_feedback: totalPreviewFeedback,
    evidence_sufficient_for_provisional: sufficient,
    reasons,
    note:
      "Hardware readiness is always available (a snapshot can always be captured). " +
      "Evidence readiness reflects real evaluation counts only -- never fabricated or estimated.",
  };
}

/** Mirrors pipeline.calibration_engine.select_strategy. */
export function selectStrategy(readiness) {
  return readiness.evidence_sufficient_for_provisional
    ? CalibrationStrategy.HARDWARE_AND_FEEDBACK
    : CalibrationStrategy.HARDWARE_ONLY;
}

/** A real, computed ratio -- never a fabricated confidence number.
 * Reuses evaluation-model.js's outputsWithDisagreement exactly, the
 * same reuse-not-duplicate relationship the backend engine has with
 * pipeline.evaluation_aggregation. */
export function agreementRate(evaluationStore, outputsWithDisagreementFn) {
  const records = evaluationStore ? evaluationStore.list() : [];
  if (!records.length) return null;
  const allOutputs = new Set(records.map((r) => r.output_id));
  const disagreementOutputs = new Set(outputsWithDisagreementFn(evaluationStore));
  let agreeing = 0;
  for (const id of allOutputs) if (!disagreementOutputs.has(id)) agreeing += 1;
  return Math.round((agreeing / allOutputs.size) * 1000) / 1000;
}

let _profileCounter = 0;

/** Session-only, append-only calibration profile log. Mirrors
 * pipeline.calibration_engine.CalibrationProfileLog/run_calibration/
 * rollback exactly, including the never-CALIBRATED-evidence rule and
 * the append-only rollback pattern (a new record, never a deletion or
 * edit). */
export class CalibrationProfileStore extends EventTarget {
  constructor() {
    super();
    /** @type {object[]} */
    this._records = [];
  }

  _nextProfileId() {
    _profileCounter += 1;
    return `cal-profile-${String(_profileCounter).padStart(5, "0")}`;
  }

  /** Run one calibration pass and append its profile. `capabilities` is
   * a synthetic Capability[] fixture; `evaluationStore`/`evaluationSummary`/
   * `previewSummary` are the same already-computed inputs the backend
   * expects -- this never re-derives them. */
  run({
    capabilities = [],
    evaluationStore = null,
    evaluationSummary = null,
    previewSummary = null,
    outputsWithDisagreementFn = null,
  } = {}) {
    const snapshot = captureHardwareSnapshot(capabilities);
    const readiness = assessReadiness({ evaluationSummary, previewSummary });
    const strategy = selectStrategy(readiness);
    const adjustments = proposeHardwareAdjustments(snapshot);
    const rate =
      evaluationStore && outputsWithDisagreementFn ? agreementRate(evaluationStore, outputsWithDisagreementFn) : null;

    let calibrationState;
    let evidence;
    let limitations;
    if (readiness.evidence_sufficient_for_provisional && rate !== null) {
      calibrationState = CalibrationState.PROVISIONAL;
      evidence = CalibrationEvidence.REVIEWER_FEEDBACK;
      limitations = [
        `Based on ${readiness.total_evaluations} reviewer decisions with ${(rate * 100).toFixed(1)}% agreement.`,
        "Reviewer agreement is not a labelled held-out set: reviewers saw the machine " +
          "recommendation before deciding, so their agreement is correlated with it and " +
          "cannot be treated as independent ground truth.",
        "Does not support a statistical error-rate claim.",
      ];
    } else {
      calibrationState = CalibrationState.UNCALIBRATED;
      evidence = CalibrationEvidence.NONE;
      limitations = ["Insufficient evidence for any calibration claim beyond UNCALIBRATED.", ...readiness.reasons];
    }

    const record = {
      profile_id: this._nextProfileId(),
      profile_version: this._records.length + 1,
      run_state: CalibrationRunState.CALIBRATED,
      calibration_state: calibrationState,
      evidence,
      strategy,
      hardware_snapshot: snapshot,
      adjustments,
      agreement_rate: rate,
      evidence_counts: {
        total_evaluations: readiness.total_evaluations,
        total_outputs_evaluated: readiness.total_outputs_evaluated,
        total_preview_feedback: readiness.total_preview_feedback,
      },
      limitations,
      supersedes: null,
      is_rollback: false,
      created_at: new Date().toISOString(),
    };
    this._records.push(record);
    this._announce(record);
    return record;
  }

  /** Append a new profile record reinstating `toProfileId`'s content as
   * active, without touching it or anything recorded after it. Never
   * deletes or mutates history. */
  rollback(toProfileId) {
    const target = this._records.find((r) => r.profile_id === toProfileId);
    if (!target) throw new RollbackTargetNotFound(toProfileId);

    const active = this.current();
    const record = {
      ...target,
      profile_id: this._nextProfileId(),
      profile_version: this._records.length + 1,
      supersedes: active ? active.profile_id : null,
      is_rollback: true,
      created_at: new Date().toISOString(),
    };
    this._records.push(record);
    this._announce(record);
    return record;
  }

  current() {
    return this._records.length ? this._records[this._records.length - 1] : null;
  }

  history() {
    return [...this._records];
  }

  _announce(record) {
    this.dispatchEvent(new CustomEvent("change", { detail: { record } }));
  }
}
