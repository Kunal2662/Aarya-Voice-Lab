"""Preview generation history — VL-D5 §17–§20. A persisted, append-only
record of every generation run for a voice profile, mirroring
`pipeline.processing_history`'s pattern exactly (`JsonLinesRegistry`,
schema-validated on write, records keyed by `record_id`, never a
timestamp) applied to generated-output provenance instead of derived-
audio provenance.

**Regeneration never overwrites.** Every generation — the first and
every one after it — appends a new record. `history()` returns the full,
ordered "Generation 1, Generation 2, Generation 3…" trail (§19);
`current()` is only ever the latest entry, never a claim that earlier
ones stopped existing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from aarya_voice_lab import __version__
from aarya_voice_lab.registry.json_registry import JsonLinesRegistry
from aarya_voice_lab.schemas.base import SchemaName

PREVIEW_HISTORY_STAGE_VERSION = "1.0.0"


@dataclass(frozen=True)
class PreviewHistoryRecord:
    record_id: str
    voice_profile_id: str
    request_id: str
    output_id: str
    model_id: str
    config_hash: str
    status: str
    output_sha256: str | None = None
    tool_version: str | None = None
    supersedes: str | None = None
    recorded_at: str | None = None
    stage_version: str = PREVIEW_HISTORY_STAGE_VERSION
    processing_version: str = __version__

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "record_id": self.record_id,
            "voice_profile_id": self.voice_profile_id,
            "request_id": self.request_id,
            "output_id": self.output_id,
            "model_id": self.model_id,
            "config_hash": self.config_hash,
            "status": self.status,
            "output_sha256": self.output_sha256,
            "tool_version": self.tool_version,
            "supersedes": self.supersedes,
            "recorded_at": self.recorded_at or datetime.now(UTC).isoformat(),
            "stage_version": self.stage_version,
            "processing_version": self.processing_version,
        }


class PreviewHistoryLog(JsonLinesRegistry):
    def __init__(self, path):
        super().__init__(path=path, schema_name=SchemaName.PREVIEW_HISTORY, id_field="record_id")


def _next_record_id(log: PreviewHistoryLog) -> str:
    return f"preview-hist-{len(log.list()) + 1:05d}"


def record_generation_result(log: PreviewHistoryLog, item, *, voice_profile_id: str) -> dict[str, Any]:
    """Append one history record from a completed
    `pipeline.generation.GenerationItem`. Never overwrites — a
    regeneration simply appends another record."""
    artifact = item.artifact or {}
    active = current(log, voice_profile_id)
    record = PreviewHistoryRecord(
        record_id=_next_record_id(log),
        voice_profile_id=voice_profile_id,
        request_id=item.request.request_id,
        output_id=artifact.get("preview_id", ""),
        model_id=item.request.model_id,
        config_hash=item.request.config_hash,
        status=item.status.value,
        output_sha256=artifact.get("sha256"),
        tool_version=artifact.get("model_version"),
        supersedes=active["record_id"] if active else None,
    )
    payload = record.to_dict()
    log.add(payload)
    return payload


def history(log: PreviewHistoryLog, voice_profile_id: str) -> list[dict[str, Any]]:
    return [r for r in log.list() if r["voice_profile_id"] == voice_profile_id]


def current(log: PreviewHistoryLog, voice_profile_id: str) -> dict[str, Any] | None:
    records = history(log, voice_profile_id)
    return records[-1] if records else None


def regeneration_count(log: PreviewHistoryLog, voice_profile_id: str) -> int:
    """Every record after the first counts as a regeneration."""
    return max(0, len(history(log, voice_profile_id)) - 1)
