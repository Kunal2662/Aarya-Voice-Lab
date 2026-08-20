"""Dataset-level quality aggregation — VL-D3 §18.

Pure aggregation over already-computed `pipeline.quality.QualityAssessment`
records (or equivalent dicts) and, optionally,
`pipeline.overlap.OverlapAssessment` statuses. Computes no new acoustic
measurement and makes no new quality decision — everything here is either
a `statistics` call or a bucket count over values `audio.analysis` /
`pipeline.quality` / `pipeline.overlap` already produced.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from aarya_voice_lab.pipeline.overlap import OverlapStatus
from aarya_voice_lab.pipeline.quality import QualityAssessment

#: Human-readable, half-open buckets: label -> (inclusive lower, exclusive upper).
_DURATION_BUCKETS_SECONDS: tuple[tuple[str, float, float], ...] = (
    ("<30s", 0.0, 30.0),
    ("30-60s", 30.0, 60.0),
    ("60-120s", 60.0, 120.0),
    ("120s+", 120.0, float("inf")),
)
_SNR_BUCKETS_DB: tuple[tuple[str, float, float], ...] = (
    ("<10dB", float("-inf"), 10.0),
    ("10-20dB", 10.0, 20.0),
    ("20-30dB", 20.0, 30.0),
    ("30dB+", 30.0, float("inf")),
)
_RATIO_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("0-25%", 0.0, 0.25),
    ("25-50%", 0.25, 0.50),
    ("50-75%", 0.50, 0.75),
    ("75-100%", 0.75, 1.0 + 1e-9),
)
_NOT_AVAILABLE = "not_available"
_OVERLAP_CANDIDATE_STATUSES = frozenset({OverlapStatus.POSSIBLE_OVERLAP.value, OverlapStatus.OVERLAP_DETECTED.value})


def _bucket(value: float | None, buckets: tuple[tuple[str, float, float], ...]) -> str:
    if value is None:
        return _NOT_AVAILABLE
    for label, low, high in buckets:
        if low <= value < high:
            return label
    return buckets[-1][0]


def _increment(distribution: dict[str, int], key: str) -> None:
    distribution[key] = distribution.get(key, 0) + 1


@dataclass(frozen=True)
class QualitySummary:
    recording_count: int
    average_duration_seconds: float | None
    median_duration_seconds: float | None
    decision_distribution: dict[str, int]
    sample_rate_distribution: dict[str, int]
    channel_distribution: dict[str, int]
    warning_code_distribution: dict[str, int]
    duration_distribution: dict[str, int]
    snr_distribution: dict[str, int]
    speech_ratio_distribution: dict[str, int]
    silence_ratio_distribution: dict[str, int]
    narrowband_count: int
    #: None when no overlap statuses were supplied — "not measured", not "zero".
    overlap_candidate_count: int | None = None
    characteristics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recording_count": self.recording_count,
            "average_duration_seconds": _round_or_none(self.average_duration_seconds),
            "median_duration_seconds": _round_or_none(self.median_duration_seconds),
            "decision_distribution": self.decision_distribution,
            "sample_rate_distribution": self.sample_rate_distribution,
            "channel_distribution": self.channel_distribution,
            "warning_code_distribution": self.warning_code_distribution,
            "duration_distribution": self.duration_distribution,
            "snr_distribution": self.snr_distribution,
            "speech_ratio_distribution": self.speech_ratio_distribution,
            "silence_ratio_distribution": self.silence_ratio_distribution,
            "narrowband_count": self.narrowband_count,
            "overlap_candidate_count": self.overlap_candidate_count,
        }


def _round_or_none(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


def summarize_quality(
    assessments: list[QualityAssessment],
    *,
    channels_by_source_file_id: dict[str, int] | None = None,
    narrowband_sample_rate_hz: int = 16_000,
    overlap_statuses: list[str] | None = None,
) -> QualitySummary:
    """Aggregate a list of per-recording assessments. Empty input yields
    an all-empty, honestly-None summary rather than raising or fabricating
    a default.

    `overlap_statuses` is an optional flat list of
    `pipeline.overlap.OverlapStatus` values (one per assessed segment/
    recording, caller's choice of granularity) — omitted entirely when the
    caller has no overlap assessments in hand yet, so
    `overlap_candidate_count` stays `None` ("not measured") rather than a
    fabricated 0.
    """
    if not assessments:
        return QualitySummary(
            recording_count=0,
            average_duration_seconds=None,
            median_duration_seconds=None,
            decision_distribution={},
            sample_rate_distribution={},
            channel_distribution={},
            warning_code_distribution={},
            duration_distribution={},
            snr_distribution={},
            speech_ratio_distribution={},
            silence_ratio_distribution={},
            narrowband_count=0,
            overlap_candidate_count=(
                sum(1 for s in overlap_statuses if s in _OVERLAP_CANDIDATE_STATUSES)
                if overlap_statuses is not None
                else None
            ),
        )

    durations = [
        a.measurements.get("duration_seconds")
        for a in assessments
        if a.measurements.get("duration_seconds") is not None
    ]
    decision_distribution: dict[str, int] = {}
    sample_rate_distribution: dict[str, int] = {}
    channel_distribution: dict[str, int] = {}
    warning_code_distribution: dict[str, int] = {}
    duration_distribution: dict[str, int] = {}
    snr_distribution: dict[str, int] = {}
    speech_ratio_distribution: dict[str, int] = {}
    silence_ratio_distribution: dict[str, int] = {}
    narrowband_count = 0

    for assessment in assessments:
        _increment(decision_distribution, assessment.decision.value)

        sample_rate = assessment.measurements.get("sample_rate")
        if sample_rate is not None:
            _increment(sample_rate_distribution, str(sample_rate))
            if sample_rate < narrowband_sample_rate_hz:
                narrowband_count += 1

        # AudioMeasurements carries no channel count -- that's inventory
        # metadata, not an acoustic measurement -- so channel distribution
        # is only computed when the caller supplies it explicitly rather
        # than invented from what's available here.
        channels = (channels_by_source_file_id or {}).get(assessment.source_file_id)
        if channels is not None:
            _increment(channel_distribution, str(channels))

        for finding in assessment.findings:
            _increment(warning_code_distribution, finding.code)

        duration_bucket = _bucket(assessment.measurements.get("duration_seconds"), _DURATION_BUCKETS_SECONDS)
        _increment(duration_distribution, duration_bucket)
        snr_bucket = _bucket(assessment.measurements.get("estimated_snr_db"), _SNR_BUCKETS_DB)
        _increment(snr_distribution, snr_bucket)
        speech_bucket = _bucket(assessment.speech.get("speech_ratio"), _RATIO_BUCKETS)
        _increment(speech_ratio_distribution, speech_bucket)
        silence_bucket = _bucket(assessment.measurements.get("silent_frame_ratio"), _RATIO_BUCKETS)
        _increment(silence_ratio_distribution, silence_bucket)

    return QualitySummary(
        recording_count=len(assessments),
        average_duration_seconds=statistics.fmean(durations) if durations else None,
        median_duration_seconds=statistics.median(durations) if durations else None,
        decision_distribution=decision_distribution,
        sample_rate_distribution=sample_rate_distribution,
        channel_distribution=channel_distribution,
        warning_code_distribution=warning_code_distribution,
        duration_distribution=duration_distribution,
        snr_distribution=snr_distribution,
        speech_ratio_distribution=speech_ratio_distribution,
        silence_ratio_distribution=silence_ratio_distribution,
        narrowband_count=narrowband_count,
        overlap_candidate_count=(
            sum(1 for s in overlap_statuses if s in _OVERLAP_CANDIDATE_STATUSES)
            if overlap_statuses is not None
            else None
        ),
    )
