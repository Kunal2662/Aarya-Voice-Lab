"""Technical candidate review — VL-D3 §12–§16, §22.

A human decision about whether a Phase 2 candidate segment is
*technically* usable: quality, duration, segmentation, overlap. This is
not, and must never become, a decision about who is speaking.

`schemas/identity_review.schema.json` (Phase 3) already established the
separation pattern this module reuses: `review_type` is pinned to a
constant (`"technical"` here, `"identity"` there) so the two record kinds
can never be confused by a downstream reader, and a correction
`supersedes` a prior record rather than editing it, so review history is
never silently overwritten. `reason_code` is a closed technical-only
vocabulary — there is no value in it that could express a speaker
judgement, by construction rather than by a runtime check.

Persistence reuses `registry.json_registry.JsonLinesRegistry` (already
used for the experiment and model registries) rather than inventing a
second storage mechanism. Every decision is a new, immutable record;
`current_decision()` reads the latest one for a segment, `history()`
returns every one, in the order they were written — never by comparing
timestamp values, which this project never trusts for logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from aarya_voice_lab import __version__
from aarya_voice_lab.registry.json_registry import JsonLinesRegistry
from aarya_voice_lab.schemas.base import SchemaName

CANDIDATE_REVIEW_STAGE_VERSION = "1.0.0"


class CandidateReviewDecision(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class CandidateReviewReason(StrEnum):
    """Closed and technical-only. Reviewers are never asked to choose a
    reason that implies a speaker judgement — the vocabulary doesn't
    have one."""

    QUALITY_ISSUE = "quality_issue"
    SEGMENTATION_ISSUE = "segmentation_issue"
    OVERLAP_ISSUE = "overlap_issue"
    DURATION_ISSUE = "duration_issue"
    TECHNICAL_USABILITY = "technical_usability"
    OTHER = "other"


@dataclass(frozen=True)
class CandidateReviewRecord:
    review_id: str
    segment_id: str
    source_file_id: str
    batch_id: str
    reviewer: str
    decision: CandidateReviewDecision
    reason_code: CandidateReviewReason
    source_sha256: str
    config_hash: str
    notes: str | None = None
    supersedes: str | None = None
    reviewed_at: str | None = None
    tool_version: str = __version__
    stage_version: str = CANDIDATE_REVIEW_STAGE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "review_id": self.review_id,
            "segment_id": self.segment_id,
            "source_file_id": self.source_file_id,
            "batch_id": self.batch_id,
            "reviewer": self.reviewer,
            "decision": self.decision.value,
            "reason_code": self.reason_code.value,
            "notes": self.notes,
            "reviewed_at": self.reviewed_at or datetime.now(UTC).isoformat(),
            "supersedes": self.supersedes,
            "review_type": "technical",
            "stage": "candidate_review",
            "processing_version": __version__,
            "source_sha256": self.source_sha256,
            "config_hash": self.config_hash,
            "tool_version": self.tool_version,
            "stage_version": self.stage_version,
        }


class CandidateReviewLog(JsonLinesRegistry):
    def __init__(self, path: Path):
        super().__init__(path=path, schema_name=SchemaName.CANDIDATE_REVIEW, id_field="review_id")


def record_review_decision(log: CandidateReviewLog, record: CandidateReviewRecord) -> dict[str, Any]:
    payload = record.to_dict()
    log.add(payload)
    return payload


def history(log: CandidateReviewLog, segment_id: str) -> list[dict[str, Any]]:
    """Every decision ever recorded for one segment, oldest first. Never
    empty-vs-overwritten: a superseded record stays in this list."""
    return [r for r in log.list() if r["segment_id"] == segment_id]


def current_decision(log: CandidateReviewLog, segment_id: str) -> dict[str, Any] | None:
    """The most recently recorded decision for a segment, or None if it
    has never been reviewed."""
    records = history(log, segment_id)
    return records[-1] if records else None


def review_disagreement_count(log: CandidateReviewLog) -> int:
    """How many segments have more than one distinct decision recorded.

    A pure count, used only as a future AI Calibration Engine input
    (VL-D3 §27) — never turned into a score by this module.
    """
    by_segment: dict[str, set[str]] = {}
    for record in log.list():
        by_segment.setdefault(record["segment_id"], set()).add(record["decision"])
    return sum(1 for decisions in by_segment.values() if len(decisions) > 1)
