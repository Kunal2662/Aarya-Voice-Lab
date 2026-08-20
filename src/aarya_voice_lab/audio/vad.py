"""Speech / silence region detection.

Energy-based voice activity detection over stdlib-decoded PCM: no numpy,
no model download, no GPU, and no network. It detects *activity*, not
speech content and certainly not speaker identity.

Design intent — the goal is useful candidate segments, not maximal
chopping:

* Silence must persist for `min_silence_seconds` before it splits a
  region, so natural pauses inside a sentence survive.
* Detected speech shorter than `min_speech_seconds` is discarded as a
  click or breath rather than kept as a fragment.
* Region edges are padded outward, because energy-based onset detection
  clips quiet consonants at word boundaries.

A more accurate neural VAD can replace this later; the region interface
is what stages depend on, not the detector.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aarya_voice_lab.audio.analysis import DEFAULT_FRAME_MS, FrameEnergy, compute_frames


@dataclass(frozen=True)
class VadConfig:
    """Thresholds for activity detection.

    Defaults are permissive on purpose. `silence_rms_threshold` sits low
    enough that quiet telephone-band speech still registers as activity —
    a stricter value would classify a whole call recording as silence.
    """

    #: Frames below this RMS (0..1) count as silence.
    silence_rms_threshold: float = 0.005
    #: Silence must last this long to split speech. Shorter gaps are
    #: natural pauses and are kept inside the region.
    min_silence_seconds: float = 0.30
    #: Activity shorter than this is discarded as a transient.
    min_speech_seconds: float = 0.20
    #: Padding added at each edge to avoid clipping soft onsets.
    speech_padding_seconds: float = 0.10
    frame_ms: float = DEFAULT_FRAME_MS

    def to_dict(self) -> dict[str, Any]:
        return {
            "silence_rms_threshold": self.silence_rms_threshold,
            "min_silence_seconds": self.min_silence_seconds,
            "min_speech_seconds": self.min_speech_seconds,
            "speech_padding_seconds": self.speech_padding_seconds,
            "frame_ms": self.frame_ms,
        }


@dataclass(frozen=True)
class Region:
    """A time span classified as speech or silence.

    'speech' means *acoustic activity*. It carries no claim about who is
    speaking, or whether it is speech at all versus other sound.
    """

    start: float
    end: float
    is_speech: bool

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": round(self.start, 6),
            "end": round(self.end, 6),
            "duration": round(self.duration, 6),
            "kind": "speech" if self.is_speech else "silence",
        }


@dataclass
class VadResult:
    regions: list[Region]
    config: VadConfig
    total_duration: float

    @property
    def speech_regions(self) -> list[Region]:
        return [r for r in self.regions if r.is_speech]

    @property
    def silence_regions(self) -> list[Region]:
        return [r for r in self.regions if not r.is_speech]

    @property
    def total_speech_seconds(self) -> float:
        return sum(r.duration for r in self.speech_regions)

    @property
    def total_silence_seconds(self) -> float:
        return sum(r.duration for r in self.silence_regions)

    @property
    def speech_ratio(self) -> float:
        return self.total_speech_seconds / self.total_duration if self.total_duration else 0.0

    def long_pauses(self, threshold: float = 2.0) -> list[Region]:
        return [r for r in self.silence_regions if r.duration >= threshold]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_duration": round(self.total_duration, 6),
            "total_speech_seconds": round(self.total_speech_seconds, 6),
            "total_silence_seconds": round(self.total_silence_seconds, 6),
            "speech_ratio": round(self.speech_ratio, 6),
            "speech_region_count": len(self.speech_regions),
            "silence_region_count": len(self.silence_regions),
            "long_pause_count": len(self.long_pauses()),
            "config": self.config.to_dict(),
            "regions": [r.to_dict() for r in self.regions],
        }


def _merge_frames_into_regions(frames: list[FrameEnergy], config: VadConfig) -> list[Region]:
    """Collapse per-frame decisions into runs, then apply the duration rules."""
    if not frames:
        return []

    runs: list[tuple[float, float, bool]] = []
    current_active = frames[0].rms >= config.silence_rms_threshold
    run_start = frames[0].start_seconds
    for frame in frames:
        active = frame.rms >= config.silence_rms_threshold
        if active != current_active:
            runs.append((run_start, frame.start_seconds, current_active))
            run_start = frame.start_seconds
            current_active = active
    runs.append((run_start, frames[-1].end_seconds, current_active))

    # A short silence between two speech runs is a natural pause: absorb it.
    absorbed: list[tuple[float, float, bool]] = []
    for start, end, active in runs:
        if (
            not active
            and absorbed
            and absorbed[-1][2]
            and (end - start) < config.min_silence_seconds
        ):
            absorbed[-1] = (absorbed[-1][0], end, True)
        elif absorbed and absorbed[-1][2] == active:
            absorbed[-1] = (absorbed[-1][0], end, active)
        else:
            absorbed.append((start, end, active))

    # Drop transient activity, converting it to silence.
    cleaned: list[tuple[float, float, bool]] = []
    for start, end, active in absorbed:
        if active and (end - start) < config.min_speech_seconds:
            active = False
        if cleaned and cleaned[-1][2] == active:
            cleaned[-1] = (cleaned[-1][0], end, active)
        else:
            cleaned.append((start, end, active))

    return [Region(start=s, end=e, is_speech=a) for s, e, a in cleaned]


def _pad_speech_regions(regions: list[Region], config: VadConfig, total_duration: float) -> list[Region]:
    """Extend speech edges outward without overlapping neighbours."""
    if not config.speech_padding_seconds:
        return regions
    padded = []
    for index, region in enumerate(regions):
        if not region.is_speech:
            padded.append(region)
            continue
        previous_end = regions[index - 1].start if index > 0 else 0.0
        next_start = regions[index + 1].end if index + 1 < len(regions) else total_duration
        start = max(region.start - config.speech_padding_seconds, previous_end, 0.0)
        end = min(region.end + config.speech_padding_seconds, next_start, total_duration)
        padded.append(Region(start=start, end=max(end, start), is_speech=True))
    return padded


def detect_regions(
    samples: list[int],
    sample_rate: int,
    *,
    bit_depth: int = 16,
    config: VadConfig | None = None,
) -> VadResult:
    config = config or VadConfig()
    total_duration = len(samples) / sample_rate if sample_rate else 0.0
    if not samples or sample_rate <= 0:
        return VadResult(regions=[], config=config, total_duration=total_duration)

    max_amplitude = 2 ** (bit_depth - 1) - 1
    frames = compute_frames(samples, sample_rate, max_amplitude, frame_ms=config.frame_ms)
    regions = _merge_frames_into_regions(frames, config)
    regions = _pad_speech_regions(regions, config, total_duration)
    return VadResult(regions=regions, config=config, total_duration=total_duration)
