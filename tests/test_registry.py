from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

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


def test_registry_add_is_race_free_under_concurrent_writers(tmp_path):
    """Hardening milestone F-2 -- exercises the real persistence mechanism
    (JsonLinesRegistry.add()'s file lock over the actual .jsonl file on
    disk), not a mocked stand-in. 25 threads race to add distinct records
    to the same registry at the same time; every writer must succeed,
    no record may be lost, and the on-disk JSONL must remain fully valid
    and readable afterward with exactly one line per record."""
    registry = ExperimentRegistry(tmp_path / "registry.jsonl")
    writer_count = 25
    barrier = threading.Barrier(writer_count)

    def add_one(n):
        record = build_experiment(
            experiment_id=f"exp-{n}",
            created_at="2026-01-01T00:00:00Z",
            dataset_version="0.0.1",
            model="m",
            model_version="1",
            status="planned",
        )
        barrier.wait()
        registry.add(record)
        return f"exp-{n}"

    with ThreadPoolExecutor(max_workers=writer_count) as pool:
        added_ids = list(pool.map(add_one, range(writer_count)))

    assert len(added_ids) == writer_count
    stored = registry.list()
    assert len(stored) == writer_count, "no record may be lost or duplicated under concurrent writers"
    assert {r["experiment_id"] for r in stored} == {f"exp-{n}" for n in range(writer_count)}
    # The on-disk file must be well-formed JSONL: every line parses, and
    # a corrupted/partial write would show up as a line count mismatch.
    lines = (tmp_path / "registry.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == writer_count
    for line in lines:
        json.loads(line)  # raises if a write was partial/corrupted


def test_registry_add_rejects_duplicate_id_under_concurrent_writers(tmp_path):
    """The uniqueness check itself must not be racy: N concurrent writers
    all attempting to add the *same* id must result in exactly one
    success and the rest rejected -- never two winners."""
    registry = ExperimentRegistry(tmp_path / "registry.jsonl")
    writer_count = 15
    barrier = threading.Barrier(writer_count)

    def add_same():
        record = build_experiment(
            experiment_id="exp-shared",
            created_at="2026-01-01T00:00:00Z",
            dataset_version="0.0.1",
            model="m",
            model_version="1",
            status="planned",
        )
        barrier.wait()
        try:
            registry.add(record)
            return "ok"
        except ValueError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=writer_count) as pool:
        outcomes = list(pool.map(lambda _: add_same(), range(writer_count)))

    assert outcomes.count("ok") == 1, f"exactly one writer must win the race, got: {outcomes}"
    assert outcomes.count("rejected") == writer_count - 1
    assert len(registry.list()) == 1


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
