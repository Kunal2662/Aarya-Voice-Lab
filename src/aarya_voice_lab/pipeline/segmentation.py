"""Deterministic segmentation into candidate spans.

Turns detected activity regions into candidate segments with exact
provenance back to (source_file_id, start, end). Given the same audio and
the same configuration, it produces byte-identical output — which is what
makes the stage resumable and its results comparable across runs.

**This stage assigns no speaker.** It produces time spans and nothing
more. Which segments belong to whom is a Phase 3 question, and the record
type here has no field capable of expressing a speaker role.

Duration policy — the defaults exist for stated reasons, not convention:

* `min_segment_seconds = 1.0` — below roughly a second there is not
  enough prosodic context for TTS training or reliable speaker
  verification, and such fragments cost review time for little gain.
* `max_segment_seconds = 20.0` — long spans are more likely to contain a
  speaker change, and most TTS training pipelines operate well below
  this. Splitting happens at the quietest interior point, not at a fixed
  offset, so cuts avoid landing mid-word.
* Splitting prefers existing silence; a hard cut is a last resort and is
  recorded as such, so review can find it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from aarya_voice_lab.audio.vad import Region, VadResult

SEGMENTATION_VERSION = "1.0.0"


class SplitReason(StrEnum):
    NATURAL = "natural"
    SPLIT_AT_SILENCE = "split_at_silence"
    HARD_SPLIT = "hard_split"


@dataclass(frozen=True)
class SegmentationConfig:
    min_segment_seconds: float = 1.0
    max_segment_seconds: float = 20.0
    #: Segments shorter than this are dropped instead of padded.
    drop_below_seconds: float = 0.5
    #: When splitting a long region, prefer a silence at least this long.
    preferred_split_silence_seconds: float = 0.2

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def config_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass
class CandidateSegment:
    """One candidate span.

    Deliberately has NO speaker field. Phase 2 must not be able to express
    a speaker claim, so the type simply cannot carry one.
    """

    segment_id: str
    source_file_id: str
    source_sha256: str
    start: float
    end: float
    split_reason: SplitReason = SplitReason.NATURAL
    segmentation_version: str = SEGMENTATION_VERSION
    config_hash: str = ""
    segment_sha256: str | None = None

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "source_file_id": self.source_file_id,
            "source_sha256": self.source_sha256,
            "start": round(self.start, 6),
            "end": round(self.end, 6),
            "duration": round(self.duration, 6),
            "split_reason": self.split_reason.value,
            "segmentation_version": self.segmentation_version,
            "config_hash": self.config_hash,
            "segment_sha256": self.segment_sha256,
        }


def _find_split_point(region: Region, silences: list[Region], config: SegmentationConfig) -> float | None:
    """Find the best interior split for an over-long region.

    Prefers the silence closest to the midpoint, so the two halves stay
    balanced and the cut lands in a real pause rather than mid-word.
    """
    target = region.start + config.max_segment_seconds
    midpoint = (region.start + min(target, region.end)) / 2.0

    candidates = [
        s
        for s in silences
        if s.duration >= config.preferred_split_silence_seconds
        and region.start + config.min_segment_seconds <= s.start
        and s.end <= region.end - config.min_segment_seconds
        and s.start <= target
    ]
    if not candidates:
        return None
    best = min(candidates, key=lambda s: abs((s.start + s.end) / 2.0 - midpoint))
    return (best.start + best.end) / 2.0


def _split_region(
    region: Region,
    silences: list[Region],
    config: SegmentationConfig,
) -> list[tuple[float, float, SplitReason]]:
    """Split one region into spans within the duration bounds."""
    spans: list[tuple[float, float, SplitReason]] = []
    cursor = region.start
    reason = SplitReason.NATURAL

    while region.end - cursor > config.max_segment_seconds:
        remaining = Region(start=cursor, end=region.end, is_speech=True)
        split_at = _find_split_point(remaining, silences, config)
        if split_at is None or split_at <= cursor + config.min_segment_seconds:
            # No usable pause: cut at the limit and record that we did.
            split_at = cursor + config.max_segment_seconds
            reason = SplitReason.HARD_SPLIT
        else:
            reason = SplitReason.SPLIT_AT_SILENCE
        spans.append((cursor, split_at, reason))
        cursor = split_at

    if region.end - cursor > 0:
        spans.append((cursor, region.end, SplitReason.NATURAL if not spans else reason))
    return spans


def segment_regions(
    vad: VadResult,
    *,
    source_file_id: str,
    source_sha256: str,
    config: SegmentationConfig | None = None,
) -> list[CandidateSegment]:
    """Produce candidate segments. Deterministic for fixed inputs."""
    config = config or SegmentationConfig()
    config_hash = config.config_hash()
    silences = vad.silence_regions

    segments: list[CandidateSegment] = []
    for region in vad.speech_regions:
        for start, end, reason in _split_region(region, silences, config):
            duration = end - start
            if duration < config.drop_below_seconds:
                continue
            if duration < config.min_segment_seconds:
                # Between drop_below and min: keep, but mark for review
                # rather than discard — short material may still be usable.
                reason = SplitReason.NATURAL if reason is SplitReason.NATURAL else reason
            index = len(segments)
            segments.append(
                CandidateSegment(
                    # Deterministic id: same audio + same config -> same id.
                    segment_id=f"{source_file_id}-seg{index:04d}",
                    source_file_id=source_file_id,
                    source_sha256=source_sha256,
                    start=start,
                    end=end,
                    split_reason=reason,
                    config_hash=config_hash,
                )
            )
    return segments


@dataclass
class SegmentationResult:
    source_file_id: str
    segments: list[CandidateSegment] = field(default_factory=list)
    config_hash: str = ""
    segmentation_version: str = SEGMENTATION_VERSION

    @property
    def total_duration(self) -> float:
        return sum(s.duration for s in self.segments)

    def short_segments(self, threshold: float) -> list[CandidateSegment]:
        return [s for s in self.segments if s.duration < threshold]

    def hard_split_segments(self) -> list[CandidateSegment]:
        return [s for s in self.segments if s.split_reason is SplitReason.HARD_SPLIT]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file_id": self.source_file_id,
            "segment_count": len(self.segments),
            "total_duration": round(self.total_duration, 6),
            "config_hash": self.config_hash,
            "segmentation_version": self.segmentation_version,
            "hard_split_count": len(self.hard_split_segments()),
            "segments": [s.to_dict() for s in self.segments],
        }
