"""End-to-end inference orchestration -- Task 4 of the Phase 4
autonomous execution plan.

Flow: Model -> Load -> Runtime -> Inference -> Audio Output -> Objective
Evaluation. This module orchestrates existing, already-real components
(`pipeline.model_manager.ModelManager` for load/status,
`pipeline.generation.VoiceGenerator` for inference,
`pipeline.objective_evaluation` for evaluation) -- it implements no new
generation or evaluation logic of its own.

No real trained voice model exists in this project (see
PHASE3_CHECKPOINT.md) and no real generation runtime is installed (no
transformers/torch/soundfile -- see docs/REAL_ML_RUNTIME_INTEGRATION.md
and pipeline.generation.LocalNeuralVoiceGenerator's own docstring). "No
real model exists" is therefore the honest, current state of every
checkout this pipeline runs on today. Per the plan's own instruction,
this orchestration runs against `SyntheticVoiceGenerator` -- a real,
deterministic, repository-controlled generator that produces genuine
(clearly synthetic) audio -- rather than fabricating output from a
generator that has none. `is_synthetic` on every result mirrors exactly
what `generate_preview()` already stamps, never overridden here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.pipeline.generation import GenerationBackendState, GenerationBlockedError, VoiceGenerator
from aarya_voice_lab.pipeline.model_manager import ModelManager
from aarya_voice_lab.pipeline.objective_evaluation import ObjectiveAudioMetrics, measure_objective_audio_metrics


class InferencePipelineError(RuntimeError):
    """Raised when Model/Load/Runtime/Inference cannot proceed."""


@dataclass(frozen=True)
class LoadedModel:
    """What "Load" actually verified. `artifact_id=None` means the
    fixture path (SyntheticVoiceGenerator) was used -- it has no model
    artifact to load, by design."""

    artifact_id: str | None
    verified: bool


@dataclass(frozen=True)
class InferenceResult:
    request_id: str
    audio_path: Path
    is_synthetic: bool
    sample_rate: int
    duration_seconds: float
    objective_metrics: ObjectiveAudioMetrics


class InferencePipeline:
    def __init__(
        self,
        *,
        generator: VoiceGenerator,
        data_root: DataRoot,
        model_manager: ModelManager | None = None,
    ) -> None:
        self._generator = generator
        self._data_root = data_root
        self._model_manager = model_manager
        self._loaded: LoadedModel | None = None

    @property
    def is_loaded(self) -> bool:
        return self._loaded is not None

    def load(self, artifact_id: str | None) -> LoadedModel:
        """Model -> Load. `artifact_id=None` is the honest fixture path:
        no real model artifact exists to verify, and none is fabricated.
        A non-None `artifact_id` must actually verify against the model
        manager's real checksum check -- an unknown or tampered artifact
        raises rather than loading anyway."""
        if artifact_id is None:
            self._loaded = LoadedModel(artifact_id=None, verified=True)
            return self._loaded
        if self._model_manager is None:
            raise InferencePipelineError("artifact_id given but no ModelManager was configured to verify it")
        if not self._model_manager.artifact_store.exists(artifact_id):
            raise InferencePipelineError(f"model artifact {artifact_id!r} is not installed")
        if not self._model_manager.verify(artifact_id):
            raise InferencePipelineError(f"model artifact {artifact_id!r} failed checksum verification")
        self._loaded = LoadedModel(artifact_id=artifact_id, verified=True)
        return self._loaded

    def unload(self) -> None:
        self._loaded = None

    def run(self, request: dict[str, Any]) -> InferenceResult:
        """Runtime -> Inference -> Audio Output -> Objective Evaluation.

        Raises InferencePipelineError if no model is loaded or the
        generator's runtime is not AVAILABLE -- never silently falls
        through to a different generator or fabricates output.
        """
        if self._loaded is None:
            raise InferencePipelineError("no model loaded -- call load() first")

        capabilities = self._generator.get_capabilities()
        if capabilities.backend_state is not GenerationBackendState.AVAILABLE:
            raise InferencePipelineError(
                f"generation runtime not available: {capabilities.backend_state.value} "
                f"(missing: {capabilities.missing_requirements})"
            )

        try:
            artifact = self._generator.generate_preview(request)
        except GenerationBlockedError as exc:
            raise InferencePipelineError(f"inference blocked: {exc}") from exc

        audio_path = self._data_root.root / artifact.relative_path
        metrics = measure_objective_audio_metrics(audio_path)

        return InferenceResult(
            request_id=request.get("request_id", artifact.preview_id),
            audio_path=audio_path,
            is_synthetic=artifact.is_synthetic,
            sample_rate=artifact.sample_rate,
            duration_seconds=artifact.duration_seconds,
            objective_metrics=metrics,
        )
