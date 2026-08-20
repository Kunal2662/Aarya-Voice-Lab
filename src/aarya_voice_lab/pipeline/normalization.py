"""Technical normalization — derived copies only.

Produces a normalized *new* file in `data/working/`. The original is
opened read-only and is never modified, moved, or replaced.

Why these defaults:

* **16 kHz** — the sample rate NeMo/Sortformer diarization and most
  speaker-verification models expect. Upsampling 8 kHz telephone audio to
  16 kHz adds no information but matches model input requirements without
  discarding anything; downsampling wideband audio to 16 kHz is the
  standard, lossy-but-accepted trade for those models. Note that TTS
  training generally prefers 22.05 or 24 kHz, so the *normalized* copy is
  for analysis, and a separate derivation should serve TTS later — which
  is exactly why the original is preserved untouched.
* **Mono** — diarization and verification operate on a single channel,
  and mixing is deterministic. A stereo call recording with one speaker
  per channel is a special case worth handling deliberately later, so
  channel layout is recorded rather than assumed.
* **16-bit PCM** — lossless for analysis and universally readable.
* **Loudness normalization: OFF by default.** Level is *evidence* about a
  recording. Normalizing it away before quality analysis would erase the
  characteristic being measured.

Nothing is chosen because it is conventional; every value above serves a
downstream requirement, and all are configurable.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from aarya_voice_lab.core.data_root import DataRoot, assert_source_writable
from aarya_voice_lab.pipeline.contracts import sha256_file

NORMALIZATION_VERSION = "1.0.0"


class NormalizationBlocked(RuntimeError):
    """Raised when normalization cannot proceed (e.g. FFmpeg missing).

    Distinct from a failure: the input is fine, the capability is absent.
    """


@dataclass(frozen=True)
class NormalizationConfig:
    target_sample_rate: int = 16_000
    target_channels: int = 1
    target_bit_depth: int = 16
    #: Off by default — see the module docstring.
    apply_loudness_normalization: bool = False
    target_loudness_lufs: float = -23.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def config_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass
class NormalizationRecord:
    """Provenance for one derived copy."""

    source_file_id: str
    source_path: str
    source_sha256: str
    output_path: str | None
    output_sha256: str | None
    config: dict[str, Any]
    config_hash: str
    tool: str | None
    tool_version: str | None
    normalization_version: str = NORMALIZATION_VERSION
    reason: str = "technical normalization for analysis"
    status: str = "completed"
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file_id": self.source_file_id,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "output_path": self.output_path,
            "output_sha256": self.output_sha256,
            "config": self.config,
            "config_hash": self.config_hash,
            "tool": self.tool,
            "tool_version": self.tool_version,
            "normalization_version": self.normalization_version,
            "reason": self.reason,
            "status": self.status,
            "note": self.note,
        }


def ffmpeg_version() -> str | None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    try:
        result = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, timeout=15, check=False)
        if result.returncode == 0 and result.stdout:
            parts = result.stdout.split()
            return parts[2] if len(parts) > 2 else result.stdout.splitlines()[0]
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def build_ffmpeg_command(source: Path, destination: Path, config: NormalizationConfig) -> list[str]:
    codec = {8: "pcm_u8", 16: "pcm_s16le", 24: "pcm_s24le", 32: "pcm_s32le"}.get(
        config.target_bit_depth, "pcm_s16le"
    )
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        # Never overwrite: refuse if the destination exists, rather than
        # clobbering a previously derived artifact.
        "-n",
        "-i", str(source),
        "-ar", str(config.target_sample_rate),
        "-ac", str(config.target_channels),
        "-c:a", codec,
    ]
    if config.apply_loudness_normalization:
        command += ["-af", f"loudnorm=I={config.target_loudness_lufs}:TP=-2.0:LRA=11"]
    command.append(str(destination))
    return command


def normalize_file(
    source: Path,
    destination: Path,
    *,
    source_file_id: str,
    source_sha256: str,
    data_root: DataRoot,
    config: NormalizationConfig | None = None,
    timeout: int = 600,
) -> NormalizationRecord:
    """Write a normalized copy of `source` to `destination`.

    Raises NormalizationBlocked when FFmpeg is unavailable — the original
    is left exactly as it was, and nothing is substituted.
    """
    config = config or NormalizationConfig()

    # Hard guard: a path bug must never be able to write into source/.
    assert_source_writable(data_root, destination)

    version = ffmpeg_version()
    if version is None:
        raise NormalizationBlocked(
            "FFmpeg is not installed, so audio cannot be normalized. The original "
            "was not read, converted, or modified. Install FFmpeg (see "
            "docs/ENVIRONMENT.md) and re-run; no substitute tool will be used."
        )

    if not source.is_file():
        raise FileNotFoundError(f"source not found: {source}")

    # Verify the source still matches what was inventoried before deriving
    # anything from it.
    actual = sha256_file(source)
    if actual != source_sha256:
        raise NormalizationBlocked(
            f"Source hash mismatch for {source_file_id}: expected {source_sha256[:16]}…, "
            f"found {actual[:16]}…. Source recordings are immutable; processing stopped."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise NormalizationBlocked(
            f"Destination already exists: {destination}. Refusing to overwrite a derived artifact."
        )

    try:
        result = subprocess.run(
            build_ffmpeg_command(source, destination, config),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise NormalizationBlocked(f"ffmpeg could not be executed: {exc}") from exc

    if result.returncode != 0 or not destination.is_file():
        return NormalizationRecord(
            source_file_id=source_file_id,
            source_path=source.name,
            source_sha256=source_sha256,
            output_path=None,
            output_sha256=None,
            config=config.to_dict(),
            config_hash=config.config_hash(),
            tool="ffmpeg",
            tool_version=version,
            status="failed",
            note=(result.stderr or "").strip()[:500] or "ffmpeg produced no output",
        )

    # Confirm the source is byte-identical after the operation.
    if sha256_file(source) != source_sha256:
        raise NormalizationBlocked(
            f"Source {source_file_id} changed during normalization — this must never happen. "
            "Processing stopped for investigation."
        )

    return NormalizationRecord(
        source_file_id=source_file_id,
        source_path=source.name,
        source_sha256=source_sha256,
        output_path=str(destination.name),
        output_sha256=sha256_file(destination),
        config=config.to_dict(),
        config_hash=config.config_hash(),
        tool="ffmpeg",
        tool_version=version,
    )


@dataclass
class NormalizationSummary:
    records: list[NormalizationRecord] = field(default_factory=list)
    blocked_reason: str | None = None

    @property
    def blocked(self) -> bool:
        return self.blocked_reason is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocked": self.blocked,
            "blocked_reason": self.blocked_reason,
            "record_count": len(self.records),
            "records": [r.to_dict() for r in self.records],
        }
