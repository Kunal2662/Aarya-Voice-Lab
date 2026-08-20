"""Read audio properties and PCM samples.

Two tiers, deliberately:

* **stdlib (`wave`)** — reads uncompressed WAV with no dependencies. This
  is the tier Phase 2 is verified against, and it works on the current
  machine, which has no FFmpeg.
* **FFmpeg (`ffprobe`)** — needed for every other container. When it is
  absent the capability is reported as unavailable and the file is left
  untouched; nothing is silently substituted or converted.

All reads open files read-only. Nothing here writes, converts, or
modifies audio.
"""

from __future__ import annotations

import array
import contextlib
import json
import shutil
import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aarya_voice_lab.audio.filetype import ContainerFormat, detect_type

#: Cap on PCM decoded into memory at once, so a long recording cannot
#: exhaust RAM during analysis.
MAX_DECODE_SAMPLES = 50_000_000


class AudioReadError(RuntimeError):
    """Raised when audio cannot be read (corrupt, truncated, unsupported)."""


@dataclass
class AudioProperties:
    duration_seconds: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    bit_depth: int | None = None
    codec: str | None = None
    container: str | None = None
    frame_count: int | None = None
    #: Where these values came from: "wave" (stdlib) or "ffprobe".
    source: str = "unknown"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "duration_seconds": self.duration_seconds,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "bit_depth": self.bit_depth,
            "codec": self.codec,
            "container": self.container,
            "frame_count": self.frame_count,
            "source": self.source,
            "warnings": list(self.warnings),
        }


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def probe_wav(path: Path) -> AudioProperties:
    """Read WAV properties with the stdlib. Raises AudioReadError if unreadable."""
    try:
        with contextlib.closing(wave.open(str(path), "rb")) as fh:
            rate = fh.getframerate()
            frames = fh.getnframes()
            width = fh.getsampwidth()
            channels = fh.getnchannels()
    except (wave.Error, OSError, EOFError) as exc:
        raise AudioReadError(f"unreadable WAV: {exc}") from exc

    properties = AudioProperties(
        duration_seconds=round(frames / rate, 6) if rate else None,
        sample_rate=rate or None,
        channels=channels or None,
        bit_depth=width * 8 if width else None,
        codec="pcm",
        container="wav",
        frame_count=frames,
        source="wave",
    )
    if rate == 0:
        properties.warnings.append("sample rate reported as zero")
    if frames == 0:
        properties.warnings.append("file contains no audio frames")

    # A header claiming more frames than the file can hold indicates truncation.
    expected_bytes = frames * width * channels
    actual_bytes = path.stat().st_size
    if width and channels and expected_bytes > actual_bytes:
        properties.warnings.append(
            f"header declares {expected_bytes} PCM bytes but the file holds at most {actual_bytes}; likely truncated"
        )
    return properties


def probe_with_ffprobe(path: Path, *, timeout: int = 60) -> AudioProperties:
    """Read properties via ffprobe. Raises AudioReadError if unavailable/failed."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise AudioReadError("ffprobe is not available; cannot probe this container")
    try:
        result = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-select_streams", "a:0",
                "-show_entries",
                "stream=sample_rate,channels,codec_name,bits_per_raw_sample,duration:format=duration,format_name",
                "-of", "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AudioReadError(f"ffprobe failed: {exc}") from exc

    if result.returncode != 0:
        raise AudioReadError(f"ffprobe error: {(result.stderr or '').strip()[:500]}")

    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise AudioReadError(f"ffprobe returned unparseable output: {exc}") from exc

    streams = payload.get("streams") or []
    if not streams:
        raise AudioReadError("no audio stream found")
    stream = streams[0]
    fmt = payload.get("format") or {}

    duration = stream.get("duration") or fmt.get("duration")
    bits = stream.get("bits_per_raw_sample")
    return AudioProperties(
        duration_seconds=float(duration) if duration else None,
        sample_rate=int(stream["sample_rate"]) if stream.get("sample_rate") else None,
        channels=int(stream["channels"]) if stream.get("channels") else None,
        bit_depth=int(bits) if bits and str(bits).isdigit() else None,
        codec=stream.get("codec_name"),
        container=fmt.get("format_name"),
        source="ffprobe",
    )


def probe(path: Path) -> AudioProperties:
    """Read properties using the best available tier.

    WAV goes through the stdlib even when FFmpeg exists: fewer moving
    parts, and it is the path Phase 2 actually verified.
    """
    detected = detect_type(path)
    if detected.container is ContainerFormat.EMPTY:
        raise AudioReadError("file is empty")
    if detected.container is ContainerFormat.WAV:
        return probe_wav(path)
    if detected.container is ContainerFormat.UNKNOWN:
        raise AudioReadError("unrecognised container; not identifiable audio")
    return probe_with_ffprobe(path)


def read_wav_mono_samples(path: Path, *, max_samples: int = MAX_DECODE_SAMPLES) -> tuple[list[int], int]:
    """Decode a WAV to mono int samples plus its sample rate.

    Multi-channel input is averaged to mono, which is what every analysis
    in this pipeline operates on. Only 8/16/32-bit PCM is handled; other
    widths raise rather than being silently misread.
    """
    try:
        with contextlib.closing(wave.open(str(path), "rb")) as fh:
            channels = fh.getnchannels()
            width = fh.getsampwidth()
            rate = fh.getframerate()
            frames = min(fh.getnframes(), max_samples // max(channels, 1))
            raw = fh.readframes(frames)
    except (wave.Error, OSError, EOFError) as exc:
        raise AudioReadError(f"unreadable WAV: {exc}") from exc

    typecode = {1: "b", 2: "h", 4: "i"}.get(width)
    if typecode is None:
        raise AudioReadError(f"unsupported PCM sample width: {width * 8} bit")

    # A truncated file can end mid-sample, leaving a byte count that is not
    # a whole number of frames. Trim the partial tail rather than letting
    # array.frombytes raise: the readable prefix is still usable, and a
    # damaged recording must degrade, not crash the run.
    frame_bytes = width * max(channels, 1)
    usable = (len(raw) // frame_bytes) * frame_bytes
    if usable == 0:
        raise AudioReadError("no complete PCM frames could be read; file is truncated or empty")
    raw = raw[:usable]

    samples = array.array(typecode)
    samples.frombytes(raw)

    if channels > 1:
        mono = [
            sum(samples[i : i + channels]) // channels
            for i in range(0, len(samples) - channels + 1, channels)
        ]
    else:
        mono = list(samples)
    return mono, rate


def max_amplitude_for_width(bit_depth: int) -> int:
    return 2 ** (bit_depth - 1) - 1
