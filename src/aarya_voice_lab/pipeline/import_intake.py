"""VL-D2 — bulk import intake: bringing external files into `source/`.

Phase 2's `pipeline.inventory` and `core.data_root` already implement
almost everything a bulk importer needs — content hashing, magic-byte
detection (never trusting extensions), zero-byte/corrupt/unsupported
detection, duplicate-by-content detection, and persisted, restart-safe
batch metadata. This module does not reimplement any of that. What it
adds is the one thing Phase 2 never needed: a controlled way to *write*
external files into `data/source/<batch-id>/` in the first place. Every
prior stage assumed `source/` was already populated by a human, out of
band.

Writing into `source/` is normally forbidden outright —
`core.data_root.assert_source_writable` exists specifically to stop that.
This module is the single, narrow, sanctioned exception, and it earns
that exception by construction rather than by an override flag:

  * the destination filename is always `<sha256><ext>` — never the
    caller-supplied filename — so a hostile or accidental path like
    `"../../../etc/passwd"` or `"..\\..\\secrets.wav"` can never influence
    where a byte lands (there is no path separator in a hex digest);
  * the write uses exclusive creation ("xb"): a destination that already
    exists is never overwritten, only recognised as a duplicate;
  * nothing here ever renames, edits, or deletes a file that has already
    landed in `source/` — once written, it is exactly as immutable as
    every other source recording.

One malformed file must never abort a batch (VL-D2 §5): every item is
processed independently, and an unexpected exception on one item marks
that item FAILED and lets the queue continue.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from aarya_voice_lab.audio.filetype import ContainerFormat, detect_type
from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.pipeline.contracts import sha256_file
from aarya_voice_lab.pipeline.dataset_gate import DatasetAccessDenied, GateReport
from aarya_voice_lab.pipeline.inventory import probe_wav_quietly  # reuse, don't reimplement
from aarya_voice_lab.schemas.base import SchemaName, validate

#: Canonical extension for a stored, content-addressed file. Derived only
#: from the DETECTED container — never from the caller's claimed
#: extension, which is exactly the thing this project refuses to trust.
_STORED_EXTENSION: dict[ContainerFormat, str] = {
    ContainerFormat.WAV: ".wav",
    ContainerFormat.MP3: ".mp3",
    ContainerFormat.FLAC: ".flac",
    ContainerFormat.OGG: ".ogg",
    ContainerFormat.MP4: ".m4a",
    ContainerFormat.AIFF: ".aiff",
    ContainerFormat.AMR: ".amr",
    ContainerFormat.MATROSKA: ".mkv",
    ContainerFormat.CAF: ".caf",
}


class ImportSource(StrEnum):
    LOCAL_FILES = "local_files"
    LOCAL_FOLDER = "local_folder"


class ImportItemStatus(StrEnum):
    QUEUED = "queued"
    SCANNING = "scanning"
    HASHING = "hashing"
    VALIDATING = "validating"
    ACCEPTED = "accepted"
    WARNING = "warning"
    INVALID = "invalid"
    BLOCKED = "blocked"
    DUPLICATE = "duplicate"
    FAILED = "failed"
    CANCELLED = "cancelled"


#: States a retry or cancel can legally act on.
RETRYABLE_STATUSES = frozenset({ImportItemStatus.FAILED, ImportItemStatus.INVALID, ImportItemStatus.BLOCKED})
TERMINAL_STATUSES = frozenset(
    {
        ImportItemStatus.ACCEPTED,
        ImportItemStatus.WARNING,
        ImportItemStatus.INVALID,
        ImportItemStatus.BLOCKED,
        ImportItemStatus.DUPLICATE,
        ImportItemStatus.FAILED,
        ImportItemStatus.CANCELLED,
    }
)


@dataclass
class ImportItem:
    """One file moving through the import queue.

    `original_filename` is kept for display only — it is never used to
    build a filesystem path. No absolute host path is ever stored on
    this object; the caller's `Path` stays local to the queue that
    enqueued it (see `ImportQueue._paths`), matching VL-D2 §11's "persist
    relative paths only."
    """

    item_id: str
    original_filename: str
    declared_extension: str | None
    size_bytes: int | None = None
    detected_container: str | None = None
    sha256: str | None = None
    content_id: str | None = None
    status: str = ImportItemStatus.QUEUED
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duplicate_of: str | None = None
    #: Relative to the data root once accepted and copied. None until then.
    #: Always POSIX-style (forward slashes), regardless of host OS -- this
    #: is a serialized manifest field (schemas/import_manifest.schema.json)
    #: read by both the Python backend and the JS frontend, so it must be
    #: a stable, canonical string, never the host platform's native
    #: separator.
    stored_relative_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "original_filename": self.original_filename,
            "declared_extension": self.declared_extension,
            "size_bytes": self.size_bytes,
            "detected_container": self.detected_container,
            "sha256": self.sha256,
            "content_id": self.content_id,
            "status": self.status,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "duplicate_of": self.duplicate_of,
            "stored_relative_path": self.stored_relative_path,
        }


def find_existing_content(data_root: DataRoot, sha256: str) -> str | None:
    """Return the batch id that already holds this content, if any.

    Cheap by construction: every accepted file is stored as
    `<sha256><ext>`, so finding a duplicate across every batch ever
    imported is a filename glob, not a re-hash of the whole dataset.
    """
    if not data_root.source.is_dir():
        return None
    for match in data_root.source.glob(f"*/{sha256}.*"):
        # match.parent.name is the batch id (data_root.source / batch-NNN / <hash>.ext)
        return match.parent.name
    return None


def _extension_for(container: ContainerFormat) -> str:
    return _STORED_EXTENSION.get(container, "")


class ImportQueue:
    """A bulk-import run against one batch.

    Construction never touches the filesystem beyond what `enqueue`
    needs to stat each path lazily during processing — enqueueing is
    just bookkeeping. `process_all()` is where files are actually read,
    hashed, and (if accepted) copied.
    """

    def __init__(
        self,
        *,
        data_root: DataRoot,
        batch_id: str,
        source: ImportSource,
        is_synthetic: bool = True,
        gate_report: GateReport | None = None,
    ) -> None:
        if not is_synthetic:
            # Mirrors the same enforcement pipeline.dataset_gate already
            # provides elsewhere — this module does not define a second,
            # weaker gate. A real-recording import with no allowed gate
            # report is refused outright, not silently downgraded.
            if gate_report is None or not gate_report.allowed:
                raise DatasetAccessDenied(
                    "Refusing a non-synthetic import: the dataset access gate is not satisfied. "
                    "See aarya_voice_lab.pipeline.dataset_gate.evaluate_gate()."
                )
        self.data_root = data_root
        self.batch_id = batch_id
        self.source = source
        self.is_synthetic = is_synthetic
        self.items: dict[str, ImportItem] = {}
        self._paths: dict[str, Path] = {}

    def enqueue(self, path: Path) -> ImportItem:
        item_id = f"import-{len(self.items) + 1:04d}"
        item = ImportItem(
            item_id=item_id,
            original_filename=path.name,
            declared_extension=path.suffix.lower() or None,
        )
        self.items[item_id] = item
        self._paths[item_id] = path
        return item

    def cancel(self, item_id: str) -> bool:
        """Cancel a not-yet-processed item. Returns False once processing began."""
        item = self.items[item_id]
        if item.status is not ImportItemStatus.QUEUED:
            return False
        item.status = ImportItemStatus.CANCELLED
        return True

    def retry(self, item_id: str) -> bool:
        """Re-run one item that previously failed/was invalid/was blocked."""
        item = self.items[item_id]
        if item.status not in RETRYABLE_STATUSES:
            return False
        item.status = ImportItemStatus.QUEUED
        item.errors.clear()
        item.warnings.clear()
        item.duplicate_of = None
        item.stored_relative_path = None
        self._process_one(item_id)
        return True

    def process_all(self) -> None:
        """Process every still-QUEUED item. Cancelled items are skipped.

        One item's exception never stops the loop — see `_process_one`.
        """
        for item_id, item in self.items.items():
            if item.status is ImportItemStatus.QUEUED:
                self._process_one(item_id)

    def _process_one(self, item_id: str) -> None:  # noqa: C901 - linear state walk, not deep nesting
        item = self.items[item_id]
        path = self._paths[item_id]
        try:
            item.status = ImportItemStatus.SCANNING
            if not path.is_file():
                item.status = ImportItemStatus.FAILED
                item.errors.append("source file no longer exists")
                return
            size = path.stat().st_size
            item.size_bytes = size
            if size == 0:
                item.status = ImportItemStatus.BLOCKED
                item.errors.append("zero-byte file")
                return

            item.status = ImportItemStatus.HASHING
            digest = sha256_file(path)
            item.sha256 = digest
            item.content_id = f"src-{digest[:16]}"

            item.status = ImportItemStatus.VALIDATING
            detected = detect_type(path)
            item.detected_container = detected.container.value
            if detected.extension_mismatch:
                item.warnings.append(
                    f"extension {item.declared_extension!r} does not match detected "
                    f"container {detected.container.value!r} — extension is display-only, "
                    "never trusted for identity or routing"
                )

            if detected.container is ContainerFormat.UNKNOWN:
                item.status = ImportItemStatus.INVALID
                item.errors.append("content does not match a known audio container")
                return
            if not detected.supported:
                item.status = ImportItemStatus.BLOCKED
                item.errors.append(f"container {detected.container.value!r} is not supported")
                return
            if detected.container is ContainerFormat.WAV and not probe_wav_quietly(path):
                item.status = ImportItemStatus.INVALID
                item.errors.append("WAV headers could not be read; file may be corrupt or truncated")
                return

            # Items in this same queue are processed sequentially, and an
            # accepted item is written to disk before the loop moves on
            # (see process_all), so a same-run duplicate is already
            # visible to find_existing_content by the time its sibling is
            # checked — one lookup covers both the within-run and
            # cross-batch cases. (A future concurrent/parallel processing
            # mode would need an additional in-memory pending-hash index
            # here, since two items could then be hashed before either
            # has written its file.)
            existing_batch = find_existing_content(self.data_root, digest)
            if existing_batch:
                item.status = ImportItemStatus.DUPLICATE
                item.duplicate_of = existing_batch
                return

            destination = self.data_root.batch_source(self.batch_id) / f"{digest}{_extension_for(detected.container)}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                with path.open("rb") as src, destination.open("xb") as dst:
                    shutil.copyfileobj(src, dst)
            except FileExistsError:
                # Lost a race with a concurrent identical import, or the
                # file was already present from an interrupted prior run —
                # either way this is the same content, already stored.
                item.status = ImportItemStatus.DUPLICATE
                item.duplicate_of = self.batch_id
                return

            item.stored_relative_path = destination.relative_to(self.data_root.root).as_posix()
            item.status = ImportItemStatus.WARNING if item.warnings else ImportItemStatus.ACCEPTED
        except Exception as exc:  # noqa: BLE001 - failure isolation is the whole point of this catch
            item.status = ImportItemStatus.FAILED
            item.errors.append(f"{type(exc).__name__}: {exc}")

    # -- views ---------------------------------------------------------

    def by_status(self, status: str) -> list[ImportItem]:
        return [item for item in self.items.values() if item.status == status]

    def counts(self) -> dict[str, int]:
        counts = dict.fromkeys(ImportItemStatus, 0)
        for item in self.items.values():
            counts[ImportItemStatus(item.status)] += 1
        return {status.value: count for status, count in counts.items()}

    def to_manifest(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "source": self.source.value,
            "is_synthetic": self.is_synthetic,
            "items": [item.to_dict() for item in self.items.values()],
            "counts": self.counts(),
        }


def write_import_manifest(queue: ImportQueue, path: Path) -> Path:
    manifest = queue.to_manifest()
    validate(manifest, SchemaName.IMPORT_MANIFEST)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return path
