"""Minimal YAML-backed configuration loader.

Deliberately small: Phase 0 configuration is a handful of static values
(project metadata, pipeline/schema versions, default paths). No secrets
belong here — see docs/SECURITY.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from aarya_voice_lab.core.paths import PROJECT_ROOT

DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs" / "default.yaml"


class ConfigError(ValueError):
    """Raised when a config file is missing, malformed, or fails checks."""


@dataclass
class AaryaVoiceLabConfig:
    project_name: str
    schema_version: str
    pipeline_version: str
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AaryaVoiceLabConfig:
        required = ["project_name", "schema_version", "pipeline_version"]
        missing = [key for key in required if key not in data]
        if missing:
            raise ConfigError(f"Config missing required keys: {missing}")
        return cls(
            project_name=data["project_name"],
            schema_version=data["schema_version"],
            pipeline_version=data["pipeline_version"],
            raw=data,
        )


def load_config(path: Path | None = None) -> AaryaVoiceLabConfig:
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise ConfigError(f"Config file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Config file must contain a mapping: {config_path}")
    return AaryaVoiceLabConfig.from_dict(data)
