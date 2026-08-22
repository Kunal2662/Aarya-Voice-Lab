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

    def list_non_private_models(self) -> list[dict[str, Any]]:
        """Every entry EXCEPT `private_voice` -- the only method in this
        class safe to expose to an unauthenticated surface (CLI --json,
        a live frontend snapshot, ...). docs/SECURITY.md is explicit: a
        private_voice model requires Core-side, server-side permission
        enforcement and must never gain a frontend-only path to itself
        (`security_metadata.frontend_direct_access` exists precisely to
        record that requirement). This project has no such Core-side
        enforcement layer yet, so the only safe rule here is to never let
        a private_voice record reach any consumer that doesn't already
        have this filter applied -- enforced at this single source
        rather than trusted to every future caller."""
        return [r for r in self.list() if r.get("model_type") != "private_voice"]
