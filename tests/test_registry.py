from __future__ import annotations

import pytest

from aarya_voice_lab.registry.experiment_registry import ExperimentRegistry
from aarya_voice_lab.registry.model_registry import ModelRegistry
from aarya_voice_lab.schemas.base import ValidationError
from aarya_voice_lab.schemas.records import build_experiment, build_model_registry_entry

PRIVATE_SECURITY_METADATA = {
    "required_permission": "voice.private.use",
    "admin_only": True,
    "audit_logged": True,
    "storage_protection": "PLANNED",
    "distribution_restricted": True,
    "frontend_direct_access": False,
}


def test_experiment_registry_roundtrip(tmp_path):
    registry = ExperimentRegistry(tmp_path / "registry.jsonl")
    record = build_experiment(
        experiment_id="exp-1",
        created_at="2026-01-01T00:00:00Z",
        dataset_version="0.0.1",
        model="m",
        model_version="1",
        status="planned",
    )
    registry.add(record)
    assert registry.get("exp-1") == record
    assert len(registry.list()) == 1


def test_registry_rejects_duplicate_ids(tmp_path):
    registry = ExperimentRegistry(tmp_path / "registry.jsonl")
    record = build_experiment(
        experiment_id="exp-1",
        created_at="2026-01-01T00:00:00Z",
        dataset_version="0.0.1",
        model="m",
        model_version="1",
        status="planned",
    )
    registry.add(record)
    with pytest.raises(ValueError, match="already exists"):
        registry.add(record)


def test_registry_rejects_invalid_record(tmp_path):
    registry = ExperimentRegistry(tmp_path / "registry.jsonl")
    with pytest.raises(ValidationError):
        registry.add({"experiment_id": "broken"})


def test_empty_registry_lists_nothing(tmp_path):
    assert ExperimentRegistry(tmp_path / "missing.jsonl").list() == []


def test_model_registry_separates_default_and_private(tmp_path):
    registry = ModelRegistry(tmp_path / "models.jsonl")
    registry.add(
        build_model_registry_entry(
            model_name="default-voice", version="1", provider="local", model_type="default_voice", status="planned"
        )
    )
    registry.add(
        build_model_registry_entry(
            model_name="private-voice",
            version="1",
            provider="local",
            model_type="private_voice",
            status="planned",
            security_metadata=PRIVATE_SECURITY_METADATA,
        )
    )
    assert [m["model_name"] for m in registry.list_default_voice_models()] == ["default-voice"]
    assert [m["model_name"] for m in registry.list_private_voice_models()] == ["private-voice"]


def test_private_model_without_security_metadata_is_rejected(tmp_path):
    registry = ModelRegistry(tmp_path / "models.jsonl")
    with pytest.raises(ValidationError):
        registry.add(
            build_model_registry_entry(
                model_name="sloppy-private",
                version="1",
                provider="local",
                model_type="private_voice",
                status="planned",
            )
        )


def test_private_model_cannot_declare_frontend_direct_access(tmp_path):
    """frontend_direct_access must be recorded, and the security model
    requires it to be false -- assert the registry preserves it so a
    later Core-side check has something to enforce against."""
    registry = ModelRegistry(tmp_path / "models.jsonl")
    entry = build_model_registry_entry(
        model_name="private-voice",
        version="1",
        provider="local",
        model_type="private_voice",
        status="planned",
        security_metadata=PRIVATE_SECURITY_METADATA,
    )
    registry.add(entry)
    stored = registry.get("private-voice")
    assert stored["security_metadata"]["frontend_direct_access"] is False
    assert stored["security_metadata"]["required_permission"] == "voice.private.use"
