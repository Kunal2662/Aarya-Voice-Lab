"""Threshold configuration and calibration state.

The central honesty requirement of Phase 3: a threshold that has not been
validated against labelled held-out data must never be presented as
though it has been.

## Why target-speaker calibration is impossible today

Calibrating an acceptance threshold requires a labelled held-out set —
recordings known to be the target speaker, excluded from enrollment.
Every recording of the target speaker is inside the dataset being
labelled, and the labels are precisely what verification is trying to
produce. There is no held-out set and there cannot be one.

So `CalibrationState.CALIBRATED` is **unreachable for the target speaker**
by construction, and `require_calibrated()` will refuse. That is not a
gap to be filled later by better code; it is a property of the data.

## What can legitimately be calibrated

* **Operator rejection** — the operator is alive and can record freely, so
  his samples split cleanly into enrollment and held-out sets.
* **Channel sensitivity** — score drop from wideband/narrowband mismatch,
  measurable from one speaker's own recordings.
* **Score distributions** and **deterministic test thresholds** — from
  synthetic fixtures, valid for verifying software behaviour only.

Each calibration record names its `evidence` so a reader can tell which
of these it rests on.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

CALIBRATION_VERSION = "1.0.0"


class CalibrationState(StrEnum):
    #: No evidence. Thresholds are defaults chosen for safety, not measurement.
    UNCALIBRATED = "UNCALIBRATED"
    #: Evidence exists but does not support a statistical claim — synthetic
    #: fixtures, small samples, or reviewer feedback rather than held-out labels.
    PROVISIONAL = "PROVISIONAL"
    #: Validated against labelled held-out data. Requires real evidence.
    CALIBRATED = "CALIBRATED"


class CalibrationEvidence(StrEnum):
    NONE = "none"
    SYNTHETIC_FIXTURES = "synthetic_fixtures"
    OPERATOR_HELD_OUT = "operator_held_out"
    CHANNEL_MISMATCH_STUDY = "channel_mismatch_study"
    REVIEWER_FEEDBACK = "reviewer_feedback"
    PUBLIC_CORPUS = "public_corpus"
    TARGET_HELD_OUT = "target_held_out"


#: Only this evidence can support CALIBRATED. It is unobtainable for the
#: target speaker — see the module docstring.
EVIDENCE_SUPPORTING_CALIBRATED: frozenset[CalibrationEvidence] = frozenset(
    {CalibrationEvidence.OPERATOR_HELD_OUT, CalibrationEvidence.TARGET_HELD_OUT}
)


class CalibrationError(RuntimeError):
    """Raised when a calibration claim is not supported by its evidence."""


@dataclass(frozen=True)
class ThresholdConfig:
    """Similarity thresholds. Deliberately asymmetric.

    Rejecting one of the target's segments costs a little data. Admitting
    one of the operator's corrupts the model in a way that is hard to
    detect and expensive to undo. The thresholds encode that asymmetry:
    rejection triggers readily, acceptance does not.
    """

    #: At or above this similarity to the operator profile -> reject.
    #: Low on purpose: catching his voice matters more than keeping hers.
    operator_rejection_threshold: float = 0.55
    #: At or above this similarity to the target profile -> acceptance candidate.
    target_acceptance_threshold: float = 0.85
    #: Between review and acceptance -> manual review.
    target_review_threshold: float = 0.65
    #: Minimum audio needed for a score to be meaningful at all.
    min_segment_seconds_for_scoring: float = 1.0
    #: Score drop tolerated when enrollment and candidate channels differ.
    channel_mismatch_allowance: float = 0.05

    def __post_init__(self) -> None:
        if not self.target_review_threshold <= self.target_acceptance_threshold:
            raise CalibrationError(
                f"review threshold {self.target_review_threshold} must not exceed "
                f"acceptance threshold {self.target_acceptance_threshold}"
            )
        for name, value in (
            ("operator_rejection_threshold", self.operator_rejection_threshold),
            ("target_acceptance_threshold", self.target_acceptance_threshold),
            ("target_review_threshold", self.target_review_threshold),
        ):
            if not 0.0 <= value <= 1.0:
                raise CalibrationError(f"{name} must be within 0..1, got {value}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def config_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass
class ScoreDistribution:
    """Summary statistics for a set of similarity scores."""

    label: str
    count: int
    mean: float
    stdev: float
    minimum: float
    maximum: float
    percentiles: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_scores(cls, label: str, scores: list[float]) -> ScoreDistribution:
        if not scores:
            raise CalibrationError(f"cannot summarise an empty score set for {label!r}")
        ordered = sorted(scores)

        def percentile(p: float) -> float:
            index = min(int(len(ordered) * p), len(ordered) - 1)
            return ordered[index]

        return cls(
            label=label,
            count=len(scores),
            mean=statistics.fmean(scores),
            stdev=statistics.pstdev(scores) if len(scores) > 1 else 0.0,
            minimum=ordered[0],
            maximum=ordered[-1],
            percentiles={"p05": percentile(0.05), "p50": percentile(0.50), "p95": percentile(0.95)},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "count": self.count,
            "mean": round(self.mean, 6),
            "stdev": round(self.stdev, 6),
            "minimum": round(self.minimum, 6),
            "maximum": round(self.maximum, 6),
            "percentiles": {k: round(v, 6) for k, v in self.percentiles.items()},
        }


@dataclass
class CalibrationRecord:
    """One calibration attempt, with its state and the evidence behind it."""

    calibration_id: str
    state: CalibrationState
    evidence: CalibrationEvidence
    thresholds: ThresholdConfig
    provider_name: str
    provider_version: str
    provider_is_synthetic: bool
    #: Which speaker role this calibration applies to, if any.
    applies_to_role: str | None = None
    genuine_distribution: dict[str, Any] | None = None
    impostor_distribution: dict[str, Any] | None = None
    #: Plain-language statement of what this calibration does NOT establish.
    limitations: list[str] = field(default_factory=list)
    reviewer_feedback_count: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    calibration_version: str = CALIBRATION_VERSION
    superseded_by: str | None = None

    def __post_init__(self) -> None:
        if self.state is CalibrationState.CALIBRATED and self.evidence not in EVIDENCE_SUPPORTING_CALIBRATED:
            raise CalibrationError(
                f"CALIBRATED requires held-out labelled evidence, but the evidence is "
                f"{self.evidence.value!r}. Use PROVISIONAL instead — representing an "
                "unvalidated threshold as calibrated is exactly the claim this project "
                "must not make."
            )
        if self.state is CalibrationState.CALIBRATED and self.provider_is_synthetic:
            raise CalibrationError(
                "A synthetic embedding provider cannot produce a CALIBRATED result: "
                "it is arithmetic over waveform shape, not a speaker model."
            )

    @property
    def is_statistically_validated(self) -> bool:
        return self.state is CalibrationState.CALIBRATED

    def config_hash(self) -> str:
        return self.thresholds.config_hash()

    def to_dict(self) -> dict[str, Any]:
        return {
            "calibration_id": self.calibration_id,
            "state": self.state.value,
            "evidence": self.evidence.value,
            "thresholds": self.thresholds.to_dict(),
            "thresholds_hash": self.config_hash(),
            "provider_name": self.provider_name,
            "provider_version": self.provider_version,
            "provider_is_synthetic": self.provider_is_synthetic,
            "applies_to_role": self.applies_to_role,
            "genuine_distribution": self.genuine_distribution,
            "impostor_distribution": self.impostor_distribution,
            "limitations": list(self.limitations),
            "reviewer_feedback_count": self.reviewer_feedback_count,
            "is_statistically_validated": self.is_statistically_validated,
            "created_at": self.created_at,
            "calibration_version": self.calibration_version,
            "superseded_by": self.superseded_by,
        }


def uncalibrated(provider_name: str, provider_version: str, *, is_synthetic: bool) -> CalibrationRecord:
    """The honest default: safe thresholds, no evidence, and it says so."""
    return CalibrationRecord(
        calibration_id="cal-uncalibrated",
        state=CalibrationState.UNCALIBRATED,
        evidence=CalibrationEvidence.NONE,
        thresholds=ThresholdConfig(),
        provider_name=provider_name,
        provider_version=provider_version,
        provider_is_synthetic=is_synthetic,
        limitations=[
            "No calibration evidence exists. Thresholds are conservative defaults "
            "chosen for safety, not values derived from measurement.",
            "No statistical claim of any kind is supported by this record.",
        ],
    )


def provisional_from_synthetic(
    calibration_id: str,
    genuine_scores: list[float],
    impostor_scores: list[float],
    provider_name: str,
    provider_version: str,
    *,
    thresholds: ThresholdConfig | None = None,
) -> CalibrationRecord:
    """Calibrate against synthetic fixtures — PROVISIONAL, never CALIBRATED.

    Legitimate for verifying that threshold *logic* behaves correctly. It
    says nothing about how the system separates two real human voices,
    and the record states that explicitly.
    """
    return CalibrationRecord(
        calibration_id=calibration_id,
        state=CalibrationState.PROVISIONAL,
        evidence=CalibrationEvidence.SYNTHETIC_FIXTURES,
        thresholds=thresholds or ThresholdConfig(),
        provider_name=provider_name,
        provider_version=provider_version,
        provider_is_synthetic=True,
        genuine_distribution=ScoreDistribution.from_scores("genuine", genuine_scores).to_dict(),
        impostor_distribution=ScoreDistribution.from_scores("impostor", impostor_scores).to_dict(),
        limitations=[
            "Derived from synthetic fixtures. Validates software behaviour only.",
            "Says nothing about separating real human voices.",
            "Must not be used to justify any real acceptance threshold.",
        ],
    )


def provisional_from_reviewer_feedback(
    calibration_id: str,
    base: CalibrationRecord,
    *,
    feedback_count: int,
    agreement_rate: float,
    thresholds: ThresholdConfig | None = None,
) -> CalibrationRecord:
    """Adjust thresholds from reviewer agreement — still PROVISIONAL.

    Reviewer agreement is the only feedback signal available without
    labelled data. It is genuine evidence, but it is not a held-out set:
    reviewers can be systematically wrong, and their decisions were made
    while seeing the machine's recommendation. Hence PROVISIONAL, always.
    """
    if not 0.0 <= agreement_rate <= 1.0:
        raise CalibrationError(f"agreement_rate must be within 0..1, got {agreement_rate}")
    return CalibrationRecord(
        calibration_id=calibration_id,
        state=CalibrationState.PROVISIONAL,
        evidence=CalibrationEvidence.REVIEWER_FEEDBACK,
        thresholds=thresholds or base.thresholds,
        provider_name=base.provider_name,
        provider_version=base.provider_version,
        provider_is_synthetic=base.provider_is_synthetic,
        applies_to_role=base.applies_to_role,
        reviewer_feedback_count=feedback_count,
        limitations=[
            f"Based on {feedback_count} reviewer decisions with {agreement_rate:.1%} agreement.",
            "Reviewer agreement is not a labelled held-out set: reviewers saw the "
            "machine recommendation before deciding, so their agreement is correlated "
            "with it and cannot be treated as independent ground truth.",
            "Does not support a statistical error-rate claim.",
        ],
    )


def require_calibrated(record: CalibrationRecord, *, operation: str) -> None:
    """Refuse an operation that needs a genuinely calibrated threshold."""
    if record.state is not CalibrationState.CALIBRATED:
        raise CalibrationError(
            f"{operation} requires CALIBRATED thresholds, but the calibration state is "
            f"{record.state.value} (evidence: {record.evidence.value}). For the target "
            "speaker this state is unreachable: calibration needs labelled held-out data, "
            "and every recording of her is inside the dataset being labelled."
        )
