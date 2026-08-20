"""Overlap *candidate* detection.

Flags segments that may contain more than one person talking at once, so
Phase 3 knows where to look. It does not decide who is speaking, does not
count speakers, and does not resolve overlap — those require diarization
and speaker verification, which belong to Phase 3.

Method: acoustic heuristics over stdlib-decoded PCM — no model, no
download, no network. Simultaneous speech tends to raise spectral
complexity and destabilise the zero-crossing rate versus a single voice.
These are **weak indicators**, and the module says so in its own output:
the confidence value is a heuristic score, not a probability.

The conservative rule that matters: a segment the detector cannot judge
is `UNKNOWN`, never `NO_OVERLAP_DETECTED`. UNKNOWN never becomes
eligible automatically — Phase 3 must resolve it.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from aarya_voice_lab.audio.analysis import compute_frames

OVERLAP_DETECTOR_NAME = "energy-zcr-heuristic"
OVERLAP_DETECTOR_VERSION = "1.0.0"


class OverlapStatus(StrEnum):
    NO_OVERLAP_DETECTED = "NO_OVERLAP_DETECTED"
    POSSIBLE_OVERLAP = "POSSIBLE_OVERLAP"
    OVERLAP_DETECTED = "OVERLAP_DETECTED"
    UNKNOWN = "UNKNOWN"


#: Statuses that must not be treated as clear in later stages.
NON_CLEAR_STATUSES: frozenset[OverlapStatus] = frozenset(
    {OverlapStatus.POSSIBLE_OVERLAP, OverlapStatus.OVERLAP_DETECTED, OverlapStatus.UNKNOWN}
)


@dataclass(frozen=True)
class OverlapConfig:
    #: Below this many frames the heuristics are meaningless -> UNKNOWN.
    min_frames_for_decision: int = 15
    #: ZCR variability above this suggests competing periodicities.
    zcr_instability_possible: float = 0.35
    zcr_instability_detected: float = 0.55
    #: Sustained high energy with unstable ZCR strengthens the signal.
    energy_stability_threshold: float = 0.25

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def config_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass
class OverlapAssessment:
    segment_id: str
    status: OverlapStatus
    #: Heuristic score in 0..1. NOT a probability. None when undecidable.
    confidence: float | None
    detection_method: str = OVERLAP_DETECTOR_NAME
    detector_version: str = OVERLAP_DETECTOR_VERSION
    config_hash: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    note: str | None = None

    @property
    def requires_phase3_resolution(self) -> bool:
        return self.status in NON_CLEAR_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "overlap_status": self.status.value,
            "overlap_confidence": self.confidence,
            "detection_method": self.detection_method,
            "detector_version": self.detector_version,
            "config_hash": self.config_hash,
            "evidence": self.evidence,
            "note": self.note,
        }


def _zcr_per_frame(samples: list[int], sample_rate: int, frame_length: int) -> list[float]:
    rates = []
    for start in range(0, len(samples), frame_length):
        window = samples[start : start + frame_length]
        if len(window) < 2:
            continue
        crossings = 0
        previous = (window[0] > 0) - (window[0] < 0)
        for sample in window[1:]:
            sign = (sample > 0) - (sample < 0)
            if sign and previous and sign != previous:
                crossings += 1
            if sign:
                previous = sign
        rates.append(crossings / len(window))
    return rates


def assess_overlap(
    segment_id: str,
    samples: list[int],
    sample_rate: int,
    *,
    bit_depth: int = 16,
    config: OverlapConfig | None = None,
) -> OverlapAssessment:
    """Assess one segment for possible overlapping speech."""
    config = config or OverlapConfig()
    config_hash = config.config_hash()

    if not samples or sample_rate <= 0:
        return OverlapAssessment(
            segment_id=segment_id,
            status=OverlapStatus.UNKNOWN,
            confidence=None,
            config_hash=config_hash,
            note="no audio available to assess",
        )

    max_amplitude = 2 ** (bit_depth - 1) - 1
    frames = compute_frames(samples, sample_rate, max_amplitude)
    frame_length = max(int(sample_rate * 0.02), 1)
    zcrs = _zcr_per_frame(samples, sample_rate, frame_length)

    if len(frames) < config.min_frames_for_decision or len(zcrs) < config.min_frames_for_decision:
        return OverlapAssessment(
            segment_id=segment_id,
            status=OverlapStatus.UNKNOWN,
            confidence=None,
            config_hash=config_hash,
            evidence={"frame_count": len(frames), "zcr_count": len(zcrs)},
            note=(
                "segment too short for the heuristic to say anything; "
                "UNKNOWN rather than assumed clear"
            ),
        )

    mean_zcr = statistics.fmean(zcrs)
    zcr_instability = (statistics.pstdev(zcrs) / mean_zcr) if mean_zcr > 0 else 0.0

    energies = [f.rms for f in frames]
    mean_energy = statistics.fmean(energies)
    energy_stability = (statistics.pstdev(energies) / mean_energy) if mean_energy > 0 else 0.0

    evidence = {
        "zcr_instability": round(zcr_instability, 6),
        "energy_stability": round(energy_stability, 6),
        "mean_zcr": round(mean_zcr, 6),
        "mean_rms": round(mean_energy, 6),
        "frame_count": len(frames),
    }

    if zcr_instability >= config.zcr_instability_detected:
        status = OverlapStatus.OVERLAP_DETECTED
        confidence = min(zcr_instability, 1.0)
    elif zcr_instability >= config.zcr_instability_possible:
        status = OverlapStatus.POSSIBLE_OVERLAP
        confidence = min(zcr_instability, 1.0)
    else:
        status = OverlapStatus.NO_OVERLAP_DETECTED
        confidence = max(0.0, 1.0 - zcr_instability)

    return OverlapAssessment(
        segment_id=segment_id,
        status=status,
        confidence=round(confidence, 6),
        config_hash=config_hash,
        evidence=evidence,
        note=(
            "heuristic acoustic indicator only; not a speaker count and not a "
            "probability. Phase 3 makes the authoritative determination."
        ),
    )
