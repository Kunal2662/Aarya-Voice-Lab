"""Processing history — VL-D4 §16, §18. A persisted, append-only record
of every processing run against a recording, mirroring
`pipeline.candidate_review`'s persistence pattern (`JsonLinesRegistry`,
schema-validated on write, never overwritten, an id for identity —
timestamp is recorded for display only) applied to derived-artifact
provenance instead of review decisions.

**A "rollback" (§18: "select previous derived version as active derived
candidate") is never a deletion or an edit.** It is a new
`ProcessingHistoryRecord` whose `output_sha256` equals a prior record's,
with `supersedes` naming the record it displaces as the active version
and `is_rollback=True` marking it as such. Nothing is ever removed from
the log — `history()` still returns every record afterward, in order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from aarya_voice_lab import __version__
from aarya_voice_lab.registry.json_registry import JsonLinesRegistry
from aarya_voice_lab.schemas.base import SchemaName

PROCESSING_HISTORY_STAGE_VERSION = "1.0.0"


@dataclass(frozen=True)
class ProcessingHistoryRecord:
    record_id: str
    recording_id: str
    artifact_id: str
    source_sha256: str
    output_sha256: str | None
    profile_id: str
    profile_name: str
    profile_version: int
    config_hash: str
    status: str
    tool_version: str | None = None
    supersedes: str | None = None
    is_rollback: bool = False
    recorded_at: str | None = None
    stage_version: str = PROCESSING_HISTORY_STAGE_VERSION
    processing_version: str = __version__

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "record_id": self.record_id,
            "recording_id": self.recording_id,
            "artifact_id": self.artifact_id,
            "source_sha256": self.source_sha256,
            "output_sha256": self.output_sha256,
            "profile_id": self.profile_id,
            "profile_name": self.profile_name,
            "profile_version": self.profile_version,
            "config_hash": self.config_hash,
            "status": self.status,
            "tool_version": self.tool_version,
            "supersedes": self.supersedes,
            "is_rollback": self.is_rollback,
            "recorded_at": self.recorded_at or datetime.now(UTC).isoformat(),
            "stage_version": self.stage_version,
            "processing_version": self.processing_version,
        }


class ProcessingHistoryLog(JsonLinesRegistry):
    def __init__(self, path):
        super().__init__(path=path, schema_name=SchemaName.PROCESSING_HISTORY, id_field="record_id")


def _next_record_id(log: ProcessingHistoryLog) -> str:
    return f"proc-hist-{len(log.list()) + 1:05d}"


def record_processing_result(log: ProcessingHistoryLog, item, *, supersedes: str | None = None) -> dict[str, Any]:
    """Append one history record from a completed `ProcessingItem`
    (`pipeline.processing.ProcessingItem`). Never overwrites — a
    re-processed recording simply appends another record."""
    artifact = item.derived_artifact or {}
    record = ProcessingHistoryRecord(
        record_id=_next_record_id(log),
        recording_id=item.recording_id,
        artifact_id=artifact.get("artifact_id", ""),
        source_sha256=item.source_sha256,
        output_sha256=artifact.get("output_sha256"),
        profile_id=item.profile.profile_id,
        profile_name=item.profile.name,
        profile_version=item.profile.version,
        config_hash=item.profile.config_hash(),
        status=item.status.value,
        tool_version=(artifact.get("fingerprint") or {}).get("tool_version"),
        supersedes=supersedes,
    )
    payload = record.to_dict()
    log.add(payload)
    return payload


def history(log: ProcessingHistoryLog, recording_id: str) -> list[dict[str, Any]]:
    return [r for r in log.list() if r["recording_id"] == recording_id]


def current(log: ProcessingHistoryLog, recording_id: str) -> dict[str, Any] | None:
    records = history(log, recording_id)
    return records[-1] if records else None


class RollbackTargetNotFound(KeyError):
    """Raised when `rollback()` is asked to roll back to a record id that
    does not exist, or does not belong to the given recording."""


def rollback(log: ProcessingHistoryLog, recording_id: str, *, to_record_id: str) -> dict[str, Any]:
    """Append a new record making `to_record_id`'s derived output active
    again, without touching `to_record_id` or anything recorded after it.
    """
    target = log.get(to_record_id)
    if target is None or target["recording_id"] != recording_id:
        raise RollbackTargetNotFound(to_record_id)

    active = current(log, recording_id)
    record = ProcessingHistoryRecord(
        record_id=_next_record_id(log),
        recording_id=recording_id,
        artifact_id=target["artifact_id"],
        source_sha256=target["source_sha256"],
        output_sha256=target["output_sha256"],
        profile_id=target["profile_id"],
        profile_name=target["profile_name"],
        profile_version=target["profile_version"],
        config_hash=target["config_hash"],
        status=target["status"],
        tool_version=target["tool_version"],
        supersedes=active["record_id"] if active else None,
        is_rollback=True,
    )
    payload = record.to_dict()
    log.add(payload)
    return payload
