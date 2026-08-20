"""Calibration preparation — VL-D3 §27.

Structured, real counts the future AI Calibration Engine (VL-D15) will
eventually read: how much quality feedback exists, how many segments
have conflicting review decisions, how many recordings are narrowband,
how many carry an overlap candidate. **No score is computed here.** The
state is always `identity.calibration.CalibrationState.UNCALIBRATED` —
the same honesty rule `identity.calibration` already enforces for
target-speaker verification applies here for exactly the same reason:
there is no engine yet to have calibrated anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aarya_voice_lab.identity.calibration import CalibrationState
from aarya_voice_lab.pipeline.candidate_review import CandidateReviewLog, review_disagreement_count
from aarya_voice_lab.pipeline.feedback import FeedbackLog, FeedbackType, counts_by_type
from aarya_voice_lab.pipeline.inventory import Inventory


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
            "No AI Calibration Engine exists yet (VL-D15). These are raw counts "
            "for a future engine to read, never a computed score."
        ),
    )
