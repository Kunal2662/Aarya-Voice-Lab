"""Quality decisions, driven entirely by configuration.

Strictly separate from `audio.analysis`, which only measures. This module
turns measurements into PASS / WARNING / REVIEW / FAIL using thresholds
the operator can change without touching code.

**Telephone and call recordings are expected input.** Low sample rate,
band-limiting, and low absolute level are characteristics to record, not
grounds for rejection. Only genuinely unusable audio — silence, heavy
clipping, no detectable activity — fails. Everything doubtful goes to
REVIEW rather than being discarded, because the source material is
irreplaceable and a wrongly-rejected recording cannot be recovered.

No score here is invented: every decision cites the measurement that
triggered it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from aarya_voice_lab.audio.analysis import AudioMeasurements
from aarya_voice_lab.audio.vad import VadResult


class QualityDecision(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    REVIEW = "REVIEW"
    FAIL = "FAIL"


#: Ordered worst-first for aggregation.
_SEVERITY_ORDER = (
    QualityDecision.FAIL,
    QualityDecision.REVIEW,
    QualityDecision.WARNING,
    QualityDecision.PASS,
)


@dataclass(frozen=True)
class QualityThresholds:
    """Every quality threshold, in one changeable place.

    Defaults chosen for *this* dataset: two speakers, mostly Marathi,
    plausibly recorded over a phone. They are intentionally lenient.
    """

    #: Heavy clipping destroys waveform detail that TTS training needs.
    max_clipping_ratio_fail: float = 0.05
    max_clipping_ratio_warning: float = 0.005
    #: Almost-all-silence recordings carry little usable speech.
    max_silent_frame_ratio_fail: float = 0.98
    max_silent_frame_ratio_review: float = 0.90
    #: Coarse SNR proxy; low values are flagged, never auto-rejected.
    min_estimated_snr_db_review: float = 6.0
    min_estimated_snr_db_warning: float = 12.0
    #: A recording with almost no detected activity needs a human look.
    min_speech_ratio_review: float = 0.05
    #: Total activity below this yields too little usable material.
    min_speech_seconds_review: float = 1.0
    #: A large DC offset indicates a capture-chain fault.
    max_dc_offset_warning: float = 0.05
    #: Recorded, never penalised: telephone-band audio is expected.
    telephone_band_sample_rate_hz: int = 16_000

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def config_hash(self) -> str:
        """Stable hash for resumability: changing a threshold invalidates
        cached results that were computed under the old value."""
        payload = json.dumps(self.to_dict(), sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass
class QualityFinding:
    code: str
    message: str
    decision: QualityDecision
    #: The measurement that produced this finding, for auditability.
    measured_value: float | None = None
    threshold: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "decision": self.decision.value,
            "measured_value": self.measured_value,
            "threshold": self.threshold,
        }


@dataclass
class QualityAssessment:
    source_file_id: str
    decision: QualityDecision
    findings: list[QualityFinding] = field(default_factory=list)
    measurements: dict[str, Any] = field(default_factory=dict)
    speech: dict[str, Any] = field(default_factory=dict)
    thresholds_hash: str = ""
    #: Characteristics recorded for later stages — not judgements.
    characteristics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file_id": self.source_file_id,
            "decision": self.decision.value,
            "findings": [f.to_dict() for f in self.findings],
            "measurements": self.measurements,
            "speech": self.speech,
            "thresholds_hash": self.thresholds_hash,
            "characteristics": list(self.characteristics),
        }


def _aggregate(decisions: list[QualityDecision]) -> QualityDecision:
    for candidate in _SEVERITY_ORDER:
        if candidate in decisions:
            return candidate
    return QualityDecision.PASS


def assess_quality(
    source_file_id: str,
    measurements: AudioMeasurements,
    vad: VadResult | None = None,
    *,
    thresholds: QualityThresholds | None = None,
) -> QualityAssessment:
    thresholds = thresholds or QualityThresholds()
    findings: list[QualityFinding] = []
    characteristics: list[str] = []

    def add(
        code: str,
        message: str,
        decision: QualityDecision,
        measured: float | None = None,
        threshold: float | None = None,
    ) -> None:
        findings.append(QualityFinding(code, message, decision, measured, threshold))

    # --- clipping ---------------------------------------------------------
    if measurements.clipping_ratio >= thresholds.max_clipping_ratio_fail:
        add(
            "severe_clipping",
            f"{measurements.clipping_ratio:.2%} of samples are clipped",
            QualityDecision.FAIL,
            measurements.clipping_ratio,
            thresholds.max_clipping_ratio_fail,
        )
    elif measurements.clipping_ratio >= thresholds.max_clipping_ratio_warning:
        add(
            "clipping",
            f"{measurements.clipping_ratio:.2%} of samples are clipped",
            QualityDecision.WARNING,
            measurements.clipping_ratio,
            thresholds.max_clipping_ratio_warning,
        )

    # --- silence ----------------------------------------------------------
    if measurements.silent_frame_ratio >= thresholds.max_silent_frame_ratio_fail:
        add(
            "almost_entirely_silent",
            f"{measurements.silent_frame_ratio:.1%} of frames are silent",
            QualityDecision.FAIL,
            measurements.silent_frame_ratio,
            thresholds.max_silent_frame_ratio_fail,
        )
    elif measurements.silent_frame_ratio >= thresholds.max_silent_frame_ratio_review:
        add(
            "mostly_silent",
            f"{measurements.silent_frame_ratio:.1%} of frames are silent",
            QualityDecision.REVIEW,
            measurements.silent_frame_ratio,
            thresholds.max_silent_frame_ratio_review,
        )

    # --- signal-to-noise (coarse proxy) -----------------------------------
    if measurements.estimated_snr_db is not None:
        if measurements.estimated_snr_db < thresholds.min_estimated_snr_db_review:
            add(
                "low_snr",
                f"estimated SNR {measurements.estimated_snr_db:.1f} dB is low; "
                "flagged for review rather than rejected",
                QualityDecision.REVIEW,
                measurements.estimated_snr_db,
                thresholds.min_estimated_snr_db_review,
            )
        elif measurements.estimated_snr_db < thresholds.min_estimated_snr_db_warning:
            add(
                "moderate_snr",
                f"estimated SNR {measurements.estimated_snr_db:.1f} dB is moderate",
                QualityDecision.WARNING,
                measurements.estimated_snr_db,
                thresholds.min_estimated_snr_db_warning,
            )

    # --- DC offset --------------------------------------------------------
    if abs(measurements.dc_offset) >= thresholds.max_dc_offset_warning:
        add(
            "dc_offset",
            f"DC offset {measurements.dc_offset:.3f} suggests a capture-chain fault",
            QualityDecision.WARNING,
            measurements.dc_offset,
            thresholds.max_dc_offset_warning,
        )

    # --- detected activity -------------------------------------------------
    speech_summary: dict[str, Any] = {}
    if vad is not None:
        speech_summary = {
            "speech_ratio": round(vad.speech_ratio, 6),
            "total_speech_seconds": round(vad.total_speech_seconds, 6),
            "speech_region_count": len(vad.speech_regions),
            "long_pause_count": len(vad.long_pauses()),
        }
        if vad.speech_ratio < thresholds.min_speech_ratio_review:
            add(
                "little_detected_activity",
                f"only {vad.speech_ratio:.1%} of the recording shows acoustic activity",
                QualityDecision.REVIEW,
                vad.speech_ratio,
                thresholds.min_speech_ratio_review,
            )
        if vad.total_speech_seconds < thresholds.min_speech_seconds_review:
            add(
                "insufficient_activity",
                f"only {vad.total_speech_seconds:.2f}s of activity detected",
                QualityDecision.REVIEW,
                vad.total_speech_seconds,
                thresholds.min_speech_seconds_review,
            )

    # --- characteristics: recorded, never penalised ------------------------
    if measurements.sample_rate and measurements.sample_rate < thresholds.telephone_band_sample_rate_hz:
        characteristics.append(
            f"narrowband_{measurements.sample_rate}hz "
            "(typical of telephone/call recordings; recorded, not penalised)"
        )
    if measurements.rms_dbfs is not None and measurements.rms_dbfs < -35:
        characteristics.append(f"low_level_{measurements.rms_dbfs:.1f}dbfs")
    if measurements.crest_factor_db is not None and measurements.crest_factor_db < 6:
        characteristics.append(
            f"compressed_dynamics_crest_{measurements.crest_factor_db:.1f}db "
            "(common in call recordings)"
        )

    return QualityAssessment(
        source_file_id=source_file_id,
        decision=_aggregate([f.decision for f in findings]),
        findings=findings,
        measurements=measurements.to_dict(),
        speech=speech_summary,
        thresholds_hash=thresholds.config_hash(),
        characteristics=characteristics,
    )
