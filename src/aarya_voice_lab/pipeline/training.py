"""Real Voice Model Engine milestone — training job architecture.

Mirrors `pipeline.generation.GenerationQueue`'s shape (sequential
processing, one broad `except Exception` per item so one job's failure
can never corrupt the queue, real wall-clock duration measurement) but
for the richer training lifecycle VL-D5/VL-D8's generation queue never
needed: QUEUED -> VALIDATING -> PREPARING -> TRAINING -> CHECKPOINTING ->
EVALUATING -> COMPLETED, with explicit FAILED/CANCELLED/TIMEOUT states
and machine-readable failure reasons.

`TrainingProvider` is the abstraction real training backends implement.
`LocalTrainingProvider` is the only concrete implementation this
milestone ships: it performs *real* capability detection (checks whether
a local training runtime is actually importable in this interpreter) and
is honest about the result. **No environment this project's own
documentation currently ships (see `requirements/`, `docs/NEMO.md`,
`docs/TTS_MODELS.md`) has been installed — installing one is an
explicitly separate, approval-gated step (see `configs/default.yaml`'s
`environments.env-tts.requires_approval`).** So in this environment
`LocalTrainingProvider` always reports `NOT_CONFIGURED` and every job it
processes fails with `TrainingFailureReason.MODEL_UNAVAILABLE` — this is
the honest, correct outcome, not a bug, and no fabricated progress or
fake completion is ever produced. The provider boundary is real and
complete; it has nothing real to run yet.

Job records persist through `TrainingJobLog`, a `JsonLinesRegistry`
subclass guarded by the same `core.file_lock` mechanism the hardening
milestone added for `JsonLinesRegistry.add()` — concurrent job creation
is race-free by construction (VL "hardening milestone" §18).
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from aarya_voice_lab.core.file_lock import locked
from aarya_voice_lab.core.paths import PROJECT_ROOT
from aarya_voice_lab.identity.runtime import ComputeBackend
from aarya_voice_lab.registry.json_registry import JsonLinesRegistry
from aarya_voice_lab.schemas.base import SchemaName

TRAINING_STAGE = "voice_model_training"
TRAINING_ARCHITECTURE_VERSION = "1.0.0"

DEFAULT_TRAINING_JOB_LOG_PATH = PROJECT_ROOT / "models" / "training_jobs.jsonl"


class TrainingJobStatus(StrEnum):
    QUEUED = "QUEUED"
    VALIDATING = "VALIDATING"
    PREPARING = "PREPARING"
    TRAINING = "TRAINING"
    CHECKPOINTING = "CHECKPOINTING"
    EVALUATING = "EVALUATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"


TERMINAL_TRAINING_STATUSES: frozenset[TrainingJobStatus] = frozenset(
    {
        TrainingJobStatus.COMPLETED,
        TrainingJobStatus.FAILED,
        TrainingJobStatus.CANCELLED,
        TrainingJobStatus.TIMEOUT,
    }
)


def is_terminal_training_status(status: TrainingJobStatus) -> bool:
    return status in TERMINAL_TRAINING_STATUSES


class TrainingFailureReason(StrEnum):
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    DATASET_INVALID = "DATASET_INVALID"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INCOMPATIBLE_MODEL = "INCOMPATIBLE_MODEL"
    RESOURCE_UNAVAILABLE = "RESOURCE_UNAVAILABLE"
    TRAINING_FAILED = "TRAINING_FAILED"
    GENERATION_FAILED = "GENERATION_FAILED"
    ARTIFACT_CORRUPTED = "ARTIFACT_CORRUPTED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"


class TrainingProviderState(StrEnum):
    """Mirrors `pipeline.generation.GenerationBackendState`'s vocabulary
    so a UI can render both with the same status-badge domain."""

    AVAILABLE = "AVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


class TrainingBlockedError(RuntimeError):
    """A job cannot proceed at all (provider not configured, validation
    failed before training began) -- distinct from a mid-run failure."""

    def __init__(self, reason: TrainingFailureReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class TrainingProviderCapabilities:
    state: TrainingProviderState
    compute_backend: ComputeBackend
    #: What this provider actually requires to move past NOT_CONFIGURED --
    #: e.g. ("nemo_toolkit", "torch") -- shown to the operator verbatim
    #: rather than a generic "unavailable".
    missing_requirements: tuple[str, ...] = field(default_factory=tuple)
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "compute_backend": self.compute_backend.value,
            "missing_requirements": list(self.missing_requirements),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class TrainingConfig:
    """A versioned, hashable training request. `job_id` is a sequential
    id, never timestamp-derived -- same discipline as
    `pipeline.generation.PreviewRequest.request_id`."""

    job_id: str
    model_name: str
    model_version: str
    speaker_profile_id: str | None
    dataset_id: str
    provider_name: str
    #: BCP-47-ish language tag, e.g. "hi" (Hindi), "mr" (Marathi), "en"
    #: (English), or "und" (undetermined) -- never assumed. See
    #: docs/REAL_VOICE_MODEL_ENGINE.md's multilingual-architecture note.
    language: str = "und"
    hyperparameters: dict[str, Any] = field(default_factory=dict)

    @property
    def config_hash(self) -> str:
        payload = {
            "model_name": self.model_name,
            "model_version": self.model_version,
            "speaker_profile_id": self.speaker_profile_id,
            "dataset_id": self.dataset_id,
            "provider_name": self.provider_name,
            "language": self.language,
            "hyperparameters": self.hyperparameters,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "speaker_profile_id": self.speaker_profile_id,
            "dataset_id": self.dataset_id,
            "provider_name": self.provider_name,
            "language": self.language,
            "hyperparameters": dict(self.hyperparameters),
            "config_hash": self.config_hash,
        }


_job_counter = 0


def build_training_config(
    *,
    model_name: str,
    model_version: str,
    dataset_id: str,
    provider_name: str,
    speaker_profile_id: str | None = None,
    language: str = "und",
    hyperparameters: dict[str, Any] | None = None,
) -> TrainingConfig:
    global _job_counter
    _job_counter += 1
    return TrainingConfig(
        job_id=f"train-job-{_job_counter:05d}",
        model_name=model_name,
        model_version=model_version,
        speaker_profile_id=speaker_profile_id,
        dataset_id=dataset_id,
        provider_name=provider_name,
        language=language,
        hyperparameters=dict(hyperparameters or {}),
    )


@dataclass
class CheckpointInfo:
    checkpoint_id: str
    step: int | None
    #: Real, measured elapsed time -- never a fabricated ETA.
    elapsed_seconds: float
    artifact_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "step": self.step,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "artifact_id": self.artifact_id,
        }


@dataclass
class TrainingJob:
    job_id: str
    config: TrainingConfig
    status: TrainingJobStatus = TrainingJobStatus.QUEUED
    #: 0..1, or None when the provider cannot genuinely measure progress
    #: (the honest default -- see module docstring). A UI must render
    #: None as "UNKNOWN", never as 0%.
    progress: float | None = None
    current_operation: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    failure_reason: TrainingFailureReason | None = None
    checkpoints: list[CheckpointInfo] = field(default_factory=list)
    output_artifact_id: str | None = None
    evaluation_result: dict[str, Any] | None = None
    queued_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "config": self.config.to_dict(),
            "status": self.status.value,
            "progress": self.progress,
            "current_operation": self.current_operation,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "failure_reason": self.failure_reason.value if self.failure_reason else None,
            "checkpoints": [c.to_dict() for c in self.checkpoints],
            "output_artifact_id": self.output_artifact_id,
            "evaluation_result": self.evaluation_result,
            "queued_at": self.queued_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
        }


class TrainingProvider(ABC):
    """Contract every training backend satisfies. The domain layer
    (`TrainingQueue` below) depends only on this -- never on a subprocess,
    a specific ML framework, or a specific model library."""

    name: str = "abstract"
    version: str = "0.0.0"

    @abstractmethod
    def capabilities(self) -> TrainingProviderCapabilities:
        raise NotImplementedError

    @abstractmethod
    def validate(self, config: TrainingConfig) -> list[str]:
        """Return validation error messages; an empty list means valid."""
        raise NotImplementedError

    @abstractmethod
    def prepare(self, job: TrainingJob) -> None:
        raise NotImplementedError

    @abstractmethod
    def train(self, job: TrainingJob) -> None:
        raise NotImplementedError

    @abstractmethod
    def checkpoint(self, job: TrainingJob) -> CheckpointInfo | None:
        raise NotImplementedError

    @abstractmethod
    def cancel(self, job: TrainingJob) -> None:
        raise NotImplementedError

    @abstractmethod
    def resume(self, job: TrainingJob) -> None:
        raise NotImplementedError

    @abstractmethod
    def status(self, job: TrainingJob) -> TrainingJobStatus:
        raise NotImplementedError

    @abstractmethod
    def artifact(self, job: TrainingJob) -> str | None:
        """Return the output artifact id once training has produced one,
        else None."""
        raise NotImplementedError


class LocalTrainingProvider(TrainingProvider):
    """The one concrete provider this milestone ships.

    Performs real, unmocked capability detection via
    `importlib.metadata` (the same mechanism `environment.verify` already
    uses to check installed distributions) against every training path
    this project's own documentation has already evaluated (see
    `requirements/diarization.txt`, `requirements/tts.txt`): NeMo (for a
    real TitaNet/Sortformer-family embedding or diarization model) and
    PyTorch generally (for a real TTS fine-tune, e.g. the IndicF5/Parler-
    TTS candidates `requirements/tts.txt` documents). Neither is
    installed in this interpreter -- confirmed empirically, not assumed
    -- so every job this provider processes ends in FAILED with reason
    MODEL_UNAVAILABLE, honestly, every time, until an approved
    environment installs one of these and a real provider subclass is
    registered for it.
    """

    name = "local-training-provider"
    version = "1.0.0"

    #: Distribution name -> human label. Checked via importlib.metadata,
    #: never assumed present. Extending this list (a new candidate
    #: backend) requires no change to the domain layer above.
    CANDIDATE_DISTRIBUTIONS: dict[str, str] = {
        "nemo_toolkit": "NVIDIA NeMo (TitaNet/Sortformer-family models)",
        "torch": "PyTorch (required by every documented TTS candidate)",
    }

    def _installed(self) -> dict[str, str | None]:
        import importlib.metadata

        found: dict[str, str | None] = {}
        for distribution in self.CANDIDATE_DISTRIBUTIONS:
            try:
                found[distribution] = importlib.metadata.version(distribution)
            except importlib.metadata.PackageNotFoundError:
                found[distribution] = None
        return found

    def capabilities(self) -> TrainingProviderCapabilities:
        installed = self._installed()
        missing = tuple(sorted(name for name, version in installed.items() if version is None))
        if not missing:
            return TrainingProviderCapabilities(
                state=TrainingProviderState.AVAILABLE,
                compute_backend=ComputeBackend.CPU,
                detail=f"detected: {installed}",
            )
        return TrainingProviderCapabilities(
            state=TrainingProviderState.NOT_CONFIGURED,
            compute_backend=ComputeBackend.CPU,
            missing_requirements=missing,
            detail=(
                "No real local training runtime is installed in this interpreter. "
                "See requirements/diarization.txt and requirements/tts.txt for the "
                "documented, license-reviewed candidates -- installing one is a "
                "separate, approval-gated step (configs/default.yaml "
                "environments.env-tts.requires_approval), not something this "
                "provider does on its own."
            ),
        )

    def validate(self, config: TrainingConfig) -> list[str]:
        capabilities = self.capabilities()
        if capabilities.state is not TrainingProviderState.AVAILABLE:
            return [f"training provider not configured: {capabilities.detail}"]
        return []

    def prepare(self, job: TrainingJob) -> None:
        raise TrainingBlockedError(
            TrainingFailureReason.MODEL_UNAVAILABLE, "no real local training runtime is installed"
        )

    def train(self, job: TrainingJob) -> None:
        raise TrainingBlockedError(
            TrainingFailureReason.MODEL_UNAVAILABLE, "no real local training runtime is installed"
        )

    def checkpoint(self, job: TrainingJob) -> CheckpointInfo | None:
        return None

    def cancel(self, job: TrainingJob) -> None:
        return None

    def resume(self, job: TrainingJob) -> None:
        raise TrainingBlockedError(
            TrainingFailureReason.MODEL_UNAVAILABLE, "no real local training runtime is installed"
        )

    def status(self, job: TrainingJob) -> TrainingJobStatus:
        return job.status

    def artifact(self, job: TrainingJob) -> str | None:
        return job.output_artifact_id


class TrainingJobLog(JsonLinesRegistry):
    """Append-only persistence for finished (terminal-status) training
    jobs, mirroring `pipeline.processing_history.ProcessingHistoryLog`'s
    shape. In-flight jobs live only in `TrainingQueue`'s memory (same as
    `pipeline.generation.GenerationQueue`'s items) -- this log records the
    permanent history of what was attempted and how it ended."""

    def __init__(self, path: Path = DEFAULT_TRAINING_JOB_LOG_PATH):
        super().__init__(path=path, schema_name=SchemaName.TRAINING_JOB, id_field="job_id")

    def record(self, job: TrainingJob) -> None:
        self.add(job.to_dict())


class TrainingQueue:
    """Sequential training-job queue. Mirrors
    `pipeline.generation.GenerationQueue`'s exact shape and concurrency
    story: one job processed at a time in this process, one broad
    `except Exception` per job so a single failure can never corrupt the
    queue, real wall-clock duration measurement, never a fabricated
    progress percentage.
    """

    def __init__(self, *, provider: TrainingProvider, job_log: TrainingJobLog | None = None) -> None:
        self._provider = provider
        self._job_log = job_log
        self._jobs: dict[str, TrainingJob] = {}
        self._order: list[str] = []

    def enqueue(self, config: TrainingConfig) -> TrainingJob:
        job = TrainingJob(job_id=config.job_id, config=config)
        self._jobs[job.job_id] = job
        self._order.append(job.job_id)
        return job

    def get(self, job_id: str) -> TrainingJob | None:
        return self._jobs.get(job_id)

    def list(self) -> list[TrainingJob]:
        return [self._jobs[job_id] for job_id in self._order]

    def counts(self) -> dict[str, int]:
        counts = dict.fromkeys((s.value for s in TrainingJobStatus), 0)
        for job in self.list():
            counts[job.status.value] += 1
        return counts

    def cancel(self, job_id: str) -> TrainingJob:
        job = self._jobs[job_id]
        if not is_terminal_training_status(job.status):
            job.status = TrainingJobStatus.CANCELLED
            job.failure_reason = TrainingFailureReason.CANCELLED
            job.finished_at = datetime.now(UTC).isoformat()
            self._provider.cancel(job)
            if self._job_log is not None:
                with locked(self._job_log.path.with_name(self._job_log.path.name + ".record-lock")):
                    self._record(job)
        return job

    def _record(self, job: TrainingJob) -> None:
        if self._job_log is None:
            return
        try:
            self._job_log.record(job)
        except ValueError:
            # Already recorded (e.g. process_one() called twice on a
            # terminal job) -- append-only history, never a duplicate.
            pass

    def process_one(self, job_id: str) -> TrainingJob:
        job = self._jobs[job_id]
        if is_terminal_training_status(job.status):
            return job

        started = datetime.now(UTC)
        job.started_at = started.isoformat()
        try:
            job.status = TrainingJobStatus.VALIDATING
            job.current_operation = "validating training configuration"
            capabilities = self._provider.capabilities()
            if capabilities.state is not TrainingProviderState.AVAILABLE:
                job.status = TrainingJobStatus.FAILED
                job.failure_reason = TrainingFailureReason.MODEL_UNAVAILABLE
                job.errors.append(capabilities.detail or f"provider not available: {capabilities.state.value}")
                return job
            errors = self._provider.validate(job.config)
            if errors:
                job.status = TrainingJobStatus.FAILED
                job.failure_reason = TrainingFailureReason.INCOMPATIBLE_MODEL
                job.errors.extend(errors)
                return job

            job.status = TrainingJobStatus.PREPARING
            job.current_operation = "preparing dataset and model"
            self._provider.prepare(job)

            job.status = TrainingJobStatus.TRAINING
            job.current_operation = "training"
            self._provider.train(job)

            job.status = TrainingJobStatus.CHECKPOINTING
            job.current_operation = "checkpointing"
            checkpoint = self._provider.checkpoint(job)
            if checkpoint is not None:
                job.checkpoints.append(checkpoint)

            job.status = TrainingJobStatus.EVALUATING
            job.current_operation = "evaluating"
            job.output_artifact_id = self._provider.artifact(job)

            job.status = TrainingJobStatus.COMPLETED
        except TrainingBlockedError as exc:
            job.status = TrainingJobStatus.FAILED
            job.failure_reason = exc.reason
            job.errors.append(str(exc))
        except Exception as exc:  # noqa: BLE001 -- one job's failure must never crash the queue
            job.status = TrainingJobStatus.FAILED
            job.failure_reason = TrainingFailureReason.TRAINING_FAILED
            job.errors.append(str(exc))
        finally:
            job.current_operation = None
            finished = datetime.now(UTC)
            job.finished_at = finished.isoformat()
            job.duration_seconds = (finished - started).total_seconds()
            if is_terminal_training_status(job.status):
                self._record(job)
        return job

    def process_all(self) -> list[TrainingJob]:
        queued_ids = [job_id for job_id in self._order if self._jobs[job_id].status == TrainingJobStatus.QUEUED]
        return [self.process_one(job_id) for job_id in queued_ids]
