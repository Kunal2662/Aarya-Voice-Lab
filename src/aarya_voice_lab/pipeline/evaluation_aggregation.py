"""Evaluation aggregation and reviewer disagreement — VL-D6.

Pure aggregation over already-written `pipeline.evaluation.Evaluation`/
`ABEvaluation` records. Computes no new evaluation and makes no new
judgement — everything here is a `statistics` call or a bucket count
over values a reviewer already recorded. Mirrors
`pipeline.quality_summary`'s "empty input → honest `None`, never
fabricated" discipline exactly: a dimension nobody scored yet has `None`
statistics, not a manufactured 0 or 3.

**Small samples stay visibly small.** `variance` is `None` below two
data points (mathematically undefined, not "zero spread"). Disagreement
is never claimed from a single evaluation — `MIN_EVALUATIONS_FOR_DISAGREEMENT`
gates it explicitly. Nothing here computes a confidence interval or a
significance test; none would be defensible at the sample sizes this
project's synthetic fixtures or an early real reviewer pool produce.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from aarya_voice_lab.pipeline.evaluation import ABDecision, EvaluationLog, VoiceQualityDimension

#: Fewer than this many independent evaluations of the same output and
#: "disagreement" is not a claim this module will make — one reviewer
#: cannot disagree with themselves.
MIN_EVALUATIONS_FOR_DISAGREEMENT = 2

#: On the 1-5 dimension scale, a max-min spread at or above this counts
#: as disagreement on that dimension. A spread of 1 (e.g. 3 vs 4) is
#: treated as normal reviewer variation, not a flagged disagreement.
DISAGREEMENT_SPREAD_THRESHOLD = 2


@dataclass(frozen=True)
class DimensionStatistics:
    dimension: str
    sample_count: int
    mean: float | None
    median: float | None
    variance: float | None
    min_score: int | None
    max_score: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "sample_count": self.sample_count,
            "mean": _round_or_none(self.mean),
            "median": _round_or_none(self.median),
            "variance": _round_or_none(self.variance),
            "min_score": self.min_score,
            "max_score": self.max_score,
        }


def _round_or_none(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


def summarize_dimension(scores: list[int], *, dimension: str) -> DimensionStatistics:
    if not scores:
        return DimensionStatistics(
            dimension=dimension, sample_count=0, mean=None, median=None, variance=None, min_score=None, max_score=None
        )
    return DimensionStatistics(
        dimension=dimension,
        sample_count=len(scores),
        mean=statistics.fmean(scores),
        median=statistics.median(scores),
        variance=statistics.variance(scores) if len(scores) >= 2 else None,
        min_score=min(scores),
        max_score=max(scores),
    )


def _has_dimension_disagreement(stats: DimensionStatistics) -> bool:
    if stats.sample_count < MIN_EVALUATIONS_FOR_DISAGREEMENT:
        return False
    return (stats.max_score - stats.min_score) >= DISAGREEMENT_SPREAD_THRESHOLD


@dataclass(frozen=True)
class OutputEvaluationSummary:
    output_id: str
    evaluation_count: int
    reviewer_count: int
    completed_count: int
    cannot_judge_count: int
    dimension_statistics: dict[str, DimensionStatistics]
    disagreement_dimensions: list[str]
    note: str

    @property
    def has_disagreement(self) -> bool:
        return bool(self.disagreement_dimensions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_id": self.output_id,
            "evaluation_count": self.evaluation_count,
            "reviewer_count": self.reviewer_count,
            "completed_count": self.completed_count,
            "cannot_judge_count": self.cannot_judge_count,
            "dimension_statistics": {k: v.to_dict() for k, v in self.dimension_statistics.items()},
            "has_disagreement": self.has_disagreement,
            "disagreement_dimensions": list(self.disagreement_dimensions),
            "note": self.note,
        }


def summarize_output_evaluations(evaluations: list[dict[str, Any]], *, output_id: str) -> OutputEvaluationSummary:
    """`evaluations` must already be filtered to one `output_id` (see
    `pipeline.evaluation.evaluations_for()`) — this function performs no
    filtering of its own, only aggregation."""
    if not evaluations:
        return OutputEvaluationSummary(
            output_id=output_id,
            evaluation_count=0,
            reviewer_count=0,
            completed_count=0,
            cannot_judge_count=0,
            dimension_statistics={d.value: summarize_dimension([], dimension=d.value) for d in VoiceQualityDimension},
            disagreement_dimensions=[],
            note="No evaluations recorded for this output yet.",
        )

    dimension_statistics: dict[str, DimensionStatistics] = {}
    for dimension in VoiceQualityDimension:
        scores = [
            e["dimension_scores"][dimension.value]
            for e in evaluations
            if dimension.value in e.get("dimension_scores", {})
        ]
        dimension_statistics[dimension.value] = summarize_dimension(scores, dimension=dimension.value)

    disagreement_dimensions = [
        dimension for dimension, stats in dimension_statistics.items() if _has_dimension_disagreement(stats)
    ]

    reviewer_count = len({e["reviewer"] for e in evaluations})
    completed_count = sum(1 for e in evaluations if e["completion_state"] == "COMPLETED")
    cannot_judge_count = sum(1 for e in evaluations if e["completion_state"] == "CANNOT_JUDGE")

    note = (
        f"{len(evaluations)} evaluation(s) from {reviewer_count} reviewer(s) — "
        + (
            "too few to assess disagreement (needs >=2)."
            if len(evaluations) < MIN_EVALUATIONS_FOR_DISAGREEMENT
            else ("disagreement detected." if disagreement_dimensions else "no disagreement detected.")
        )
    )

    return OutputEvaluationSummary(
        output_id=output_id,
        evaluation_count=len(evaluations),
        reviewer_count=reviewer_count,
        completed_count=completed_count,
        cannot_judge_count=cannot_judge_count,
        dimension_statistics=dimension_statistics,
        disagreement_dimensions=disagreement_dimensions,
        note=note,
    )


def outputs_with_disagreement(log: EvaluationLog) -> list[str]:
    """Every distinct `output_id` with >=2 evaluations and a disagreeing
    dimension — the multi-output equivalent of
    `pipeline.candidate_review.review_disagreement_count()`, returning
    ids rather than a bare count so a caller can link to each one."""
    by_output: dict[str, list[dict[str, Any]]] = {}
    for record in log.list():
        by_output.setdefault(record["output_id"], []).append(record)
    return [
        output_id
        for output_id, records in by_output.items()
        if summarize_output_evaluations(records, output_id=output_id).has_disagreement
    ]


@dataclass(frozen=True)
class ABPreferenceSummary:
    output_id_a: str
    output_id_b: str
    total_decisions: int
    prefer_a_count: int
    prefer_b_count: int
    no_preference_count: int
    cannot_judge_count: int
    #: Fraction of decisions with an actual preference (excludes
    #: NO_PREFERENCE/CANNOT_JUDGE) that favoured A. None when zero such
    #: decisions exist — never a fabricated 0.5.
    preference_rate_a: float | None
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_id_a": self.output_id_a,
            "output_id_b": self.output_id_b,
            "total_decisions": self.total_decisions,
            "prefer_a_count": self.prefer_a_count,
            "prefer_b_count": self.prefer_b_count,
            "no_preference_count": self.no_preference_count,
            "cannot_judge_count": self.cannot_judge_count,
            "preference_rate_a": _round_or_none(self.preference_rate_a),
            "note": self.note,
        }


def summarize_ab_preferences(
    ab_evaluations: list[dict[str, Any]], *, output_id_a: str, output_id_b: str
) -> ABPreferenceSummary:
    """`ab_evaluations` must already be filtered to this exact (A, B)
    pair — this function performs no filtering of its own. Pairwise
    preference counting only; never a claim of statistical significance
    regardless of sample size."""
    prefer_a = sum(1 for e in ab_evaluations if e["decision"] == ABDecision.PREFER_A.value)
    prefer_b = sum(1 for e in ab_evaluations if e["decision"] == ABDecision.PREFER_B.value)
    no_preference = sum(1 for e in ab_evaluations if e["decision"] == ABDecision.NO_PREFERENCE.value)
    cannot_judge = sum(1 for e in ab_evaluations if e["decision"] == ABDecision.CANNOT_JUDGE.value)
    decided = prefer_a + prefer_b

    return ABPreferenceSummary(
        output_id_a=output_id_a,
        output_id_b=output_id_b,
        total_decisions=len(ab_evaluations),
        prefer_a_count=prefer_a,
        prefer_b_count=prefer_b,
        no_preference_count=no_preference,
        cannot_judge_count=cannot_judge,
        preference_rate_a=(prefer_a / decided) if decided else None,
        note=(
            f"{len(ab_evaluations)} A/B decision(s), {decided} with a stated preference."
            if ab_evaluations
            else "No A/B decisions recorded for this pair yet."
        ),
    )


@dataclass(frozen=True)
class EvaluationCalibrationSignals:
    """Structured, real counts a future calibration step could read —
    never a computed score. Distinguishes raw reviewer feedback (the
    evaluations themselves) from an aggregated signal (this record)."""

    total_evaluations: int
    total_outputs_evaluated: int
    total_reviewers: int
    disagreement_output_count: int
    completed_count: int
    cannot_judge_count: int
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_evaluations": self.total_evaluations,
            "total_outputs_evaluated": self.total_outputs_evaluated,
            "total_reviewers": self.total_reviewers,
            "disagreement_output_count": self.disagreement_output_count,
            "completed_count": self.completed_count,
            "cannot_judge_count": self.cannot_judge_count,
            "note": self.note,
        }


def summarize_calibration_signals(log: EvaluationLog) -> EvaluationCalibrationSignals:
    records = log.list()
    return EvaluationCalibrationSignals(
        total_evaluations=len(records),
        total_outputs_evaluated=len({r["output_id"] for r in records}),
        total_reviewers=len({r["reviewer"] for r in records}),
        disagreement_output_count=len(outputs_with_disagreement(log)),
        completed_count=sum(1 for r in records if r["completion_state"] == "COMPLETED"),
        cannot_judge_count=sum(1 for r in records if r["completion_state"] == "CANNOT_JUDGE"),
        note=(
            "Raw counts for a future calibration step to read — never a computed "
            "score, and never used by this module to declare a voice calibrated."
        ),
    )
