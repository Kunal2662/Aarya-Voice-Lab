from __future__ import annotations

import pytest

from aarya_voice_lab.registry.dataset_registry import PublicDatasetRegistry
from aarya_voice_lab.schemas.base import ValidationError
from aarya_voice_lab.schemas.records import build_public_dataset_entry


def _entry(**overrides):
    defaults = dict(
        dataset_id="example-corpus-v1",
        dataset_name="Example Corpus",
        version="1.0",
        source="https://example.org/example-corpus",
        license="CC BY 4.0",
        permitted_uses=["training-pipeline-development"],
        status="registered",
    )
    defaults.update(overrides)
    return build_public_dataset_entry(**defaults)


def test_registry_roundtrip(tmp_path):
    registry = PublicDatasetRegistry(tmp_path / "registry.jsonl")
    record = _entry()
    registry.add(record)
    assert registry.get("example-corpus-v1") == record
    assert len(registry.list()) == 1


def test_registry_rejects_duplicate_ids(tmp_path):
    registry = PublicDatasetRegistry(tmp_path / "registry.jsonl")
    registry.add(_entry())
    with pytest.raises(ValueError, match="already exists"):
        registry.add(_entry())


def test_registry_rejects_missing_required_fields(tmp_path):
    registry = PublicDatasetRegistry(tmp_path / "registry.jsonl")
    with pytest.raises(ValidationError):
        registry.add({"dataset_id": "broken"})


def test_registry_rejects_unlisted_permitted_use(tmp_path):
    """permitted_uses is a closed enum -- an invented use category must
    be rejected, not silently accepted, so a caller can't grant itself a
    use the dataset's own license was never checked against."""
    with pytest.raises(ValidationError):
        _entry(permitted_uses=["whatever-i-want"])


def test_empty_registry_lists_nothing(tmp_path):
    assert PublicDatasetRegistry(tmp_path / "missing.jsonl").list() == []


def test_registered_status_grants_no_permission(tmp_path):
    """The core data-policy rule: recording metadata is not the same as
    approving use. A freshly registered dataset (status='registered')
    must not appear in list_approved() or pass permits_use(), even
    though its permitted_uses field is fully populated."""
    registry = PublicDatasetRegistry(tmp_path / "registry.jsonl")
    registry.add(_entry(status="registered"))
    assert registry.list_approved() == []
    assert registry.permits_use("example-corpus-v1", "training-pipeline-development") is False


def test_approved_dataset_permits_only_its_recorded_uses(tmp_path):
    registry = PublicDatasetRegistry(tmp_path / "registry.jsonl")
    registry.add(
        _entry(
            status="approved",
            permitted_uses=["training-pipeline-development", "benchmark-development"],
        )
    )
    assert [r["dataset_id"] for r in registry.list_approved()] == ["example-corpus-v1"]
    assert registry.permits_use("example-corpus-v1", "training-pipeline-development") is True
    assert registry.permits_use("example-corpus-v1", "benchmark-development") is True
    assert registry.permits_use("example-corpus-v1", "model-experimentation") is False


def test_permits_use_is_false_for_unknown_dataset(tmp_path):
    registry = PublicDatasetRegistry(tmp_path / "registry.jsonl")
    assert registry.permits_use("does-not-exist", "training-pipeline-development") is False


def test_list_by_status_partitions_entries(tmp_path):
    registry = PublicDatasetRegistry(tmp_path / "registry.jsonl")
    registry.add(_entry(dataset_id="a", status="registered"))
    registry.add(_entry(dataset_id="b", status="approved"))
    registry.add(_entry(dataset_id="c", status="rejected"))
    assert [r["dataset_id"] for r in registry.list_by_status("registered")] == ["a"]
    assert [r["dataset_id"] for r in registry.list_by_status("approved")] == ["b"]
    assert [r["dataset_id"] for r in registry.list_by_status("rejected")] == ["c"]


def test_optional_array_fields_default_to_empty_list(tmp_path):
    record = _entry()
    assert record["prohibited_uses"] == []
    assert record["language"] == []
