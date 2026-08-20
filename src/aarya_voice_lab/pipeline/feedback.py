"""Feedback architecture — VL-D3 §26, extended by VL-D4 §28.

Free-text human feedback attached to a recording, segment, candidate,
processing result, or (later) a voice preview: "too noisy", "segment
boundary incorrect", "candidate unusable", "over-processed". Stored for
a human or a future AI Calibration Engine to read; **never** converted
into a model-training label by anything in this module or elsewhere in
the project today.

Persistence reuses `JsonLinesRegistry`, same as
`pipeline.candidate_review` and the experiment/model registries — one
small, well-tested storage mechanism, not a new one per feature.

VL-D4 adds `PROCESSING_FEEDBACK` rather than a second feedback
mechanism — the existing `attributes` field (already a free-form,
string-valued dict per `schemas/feedback.schema.json`) carries the
specific category via `ProcessingFeedbackCategory`, validated by
`record_processing_feedback()` below, exactly the same "reuse existing
backend contracts, do not duplicate" rule VL-D3 itself was built under.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from aarya_voice_lab import __version__
from aarya_voice_lab.registry.json_registry import JsonLinesRegistry
from aarya_voice_lab.schemas.base import SchemaName


class FeedbackType(StrEnum):
    QUALITY_FEEDBACK = "QUALITY_FEEDBACK"
    SEGMENT_FEEDBACK = "SEGMENT_FEEDBACK"
    CANDIDATE_FEEDBACK = "CANDIDATE_FEEDBACK"
    PLAYBACK_FEEDBACK = "PLAYBACK_FEEDBACK"
    PROCESSING_FEEDBACK = "PROCESSING_FEEDBACK"


class ProcessingFeedbackCategory(StrEnum):
    """Closed vocabulary for VL-D4 §28's processing feedback — stored in
    a `PROCESSING_FEEDBACK` record's `attributes["category"]`, validated
    here rather than left as an arbitrary string."""

    TOO_AGGRESSIVE = "TOO_AGGRESSIVE"
    TOO_NOISY = "TOO_NOISY"
    TOO_QUIET = "TOO_QUIET"
    OVER_PROCESSED = "OVER_PROCESSED"
    UNDER_PROCESSED = "UNDER_PROCESSED"
    BOUNDARY_INCORRECT = "BOUNDARY_INCORRECT"
    QUALITY_DEGRADED = "QUALITY_DEGRADED"
    GOOD_RESULT = "GOOD_RESULT"
    OTHER = "OTHER"


@dataclass(frozen=True)
class FeedbackRecord:
    feedback_id: str
    feedback_type: FeedbackType
    target_id: str
    reviewer: str
    comment: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "feedback_id": self.feedback_id,
            "feedback_type": self.feedback_type.value,
            "target_id": self.target_id,
            "reviewer": self.reviewer,
            "comment": self.comment,
            "attributes": dict(self.attributes),
            "created_at": self.created_at or datetime.now(UTC).isoformat(),
            "processing_version": __version__,
        }


class FeedbackLog(JsonLinesRegistry):
    def __init__(self, path: Path):
        super().__init__(path=path, schema_name=SchemaName.FEEDBACK, id_field="feedback_id")


def record_feedback(log: FeedbackLog, record: FeedbackRecord) -> dict[str, Any]:
    payload = record.to_dict()
    log.add(payload)
    return payload


def record_processing_feedback(
    log: FeedbackLog,
    *,
    target_id: str,
    reviewer: str,
    category: ProcessingFeedbackCategory,
    comment: str | None = None,
    feedback_id: str | None = None,
) -> dict[str, Any]:
    """Record VL-D4 §28 processing feedback with a validated category —
    never converted into a training label here or anywhere downstream."""
    if not isinstance(category, ProcessingFeedbackCategory):
        raise ValueError(f"unknown ProcessingFeedbackCategory: {category!r}")
    record = FeedbackRecord(
        feedback_id=feedback_id or f"feedback-{len(log.list()) + 1:05d}",
        feedback_type=FeedbackType.PROCESSING_FEEDBACK,
        target_id=target_id,
        reviewer=reviewer,
        comment=comment,
        attributes={"category": category.value},
    )
    return record_feedback(log, record)


def feedback_for(log: FeedbackLog, target_id: str) -> list[dict[str, Any]]:
    return [r for r in log.list() if r["target_id"] == target_id]


def counts_by_type(log: FeedbackLog) -> dict[str, int]:
    counts = dict.fromkeys(FeedbackType, 0)
    for record in log.list():
        counts[FeedbackType(record["feedback_type"])] += 1
    return {feedback_type.value: count for feedback_type, count in counts.items()}
