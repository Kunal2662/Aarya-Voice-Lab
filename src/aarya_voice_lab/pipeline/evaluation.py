"""Human evaluation of voice preview outputs — VL-D6.

Builds on VL-V0's `identity.preview` and VL-D5's `pipeline.preview_feedback`
rather than duplicating them. `identity.preview.PreviewFeedback` stays
exactly as-is — VL-D5's single-output accept/reject/regenerate loop is
untouched. This module covers the genuinely broader concern that flat
shape cannot express: *multiple simultaneous dimension scores*, a
*confidence* score, a *CANNOT_JUDGE* state, and *many reviewers
evaluating the same output* (reviewer disagreement) — the same "build
new only where the existing concept is genuinely different" judgement
VL-D3's `candidate_review` (vs. `identity_review`) and VL-D5's
`generation_models` (vs. `registry.model_registry`) already used.

`VoiceQualityDimension` is deliberately bounded to 11 values, not the
full folk taxonomy of speech-quality adjectives. Seven names are reused
verbatim from `pipeline.preview_feedback.PreviewFeedbackCategory`
because they mean the literal same thing in both contexts: NATURALNESS,
CLARITY, PRONUNCIATION, PROSODY, PACE, ARTIFACTS, OVERALL. Four are new
because VL-D6's evaluation model genuinely needs them: INTELLIGIBILITY
(can the words be understood — distinct from CLARITY, which is about
how clean the audio sounds), EXPRESSIVENESS, CONSISTENCY, and NOISE
(background noise — distinct from ARTIFACTS' synthesis-glitch meaning).
Two axes the phase spec asked about fold into existing ones rather than
duplicating: Rhythm → PROSODY, Stability → CONSISTENCY.

Every field that identifies *what* was evaluated is an id or a hash
(`output_id`, `voice_profile_id`, `model_id`, `config_hash`,
`output_sha256`) — the same "connected only by id references" discipline
VL-D5's `VoiceProfile` already established. There is no field anywhere
in this module capable of expressing a speaker characteristic, an
accent, a pronunciation match, or a target-speaker label.
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

EVALUATION_SCHEMA_VERSION = "1.0.0"

MIN_SCORE = 1
MAX_SCORE = 5


class VoiceQualityDimension(StrEnum):
    NATURALNESS = "NATURALNESS"
    CLARITY = "CLARITY"
    INTELLIGIBILITY = "INTELLIGIBILITY"
    PRONUNCIATION = "PRONUNCIATION"
    PROSODY = "PROSODY"
    PACE = "PACE"
    EXPRESSIVENESS = "EXPRESSIVENESS"
    CONSISTENCY = "CONSISTENCY"
    ARTIFACTS = "ARTIFACTS"
    NOISE = "NOISE"
    OVERALL = "OVERALL"


class EvaluationCompletionState(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANNOT_JUDGE = "CANNOT_JUDGE"
    ABANDONED = "ABANDONED"


class ABDecision(StrEnum):
    """Deliberately separate from `identity.preview.PreviewFeedbackOutcome`
    — that vocabulary (accepted/rejected/regenerate/uncertain) is about a
    single output's fate, not a comparison between two."""

    PREFER_A = "PREFER_A"
    PREFER_B = "PREFER_B"
    NO_PREFERENCE = "NO_PREFERENCE"
    CANNOT_JUDGE = "CANNOT_JUDGE"


class UnlistenedEvaluationError(RuntimeError):
    """Raised when an evaluation is marked COMPLETED, or an A/B decision
    of PREFER_A/PREFER_B/NO_PREFERENCE is recorded, without the relevant
    output(s) having been listened to first. The same enforced-in-code
    discipline `pipeline.preview_feedback.UnlistenedFeedbackError`
    already established, generalised to a multi-dimension record and to
    a two-output comparison."""


class InvalidDimensionScoreError(ValueError):
    """A dimension score outside [MIN_SCORE, MAX_SCORE], a score for a
    dimension not in `VoiceQualityDimension`, or a dimension marked both
    scored and cannot-judge."""


@dataclass(frozen=True)
class ListeningState:
    """Honest, browser-measurable listening signals only. `listened` is
    the single boolean gate (matches `PreviewFeedback.listened`'s meaning
    exactly); everything else is additional detail, never inflated
    beyond what a real `<audio>` element can report.
    `furthest_position_seconds` is deliberately not called "time
    listened" — a user can seek, so this is only the furthest playback
    position reached, not elapsed listening time. If a caller cannot
    measure it reliably, it stays `None` rather than a fabricated 0."""

    listened: bool = False
    first_listened_at: str | None = None
    replay_count: int = 0
    furthest_position_seconds: float | None = None
    completed_playback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "listened": self.listened,
            "first_listened_at": self.first_listened_at,
            "replay_count": self.replay_count,
            "furthest_position_seconds": self.furthest_position_seconds,
            "completed_playback": self.completed_playback,
        }


@dataclass(frozen=True)
class Evaluation:
    """One reviewer's structured evaluation of one output.

    **Append-only.** A second evaluation of the same `output_id` — by
    the same reviewer or a different one — is always a *new* record,
    never an edit. That is how reviewer disagreement is represented
    (multiple independent records for one output), not a separate
    mechanism. `supersedes` exists only for the narrower case of the
    *same* reviewer revising their own prior evaluation of the same
    output — it never merges or replaces a different reviewer's record.
    """

    evaluation_id: str
    output_id: str
    reviewer: str
    listening: ListeningState
    dimension_scores: dict[str, int] = field(default_factory=dict)
    cannot_judge_dimensions: tuple[str, ...] = field(default_factory=tuple)
    confidence: int | None = None
    completion_state: EvaluationCompletionState = EvaluationCompletionState.IN_PROGRESS
    comment: str | None = None
    voice_profile_id: str | None = None
    model_id: str | None = None
    config_hash: str | None = None
    output_sha256: str | None = None
    evaluation_version: int = 1
    supersedes: str | None = None
    created_at: str | None = None
    schema_version: str = EVALUATION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "evaluation_id": self.evaluation_id,
            "output_id": self.output_id,
            "reviewer": self.reviewer,
            "listening": self.listening.to_dict(),
            "dimension_scores": dict(self.dimension_scores),
            "cannot_judge_dimensions": list(self.cannot_judge_dimensions),
            "confidence": self.confidence,
            "completion_state": self.completion_state.value,
            "comment": self.comment,
            "voice_profile_id": self.voice_profile_id,
            "model_id": self.model_id,
            "config_hash": self.config_hash,
            "output_sha256": self.output_sha256,
            "evaluation_version": self.evaluation_version,
            "supersedes": self.supersedes,
            "created_at": self.created_at or datetime.now(UTC).isoformat(),
            "processing_version": __version__,
        }


class EvaluationLog(JsonLinesRegistry):
    def __init__(self, path: Path):
        super().__init__(path=path, schema_name=SchemaName.EVALUATION, id_field="evaluation_id")


def _validate_dimension_scores(dimension_scores: dict[str, int], cannot_judge_dimensions: tuple[str, ...]) -> None:
    known = {d.value for d in VoiceQualityDimension}
    for dimension, score in dimension_scores.items():
        if dimension not in known:
            raise InvalidDimensionScoreError(f"unknown VoiceQualityDimension: {dimension!r}")
        if not MIN_SCORE <= score <= MAX_SCORE:
            raise InvalidDimensionScoreError(
                f"score for {dimension} must be within {MIN_SCORE}..{MAX_SCORE}, got {score}"
            )
    for dimension in cannot_judge_dimensions:
        if dimension not in known:
            raise InvalidDimensionScoreError(f"unknown VoiceQualityDimension: {dimension!r}")
        if dimension in dimension_scores:
            raise InvalidDimensionScoreError(f"{dimension} cannot be both scored and marked cannot-judge")


def record_evaluation(
    log: EvaluationLog,
    *,
    output_id: str,
    reviewer: str,
    listening: ListeningState,
    dimension_scores: dict[str, int] | None = None,
    cannot_judge_dimensions: tuple[str, ...] = (),
    confidence: int | None = None,
    completion_state: EvaluationCompletionState = EvaluationCompletionState.COMPLETED,
    comment: str | None = None,
    voice_profile_id: str | None = None,
    model_id: str | None = None,
    config_hash: str | None = None,
    output_sha256: str | None = None,
    supersedes: str | None = None,
    evaluation_version: int = 1,
    evaluation_id: str | None = None,
) -> dict[str, Any]:
    """Append one evaluation record. Refuses to mark an evaluation
    COMPLETED without `listening.listened` — "no generated result should
    be treated as final without a previewable output" (VL-D5 §15)
    generalises directly to "no evaluation should be treated as final
    without having actually been listened to" here."""
    dimension_scores = dict(dimension_scores or {})
    _validate_dimension_scores(dimension_scores, cannot_judge_dimensions)

    if confidence is not None and not MIN_SCORE <= confidence <= MAX_SCORE:
        raise InvalidDimensionScoreError(f"confidence must be within {MIN_SCORE}..{MAX_SCORE}, got {confidence}")

    if completion_state == EvaluationCompletionState.COMPLETED and not listening.listened:
        raise UnlistenedEvaluationError(
            f"cannot mark evaluation of {output_id} COMPLETED — the output must be listened to first"
        )

    record = Evaluation(
        evaluation_id=evaluation_id or f"eval-{len(log.list()) + 1:05d}",
        output_id=output_id,
        reviewer=reviewer,
        listening=listening,
        dimension_scores=dimension_scores,
        cannot_judge_dimensions=tuple(cannot_judge_dimensions),
        confidence=confidence,
        completion_state=completion_state,
        comment=comment,
        voice_profile_id=voice_profile_id,
        model_id=model_id,
        config_hash=config_hash,
        output_sha256=output_sha256,
        supersedes=supersedes,
        evaluation_version=evaluation_version,
    )
    payload = record.to_dict()
    log.add(payload)
    return payload


def evaluations_for(log: EvaluationLog, output_id: str) -> list[dict[str, Any]]:
    """Every evaluation ever recorded for one output, in write order —
    this is precisely the raw material reviewer disagreement is computed
    from (see `pipeline.evaluation_aggregation`)."""
    return [r for r in log.list() if r["output_id"] == output_id]


def reviewers_for(log: EvaluationLog, output_id: str) -> list[str]:
    return [r["reviewer"] for r in evaluations_for(log, output_id)]


@dataclass(frozen=True)
class ABEvaluation:
    """A reviewer's A/B decision between two outputs. `blinded` records
    whether the reviewer's own panel suppressed model/profile/config
    labels while they evaluated — **UI-level metadata suppression only**.
    It is not a cryptographic or structural anonymity guarantee: nothing
    here prevents a reviewer from recognising a voice by its acoustic
    characteristics alone. Callers must never present `blinded=true` as
    a stronger claim than "the labels were hidden on screen."""

    ab_evaluation_id: str
    output_id_a: str
    output_id_b: str
    reviewer: str
    listened_a: bool
    listened_b: bool
    decision: ABDecision
    blinded: bool = False
    comment: str | None = None
    created_at: str | None = None
    schema_version: str = EVALUATION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ab_evaluation_id": self.ab_evaluation_id,
            "output_id_a": self.output_id_a,
            "output_id_b": self.output_id_b,
            "reviewer": self.reviewer,
            "listened_a": self.listened_a,
            "listened_b": self.listened_b,
            "decision": self.decision.value,
            "blinded": self.blinded,
            "comment": self.comment,
            "created_at": self.created_at or datetime.now(UTC).isoformat(),
            "processing_version": __version__,
        }


class ABEvaluationLog(JsonLinesRegistry):
    def __init__(self, path: Path):
        super().__init__(path=path, schema_name=SchemaName.AB_EVALUATION, id_field="ab_evaluation_id")


_DECISIONS_REQUIRING_BOTH_LISTENED = frozenset({ABDecision.PREFER_A, ABDecision.PREFER_B, ABDecision.NO_PREFERENCE})


def record_ab_evaluation(
    log: ABEvaluationLog,
    *,
    output_id_a: str,
    output_id_b: str,
    reviewer: str,
    listened_a: bool,
    listened_b: bool,
    decision: ABDecision,
    blinded: bool = False,
    comment: str | None = None,
    ab_evaluation_id: str | None = None,
) -> dict[str, Any]:
    """CANNOT_JUDGE never requires listening (a reviewer may reach it
    precisely because playback failed); PREFER_A/PREFER_B/NO_PREFERENCE
    all require both outputs to have been listened to."""
    if decision in _DECISIONS_REQUIRING_BOTH_LISTENED and not (listened_a and listened_b):
        raise UnlistenedEvaluationError(
            f"cannot record {decision.value} between {output_id_a} and {output_id_b} "
            "— both outputs must be listened to first"
        )

    record = ABEvaluation(
        ab_evaluation_id=ab_evaluation_id or f"ab-eval-{len(log.list()) + 1:05d}",
        output_id_a=output_id_a,
        output_id_b=output_id_b,
        reviewer=reviewer,
        listened_a=listened_a,
        listened_b=listened_b,
        decision=decision,
        blinded=blinded,
        comment=comment,
    )
    payload = record.to_dict()
    log.add(payload)
    return payload


def ab_evaluations_for(log: ABEvaluationLog, output_id: str) -> list[dict[str, Any]]:
    """Every A/B record naming this output on either side."""
    return [r for r in log.list() if output_id in (r["output_id_a"], r["output_id_b"])]
