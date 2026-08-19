"""System info must degrade gracefully when hardware/tools are absent."""

from __future__ import annotations

import json

from aarya_voice_lab import system_info


def test_collect_system_report_succeeds():
    report = system_info.collect_system_report()
    assert report.os.system
    assert report.python_version
    assert isinstance(report.gpu.available, bool)
    assert isinstance(report.cuda.available, bool)
    assert isinstance(report.ffmpeg.available, bool)


def test_report_is_json_serializable():
    report = system_info.collect_system_report()
    json.dumps(report.to_dict(), default=str)


def test_format_report_returns_text():
    text = system_info.format_report(system_info.collect_system_report())
    assert "AARYA Voice Lab" in text
    assert "Python" in text


def test_gpu_detection_handles_missing_nvidia_smi(monkeypatch):
    monkeypatch.setattr(system_info.shutil, "which", lambda name: None)
    info = system_info.get_gpu_info()
    assert info.available is False
    assert info.note


def test_ffmpeg_detection_handles_missing_binary(monkeypatch):
    monkeypatch.setattr(system_info.shutil, "which", lambda name: None)
    info = system_info.get_ffmpeg_info()
    assert info.available is False


def test_gpu_detection_handles_failing_nvidia_smi(monkeypatch):
    monkeypatch.setattr(system_info.shutil, "which", lambda name: "/usr/bin/nvidia-smi")

    def boom(*args, **kwargs):
        raise OSError("simulated failure")

    monkeypatch.setattr(system_info.subprocess, "run", boom)
    info = system_info.get_gpu_info()
    assert info.available is False
    assert "failed" in (info.note or "")


def test_cuda_detection_without_torch_does_not_crash():
    info = system_info.get_cuda_info()
    assert isinstance(info.available, bool)
    assert isinstance(info.torch_installed, bool)


def test_disk_info_reports_positive_total():
    info = system_info.get_disk_info(".")
    assert info.total_bytes > 0


def test_cli_entrypoint_runs():
    assert system_info.main(["--json"]) == 0
