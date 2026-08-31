"""Tests for `pipeline.indicf5_generation.IndicF5VoiceGenerator` -- the
real, local IndicF5 backend, distinct from `LocalNeuralVoiceGenerator`
(VLD18's capability-detection-only stub).

This module must stay importable and testable in the base interpreter,
which has no `torch`/vendored-`f5_tts` -- every test here exercises the
subprocess-management and validation logic only. Nothing here starts a
real GPU worker or asserts anything about generated audio quality; that
verification lives in `scripts/indicf5_bundled_reference_test.py` (a
human listens) and was done manually for this milestone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.pipeline.generation import (
    GenerationBackendState,
    GenerationBlockedError,
    VoiceGenerator,
    build_preview_request,
)
from aarya_voice_lab.pipeline.indicf5_generation import (
    TTS_PYTHON_ENV_VAR,
    IndicF5VoiceGenerator,
    autodetect_tts_python,
)


def _data_root(tmp_path):
    root = DataRoot(root=tmp_path / "data")
    root.create()
    return root


def test_indicf5_voice_generator_is_a_voice_generator():
    assert issubclass(IndicF5VoiceGenerator, VoiceGenerator)


def test_indicf5_voice_generator_is_a_distinct_backend_name(tmp_path):
    from aarya_voice_lab.pipeline.generation import LocalNeuralVoiceGenerator

    generator = IndicF5VoiceGenerator(_data_root(tmp_path))
    assert generator.name != LocalNeuralVoiceGenerator.name


def test_autodetect_tts_python_honors_env_var_override(monkeypatch):
    monkeypatch.setenv(TTS_PYTHON_ENV_VAR, r"C:\some\custom\python.exe")
    assert autodetect_tts_python() == Path(r"C:\some\custom\python.exe")


def test_autodetect_tts_python_none_when_nothing_found(tmp_path, monkeypatch):
    monkeypatch.delenv(TTS_PYTHON_ENV_VAR, raising=False)
    monkeypatch.setattr("aarya_voice_lab.pipeline.indicf5_generation.PROJECT_ROOT", tmp_path)
    assert autodetect_tts_python() is None


def test_get_capabilities_reports_not_configured_when_no_interpreter(tmp_path):
    generator = IndicF5VoiceGenerator(_data_root(tmp_path), tts_python=None)
    generator._tts_python = None  # force the "never found" state deterministically
    capabilities = generator.get_capabilities()
    assert capabilities.backend_state == GenerationBackendState.NOT_CONFIGURED
    assert "tts-interpreter" in capabilities.missing_requirements


def test_get_capabilities_reports_error_when_interpreter_path_is_bogus(tmp_path):
    bogus = tmp_path / "does-not-exist" / "python.exe"
    generator = IndicF5VoiceGenerator(_data_root(tmp_path), tts_python=bogus)
    capabilities = generator.get_capabilities()
    assert capabilities.backend_state == GenerationBackendState.ERROR
    assert "does-not-exist" in capabilities.detail or "failed to start" in capabilities.detail.lower()


def test_validate_request_rejects_empty_text(tmp_path):
    generator = IndicF5VoiceGenerator(_data_root(tmp_path))
    errors = generator.validate_request({"text": "", "sample_rate": 24000})
    assert any("empty" in e for e in errors)


def test_validate_request_rejects_text_over_max_length(tmp_path):
    from aarya_voice_lab.pipeline.generation import MAX_TEXT_LENGTH

    generator = IndicF5VoiceGenerator(_data_root(tmp_path))
    errors = generator.validate_request({"text": "a" * (MAX_TEXT_LENGTH + 1), "sample_rate": 24000})
    assert any("exceeds" in e for e in errors)


def test_validate_request_reports_missing_interpreter(tmp_path):
    generator = IndicF5VoiceGenerator(_data_root(tmp_path))
    generator._tts_python = None
    errors = generator.validate_request({"text": "hello", "sample_rate": 24000})
    assert any("not configured" in e for e in errors)


def test_generate_preview_raises_blocked_error_when_not_configured(tmp_path):
    generator = IndicF5VoiceGenerator(_data_root(tmp_path))
    generator._tts_python = None
    request = build_preview_request(text="hello", voice_profile_id="vp-1", model_id=generator.name)
    with pytest.raises(GenerationBlockedError):
        generator.generate_preview(request.to_dict())


def test_generate_preview_never_writes_a_fake_artifact_when_worker_unreachable(tmp_path):
    data_root = _data_root(tmp_path)
    generator = IndicF5VoiceGenerator(data_root, tts_python=tmp_path / "nonexistent-python.exe")
    request = build_preview_request(text="hello", voice_profile_id="vp-1", model_id=generator.name)
    with pytest.raises(GenerationBlockedError):
        generator.generate_preview(request.to_dict())
    assert list(data_root.previews.glob("*.wav")) == []


def test_close_is_a_safe_no_op_when_never_started(tmp_path):
    generator = IndicF5VoiceGenerator(_data_root(tmp_path))
    generator.close()  # must not raise even though no worker was ever launched
    generator.close()  # idempotent
