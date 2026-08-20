"""Raw audio measurements.

This module **only measures**. It contains no thresholds, no pass/fail
logic, and no notion of what "good" audio is. Decisions live in
`pipeline.quality`, driven by configuration.

That separation is deliberate and required by the Phase 2 brief: the
source material is expected to include telephone/call recordings, which
are band-limited and quiet by nature. If measurement and judgement were
entangled, "sounds like a phone call" would silently become "bad audio",
and the dataset would be discarded by its own pipeline.

Pure-Python over stdlib-decoded PCM, so it runs on CPU with no numpy,
no FFmpeg, and no GPU.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

#: Analysis window. 20 ms is the usual speech-processing frame: long
#: enough for a stable energy estimate, short enough to catch pauses.
DEFAULT_FRAME_MS = 20.0


@dataclass(frozen=True)
class FrameEnergy:
    """Per-frame energy, the basis of every measurement below."""

    frame_index: int
    start_seconds: float
    end_seconds: float
    rms: float
    peak: float


@dataclass
class AudioMeasurements:
    """Raw, judgement-free measurements for one audio signal."""

    duration_seconds: float
    sample_rate: int
    sample_count: int
    peak_amplitude: float = 0.0
    rms_amplitude: float = 0.0
    peak_dbfs: float | None = None
    rms_dbfs: float | None = None
    crest_factor_db: float | None = None
    clipped_sample_count: int = 0
    clipping_ratio: float = 0.0
    dc_offset: float = 0.0
    zero_crossing_rate: float = 0.0
    #: Estimated noise floor from the quietest frames.
    noise_floor_dbfs: float | None = None
    #: Difference between speech-level and noise-floor frames.
    estimated_snr_db: float | None = None
    silent_frame_ratio: float = 0.0
    frames: list[FrameEnergy] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """Serialisable form. Per-frame data is excluded — it is large and
        reconstructible from the audio."""
        return {
            "duration_seconds": round(self.duration_seconds, 6),
            "sample_rate": self.sample_rate,
            "sample_count": self.sample_count,
            "peak_amplitude": round(self.peak_amplitude, 6),
            "rms_amplitude": round(self.rms_amplitude, 6),
            "peak_dbfs": _round_or_none(self.peak_dbfs),
            "rms_dbfs": _round_or_none(self.rms_dbfs),
            "crest_factor_db": _round_or_none(self.crest_factor_db),
            "clipped_sample_count": self.clipped_sample_count,
            "clipping_ratio": round(self.clipping_ratio, 8),
            "dc_offset": round(self.dc_offset, 6),
            "zero_crossing_rate": round(self.zero_crossing_rate, 6),
            "noise_floor_dbfs": _round_or_none(self.noise_floor_dbfs),
            "estimated_snr_db": _round_or_none(self.estimated_snr_db),
            "silent_frame_ratio": round(self.silent_frame_ratio, 6),
            "frame_count": len(self.frames),
        }


def _round_or_none(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


def _to_dbfs(amplitude: float) -> float | None:
    """Amplitude (0..1) to dBFS. Silence has no dB value, so returns None."""
    if amplitude <= 0:
        return None
    return 20.0 * math.log10(amplitude)


def compute_frames(
    samples: list[int],
    sample_rate: int,
    max_amplitude: int,
    *,
    frame_ms: float = DEFAULT_FRAME_MS,
) -> list[FrameEnergy]:
    if not samples or sample_rate <= 0:
        return []
    frame_length = max(int(sample_rate * frame_ms / 1000.0), 1)
    frames = []
    for index, start in enumerate(range(0, len(samples), frame_length)):
        window = samples[start : start + frame_length]
        if not window:
            continue
        total = 0.0
        peak = 0.0
        for sample in window:
            normalized = sample / max_amplitude
            total += normalized * normalized
            peak = max(peak, abs(normalized))
        frames.append(
            FrameEnergy(
                frame_index=index,
                start_seconds=start / sample_rate,
                end_seconds=min((start + len(window)) / sample_rate, len(samples) / sample_rate),
                rms=math.sqrt(total / len(window)),
                peak=peak,
            )
        )
    return frames


def measure(
    samples: list[int],
    sample_rate: int,
    *,
    bit_depth: int = 16,
    frame_ms: float = DEFAULT_FRAME_MS,
    silence_rms_threshold: float = 0.001,
) -> AudioMeasurements:
    """Measure a mono PCM signal. No judgements, only numbers."""
    max_amplitude = 2 ** (bit_depth - 1) - 1
    sample_count = len(samples)
    duration = sample_count / sample_rate if sample_rate else 0.0

    measurements = AudioMeasurements(
        duration_seconds=duration,
        sample_rate=sample_rate,
        sample_count=sample_count,
    )
    if not samples or sample_rate <= 0:
        return measurements

    total_square = 0.0
    total = 0.0
    peak = 0
    clipped = 0
    zero_crossings = 0
    previous_sign = 0
    # A sample at (or within one step of) full scale is treated as clipped.
    clip_threshold = max_amplitude - 1

    for sample in samples:
        magnitude = abs(sample)
        if magnitude > peak:
            peak = magnitude
        if magnitude >= clip_threshold:
            clipped += 1
        normalized = sample / max_amplitude
        total_square += normalized * normalized
        total += normalized
        sign = (sample > 0) - (sample < 0)
        if sign and previous_sign and sign != previous_sign:
            zero_crossings += 1
        if sign:
            previous_sign = sign

    measurements.peak_amplitude = peak / max_amplitude
    measurements.rms_amplitude = math.sqrt(total_square / sample_count)
    measurements.peak_dbfs = _to_dbfs(measurements.peak_amplitude)
    measurements.rms_dbfs = _to_dbfs(measurements.rms_amplitude)
    if measurements.peak_dbfs is not None and measurements.rms_dbfs is not None:
        measurements.crest_factor_db = measurements.peak_dbfs - measurements.rms_dbfs
    measurements.clipped_sample_count = clipped
    measurements.clipping_ratio = clipped / sample_count
    measurements.dc_offset = total / sample_count
    measurements.zero_crossing_rate = zero_crossings / sample_count

    frames = compute_frames(samples, sample_rate, max_amplitude, frame_ms=frame_ms)
    measurements.frames = frames
    if frames:
        measurements.silent_frame_ratio = sum(1 for f in frames if f.rms < silence_rms_threshold) / len(frames)
        measurements.noise_floor_dbfs, measurements.estimated_snr_db = _estimate_snr(frames)
    return measurements


def _estimate_snr(frames: list[FrameEnergy]) -> tuple[float | None, float | None]:
    """Estimate noise floor and SNR from the frame energy distribution.

    Uses the 10th percentile as noise and the 90th as signal. This is a
    coarse proxy, not a calibrated SNR: it assumes the recording contains
    both quiet and loud passages. Reported so later stages can compare
    recordings, never as ground truth.
    """
    levels = sorted(f.rms for f in frames)
    if len(levels) < 10:
        return None, None
    noise = levels[len(levels) // 10]
    signal = levels[(len(levels) * 9) // 10]
    noise_db = _to_dbfs(noise)
    signal_db = _to_dbfs(signal)
    if noise_db is None or signal_db is None:
        return noise_db, None
    return noise_db, signal_db - noise_db
