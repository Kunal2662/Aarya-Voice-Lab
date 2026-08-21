"""Calibration preparation — VL-D3 §27, extended by VL-D5 §23, VL-D6, VL-D7.

Structured, real counts that `pipeline.calibration_engine` (VL-D7) reads:
how much quality feedback exists, how many segments have conflicting
review decisions, how many recordings are narrowband, how many carry an
overlap candidate, how many generation ratings and regenerations exist
(VL-D5), and — new in VL-D6 — how many human evaluations and reviewer
disagreements exist. **No score is computed here, and this module still
never becomes calibrated itself** — the state each summary reports is
always `identity.calibration.CalibrationState.UNCALIBRATED`, the same
honesty rule `identity.calibration` already enforces for target-speaker
verification. `pipeline.calibration_engine` is the module that reads
these summaries and may reach `PROVISIONAL` (never `CALIBRATED`); this
module's own job stays exactly what it was before VL-D7 existed --
counting, never judging. VL-D6 deliberately did not call
`identity.calibration.provisional_from_reviewer_feedback()` itself —
that function already existed and already did confidence-aware,
still-non-calibrating reviewer-agreement adjustment, but invoking it was
left to VL-D7, which now does so in `calibration_engine.run_calibration`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aarya_voice_lab.identity.calibration import CalibrationState
from aarya_voice_lab.identity.preview import PreviewFeedbackOutcome
from aarya_voice_lab.pipeline.candidate_review import CandidateReviewLog, review_disagreement_count
from aarya_voice_lab.pipeline.evaluation import EvaluationLog
from aarya_voice_lab.pipeline.evaluation_aggregation import EvaluationCalibrationSignals, summarize_calibration_signals
from aarya_voice_lab.pipeline.feedback import FeedbackLog, FeedbackType, counts_by_type
from aarya_voice_lab.pipeline.inventory import Inventory
from aarya_voice_lab.pipeline.preview_feedback import PreviewFeedbackLog, counts_by_category, counts_by_outcome
from aarya_voice_lab.pipeline.preview_history import PreviewHistoryLog, regeneration_count


@dataclass(frozen=True)
class CalibrationInputSummary:
    calibration_state: CalibrationState
    quality_feedback_count: int
    review_disagreement_count: int
    narrowband_count: int
    total_recordings: int
    feedback_counts_by_type: dict[str, int]
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "calibration_state": self.calibration_state.value,
            "quality_feedback_count": self.quality_feedback_count,
            "review_disagreement_count": self.review_disagreement_count,
            "narrowband_count": self.narrowband_count,
            "total_recordings": self.total_recordings,
            "feedback_counts_by_type": self.feedback_counts_by_type,
            "note": self.note,
        }


def summarize_calibration_inputs(
    *,
    inventory: Inventory | None = None,
    feedback_log: FeedbackLog | None = None,
    review_log: CandidateReviewLog | None = None,
    narrowband_sample_rate_hz: int = 16_000,
) -> CalibrationInputSummary:
    feedback_counts = counts_by_type(feedback_log) if feedback_log is not None else {t.value: 0 for t in FeedbackType}

    narrowband_count = 0
    total_recordings = 0
    if inventory is not None:
        total_recordings = len(inventory.unique_files)
        narrowband_count = sum(
            1
            for record in inventory.unique_files
            if record.sample_rate and record.sample_rate < narrowband_sample_rate_hz
        )

    disagreements = review_disagreement_count(review_log) if review_log is not None else 0

    return CalibrationInputSummary(
        calibration_state=CalibrationState.UNCALIBRATED,
        quality_feedback_count=feedback_counts.get(FeedbackType.QUALITY_FEEDBACK.value, 0),
        review_disagreement_count=disagreements,
        narrowband_count=narrowband_count,
        total_recordings=total_recordings,
        feedback_counts_by_type=feedback_counts,
        note=(
            "pipeline.calibration_engine (VL-D7) reads these as raw evidence "
            "inputs; never a computed score."
        ),
    )


@dataclass(frozen=True)
class PreviewCalibrationInputSummary:
    calibration_state: CalibrationState
    total_generations: int
    voice_profile_count: int
    total_regenerations: int
    feedback_counts_by_outcome: dict[str, int]
    feedback_counts_by_category: dict[str, int]
    accepted_count: int
    rejected_count: int
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "calibration_state": self.calibration_state.value,
            "total_generations": self.total_generations,
            "voice_profile_count": self.voice_profile_count,
            "total_regenerations": self.total_regenerations,
            "feedback_counts_by_outcome": self.feedback_counts_by_outcome,
            "feedback_counts_by_category": self.feedback_counts_by_category,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "note": self.note,
        }


def summarize_preview_calibration_inputs(
    *,
    history_log: PreviewHistoryLog | None = None,
    feedback_log: PreviewFeedbackLog | None = None,
) -> PreviewCalibrationInputSummary:
    """VL-D5 §23 — structured generation/feedback signals for
    `pipeline.calibration_engine` (VL-D7). Always `UNCALIBRATED`; only real counts."""
    all_records = history_log.list() if history_log is not None else []
    voice_profile_ids = sorted({r["voice_profile_id"] for r in all_records})
    total_regenerations = (
        sum(regeneration_count(history_log, vid) for vid in voice_profile_ids) if history_log is not None else 0
    )

    outcome_counts = (
        counts_by_outcome(feedback_log) if feedback_log is not None else {o.value: 0 for o in PreviewFeedbackOutcome}
    )
    category_counts = counts_by_category(feedback_log) if feedback_log is not None else {}

    return PreviewCalibrationInputSummary(
        calibration_state=CalibrationState.UNCALIBRATED,
        total_generations=len(all_records),
        voice_profile_count=len(voice_profile_ids),
        total_regenerations=total_regenerations,
        feedback_counts_by_outcome=outcome_counts,
        feedback_counts_by_category=category_counts,
        accepted_count=outcome_counts.get(PreviewFeedbackOutcome.ACCEPTED.value, 0),
        rejected_count=outcome_counts.get(PreviewFeedbackOutcome.REJECTED.value, 0),
        note=(
            "pipeline.calibration_engine (VL-D7) reads these as raw evidence "
            "inputs; never a computed score."
        ),
    )


@dataclass(frozen=True)
class EvaluationCalibrationInputSummary:
    calibration_state: CalibrationState
    total_evaluations: int
    total_outputs_evaluated: int
    total_reviewers: int
    disagreement_output_count: int
    completed_count: int
    cannot_judge_count: int
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "calibration_state": self.calibration_state.value,
            "total_evaluations": self.total_evaluations,
            "total_outputs_evaluated": self.total_outputs_evaluated,
            "total_reviewers": self.total_reviewers,
            "disagreement_output_count": self.disagreement_output_count,
            "completed_count": self.completed_count,
            "cannot_judge_count": self.cannot_judge_count,
            "note": self.note,
        }


def summarize_evaluation_calibration_inputs(
    *, evaluation_log: EvaluationLog | None = None
) -> EvaluationCalibrationInputSummary:
    """VL-D6 — structured human-evaluation/disagreement signals for
    `pipeline.calibration_engine` (VL-D7). Always `UNCALIBRATED`; only real
    counts, computed by `pipeline.evaluation_aggregation` (pure
    aggregation, no new judgement made here or there)."""
    signals = (
        summarize_calibration_signals(evaluation_log)
        if evaluation_log is not None
        else EvaluationCalibrationSignals(
            total_evaluations=0,
            total_outputs_evaluated=0,
            total_reviewers=0,
            disagreement_output_count=0,
            completed_count=0,
            cannot_judge_count=0,
            note="No evaluation log supplied.",
        )
    )

    return EvaluationCalibrationInputSummary(
        calibration_state=CalibrationState.UNCALIBRATED,
        total_evaluations=signals.total_evaluations,
        total_outputs_evaluated=signals.total_outputs_evaluated,
        total_reviewers=signals.total_reviewers,
        disagreement_output_count=signals.disagreement_output_count,
        completed_count=signals.completed_count,
        cannot_judge_count=signals.cannot_judge_count,
        note=(
            "pipeline.calibration_engine (VL-D7) reads these as raw evidence "
            "inputs; never a computed score."
        ),
    )
