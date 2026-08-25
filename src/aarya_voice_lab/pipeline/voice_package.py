"""The `.arya-voice` package contract and builder -- Task 6 (contract)
and Task 5 of the Phase 4 plan (builder) of the autonomous execution
record.

Voice Lab and AARYA Core are separate systems. This module defines the
versioned manifest contract at the boundary between them, and this
project's own side of producing one:

    Voice Lab -> .arya-voice -> AARYA Core Voice Package Manager

It does **not** implement AARYA Core's importer, installer, or voice
registry -- those are Core-side responsibilities this repository does
not contain (see README.md's "AARYA Core integration" row and
ARCHITECTURE.md's scope boundaries). `*.zip` remains git-ignored
throughout this repository by design (no packaged binary belongs in
version control); `build_package_archive()` writes to a caller-supplied
path outside version control (normally a temp directory in tests), and
this module never commits or ships one.

Package contents are data/model oriented by design: a manifest, a model
artifact, and metadata/license files. Arbitrary executable content is
never permitted by default -- `validate_package_entries()` uses a fixed
allowlist of extensions, so an unrecognised or executable file type is
rejected rather than silently passed through, and `build_package_archive()`
refuses to write a package whose own entries would fail that same check.

See docs/VOICE_PACKAGE_SPEC.md for the full contract description.
"""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from aarya_voice_lab import SCHEMA_VERSION
from aarya_voice_lab.schemas.base import SchemaName, ValidationError, validate

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

#: A voice model this project's own architecture targets (TitaNet
#: embeddings, small TTS candidates) is realistically well under this.
#: Refusing anything larger closes a zip-bomb vector: extractall()/read()
#: decompress an amount proportional to the *declared* uncompressed
#: size, and a malicious archive can declare an enormous size behind a
#: tiny compressed payload.
MAX_PACKAGE_ENTRY_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB


def check_entry_sizes(
    archive: zipfile.ZipFile, *, max_bytes: int = MAX_PACKAGE_ENTRY_UNCOMPRESSED_BYTES
) -> list[str]:
    """Check every entry's *declared* uncompressed size against a limit,
    without decompressing anything -- a zip-bomb defense. Must be called
    (and its result checked) before any `.read()` or `.extractall()` on
    an untrusted archive: those decompress an amount proportional to the
    attacker-declared size, not the file's real size on disk.
    """
    problems: list[str] = []
    for info in archive.infolist():
        if info.file_size > max_bytes:
            problems.append(
                f"{info.filename!r}: declared uncompressed size {info.file_size} bytes exceeds the "
                f"{max_bytes} byte limit -- refusing to decompress (possible zip bomb)"
            )
    return problems


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


def reject_symlink_entries(archive: zipfile.ZipFile) -> list[str]:
    """Reject any entry whose Unix mode bits (`ZipInfo.external_attr`)
    mark it as a symlink.

    Python's own `zipfile.extractall()` does not restore Unix mode bits
    at all -- a symlink-mode entry extracts as a plain file containing
    the link-target string as literal bytes, verified empirically, not
    assumed. This check exists as defense in depth regardless: a
    different consumer of this same package format (a future Core-side
    importer using a different extraction library, or a command-line
    `unzip`/`7z` on a Unix host, both of which *do* restore symlinks)
    must never be handed an archive that could plant one. Never raises
    on an entry with no Unix mode information (`external_attr == 0`,
    e.g. an archive built on Windows) -- absence of the bit is not
    evidence of a symlink.
    """
    problems: list[str] = []
    for info in archive.infolist():
        mode = info.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            problems.append(f"{info.filename!r}: symlink-mode package entries are never permitted")
    return problems


class VoicePackageBuildError(ValueError):
    """Raised when a package cannot be built or fails post-build
    validation."""


def build_package_archive(
    output_path: Path,
    *,
    manifest: dict[str, Any],
    model_bytes: bytes,
    model_filename: str,
    extra_files: dict[str, bytes] | None = None,
) -> Path:
    """Build a real `.arya-voice` zip archive at `output_path`.

    `manifest` must already be a validated record (see
    `build_voice_package_manifest()`) -- this function re-validates it
    anyway, since a manifest built by hand or mutated after construction
    must never silently reach disk unchecked. The model file's checksum
    is verified against `manifest["integrity"]["checksum_sha256"]`
    before anything is written -- a mismatch is a caller error and is
    refused, not silently corrected.
    """
    try:
        validate(manifest, SchemaName.VOICE_PACKAGE_MANIFEST)
    except ValidationError as exc:
        raise VoicePackageBuildError(f"manifest failed schema validation: {exc}") from exc

    actual_checksum = hashlib.sha256(model_bytes).hexdigest()
    declared_checksum = manifest["integrity"]["checksum_sha256"]
    if actual_checksum != declared_checksum:
        raise VoicePackageBuildError(
            f"model bytes checksum {actual_checksum} does not match manifest.integrity.checksum_sha256 "
            f"{declared_checksum} -- refusing to build a package with a false integrity claim"
        )

    entries = {"manifest.json": json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")}
    entries[model_filename] = model_bytes
    for name, content in (extra_files or {}).items():
        entries[name] = content

    entry_problems = validate_package_entries(list(entries))
    if entry_problems:
        raise VoicePackageBuildError(f"refusing to build package with disallowed entries: {entry_problems}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return output_path


def validate_package_archive(archive_path: Path) -> list[str]:
    """Read-only validation of an already-built `.arya-voice` archive:
    entry allowlist, manifest schema, and checksum -- without extracting
    anything to disk. Returns a list of problems; empty means valid.
    Never raises on a malformed archive -- reports it as a problem
    instead, since a caller validating an untrusted file needs the
    complete list of what is wrong, not an exception on the first one.
    """
    problems: list[str] = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            problems.extend(validate_package_entries(names))
            problems.extend(reject_symlink_entries(archive))
            size_problems = check_entry_sizes(archive)
            if size_problems:
                # A declared-oversized entry must never be decompressed,
                # not even to read manifest.json -- report and stop here.
                problems.extend(size_problems)
                return problems
            if "manifest.json" not in names:
                problems.append("archive contains no manifest.json")
                return problems
            try:
                manifest = json.loads(archive.read("manifest.json"))
            except json.JSONDecodeError as exc:
                problems.append(f"manifest.json is not valid JSON: {exc}")
                return problems
            try:
                validate(manifest, SchemaName.VOICE_PACKAGE_MANIFEST)
            except ValidationError as exc:
                problems.append(f"manifest failed schema validation: {exc}")
                return problems

            model_entries = [n for n in names if n != "manifest.json"]
            declared_checksum = manifest["integrity"]["checksum_sha256"]
            matched = False
            for name in model_entries:
                actual_checksum = hashlib.sha256(archive.read(name)).hexdigest()
                if actual_checksum == declared_checksum:
                    matched = True
                    break
            if not matched:
                problems.append(
                    f"no package entry's checksum matches manifest.integrity.checksum_sha256 {declared_checksum}"
                )
    except zipfile.BadZipFile as exc:
        problems.append(f"not a valid zip archive: {exc}")
    return problems
