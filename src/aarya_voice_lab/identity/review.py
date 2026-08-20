"""Identity review: the human decision on who is speaking.

Distinct from Phase 2's `candidate_review`, which asks only whether audio
is technically usable. Keeping them separate is a structural guarantee
that a Phase 2 reviewer is never shown an identity question — every
record here carries `review_type: "identity"`, and every Phase 2 review
item carries `asks_about_speaker_identity: false`.

Two rules shape this module:

* **Human approval is mandatory for acceptance.** No confidence level
  bypasses it. `promote_to_dataset` refuses anything unreviewed.
* **Ambiguous is a first-class outcome.** On degraded call audio "I
  cannot tell" is often the correct answer, and forcing a binary choice
  is how errors enter a dataset that cannot be rebuilt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from aarya_voice_lab import __version__
from aarya_voice_lab.core.data_root import DataRoot, assert_source_writable
from aarya_voice_lab.identity.verification import VerificationDecision, VerificationResult

IDENTITY_REVIEW_VERSION = "1.0.0"


class IdentityDecision(StrEnum):
    CONFIRM_TARGET = "confirm_target"
    CONFIRM_OPERATOR = "confirm_operator"
    AMBIGUOUS = "ambiguous"
    UNUSABLE = "unusable"


#: Only this decision can lead to dataset inclusion.
ACCEPTING_DECISIONS: frozenset[IdentityDecision] = frozenset({IdentityDecision.CONFIRM_TARGET})


class ReviewError(RuntimeError):
    """Raised when a review record is invalid or missing."""


@dataclass
class IdentityReviewItem:
    """What a reviewer needs to decide. Contains no embedding vector."""

    segment_id: str
    verification_id: str
    source_file_id: str | None
    start_time: float | None
    end_time: float | None
    duration: float | None
    machine_decision: str
    machine_reason: str
    machine_confidence: str
    primary_similarity: float | None
    operator_similarity: float | None
    overlap_status: str | None
    quality_status: str | None
    calibration_state: str
    provider_is_synthetic: bool
    #: Relative path to previewable audio, when it has been extracted.
    audio_preview_path: str | None = None
    review_type: str = "identity"

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "verification_id": self.verification_id,
            "source_file_id": self.source_file_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "machine_decision": self.machine_decision,
            "machine_reason": self.machine_reason,
            "machine_confidence": self.machine_confidence,
            "primary_similarity": self.primary_similarity,
            "operator_similarity": self.operator_similarity,
            "overlap_status": self.overlap_status,
            "quality_status": self.quality_status,
            "calibration_state": self.calibration_state,
            "provider_is_synthetic": self.provider_is_synthetic,
            "audio_preview_path": self.audio_preview_path,
            "review_type": self.review_type,
        }


@dataclass
class IdentityReviewRecord:
    """One human decision. Immutable — corrections supersede."""

    review_id: str
    segment_id: str
    verification_id: str
    reviewer: str
    decision: IdentityDecision
    listened: bool
    listen_duration_seconds: float | None = None
    machine_recommendation: str | None = None
    notes: str | None = None
    reviewed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    supersedes: str | None = None
    review_type: str = "identity"
    schema_version: str = IDENTITY_REVIEW_VERSION
    processing_version: str = __version__

    @property
    def agreed_with_machine(self) -> bool | None:
        """Whether the human matched the machine, for disagreement tracking."""
        if self.machine_recommendation is None:
            return None
        machine_accepted = self.machine_recommendation == VerificationDecision.ELIGIBLE.value
        if self.decision is IdentityDecision.CONFIRM_TARGET:
            return machine_accepted
        if self.decision in (IdentityDecision.CONFIRM_OPERATOR, IdentityDecision.UNUSABLE):
            return not machine_accepted
        return None

    @property
    def is_valid_review(self) -> bool:
        """A decision made without listening is not a review."""
        return self.listened

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "review_id": self.review_id,
            "segment_id": self.segment_id,
            "verification_id": self.verification_id,
            "reviewer": self.reviewer,
            "decision": self.decision.value,
            "listened": self.listened,
            "listen_duration_seconds": self.listen_duration_seconds,
            "machine_recommendation": self.machine_recommendation,
            "agreed_with_machine": self.agreed_with_machine,
            "notes": self.notes,
            "reviewed_at": self.reviewed_at,
            "supersedes": self.supersedes,
            "review_type": self.review_type,
            "processing_version": self.processing_version,
            "is_valid_review": self.is_valid_review,
        }


class IdentityReviewQueue:
    """Builds review items and records decisions."""

    #: Machine outcomes that still need a human before anything happens.
    REVIEWABLE_DECISIONS: frozenset[str] = frozenset(
        {
            VerificationDecision.ELIGIBLE.value,
            VerificationDecision.MANUAL_REVIEW.value,
            VerificationDecision.SYNTHETIC_ONLY.value,
        }
    )

    def __init__(self, data_root: DataRoot, name: str = "identity_reviews"):
        self.data_root = data_root
        self.directory = data_root.root / "review"
        self.path = self.directory / f"{name}.jsonl"

    def build_items(
        self,
        results: list[VerificationResult],
        candidate_index: dict[str, dict[str, Any]] | None = None,
    ) -> list[IdentityReviewItem]:
        """Turn verification results into review items.

        Note that ELIGIBLE results are queued too: machine eligibility is
        a recommendation, and acceptance still requires a human.
        """
        candidate_index = candidate_index or {}
        items = []
        for result in results:
            if result.decision.value not in self.REVIEWABLE_DECISIONS:
                continue
            candidate = candidate_index.get(result.segment_id, {})
            items.append(
                IdentityReviewItem(
                    segment_id=result.segment_id,
                    verification_id=result.verification_id,
                    source_file_id=result.source_file_id,
                    start_time=candidate.get("start_time"),
                    end_time=candidate.get("end_time"),
                    duration=candidate.get("duration"),
                    machine_decision=result.decision.value,
                    machine_reason=result.reason,
                    machine_confidence=result.confidence,
                    primary_similarity=result.primary.similarity if result.primary else None,
                    operator_similarity=(
                        result.operator_score.similarity if result.operator_score else None
                    ),
                    overlap_status=result.overlap_status_inherited,
                    quality_status=candidate.get("quality_status"),
                    calibration_state=result.calibration_state.value,
                    provider_is_synthetic=result.provider_is_synthetic,
                )
            )
        return items

    def record(self, record: IdentityReviewRecord) -> IdentityReviewRecord:
        if record.review_type != "identity":
            raise ReviewError(
                f"review_type must be 'identity', got {record.review_type!r}. Technical "
                "review belongs to the Phase 2 candidate_review queue."
            )
        assert_source_writable(self.data_root, self.path)
        self.directory.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")
        return record

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def latest_for(self, segment_id: str) -> dict[str, Any] | None:
        """The current decision for a segment; later records supersede earlier."""
        matches = [r for r in self.read_all() if r["segment_id"] == segment_id]
        return matches[-1] if matches else None

    def approved_segment_ids(self) -> list[str]:
        """Segments a human confirmed as the target, having listened."""
        approved = []
        for segment_id in {r["segment_id"] for r in self.read_all()}:
            latest = self.latest_for(segment_id)
            if (
                latest
                and latest["decision"] == IdentityDecision.CONFIRM_TARGET.value
                and latest["listened"]
            ):
                approved.append(segment_id)
        return sorted(approved)

    def disagreement_rate(self) -> dict[str, Any]:
        """How often reviewers overturn the machine, in each direction.

        Without labelled data this is the only early warning that an
        acceptance threshold has drifted too loose.
        """
        records = [r for r in self.read_all() if r.get("agreed_with_machine") is not None]
        if not records:
            return {"sample_size": 0, "agreement_rate": None, "note": "no comparable decisions yet"}
        agreed = sum(1 for r in records if r["agreed_with_machine"])
        overturned_acceptances = sum(
            1
            for r in records
            if not r["agreed_with_machine"]
            and r["machine_recommendation"] == VerificationDecision.ELIGIBLE.value
        )
        return {
            "sample_size": len(records),
            "agreement_rate": round(agreed / len(records), 6),
            "overturned_acceptances": overturned_acceptances,
            "note": (
                "Reviewers saw the machine recommendation before deciding, so agreement "
                "is correlated with it and is not independent ground truth."
            ),
        }


def promote_to_dataset(
    result: VerificationResult,
    review: dict[str, Any] | None,
) -> tuple[bool, str]:
    """Decide whether a segment may enter the verified dataset.

    Every condition must hold. This is the last gate before irreversible
    inclusion, so it fails closed on anything missing.
    """
    if review is None:
        return False, "no human review recorded; acceptance always requires a human"
    if not review.get("listened"):
        return False, "reviewer did not listen; a decision without playback is not a review"
    if review.get("decision") != IdentityDecision.CONFIRM_TARGET.value:
        return False, f"human decision was {review.get('decision')!r}, not confirm_target"
    if result.provider_is_synthetic:
        return False, (
            "verification used a synthetic embedding provider; synthetic results validate "
            "software behaviour and must never enter a real dataset"
        )
    if result.decision in (
        VerificationDecision.REJECTED_OPERATOR,
        VerificationDecision.REJECTED_OVERLAP,
    ):
        return False, f"machine rejected this segment: {result.reason}"
    return True, "human confirmed the target speaker after listening"
