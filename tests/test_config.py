from __future__ import annotations

import pytest

from aarya_voice_lab.core.config import DEFAULT_CONFIG_PATH, ConfigError, load_config
from aarya_voice_lab.core.paths import PROTECTED_DIRECTORIES


def test_default_config_loads():
    config = load_config()
    assert config.project_name
    assert config.schema_version
    assert config.pipeline_version


def test_missing_config_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yaml")


def test_malformed_config_raises(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("just a string, not a mapping\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_incomplete_config_raises(tmp_path):
    path = tmp_path / "partial.yaml"
    path.write_text("project_name: x\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_default_config_declares_no_cloud_provider():
    """Local-first guarantee: the shipped config must not preconfigure any
    cloud voice provider."""
    providers = load_config().raw.get("providers", {})
    assert all(value is None for value in providers.values()), providers


def test_config_protected_directories_match_code():
    configured = load_config().raw.get("protected_directories", [])
    assert sorted(configured) == sorted(PROTECTED_DIRECTORIES)


def test_default_config_file_contains_no_secrets():
    text = DEFAULT_CONFIG_PATH.read_text(encoding="utf-8").lower()
    for needle in ("api_key:", "password:", "token:", "secret:"):
        assert needle not in text
