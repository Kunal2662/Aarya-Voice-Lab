"""Preview feedback persistence — VL-D5 §21, §22.

Reuses `identity.preview.PreviewFeedback`/`PreviewFeedbackOutcome`
directly (Phase 3's VL-V0 contract for exactly this: a listener's
response to one preview iteration, with `listened`, `outcome`
ACCEPTED/REJECTED/REGENERATE/UNCERTAIN, and a free-form `attributes`
dict) rather than building a second, competing feedback record. This
module adds only what VL-V0 never needed: persistence
(`JsonLinesRegistry`, mirroring `pipeline.feedback`/`pipeline.candidate_review`)
and a validated category vocabulary for VL-D5 §21's specific feedback
axes, stored in the existing `attributes["category"]` field exactly the
way VL-D4's `ProcessingFeedbackCategory` already uses that field.

**A rating/accept/reject decision without having listened is refused.**
"No generated result should be treated as final without a previewable
output" (VL-D5 §15) is enforced here, not left to the caller to
remember: `record_preview_feedback()` raises if `outcome` is
`ACCEPTED`/`REJECTED` and `listened` is `False`.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from aarya_voice_lab.identity.preview import PreviewFeedback, PreviewFeedbackOutcome
from aarya_voice_lab.registry.json_registry import JsonLinesRegistry
from aarya_voice_lab.schemas.base import SchemaName


class PreviewFeedbackCategory(StrEnum):
    VOICE_QUALITY = "VOICE_QUALITY"
    NATURALNESS = "NATURALNESS"
    CLARITY = "CLARITY"
    PRONUNCIATION = "PRONUNCIATION"
    PACE = "PACE"
    PITCH = "PITCH"
    PROSODY = "PROSODY"
    STYLE = "STYLE"
    ARTIFACTS = "ARTIFACTS"
    OVERALL = "OVERALL"


class UnlistenedFeedbackError(RuntimeError):
    """Raised when an accept/reject decision is recorded without the
    preview having been listened to first."""


class PreviewFeedbackLog(JsonLinesRegistry):
    def __init__(self, path: Path):
        super().__init__(path=path, schema_name=SchemaName.PREVIEW_FEEDBACK, id_field="feedback_id")


def record_preview_feedback(
    log: PreviewFeedbackLog,
    *,
    preview_id: str,
    listener: str,
    outcome: PreviewFeedbackOutcome,
    listened: bool,
    category: PreviewFeedbackCategory | None = None,
    rating: int | None = None,
    comment: str | None = None,
    feedback_id: str | None = None,
) -> dict[str, Any]:
    if not listened and outcome in (PreviewFeedbackOutcome.ACCEPTED, PreviewFeedbackOutcome.REJECTED):
        raise UnlistenedFeedbackError(
            f"cannot record {outcome.value} for {preview_id} — the preview must be listened to first"
        )
    if category is not None and not isinstance(category, PreviewFeedbackCategory):
        raise ValueError(f"unknown PreviewFeedbackCategory: {category!r}")

    attributes: dict[str, str] = {}
    if category is not None:
        attributes["category"] = category.value
    if rating is not None:
        attributes["rating"] = str(rating)

    record = PreviewFeedback(
        feedback_id=feedback_id or f"preview-feedback-{len(log.list()) + 1:05d}",
        preview_id=preview_id,
        listener=listener,
        outcome=outcome,
        listened=listened,
        comment=comment,
        attributes=attributes,
    )
    payload = record.to_dict()
    log.add(payload)
    return payload


def feedback_for(log: PreviewFeedbackLog, preview_id: str) -> list[dict[str, Any]]:
    return [r for r in log.list() if r["preview_id"] == preview_id]


def counts_by_outcome(log: PreviewFeedbackLog) -> dict[str, int]:
    counts = dict.fromkeys((o.value for o in PreviewFeedbackOutcome), 0)
    for record in log.list():
        counts[record["outcome"]] += 1
    return counts


def counts_by_category(log: PreviewFeedbackLog) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in log.list():
        category = record.get("attributes", {}).get("category")
        if category:
            counts[category] = counts.get(category, 0) + 1
    return counts
