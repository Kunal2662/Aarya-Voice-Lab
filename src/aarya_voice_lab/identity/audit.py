"""Append-only audit log for identity operations.

This is the record that answers "why is this segment in the dataset?"
months later, and "what happened to that embedding?" after it is gone.

Append-only in the sense that matters: entries are only ever added, each
one chains to the previous by hash, and nothing in this module can edit
or remove an entry. A tampered or truncated log is *detectable* via
`verify_chain()` — it is not cryptographically prevented, which would
need an external notary. The distinction is stated rather than glossed:
this defends against accident and silent corruption, not a determined
attacker with write access.

Deletion entries matter especially. When an embedding is destroyed, the
record of its destruction must outlive it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from aarya_voice_lab import __version__
from aarya_voice_lab.core.data_root import DataRoot, assert_source_writable

AUDIT_LOG_VERSION = "1.0.0"
GENESIS_HASH = "0" * 64


class AuditEventType(StrEnum):
    ENROLLMENT_CREATED = "enrollment_created"
    ENROLLMENT_SUPERSEDED = "enrollment_superseded"
    PROFILE_REVOKED = "profile_revoked"
    EMBEDDING_CREATED = "embedding_created"
    EMBEDDING_DELETED = "embedding_deleted"
    VERIFICATION_RUN = "verification_run"
    REVIEW_DECISION = "review_decision"
    CALIBRATION_CREATED = "calibration_created"
    THRESHOLD_CHANGED = "threshold_changed"
    DATASET_BUILT = "dataset_built"
    GATE_EVALUATED = "gate_evaluated"
    ACCESS_DENIED = "access_denied"


@dataclass
class AuditEntry:
    sequence: int
    event_type: AuditEventType
    actor: str
    subject_id: str
    detail: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    previous_hash: str = GENESIS_HASH
    processing_version: str = __version__
    audit_version: str = AUDIT_LOG_VERSION

    def payload(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "actor": self.actor,
            "subject_id": self.subject_id,
            "detail": self.detail,
            "timestamp": self.timestamp,
            "previous_hash": self.previous_hash,
            "processing_version": self.processing_version,
            "audit_version": self.audit_version,
        }

    def entry_hash(self) -> str:
        raw = json.dumps(self.payload(), sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**self.payload(), "entry_hash": self.entry_hash()}


class AuditLog:
    """Hash-chained JSON Lines audit log under `data/audit/`."""

    def __init__(self, data_root: DataRoot, name: str = "identity"):
        self.data_root = data_root
        self.directory = data_root.root / "audit"
        self.path: Path = self.directory / f"{name}.jsonl"

    def append(
        self,
        event_type: AuditEventType,
        *,
        actor: str,
        subject_id: str,
        detail: dict[str, Any] | None = None,
    ) -> AuditEntry:
        assert_source_writable(self.data_root, self.path)
        self.directory.mkdir(parents=True, exist_ok=True)

        entries = self.read_all()
        entry = AuditEntry(
            sequence=len(entries) + 1,
            event_type=event_type,
            actor=actor,
            subject_id=subject_id,
            detail=self._sanitise(detail or {}),
            previous_hash=entries[-1]["entry_hash"] if entries else GENESIS_HASH,
        )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.to_dict(), sort_keys=True) + "\n")
        return entry

    @staticmethod
    def _sanitise(detail: dict[str, Any]) -> dict[str, Any]:
        """Strip anything that must never reach a log.

        An audit log is read, copied, and pasted into issue reports. A raw
        embedding vector or an absolute path into private storage must not
        be able to travel that way.
        """
        forbidden = {"values", "vector", "embedding", "samples", "audio", "waveform"}
        cleaned: dict[str, Any] = {}
        for key, value in detail.items():
            if key.lower() in forbidden:
                cleaned[key] = "<redacted: never logged>"
            elif isinstance(value, str) and value.startswith("/"):
                cleaned[key] = f"<absolute path redacted: {Path(value).name}>"
            elif isinstance(value, dict):
                cleaned[key] = AuditLog._sanitise(value)
            else:
                cleaned[key] = value
        return cleaned

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        entries = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                entries.append(json.loads(line))
        return entries

    def verify_chain(self) -> tuple[bool, list[str]]:
        """Check the hash chain. Returns (intact, problems)."""
        problems: list[str] = []
        previous = GENESIS_HASH
        for index, raw in enumerate(self.read_all(), start=1):
            stored_hash = raw.pop("entry_hash", None)
            recomputed = hashlib.sha256(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()
            if stored_hash != recomputed:
                problems.append(f"entry {index}: content does not match its recorded hash")
            if raw.get("previous_hash") != previous:
                problems.append(f"entry {index}: chain broken — previous_hash does not match entry {index - 1}")
            if raw.get("sequence") != index:
                problems.append(f"entry {index}: sequence number is {raw.get('sequence')}")
            previous = stored_hash or recomputed
        return (not problems), problems

    def filter(self, event_type: AuditEventType | None = None, subject_id: str | None = None):
        entries = self.read_all()
        if event_type is not None:
            entries = [e for e in entries if e["event_type"] == event_type.value]
        if subject_id is not None:
            entries = [e for e in entries if e["subject_id"] == subject_id]
        return entries

    def history_for(self, subject_id: str) -> list[dict[str, Any]]:
        """Everything that ever happened to one subject."""
        return self.filter(subject_id=subject_id)

    def summary(self) -> dict[str, Any]:
        entries = self.read_all()
        counts: dict[str, int] = {}
        for entry in entries:
            counts[entry["event_type"]] = counts.get(entry["event_type"], 0) + 1
        intact, problems = self.verify_chain()
        return {
            "entry_count": len(entries),
            "event_counts": counts,
            "chain_intact": intact,
            "chain_problems": problems,
            "first_entry": entries[0]["timestamp"] if entries else None,
            "last_entry": entries[-1]["timestamp"] if entries else None,
        }
