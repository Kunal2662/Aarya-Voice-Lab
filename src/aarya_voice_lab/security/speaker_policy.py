"""Conservative speaker-safety decision policy for the Private Voice dataset.

This module implements ONLY the decision logic described in
docs/SECURITY.md sections "Speaker Safety" and "Two-System Verification".
It takes structured verification inputs (produced by future diarization/
verification stages) and returns a classification. It does not perform
diarization, transcription, or any audio analysis itself, and is not
wired to any real recording in Phase 0.

Design intent (do not weaken without updating docs/SECURITY.md):
  - The target female speaker is eligible only when independently
    confirmed by two systems with sufficient confidence.
  - Anything identified as the operator's own voice is rejected.
  - Overlapping speech is rejected by default.
  - Ambiguous or unknown cases fall to manual review rather than being
    auto-accepted. When in doubt, exclude.
  - Speaker labels (e.g. "spk_0", "Speaker A") are recording-local and
    must never be assumed consistent across different source files.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SpeakerRole(StrEnum):
    TARGET_FEMALE_SPEAKER = "target_female_speaker"
    OPERATOR_VOICE = "operator_voice"
    UNKNOWN = "unknown"


class OverlapStatus(StrEnum):
    NONE = "none"
    OVERLAP = "overlap"
    UNKNOWN = "unknown"


class VerificationAgreement(StrEnum):
    """How the primary and secondary verification systems relate."""

    BOTH_AGREE_TARGET = "both_agree_target"
    BOTH_AGREE_OPERATOR = "both_agree_operator"
    CONFLICTING = "conflicting"
    SECONDARY_NOT_RUN = "secondary_not_run"
    NEITHER_CONFIDENT = "neither_confident"


class EligibilityDecision(StrEnum):
    ELIGIBLE = "eligible"
    REJECT = "reject"
    MANUAL_REVIEW = "manual_review"


class ConfidenceLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class SpeakerVerificationInput:
    """Structured, already-computed verification signals for one segment.

    Populated by future pipeline stages (diarization + independent
    verification). Never constructed from raw audio in this module.
    """

    primary_role: SpeakerRole
    primary_confidence: float  # 0.0-1.0, from the primary system (e.g. NeMo/SortFormer)
    secondary_role: SpeakerRole | None  # None if secondary verification was not run
    secondary_confidence: float | None
    overlap_status: OverlapStatus
    audio_quality_acceptable: bool


def _agreement(inp: SpeakerVerificationInput) -> VerificationAgreement:
    if inp.secondary_role is None:
        return VerificationAgreement.SECONDARY_NOT_RUN
    target = SpeakerRole.TARGET_FEMALE_SPEAKER
    if inp.primary_role == target and inp.secondary_role == target:
        return VerificationAgreement.BOTH_AGREE_TARGET
    if inp.primary_role == SpeakerRole.OPERATOR_VOICE and inp.secondary_role == SpeakerRole.OPERATOR_VOICE:
        return VerificationAgreement.BOTH_AGREE_OPERATOR
    if inp.primary_role != inp.secondary_role:
        return VerificationAgreement.CONFLICTING
    return VerificationAgreement.NEITHER_CONFIDENT


# Minimum per-system confidence to treat a "target speaker" call as trustworthy.
HIGH_CONFIDENCE_THRESHOLD = 0.90
MEDIUM_CONFIDENCE_THRESHOLD = 0.70


def classify_confidence(inp: SpeakerVerificationInput) -> ConfidenceLevel:
    confidences = [inp.primary_confidence]
    if inp.secondary_confidence is not None:
        confidences.append(inp.secondary_confidence)
    lowest = min(confidences)
    if lowest >= HIGH_CONFIDENCE_THRESHOLD:
        return ConfidenceLevel.HIGH
    if lowest >= MEDIUM_CONFIDENCE_THRESHOLD:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def decide_eligibility(inp: SpeakerVerificationInput) -> tuple[EligibilityDecision, str]:
    """Return (decision, reason) for whether a segment may enter the dataset.

    This is intentionally conservative: any doubt routes to REJECT or
    MANUAL_REVIEW, never straight to ELIGIBLE.
    """
    # Overlap is rejected by default regardless of speaker identity.
    if inp.overlap_status == OverlapStatus.OVERLAP:
        return EligibilityDecision.REJECT, "overlapping speech detected"
    if inp.overlap_status == OverlapStatus.UNKNOWN:
        return EligibilityDecision.MANUAL_REVIEW, "overlap status could not be determined"

    # The operator's own voice is never eligible, regardless of confidence.
    if inp.primary_role == SpeakerRole.OPERATOR_VOICE:
        return EligibilityDecision.REJECT, "primary system identified operator voice"

    if inp.primary_role == SpeakerRole.UNKNOWN:
        return EligibilityDecision.MANUAL_REVIEW, "primary system could not identify speaker"

    # From here, primary_role == TARGET_FEMALE_SPEAKER.
    agreement = _agreement(inp)

    if agreement == VerificationAgreement.BOTH_AGREE_OPERATOR:
        return EligibilityDecision.REJECT, "independent verification identified operator voice"

    if agreement == VerificationAgreement.CONFLICTING:
        return EligibilityDecision.MANUAL_REVIEW, "primary and secondary verification disagree"

    if agreement == VerificationAgreement.SECONDARY_NOT_RUN:
        return EligibilityDecision.MANUAL_REVIEW, "independent verification not yet run"

    if agreement == VerificationAgreement.NEITHER_CONFIDENT:
        return EligibilityDecision.MANUAL_REVIEW, "verification systems did not converge on a role"

    # agreement == BOTH_AGREE_TARGET
    if not inp.audio_quality_acceptable:
        return EligibilityDecision.MANUAL_REVIEW, "both systems agree on target speaker but audio quality is marginal"

    confidence = classify_confidence(inp)
    if confidence == ConfidenceLevel.HIGH:
        return EligibilityDecision.ELIGIBLE, "both systems agree on target speaker with high confidence"
    if confidence == ConfidenceLevel.MEDIUM:
        return EligibilityDecision.MANUAL_REVIEW, "both systems agree on target speaker but confidence is only medium"
    return EligibilityDecision.REJECT, "both systems agree on target speaker but confidence is low"
