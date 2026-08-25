"""Task 4 of the Phase 4 autonomous execution plan -- inference
pipeline orchestration tests.

No real trained voice model exists anywhere this project runs, so every
"real inference" assertion here exercises SyntheticVoiceGenerator (a
real, deterministic, repository-controlled fixture) rather than a
fabricated stand-in for a real model.
"""

from __future__ import annotations

import pytest

from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.pipeline.generation import (
    SyntheticVoiceGenerator,
    UnavailableVoiceGenerator,
    build_preview_request,
)
from aarya_voice_lab.pipeline.inference_pipeline import InferencePipeline, InferencePipelineError
from aarya_voice_lab.pipeline.model_manager import ModelManager
from aarya_voice_lab.registry.model_registry import ModelRegistry


def _manager(tmp_path, data_root):
    registry = ModelRegistry(tmp_path / "models" / "registry.jsonl")
    return ModelManager(data_root, model_registry=registry)


def _pipeline(tmp_path, *, generator=None, with_manager=True):
    data_root = DataRoot(root=tmp_path / "data").create()
    generator = generator or SyntheticVoiceGenerator(data_root)
    manager = _manager(tmp_path, data_root) if with_manager else None
    return InferencePipeline(generator=generator, data_root=data_root, model_manager=manager), data_root


def _request(**overrides):
    defaults = dict(text="hello from a test fixture", voice_profile_id="profile-1", model_id="synthetic-tone")
    defaults.update(overrides)
    return build_preview_request(**defaults).to_dict()


def test_load_with_no_artifact_id_uses_the_fixture_path(tmp_path):
    pipeline, _ = _pipeline(tmp_path)
    loaded = pipeline.load(None)
    assert loaded.artifact_id is None
    assert loaded.verified is True
    assert pipeline.is_loaded is True


def test_full_flow_produces_real_non_fabricated_audio_and_evaluation(tmp_path):
    pipeline, _ = _pipeline(tmp_path)
    pipeline.load(None)

    result = pipeline.run(_request())

    assert result.audio_path.is_file()
    assert result.is_synthetic is True
    assert result.duration_seconds > 0
    assert result.objective_metrics.is_valid is True
    assert result.objective_metrics.duration_seconds > 0
    assert result.objective_metrics.sample_rate == result.sample_rate


def test_run_without_load_raises(tmp_path):
    pipeline, _ = _pipeline(tmp_path)
    with pytest.raises(InferencePipelineError, match="no model loaded"):
        pipeline.run(_request())


def test_unload_clears_loaded_state(tmp_path):
    pipeline, _ = _pipeline(tmp_path)
    pipeline.load(None)
    assert pipeline.is_loaded is True

    pipeline.unload()

    assert pipeline.is_loaded is False
    with pytest.raises(InferencePipelineError, match="no model loaded"):
        pipeline.run(_request())


def test_load_rejects_an_unknown_artifact_id(tmp_path):
    pipeline, _ = _pipeline(tmp_path)
    with pytest.raises(InferencePipelineError, match="not installed"):
        pipeline.load("artifact-doesnotexist")


def test_load_rejects_without_a_model_manager_configured(tmp_path):
    pipeline, _ = _pipeline(tmp_path, with_manager=False)
    with pytest.raises(InferencePipelineError, match="no ModelManager"):
        pipeline.load("artifact-anything")


def test_runtime_unavailable_backend_is_refused_honestly(tmp_path):
    """The runtime-unavailable test case: UnavailableVoiceGenerator is a
    real, existing fixture in this codebase for exactly this purpose --
    never a fabricated success."""
    pipeline, _ = _pipeline(tmp_path, generator=UnavailableVoiceGenerator())
    pipeline.load(None)

    with pytest.raises(InferencePipelineError, match="not available"):
        pipeline.run(_request())


def test_invalid_request_is_blocked_not_silently_generated(tmp_path):
    pipeline, _ = _pipeline(tmp_path)
    pipeline.load(None)

    with pytest.raises(InferencePipelineError, match="inference blocked"):
        pipeline.run(_request(text=""))  # empty text is invalid


def test_two_runs_produce_deterministic_but_independent_audio(tmp_path):
    """Same text -> same deterministic tone (SyntheticVoiceGenerator's
    own contract); different request ids -> different files on disk."""
    pipeline, _ = _pipeline(tmp_path)
    pipeline.load(None)

    first = pipeline.run(_request(text="same text"))
    second = pipeline.run(_request(text="same text"))

    assert first.audio_path != second.audio_path
    assert first.objective_metrics.duration_seconds == pytest.approx(second.objective_metrics.duration_seconds)


def test_load_after_installing_a_real_model_verifies_checksum(tmp_path):
    import hashlib
    import json

    payload = b"deterministic fixture bytes for the inference pipeline load test"
    manifest = {
        "schema_version": "0.1.0",
        "format": "arya-voice-package",
        "format_version": "1.0.0",
        "voice_id": "loadable-voice",
        "display_name": "Loadable Voice",
        "version": "1.0.0",
        "type": "default_voice",
        "provider": "local",
        "provider_version": None,
        "languages": ["en"],
        "model_format": "json_metadata",
        "runtime_requirements": None,
        "hardware_requirements": None,
        "memory_requirements_mb": None,
        "license": "MIT",
        "provenance": None,
        "integrity": {"algorithm": "sha256", "checksum_sha256": hashlib.sha256(payload).hexdigest()},
        "compatibility": None,
        "creator": None,
        "created_at": None,
        "notes": None,
    }
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    (package_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (package_dir / "model.json").write_bytes(payload)

    pipeline, data_root = _pipeline(tmp_path)
    manager = _manager(tmp_path, data_root)
    artifact = manager.install_from_directory(package_dir)

    pipeline_with_manager = InferencePipeline(
        generator=SyntheticVoiceGenerator(data_root), data_root=data_root, model_manager=manager
    )
    loaded = pipeline_with_manager.load(artifact.artifact_id)
    assert loaded.artifact_id == artifact.artifact_id
    assert loaded.verified is True
