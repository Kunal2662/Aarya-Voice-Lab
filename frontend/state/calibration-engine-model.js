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
  "Accelerator PRESENCE is now detected across vendors: NVIDIA via nvidia-smi, AMD " +
  "via rocm-smi, any other vendor via a PCI-id sysfs enumeration on Linux, or a " +
  "Windows WMI enumeration on Windows (see environment.audit.check_accelerator) -- " +
  "none needing a vendor tool installed. What is still " +
  "NOT detected is whether a matching compute RUNTIME actually works: only CUDA has " +
  "a runtime check here, so a detected AMD/other accelerator always yields " +
  "detected_backend=other, never a fabricated ROCm/Metal/OpenCL runtime claim. In " +
  "the browser, CPU core count and (where the browser exposes it) approximate " +
  "memory are the only hardware facts read directly -- everything else comes from " +
  "the synthetic capability fixture or live snapshot supplied to this session.";

/** Mirrors pipeline.calibration_engine.ParameterBoundsError. */
export class ParameterBoundsError extends Error {}

/** Mirrors pipeline.calibration_engine.RollbackTargetNotFound. */
export class RollbackTargetNotFound extends Error {}

// ---------------------------------------------------------------------
// VL-D8 -- Calibration Application & Validation Loop. Mirrors
// pipeline.calibration_engine's apply_adjustment()/validate_calibration()
// exactly in record shape and honesty rules. application_state
// (PROPOSED/APPLIED/VALIDATED) is a third axis, independent of
// run_state and calibration_state -- see calibration-run-panel.js.
// ---------------------------------------------------------------------

export const ApplicationState = Object.freeze({
  PROPOSED: "PROPOSED",
  APPLIED: "APPLIED",
  VALIDATED: "VALIDATED",
});

/** Mirrors pipeline.calibration_engine.CalibrationProfileNotFound. */
export class CalibrationProfileNotFound extends Error {}

/** Mirrors pipeline.calibration_engine.AdjustmentNotFound. */
export class AdjustmentNotFound extends Error {}

/** Mirrors pipeline.calibration_engine.ValidationWithoutApplicationError. */
export class ValidationWithoutApplicationError extends Error {}

const APPLICATION_TARGETS = new Set(["max_concurrent_generations"]);

/** Deterministic queue-batching formula -- exactly
 * pipeline.generation.GenerationQueue.process_all()'s batch-count math,
 * so the frontend measures the same real effect the backend does
 * without needing to drive the async, UI-progress-animated
 * GenerationQueueStore. A queue-batching measurement only -- never a
 * voice-quality claim. */
export function computeBatchCount(itemCount, maxConcurrent) {
  if (itemCount <= 0) return 0;
  const batchSize = maxConcurrent || itemCount;
  return Math.ceil(itemCount / batchSize);
}

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
  const accelerator = capabilities.find((c) => c.name === "Accelerator (any vendor)") || null;
  const cuda = capabilities.find((c) => c.name === "CUDA runtime") || null;
  const nvidiaConfirmed = !!gpu && gpu.state === "AVAILABLE";
  const anyAcceleratorConfirmed = !!accelerator && accelerator.state === "AVAILABLE";
  const acceleratorConfirmed = nvidiaConfirmed || anyAcceleratorConfirmed;
  let detectedBackend = null;
  if (nvidiaConfirmed && cuda && cuda.state === "AVAILABLE") {
    detectedBackend = "cuda";
  } else if (acceleratorConfirmed) {
    // A non-NVIDIA (or NVIDIA-without-confirmed-CUDA) accelerator is
    // present with no runtime-level check behind it yet -- "other" is
    // the honest answer, mirroring pipeline.calibration_engine exactly.
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
      application_state: ApplicationState.PROPOSED,
      applied_from_profile_id: null,
      applied_parameter_name: null,
      applied_value: null,
      applied_at: null,
      validation: null,
    };
    this._records.push(record);
    this._announce(record);
    return record;
  }

  /** Apply one of `profileId`'s proposed adjustments (VL-D8).
   * Re-validates bounds *now* by reconstructing the adjustment via
   * buildParameterAdjustment (never trusts the earlier proposal
   * blindly). For `max_concurrent_generations`, sets that value on
   * `queue` when supplied (a real state/generation-model.js
   * GenerationQueueStore-shaped object exposing
   * `setMaxConcurrentGenerations`). Never edits the source record --
   * appends a new APPLIED profile version. */
  applyAdjustment({ profileId, parameterName, queue = null }) {
    const source = this._records.find((r) => r.profile_id === profileId);
    if (!source) throw new CalibrationProfileNotFound(profileId);

    const match = (source.adjustments || []).find((a) => a.parameter_name === parameterName);
    if (!match) throw new AdjustmentNotFound(parameterName);

    const adjustment = buildParameterAdjustment({
      parameterName: match.parameter_name,
      previousValue: match.previous_value,
      proposedValue: match.proposed_value,
      minBound: match.min_bound,
      maxBound: match.max_bound,
      rationale: match.rationale,
      evidenceReference: match.evidence_reference,
    });

    if (queue) {
      if (!APPLICATION_TARGETS.has(parameterName)) {
        throw new Error(`no generation-pipeline application path exists for parameter ${parameterName}`);
      }
      queue.setMaxConcurrentGenerations(Math.round(adjustment.proposed_value));
    }

    const active = this.current();
    const now = new Date().toISOString();
    const record = {
      ...source,
      profile_id: this._nextProfileId(),
      profile_version: this._records.length + 1,
      supersedes: active ? active.profile_id : null,
      is_rollback: false,
      created_at: now,
      application_state: ApplicationState.APPLIED,
      applied_from_profile_id: source.profile_id,
      applied_parameter_name: parameterName,
      applied_value: adjustment.proposed_value,
      applied_at: now,
      validation: null,
    };
    this._records.push(record);
    this._announce(record);
    return record;
  }

  /** Measure whether an applied adjustment produced its expected
   * runtime effect (VL-D8), and append a new VALIDATED profile version.
   * `fixtureItemCount` (default 6) is the size of the synthetic fixture
   * set the deterministic batch-count formula is evaluated over;
   * `baselineMaxConcurrent` (default 1) is the "before" concurrency.
   * Reports validation.not_measurable=true / measured_delta=null when
   * the fixture size can't show a difference -- never fabricated. */
  validateCalibration({ profileId, fixtureItemCount = 6, baselineMaxConcurrent = 1 }) {
    const source = this._records.find((r) => r.profile_id === profileId);
    if (!source) throw new CalibrationProfileNotFound(profileId);
    if (source.application_state !== ApplicationState.APPLIED || source.applied_value == null) {
      throw new ValidationWithoutApplicationError(
        `${profileId} has application_state=${source.application_state}; validateCalibration requires APPLIED`,
      );
    }

    const appliedConcurrency = Math.round(source.applied_value);
    const beforeBatchCount = computeBatchCount(fixtureItemCount, baselineMaxConcurrent);
    const afterBatchCount = computeBatchCount(fixtureItemCount, appliedConcurrency);
    const now = new Date().toISOString();

    const measurable = fixtureItemCount > 0 && beforeBatchCount !== afterBatchCount;
    const validation = measurable
      ? {
          validated: true,
          before_batch_count: beforeBatchCount,
          after_batch_count: afterBatchCount,
          measured_delta: beforeBatchCount - afterBatchCount,
          not_measurable: false,
          note:
            `Measured over ${fixtureItemCount} synthetic queue item(s): baseline concurrency=` +
            `${baselineMaxConcurrent} -> ${beforeBatchCount} batch(es); applied concurrency=` +
            `${appliedConcurrency} -> ${afterBatchCount} batch(es). Queue-batching effect only -- ` +
            "not a voice-quality measurement.",
          validated_at: now,
        }
      : {
          validated: false,
          before_batch_count: beforeBatchCount || null,
          after_batch_count: afterBatchCount || null,
          measured_delta: null,
          not_measurable: true,
          note:
            "No measurable batch-count difference: either the fixture set was empty, or the " +
            "applied concurrency produced the same batch count as the baseline at this fixture " +
            "size. Not a fabricated result -- an honest report that this run could not " +
            "demonstrate the effect.",
          validated_at: now,
        };

    const active = this.current();
    const record = {
      ...source,
      profile_id: this._nextProfileId(),
      profile_version: this._records.length + 1,
      supersedes: active ? active.profile_id : null,
      is_rollback: false,
      created_at: now,
      application_state: ApplicationState.VALIDATED,
      validation,
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

  /** VL-D9 -- restores a previously exportCalibrationPlan()'d append-only
   * profile history verbatim. Every field a CalibrationProfile record
   * carries was already reviewed as calibration-engine bookkeeping only
   * (see docs/VLD8_CALIBRATION_APPLICATION.md's security boundary):
   * hardware_snapshot has no GPU product name, no speaker field
   * anywhere, agreement_rate is a real computed ratio, never a
   * fabricated confidence score. This is a pure restore of
   * already-computed history, never a re-run of run()/applyAdjustment()/
   * validateCalibration() -- restoring a VALIDATED record does not
   * re-measure anything, exactly as the append-only backend log never
   * re-derives a past record. A record missing profile_id/profile_version
   * or carrying an unknown run_state/application_state is dropped.
   * Also advances the module-level profile-id counter so a fresh
   * run()/applyAdjustment()/rollback() call after hydration can never
   * mint a profile_id that collides with a restored one. */
  hydrate(plan) {
    if (!plan || !Array.isArray(plan.calibration_profiles)) return false;
    const restored = plan.calibration_profiles
      .filter(
        (r) =>
          r &&
          typeof r.profile_id === "string" &&
          typeof r.profile_version === "number" &&
          Object.values(CalibrationRunState).includes(r.run_state) &&
          Object.values(ApplicationState).includes(r.application_state),
      )
      .map((r) => ({ ...r }));
    if (!restored.length) return false;
    this._records = restored;

    let maxCounter = 0;
    for (const record of restored) {
      const match = /^cal-profile-(\d+)$/.exec(record.profile_id);
      if (match) maxCounter = Math.max(maxCounter, parseInt(match[1], 10));
    }
    if (maxCounter > _profileCounter) _profileCounter = maxCounter;
    return true;
  }

  /** VL-D9 -- clears this store's profile history in place (same object
   * identity, so existing listeners/service references stay valid) and
   * announces a detail-less "change" so mounted UI re-renders
   * immediately. Backs the explicit "Clear session data" control -- never
   * called automatically. */
  reset() {
    this._records = [];
    this.dispatchEvent(new CustomEvent("change", { detail: {} }));
  }

  _announce(record) {
    this.dispatchEvent(new CustomEvent("change", { detail: { record } }));
  }
}

/** VL-D9 -- the calibration store's missing export function, added
 * following the same convention as VL-D2-D6's exportXPlan() functions:
 * `history()` already returns the exact backend-shaped
 * CalibrationProfile records (see run()/applyAdjustment()/
 * validateCalibration()/rollback() above), so this wraps that append-only
 * log the same way exportReviewPlan()/exportProcessingPlan()/
 * exportGenerationPlan()/exportEvaluationPlan() wrap theirs -- never a
 * second, divergent serialization format. */
export function exportCalibrationPlan(store) {
  return {
    is_synthetic: true,
    generated_by: "frontend client-side calibration engine (session-only, not authoritative)",
    calibration_profiles: store.history(),
  };
}
