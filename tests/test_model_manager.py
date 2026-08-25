from __future__ import annotations

import hashlib
import json
import zipfile

import pytest

from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.pipeline.model_manager import (
    ModelManager,
    ModelManagerError,
    check_compatibility,
)
from aarya_voice_lab.registry.model_registry import ModelRegistry

VALID_PAYLOAD = b"not a real model, just deterministic bytes for a test fixture"
VALID_CHECKSUM = hashlib.sha256(VALID_PAYLOAD).hexdigest()


def _manifest(**overrides):
    defaults = dict(
        schema_version="0.1.0",
        format="arya-voice-package",
        format_version="1.0.0",
        voice_id="test-voice",
        display_name="Test Voice",
        version="1.0.0",
        type="default_voice",
        provider="local",
        provider_version=None,
        languages=["en"],
        model_format="json_metadata",
        runtime_requirements=None,
        hardware_requirements=None,
        memory_requirements_mb=None,
        license="MIT",
        provenance=None,
        integrity={"algorithm": "sha256", "checksum_sha256": VALID_CHECKSUM},
        compatibility=None,
        creator=None,
        created_at=None,
        notes=None,
    )
    defaults.update(overrides)
    return defaults


def _write_package(package_dir, manifest=None, *, payload=VALID_PAYLOAD, model_filename="model.json"):
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "manifest.json").write_text(json.dumps(manifest or _manifest()), encoding="utf-8")
    (package_dir / model_filename).write_bytes(payload)
    return package_dir


def _manager(tmp_path):
    data_root = DataRoot(root=tmp_path / "data").create()
    registry = ModelRegistry(tmp_path / "models" / "registry.jsonl")
    return ModelManager(data_root, model_registry=registry)


def test_installs_a_well_formed_package(tmp_path):
    package_dir = _write_package(tmp_path / "package")
    manager = _manager(tmp_path)

    artifact = manager.install_from_directory(package_dir)

    assert artifact.checksum_sha256 == VALID_CHECKSUM
    assert artifact.model_name == "test-voice"
    assert manager.artifact_store.exists(artifact.artifact_id)
    assert manager.model_registry.get("test-voice") is not None


def test_rejects_checksum_mismatch(tmp_path):
    manifest = _manifest(integrity={"algorithm": "sha256", "checksum_sha256": "a" * 64})
    package_dir = _write_package(tmp_path / "package", manifest=manifest)
    manager = _manager(tmp_path)

    with pytest.raises(ModelManagerError, match="checksum mismatch"):
        manager.install_from_directory(package_dir)
    assert manager.list_installed() == []


def test_rejects_invalid_manifest_schema(tmp_path):
    manifest = _manifest()
    del manifest["license"]  # required field
    package_dir = _write_package(tmp_path / "package", manifest=manifest)
    manager = _manager(tmp_path)

    with pytest.raises(ModelManagerError, match="schema validation"):
        manager.install_from_directory(package_dir)


def test_rejects_package_with_executable_entry(tmp_path):
    package_dir = _write_package(tmp_path / "package")
    (package_dir / "run.sh").write_text("#!/bin/sh\necho hi", encoding="utf-8")
    manager = _manager(tmp_path)

    with pytest.raises(ModelManagerError, match="disallowed entries"):
        manager.install_from_directory(package_dir)
    assert manager.list_installed() == []


def test_rejects_unknown_provider(tmp_path):
    manifest = _manifest(provider="some-unvetted-provider")
    package_dir = _write_package(tmp_path / "package", manifest=manifest)
    manager = _manager(tmp_path)

    with pytest.raises(ModelManagerError, match="incompatible package"):
        manager.install_from_directory(package_dir)


def test_check_compatibility_reports_both_problems_independently():
    manifest = _manifest(provider="unknown-provider", model_format="unsupported-format")
    report = check_compatibility(manifest)
    assert report.compatible is False
    assert len(report.problems) == 2


def test_check_compatibility_passes_for_a_known_provider_and_format():
    report = check_compatibility(_manifest())
    assert report.compatible is True
    assert report.problems == ()


def test_installing_the_same_package_twice_is_refused(tmp_path):
    """ArtifactStore's own checksum-identity refusal must surface as a
    real, catchable error -- not a silent no-op and not a duplicate."""
    package_dir = _write_package(tmp_path / "package")
    manager = _manager(tmp_path)
    manager.install_from_directory(package_dir)
    with pytest.raises(Exception):  # noqa: B017 -- ArtifactStore's own ArtifactError
        manager.install_from_directory(package_dir)


def test_install_from_archive_extracts_and_installs(tmp_path):
    package_dir = _write_package(tmp_path / "source_package")
    archive_path = tmp_path / "voice.arya-voice"
    with zipfile.ZipFile(archive_path, "w") as zf:
        for file in package_dir.iterdir():
            zf.write(file, arcname=file.name)

    manager = _manager(tmp_path)
    artifact = manager.install_from_archive(archive_path, extract_to=tmp_path / "extracted")
    assert artifact.checksum_sha256 == VALID_CHECKSUM


def test_install_from_archive_rejects_executable_entry_before_extracting(tmp_path):
    archive_path = tmp_path / "malicious.arya-voice"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(_manifest()))
        zf.writestr("evil.exe", b"MZ\x90\x00")

    manager = _manager(tmp_path)
    extract_to = tmp_path / "extracted"
    with pytest.raises(ModelManagerError, match="disallowed entries"):
        manager.install_from_archive(archive_path, extract_to=extract_to)
    # Must refuse *before* extraction -- nothing should land on disk.
    assert not extract_to.exists() or list(extract_to.iterdir()) == []


def test_remove_deletes_artifact_but_registry_history_remains(tmp_path):
    package_dir = _write_package(tmp_path / "package")
    manager = _manager(tmp_path)
    artifact = manager.install_from_directory(package_dir)

    removed = manager.remove(artifact.artifact_id)

    assert removed is True
    assert manager.artifact_store.exists(artifact.artifact_id) is False
    # Append-only registry: the historical entry is never deleted.
    assert manager.model_registry.get("test-voice") is not None


def test_verify_returns_true_for_untampered_artifact(tmp_path):
    package_dir = _write_package(tmp_path / "package")
    manager = _manager(tmp_path)
    artifact = manager.install_from_directory(package_dir)
    assert manager.verify(artifact.artifact_id) is True


def test_verify_returns_false_for_tampered_bytes(tmp_path):
    package_dir = _write_package(tmp_path / "package")
    manager = _manager(tmp_path)
    artifact = manager.install_from_directory(package_dir)

    bin_path = manager.artifact_store.directory / f"{artifact.artifact_id}.bin"
    bin_path.write_bytes(b"tampered bytes, different length entirely")

    assert manager.verify(artifact.artifact_id) is False


def test_verify_raises_for_unknown_artifact(tmp_path):
    manager = _manager(tmp_path)
    with pytest.raises(ModelManagerError, match="not installed"):
        manager.verify("artifact-doesnotexist")


def test_status_reports_installed_model(tmp_path):
    package_dir = _write_package(tmp_path / "package")
    manager = _manager(tmp_path)
    artifact = manager.install_from_directory(package_dir)

    status = manager.status(artifact.artifact_id)

    assert status.artifact_present is True
    assert status.checksum_valid is True
    assert status.model_name == "test-voice"
    assert status.version == "1.0.0"
    assert status.lifecycle_state == "AVAILABLE"


def test_status_reports_missing_artifact_honestly(tmp_path):
    manager = _manager(tmp_path)
    status = manager.status("artifact-neverexisted")
    assert status.artifact_present is False
    assert status.checksum_valid is None
    assert status.artifact_id is None


def test_status_after_removal_reflects_removal(tmp_path):
    package_dir = _write_package(tmp_path / "package")
    manager = _manager(tmp_path)
    artifact = manager.install_from_directory(package_dir)
    manager.remove(artifact.artifact_id)

    status = manager.status(artifact.artifact_id)
    assert status.artifact_present is False


def test_list_installed_reflects_current_store_contents(tmp_path):
    manager = _manager(tmp_path)
    assert manager.list_installed() == []
    package_dir = _write_package(tmp_path / "package")
    artifact = manager.install_from_directory(package_dir)
    assert manager.list_installed() == [artifact.artifact_id]


def test_install_from_archive_refuses_a_declared_oversized_entry_before_extracting(tmp_path, monkeypatch):
    """Phase 5 of the 8-phase release plan: a zip-bomb-style declared
    size must be refused before archive.extractall() is ever called."""
    import aarya_voice_lab.pipeline.model_manager as model_manager_module

    package_dir = _write_package(tmp_path / "package")
    archive_path = tmp_path / "voice.arya-voice"
    with zipfile.ZipFile(archive_path, "w") as zf:
        for file in package_dir.iterdir():
            zf.write(file, arcname=file.name)

    monkeypatch.setattr(
        model_manager_module, "check_entry_sizes", lambda archive: ["simulated declared-oversized entry"]
    )

    manager = _manager(tmp_path)
    extract_to = tmp_path / "extracted"
    with pytest.raises(ModelManagerError, match="failed size checks"):
        manager.install_from_archive(archive_path, extract_to=extract_to)
    assert not extract_to.exists() or list(extract_to.iterdir()) == []
