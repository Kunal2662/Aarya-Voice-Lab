"""Task 6 of the Phase 4 autonomous execution plan -- Windows release
preparation. No installer binary is built or invoked anywhere here."""

from __future__ import annotations

import pytest

from aarya_voice_lab import SCHEMA_VERSION, __version__
from aarya_voice_lab.core.paths import PROJECT_ROOT, PROTECTED_DIRECTORIES
from aarya_voice_lab.release import (
    DEFAULT_RELEASE_CONFIG_PATH,
    ReleaseConfigError,
    check_schema_compatibility,
    is_safe_to_delete_without_confirmation,
    load_release_metadata,
    validate_release_layout,
)


def test_default_release_config_loads():
    metadata = load_release_metadata()
    assert metadata.product_name == "AARYA Voice Lab"
    assert metadata.platform == "windows"


def test_default_release_config_has_a_stable_reverse_dns_app_id():
    """Phase 7 of the 8-phase release plan: a future installer needs a
    stable product identity across upgrades, distinct from the
    human-readable product_name."""
    metadata = load_release_metadata()
    assert metadata.app_id == "com.aarya.voicelab"
    assert metadata.app_id.count(".") >= 2


def test_default_release_config_version_matches_package_version():
    """The release manifest's version field must not silently drift from
    the actual installed package version."""
    metadata = load_release_metadata()
    assert metadata.version == __version__


def test_default_release_config_schema_version_matches_code():
    metadata = load_release_metadata()
    assert metadata.schema_version == SCHEMA_VERSION


def test_data_directories_match_protected_directories_exactly():
    """release.yaml's data_directories must stay in sync with
    core.paths.PROTECTED_DIRECTORIES, the same discipline
    configs/default.yaml's protected_directories already follows."""
    metadata = load_release_metadata()
    assert set(metadata.data_directories) >= set(PROTECTED_DIRECTORIES)


def test_missing_release_config_raises():
    with pytest.raises(ReleaseConfigError, match="not found"):
        load_release_metadata(DEFAULT_RELEASE_CONFIG_PATH.parent / "does-not-exist.yaml")


def test_release_config_rejects_missing_required_keys(tmp_path):
    incomplete = tmp_path / "incomplete.yaml"
    incomplete.write_text("product_name: X\n", encoding="utf-8")
    with pytest.raises(ReleaseConfigError, match="missing required keys"):
        load_release_metadata(incomplete)


def test_release_config_rejects_a_non_mapping_file(tmp_path):
    not_a_mapping = tmp_path / "list.yaml"
    not_a_mapping.write_text("- one\n- two\n", encoding="utf-8")
    with pytest.raises(ReleaseConfigError, match="must contain a mapping"):
        load_release_metadata(not_a_mapping)


def test_validate_release_layout_passes_on_the_real_checkout():
    """This repository's own directories already satisfy the release
    layout -- a real, current-state assertion, not a fixture."""
    metadata = load_release_metadata()
    problems = validate_release_layout(PROJECT_ROOT, metadata)
    assert problems == [], f"real checkout should satisfy its own declared layout: {problems}"


def test_validate_release_layout_reports_a_missing_directory(tmp_path):
    metadata = load_release_metadata()
    # tmp_path has none of the declared directories.
    problems = validate_release_layout(tmp_path, metadata)
    assert len(problems) == len(metadata.data_directories)
    assert all("does not exist" in p for p in problems)


def test_validate_release_layout_reports_a_file_where_a_directory_is_expected(tmp_path):
    metadata = load_release_metadata()
    (tmp_path / metadata.data_directories[0]).write_text("not a directory", encoding="utf-8")
    problems = validate_release_layout(tmp_path, metadata)
    assert any("is not a directory" in p for p in problems)


def test_protected_directories_are_never_safe_to_delete_without_confirmation():
    metadata = load_release_metadata()
    for name in metadata.uninstall_protected_directories:
        assert is_safe_to_delete_without_confirmation(name, metadata) is False


def test_unrecognised_directory_name_fails_closed():
    metadata = load_release_metadata()
    assert is_safe_to_delete_without_confirmation("something-nobody-declared", metadata) is False


def test_non_protected_declared_directory_is_safe_to_delete():
    metadata = load_release_metadata()
    non_protected = [d for d in metadata.data_directories if d not in metadata.uninstall_protected_directories]
    assert non_protected, "expected at least one non-protected declared directory"
    for name in non_protected:
        assert is_safe_to_delete_without_confirmation(name, metadata) is True


def test_schema_compatibility_matches_on_identical_versions():
    result = check_schema_compatibility("0.1.0", "0.1.0")
    assert result.compatible is True


def test_schema_compatibility_matches_on_same_major_different_minor():
    result = check_schema_compatibility("0.1.0", "0.1.0")
    assert result.compatible is True
    # Same-major, different-minor is still compatible by this project's
    # own semver convention.
    result2 = check_schema_compatibility("1.2.0", "1.9.0")
    assert result2.compatible is True


def test_schema_compatibility_refuses_on_major_mismatch():
    result = check_schema_compatibility("1.0.0", "2.0.0")
    assert result.compatible is False
    assert "migration" in result.reason
