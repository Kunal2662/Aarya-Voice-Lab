"""Hardware / environment inspection for AARYA Voice Lab.

Reports what's available on the current machine (OS, CPU, RAM, GPU,
CUDA, FFmpeg, disk, Python) without requiring any of it to be present.
Every capability check is isolated in its own try/except so a missing
tool (no GPU, no ffmpeg, no CUDA) is reported cleanly rather than
crashing the whole report.

Run directly with:

    python -m aarya_voice_lab.system_info
"""

from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def _safe(fn, default=None):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - deliberately broad, this is a diagnostic tool
        return default if default is not None else f"error: {exc}"


@dataclass
class OSInfo:
    system: str
    release: str
    version: str
    machine: str
    platform: str


@dataclass
class CPUInfo:
    processor: str
    architecture: str
    logical_cores: int | None
    physical_cores: int | None


@dataclass
class MemoryInfo:
    total_bytes: int | None
    available_bytes: int | None
    source: str  # "psutil" or "unavailable"


@dataclass
class DiskInfo:
    path: str
    total_bytes: int
    used_bytes: int
    free_bytes: int


@dataclass
class GPUInfo:
    available: bool
    driver_version: str | None = None
    devices: list[dict[str, Any]] = field(default_factory=list)
    detection_method: str = "none"
    note: str | None = None
    #: "NVIDIA", "AMD", a PCI-vendor-ID-derived guess, or None when
    #: nothing was detected. Hardware-agnostic rule (Real ML Runtime
    #: milestone follow-up): no vendor is privileged in detection order
    #: beyond NVIDIA being checked first because scripts/install_env.sh's
    #: CUDA-wheel decision already depends on that specific signal.
    vendor: str | None = None


@dataclass
class CUDAInfo:
    available: bool
    torch_installed: bool
    cuda_version: str | None = None
    nvcc_version: str | None = None
    note: str | None = None


@dataclass
class FFmpegInfo:
    available: bool
    version: str | None = None
    path: str | None = None


@dataclass
class SystemReport:
    os: OSInfo
    cpu: CPUInfo
    memory: MemoryInfo
    disk: DiskInfo
    gpu: GPUInfo
    cuda: CUDAInfo
    ffmpeg: FFmpegInfo
    python_version: str
    python_executable: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_os_info() -> OSInfo:
    return OSInfo(
        system=platform.system() or "unknown",
        release=platform.release() or "unknown",
        version=platform.version() or "unknown",
        machine=platform.machine() or "unknown",
        platform=platform.platform() or "unknown",
    )


def get_cpu_info() -> CPUInfo:
    logical = _safe(lambda: __import__("os").cpu_count())
    physical = logical
    try:
        import psutil

        physical = psutil.cpu_count(logical=False) or logical
        logical = psutil.cpu_count(logical=True) or logical
    except ImportError:
        pass
    return CPUInfo(
        processor=platform.processor() or "unknown",
        architecture=platform.machine() or "unknown",
        logical_cores=logical,
        physical_cores=physical,
    )


def get_memory_info() -> MemoryInfo:
    try:
        import psutil

        vm = psutil.virtual_memory()
        return MemoryInfo(total_bytes=vm.total, available_bytes=vm.available, source="psutil")
    except ImportError:
        return MemoryInfo(total_bytes=None, available_bytes=None, source="unavailable (psutil not installed)")


def get_disk_info(path: str = ".") -> DiskInfo:
    total, used, free = shutil.disk_usage(path)
    return DiskInfo(path=path, total_bytes=total, used_bytes=used, free_bytes=free)


#: PCI vendor IDs for the GPU vendors this project can currently name.
#: Not exhaustive -- an unrecognized ID still gets detected and reported
#: as present, just without a friendly name. See _detect_gpu_via_sysfs().
_PCI_VENDOR_NAMES = {
    "0x10de": "NVIDIA",
    "0x1002": "AMD",
    "0x8086": "Intel",
}

#: Module-level so tests can monkeypatch it to a fabricated layout
#: rather than needing a real (or real-looking) /sys/class/drm.
_DRM_ROOT = Path("/sys/class/drm")


def _detect_nvidia_gpu(nvidia_smi: str) -> GPUInfo:
    try:
        result = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return GPUInfo(available=False, detection_method="nvidia-smi", note=f"nvidia-smi failed: {exc}")

    if result.returncode != 0 or not result.stdout.strip():
        return GPUInfo(
            available=False,
            detection_method="nvidia-smi",
            note=f"nvidia-smi returned no GPUs (exit {result.returncode})",
        )

    devices = []
    driver_version = None
    for line in result.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            name, mem_total_mib, driver_version = parts[0], parts[1], parts[2]
            devices.append({"name": name, "vram_mib": mem_total_mib})

    return GPUInfo(
        available=bool(devices),
        driver_version=driver_version,
        devices=devices,
        detection_method="nvidia-smi",
        vendor="NVIDIA" if devices else None,
    )


def _detect_amd_gpu() -> GPUInfo | None:
    """AMD via ROCm's own inspection tool. Returns None (never a
    negative GPUInfo) when rocm-smi is absent or its probe fails, so the
    caller can keep falling through to the vendor-neutral sysfs check
    rather than reporting a false "no GPU" the moment this one tool is
    missing -- the exact trap the NVIDIA-only detection this milestone
    is fixing fell into."""
    rocm_smi = shutil.which("rocm-smi")
    if not rocm_smi:
        return None
    try:
        result = subprocess.run(
            [rocm_smi, "--showproductname", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    devices = [
        {"name": info.get("Card series") or info.get("Card model") or card_id, "vram_mib": None}
        for card_id, info in parsed.items()
        if isinstance(info, dict)
    ]
    if not devices:
        return None
    return GPUInfo(available=True, devices=devices, detection_method="rocm-smi", vendor="AMD")


def _detect_gpu_via_sysfs() -> GPUInfo | None:
    """Vendor-neutral last resort: a GPU shows up as a PCI display
    device under /sys/class/drm on Linux whether or not any vendor CLI
    (nvidia-smi, rocm-smi, intel_gpu_top, ...) is installed. This is
    presence-only -- no driver, VRAM, or model name is available this
    way -- but it is what actually makes "no GPU detected" honest on a
    machine whose only accelerator is AMD or Intel and has no vendor
    tool installed, rather than silently assuming NVIDIA-or-nothing."""
    if not _DRM_ROOT.is_dir():
        return None
    try:
        card_dirs = sorted(p for p in _DRM_ROOT.glob("card[0-9]*") if p.is_dir())
    except OSError:
        return None

    devices: list[dict[str, Any]] = []
    seen_device_dirs: set[Path] = set()
    vendor_names: set[str] = set()
    for card in card_dirs:
        vendor_path = card / "device" / "vendor"
        if not vendor_path.is_file():
            continue
        try:
            resolved = vendor_path.parent.resolve()
        except OSError:
            continue
        if resolved in seen_device_dirs:
            continue
        seen_device_dirs.add(resolved)
        try:
            vendor_id = vendor_path.read_text().strip().lower()
        except OSError:
            continue
        vendor_name = _PCI_VENDOR_NAMES.get(vendor_id, f"unknown (PCI vendor {vendor_id})")
        vendor_names.add(vendor_name)
        devices.append({"name": f"{vendor_name} GPU (model unconfirmed -- no vendor tool installed)", "vram_mib": None})

    if not devices:
        return None
    vendor = vendor_names.pop() if len(vendor_names) == 1 else "mixed"
    return GPUInfo(
        available=True,
        devices=devices,
        detection_method="sysfs-pci-id",
        vendor=vendor,
        note="presence-only detection via PCI vendor ID -- install nvidia-smi/rocm-smi for driver/VRAM detail",
    )


def _detect_gpu_via_windows_wmi() -> GPUInfo | None:
    """VL-D19 -- vendor-neutral last resort on Windows. `_detect_gpu_via_
    sysfs()` above reads /sys/class/drm, a Linux-only path that does not
    exist on Windows at all -- on a Windows machine with no nvidia-smi/
    rocm-smi on PATH, GPU detection previously fell straight through to
    the honest "nothing found" negative even when a real GPU (confirmed:
    an Intel integrated GPU on the machine this was written and verified
    on) was physically present. This is the Windows equivalent: every
    video controller Windows itself already enumerates carries a
    PNPDeviceID containing a PCI vendor id (VEN_XXXX), the same PCI
    vendor-id scheme _PCI_VENDOR_NAMES already covers for Linux. Unlike
    sysfs, WMI also reports a real device name, so this can name the
    device precisely rather than falling back to the generic
    "model unconfirmed" phrasing sysfs needs."""
    if platform.system() != "Windows":
        return None
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        return None
    try:
        result = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-CimInstance Win32_VideoController | "
                "Select-Object Name,PNPDeviceID | ConvertTo-Json -Compress",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    controllers = parsed if isinstance(parsed, list) else [parsed]
    devices: list[dict[str, Any]] = []
    vendor_names: set[str] = set()
    for controller in controllers:
        if not isinstance(controller, dict):
            continue
        pnp_device_id = controller.get("PNPDeviceID") or ""
        match = re.search(r"VEN_([0-9A-Fa-f]{4})", pnp_device_id)
        if not match:
            continue
        vendor_id = f"0x{match.group(1).lower()}"
        vendor_name = _PCI_VENDOR_NAMES.get(vendor_id, f"unknown (PCI vendor {vendor_id})")
        vendor_names.add(vendor_name)
        name = controller.get("Name") or f"{vendor_name} GPU (model unconfirmed)"
        devices.append({"name": name, "vram_mib": None})

    if not devices:
        return None
    vendor = vendor_names.pop() if len(vendor_names) == 1 else "mixed"
    return GPUInfo(
        available=True,
        devices=devices,
        detection_method="windows-wmi",
        vendor=vendor,
        note="detected via Windows WMI (Win32_VideoController) enumeration -- driver/VRAM detail not queried",
    )


def get_gpu_info() -> GPUInfo:
    """NVIDIA is checked first only because scripts/install_env.sh's CUDA-
    vs-CPU wheel index decision already depends on that specific signal
    (see docs/GPU_STRATEGY.md) -- it is not a claim that NVIDIA is
    privileged as a vendor. When nvidia-smi is not even on PATH, AMD
    (rocm-smi) and then a vendor-neutral PCI enumeration are tried in
    turn before honestly reporting no accelerator at all. When
    nvidia-smi IS present but its own probe fails, that failure is
    reported directly rather than silently falling through to another
    vendor -- a broken NVIDIA tool on an NVIDIA machine is a real signal
    worth surfacing, not something to paper over.

    VL-D19 -- the sysfs check above only ever succeeds on Linux
    (/sys/class/drm does not exist on Windows); _detect_gpu_via_windows_
    wmi() is the platform-appropriate equivalent, tried last for the same
    reason sysfs is: presence-only, no vendor tool required."""
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        return _detect_nvidia_gpu(nvidia_smi)

    amd = _detect_amd_gpu()
    if amd is not None:
        return amd

    sysfs = _detect_gpu_via_sysfs()
    if sysfs is not None:
        return sysfs

    windows_wmi = _detect_gpu_via_windows_wmi()
    if windows_wmi is not None:
        return windows_wmi

    return GPUInfo(
        available=False,
        detection_method="none",
        note="no NVIDIA, AMD, or PCI-enumerable GPU found (nvidia-smi not found on PATH)",
    )


def get_cuda_info() -> CUDAInfo:
    torch_installed = False
    cuda_version = None
    try:
        import torch  # type: ignore

        torch_installed = True
        if torch.cuda.is_available():
            cuda_version = torch.version.cuda
            return CUDAInfo(available=True, torch_installed=True, cuda_version=cuda_version)
        return CUDAInfo(
            available=False,
            torch_installed=True,
            note="torch installed but torch.cuda.is_available() is False",
        )
    except ImportError:
        pass

    nvcc = shutil.which("nvcc")
    nvcc_version = None
    if nvcc:
        try:
            result = subprocess.run([nvcc, "--version"], capture_output=True, text=True, timeout=10, check=False)
            if result.returncode == 0:
                nvcc_version = result.stdout.strip().splitlines()[-1]
        except (OSError, subprocess.SubprocessError):
            pass

    return CUDAInfo(
        available=False,
        torch_installed=torch_installed,
        nvcc_version=nvcc_version,
        note="torch not installed; CUDA availability could not be confirmed via torch"
        if not nvcc
        else "nvcc found but torch not installed; CUDA runtime availability unconfirmed",
    )


def get_ffmpeg_info() -> FFmpegInfo:
    path = shutil.which("ffmpeg")
    if not path:
        return FFmpegInfo(available=False)
    try:
        result = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=10, check=False)
        version_line = result.stdout.strip().splitlines()[0] if result.stdout else None
        return FFmpegInfo(available=result.returncode == 0, version=version_line, path=path)
    except (OSError, subprocess.SubprocessError) as exc:
        return FFmpegInfo(available=False, path=path, version=f"error invoking ffmpeg: {exc}")


def collect_system_report() -> SystemReport:
    return SystemReport(
        os=get_os_info(),
        cpu=get_cpu_info(),
        memory=get_memory_info(),
        disk=get_disk_info(),
        gpu=get_gpu_info(),
        cuda=get_cuda_info(),
        ffmpeg=get_ffmpeg_info(),
        python_version=sys.version,
        python_executable=sys.executable,
    )


def format_report(report: SystemReport) -> str:
    def gb(n: int | None) -> str:
        return f"{n / (1024 ** 3):.1f} GB" if isinstance(n, int) else "unknown"

    lines = [
        "AARYA Voice Lab — System Report",
        "=" * 40,
        f"OS               : {report.os.platform}",
        f"Architecture     : {report.os.machine}",
        f"CPU              : {report.cpu.processor} "
        f"({report.cpu.physical_cores or '?'} physical / {report.cpu.logical_cores or '?'} logical cores)",
        f"RAM              : total={gb(report.memory.total_bytes)} available={gb(report.memory.available_bytes)}"
        + ("" if report.memory.source == "psutil" else " [psutil not installed — install requirements/base.txt]"),
        f"Disk (.)         : total={gb(report.disk.total_bytes)} free={gb(report.disk.free_bytes)}",
        f"Python           : {sys.version.split()[0]} ({report.python_executable})",
        f"FFmpeg           : {'available — ' + report.ffmpeg.version if report.ffmpeg.available else 'NOT AVAILABLE'}",
        f"GPU              : {'available' if report.gpu.available else 'NOT AVAILABLE'}"
        + (f" [{report.gpu.vendor}, via {report.gpu.detection_method}]" if report.gpu.available else "")
        + (f" ({report.gpu.note})" if report.gpu.note else ""),
    ]
    for device in report.gpu.devices:
        vram = f"{device.get('vram_mib')} MiB VRAM" if device.get("vram_mib") is not None else "VRAM unknown"
        lines.append(f"  - {device.get('name')} ({vram})")
    if report.gpu.driver_version:
        lines.append(f"  Driver version : {report.gpu.driver_version}")
    lines.append(
        f"CUDA (via torch) : {'available' if report.cuda.available else 'NOT AVAILABLE'}"
        + (f" ({report.cuda.note})" if report.cuda.note else "")
    )
    if not report.gpu.available:
        lines.append("")
        lines.append("NOTE: No GPU detected. CPU-only execution is supported at the")
        lines.append("architecture level; GPU-dependent pipeline stages will be slower")
        lines.append("or require future optimization/quantization work.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Report AARYA Voice Lab environment/hardware capabilities.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of text.")
    args = parser.parse_args(argv)

    report = collect_system_report()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
