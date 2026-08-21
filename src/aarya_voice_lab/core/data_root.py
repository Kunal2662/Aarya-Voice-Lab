"""The `data/` root: where source, derived artifacts, and reports live.

Layout:

    data/
      source/      READ-ONLY originals. Never written, never deleted.
      working/     Derived intermediates (normalized audio, analyses).
      segments/    Derived candidate audio.
      manifests/   Machine-readable stage contracts.
      reports/     Human-readable summaries.
      review/      Manual-review metadata (no audio unless requested).
      cache/       Disposable; never committed.
      embeddings/  Phase 3 biometric vectors. Never committed, never exported.
      enrollment/  Phase 3 speaker profiles.
      audit/       Phase 3 append-only identity audit log.
      previews/    VL-D5 generated preview audio (synthetic only today).
      calibration/ VL-D7 calibration engine profiles (hardware snapshots,
                   proposed parameters, provenance -- never audio, never
                   embeddings, never speaker identity).

Everything under `data/` is git-ignored except the README. `source/` is
additionally protected in code: `assert_source_writable` refuses any
write, and the inventory stage refuses to read it without an explicit
approval flag.

Batches (`batch-001`, `batch-002`, …) exist so future recordings can be
added without reprocessing or redesigning anything. Nothing is designed
around a fixed count of files.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aarya_voice_lab import __version__
from aarya_voice_lab.core.paths import PROJECT_ROOT

DATA_ROOT_NAME = "data"
BATCH_ID_PATTERN = re.compile(r"^batch-\d{3,}$")

#: Subdirectories of the data root, and whether they are writable.
SOURCE_DIR = "source"
WORKING_DIR = "working"
SEGMENTS_DIR = "segments"
MANIFESTS_DIR = "manifests"
REPORTS_DIR = "reports"
REVIEW_DIR = "review"
CACHE_DIR = "cache"
EMBEDDINGS_DIR = "embeddings"
ENROLLMENT_DIR = "enrollment"
AUDIT_DIR = "audit"
PREVIEWS_DIR = "previews"
CALIBRATION_DIR = "calibration"

DATA_SUBDIRECTORIES: tuple[str, ...] = (
    SOURCE_DIR,
    WORKING_DIR,
    SEGMENTS_DIR,
    MANIFESTS_DIR,
    REPORTS_DIR,
    REVIEW_DIR,
    CACHE_DIR,
    EMBEDDINGS_DIR,
    ENROLLMENT_DIR,
    AUDIT_DIR,
    PREVIEWS_DIR,
    CALIBRATION_DIR,
)

#: The one directory the pipeline must never write to.
READ_ONLY_SUBDIRECTORIES: frozenset[str] = frozenset({SOURCE_DIR})


class SourceImmutabilityError(PermissionError):
    """Raised when an operation would write into the source tree."""


class InvalidBatchIdError(ValueError):
    """Raised for a batch id that does not match `batch-NNN`."""


@dataclass(frozen=True)
class DataRoot:
    """Resolved paths for one data root."""

    root: Path

    @classmethod
    def default(cls, project_root: Path | None = None) -> DataRoot:
        return cls(root=(project_root or PROJECT_ROOT) / DATA_ROOT_NAME)

    @property
    def source(self) -> Path:
        return self.root / SOURCE_DIR

    @property
    def working(self) -> Path:
        return self.root / WORKING_DIR

    @property
    def segments(self) -> Path:
        return self.root / SEGMENTS_DIR

    @property
    def manifests(self) -> Path:
        return self.root / MANIFESTS_DIR

    @property
    def reports(self) -> Path:
        return self.root / REPORTS_DIR

    @property
    def review(self) -> Path:
        return self.root / REVIEW_DIR

    @property
    def cache(self) -> Path:
        return self.root / CACHE_DIR

    @property
    def embeddings(self) -> Path:
        """Biometric vectors. Git-ignored; never exported."""
        return self.root / EMBEDDINGS_DIR

    @property
    def enrollment(self) -> Path:
        """Speaker profiles. Git-ignored: naming which segments a human
        identified as a specific person is sensitive even without the vector."""
        return self.root / ENROLLMENT_DIR

    @property
    def audit(self) -> Path:
        return self.root / AUDIT_DIR

    @property
    def previews(self) -> Path:
        """Generated preview audio (VL-D5). Synthetic only until a real
        generation backend and the dataset access gate both exist."""
        return self.root / PREVIEWS_DIR

    @property
    def calibration(self) -> Path:
        """VL-D7 calibration engine profiles: hardware snapshots and
        proposed runtime parameters, never audio or biometric material."""
        return self.root / CALIBRATION_DIR

    def create(self) -> DataRoot:
        """Create the writable directories. Does NOT create `source/` —
        the operator places originals there deliberately."""
        for name in DATA_SUBDIRECTORIES:
            if name not in READ_ONLY_SUBDIRECTORIES:
                (self.root / name).mkdir(parents=True, exist_ok=True)
        return self

    # -- batch-scoped paths -------------------------------------------------

    def batch_source(self, batch_id: str) -> Path:
        return self.source / validate_batch_id(batch_id)

    def batch_working(self, batch_id: str) -> Path:
        return self.working / validate_batch_id(batch_id)

    def batch_segments(self, batch_id: str) -> Path:
        return self.segments / validate_batch_id(batch_id)

    def batch_manifests(self, batch_id: str) -> Path:
        return self.manifests / validate_batch_id(batch_id)

    def batch_run_dir(self, batch_id: str) -> Path:
        """Where stage results for a batch are written."""
        return self.working / validate_batch_id(batch_id) / "run"

    def is_within_source(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            return False
        source = self.source.resolve() if self.source.exists() else self.source
        return resolved == source or source in resolved.parents


def validate_batch_id(batch_id: str) -> str:
    if not BATCH_ID_PATTERN.match(batch_id):
        raise InvalidBatchIdError(
            f"Invalid batch id {batch_id!r}: expected 'batch-NNN' (e.g. 'batch-001')"
        )
    return batch_id


def next_batch_id(existing: list[str]) -> str:
    """Return the next unused batch id, so new recordings can be added
    without touching earlier batches."""
    numbers = [int(b.split("-", 1)[1]) for b in existing if BATCH_ID_PATTERN.match(b)]
    return f"batch-{max(numbers, default=0) + 1:03d}"


def assert_source_writable(data_root: DataRoot, destination: Path) -> None:
    """Refuse any write that would land inside `source/`.

    Originals are irreplaceable: the speaker is deceased and the
    recordings cannot be remade. This check is called by every stage that
    writes an artifact, so a path bug cannot silently overwrite one.
    """
    if data_root.is_within_source(destination):
        raise SourceImmutabilityError(
            f"Refusing to write to {destination}: source recordings are immutable. "
            "Derived artifacts belong in data/working/ or data/segments/."
        )


@dataclass
class BatchMetadata:
    batch_id: str
    created_at: str
    processing_version: str
    source_file_count: int = 0
    status: str = "created"
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "created_at": self.created_at,
            "processing_version": self.processing_version,
            "source_file_count": self.source_file_count,
            "status": self.status,
            "notes": self.notes,
        }


def create_batch(
    data_root: DataRoot,
    batch_id: str,
    *,
    source_file_count: int = 0,
    notes: str | None = None,
) -> BatchMetadata:
    validate_batch_id(batch_id)
    metadata = BatchMetadata(
        batch_id=batch_id,
        created_at=datetime.now(UTC).isoformat(),
        processing_version=__version__,
        source_file_count=source_file_count,
        notes=notes,
    )
    directory = data_root.batch_manifests(batch_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "batch.json").write_text(
        json.dumps(metadata.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
    )
    return metadata


def read_batch(data_root: DataRoot, batch_id: str) -> BatchMetadata | None:
    path = data_root.batch_manifests(batch_id) / "batch.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return BatchMetadata(**data)


def list_batches(data_root: DataRoot) -> list[str]:
    if not data_root.manifests.is_dir():
        return []
    return sorted(
        p.name for p in data_root.manifests.iterdir() if p.is_dir() and BATCH_ID_PATTERN.match(p.name)
    )
