"""Experiment registry: local record of voice-model experiment runs.

See docs/MODEL_STRATEGY.md. Backed by experiments/registry.jsonl, which
is git-ignored -- experiment records may reference private dataset
versions.
"""

from __future__ import annotations

from pathlib import Path

from aarya_voice_lab.core.paths import PROJECT_ROOT
from aarya_voice_lab.registry.json_registry import JsonLinesRegistry
from aarya_voice_lab.schemas.base import SchemaName

DEFAULT_EXPERIMENT_REGISTRY_PATH = PROJECT_ROOT / "experiments" / "registry.jsonl"


class ExperimentRegistry(JsonLinesRegistry):
    def __init__(self, path: Path = DEFAULT_EXPERIMENT_REGISTRY_PATH):
        super().__init__(path=path, schema_name=SchemaName.EXPERIMENT, id_field="experiment_id")
