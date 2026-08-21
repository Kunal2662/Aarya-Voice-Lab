"""AI Calibration Engine — VL-D7.

The engine `pipeline.calibration_prep` (VL-D3 §27, extended VL-D5 §23,
VL-D6) has been preparing raw counts for since it was written: reads the
three existing calibration-input summaries, detects this host's hardware
via the existing `environment.audit`/`system_info` probes, and produces a
versioned, append-only `CalibrationProfile` recording what it found and
what it honestly can and cannot conclude from it.

## Two independent state axes — never conflate them

* **`CalibrationRunState`** — did the engine's own process complete? A
  hardware snapshot was captured, evidence was read, a strategy was
  selected, a profile was written. This can be `CALIBRATED` (the run
  finished) even when the *evidence* backing the profile is `UNCALIBRATED`.
* **`identity.calibration.CalibrationState`** — is there real evidence
  behind a claim? Reused unchanged from Phase 3. `CALIBRATED` here
  requires labelled held-out data, which — per `identity.calibration`'s
  own module docstring — is unreachable for the target speaker by
  construction. This engine never attempts to produce it: the best
  reachable evidence state is `PROVISIONAL`, via the same
  `provisional_from_reviewer_feedback` that VL-D6 built and deliberately
  left uncalled for this exact future phase.

A successful run (`run_state=CALIBRATED`) paired with `PROVISIONAL` or
even `UNCALIBRATED` evidence is not a bug — it is the honest, expected
outcome whenever human-evaluation evidence is thin or absent.

## Parameter scope, deliberately narrow

This phase's bounded parameter adjustments are **hardware/runtime
performance parameters only** (e.g. recommended generation concurrency),
derived from `HardwareSnapshot` and bounded by it. No voice-quality
parameter is ever adjusted: doing so would require calibrated quality
evidence this project does not have, and proposing one anyway would be
exactly the fabricated-improvement claim this project must never make.
Reviewer-feedback evidence (when sufficient) only ever affects the
*evidence state* of the resulting profile, never a numeric parameter.

## Hardware detection, honestly bounded

`HardwareSnapshot` does not add a new hardware probe. It reads
`environment.audit.run_audit()` (which itself reads `system_info`) and
`identity.runtime`'s vendor-neutral vocabulary. `environment.audit`'s GPU
check today only actively probes for NVIDIA hardware via `nvidia-smi` —
an AMD, Intel, or Apple accelerator is architecturally representable
(`identity.runtime.ComputeBackend` has ROCM/METAL/OPENCL/VULKAN/XPU/OTHER
members precisely so it does not need a schema change later) but is not
yet actively detected. `HardwareSnapshot` reports this limitation
verbatim rather than reporting "no accelerator" as if it were a
confirmed CPU-only host.

## What this module never does

Never reads `data_root.source`, never computes an embedding, never
trains anything, never infers or stores a speaker-identity field, never
bypasses `pipeline.dataset_gate`, never talks to the network. It reads
already-computed summaries and already-detected capabilities and writes
a profile record — the same "pure aggregation/orchestration over
existing data" shape as `pipeline.evaluation_aggregation`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from aarya_voice_lab import __version__
from aarya_voice_lab.core.capability import CapabilityState
from aarya_voice_lab.environment.audit import EnvironmentAudit, run_audit
from aarya_voice_lab.identity.calibration import (
    CalibrationEvidence,
    CalibrationState,
    provisional_from_reviewer_feedback,
    uncalibrated,
)
from aarya_voice_lab.identity.runtime import ComputeBackend
from aarya_voice_lab.pipeline.calibration_prep import (
    EvaluationCalibrationInputSummary,
    PreviewCalibrationInputSummary,
)
from aarya_voice_lab.pipeline.evaluation import EvaluationLog
from aarya_voice_lab.pipeline.evaluation_aggregation import outputs_with_disagreement
from aarya_voice_lab.registry.json_registry import JsonLinesRegistry
from aarya_voice_lab.schemas.base import SchemaName
from aarya_voice_lab.system_info import SystemReport, collect_system_report

CALIBRATION_ENGINE_VERSION = "1.0.0"

#: At least this many human evaluations must exist before reviewer
#: feedback is even considered for PROVISIONAL evidence. Mirrors
#: `pipeline.evaluation_aggregation.MIN_EVALUATIONS_FOR_DISAGREEMENT`:
#: below this, "agreement" isn't a meaningful statement either.
MIN_EVIDENCE_FOR_PROVISIONAL = 2

GPU_CAPABILITY_NAME = "NVIDIA GPU"
CUDA_CAPABILITY_NAME = "CUDA runtime"

HARDWARE_DETECTION_LIMITATION = (
    "Accelerator detection today only actively probes for NVIDIA GPUs via "
    "nvidia-smi (see environment.audit.check_gpu). AMD, Intel, and Apple "
    "accelerators are architecturally representable (identity.runtime."
    "ComputeBackend) but not yet detected. The absence of a detected NVIDIA "
    "GPU does not confirm a CPU-only host on non-NVIDIA hardware."
)


class CalibrationRunState(StrEnum):
    """Process/lifecycle state of one calibration engine run.

    Mirrors `frontend/tokens/status.json`'s `hardware_calibration` domain
    exactly (reserved since VL-D1, unused until this phase). `CALIBRATING`
    is a UI-facing transient state, the same role `pipeline_stage`'s
    `running` already plays elsewhere — this module's `run_calibration`
    is synchronous and only ever returns a terminal state.
    """

    UNCALIBRATED = "UNCALIBRATED"
    NOT_TESTED = "NOT_TESTED"
    CALIBRATING = "CALIBRATING"
    CALIBRATED = "CALIBRATED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class CalibrationStrategy(StrEnum):
    """Which class of calibration action the engine took, and why."""

    #: No run has been attempted yet, or hardware capture failed.
    NONE = "NONE"
    #: Evidence is insufficient for anything evidence-based; only
    #: hardware-derived runtime parameters were considered.
    HARDWARE_ONLY = "HARDWARE_ONLY"
    #: Hardware parameters plus enough reviewer-feedback evidence to
    #: support a PROVISIONAL evidence state (never CALIBRATED).
    HARDWARE_AND_FEEDBACK = "HARDWARE_AND_FEEDBACK"


class ParameterBoundsError(ValueError):
    """Raised when a proposed parameter value falls outside its own
    declared bounds, or the bounds themselves are inverted."""


class CalibrationEngineError(RuntimeError):
    """Raised for a calibration-engine operation that cannot proceed."""


@dataclass(frozen=True)
class CalibrationParameterAdjustment:
    """One bounded, evidence-referenced runtime parameter proposal.

    Every field the security review asked for is present and required:
    no adjustment can be constructed that lacks bounds, a rationale, or
    an evidence reference. `__post_init__` refuses a proposal outside
    its own declared bounds rather than silently clamping it — clamping
    would hide a bug in whatever proposed the value.
    """

    parameter_name: str
    previous_value: float
    proposed_value: float
    min_bound: float
    max_bound: float
    rationale: str
    evidence_reference: str

    def __post_init__(self) -> None:
        if self.min_bound > self.max_bound:
            raise ParameterBoundsError(
                f"{self.parameter_name}: min_bound {self.min_bound} exceeds max_bound {self.max_bound}"
            )
        if not self.min_bound <= self.proposed_value <= self.max_bound:
            raise ParameterBoundsError(
                f"{self.parameter_name}: proposed value {self.proposed_value} is outside "
                f"the declared bounds [{self.min_bound}, {self.max_bound}]"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter_name": self.parameter_name,
            "previous_value": self.previous_value,
            "proposed_value": self.proposed_value,
            "min_bound": self.min_bound,
            "max_bound": self.max_bound,
            "rationale": self.rationale,
            "evidence_reference": self.evidence_reference,
        }


@dataclass(frozen=True)
class HardwareSnapshot:
    """A point-in-time capture of this host's capabilities.

    Built entirely from `environment.audit.run_audit()` (itself built on
    `system_info.collect_system_report()`) — no new probe is added here.
    `detected_backend` is deliberately `None` rather than `ComputeBackend.CPU`
    when no accelerator is confirmed present: on non-NVIDIA hardware that
    is an honest "not confirmed", not a verified fact. See
    `HARDWARE_DETECTION_LIMITATION`.
    """

    captured_at: str
    capabilities: tuple[dict[str, Any], ...]
    logical_cores: int | None
    total_ram_gb: float | None
    detected_backend: ComputeBackend | None
    accelerator_confirmed: bool
    limitation: str = HARDWARE_DETECTION_LIMITATION

    @classmethod
    def capture(
        cls,
        *,
        audit: EnvironmentAudit | None = None,
        report: SystemReport | None = None,
    ) -> HardwareSnapshot:
        audit = audit if audit is not None else run_audit()
        report = report if report is not None else collect_system_report()

        gpu = audit.get(GPU_CAPABILITY_NAME)
        cuda = audit.get(CUDA_CAPABILITY_NAME)
        accelerator_confirmed = gpu is not None and gpu.state is CapabilityState.AVAILABLE
        if accelerator_confirmed and cuda is not None and cuda.state is CapabilityState.AVAILABLE:
            detected_backend: ComputeBackend | None = ComputeBackend.CUDA
        elif accelerator_confirmed:
            detected_backend = ComputeBackend.OTHER
        else:
            detected_backend = None

        return cls(
            captured_at=datetime.now(UTC).isoformat(),
            capabilities=tuple(c.to_dict() for c in audit.capabilities),
            logical_cores=report.cpu.logical_cores,
            total_ram_gb=(report.memory.total_bytes / (1024**3)) if report.memory.total_bytes else None,
            detected_backend=detected_backend,
            accelerator_confirmed=accelerator_confirmed,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "captured_at": self.captured_at,
            "capabilities": list(self.capabilities),
            "logical_cores": self.logical_cores,
            "total_ram_gb": round(self.total_ram_gb, 3) if self.total_ram_gb is not None else None,
            "detected_backend": self.detected_backend.value if self.detected_backend else None,
            "accelerator_confirmed": self.accelerator_confirmed,
            "limitation": self.limitation,
        }


def propose_hardware_adjustments(snapshot: HardwareSnapshot) -> list[CalibrationParameterAdjustment]:
    """Bounded, hardware-derived runtime-performance proposals only.

    Deliberately does not touch anything voice-quality-related — see the
    module docstring's "Parameter scope" section for why.
    """
    cores = snapshot.logical_cores or 1
    proposed = float(max(1, min(cores // 2, 8)))
    return [
        CalibrationParameterAdjustment(
            parameter_name="max_concurrent_generations",
            previous_value=1.0,
            proposed_value=proposed,
            min_bound=1.0,
            max_bound=8.0,
            rationale=(
                f"derived from {cores} logical CPU core(s) detected on this host "
                f"(capped at 8 to avoid oversubscription on larger machines)"
            ),
            evidence_reference=f"hardware_snapshot:{snapshot.captured_at}",
        )
    ]


@dataclass(frozen=True)
class CalibrationReadiness:
    """What the engine can honestly say about evidence sufficiency
    before selecting a strategy. Hardware readiness is always available
    — a snapshot can always be captured — evidence readiness reflects
    real counts only, never a fabricated estimate."""

    total_evaluations: int
    total_outputs_evaluated: int
    total_preview_feedback: int
    evidence_sufficient_for_provisional: bool
    reasons: tuple[str, ...]
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_evaluations": self.total_evaluations,
            "total_outputs_evaluated": self.total_outputs_evaluated,
            "total_preview_feedback": self.total_preview_feedback,
            "evidence_sufficient_for_provisional": self.evidence_sufficient_for_provisional,
            "reasons": list(self.reasons),
            "note": self.note,
        }


def assess_readiness(
    *,
    evaluation_summary: EvaluationCalibrationInputSummary | None = None,
    preview_summary: PreviewCalibrationInputSummary | None = None,
) -> CalibrationReadiness:
    """Read the existing VL-D6/VL-D5 calibration-prep summaries and
    report, honestly, whether there is enough evidence to attempt
    anything beyond hardware-only calibration. Computes no new count —
    every number here already exists in the summary it was read from."""
    total_evaluations = evaluation_summary.total_evaluations if evaluation_summary else 0
    total_outputs = evaluation_summary.total_outputs_evaluated if evaluation_summary else 0
    total_preview_feedback = (
        preview_summary.accepted_count + preview_summary.rejected_count if preview_summary else 0
    )

    sufficient = total_evaluations >= MIN_EVIDENCE_FOR_PROVISIONAL
    reasons: list[str] = []
    if total_evaluations == 0:
        reasons.append("no human evaluations recorded yet")
    elif not sufficient:
        reasons.append(
            f"only {total_evaluations} evaluation(s) recorded; at least "
            f"{MIN_EVIDENCE_FOR_PROVISIONAL} are needed before reviewer-feedback "
            "evidence can even be considered provisional"
        )

    return CalibrationReadiness(
        total_evaluations=total_evaluations,
        total_outputs_evaluated=total_outputs,
        total_preview_feedback=total_preview_feedback,
        evidence_sufficient_for_provisional=sufficient,
        reasons=tuple(reasons),
        note=(
            "Hardware readiness is always available (a snapshot can always be "
            "captured). Evidence readiness reflects real evaluation counts only "
            "-- never fabricated or estimated."
        ),
    )


def select_strategy(readiness: CalibrationReadiness) -> CalibrationStrategy:
    if readiness.evidence_sufficient_for_provisional:
        return CalibrationStrategy.HARDWARE_AND_FEEDBACK
    return CalibrationStrategy.HARDWARE_ONLY


def _agreement_rate(evaluation_log: EvaluationLog | None) -> float | None:
    """A real, computed ratio -- never a fabricated confidence number.

    Reuses `pipeline.evaluation_aggregation.outputs_with_disagreement`
    exactly as it stands; computes no new judgement, only a proportion
    over its output."""
    if evaluation_log is None:
        return None
    all_records = evaluation_log.list()
    if not all_records:
        return None
    all_outputs = {r["output_id"] for r in all_records}
    disagreement_outputs = set(outputs_with_disagreement(evaluation_log))
    agreeing = len(all_outputs) - len(all_outputs & disagreement_outputs)
    return agreeing / len(all_outputs)


@dataclass(frozen=True)
class CalibrationProfile:
    """One versioned, immutable calibration engine run. Append-only:
    persisted through `CalibrationProfileLog`, which -- like every other
    `JsonLinesRegistry` in this project -- never overwrites a record."""

    profile_id: str
    profile_version: int
    run_state: CalibrationRunState
    calibration_state: CalibrationState
    evidence: CalibrationEvidence
    strategy: CalibrationStrategy
    hardware_snapshot: dict[str, Any]
    adjustments: tuple[dict[str, Any], ...]
    agreement_rate: float | None
    evidence_counts: dict[str, int]
    limitations: tuple[str, ...]
    supersedes: str | None = None
    is_rollback: bool = False
    created_at: str | None = None
    engine_version: str = CALIBRATION_ENGINE_VERSION
    processing_version: str = __version__
    schema_version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "run_state": self.run_state.value,
            "calibration_state": self.calibration_state.value,
            "evidence": self.evidence.value,
            "strategy": self.strategy.value,
            "hardware_snapshot": self.hardware_snapshot,
            "adjustments": list(self.adjustments),
            "agreement_rate": round(self.agreement_rate, 6) if self.agreement_rate is not None else None,
            "evidence_counts": self.evidence_counts,
            "limitations": list(self.limitations),
            "supersedes": self.supersedes,
            "is_rollback": self.is_rollback,
            "created_at": self.created_at or datetime.now(UTC).isoformat(),
            "engine_version": self.engine_version,
            "processing_version": self.processing_version,
            "schema_version": self.schema_version,
        }


class CalibrationProfileLog(JsonLinesRegistry):
    def __init__(self, path):
        super().__init__(path=path, schema_name=SchemaName.CALIBRATION_PROFILE, id_field="profile_id")


def _next_profile_id(log: CalibrationProfileLog) -> str:
    return f"cal-profile-{len(log.list()) + 1:05d}"


def current_profile(log: CalibrationProfileLog) -> dict[str, Any] | None:
    records = log.list()
    return records[-1] if records else None


def profile_history(log: CalibrationProfileLog) -> list[dict[str, Any]]:
    return log.list()


def run_calibration(
    log: CalibrationProfileLog,
    *,
    evaluation_log: EvaluationLog | None = None,
    evaluation_summary: EvaluationCalibrationInputSummary | None = None,
    preview_summary: PreviewCalibrationInputSummary | None = None,
    hardware_snapshot: HardwareSnapshot | None = None,
) -> dict[str, Any]:
    """Run one calibration pass and append its profile.

    `evaluation_summary`/`preview_summary` are the outputs of
    `pipeline.calibration_prep.summarize_evaluation_calibration_inputs`/
    `summarize_preview_calibration_inputs` -- callers assemble those
    exactly as VL-D6 already does; this function never re-derives them.
    Never raises on thin evidence: honesty about insufficient evidence is
    a normal, successful outcome, not a failure. Only a hardware-snapshot
    capture failure produces `run_state=FAILED`.
    """
    try:
        snapshot = hardware_snapshot if hardware_snapshot is not None else HardwareSnapshot.capture()
    except Exception as exc:  # noqa: BLE001 - any probe failure must degrade to an honest FAILED record
        profile = CalibrationProfile(
            profile_id=_next_profile_id(log),
            profile_version=len(log.list()) + 1,
            run_state=CalibrationRunState.FAILED,
            calibration_state=CalibrationState.UNCALIBRATED,
            evidence=CalibrationEvidence.NONE,
            strategy=CalibrationStrategy.NONE,
            hardware_snapshot={},
            adjustments=(),
            agreement_rate=None,
            evidence_counts={},
            limitations=(f"Hardware snapshot capture failed: {exc}",),
        )
        payload = profile.to_dict()
        log.add(payload)
        return payload

    readiness = assess_readiness(evaluation_summary=evaluation_summary, preview_summary=preview_summary)
    strategy = select_strategy(readiness)
    adjustments = propose_hardware_adjustments(snapshot)
    agreement_rate = _agreement_rate(evaluation_log)

    if readiness.evidence_sufficient_for_provisional and agreement_rate is not None:
        base = uncalibrated("aarya-voice-lab-calibration-engine", CALIBRATION_ENGINE_VERSION, is_synthetic=False)
        record = provisional_from_reviewer_feedback(
            f"cal-evidence-{_next_profile_id(log)}",
            base,
            feedback_count=readiness.total_evaluations,
            agreement_rate=agreement_rate,
        )
        calibration_state = record.state
        evidence = record.evidence
        evidence_limitations = tuple(record.limitations)
    else:
        calibration_state = CalibrationState.UNCALIBRATED
        evidence = CalibrationEvidence.NONE
        evidence_limitations = (
            "Insufficient evidence for any calibration claim beyond UNCALIBRATED.",
            *readiness.reasons,
        )

    profile = CalibrationProfile(
        profile_id=_next_profile_id(log),
        profile_version=len(log.list()) + 1,
        run_state=CalibrationRunState.CALIBRATED,
        calibration_state=calibration_state,
        evidence=evidence,
        strategy=strategy,
        hardware_snapshot=snapshot.to_dict(),
        adjustments=tuple(a.to_dict() for a in adjustments),
        agreement_rate=agreement_rate,
        evidence_counts={
            "total_evaluations": readiness.total_evaluations,
            "total_outputs_evaluated": readiness.total_outputs_evaluated,
            "total_preview_feedback": readiness.total_preview_feedback,
        },
        limitations=evidence_limitations,
    )
    payload = profile.to_dict()
    log.add(payload)
    return payload


class RollbackTargetNotFound(KeyError):
    """Raised when `rollback()` is asked to roll back to a profile id
    that does not exist in the log."""


def rollback(log: CalibrationProfileLog, *, to_profile_id: str) -> dict[str, Any]:
    """Append a new profile record reinstating `to_profile_id`'s content
    as active, without touching it or anything recorded after it -- the
    same pattern `pipeline.processing_history.rollback` already
    established. Never deletes or mutates history."""
    target = log.get(to_profile_id)
    if target is None:
        raise RollbackTargetNotFound(to_profile_id)

    active = current_profile(log)
    payload = dict(target)
    payload["profile_id"] = _next_profile_id(log)
    payload["profile_version"] = len(log.list()) + 1
    payload["supersedes"] = active["profile_id"] if active else None
    payload["is_rollback"] = True
    payload["created_at"] = datetime.now(UTC).isoformat()
    log.add(payload)
    return payload
