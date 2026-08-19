"""Audio discovery / inventory — the first pipeline stage.

Catalogues audio files in a directory: id, path, size, hash, and (for
WAV) format details read via the stdlib. It opens files read-only and
never modifies, moves, or copies them.

Phase 1 status: implemented and tested against SYNTHETIC audio only. It
is deliberately usable on any directory the operator points it at, but
the CLI refuses to run it against the private source tree without an
explicit approved operation — see `require_synthetic_or_approved`.
"""

from __future__ import annotations

import contextlib
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aarya_voice_lab.core.paths import PROJECT_ROOT
from aarya_voice_lab.pipeline.contracts import sha256_file
from aarya_voice_lab.security.source_protection import AUDIO_EXTENSIONS


class PrivateSourceAccessError(PermissionError):
    """Raised when an operation would read the protected source tree."""


@dataclass
class AudioFileRecord:
    source_file_id: str
    path: str
    size_bytes: int
    sha256: str
    duration_seconds: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    format_note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file_id": self.source_file_id,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "duration_seconds": self.duration_seconds,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "format_note": self.format_note,
        }


@dataclass
class Inventory:
    root: str
    files: list[AudioFileRecord] = field(default_factory=list)

    @property
    def total_duration_seconds(self) -> float:
        return sum(f.duration_seconds or 0.0 for f in self.files)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "file_count": len(self.files),
            "total_duration_seconds": round(self.total_duration_seconds, 3),
            "files": [f.to_dict() for f in self.files],
        }


def require_synthetic_or_approved(directory: Path, *, approved: bool = False) -> None:
    """Refuse to inventory the protected source tree unless explicitly approved.

    This is a guard against an accidental invocation (a stray path, a
    script defaulting to `source/`) rather than against a determined
    operator — the approval flag exists precisely so a later phase can
    proceed deliberately.
    """
    if approved:
        return
    resolved = directory.resolve()
    protected = (PROJECT_ROOT / "source").resolve()
    if resolved == protected or protected in resolved.parents:
        raise PrivateSourceAccessError(
            f"Refusing to inventory {resolved}: this is the protected private source "
            "tree. Phase 1 must not access the recordings. Pass approved=True only "
            "within an explicitly approved dataset phase."
        )


def _probe_wav(path: Path) -> dict[str, Any]:
    """Read WAV headers with the stdlib. Returns {} for non-WAV or unreadable."""
    try:
        with contextlib.closing(wave.open(str(path), "rb")) as fh:
            frames = fh.getnframes()
            rate = fh.getframerate()
            return {
                "duration_seconds": round(frames / rate, 6) if rate else None,
                "sample_rate": rate,
                "channels": fh.getnchannels(),
            }
    except (wave.Error, OSError, EOFError):
        return {}


def discover_audio_files(directory: Path, *, recursive: bool = True) -> list[Path]:
    if not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")
    pattern = "**/*" if recursive else "*"
    return sorted(
        path
        for path in directory.glob(pattern)
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    )


def build_inventory(
    directory: Path,
    *,
    recursive: bool = True,
    approved: bool = False,
) -> Inventory:
    require_synthetic_or_approved(directory, approved=approved)
    inventory = Inventory(root=str(directory))
    for index, path in enumerate(discover_audio_files(directory, recursive=recursive)):
        probe = _probe_wav(path)
        inventory.files.append(
            AudioFileRecord(
                source_file_id=f"src-{index:04d}",
                # Relative so records never embed an absolute private path.
                path=str(path.relative_to(directory)),
                size_bytes=path.stat().st_size,
                sha256=sha256_file(path),
                duration_seconds=probe.get("duration_seconds"),
                sample_rate=probe.get("sample_rate"),
                channels=probe.get("channels"),
                format_note=None if probe else "headers not readable without FFmpeg",
            )
        )
    return inventory
