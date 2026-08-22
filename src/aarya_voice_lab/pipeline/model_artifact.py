"""Real Voice Model Engine milestone — checksum-addressable model artifacts.

Mirrors `pipeline.import_intake`'s content-addressed pattern (the caller-
supplied name is never trusted as identity) and `JsonLinesRegistry.add()`'s
refuse-to-overwrite discipline: an artifact's identity is its checksum,
never its filename, and a second write of an artifact that already
exists under that checksum is refused rather than silently replacing it.

An artifact record never embeds the file's bytes and never embeds a raw,
unreviewed download — `ArtifactStore.save()` only ever writes bytes the
caller already has in memory (the output of a real, local
training/export step). This module does not fetch anything from the
network and does not execute anything it stores.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from aarya_voice_lab.core.data_root import DataRoot, assert_source_writable
from aarya_voice_lab.pipeline.model_lifecycle import ModelLifecycleState


class ModelArtifactFormat(StrEnum):
    """Deliberately narrow. A format absent from this list must not be
    silently accepted -- `ArtifactStore.save()` raises for one."""

    ONNX = "onnx"
    SAFETENSORS = "safetensors"
    PYTORCH_STATE_DICT = "pytorch_state_dict"
    NEMO_CHECKPOINT = "nemo_checkpoint"
    RAW_AUDIO_WAV = "raw_audio_wav"
    JSON_METADATA = "json_metadata"


class ModelArtifactType(StrEnum):
    EMBEDDING_MODEL_WEIGHTS = "embedding_model_weights"
    GENERATION_MODEL_WEIGHTS = "generation_model_weights"
    TRAINING_CHECKPOINT = "training_checkpoint"
    GENERATED_AUDIO = "generated_audio"
    EVALUATION_REPORT = "evaluation_report"


class ArtifactError(RuntimeError):
    """Raised for an artifact operation that cannot proceed safely."""


class ArtifactIntegrityError(ArtifactError):
    """Raised when a loaded artifact's bytes do not match its recorded
    checksum -- the file was corrupted, truncated, or tampered with."""


@dataclass(frozen=True)
class ModelArtifact:
    """Metadata for one stored artifact. Never carries the bytes."""

    artifact_id: str
    checksum_sha256: str
    size_bytes: int
    artifact_format: ModelArtifactFormat
    artifact_type: ModelArtifactType
    model_name: str
    model_version: str
    provider_name: str
    lifecycle_state: ModelLifecycleState
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    source_job_id: str | None = None
    source_dataset_id: str | None = None
    #: e.g. {"sample_rate": 16000, "embedding_dimension": 192} -- whatever
    #: a consumer needs to check before trying to load this artifact.
    compatibility_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "checksum_sha256": self.checksum_sha256,
            "size_bytes": self.size_bytes,
            "artifact_format": self.artifact_format.value,
            "artifact_type": self.artifact_type.value,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "provider_name": self.provider_name,
            "lifecycle_state": self.lifecycle_state.value,
            "created_at": self.created_at,
            "source_job_id": self.source_job_id,
            "source_dataset_id": self.source_dataset_id,
            "compatibility_metadata": dict(self.compatibility_metadata),
        }


def artifact_id_from_checksum(checksum_sha256: str) -> str:
    return f"artifact-{checksum_sha256[:16]}"


class ArtifactStore:
    """Protected, checksum-addressed storage under `data/model_artifacts/`.

    Storage layout: `<artifact_id>.bin` (the bytes) plus
    `<artifact_id>.meta.json` (the `ModelArtifact` record) — the same
    vector+sidecar shape `identity.embeddings.EmbeddingStore` already
    uses, applied to a general byte payload instead of a fixed-length
    float vector.
    """

    def __init__(self, data_root: DataRoot):
        self.data_root = data_root
        self.directory = data_root.model_artifacts

    def _bin_path(self, artifact_id: str) -> Path:
        return self.directory / f"{artifact_id}.bin"

    def _meta_path(self, artifact_id: str) -> Path:
        return self.directory / f"{artifact_id}.meta.json"

    def save(
        self,
        payload: bytes,
        *,
        artifact_format: ModelArtifactFormat,
        artifact_type: ModelArtifactType,
        model_name: str,
        model_version: str,
        provider_name: str,
        lifecycle_state: ModelLifecycleState = ModelLifecycleState.DRAFT,
        source_job_id: str | None = None,
        source_dataset_id: str | None = None,
        compatibility_metadata: dict[str, Any] | None = None,
    ) -> ModelArtifact:
        checksum = hashlib.sha256(payload).hexdigest()
        artifact_id = artifact_id_from_checksum(checksum)
        bin_path = self._bin_path(artifact_id)
        meta_path = self._meta_path(artifact_id)

        assert_source_writable(self.data_root, bin_path)
        if bin_path.is_file() or meta_path.is_file():
            raise ArtifactError(
                f"artifact {artifact_id!r} (checksum {checksum}) already exists — "
                "refusing to overwrite; artifact identity is its checksum, not its filename"
            )

        self.directory.mkdir(parents=True, exist_ok=True)
        record = ModelArtifact(
            artifact_id=artifact_id,
            checksum_sha256=checksum,
            size_bytes=len(payload),
            artifact_format=artifact_format,
            artifact_type=artifact_type,
            model_name=model_name,
            model_version=model_version,
            provider_name=provider_name,
            lifecycle_state=lifecycle_state,
            source_job_id=source_job_id,
            source_dataset_id=source_dataset_id,
            compatibility_metadata=compatibility_metadata or {},
        )
        bin_path.write_bytes(payload)
        meta_path.write_text(json.dumps(record.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        return record

    def load_metadata(self, artifact_id: str) -> ModelArtifact:
        meta_path = self._meta_path(artifact_id)
        if not meta_path.is_file():
            raise ArtifactError(f"artifact {artifact_id!r} not found in {self.directory}")
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return ModelArtifact(
            artifact_id=data["artifact_id"],
            checksum_sha256=data["checksum_sha256"],
            size_bytes=data["size_bytes"],
            artifact_format=ModelArtifactFormat(data["artifact_format"]),
            artifact_type=ModelArtifactType(data["artifact_type"]),
            model_name=data["model_name"],
            model_version=data["model_version"],
            provider_name=data["provider_name"],
            lifecycle_state=ModelLifecycleState(data["lifecycle_state"]),
            created_at=data["created_at"],
            source_job_id=data.get("source_job_id"),
            source_dataset_id=data.get("source_dataset_id"),
            compatibility_metadata=data.get("compatibility_metadata", {}),
        )

    def load_bytes(self, artifact_id: str) -> bytes:
        """Load and verify. Never returns bytes that fail their own
        recorded checksum -- a mismatch means corruption or tampering,
        and this must never be silently trusted."""
        record = self.load_metadata(artifact_id)
        bin_path = self._bin_path(artifact_id)
        if not bin_path.is_file():
            raise ArtifactError(f"artifact {artifact_id!r} has metadata but no stored bytes in {self.directory}")
        payload = bin_path.read_bytes()
        actual = hashlib.sha256(payload).hexdigest()
        if actual != record.checksum_sha256:
            raise ArtifactIntegrityError(
                f"artifact {artifact_id!r} failed integrity check: "
                f"recorded checksum {record.checksum_sha256}, actual {actual}"
            )
        return payload

    def exists(self, artifact_id: str) -> bool:
        return self._meta_path(artifact_id).is_file()

    def list_ids(self) -> list[str]:
        if not self.directory.is_dir():
            return []
        return sorted(p.stem.removesuffix(".meta") for p in self.directory.glob("*.meta.json"))

    def delete(self, artifact_id: str) -> bool:
        removed = False
        for path in (self._bin_path(artifact_id), self._meta_path(artifact_id)):
            if path.is_file():
                path.unlink()
                removed = True
        return removed
