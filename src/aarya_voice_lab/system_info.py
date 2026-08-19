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
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
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


def get_gpu_info() -> GPUInfo:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return GPUInfo(available=False, detection_method="none", note="nvidia-smi not found on PATH")

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
        + (f" ({report.gpu.note})" if report.gpu.note else ""),
    ]
    for device in report.gpu.devices:
        lines.append(f"  - {device.get('name')} ({device.get('vram_mib')} MiB VRAM)")
    if report.gpu.driver_version:
        lines.append(f"  NVIDIA driver  : {report.gpu.driver_version}")
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
