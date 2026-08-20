"""Audio validation stage.

Classifies each inventoried file so later stages never have to guess
whether input is usable. Nothing is converted or repaired here — a file
that fails validation is reported, not fixed, because silently
"correcting" a private recording would violate source immutability.

Results are one of:

    VALID    usable as-is
    WARNING  usable, but something needs a human's attention
    INVALID  not usable (corrupt, empty, unrecognised)
    BLOCKED  cannot be determined here — a capability is missing
             (e.g. a non-WAV container with no FFmpeg installed)

BLOCKED is deliberately distinct from INVALID: "we cannot tell" must
never be recorded as "this file is bad".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from aarya_voice_lab.audio.filetype import ContainerFormat, detect_type
from aarya_voice_lab.audio.probe import (
    AudioProperties,
    AudioReadError,
    ffmpeg_available,
    probe,
)


class ValidationStatus(StrEnum):
    VALID = "VALID"
    WARNING = "WARNING"
    INVALID = "INVALID"
    BLOCKED = "BLOCKED"


@dataclass
class ValidationFinding:
    code: str
    message: str
    severity: ValidationStatus

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "severity": self.severity.value}


@dataclass
class ValidationResult:
    source_file_id: str
    path: str
    status: ValidationStatus
    findings: list[ValidationFinding] = field(default_factory=list)
    properties: AudioProperties | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file_id": self.source_file_id,
            "path": self.path,
            "status": self.status.value,
            "findings": [f.to_dict() for f in self.findings],
            "properties": self.properties.to_dict() if self.properties else None,
        }


@dataclass(frozen=True)
class ValidationConfig:
    """Thresholds for structural validity only — not quality judgements.

    Deliberately permissive: this project's source material is expected to
    include telephone/call recordings, which are low sample-rate and
    band-limited by nature. Rejecting them here would discard the dataset.
    Quality characteristics are measured separately in the quality stage.
    """

    min_duration_seconds: float = 0.1
    max_duration_seconds: float = 6 * 60 * 60
    #: Below this, warn — never reject. 8 kHz telephone audio is valid input.
    low_sample_rate_warning_hz: int = 16_000
    max_channels: int = 8

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_duration_seconds": self.min_duration_seconds,
            "max_duration_seconds": self.max_duration_seconds,
            "low_sample_rate_warning_hz": self.low_sample_rate_warning_hz,
            "max_channels": self.max_channels,
        }


def _worst(statuses: list[ValidationStatus]) -> ValidationStatus:
    for candidate in (
        ValidationStatus.INVALID,
        ValidationStatus.BLOCKED,
        ValidationStatus.WARNING,
    ):
        if candidate in statuses:
            return candidate
    return ValidationStatus.VALID


def validate_audio_file(
    path: Path,
    *,
    source_file_id: str,
    config: ValidationConfig | None = None,
    relative_to: Path | None = None,
) -> ValidationResult:
    config = config or ValidationConfig()
    display_path = str(path.relative_to(relative_to)) if relative_to else path.name
    findings: list[ValidationFinding] = []

    def add(code: str, message: str, severity: ValidationStatus) -> None:
        findings.append(ValidationFinding(code, message, severity))

    if not path.is_file():
        add("missing_file", "file does not exist or is not a regular file", ValidationStatus.INVALID)
        return ValidationResult(source_file_id, display_path, ValidationStatus.INVALID, findings)

    if path.stat().st_size == 0:
        add("zero_byte_file", "file is zero bytes", ValidationStatus.INVALID)
        return ValidationResult(source_file_id, display_path, ValidationStatus.INVALID, findings)

    detected = detect_type(path)

    if detected.container is ContainerFormat.EMPTY:
        add("empty_header", "file has no readable header", ValidationStatus.INVALID)
        return ValidationResult(source_file_id, display_path, ValidationStatus.INVALID, findings)

    if detected.container is ContainerFormat.UNKNOWN:
        add(
            "unrecognised_container",
            "content does not match any known audio container",
            ValidationStatus.INVALID,
        )
        return ValidationResult(source_file_id, display_path, ValidationStatus.INVALID, findings)

    if detected.extension_mismatch:
        add(
            "extension_mismatch",
            f"content is {detected.container.value} but the extension is "
            f"{detected.declared_extension!r}; the extension was ignored",
            ValidationStatus.WARNING,
        )

    if not detected.supported:
        add(
            "unsupported_container",
            f"container {detected.container.value} is not supported",
            ValidationStatus.INVALID,
        )
        return ValidationResult(source_file_id, display_path, _worst([f.severity for f in findings]), findings)

    # Non-WAV needs FFmpeg. Absent it, we cannot inspect the file —
    # report BLOCKED and leave the original completely untouched.
    if not detected.natively_readable and not ffmpeg_available():
        add(
            "capability_unavailable",
            f"{detected.container.value} requires FFmpeg to inspect, and FFmpeg is not "
            "installed. The file was not read, converted, or modified.",
            ValidationStatus.BLOCKED,
        )
        return ValidationResult(source_file_id, display_path, ValidationStatus.BLOCKED, findings)

    try:
        properties = probe(path)
    except AudioReadError as exc:
        add("corrupt_or_unreadable", str(exc), ValidationStatus.INVALID)
        return ValidationResult(source_file_id, display_path, ValidationStatus.INVALID, findings)

    for warning in properties.warnings:
        code = "truncated_stream" if "truncated" in warning else "malformed_metadata"
        add(code, warning, ValidationStatus.WARNING)

    duration = properties.duration_seconds
    if duration is None:
        add("unknown_duration", "duration could not be determined", ValidationStatus.WARNING)
    elif duration < config.min_duration_seconds:
        add(
            "too_short",
            f"duration {duration:.3f}s is below the minimum {config.min_duration_seconds}s",
            ValidationStatus.INVALID,
        )
    elif duration > config.max_duration_seconds:
        add(
            "too_long",
            f"duration {duration:.1f}s exceeds the maximum {config.max_duration_seconds}s",
            ValidationStatus.WARNING,
        )

    rate = properties.sample_rate
    if not rate:
        add("unknown_sample_rate", "sample rate could not be determined", ValidationStatus.WARNING)
    elif rate < config.low_sample_rate_warning_hz:
        # A warning, never a rejection: telephone-band audio is expected here.
        add(
            "low_sample_rate",
            f"sample rate {rate} Hz is below {config.low_sample_rate_warning_hz} Hz "
            "(typical of telephone/call recordings; recorded, not rejected)",
            ValidationStatus.WARNING,
        )

    channels = properties.channels
    if not channels:
        add("unknown_channels", "channel count could not be determined", ValidationStatus.WARNING)
    elif channels > config.max_channels:
        add("too_many_channels", f"{channels} channels exceeds {config.max_channels}", ValidationStatus.WARNING)

    return ValidationResult(
        source_file_id=source_file_id,
        path=display_path,
        status=_worst([f.severity for f in findings]),
        findings=findings,
        properties=properties,
    )


@dataclass
class ValidationSummary:
    results: list[ValidationResult] = field(default_factory=list)

    def count(self, status: ValidationStatus) -> int:
        return sum(1 for r in self.results if r.status is status)

    @property
    def usable(self) -> list[ValidationResult]:
        return [r for r in self.results if r.status in (ValidationStatus.VALID, ValidationStatus.WARNING)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": len(self.results),
            "valid": self.count(ValidationStatus.VALID),
            "warning": self.count(ValidationStatus.WARNING),
            "invalid": self.count(ValidationStatus.INVALID),
            "blocked": self.count(ValidationStatus.BLOCKED),
            "results": [r.to_dict() for r in self.results],
        }
