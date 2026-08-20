"""Generation model registry — VL-D5 §26, §27.

Distinct from `registry.model_registry.ModelRegistry` (Phase 1's
persisted, security-metadata-carrying record of *final voice model*
artifacts — default/private voice, audited for release). This module is
about which *generation backends/engines* are pluggable into
`pipeline.generation.VoiceGenerator` right now — a different concern
that happens to share the word "model." Reusing Phase 1's schema here
would force an ill-fitting `model_type: default_voice | private_voice |
other` distinction onto something that isn't about the final voice at
all, so this stays a separate, lighter, in-memory registry — the same
"build new only where the existing concept is genuinely a different
one" judgement VL-D3 already applied to `quality_decision`.

Hardware/capability vocabulary is reused, not reinvented:
`identity.runtime.ComputeBackend` and `RuntimeCapability` are exactly
the vendor-neutral vocabulary this registry's `backend`/`requirements`
fields need — nothing here names NVIDIA, CUDA, or a GPU directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aarya_voice_lab.identity.runtime import ComputeBackend, RuntimeCapability


@dataclass(frozen=True)
class GenerationModel:
    model_id: str
    name: str
    version: str
    backend: ComputeBackend
    #: e.g. {"speed", "seed", "output_format"} — matched against
    #: pipeline.generation.GenerationCapabilities.controls.
    capabilities: frozenset[str] = field(default_factory=frozenset)
    requirements: RuntimeCapability | None = None
    status: str = "not_configured"

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "name": self.name,
            "version": self.version,
            "backend": self.backend.value,
            "capabilities": sorted(self.capabilities),
            "requirements": self.requirements.to_dict() if self.requirements else None,
            "status": self.status,
        }


class GenerationModelRegistry:
    """In-memory registry of pluggable generation models/backends —
    runtime-discovered declarations, not persisted artifacts, so no
    `JsonLinesRegistry` backing is needed (unlike processing history,
    which records what actually happened)."""

    def __init__(self) -> None:
        self._models: dict[str, GenerationModel] = {}

    def register(self, model: GenerationModel) -> GenerationModel:
        self._models[model.model_id] = model
        return model

    def get(self, model_id: str) -> GenerationModel | None:
        return self._models.get(model_id)

    def list(self) -> list[GenerationModel]:
        return list(self._models.values())

    def list_by_backend(self, backend: ComputeBackend) -> list[GenerationModel]:
        return [m for m in self._models.values() if m.backend is backend]
