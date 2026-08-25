"""Task 5 of the Phase 4 autonomous execution plan -- Voice Package
Builder. Round-trip: create -> validate -> extract -> revalidate. No
.arya-voice file is ever written outside tmp_path, and nothing built
here is committed."""

from __future__ import annotations

import hashlib
import json
import zipfile

import pytest

from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.pipeline.model_manager import ModelManager
from aarya_voice_lab.pipeline.voice_package import (
    VoicePackageBuildError,
    build_package_archive,
    build_voice_package_manifest,
    validate_package_archive,
)
from aarya_voice_lab.registry.model_registry import ModelRegistry

MODEL_BYTES = b"deterministic fixture bytes standing in for a real model artifact"
CHECKSUM = hashlib.sha256(MODEL_BYTES).hexdigest()


def _manifest(**overrides):
    defaults = dict(
        voice_id="built-voice",
        display_name="Built Voice",
        version="1.0.0",
        type="default_voice",
        provider="local",
        languages=["en"],
        model_format="json_metadata",
        license="MIT",
        checksum_sha256=CHECKSUM,
    )
    defaults.update(overrides)
    return build_voice_package_manifest(**defaults)


def test_build_creates_a_real_zip_archive(tmp_path):
    output = tmp_path / "voice.arya-voice"
    result = build_package_archive(
        output, manifest=_manifest(), model_bytes=MODEL_BYTES, model_filename="model.json"
    )
    assert result == output
    assert output.is_file()
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {"manifest.json", "model.json"}


def test_build_refuses_checksum_mismatch(tmp_path):
    manifest = _manifest(checksum_sha256="a" * 64)
    output = tmp_path / "voice.arya-voice"
    with pytest.raises(VoicePackageBuildError, match="does not match"):
        build_package_archive(output, manifest=manifest, model_bytes=MODEL_BYTES, model_filename="model.json")
    assert not output.exists()


def test_build_refuses_disallowed_extra_files(tmp_path):
    output = tmp_path / "voice.arya-voice"
    with pytest.raises(VoicePackageBuildError, match="disallowed entries"):
        build_package_archive(
            output,
            manifest=_manifest(),
            model_bytes=MODEL_BYTES,
            model_filename="model.json",
            extra_files={"install.sh": b"#!/bin/sh\necho hi"},
        )
    assert not output.exists()


def test_build_refuses_invalid_manifest(tmp_path):
    manifest = _manifest()
    manifest["type"] = "private_voice"  # not schema-valid for a package
    output = tmp_path / "voice.arya-voice"
    with pytest.raises(VoicePackageBuildError, match="schema validation"):
        build_package_archive(output, manifest=manifest, model_bytes=MODEL_BYTES, model_filename="model.json")


def test_round_trip_create_validate_extract_revalidate(tmp_path):
    # 1. Create.
    output = tmp_path / "voice.arya-voice"
    build_package_archive(output, manifest=_manifest(), model_bytes=MODEL_BYTES, model_filename="model.json")

    # 2. Validate (without extracting).
    problems = validate_package_archive(output)
    assert problems == []

    # 3. Extract (via ModelManager, reusing Task 2's real extraction +
    #    install pipeline rather than a second, duplicate implementation).
    data_root = DataRoot(root=tmp_path / "data").create()
    registry = ModelRegistry(tmp_path / "models" / "registry.jsonl")
    manager = ModelManager(data_root, model_registry=registry)
    artifact = manager.install_from_archive(output, extract_to=tmp_path / "extracted")

    # 4. Revalidate: the installed artifact's stored bytes still match
    #    their checksum, and the registry recorded the same identity the
    #    manifest declared.
    assert manager.verify(artifact.artifact_id) is True
    assert artifact.checksum_sha256 == CHECKSUM
    assert registry.get("built-voice") is not None


def test_validate_package_archive_detects_a_disallowed_entry_added_after_the_fact(tmp_path):
    """A round-trip validator must catch tampering even if the archive
    was not produced by build_package_archive() at all."""
    output = tmp_path / "tampered.arya-voice"
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps(_manifest()))
        archive.writestr("model.json", MODEL_BYTES)
        archive.writestr("payload.exe", b"MZ\x90\x00")

    problems = validate_package_archive(output)
    assert any("payload.exe" in p for p in problems)


def test_validate_package_archive_detects_checksum_mismatch(tmp_path):
    manifest = _manifest()
    output = tmp_path / "mismatched.arya-voice"
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("model.json", b"these are not the bytes the checksum was computed from")

    problems = validate_package_archive(output)
    assert any("no package entry's checksum matches" in p for p in problems)


def test_validate_package_archive_detects_missing_manifest(tmp_path):
    output = tmp_path / "no_manifest.arya-voice"
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("model.json", MODEL_BYTES)

    problems = validate_package_archive(output)
    assert any("no manifest.json" in p for p in problems)


def test_validate_package_archive_reports_malformed_zip_as_a_problem_not_an_exception(tmp_path):
    fake = tmp_path / "not_a_zip.arya-voice"
    fake.write_bytes(b"this is not a zip file at all")

    problems = validate_package_archive(fake)
    assert any("not a valid zip archive" in p for p in problems)


def test_validate_package_archive_detects_invalid_manifest_json(tmp_path):
    output = tmp_path / "broken_manifest.arya-voice"
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", "{not valid json")
        archive.writestr("model.json", MODEL_BYTES)

    problems = validate_package_archive(output)
    assert any("not valid JSON" in p for p in problems)
