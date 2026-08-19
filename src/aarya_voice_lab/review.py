"""Manual review workflow: data model and interface architecture.

Section 10 of the Phase 0 spec: design (not implement against real data)
a workflow letting a human inspect a candidate segment -- transcript,
timestamps, speaker assignment -- and record approve/reject/ambiguous.

ReviewQueue operates purely on manifest dicts already in memory (loaded
from a dataset manifest) plus a ManualReviewLog for recording decisions.
It never touches audio; a future CLI/UI layer is responsible for actually
letting a human listen to a segment before calling `decide()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aarya_voice_lab.registry.json_registry import JsonLinesRegistry
from aarya_voice_lab.schemas.base import SchemaName
from aarya_voice_lab.schemas.records import build_manual_review


@dataclass(frozen=True)
class ReviewItem:
    """What a human reviewer needs to see for one segment -- no audio."""

    segment_id: str
    source_file_id: str
    source_start: float
    source_end: float
    speaker_id: str
    transcript: str | None
    target_speaker_status: str
    confidence_classification: str | None


class ManualReviewLog(JsonLinesRegistry):
    def __init__(self, path):
        super().__init__(path=path, schema_name=SchemaName.MANUAL_REVIEW, id_field="review_id")


class ReviewQueue:
    """Pending items = segments whose acceptance_status is 'pending' or
    'ambiguous', or whose target_speaker_status is 'manual_review'."""

    PENDING_ACCEPTANCE_STATUSES = frozenset({"pending", "ambiguous"})

    def __init__(self, segments: list[dict[str, Any]]):
        self._segments = segments

    def pending_items(self) -> list[ReviewItem]:
        items = []
        for seg in self._segments:
            needs_review = (
                seg.get("acceptance_status") in self.PENDING_ACCEPTANCE_STATUSES
                or seg.get("target_speaker_status") == "manual_review"
            )
            if needs_review:
                items.append(
                    ReviewItem(
                        segment_id=seg["segment_id"],
                        source_file_id=seg["source_file_id"],
                        source_start=seg["source_start"],
                        source_end=seg["source_end"],
                        speaker_id=seg["speaker_id"],
                        transcript=seg.get("transcript"),
                        target_speaker_status=seg["target_speaker_status"],
                        confidence_classification=seg.get("confidence_classification"),
                    )
                )
        return items

    @staticmethod
    def record_decision(
        log: ManualReviewLog,
        *,
        review_id: str,
        segment_id: str,
        reviewer: str,
        reviewed_at: str,
        decision: str,
        notes: str | None = None,
    ) -> dict[str, Any]:
        if decision not in {"approve", "reject", "ambiguous"}:
            raise ValueError(f"Invalid decision: {decision!r}")
        record = build_manual_review(
            review_id=review_id,
            segment_id=segment_id,
            reviewer=reviewer,
            reviewed_at=reviewed_at,
            decision=decision,
            notes=notes,
        )
        log.add(record)
        return record
