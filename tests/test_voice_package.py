from __future__ import annotations

import pytest

from aarya_voice_lab.pipeline.voice_package import (
    build_voice_package_manifest,
    package_is_valid,
    validate_package_entries,
)
from aarya_voice_lab.schemas.base import ValidationError

VALID_CHECKSUM = "a" * 64


def _manifest(**overrides):
    defaults = dict(
        voice_id="default-voice-1",
        display_name="Default Voice One",
        version="0.1.0",
        type="default_voice",
        provider="local",
        languages=["en"],
        model_format="onnx",
        license="MIT",
        checksum_sha256=VALID_CHECKSUM,
    )
    defaults.update(overrides)
    return build_voice_package_manifest(**defaults)


def test_builds_a_valid_manifest():
    manifest = _manifest()
    assert manifest["format"] == "arya-voice-package"
    assert manifest["type"] == "default_voice"
    assert manifest["integrity"]["checksum_sha256"] == VALID_CHECKSUM
    assert manifest["integrity"]["algorithm"] == "sha256"


def test_rejects_private_voice_type():
    """A .arya-voice.zip is a distribution artifact. Private Voice must
    never gain a path to distribution -- the schema's enum excludes it
    entirely, matching the same rule VL-D12 already enforces for the
    model registry's frontend-facing methods."""
    with pytest.raises(ValidationError):
        _manifest(type="private_voice")


def test_rejects_unknown_model_format():
    with pytest.raises(ValidationError):
        _manifest(model_format="some-made-up-format")


def test_rejects_malformed_checksum():
    with pytest.raises(ValidationError):
        _manifest(checksum_sha256="not-a-real-sha256")


def test_rejects_empty_languages():
    with pytest.raises(ValidationError):
        _manifest(languages=[])


def test_rejects_missing_license():
    with pytest.raises(TypeError):
        build_voice_package_manifest(
            voice_id="v",
            display_name="V",
            version="1",
            type="default_voice",
            provider="local",
            languages=["en"],
            model_format="onnx",
            checksum_sha256=VALID_CHECKSUM,
        )


def test_optional_fields_default_to_none():
    manifest = _manifest()
    assert manifest["provider_version"] is None
    assert manifest["runtime_requirements"] is None
    assert manifest["compatibility"] is None
    assert manifest["creator"] is None


def test_accepts_a_well_formed_data_only_package():
    entries = ["manifest.json", "model.onnx", "LICENSE.txt", "README.md"]
    assert validate_package_entries(entries) == []
    assert package_is_valid(entries) is True


@pytest.mark.parametrize(
    "entry",
    [
        "run.py",
        "install.sh",
        "setup.exe",
        "hook.ps1",
        "lib.dll",
        "lib.so",
        "payload.jar",
    ],
)
def test_rejects_executable_and_script_entries_by_default(entry):
    problems = validate_package_entries(["manifest.json", entry])
    assert problems, f"{entry!r} should have been rejected"
    assert package_is_valid(["manifest.json", entry]) is False


def test_rejects_path_traversal_entries():
    problems = validate_package_entries(["manifest.json", "../../etc/passwd.json"])
    assert any("traversal" in p for p in problems)


def test_rejects_explicitly_forbidden_entry_names():
    problems = validate_package_entries(["manifest.json", "__init__.py"])
    assert problems


def test_validate_package_entries_reports_every_problem_not_just_the_first():
    problems = validate_package_entries(["a.exe", "b.sh", "manifest.json"])
    assert len(problems) == 2


def test_windows_style_separators_are_normalized_before_checking():
    problems = validate_package_entries(["subdir\\model.onnx", "subdir\\..\\..\\evil.exe"])
    # model.onnx should pass on extension grounds; the traversal entry
    # must still be caught regardless of which separator style was used.
    assert any("traversal" in p for p in problems)
    assert not any("model.onnx" in p for p in problems)
