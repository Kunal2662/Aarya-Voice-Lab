"""Tests for path-safety and Git source protection.

These tests never create real audio content; they use empty placeholder
files with audio-like names to exercise path classification only.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from aarya_voice_lab.core.paths import PROJECT_ROOT, PROTECTED_DIRECTORIES, find_project_root
from aarya_voice_lab.security.source_protection import (
    classify_path,
    scan_git_repo,
    scan_paths,
)


@pytest.mark.parametrize(
    "path",
    [
        "source/recording_01.wav",
        "datasets/private/segment.mp3",
        "somewhere/audio.flac",
        "a/b/c.m4a",
        "clip.opus",
    ],
)
def test_audio_paths_are_flagged(path):
    assert classify_path(Path(path)) is not None


@pytest.mark.parametrize(
    "path",
    [
        "models/private_voice.ckpt",
        "checkpoints/model.safetensors",
        "embeddings/speaker.npy",
        "x/y/model.pt",
    ],
)
def test_model_and_embedding_artifacts_are_flagged(path):
    assert classify_path(Path(path)) is not None


@pytest.mark.parametrize(
    "path",
    ["configs/api_secret.yaml", "my_credentials.json", "auth.token", "apikey.txt"],
)
def test_secret_like_names_are_flagged(path):
    assert classify_path(Path(path)) is not None


def test_private_audio_directories_are_flagged_regardless_of_extension():
    assert classify_path(Path("some/recordings/index.txt")) is not None
    assert classify_path(Path("work/private_dataset/notes.md")) is not None


@pytest.mark.parametrize(
    "path",
    [
        "src/aarya_voice_lab/cli/main.py",
        "docs/ARCHITECTURE.md",
        "schemas/segment.schema.json",
        "manifests/templates/example_dataset_manifest.json",
        "README.md",
    ],
)
def test_legitimate_project_files_are_not_flagged(path):
    assert classify_path(Path(path)) is None


def test_scan_paths_collects_all_violations():
    result = scan_paths([Path("a.wav"), Path("src/main.py"), Path("b.ckpt")])
    assert not result.ok
    assert len(result.violations) == 2


def test_scan_paths_clean_input_is_ok():
    result = scan_paths([Path("src/main.py"), Path("docs/README.md")])
    assert result.ok


def test_repository_has_no_protected_material_tracked():
    """The live guard: nothing currently tracked or staged in this repo may
    look like private audio, a model artifact, or a secret."""
    result = scan_git_repo(PROJECT_ROOT)
    assert result.ok, "Protected material found in Git:\n" + "\n".join(
        f"  {v.path}: {v.reason}" for v in result.violations
    )


def test_find_project_root_locates_pyproject():
    assert (find_project_root() / "pyproject.toml").is_file()


def test_gitignore_covers_every_protected_directory():
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    for directory in PROTECTED_DIRECTORIES:
        assert f"/{directory}/**" in gitignore, f"{directory} is not carved out in .gitignore"


@pytest.mark.parametrize(
    "relative_path",
    [
        "source/fake_recording.wav",
        "datasets/fake_segment.wav",
        "models/fake_model.ckpt",
        "source/nested/deep/fake.mp3",
    ],
)
def test_git_actually_ignores_private_paths(tmp_path, relative_path):
    """Behavioural check: ask Git itself whether it would ignore these
    paths. Asserting on .gitignore text alone would not catch a rule that
    is present but ineffective."""
    result = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "check-ignore", "-q", relative_path],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"git does NOT ignore {relative_path}"


@pytest.mark.parametrize(
    "relative_path",
    [
        "source/README.md",
        "datasets/README.md",
        "manifests/templates/example_dataset_manifest.json",
        "schemas/segment.schema.json",
    ],
)
def test_documentation_and_templates_remain_trackable(relative_path):
    """The protection rules must not accidentally exclude the docs and
    synthetic templates that are supposed to be in Git."""
    result = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "check-ignore", "-q", relative_path],
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0, f"{relative_path} should be trackable but git ignores it"


def test_source_directory_contains_no_audio():
    """Phase 0 must not have introduced any recording into source/."""
    source_dir = PROJECT_ROOT / "source"
    if not source_dir.is_dir():
        return
    offenders = [p for p in source_dir.rglob("*") if p.is_file() and classify_path(p) is not None]
    assert not offenders, f"Unexpected private material in source/: {offenders}"
