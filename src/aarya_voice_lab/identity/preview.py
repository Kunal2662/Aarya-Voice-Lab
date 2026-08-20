"""VL-V0 — Universal Voice Preview & Feedback contracts.

Contracts only. **No voice generation exists**, and nothing here
synthesizes audio. This module fixes the shape of the future loop so
later phases can implement against a stable interface:

    operation -> generation -> preview -> listen -> feedback
              -> regenerate -> preview v2 -> accept -> final output

The requirement it encodes: **every voice-generation operation must
produce something a human can listen to before it is accepted.** A voice
built from a deceased person's recordings must never be adopted on the
strength of a similarity number alone — the only meaningful test is
whether it sounds right to someone who knew her.

In Phase 3 the only "preview" that exists is playback of an already-
extracted candidate segment during identity review. That is real audio
from the dataset, not generated speech, and `PreviewKind` distinguishes
the two so the difference stays legible in every record.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class PreviewKind(StrEnum):
    #: Playback of existing recorded audio. The only kind Phase 3 uses.
    SOURCE_SEGMENT = "source_segment"
    #: Speech produced by a voice model. PLANNED — never generated yet.
    GENERATED_SPEECH = "generated_speech"
    #: Generated from synthetic fixtures; not a voice.
    SYNTHETIC_FIXTURE = "synthetic_fixture"


class PreviewFeedbackOutcome(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    REGENERATE = "regenerate"
    UNCERTAIN = "uncertain"


@dataclass
class PreviewArtifact:
    """A listenable artifact plus the provenance to interpret it."""

    preview_id: str
    kind: PreviewKind
    #: Relative to the data root. Never absolute — paths can leak locations.
    relative_path: str
    sha256: str
    duration_seconds: float
    sample_rate: int
    iteration: int = 1
    #: What produced it: a segment id now, a model id later.
    origin_id: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    is_synthetic: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "preview_id": self.preview_id,
            "kind": self.kind.value,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "duration_seconds": round(self.duration_seconds, 6),
            "sample_rate": self.sample_rate,
            "iteration": self.iteration,
            "origin_id": self.origin_id,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "is_synthetic": self.is_synthetic,
            "created_at": self.created_at,
        }


@dataclass
class PreviewFeedback:
    """A listener's response to one preview iteration."""

    feedback_id: str
    preview_id: str
    listener: str
    outcome: PreviewFeedbackOutcome
    listened: bool
    listen_duration_seconds: float | None = None
    comment: str | None = None
    #: Structured hints for regeneration, e.g. {"pace": "too_fast"}.
    attributes: dict[str, str] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def requests_regeneration(self) -> bool:
        return self.outcome is PreviewFeedbackOutcome.REGENERATE

    def to_dict(self) -> dict[str, Any]:
        return {
            "feedback_id": self.feedback_id,
            "preview_id": self.preview_id,
            "listener": self.listener,
            "outcome": self.outcome.value,
            "listened": self.listened,
            "listen_duration_seconds": self.listen_duration_seconds,
            "comment": self.comment,
            "attributes": dict(self.attributes),
            "requests_regeneration": self.requests_regeneration,
            "created_at": self.created_at,
        }


class PreviewProvider(ABC):
    """Contract a future voice generator satisfies.

    No implementation exists. It is declared now so the preview loop can
    be designed, tested, and wired into the desktop UI before any model
    is chosen — and so that when one is chosen, the acceptance path
    already requires a human to listen.
    """

    name: str = "abstract"
    version: str = "0.0.0"

    @abstractmethod
    def generate_preview(self, request: dict[str, Any]) -> PreviewArtifact:
        raise NotImplementedError("Phase 3 implements no voice generation")

    @abstractmethod
    def supports_regeneration(self) -> bool:
        raise NotImplementedError


def preview_loop_state(
    previews: list[PreviewArtifact],
    feedback: list[PreviewFeedback],
) -> dict[str, Any]:
    """Summarise where a preview/feedback loop currently stands.

    Shape is fixed now so the desktop UI can be built against it while
    generation remains unimplemented.
    """
    by_preview = {f.preview_id: f for f in feedback}
    accepted = [
        p
        for p in previews
        if (response := by_preview.get(p.preview_id))
        and response.outcome is PreviewFeedbackOutcome.ACCEPTED
    ]
    awaiting = [p for p in previews if p.preview_id not in by_preview]
    return {
        "iteration_count": len(previews),
        "latest_iteration": max((p.iteration for p in previews), default=0),
        "awaiting_feedback": [p.preview_id for p in awaiting],
        "accepted_preview_id": accepted[-1].preview_id if accepted else None,
        "is_accepted": bool(accepted),
        "regeneration_requested": any(f.requests_regeneration for f in feedback),
        "generation_implemented": False,
        "note": (
            "VL-V0 contracts only. No voice generation exists in Phase 3, and no "
            "generated speech has ever been produced by this project."
        ),
    }
