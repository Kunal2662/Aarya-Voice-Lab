"""Inventory stage — deterministic cataloguing of source recordings.

Records identity and provenance for every candidate file: hash, size,
detected container (from content, not extension), and audio properties
where readable. Detects duplicates, corrupt files, zero-byte files, and
unsupported formats.

Source files are opened **read-only** and never modified, moved, or
renamed. `source_file_id` is derived from content hash, so the same
recording keeps its identity across runs and across machines regardless
of filename — which is what makes the stage deterministic and resumable.
"""

from __future__ import annotations

import contextlib
import wave
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aarya_voice_lab.audio.filetype import ContainerFormat, detect_type
from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.core.paths import PROJECT_ROOT
from aarya_voice_lab.pipeline.contracts import sha256_file
from aarya_voice_lab.security.source_protection import AUDIO_EXTENSIONS

#: Files without a recognised audio extension are still inspected, because
#: extensions cannot be trusted. This bounds how much non-audio gets
#: header-checked in a directory that also holds documents.
MAX_HEADER_PROBE_BYTES = 64


class PrivateSourceAccessError(PermissionError):
    """Raised when an operation would read the protected source tree."""


@dataclass
class AudioFileRecord:
    source_file_id: str
    filename: str
    path: str
    size_bytes: int
    sha256: str
    extension: str | None = None
    container: str | None = None
    mime_type: str | None = None
    extension_mismatch: bool = False
    duration_seconds: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    bit_depth: int | None = None
    codec: str | None = None
    #: pending | duplicate_content | unreadable | zero_byte | unsupported
    processing_status: str = "pending"
    duplicate_of: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file_id": self.source_file_id,
            "filename": self.filename,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "extension": self.extension,
            "container": self.container,
            "mime_type": self.mime_type,
            "extension_mismatch": self.extension_mismatch,
            "duration_seconds": self.duration_seconds,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "bit_depth": self.bit_depth,
            "codec": self.codec,
            "processing_status": self.processing_status,
            "duplicate_of": self.duplicate_of,
            "note": self.note,
        }


@dataclass
class Inventory:
    root: str
    batch_id: str | None = None
    files: list[AudioFileRecord] = field(default_factory=list)

    @property
    def total_duration_seconds(self) -> float:
        return sum(f.duration_seconds or 0.0 for f in self.files)

    @property
    def unique_files(self) -> list[AudioFileRecord]:
        return [f for f in self.files if f.processing_status != "duplicate_content"]

    @property
    def duplicates(self) -> list[AudioFileRecord]:
        return [f for f in self.files if f.processing_status == "duplicate_content"]

    @property
    def unreadable(self) -> list[AudioFileRecord]:
        return [f for f in self.files if f.processing_status in ("unreadable", "zero_byte", "unsupported")]

    def by_id(self, source_file_id: str) -> AudioFileRecord | None:
        return next((f for f in self.files if f.source_file_id == source_file_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "batch_id": self.batch_id,
            "file_count": len(self.files),
            "unique_file_count": len(self.unique_files),
            "duplicate_count": len(self.duplicates),
            "unreadable_count": len(self.unreadable),
            "total_duration_seconds": round(self.total_duration_seconds, 3),
            "files": [f.to_dict() for f in self.files],
        }


def require_synthetic_or_approved(directory: Path, *, approved: bool = False) -> None:
    """Refuse to read the protected source tree unless explicitly approved.

    Guards against an accidental invocation — a stray path, a script
    defaulting to the source directory — rather than a determined
    operator. The approval flag exists so an approved phase can proceed
    deliberately, and is gated by `dataset_gate.assert_access_allowed`.
    """
    if approved:
        return
    resolved = directory.resolve()
    protected_roots = [
        (PROJECT_ROOT / "source").resolve(),
        DataRoot.default().source,
    ]
    for protected in protected_roots:
        protected_resolved = protected.resolve() if protected.exists() else protected
        if resolved == protected_resolved or protected_resolved in resolved.parents:
            raise PrivateSourceAccessError(
                f"Refusing to read {resolved}: this is the protected private source tree. "
                "Pass approved=True only within an explicitly approved dataset phase "
                "(see aarya_voice_lab.pipeline.dataset_gate)."
            )


def _probe_wav_quietly(path: Path) -> dict[str, Any]:
    """Best-effort WAV header read. Returns {} rather than raising —
    inventory records unreadability as a status, it does not fail a run."""
    try:
        with contextlib.closing(wave.open(str(path), "rb")) as fh:
            rate = fh.getframerate()
            frames = fh.getnframes()
            width = fh.getsampwidth()
            return {
                "duration_seconds": round(frames / rate, 6) if rate else None,
                "sample_rate": rate or None,
                "channels": fh.getnchannels() or None,
                "bit_depth": width * 8 if width else None,
                "codec": "pcm",
            }
    except (wave.Error, OSError, EOFError):
        return {}


def _looks_like_audio(path: Path) -> bool:
    """Whether to inventory a file at all.

    Recognised extension OR an audio-looking header — the second clause
    matters because a recording may arrive with a wrong or missing
    extension, and dropping it here would lose it silently.
    """
    if path.suffix.lower() in AUDIO_EXTENSIONS:
        return True
    try:
        if path.stat().st_size == 0:
            return False
    except OSError:
        return False
    return detect_type(path).container not in (ContainerFormat.UNKNOWN, ContainerFormat.EMPTY)


def discover_audio_files(directory: Path, *, recursive: bool = True) -> list[Path]:
    if not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")
    pattern = "**/*" if recursive else "*"
    return sorted(p for p in directory.glob(pattern) if p.is_file() and _looks_like_audio(p))


def build_inventory(
    directory: Path,
    *,
    recursive: bool = True,
    approved: bool = False,
    batch_id: str | None = None,
) -> Inventory:
    """Catalogue every audio file under `directory`. Never writes."""
    require_synthetic_or_approved(directory, approved=approved)
    inventory = Inventory(root=str(directory), batch_id=batch_id)

    seen_hashes: dict[str, str] = {}
    for path in discover_audio_files(directory, recursive=recursive):
        size = path.stat().st_size
        digest = sha256_file(path)
        # Content-addressed id: stable across renames, machines, and runs.
        source_file_id = f"src-{digest[:16]}"
        detected = detect_type(path)

        record = AudioFileRecord(
            source_file_id=source_file_id,
            filename=path.name,
            path=str(path.relative_to(directory)),
            size_bytes=size,
            sha256=digest,
            extension=path.suffix.lower() or None,
            container=detected.container.value,
            mime_type=detected.mime_type,
            extension_mismatch=detected.extension_mismatch,
        )

        if size == 0:
            record.processing_status = "zero_byte"
            record.note = "file is zero bytes"
        elif detected.container is ContainerFormat.UNKNOWN:
            record.processing_status = "unsupported"
            record.note = "content does not match a known audio container"
        elif not detected.supported:
            record.processing_status = "unsupported"
            record.note = f"container {detected.container.value} is not supported"
        elif detected.container is ContainerFormat.WAV:
            probe = _probe_wav_quietly(path)
            if probe:
                record.duration_seconds = probe["duration_seconds"]
                record.sample_rate = probe["sample_rate"]
                record.channels = probe["channels"]
                record.bit_depth = probe["bit_depth"]
                record.codec = probe["codec"]
            else:
                record.processing_status = "unreadable"
                record.note = "WAV headers could not be read; file may be corrupt"
        else:
            record.note = "properties require FFmpeg; not probed in this stage"

        # Duplicate *content*, regardless of filename or location.
        if digest in seen_hashes:
            record.processing_status = "duplicate_content"
            record.duplicate_of = seen_hashes[digest]
            record.note = f"identical content to {seen_hashes[digest]}"
        else:
            seen_hashes[digest] = record.path

        inventory.files.append(record)

    return inventory


def duplicate_groups(inventory: Inventory) -> dict[str, list[str]]:
    """Map each content hash to the paths sharing it (2+ only)."""
    groups: dict[str, list[str]] = defaultdict(list)
    for record in inventory.files:
        groups[record.sha256].append(record.path)
    return {digest: paths for digest, paths in groups.items() if len(paths) > 1}


def verify_sources_unchanged(inventory: Inventory, directory: Path) -> list[str]:
    """Re-hash inventoried files and report any whose content changed.

    Source recordings are immutable. A changed hash means either the file
    was modified — which must never happen — or the wrong directory is
    being processed. Either way, processing that file must stop.
    """
    problems = []
    for record in inventory.files:
        path = directory / record.path
        if not path.is_file():
            problems.append(f"{record.path}: source file is missing")
            continue
        if sha256_file(path) != record.sha256:
            problems.append(f"{record.path}: SHA-256 changed since inventory — source must be immutable")
    return problems
