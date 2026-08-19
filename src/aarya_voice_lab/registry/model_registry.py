"""Model registry: local record of voice model artifacts (default + private).

See docs/MODEL_STRATEGY.md and docs/SECURITY.md. Backed by
models/registry.jsonl, which is git-ignored.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aarya_voice_lab.core.paths import PROJECT_ROOT
from aarya_voice_lab.registry.json_registry import JsonLinesRegistry
from aarya_voice_lab.schemas.base import SchemaName

DEFAULT_MODEL_REGISTRY_PATH = PROJECT_ROOT / "models" / "registry.jsonl"


class ModelRegistry(JsonLinesRegistry):
    def __init__(self, path: Path = DEFAULT_MODEL_REGISTRY_PATH):
        super().__init__(path=path, schema_name=SchemaName.MODEL_REGISTRY, id_field="model_name")

    def list_private_voice_models(self) -> list[dict[str, Any]]:
        return [r for r in self.list() if r.get("model_type") == "private_voice"]

    def list_default_voice_models(self) -> list[dict[str, Any]]:
        return [r for r in self.list() if r.get("model_type") == "default_voice"]
