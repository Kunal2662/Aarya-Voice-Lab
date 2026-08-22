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


def test_gpu_detection_falls_through_to_amd_when_nvidia_absent(monkeypatch, tmp_path):
    """Hardware-agnostic rule: absence of nvidia-smi must not stop
    looking for a GPU altogether -- AMD (rocm-smi) is tried next."""

    def fake_which(name):
        return "/usr/bin/rocm-smi" if name == "rocm-smi" else None

    monkeypatch.setattr(system_info.shutil, "which", fake_which)

    def fake_run(cmd, **kwargs):
        assert cmd[0] == "/usr/bin/rocm-smi"

        class Result:
            returncode = 0
            stdout = json.dumps({"card0": {"Card series": "Radeon Test GPU"}})

        return Result()

    monkeypatch.setattr(system_info.subprocess, "run", fake_run)
    monkeypatch.setattr(system_info, "_detect_gpu_via_sysfs", lambda: None)

    info = system_info.get_gpu_info()
    assert info.available is True
    assert info.vendor == "AMD"
    assert info.detection_method == "rocm-smi"
    assert info.devices[0]["name"] == "Radeon Test GPU"


def test_gpu_detection_falls_through_to_sysfs_when_no_vendor_tool_found(monkeypatch):
    """Vendor-neutral last resort: a GPU with no nvidia-smi/rocm-smi
    installed must still be reported as present, not silently absent."""
    monkeypatch.setattr(system_info.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        system_info,
        "_detect_gpu_via_sysfs",
        lambda: system_info.GPUInfo(
            available=True,
            devices=[{"name": "Intel GPU (model unconfirmed -- no vendor tool installed)", "vram_mib": None}],
            detection_method="sysfs-pci-id",
            vendor="Intel",
            note="presence-only detection via PCI vendor ID",
        ),
    )
    info = system_info.get_gpu_info()
    assert info.available is True
    assert info.vendor == "Intel"
    assert info.detection_method == "sysfs-pci-id"


def test_gpu_detection_reports_honest_negative_when_nothing_found(monkeypatch):
    monkeypatch.setattr(system_info.shutil, "which", lambda name: None)
    monkeypatch.setattr(system_info, "_detect_gpu_via_sysfs", lambda: None)
    info = system_info.get_gpu_info()
    assert info.available is False
    assert info.vendor is None
    assert "no NVIDIA, AMD, or PCI-enumerable GPU found" in info.note


def test_sysfs_gpu_detection_reads_real_pci_vendor_ids(tmp_path, monkeypatch):
    """Exercises the real sysfs-reading code (not mocked) against a
    fabricated /sys/class/drm layout -- proves the PCI-vendor-id parsing
    itself works, not just that some other function was called."""
    drm_root = tmp_path / "drm"
    card_device = drm_root / "card0" / "device"
    card_device.mkdir(parents=True)
    (card_device / "vendor").write_text("0x1002\n")

    monkeypatch.setattr(system_info, "_DRM_ROOT", drm_root)

    info = system_info._detect_gpu_via_sysfs()
    assert info is not None
    assert info.available is True
    assert info.vendor == "AMD"
    assert info.detection_method == "sysfs-pci-id"
