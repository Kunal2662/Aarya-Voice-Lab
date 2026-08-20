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
import random
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


# ---------------------------------------------------------------------------
# Phase 2 fixtures: richer signals plus deliberately-broken input.
#
# Everything below is still generated from arithmetic. None of it contains
# speech, and none of it derives from any recording of any person.
# ---------------------------------------------------------------------------


def _speech_like_samples(
    frequency: float,
    duration: float,
    sample_rate: int,
    amplitude: float = 0.4,
) -> list[int]:
    """A harmonically rich, amplitude-modulated tone.

    Closer to voiced speech than a pure sine — it has harmonics and a
    syllable-rate envelope — which exercises the energy and
    zero-crossing analyses meaningfully. It is NOT speech, and no
    conclusion about real speech should be drawn from it.
    """
    count = int(duration * sample_rate)
    samples = []
    for i in range(count):
        t = i / sample_rate
        # 4 Hz envelope approximates a syllable rate.
        envelope = 0.6 + 0.4 * math.sin(2.0 * math.pi * 4.0 * t)
        value = (
            1.00 * math.sin(2.0 * math.pi * frequency * t)
            + 0.50 * math.sin(2.0 * math.pi * frequency * 2 * t)
            + 0.25 * math.sin(2.0 * math.pi * frequency * 3 * t)
        ) / 1.75
        samples.append(int(amplitude * envelope * value * _INT16_MAX))
    return samples


def generate_speech_like(
    path: Path,
    *,
    frequency_hz: float = 180.0,
    duration_seconds: float = 2.0,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    amplitude: float = 0.4,
) -> Path:
    return write_wav(
        path, _speech_like_samples(frequency_hz, duration_seconds, sample_rate, amplitude), sample_rate
    )


def generate_conversation(
    path: Path,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    include_overlap: bool = True,
    turn_seconds: float = 2.0,
    pause_seconds: float = 0.6,
) -> tuple[Path, list[SyntheticTurn]]:
    """A two-'speaker' exchange with pauses and optional overlap.

    Returns ground-truth turns so tests can assert segmentation behaviour
    without needing a real diarizer.
    """
    samples: list[int] = []
    turns: list[SyntheticTurn] = []
    cursor = 0.0

    def add(chunk: list[int], duration: float, speaker: str | None, overlapping: bool = False) -> None:
        nonlocal cursor
        samples.extend(chunk)
        if speaker is not None:
            turns.append(SyntheticTurn(speaker, cursor, cursor + duration, overlapping))
        cursor += duration

    add(_silence_samples(0.3, sample_rate), 0.3, None)
    add(_speech_like_samples(SPEAKER_A.frequency_hz, turn_seconds, sample_rate), turn_seconds, SPEAKER_A.label)
    add(_silence_samples(pause_seconds, sample_rate), pause_seconds, None)
    add(_speech_like_samples(SPEAKER_B.frequency_hz, turn_seconds, sample_rate), turn_seconds, SPEAKER_B.label)
    add(_silence_samples(pause_seconds, sample_rate), pause_seconds, None)

    if include_overlap:
        a = _speech_like_samples(SPEAKER_A.frequency_hz, 1.5, sample_rate, 0.3)
        b = _speech_like_samples(SPEAKER_B.frequency_hz * 1.7, 1.5, sample_rate, 0.3)
        mixed = [x + y for x, y in zip(a, b, strict=True)]
        turns.append(SyntheticTurn(SPEAKER_A.label, cursor, cursor + 1.5, overlapping=True))
        add(mixed, 1.5, SPEAKER_B.label, overlapping=True)

    add(_silence_samples(0.3, sample_rate), 0.3, None)
    write_wav(path, samples, sample_rate)
    return path, turns


def generate_clipped(
    path: Path,
    *,
    duration_seconds: float = 1.0,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> Path:
    """Heavily clipped audio, for exercising the clipping detector."""
    raw = _sine_samples(300.0, duration_seconds, sample_rate, amplitude=3.0)
    return write_wav(path, [_clamp(s) for s in raw], sample_rate)


def generate_narrowband(
    path: Path,
    *,
    duration_seconds: float = 2.0,
) -> Path:
    """8 kHz audio, standing in for a telephone/call recording.

    Used to assert that such recordings are recorded as a characteristic
    and NOT rejected — they are expected input for this dataset.
    """
    return write_wav(
        path, _speech_like_samples(200.0, duration_seconds, 8_000, 0.25), 8_000
    )


def _noise_samples(duration: float, sample_rate: int, amplitude: float, *, seed: int = 42) -> list[int]:
    """Deterministic pseudo-noise: a fixed-seed PRNG, not real acoustic
    noise. Reproducible across runs and machines, which is what makes it
    a usable fixture rather than one-off randomness."""
    rng = random.Random(seed)
    count = int(duration * sample_rate)
    return [int(amplitude * rng.uniform(-1.0, 1.0) * _INT16_MAX) for _ in range(count)]


def generate_noisy_speech(
    path: Path,
    *,
    frequency_hz: float = 180.0,
    duration_seconds: float = 2.0,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    speech_amplitude: float = 0.35,
    noise_amplitude: float = 0.15,
) -> Path:
    """Speech-like signal with a deterministic pseudo-noise floor mixed
    in — for exercising low-SNR classification (VL-D3 §33's "noisy
    speech" fixture). Not real acoustic noise, and not real speech."""
    speech = _speech_like_samples(frequency_hz, duration_seconds, sample_rate, speech_amplitude)
    noise = _noise_samples(duration_seconds, sample_rate, noise_amplitude)
    mixed = [_clamp(s + n) for s, n in zip(speech, noise, strict=True)]
    return write_wav(path, mixed, sample_rate)


def generate_zero_byte(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def generate_corrupt_wav(path: Path) -> Path:
    """A file with a valid RIFF/WAVE header but a destroyed body."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"\xff" * 32)
    return path


def generate_truncated_wav(path: Path, *, sample_rate: int = DEFAULT_SAMPLE_RATE) -> Path:
    """A valid header declaring far more PCM data than the file contains."""
    generate_tone(path, duration_seconds=1.0, sample_rate=sample_rate)
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 3])
    return path


def generate_mislabelled_file(path: Path) -> Path:
    """MP3 content carrying a .wav extension — extensions must not be trusted."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 64)
    return path


def generate_unsupported_file(path: Path) -> Path:
    """Not audio at all, despite an audio extension."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"This is plain text, not audio." + b"\x00" * 32)
    return path


def generate_phase2_corpus(directory: Path) -> dict[str, Path]:
    """A deterministic corpus covering the cases Phase 2 must handle."""
    directory.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    conversation, _ = generate_conversation(directory / "conversation.wav")
    paths["conversation"] = conversation
    paths["clean_speech"] = generate_speech_like(directory / "clean_speech.wav", duration_seconds=3.0)
    paths["short"] = generate_speech_like(directory / "short.wav", duration_seconds=0.3)
    paths["silence"] = generate_silence(directory / "silence.wav", duration_seconds=2.0)
    paths["clipped"] = generate_clipped(directory / "clipped.wav")
    paths["narrowband"] = generate_narrowband(directory / "narrowband_8k.wav")
    paths["zero_byte"] = generate_zero_byte(directory / "zero_byte.wav")
    paths["corrupt"] = generate_corrupt_wav(directory / "corrupt.wav")
    paths["truncated"] = generate_truncated_wav(directory / "truncated.wav")
    paths["mislabelled"] = generate_mislabelled_file(directory / "mislabelled.wav")
    paths["unsupported"] = generate_unsupported_file(directory / "unsupported.wav")

    # An exact duplicate of clean_speech, under a different name.
    duplicate = directory / "duplicate_of_clean.wav"
    duplicate.write_bytes(paths["clean_speech"].read_bytes())
    paths["duplicate"] = duplicate
    return paths
