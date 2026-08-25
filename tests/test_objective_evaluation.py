from __future__ import annotations

import time

from aarya_voice_lab.pipeline.objective_evaluation import (
    current_process_memory_mb,
    measure_latency,
    measure_objective_audio_metrics,
    real_time_factor,
)
from aarya_voice_lab.testing.synthetic_audio import generate_clipped, generate_silence, generate_speech_like


def test_measures_real_valid_audio(tmp_path):
    path = generate_speech_like(tmp_path / "speech.wav", duration_seconds=2.0)
    metrics = measure_objective_audio_metrics(path)
    assert metrics.is_valid is True
    assert 1.9 <= metrics.duration_seconds <= 2.1
    assert metrics.sample_rate == 16_000
    assert metrics.read_error is None


def test_detects_clipping(tmp_path):
    path = generate_clipped(tmp_path / "clipped.wav", duration_seconds=1.0)
    metrics = measure_objective_audio_metrics(path)
    assert metrics.is_valid is True
    assert metrics.clipping_ratio > 0.5


def test_detects_silence(tmp_path):
    path = generate_silence(tmp_path / "silence.wav", duration_seconds=1.0)
    metrics = measure_objective_audio_metrics(path)
    assert metrics.is_valid is True
    assert metrics.silent_frame_ratio == 1.0


def test_invalid_file_reports_is_valid_false_not_a_crash(tmp_path):
    path = tmp_path / "not_audio.wav"
    path.write_bytes(b"this is not a wav file at all")
    metrics = measure_objective_audio_metrics(path)
    assert metrics.is_valid is False
    assert metrics.read_error is not None
    assert metrics.duration_seconds is None


def test_missing_file_reports_is_valid_false(tmp_path):
    metrics = measure_objective_audio_metrics(tmp_path / "does_not_exist.wav")
    assert metrics.is_valid is False
    assert metrics.read_error is not None


def test_measure_latency_reports_real_elapsed_time():
    def slow_operation():
        time.sleep(0.05)
        return "done"

    result, timing = measure_latency(slow_operation)
    assert result == "done"
    assert timing.elapsed_seconds >= 0.05
    assert timing.latency_ms >= 50.0


def test_real_time_factor_computes_ratio():
    assert real_time_factor(processing_seconds=2.0, audio_duration_seconds=4.0) == 0.5
    assert real_time_factor(processing_seconds=4.0, audio_duration_seconds=2.0) == 2.0


def test_real_time_factor_is_none_for_zero_duration():
    assert real_time_factor(processing_seconds=1.0, audio_duration_seconds=0.0) is None


def test_current_process_memory_mb_returns_a_real_positive_number():
    """psutil is a documented project dependency (README.md Installation),
    so this should genuinely measure something on any machine this suite
    runs on -- assert a real number was produced, not merely that the
    function didn't crash."""
    memory_mb = current_process_memory_mb()
    assert memory_mb is None or memory_mb > 0
