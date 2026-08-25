"""Windows release preparation -- Task 6 of the Phase 4 autonomous
execution plan.

Repository-safe release/packaging metadata and readiness checks only:
no installer binary is generated or invoked here, and nothing here
modifies AARYA Core (a separate, out-of-scope system). See
docs/WINDOWS_RELEASE.md for the full picture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from aarya_voice_lab.core.paths import PROJECT_ROOT

DEFAULT_RELEASE_CONFIG_PATH = PROJECT_ROOT / "configs" / "release.yaml"


class ReleaseConfigError(ValueError):
    """Raised when the release config is missing, malformed, or fails checks."""


@dataclass
class ReleaseMetadata:
    product_name: str
    app_id: str
    version: str
    schema_version: str
    publisher: str
    platform: str
    min_os_version: str
    architecture: str
    data_directories: tuple[str, ...]
    uninstall_protected_directories: tuple[str, ...]
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReleaseMetadata:
        required = [
            "product_name",
            "app_id",
            "version",
            "schema_version",
            "publisher",
            "platform",
            "min_os_version",
            "architecture",
            "data_directories",
            "uninstall_protected_directories",
        ]
        missing = [key for key in required if key not in data]
        if missing:
            raise ReleaseConfigError(f"release config missing required keys: {missing}")
        return cls(
            product_name=data["product_name"],
            app_id=data["app_id"],
            version=data["version"],
            schema_version=data["schema_version"],
            publisher=data["publisher"],
            platform=data["platform"],
            min_os_version=data["min_os_version"],
            architecture=data["architecture"],
            data_directories=tuple(data["data_directories"]),
            uninstall_protected_directories=tuple(data["uninstall_protected_directories"]),
            raw=data,
        )


def load_release_metadata(path: Path | None = None) -> ReleaseMetadata:
    config_path = path or DEFAULT_RELEASE_CONFIG_PATH
    if not config_path.is_file():
        raise ReleaseConfigError(f"release config not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ReleaseConfigError(f"release config must contain a mapping: {config_path}")
    return ReleaseMetadata.from_dict(data)


def validate_release_layout(root: Path, metadata: ReleaseMetadata) -> list[str]:
    """Check that every declared data directory exists (or is creatable)
    under `root` and is writable. Returns a list of problems -- empty
    means the layout is release-ready. Never creates a directory that
    does not already exist; that is a separate, explicit first-run step,
    not something a read-only readiness check should do as a side
    effect."""
    problems: list[str] = []
    for name in metadata.data_directories:
        directory = root / name
        if not directory.exists():
            problems.append(f"{name!r}: does not exist at {directory}")
            continue
        if not directory.is_dir():
            problems.append(f"{name!r}: exists but is not a directory: {directory}")
            continue
        probe = directory / ".release_write_probe"
        try:
            probe.write_text("", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            problems.append(f"{name!r}: not writable: {exc}")
    return problems


def is_safe_to_delete_without_confirmation(directory_name: str, metadata: ReleaseMetadata) -> bool:
    """False for any directory an uninstaller must never remove without
    a separate, explicit user confirmation (it may contain real
    recordings, embeddings, or trained models -- see docs/PRIVACY.md).
    Fails closed: an unrecognised name is also treated as unsafe, never
    assumed removable."""
    if directory_name in metadata.uninstall_protected_directories:
        return False
    return directory_name in metadata.data_directories


@dataclass(frozen=True)
class SchemaCompatibility:
    compatible: bool
    installed_schema_version: str
    code_schema_version: str
    reason: str


def check_schema_compatibility(installed_schema_version: str, code_schema_version: str) -> SchemaCompatibility:
    """Migration safety check: a MAJOR version mismatch between data
    written by a previous release and the currently running code is
    treated as incompatible -- refuse rather than silently attempt to
    read data in a shape the code was never verified against. Minor/
    patch differences are compatible by this project's own schema_version
    convention (see SCHEMA_VERSION's docstring: bump only on an
    incompatible shape change)."""

    def _major(version: str) -> str:
        return version.split(".", 1)[0]

    if _major(installed_schema_version) != _major(code_schema_version):
        return SchemaCompatibility(
            compatible=False,
            installed_schema_version=installed_schema_version,
            code_schema_version=code_schema_version,
            reason=(
                f"major schema version mismatch: installed data is {installed_schema_version}, "
                f"running code is {code_schema_version} -- a migration step is required before proceeding"
            ),
        )
    return SchemaCompatibility(
        compatible=True,
        installed_schema_version=installed_schema_version,
        code_schema_version=code_schema_version,
        reason="major schema version matches",
    )
