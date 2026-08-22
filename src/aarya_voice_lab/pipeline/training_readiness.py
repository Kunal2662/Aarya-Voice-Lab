"""Real Voice Model Engine milestone — dataset/profile training-readiness
assessment.

This is pure aggregation over already-measured values (the same shape as
`pipeline.evaluation_aggregation` and `pipeline.calibration_prep`): it
never re-measures audio itself and never invents a number. Callers pass
in real per-recording measurements already produced elsewhere in the
pipeline (`audio.analysis.measure`, `pipeline.quality.assess_quality`,
`identity.calibration`), and this module only decides, factor by factor,
whether the aggregate clears a documented threshold.

Every threshold lives in `configs/default.yaml`'s `training_readiness`
section, never hardcoded here, so its origin is inspectable and it can be
tightened once a real model's actual data requirements are known (see
`docs/REAL_VOICE_MODEL_ENGINE.md`). A `TrainingProvider` may declare its
own, stricter requirements (`TrainingProvider.data_requirements()`); this
module's config values are a floor, not a ceiling — the effective
threshold for any factor is the stricter of the two.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from aarya_voice_lab.core.config import AaryaVoiceLabConfig
from aarya_voice_lab.identity.calibration import CalibrationState

DEFAULT_THRESHOLDS: dict[str, float] = {
    "minimum_sample_count": 20,
    "minimum_total_duration_seconds": 300,
    "minimum_average_duration_seconds": 2.0,
    "required_sample_rate": 16000,
    "required_channels": 1,
    "max_clipping_ratio": 0.01,
    "max_silence_ratio": 0.5,
    "minimum_snr_db": 15.0,
}


def thresholds_from_config(config: AaryaVoiceLabConfig | None) -> dict[str, float]:
    """Merge `configs/default.yaml`'s `training_readiness` section over
    the documented defaults above. A config missing the section, or
    missing individual keys, falls back to the defaults rather than
    raising — the defaults themselves are the documented origin for an
    un-configured value."""
    configured = (config.raw.get("training_readiness") if config else None) or {}
    return {**DEFAULT_THRESHOLDS, **configured}


class ReadinessFactor(StrEnum):
    SAMPLE_COUNT = "sample_count"
    TOTAL_DURATION = "total_duration"
    AVERAGE_DURATION = "average_duration"
    SAMPLE_RATE = "sample_rate"
    CHANNELS = "channels"
    CLIPPING = "clipping"
    SILENCE = "silence"
    SIGNAL_TO_NOISE = "signal_to_noise"
    QUALITY_DECISION = "quality_decision"
    PROCESSING_STATUS = "processing_status"
    CALIBRATION_STATE = "calibration_state"
    SPEAKER_CONSISTENCY = "speaker_consistency"
    DUPLICATE_CONTENT = "duplicate_content"
    METADATA_COMPLETENESS = "metadata_completeness"


@dataclass(frozen=True)
class FactorResult:
    factor: ReadinessFactor
    passed: bool
    measured: Any
    required: Any
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor": self.factor.value,
            "passed": self.passed,
            "measured": self.measured,
            "required": self.required,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class TrainingReadinessInput:
    """Real, already-measured values a caller assembles from the
    candidate manifest, quality summary, and calibration state. Every
    field here must trace back to a real measurement — this dataclass
    performs no computation of its own, only carries what was already
    computed elsewhere.
    """

    sample_count: int
    total_duration_seconds: float
    sample_rate: int | None
    channels: int | None
    #: Mean of per-sample `audio.analysis.AudioMeasurements.clipping_ratio`.
    mean_clipping_ratio: float | None
    #: Mean of per-sample `AudioMeasurements.silent_frame_ratio`.
    mean_silence_ratio: float | None
    #: Mean of per-sample `AudioMeasurements.estimated_snr_db`; `None` when
    #: not measurable, never fabricated.
    mean_snr_db: float | None
    #: How many samples carry a FAIL `pipeline.quality.QualityDecision`.
    failing_quality_count: int
    #: How many samples are not yet through processing (still QUEUED/
    #: PREPARING/etc. rather than a terminal processing_status).
    unprocessed_count: int
    calibration_state: CalibrationState
    #: How many samples appear more than once (by content hash) in the
    #: source manifest — real duplicate detection, not an estimate.
    duplicate_sample_count: int
    #: Fields required by the target model's metadata contract that are
    #: missing on one or more samples (e.g. missing language tag).
    missing_metadata_fields: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_count": self.sample_count,
            "total_duration_seconds": round(self.total_duration_seconds, 6),
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "mean_clipping_ratio": self.mean_clipping_ratio,
            "mean_silence_ratio": self.mean_silence_ratio,
            "mean_snr_db": self.mean_snr_db,
            "failing_quality_count": self.failing_quality_count,
            "unprocessed_count": self.unprocessed_count,
            "calibration_state": self.calibration_state.value,
            "duplicate_sample_count": self.duplicate_sample_count,
            "missing_metadata_fields": list(self.missing_metadata_fields),
        }


@dataclass(frozen=True)
class TrainingReadinessReport:
    ready: bool
    factors: tuple[FactorResult, ...]
    thresholds_used: dict[str, float]
    input_summary: dict[str, Any]

    @property
    def failing_factors(self) -> tuple[FactorResult, ...]:
        return tuple(f for f in self.factors if not f.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "factors": [f.to_dict() for f in self.factors],
            "failing_factors": [f.factor.value for f in self.failing_factors],
            "thresholds_used": dict(self.thresholds_used),
            "input_summary": self.input_summary,
        }


def assess_training_readiness(
    data: TrainingReadinessInput,
    *,
    config: AaryaVoiceLabConfig | None = None,
    provider_requirements: dict[str, float] | None = None,
) -> TrainingReadinessReport:
    """Evaluate every documented factor and return a full, honest report.

    `provider_requirements` lets a `TrainingProvider` raise the floor for
    any threshold (e.g. a specific model needing a longer minimum
    duration); it can only tighten a requirement, never loosen one below
    the config default.
    """
    thresholds = thresholds_from_config(config)
    if provider_requirements:
        for key, value in provider_requirements.items():
            if key not in thresholds:
                continue
            # Tighter is a larger minimum, or a smaller maximum -- infer
            # direction from the key name rather than assuming one way.
            if key.startswith("max_"):
                thresholds[key] = min(thresholds[key], value)
            else:
                thresholds[key] = max(thresholds[key], value)

    average_duration = data.total_duration_seconds / data.sample_count if data.sample_count else 0.0

    factors: list[FactorResult] = [
        FactorResult(
            ReadinessFactor.SAMPLE_COUNT,
            data.sample_count >= thresholds["minimum_sample_count"],
            data.sample_count,
            thresholds["minimum_sample_count"],
            "Number of samples available for training.",
        ),
        FactorResult(
            ReadinessFactor.TOTAL_DURATION,
            data.total_duration_seconds >= thresholds["minimum_total_duration_seconds"],
            round(data.total_duration_seconds, 3),
            thresholds["minimum_total_duration_seconds"],
            "Total audio duration across all samples.",
        ),
        FactorResult(
            ReadinessFactor.AVERAGE_DURATION,
            average_duration >= thresholds["minimum_average_duration_seconds"],
            round(average_duration, 3),
            thresholds["minimum_average_duration_seconds"],
            "Mean duration per sample.",
        ),
        FactorResult(
            ReadinessFactor.SAMPLE_RATE,
            data.sample_rate == thresholds["required_sample_rate"],
            data.sample_rate,
            thresholds["required_sample_rate"],
            "Samples must already share the required sample rate.",
        ),
        FactorResult(
            ReadinessFactor.CHANNELS,
            data.channels == thresholds["required_channels"],
            data.channels,
            thresholds["required_channels"],
            "Samples must already be the required channel count.",
        ),
        FactorResult(
            ReadinessFactor.CLIPPING,
            data.mean_clipping_ratio is not None and data.mean_clipping_ratio <= thresholds["max_clipping_ratio"],
            data.mean_clipping_ratio,
            thresholds["max_clipping_ratio"],
            "Mean clipping ratio across samples; unmeasured counts as a failure, never assumed clean.",
        ),
        FactorResult(
            ReadinessFactor.SILENCE,
            data.mean_silence_ratio is not None and data.mean_silence_ratio <= thresholds["max_silence_ratio"],
            data.mean_silence_ratio,
            thresholds["max_silence_ratio"],
            "Mean silent-frame ratio across samples.",
        ),
        FactorResult(
            ReadinessFactor.SIGNAL_TO_NOISE,
            data.mean_snr_db is not None and data.mean_snr_db >= thresholds["minimum_snr_db"],
            data.mean_snr_db,
            thresholds["minimum_snr_db"],
            "Mean estimated SNR across samples; unmeasured counts as a failure.",
        ),
        FactorResult(
            ReadinessFactor.QUALITY_DECISION,
            data.failing_quality_count == 0,
            data.failing_quality_count,
            0,
            "Samples with a FAIL quality decision must be excluded or reprocessed before training.",
        ),
        FactorResult(
            ReadinessFactor.PROCESSING_STATUS,
            data.unprocessed_count == 0,
            data.unprocessed_count,
            0,
            "Every sample must have completed processing (a terminal processing_status).",
        ),
        FactorResult(
            ReadinessFactor.CALIBRATION_STATE,
            data.calibration_state is not CalibrationState.UNCALIBRATED,
            data.calibration_state.value,
            "PROVISIONAL or CALIBRATED",
            "Real speaker-identity calibration must have at least provisional evidence.",
        ),
        FactorResult(
            ReadinessFactor.SPEAKER_CONSISTENCY,
            True,
            "not independently assessed",
            "n/a",
            "Speaker consistency across samples is not independently verifiable without a real "
            "embedding provider (see identity.embeddings) -- reported informational, never assumed.",
        ),
        FactorResult(
            ReadinessFactor.DUPLICATE_CONTENT,
            data.duplicate_sample_count == 0,
            data.duplicate_sample_count,
            0,
            "Samples with duplicate content (by hash) must be de-duplicated before training.",
        ),
        FactorResult(
            ReadinessFactor.METADATA_COMPLETENESS,
            not data.missing_metadata_fields,
            list(data.missing_metadata_fields),
            [],
            "Fields the target model's metadata contract requires but at least one sample is missing.",
        ),
    ]

    # SPEAKER_CONSISTENCY is informational (see its detail above): it never
    # blocks readiness on its own, since there is no real embedding
    # provider installed to compute it (see identity.embeddings). Every
    # other factor is blocking.
    blocking = [f for f in factors if f.factor is not ReadinessFactor.SPEAKER_CONSISTENCY]
    ready = all(f.passed for f in blocking)

    return TrainingReadinessReport(
        ready=ready,
        factors=tuple(factors),
        thresholds_used=thresholds,
        input_summary=data.to_dict(),
    )
