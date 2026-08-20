"""Container detection from file content, not filename.

The brief is explicit that extensions must not be trusted. A recording
handed over as `.wav` may be an MP3, an M4A, or a truncated download; a
file with no extension may be perfectly valid audio. Guessing from the
name would mis-route files at the very first stage.

Detection reads a small header prefix — the file is opened read-only and
never modified. Only container/format identification happens here; codec
inspection needs FFmpeg (see `audio.probe`).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

#: Bytes needed to identify every container below.
HEADER_BYTES = 16


class ContainerFormat(StrEnum):
    WAV = "wav"
    MP3 = "mp3"
    FLAC = "flac"
    OGG = "ogg"
    MP4 = "mp4"          # also m4a/aac-in-mp4
    AIFF = "aiff"
    AMR = "amr"
    MATROSKA = "matroska"  # mkv / webm
    CAF = "caf"
    EMPTY = "empty"
    UNKNOWN = "unknown"


#: Containers this project can process in Phase 2 without FFmpeg.
NATIVELY_READABLE: frozenset[ContainerFormat] = frozenset({ContainerFormat.WAV})

#: Containers considered valid audio input (FFmpeg needed to decode).
SUPPORTED_CONTAINERS: frozenset[ContainerFormat] = frozenset(
    {
        ContainerFormat.WAV,
        ContainerFormat.MP3,
        ContainerFormat.FLAC,
        ContainerFormat.OGG,
        ContainerFormat.MP4,
        ContainerFormat.AIFF,
        ContainerFormat.AMR,
        ContainerFormat.MATROSKA,
        ContainerFormat.CAF,
    }
)

MIME_TYPES: dict[ContainerFormat, str] = {
    ContainerFormat.WAV: "audio/wav",
    ContainerFormat.MP3: "audio/mpeg",
    ContainerFormat.FLAC: "audio/flac",
    ContainerFormat.OGG: "audio/ogg",
    ContainerFormat.MP4: "audio/mp4",
    ContainerFormat.AIFF: "audio/aiff",
    ContainerFormat.AMR: "audio/amr",
    ContainerFormat.MATROSKA: "video/x-matroska",
    ContainerFormat.CAF: "audio/x-caf",
}


@dataclass(frozen=True)
class DetectedType:
    container: ContainerFormat
    mime_type: str | None
    #: True when the extension disagrees with the detected content.
    extension_mismatch: bool = False
    declared_extension: str | None = None

    @property
    def supported(self) -> bool:
        return self.container in SUPPORTED_CONTAINERS

    @property
    def natively_readable(self) -> bool:
        return self.container in NATIVELY_READABLE


def _identify(header: bytes) -> ContainerFormat:
    if not header:
        return ContainerFormat.EMPTY
    if header[:4] == b"RIFF" and header[8:12] == b"WAVE":
        return ContainerFormat.WAV
    if header[:4] == b"fLaC":
        return ContainerFormat.FLAC
    if header[:4] == b"OggS":
        return ContainerFormat.OGG
    if header[4:8] == b"ftyp":
        return ContainerFormat.MP4
    if header[:4] == b"FORM" and header[8:12] in (b"AIFF", b"AIFC"):
        return ContainerFormat.AIFF
    if header[:4] == b"caff":
        return ContainerFormat.CAF
    if header[:4] == b"\x1a\x45\xdf\xa3":
        return ContainerFormat.MATROSKA
    if header[:6] == b"#!AMR\n":
        return ContainerFormat.AMR
    # MP3: an ID3 tag, or a raw frame sync (11 set bits).
    if header[:3] == b"ID3":
        return ContainerFormat.MP3
    if len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0:
        return ContainerFormat.MP3
    return ContainerFormat.UNKNOWN


#: Extensions that legitimately map to each detected container, used only
#: to report a mismatch — never to decide the format.
_EXTENSION_MAP: dict[ContainerFormat, frozenset[str]] = {
    ContainerFormat.WAV: frozenset({".wav", ".wave"}),
    ContainerFormat.MP3: frozenset({".mp3"}),
    ContainerFormat.FLAC: frozenset({".flac"}),
    ContainerFormat.OGG: frozenset({".ogg", ".oga", ".opus"}),
    ContainerFormat.MP4: frozenset({".mp4", ".m4a", ".aac", ".mov"}),
    ContainerFormat.AIFF: frozenset({".aiff", ".aif", ".aifc"}),
    ContainerFormat.AMR: frozenset({".amr"}),
    ContainerFormat.MATROSKA: frozenset({".mkv", ".webm"}),
    ContainerFormat.CAF: frozenset({".caf"}),
}


def detect_type(path: Path) -> DetectedType:
    """Identify a file's container by reading its header.

    Opens the file read-only. Never writes, never seeks past the header.
    """
    try:
        with path.open("rb") as fh:
            header = fh.read(HEADER_BYTES)
    except OSError:
        return DetectedType(ContainerFormat.UNKNOWN, None)

    container = _identify(header)
    extension = path.suffix.lower() or None
    expected = _EXTENSION_MAP.get(container, frozenset())
    mismatch = bool(
        extension
        and container not in (ContainerFormat.UNKNOWN, ContainerFormat.EMPTY)
        and extension not in expected
    )
    return DetectedType(
        container=container,
        mime_type=MIME_TYPES.get(container),
        extension_mismatch=mismatch,
        declared_extension=extension,
    )
