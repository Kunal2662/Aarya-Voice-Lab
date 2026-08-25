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
    MAX_PACKAGE_ENTRY_UNCOMPRESSED_BYTES,
    VoicePackageBuildError,
    build_package_archive,
    build_voice_package_manifest,
    check_entry_sizes,
    reject_symlink_entries,
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
    # 1. Build.
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

    # 5. Status: the final step of the produce-and-register flow -- a
    #    caller must be able to ask "is this voice actually installed
    #    and intact" without repeating steps 3-4 itself.
    status = manager.status(artifact.artifact_id)
    assert status.artifact_present is True
    assert status.checksum_valid is True
    assert status.model_name == "built-voice"
    assert status.lifecycle_state == "AVAILABLE"


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


def test_check_entry_sizes_flags_a_declared_oversized_entry(tmp_path):
    """Simulates the core of a zip-bomb-style archive: a central-
    directory entry that DECLARES an oversized uncompressed size.
    check_entry_sizes() must catch this from the declared size alone,
    without decompressing anything -- proven here by never calling
    .read() anywhere in this test."""
    archive_path = tmp_path / "bomb.arya-voice"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("payload.bin", b"tiny")

    with zipfile.ZipFile(archive_path) as archive:
        info = archive.infolist()[0]
        info.file_size = MAX_PACKAGE_ENTRY_UNCOMPRESSED_BYTES + 1
        problems = check_entry_sizes(archive)

    assert any("zip bomb" in p for p in problems)


def test_check_entry_sizes_passes_for_normal_sized_entries(tmp_path):
    archive_path = tmp_path / "normal.arya-voice"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(_manifest()))
        zf.writestr("model.json", MODEL_BYTES)

    with zipfile.ZipFile(archive_path) as archive:
        assert check_entry_sizes(archive) == []


def test_validate_package_archive_calls_the_size_check_before_reading_manifest(tmp_path, monkeypatch):
    """Integration proof that validate_package_archive() is actually
    wired to check_entry_sizes() and respects a failure from it, rather
    than only the unit-level check_entry_sizes() behavior above."""
    import aarya_voice_lab.pipeline.voice_package as voice_package_module

    output = tmp_path / "voice.arya-voice"
    build_package_archive(output, manifest=_manifest(), model_bytes=MODEL_BYTES, model_filename="model.json")

    monkeypatch.setattr(
        voice_package_module, "check_entry_sizes", lambda archive: ["simulated declared-oversized entry"]
    )
    problems = validate_package_archive(output)

    assert problems == ["simulated declared-oversized entry"]


def test_reject_symlink_entries_flags_a_real_symlink_mode_entry(tmp_path):
    """Verified empirically (not assumed) before this test was written:
    Python's own zipfile.extractall() does NOT restore Unix mode bits --
    a symlink-mode entry extracts as a plain file containing the
    link-target string as literal bytes. This check is defense in depth
    against a *different* future consumer of this same archive format
    (a Core-side importer using a different library, or command-line
    unzip/7z on a Unix host) that might actually restore it."""
    import stat

    archive_path = tmp_path / "symlink.arya-voice"
    with zipfile.ZipFile(archive_path, "w") as zf:
        info = zipfile.ZipInfo("model.onnx")
        info.create_system = 3  # Unix
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "/etc/passwd")

    with zipfile.ZipFile(archive_path) as archive:
        problems = reject_symlink_entries(archive)

    assert any("symlink" in p for p in problems)


def test_reject_symlink_entries_passes_for_ordinary_entries(tmp_path):
    archive_path = tmp_path / "normal.arya-voice"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(_manifest()))
        zf.writestr("model.json", MODEL_BYTES)

    with zipfile.ZipFile(archive_path) as archive:
        assert reject_symlink_entries(archive) == []


def test_reject_symlink_entries_does_not_misfire_on_windows_built_archives(tmp_path):
    """An archive built on Windows carries external_attr == 0 for every
    entry (no Unix mode bits at all) -- must never be misread as 'every
    entry is a symlink.'"""
    archive_path = tmp_path / "windows_built.arya-voice"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(_manifest()))  # create_system defaults to Windows (0) here

    with zipfile.ZipFile(archive_path) as archive:
        assert reject_symlink_entries(archive) == []


def test_validate_package_archive_rejects_a_symlink_entry(tmp_path):
    import stat

    archive_path = tmp_path / "symlink.arya-voice"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(_manifest()))
        info = zipfile.ZipInfo("model.json")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, MODEL_BYTES.decode("utf-8", errors="replace"))

    problems = validate_package_archive(archive_path)
    assert any("symlink" in p for p in problems)


def test_install_from_archive_rejects_a_symlink_entry_before_extracting(tmp_path):
    import stat

    from aarya_voice_lab.core.data_root import DataRoot
    from aarya_voice_lab.pipeline.model_manager import ModelManager, ModelManagerError
    from aarya_voice_lab.registry.model_registry import ModelRegistry

    archive_path = tmp_path / "symlink.arya-voice"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(_manifest()))
        info = zipfile.ZipInfo("model.json")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "/etc/passwd")

    data_root = DataRoot(root=tmp_path / "data").create()
    registry = ModelRegistry(tmp_path / "models" / "registry.jsonl")
    manager = ModelManager(data_root, model_registry=registry)
    extract_to = tmp_path / "extracted"

    with pytest.raises(ModelManagerError, match="symlink"):
        manager.install_from_archive(archive_path, extract_to=extract_to)
    assert not extract_to.exists() or list(extract_to.iterdir()) == []


def test_build_leaves_no_temp_file_behind_on_success(tmp_path):
    output = tmp_path / "voice.arya-voice"
    build_package_archive(output, manifest=_manifest(), model_bytes=MODEL_BYTES, model_filename="model.json")

    remaining = list(tmp_path.iterdir())
    assert remaining == [output], f"expected only the final archive, found: {remaining}"


def test_build_never_leaves_a_corrupt_partial_file_at_the_output_path_on_failure(tmp_path, monkeypatch):
    """Real defect class this guards against: a crash partway through
    writing the zip must never leave a half-written, corrupt file at
    output_path -- confirmed by forcing zipfile.ZipFile.writestr() to
    raise mid-write and checking the target path afterward."""
    import aarya_voice_lab.pipeline.voice_package as voice_package_module

    def _boom(self, *args, **kwargs):
        raise RuntimeError("simulated crash mid-write")

    monkeypatch.setattr(voice_package_module.zipfile.ZipFile, "writestr", _boom)

    output = tmp_path / "voice.arya-voice"
    with pytest.raises(RuntimeError, match="simulated crash"):
        build_package_archive(output, manifest=_manifest(), model_bytes=MODEL_BYTES, model_filename="model.json")

    assert not output.exists(), "a crash mid-write must never leave a corrupt file at the real output path"
    # No orphaned temp file left behind either.
    assert list(tmp_path.iterdir()) == []


def test_build_is_atomic_the_target_never_observably_exists_in_a_partial_state(tmp_path):
    """Build twice to the same path -- the second build must either
    fully replace the first archive or fail outright, never leave a
    mixed/partial result. A simple, real proof: build, then build again
    with different content, then validate the final file is fully
    self-consistent (not a mix of both builds)."""
    output = tmp_path / "voice.arya-voice"
    build_package_archive(output, manifest=_manifest(), model_bytes=MODEL_BYTES, model_filename="model.json")

    other_payload = b"a completely different model payload for the second build"
    other_checksum = hashlib.sha256(other_payload).hexdigest()
    other_manifest = _manifest(
        version="2.0.0", checksum_sha256=other_checksum
    )
    build_package_archive(output, manifest=other_manifest, model_bytes=other_payload, model_filename="model.json")

    problems = validate_package_archive(output)
    assert problems == []
    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["version"] == "2.0.0"
        assert hashlib.sha256(archive.read("model.json")).hexdigest() == other_checksum
