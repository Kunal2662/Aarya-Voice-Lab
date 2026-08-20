"""Boundary and noise conditioning — VL-D4 §9, §10, §11, §12.

**Boundary conditioning** (leading/trailing silence trim + padding) has
no FFmpeg dependency at all: it only crops and pads existing PCM frames,
never resamples or re-encodes, so it works even on a machine without
FFmpeg (unlike `pipeline.normalization`, which genuinely needs it).
Detection reuses `audio.vad.detect_regions()` on the same mono-
downmixed samples every other VAD-driven stage already uses
(`audio.probe.read_wav_mono_samples`) — detection never needs the
original channel layout, only the write step does, which is why the
write step re-opens the source file directly with the stdlib `wave`
module (the same dependency-free tool `testing.synthetic_audio` and
`pipeline.normalization`'s own honesty pattern already use) rather than
going through the mono-downmix reader. Speech content itself is never
trimmed — only silence runs at least `BoundaryPolicy.min_trim_seconds`
long at the very start/end of the recording, never past the first/last
detected speech region (VL-D4 §10's "prioritize preservation of speech
content").

**Noise conditioning** is a decision, not an implementation, in VL-D4:
OFF and MEASURE_ONLY are real (MEASURE_ONLY reports that noise-floor/SNR
numbers already come from `audio.analysis.measure()` — nothing here
remeasures them); LIGHT and STANDARD are closed, named vocabulary
values with no noise-reduction tool behind them yet, and honestly report
NOT_AVAILABLE rather than being silently downgraded to MEASURE_ONLY or
pretending a pass occurred (VL-D4 §11: "If a noise-processing tool is
unavailable: show NOT AVAILABLE. Do not pretend processing occurred.").

**Telephone/narrowband audio is never treated as a defect here.**
Nothing in this module inspects sample rate to decide whether to trim or
condition more aggressively — that would silently re-introduce the
narrowband-as-invalid mistake `pipeline.quality` already rejected (VL-D4
§12).
"""

from __future__ import annotations

import wave
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from aarya_voice_lab.audio.vad import VadResult
from aarya_voice_lab.core.data_root import DataRoot, assert_source_writable
from aarya_voice_lab.pipeline.contracts import sha256_file
from aarya_voice_lab.pipeline.processing_profile import BoundaryPolicy, NoiseConditioningMode

CONDITIONING_VERSION = "1.0.0"


class ConditioningBlocked(RuntimeError):
    """Raised when boundary conditioning cannot proceed.

    Distinct from a failure: the input/policy is fine, something external
    (an unreadable file, an existing destination, a changed source)
    prevented the operation.
    """


@dataclass
class BoundaryConditioningRecord:
    """Provenance for one boundary-trim derived copy."""

    source_file_id: str
    source_path: str
    source_sha256: str
    output_path: str | None
    output_sha256: str | None
    leading_trim_seconds: float
    trailing_trim_seconds: float
    boundary_policy: dict[str, Any]
    conditioning_version: str = CONDITIONING_VERSION
    status: str = "completed"
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file_id": self.source_file_id,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "output_path": self.output_path,
            "output_sha256": self.output_sha256,
            "leading_trim_seconds": self.leading_trim_seconds,
            "trailing_trim_seconds": self.trailing_trim_seconds,
            "boundary_policy": self.boundary_policy,
            "conditioning_version": self.conditioning_version,
            "status": self.status,
            "note": self.note,
        }


def compute_boundary_trim(
    vad: VadResult,
    duration_seconds: float,
    policy: BoundaryPolicy,
) -> tuple[float, float]:
    """How much silence to cut from each edge.

    Never trims past the first/last detected speech region, and ignores
    an edge silence run shorter than `policy.min_trim_seconds` — a
    natural short pause before speech is left alone rather than stripped.
    """
    if not vad.speech_regions:
        return 0.0, 0.0

    leading = vad.speech_regions[0].start if policy.trim_leading_silence else 0.0
    trailing = (duration_seconds - vad.speech_regions[-1].end) if policy.trim_trailing_silence else 0.0
    leading = leading if leading >= policy.min_trim_seconds else 0.0
    trailing = trailing if trailing >= policy.min_trim_seconds else 0.0
    return leading, trailing


def condition_boundaries(
    source: Path,
    destination: Path,
    *,
    source_file_id: str,
    source_sha256: str,
    vad: VadResult,
    duration_seconds: float,
    data_root: DataRoot,
    policy: BoundaryPolicy | None = None,
) -> BoundaryConditioningRecord:
    """Write a boundary-trimmed copy of `source` to `destination`.

    Raises `ConditioningBlocked` for anything that stops the write
    (missing file, hash mismatch, existing destination, an unreadable/
    unwritable WAV) — the original is never touched either way.
    """
    policy = policy or BoundaryPolicy()

    # Hard guard: a path bug must never be able to write into source/.
    assert_source_writable(data_root, destination)

    if not source.is_file():
        raise FileNotFoundError(f"source not found: {source}")

    actual = sha256_file(source)
    if actual != source_sha256:
        raise ConditioningBlocked(
            f"Source hash mismatch for {source_file_id}: expected {source_sha256[:16]}…, "
            f"found {actual[:16]}…. Source recordings are immutable; processing stopped."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ConditioningBlocked(
            f"Destination already exists: {destination}. Refusing to overwrite a derived artifact."
        )

    leading, trailing = compute_boundary_trim(vad, duration_seconds, policy)

    try:
        with wave.open(str(source), "rb") as src:
            channels = src.getnchannels()
            width = src.getsampwidth()
            rate = src.getframerate()
            total_frames = src.getnframes()

            pad_frames = int(round(policy.pad_seconds * rate))
            start_frame = max(0, int(round(leading * rate)) - pad_frames)
            end_frame = min(total_frames, total_frames - int(round(trailing * rate)) + pad_frames)
            end_frame = max(start_frame, end_frame)

            src.setpos(start_frame)
            frame_count = end_frame - start_frame
            raw = src.readframes(frame_count) if frame_count > 0 else b""

        with wave.open(str(destination), "wb") as dst:
            dst.setnchannels(channels)
            dst.setsampwidth(width)
            dst.setframerate(rate)
            dst.writeframes(raw)
    except (wave.Error, OSError, EOFError) as exc:
        raise ConditioningBlocked(f"boundary conditioning failed: {exc}") from exc

    if sha256_file(source) != source_sha256:
        raise ConditioningBlocked(
            f"Source {source_file_id} changed during conditioning — this must never happen. "
            "Processing stopped for investigation."
        )

    return BoundaryConditioningRecord(
        source_file_id=source_file_id,
        source_path=source.name,
        source_sha256=source_sha256,
        output_path=destination.name,
        output_sha256=sha256_file(destination),
        leading_trim_seconds=round(leading, 6),
        trailing_trim_seconds=round(trailing, 6),
        boundary_policy=policy.to_dict(),
    )


class NoiseConditioningOutcome(StrEnum):
    NOT_APPLIED = "not_applied"
    MEASURED_ONLY = "measured_only"
    NOT_AVAILABLE = "not_available"


@dataclass(frozen=True)
class NoiseConditioningResult:
    mode: NoiseConditioningMode
    outcome: NoiseConditioningOutcome
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode.value, "outcome": self.outcome.value, "note": self.note}


def apply_noise_conditioning(mode: NoiseConditioningMode) -> NoiseConditioningResult:
    """Decide what (if anything) noise conditioning does for `mode`.

    Never alters audio itself — that remains `pipeline.normalization`'s
    and `condition_boundaries`'s job. This function only reports the
    honest outcome of the *decision* a profile's noise-conditioning mode
    represents.
    """
    if mode is NoiseConditioningMode.OFF:
        return NoiseConditioningResult(
            mode=mode, outcome=NoiseConditioningOutcome.NOT_APPLIED, note="Noise conditioning disabled by profile."
        )
    if mode is NoiseConditioningMode.MEASURE_ONLY:
        return NoiseConditioningResult(
            mode=mode,
            outcome=NoiseConditioningOutcome.MEASURED_ONLY,
            note="Noise floor and estimated SNR are already reported by quality measurements; audio is unchanged.",
        )
    # LIGHT / STANDARD: real, named vocabulary values with no tool behind
    # them yet in VL-D4 — honestly unavailable, never silently downgraded.
    return NoiseConditioningResult(
        mode=mode,
        outcome=NoiseConditioningOutcome.NOT_AVAILABLE,
        note=(
            f"NOT AVAILABLE — no noise-reduction tool is wired up for {mode.value} conditioning in VL-D4. "
            "Audio is unchanged."
        ),
    )
