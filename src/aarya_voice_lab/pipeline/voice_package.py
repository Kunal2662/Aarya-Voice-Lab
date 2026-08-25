"""The `.arya-voice.zip` package contract -- Task 6 of the autonomous
execution plan.

Voice Lab and AARYA Core are separate systems. This module defines only
the versioned manifest contract at the boundary between them:

    Voice Lab -> .arya-voice.zip -> AARYA Core Voice Package Manager

It does **not** implement AARYA Core's importer, installer, or voice
registry -- those are Core-side responsibilities this repository does
not contain (see README.md's "AARYA Core integration" row and
ARCHITECTURE.md's scope boundaries). It also does not create, sign, or
extract any actual `.zip` file; `*.zip` is git-ignored throughout this
repository by design (no packaged binary belongs in version control),
and no package has ever been produced by this project.

Package contents are data/model oriented by design: a manifest, a model
artifact, and metadata/license files. Arbitrary executable content is
never permitted by default -- `validate_package_entries()` uses a fixed
allowlist of extensions, so an unrecognised or executable file type is
rejected rather than silently passed through.

See docs/VOICE_PACKAGE_SPEC.md for the full contract description.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from aarya_voice_lab import SCHEMA_VERSION
from aarya_voice_lab.schemas.base import SchemaName, validate

PACKAGE_FORMAT_MARKER = "arya-voice-package"
CURRENT_MANIFEST_FORMAT_VERSION = "1.0.0"

#: The only file types a package may contain. Deliberately an allowlist,
#: not a blocklist -- an unrecognised extension is rejected by default,
#: matching this project's fail-closed design principle (ARCHITECTURE.md).
#: No script or executable extension appears here.
ALLOWED_PACKAGE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".json",  # manifest.json, metadata
        ".txt",  # license text, notes
        ".md",  # license/attribution text
        ".onnx",
        ".safetensors",
        ".pt",
        ".pth",
        ".ckpt",
        ".nemo",
        ".bin",
        ".wav",  # e.g. a short preview sample
    }
)

#: Names explicitly forbidden even if their extension would otherwise be
#: allowed (defence in depth against a manifest that merely looks like
#: metadata but is meant to be interpreted as code by some other tool).
FORBIDDEN_PACKAGE_ENTRY_NAMES: frozenset[str] = frozenset({"__init__.py", "setup.py"})


class VoicePackageValidationError(ValueError):
    """Raised when a manifest or package entry list fails validation."""


def build_voice_package_manifest(
    *,
    voice_id: str,
    display_name: str,
    version: str,
    type: str,
    provider: str,
    languages: list[str],
    model_format: str,
    license: str,
    provider_version: str | None = None,
    runtime_requirements: dict[str, Any] | None = None,
    hardware_requirements: dict[str, Any] | None = None,
    memory_requirements_mb: float | None = None,
    provenance: str | None = None,
    checksum_sha256: str = "",
    compatibility: dict[str, Any] | None = None,
    creator: dict[str, Any] | None = None,
    created_at: str | None = None,
    notes: str | None = None,
    format_version: str = CURRENT_MANIFEST_FORMAT_VERSION,
    schema_version: str = SCHEMA_VERSION,
) -> dict[str, Any]:
    """Build and validate one voice package manifest record.

    `type='private_voice'` is not accepted -- the schema's own enum
    excludes it, and this function does not work around that.
    """
    record: dict[str, Any] = {
        "schema_version": schema_version,
        "format": PACKAGE_FORMAT_MARKER,
        "format_version": format_version,
        "voice_id": voice_id,
        "display_name": display_name,
        "version": version,
        "type": type,
        "provider": provider,
        "provider_version": provider_version,
        "languages": languages,
        "model_format": model_format,
        "runtime_requirements": runtime_requirements,
        "hardware_requirements": hardware_requirements,
        "memory_requirements_mb": memory_requirements_mb,
        "license": license,
        "provenance": provenance,
        "integrity": {"algorithm": "sha256", "checksum_sha256": checksum_sha256},
        "compatibility": compatibility,
        "creator": creator,
        "created_at": created_at,
        "notes": notes,
    }
    validate(record, SchemaName.VOICE_PACKAGE_MANIFEST)
    return record


def validate_package_entries(entry_names: list[str]) -> list[str]:
    """Validate a proposed package's file listing against the allowlist.

    Returns a list of human-readable rejection reasons; an empty list
    means every entry is acceptable. Never raises -- a caller assembling
    a package needs the *complete* list of problems, not just the first.
    Path separators are normalised to POSIX for the check, since a zip
    archive's internal names are always POSIX-style regardless of the
    platform that created or reads it.
    """
    problems: list[str] = []
    for raw_name in entry_names:
        name = PurePosixPath(raw_name.replace("\\", "/"))
        if ".." in name.parts:
            problems.append(f"{raw_name!r}: path traversal ('..') is never permitted in a package entry")
            continue
        if name.name in FORBIDDEN_PACKAGE_ENTRY_NAMES:
            problems.append(f"{raw_name!r}: explicitly forbidden entry name")
            continue
        suffix = name.suffix.lower()
        if suffix not in ALLOWED_PACKAGE_EXTENSIONS:
            problems.append(
                f"{raw_name!r}: extension {suffix or '(none)'!r} is not on the package allowlist "
                f"{sorted(ALLOWED_PACKAGE_EXTENSIONS)}"
            )
    return problems


def package_is_valid(entry_names: list[str]) -> bool:
    return not validate_package_entries(entry_names)
