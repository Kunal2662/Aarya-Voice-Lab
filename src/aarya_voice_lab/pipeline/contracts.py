"""Filesystem contracts between pipeline stages.

Stages run in different Python environments with mutually incompatible
PyTorch builds, so they cannot call each other. They communicate by
writing artifacts and a stage-result record into a run directory:

    <run_dir>/
        01_inventory/
            result.json        <- stage_result schema
            <stage outputs>
        02_speaker_diarization/
            result.json
            ...

`result.json` is the contract. A downstream stage reads its predecessor's
result, verifies the input hashes, and either proceeds or refuses.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aarya_voice_lab import SCHEMA_VERSION, __version__
from aarya_voice_lab.pipeline.stages import PIPELINE_ORDER, PipelineStage
from aarya_voice_lab.schemas.base import SchemaName, validate

RESULT_FILENAME = "result.json"
#: Read in chunks so hashing a large recording never loads it into memory.
_HASH_CHUNK_BYTES = 1024 * 1024


class StageStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class StageContractError(RuntimeError):
    """Raised when a stage's inputs or predecessor state are unusable."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def describe_artifact(path: Path, run_dir: Path, kind: str | None = None) -> dict[str, Any]:
    """Build an artifact record. `path` is stored relative to `run_dir`.

    Relative paths matter: an absolute path could embed a location inside
    the private source tree, and these records are meant to be safely
    readable and diffable.
    """
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(run_dir.resolve())
    except ValueError:
        relative = Path(resolved.name)
    return {
        "path": str(relative),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
        "kind": kind,
    }


def stage_directory(run_dir: Path, stage: PipelineStage) -> Path:
    index = PIPELINE_ORDER.index(stage)
    return run_dir / f"{index:02d}_{stage.value}"


@dataclass
class StageResult:
    stage: PipelineStage
    environment_id: str
    status: str = StageStatus.PENDING
    tool: str | None = None
    tool_version: str | None = None
    model: str | None = None
    model_version: str | None = None
    processing_version: str = __version__
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str | None = None
    duration_seconds: float | None = None
    hardware: dict[str, Any] = field(default_factory=dict)
    software_versions: dict[str, str] = field(default_factory=dict)
    inputs: list[dict[str, Any]] = field(default_factory=list)
    outputs: list[dict[str, Any]] = field(default_factory=list)
    error: dict[str, Any] | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "stage": self.stage.value,
            "status": self.status,
            "environment_id": self.environment_id,
            "tool": self.tool,
            "tool_version": self.tool_version,
            "model": self.model,
            "model_version": self.model_version,
            "processing_version": self.processing_version,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "hardware": self.hardware,
            "software_versions": self.software_versions,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "error": self.error,
            "notes": self.notes,
        }

    def mark_completed(self) -> None:
        self.status = StageStatus.COMPLETED
        self._finish()

    def mark_failed(self, kind: str, message: str, remediation: str | None = None) -> None:
        self.status = StageStatus.FAILED
        self.error = {"kind": kind, "message": message, "remediation": remediation}
        self._finish()

    def mark_blocked(self, kind: str, message: str, remediation: str | None = None) -> None:
        """A stop condition, not a bug: credentials, gated models, etc."""
        self.status = StageStatus.BLOCKED
        self.error = {"kind": kind, "message": message, "remediation": remediation}
        self._finish()

    def _finish(self) -> None:
        completed = datetime.now(UTC)
        self.completed_at = completed.isoformat()
        started = datetime.fromisoformat(self.started_at)
        self.duration_seconds = max((completed - started).total_seconds(), 0.0)

    def write(self, run_dir: Path) -> Path:
        record = self.to_dict()
        validate(record, SchemaName.STAGE_RESULT)
        directory = stage_directory(run_dir, self.stage)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / RESULT_FILENAME
        path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        return path


def read_stage_result(run_dir: Path, stage: PipelineStage) -> dict[str, Any] | None:
    path = stage_directory(run_dir, stage) / RESULT_FILENAME
    if not path.is_file():
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    validate(record, SchemaName.STAGE_RESULT)
    return record


def is_stage_complete(run_dir: Path, stage: PipelineStage) -> bool:
    record = read_stage_result(run_dir, stage)
    return bool(record and record["status"] == StageStatus.COMPLETED)


def require_predecessor(run_dir: Path, stage: PipelineStage) -> dict[str, Any] | None:
    """Return the previous stage's completed result, or raise.

    Returns None for the first stage, which has no predecessor.
    """
    index = PIPELINE_ORDER.index(stage)
    if index == 0:
        return None
    previous = PIPELINE_ORDER[index - 1]
    record = read_stage_result(run_dir, previous)
    if record is None:
        raise StageContractError(
            f"Stage {stage.value!r} requires {previous.value!r} to have run first, "
            f"but no {RESULT_FILENAME} was found in {stage_directory(run_dir, previous)}"
        )
    if record["status"] != StageStatus.COMPLETED:
        raise StageContractError(
            f"Stage {stage.value!r} requires {previous.value!r} to be completed, "
            f"but its status is {record['status']!r}"
        )
    return record


def verify_inputs_unchanged(run_dir: Path, record: dict[str, Any]) -> list[str]:
    """Re-hash a result's outputs and report any that changed or vanished.

    Used for resumability: if a stage's declared outputs still match their
    recorded hashes, downstream work does not need redoing.
    """
    problems = []
    for artifact in record.get("outputs", []):
        # describe_artifact() stores paths relative to run_dir (already
        # including the stage folder), so resolve against run_dir directly.
        path = run_dir / artifact["path"]
        if not path.is_file():
            problems.append(f"missing output: {artifact['path']}")
            continue
        if sha256_file(path) != artifact["sha256"]:
            problems.append(f"content changed since recorded: {artifact['path']}")
    return problems
