"""Verification engine: compare a candidate against speaker profiles.

Rejection-first, by design. The engine scores a candidate against the
operator profile *before* the target profile, because the two errors are
not equally bad: rejecting one of her segments costs a little data, while
admitting one of his corrupts the model in a way that is hard to detect
after training and expensive to undo.

Eligibility itself is delegated to `security.speaker_policy`, the Phase 0
module that already encodes the rules and is exhaustively tested. This
engine's job is to populate its inputs honestly — not to reimplement the
decision, which would create two policies free to drift apart.

## Synthetic provenance

A verification produced with a synthetic embedding provider is stamped
`provider_is_synthetic=True` and its decision is reported as
`SYNTHETIC_ONLY`, never as a real identity conclusion. The verified
dataset refuses such records unless the dataset is itself declared
synthetic. Nothing built during this software-only phase can be mistaken
later for a real determination.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from aarya_voice_lab import __version__
from aarya_voice_lab.identity.calibration import (
    CalibrationRecord,
    CalibrationState,
    ThresholdConfig,
)
from aarya_voice_lab.identity.embeddings import (
    EmbeddingStore,
    EmbeddingVector,
    SyntheticProvenanceError,
    cosine_similarity,
)
from aarya_voice_lab.identity.profile import SpeakerProfile, SpeakerRole
from aarya_voice_lab.security.speaker_policy import (
    EligibilityDecision,
    OverlapStatus,
    SpeakerVerificationInput,
    decide_eligibility,
)
from aarya_voice_lab.security.speaker_policy import SpeakerRole as PolicySpeakerRole

VERIFICATION_ENGINE_VERSION = "1.0.0"


class VerificationDecision(StrEnum):
    """Outcome of verifying one candidate.

    `SYNTHETIC_ONLY` exists so a development run produces a real record
    with a real decision path, while remaining structurally incapable of
    being read as an identity conclusion.
    """

    ELIGIBLE = "eligible"
    REJECTED_OPERATOR = "rejected_operator"
    REJECTED_LOW_SIMILARITY = "rejected_low_similarity"
    REJECTED_OVERLAP = "rejected_overlap"
    MANUAL_REVIEW = "manual_review"
    INSUFFICIENT_AUDIO = "insufficient_audio"
    SYNTHETIC_ONLY = "synthetic_only"


class VerificationError(RuntimeError):
    """Raised when verification cannot proceed."""


@dataclass
class SystemScore:
    """One system's opinion about one candidate."""

    system_name: str
    model_name: str
    model_version: str
    profile_version_key: str
    similarity: float
    role_hypothesis: SpeakerRole
    #: Present only when calibration supports it; None otherwise. Never faked.
    calibrated_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "system_name": self.system_name,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "profile_version_key": self.profile_version_key,
            "similarity": round(self.similarity, 6),
            "role_hypothesis": self.role_hypothesis.value,
            "calibrated_score": None if self.calibrated_score is None else round(self.calibrated_score, 6),
        }


@dataclass
class ReviewerFeedback:
    """A human's response to a verification.

    Deliberately never auto-converted into an identity claim: it is
    recorded next to the machine result, and only the review stage may
    promote a segment. `agreed_with_machine` is derived for disagreement
    tracking — the one feedback signal available without labelled data.
    """

    reviewer: str
    outcome: str  # accepted | rejected | uncertain | needs_review
    reviewed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    comment: str | None = None
    listened: bool = False
    listen_duration_seconds: float | None = None
    machine_decision: str | None = None

    VALID_OUTCOMES = ("accepted", "rejected", "uncertain", "needs_review")

    def __post_init__(self) -> None:
        if self.outcome not in self.VALID_OUTCOMES:
            raise VerificationError(
                f"Invalid reviewer outcome {self.outcome!r}; expected one of {self.VALID_OUTCOMES}"
            )

    @property
    def agreed_with_machine(self) -> bool | None:
        if self.machine_decision is None:
            return None
        machine_accepted = self.machine_decision == VerificationDecision.ELIGIBLE.value
        if self.outcome == "accepted":
            return machine_accepted
        if self.outcome == "rejected":
            return not machine_accepted
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reviewer": self.reviewer,
            "outcome": self.outcome,
            "reviewed_at": self.reviewed_at,
            "comment": self.comment,
            "listened": self.listened,
            "listen_duration_seconds": self.listen_duration_seconds,
            "machine_decision": self.machine_decision,
            "agreed_with_machine": self.agreed_with_machine,
        }


@dataclass
class VerificationResult:
    """The full record of verifying one candidate segment."""

    verification_id: str
    segment_id: str
    decision: VerificationDecision
    reason: str
    primary: SystemScore | None = None
    secondary: SystemScore | None = None
    operator_score: SystemScore | None = None
    confidence: str = "low"
    calibration_state: CalibrationState = CalibrationState.UNCALIBRATED
    calibration_id: str | None = None
    thresholds_hash: str = ""
    provider_is_synthetic: bool = True
    #: Phase 2 verdict, carried forward and never recomputed here.
    overlap_status_inherited: str | None = None
    source_file_id: str | None = None
    source_sha256: str | None = None
    candidate_manifest_sha256: str | None = None
    reviewer_feedback: list[ReviewerFeedback] = field(default_factory=list)
    engine_version: str = VERIFICATION_ENGINE_VERSION
    processing_version: str = __version__
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def is_real_identity_claim(self) -> bool:
        """Whether this result may be read as a real identity conclusion."""
        return not self.provider_is_synthetic and self.decision is not VerificationDecision.SYNTHETIC_ONLY

    def add_feedback(self, feedback: ReviewerFeedback) -> None:
        feedback.machine_decision = self.decision.value
        self.reviewer_feedback.append(feedback)

    def fingerprint(self) -> str:
        payload = json.dumps(
            {
                "segment_id": self.segment_id,
                "primary_profile": self.primary.profile_version_key if self.primary else None,
                "operator_profile": self.operator_score.profile_version_key if self.operator_score else None,
                "thresholds_hash": self.thresholds_hash,
                "engine_version": self.engine_version,
                "provider": self.primary.model_name if self.primary else None,
                "provider_version": self.primary.model_version if self.primary else None,
            },
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "verification_id": self.verification_id,
            "segment_id": self.segment_id,
            "decision": self.decision.value,
            "reason": self.reason,
            "primary": self.primary.to_dict() if self.primary else None,
            "secondary": self.secondary.to_dict() if self.secondary else None,
            "operator_score": self.operator_score.to_dict() if self.operator_score else None,
            "confidence": self.confidence,
            "calibration_state": self.calibration_state.value,
            "calibration_id": self.calibration_id,
            "thresholds_hash": self.thresholds_hash,
            "provider_is_synthetic": self.provider_is_synthetic,
            "is_real_identity_claim": self.is_real_identity_claim,
            "overlap_status_inherited": self.overlap_status_inherited,
            "source_file_id": self.source_file_id,
            "source_sha256": self.source_sha256,
            "candidate_manifest_sha256": self.candidate_manifest_sha256,
            "reviewer_feedback": [f.to_dict() for f in self.reviewer_feedback],
            "engine_version": self.engine_version,
            "processing_version": self.processing_version,
            "fingerprint": self.fingerprint(),
            "created_at": self.created_at,
        }


def _to_policy_role(role: SpeakerRole) -> PolicySpeakerRole:
    """Map a profile role onto the Phase 0 policy vocabulary.

    A synthetic speaker maps to UNKNOWN rather than to the target: the
    policy must never see a synthetic profile as a real target speaker.
    """
    return {
        SpeakerRole.TARGET_SPEAKER: PolicySpeakerRole.TARGET_FEMALE_SPEAKER,
        SpeakerRole.OPERATOR: PolicySpeakerRole.OPERATOR_VOICE,
    }.get(role, PolicySpeakerRole.UNKNOWN)


def _to_policy_overlap(status: str | None) -> OverlapStatus:
    return {
        "NO_OVERLAP_DETECTED": OverlapStatus.NONE,
        "OVERLAP_DETECTED": OverlapStatus.OVERLAP,
        "POSSIBLE_OVERLAP": OverlapStatus.OVERLAP,
    }.get(status or "", OverlapStatus.UNKNOWN)


class VerificationEngine:
    """Scores candidates against profiles and decides eligibility."""

    version = VERIFICATION_ENGINE_VERSION

    def __init__(
        self,
        *,
        embedding_store: EmbeddingStore,
        calibration: CalibrationRecord,
        target_profile: SpeakerProfile | None = None,
        operator_profile: SpeakerProfile | None = None,
        secondary_embedding_store: EmbeddingStore | None = None,
    ):
        self.embedding_store = embedding_store
        self.secondary_embedding_store = secondary_embedding_store
        self.calibration = calibration
        self.target_profile = target_profile
        self.operator_profile = operator_profile

    @property
    def thresholds(self) -> ThresholdConfig:
        return self.calibration.thresholds

    def _score_against(self, profile: SpeakerProfile, candidate: EmbeddingVector, system: str) -> SystemScore:
        profile.require_usable()
        if profile.embedding_id is None:
            raise VerificationError(f"profile {profile.profile_version_key} has no stored embedding")
        reference = self.embedding_store.load(profile.embedding_id)
        similarity = cosine_similarity(reference, candidate)
        return SystemScore(
            system_name=system,
            model_name=profile.provider_name or "unknown",
            model_version=profile.provider_version or "unknown",
            profile_version_key=profile.profile_version_key,
            similarity=similarity,
            role_hypothesis=profile.role,
            # Only populated when calibration genuinely supports it.
            calibrated_score=(
                similarity if self.calibration.state is CalibrationState.CALIBRATED else None
            ),
        )

    def verify(
        self,
        *,
        verification_id: str,
        segment_id: str,
        candidate: EmbeddingVector,
        duration_seconds: float,
        overlap_status: str | None = None,
        quality_acceptable: bool = True,
        source_file_id: str | None = None,
        source_sha256: str | None = None,
        candidate_manifest_sha256: str | None = None,
        secondary_candidate: EmbeddingVector | None = None,
    ) -> VerificationResult:
        """Verify one candidate segment. Rejection is evaluated first."""
        provider_is_synthetic = candidate.is_synthetic

        result = VerificationResult(
            verification_id=verification_id,
            segment_id=segment_id,
            decision=VerificationDecision.MANUAL_REVIEW,
            reason="not yet evaluated",
            calibration_state=self.calibration.state,
            calibration_id=self.calibration.calibration_id,
            thresholds_hash=self.calibration.config_hash(),
            provider_is_synthetic=provider_is_synthetic,
            overlap_status_inherited=overlap_status,
            source_file_id=source_file_id,
            source_sha256=source_sha256,
            candidate_manifest_sha256=candidate_manifest_sha256,
        )

        if duration_seconds < self.thresholds.min_segment_seconds_for_scoring:
            result.decision = VerificationDecision.INSUFFICIENT_AUDIO
            result.reason = (
                f"segment is {duration_seconds:.2f}s; below the "
                f"{self.thresholds.min_segment_seconds_for_scoring}s minimum for a meaningful score"
            )
            return result

        # --- rejection first -------------------------------------------------
        if self.operator_profile is not None:
            operator_score = self._score_against(self.operator_profile, candidate, "operator_rejection")
            result.operator_score = operator_score
            if operator_score.similarity >= self.thresholds.operator_rejection_threshold:
                result.decision = VerificationDecision.REJECTED_OPERATOR
                result.reason = (
                    f"similarity to the operator profile is {operator_score.similarity:.3f}, "
                    f"at or above the rejection threshold "
                    f"{self.thresholds.operator_rejection_threshold}"
                )
                result.confidence = "high"
                return result

        if self.target_profile is None:
            result.decision = VerificationDecision.MANUAL_REVIEW
            result.reason = "no target profile is enrolled; nothing to accept against"
            return result

        # --- acceptance side --------------------------------------------------
        primary = self._score_against(self.target_profile, candidate, "primary")
        result.primary = primary

        secondary_role = None
        secondary_confidence = None
        if secondary_candidate is not None and self.secondary_embedding_store is not None:
            secondary = self._score_against(self.target_profile, secondary_candidate, "secondary")
            result.secondary = secondary
            secondary_role = _to_policy_role(secondary.role_hypothesis)
            secondary_confidence = secondary.similarity

        policy_input = SpeakerVerificationInput(
            primary_role=_to_policy_role(primary.role_hypothesis),
            primary_confidence=primary.similarity,
            secondary_role=secondary_role,
            secondary_confidence=secondary_confidence,
            overlap_status=_to_policy_overlap(overlap_status),
            audio_quality_acceptable=quality_acceptable,
        )
        policy_decision, policy_reason = decide_eligibility(policy_input)

        if primary.similarity < self.thresholds.target_review_threshold:
            result.decision = VerificationDecision.REJECTED_LOW_SIMILARITY
            result.reason = (
                f"similarity to the target profile is {primary.similarity:.3f}, below the "
                f"review threshold {self.thresholds.target_review_threshold}"
            )
            result.confidence = "low"
        elif policy_decision is EligibilityDecision.REJECT:
            result.decision = (
                VerificationDecision.REJECTED_OVERLAP
                if "overlap" in policy_reason
                else VerificationDecision.REJECTED_LOW_SIMILARITY
            )
            result.reason = policy_reason
        elif policy_decision is EligibilityDecision.MANUAL_REVIEW:
            result.decision = VerificationDecision.MANUAL_REVIEW
            result.reason = policy_reason
            result.confidence = "medium"
        elif primary.similarity < self.thresholds.target_acceptance_threshold:
            result.decision = VerificationDecision.MANUAL_REVIEW
            result.reason = (
                f"similarity {primary.similarity:.3f} is between the review and acceptance "
                f"thresholds; a human must decide"
            )
            result.confidence = "medium"
        else:
            result.decision = VerificationDecision.ELIGIBLE
            result.reason = policy_reason
            result.confidence = "high"

        # A synthetic provider can never yield a real identity conclusion.
        if provider_is_synthetic and result.decision is VerificationDecision.ELIGIBLE:
            result.decision = VerificationDecision.SYNTHETIC_ONLY
            result.reason = (
                "would be eligible, but the embedding provider is synthetic: this is a "
                "software-behaviour result, not an identity determination"
            )

        return result


def assert_real_identity_claim(result: VerificationResult, *, operation: str) -> None:
    """Refuse to treat a synthetic-derived result as a real conclusion."""
    if not result.is_real_identity_claim:
        raise SyntheticProvenanceError(
            f"{operation} requires a real identity determination, but verification "
            f"{result.verification_id} was produced with a synthetic embedding provider "
            f"(decision: {result.decision.value}). Synthetic results validate software "
            "behaviour only and must never enter a real dataset."
        )
