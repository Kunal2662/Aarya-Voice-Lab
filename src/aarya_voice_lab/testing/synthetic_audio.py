"""Generate synthetic test audio.

Every sample produced here is a mathematically generated waveform — sine
tones, silence, and deterministic pseudo-noise. It contains no speech, no
recording of any person, and nothing derived from the private source
material. This is the ONLY audio this project is permitted to create
before an approved dataset phase.

Uses the stdlib `wave` module so the base environment needs no audio
dependencies (no numpy, no soundfile, no FFmpeg).

Generated files are written to caller-chosen locations — normally a pytest
tmp_path. They must never be committed: the root .gitignore blocks *.wav,
and a test asserts that it does.
"""

from __future__ import annotations

import math
import struct
import wave
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SAMPLE_RATE = 16_000
_INT16_MAX = 32767


@dataclass(frozen=True)
class SyntheticSpeaker:
    """A stand-in for a speaker: a distinct tone, not a voice.

    Used to exercise multi-speaker plumbing (segment boundaries, speaker
    labels, overlap handling) without any real speech. Two different
    frequencies are trivially separable, which is what makes them useful
    for testing pipeline mechanics — they are NOT a substitute for real
    diarization evaluation.
    """

    label: str
    frequency_hz: float


SPEAKER_A = SyntheticSpeaker(label="synthetic_speaker_a", frequency_hz=220.0)
SPEAKER_B = SyntheticSpeaker(label="synthetic_speaker_b", frequency_hz=440.0)


def _sine_samples(frequency: float, duration: float, sample_rate: int, amplitude: float) -> list[int]:
    count = int(duration * sample_rate)
    return [
        int(amplitude * _INT16_MAX * math.sin(2.0 * math.pi * frequency * (i / sample_rate)))
        for i in range(count)
    ]


def _silence_samples(duration: float, sample_rate: int) -> list[int]:
    return [0] * int(duration * sample_rate)


def write_wav(path: Path, samples: list[int], sample_rate: int = DEFAULT_SAMPLE_RATE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(sample_rate)
        fh.writeframes(b"".join(struct.pack("<h", _clamp(s)) for s in samples))
    return path


def _clamp(sample: int) -> int:
    return max(-_INT16_MAX, min(_INT16_MAX, sample))


def generate_tone(
    path: Path,
    *,
    frequency_hz: float = 440.0,
    duration_seconds: float = 1.0,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    amplitude: float = 0.5,
) -> Path:
    """Write a single-tone WAV. Smallest useful fixture."""
    return write_wav(path, _sine_samples(frequency_hz, duration_seconds, sample_rate, amplitude), sample_rate)


def generate_silence(path: Path, *, duration_seconds: float = 1.0, sample_rate: int = DEFAULT_SAMPLE_RATE) -> Path:
    return write_wav(path, _silence_samples(duration_seconds, sample_rate), sample_rate)


@dataclass(frozen=True)
class SyntheticTurn:
    """One labelled span in a generated multi-speaker file."""

    speaker: str
    start: float
    end: float
    overlapping: bool = False


def generate_two_speaker_file(
    path: Path,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    include_overlap: bool = True,
) -> tuple[Path, list[SyntheticTurn]]:
    """Write a synthetic file with two 'speakers', silence, and optional overlap.

    Returns the path plus ground-truth turns, so a test can assert that a
    stage produced the segmentation it should have — without needing a
    real diarizer or any real audio.
    """
    segments: list[int] = []
    turns: list[SyntheticTurn] = []
    cursor = 0.0

    def append(samples: list[int], duration: float, speaker: str | None, overlapping: bool = False) -> None:
        nonlocal cursor
        segments.extend(samples)
        if speaker is not None:
            turns.append(SyntheticTurn(speaker=speaker, start=cursor, end=cursor + duration, overlapping=overlapping))
        cursor += duration

    append(_sine_samples(SPEAKER_A.frequency_hz, 1.0, sample_rate, 0.5), 1.0, SPEAKER_A.label)
    append(_silence_samples(0.25, sample_rate), 0.25, None)
    append(_sine_samples(SPEAKER_B.frequency_hz, 1.0, sample_rate, 0.5), 1.0, SPEAKER_B.label)

    if include_overlap:
        append(_silence_samples(0.25, sample_rate), 0.25, None)
        mixed_a = _sine_samples(SPEAKER_A.frequency_hz, 0.75, sample_rate, 0.35)
        mixed_b = _sine_samples(SPEAKER_B.frequency_hz, 0.75, sample_rate, 0.35)
        mixed = [a + b for a, b in zip(mixed_a, mixed_b, strict=True)]
        # Both speakers are recorded for the same span: this is the case the
        # safety policy must reject by default.
        turns.append(SyntheticTurn(SPEAKER_A.label, cursor, cursor + 0.75, overlapping=True))
        append(mixed, 0.75, SPEAKER_B.label, overlapping=True)

    write_wav(path, segments, sample_rate)
    return path, turns


def generate_corpus(directory: Path, *, count: int = 2) -> list[Path]:
    """Write a tiny multi-file synthetic corpus for discovery tests."""
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for index in range(count):
        path = directory / f"synthetic_{index:03d}.wav"
        generate_two_speaker_file(path, include_overlap=index % 2 == 1)
        paths.append(path)
    return paths
