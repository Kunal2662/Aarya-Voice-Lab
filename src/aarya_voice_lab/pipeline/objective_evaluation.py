"""Objective, automated evaluation metrics for generated/trained voice
outputs.

This module measures only what can be computed mechanically from an
audio file or a timed operation: duration, sample rate, clipping,
silence ratio, audio validity, latency, real-time factor, and process
memory where available. Field names match `schemas/benchmark.schema.json`'s
`metrics` block (`latency_ms`, `real_time_factor`, `cpu_memory_mb`) so a
result from this module can be written into a benchmark record without
renaming.

Task 5 of the autonomous execution plan. This module deliberately does
**not** compute:

- subjective quality scores (naturalness, prosody, language quality) --
  those are human judgements; see `pipeline.evaluation` /
  `pipeline.evaluation_aggregation` (VL-D6/D7/D8), which already
  implement the schema and process for real human evaluation. Nothing
  here fabricates a human score.
- `speaker_similarity` -- that requires a real embedding provider and
  belongs to `identity.embeddings` / `docs/PHASE3_IDENTITY.md`, not
  here.

Objective metrics, human evaluation, and speaker-verification metrics
are kept in three separate modules on purpose, mirroring
`docs/DATA_POLICY.md`'s "never mix tracks" discipline applied to
evaluation instead of data.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from aarya_voice_lab.audio.analysis import measure
from aarya_voice_lab.audio.probe import AudioReadError, read_wav_mono_samples

T = TypeVar("T")


@dataclass(frozen=True)
class ObjectiveAudioMetrics:
    """Real, measured properties of one audio file.

    `is_valid=False` means the file could not be read/decoded -- every
    other field is None in that case, never a fabricated placeholder.
    """

    is_valid: bool
    duration_seconds: float | None = None
    sample_rate: int | None = None
    clipping_ratio: float | None = None
    silent_frame_ratio: float | None = None
    peak_dbfs: float | None = None
    rms_dbfs: float | None = None
    read_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "duration_seconds": self.duration_seconds,
            "sample_rate": self.sample_rate,
            "clipping_ratio": self.clipping_ratio,
            "silent_frame_ratio": self.silent_frame_ratio,
            "peak_dbfs": self.peak_dbfs,
            "rms_dbfs": self.rms_dbfs,
            "read_error": self.read_error,
        }


def measure_objective_audio_metrics(path: Path) -> ObjectiveAudioMetrics:
    """Read and measure one WAV file.

    Never raises on an invalid file -- reports `is_valid=False` with the
    real error message instead, since a batch evaluation over many
    outputs must not abort on the first bad one.
    """
    try:
        samples, sample_rate = read_wav_mono_samples(path)
    except (AudioReadError, OSError) as exc:
        return ObjectiveAudioMetrics(is_valid=False, read_error=str(exc))
    if not samples:
        return ObjectiveAudioMetrics(is_valid=False, read_error="no decodable samples")
    result = measure(samples, sample_rate)
    return ObjectiveAudioMetrics(
        is_valid=True,
        duration_seconds=result.duration_seconds,
        sample_rate=result.sample_rate,
        clipping_ratio=result.clipping_ratio,
        silent_frame_ratio=result.silent_frame_ratio,
        peak_dbfs=result.peak_dbfs,
        rms_dbfs=result.rms_dbfs,
    )


@dataclass(frozen=True)
class TimedResult:
    """Wall-clock elapsed time for one operation -- real, measured,
    never estimated."""

    elapsed_seconds: float
    latency_ms: float


def measure_latency(fn: Callable[[], T]) -> tuple[T, TimedResult]:
    """Run `fn` once and measure its real wall-clock latency.

    Used for model-load-time and inference-latency measurement alike --
    the caller decides what `fn` does; this function only times it.
    """
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    return result, TimedResult(elapsed_seconds=elapsed, latency_ms=elapsed * 1000.0)


def real_time_factor(processing_seconds: float, audio_duration_seconds: float) -> float | None:
    """processing_time / audio_duration.

    None when `audio_duration_seconds` is not positive -- undefined,
    never reported as 0.0 or infinity.
    """
    if audio_duration_seconds <= 0:
        return None
    return processing_seconds / audio_duration_seconds


def current_process_memory_mb() -> float | None:
    """Real RSS memory of the current process via psutil, in MB.

    None if psutil is unavailable -- never a fabricated number. GPU
    memory is intentionally not measured here: proving GPU residency
    requires a real GPU-resident ML process, which this project does not
    have in any environment it runs in (see docs/GPU_STRATEGY.md);
    inventing a number would misrepresent that.
    """
    try:
        import psutil

        return psutil.Process().memory_info().rss / (1024 * 1024)
    except ImportError:
        return None
