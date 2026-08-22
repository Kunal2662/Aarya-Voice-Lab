"""Capability audit: classify every toolchain prerequisite on this machine.

Builds on system_info (raw hardware facts) and turns each finding into a
CapabilityState so callers can distinguish "absent but irrelevant here"
from "absent and blocking" from "present but the wrong version".

Nothing here installs, downloads, or contacts the network. Probes are
read-only: `shutil.which`, importing an already-installed module, and
reading `--version` output.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

from aarya_voice_lab.core.capability import BLOCKING_STATES, Capability, CapabilityState
from aarya_voice_lab.system_info import collect_system_report

#: Interpreter range this project supports at all.
MIN_PYTHON = (3, 11)
MAX_PYTHON_EXCLUSIVE = (3, 14)
#: The version the ML toolchain should standardise on (see docs/COMPATIBILITY.md).
RECOMMENDED_PYTHON = (3, 12)

#: Minimum free disk for an ML environment build (torch + CUDA wheels are large).
ML_ENVIRONMENT_DISK_BYTES = 15 * 1024**3


def _module_version(module_name: str, distribution: str | None = None) -> str | None:
    try:
        return importlib.metadata.version(distribution or module_name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _module_installed(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def check_python() -> Capability:
    version = sys.version_info
    version_text = f"{version.major}.{version.minor}.{version.micro}"
    if version < MIN_PYTHON:
        return Capability(
            "Python",
            CapabilityState.INCOMPATIBLE,
            f"below the supported minimum {MIN_PYTHON[0]}.{MIN_PYTHON[1]}",
            version_text,
        )
    if version >= MAX_PYTHON_EXCLUSIVE:
        return Capability(
            "Python",
            CapabilityState.INCOMPATIBLE,
            f"at or above {MAX_PYTHON_EXCLUSIVE[0]}.{MAX_PYTHON_EXCLUSIVE[1]}, "
            "which the speech toolchain does not support",
            version_text,
        )
    if version[:2] != RECOMMENDED_PYTHON:
        return Capability(
            "Python",
            CapabilityState.AVAILABLE,
            f"supported, but {RECOMMENDED_PYTHON[0]}.{RECOMMENDED_PYTHON[1]} is "
            "recommended for the ML environments",
            version_text,
        )
    return Capability("Python", CapabilityState.AVAILABLE, "recommended version", version_text)


def check_pip() -> Capability:
    version = _module_version("pip")
    if version:
        return Capability("pip", CapabilityState.AVAILABLE, version=version)
    if shutil.which("pip") or shutil.which("pip3"):
        return Capability("pip", CapabilityState.AVAILABLE, "found on PATH; version not reported")
    return Capability("pip", CapabilityState.NOT_AVAILABLE, "required to build any environment")


def check_venv() -> Capability:
    """Virtual-environment support: the isolation strategy depends on it."""
    if _module_installed("venv"):
        return Capability("virtualenv support", CapabilityState.AVAILABLE, "stdlib venv importable")
    if shutil.which("uv"):
        return Capability("virtualenv support", CapabilityState.AVAILABLE, "uv available")
    return Capability(
        "virtualenv support",
        CapabilityState.NOT_AVAILABLE,
        "neither stdlib venv nor uv found; environment isolation is impossible",
    )


def check_ffmpeg() -> Capability:
    """FFmpeg is OPTIONAL for Phase 0/1 and REQUIRED for audio stages."""
    report = collect_system_report()
    if report.ffmpeg.available:
        version = (report.ffmpeg.version or "").split()
        return Capability(
            "FFmpeg",
            CapabilityState.AVAILABLE,
            version=version[2] if len(version) > 2 else None,
        )
    return Capability(
        "FFmpeg",
        CapabilityState.OPTIONAL,
        "not installed; required before any audio stage runs, not for Phase 1 "
        "(see docs/ENVIRONMENT.md for per-OS install steps)",
    )


def check_gpu() -> Capability:
    """NVIDIA-specific, by name, on purpose: scripts/install_env.sh's
    CUDA-vs-CPU torch wheel index decision depends on exactly this
    signal (see docs/GPU_STRATEGY.md), so this capability's name and
    meaning stay fixed. See check_accelerator() for the vendor-neutral
    signal that also recognizes AMD/other hardware."""
    report = collect_system_report()
    if report.gpu.available and report.gpu.vendor == "NVIDIA":
        names = ", ".join(str(d.get("name")) for d in report.gpu.devices)
        return Capability(
            "NVIDIA GPU",
            CapabilityState.AVAILABLE,
            f"{len(report.gpu.devices)} device(s): {names}",
            report.gpu.driver_version,
        )
    return Capability(
        "NVIDIA GPU",
        CapabilityState.OPTIONAL,
        "no NVIDIA GPU detected; CPU-only execution is supported (slower) — "
        f"{report.gpu.note or 'nvidia-smi not found'}",
    )


def check_accelerator() -> Capability:
    """Hardware-agnostic rule (Real ML Runtime milestone follow-up):
    AVAILABLE for ANY detected accelerator -- NVIDIA, AMD (rocm-smi), or
    a PCI-enumerable device of an unrecognized vendor (see
    system_info._detect_gpu_via_sysfs) -- never just NVIDIA. check_gpu()
    above stays NVIDIA-specific because a real, existing decision
    (the torch wheel index) depends on that exact signal; this capability
    is the one calibration/UI code should read when the question is
    "is there an accelerator at all", not "is it specifically NVIDIA"."""
    report = collect_system_report()
    if report.gpu.available:
        names = ", ".join(str(d.get("name")) for d in report.gpu.devices)
        detail = f"{len(report.gpu.devices)} device(s) via {report.gpu.detection_method}: {names}"
        if report.gpu.note:
            detail += f" — {report.gpu.note}"
        return Capability("Accelerator (any vendor)", CapabilityState.AVAILABLE, detail, report.gpu.vendor)
    return Capability(
        "Accelerator (any vendor)",
        CapabilityState.OPTIONAL,
        "no NVIDIA, AMD, or PCI-enumerable accelerator detected; "
        "CPU-only execution is supported (slower)",
    )


def check_cuda_runtime() -> Capability:
    report = collect_system_report()
    if report.cuda.available:
        return Capability("CUDA runtime", CapabilityState.AVAILABLE, version=report.cuda.cuda_version)
    if not report.cuda.torch_installed:
        return Capability(
            "CUDA runtime",
            CapabilityState.UNKNOWN,
            "torch is not installed, so CUDA availability cannot be confirmed here",
        )
    return Capability("CUDA runtime", CapabilityState.OPTIONAL, report.cuda.note or "torch reports no CUDA")


def check_cuda_toolkit() -> Capability:
    nvcc = shutil.which("nvcc")
    if not nvcc:
        return Capability(
            "CUDA toolkit (nvcc)",
            CapabilityState.OPTIONAL,
            "not required — PyTorch CUDA wheels bundle their own runtime; "
            "only needed to compile custom kernels",
        )
    try:
        result = subprocess.run([nvcc, "--version"], capture_output=True, text=True, timeout=10, check=False)
        line = result.stdout.strip().splitlines()[-1] if result.stdout else None
        return Capability("CUDA toolkit (nvcc)", CapabilityState.AVAILABLE, version=line)
    except (OSError, subprocess.SubprocessError) as exc:
        return Capability("CUDA toolkit (nvcc)", CapabilityState.UNKNOWN, f"nvcc probe failed: {exc}")


def check_pytorch() -> Capability:
    version = _module_version("torch")
    if version is None:
        return Capability(
            "PyTorch",
            CapabilityState.OPTIONAL,
            "not installed in this environment — expected for the base env; "
            "install it inside env-nemo / env-whisperx / env-tts instead",
        )
    return Capability("PyTorch", CapabilityState.AVAILABLE, version=version)


def check_disk() -> Capability:
    report = collect_system_report()
    free = report.disk.free_bytes
    free_gb = free / 1024**3
    if free < ML_ENVIRONMENT_DISK_BYTES:
        return Capability(
            "Disk space",
            CapabilityState.NOT_AVAILABLE,
            f"{free_gb:.1f} GB free; an ML environment (torch + CUDA wheels) "
            f"needs roughly {ML_ENVIRONMENT_DISK_BYTES / 1024**3:.0f} GB",
        )
    return Capability("Disk space", CapabilityState.AVAILABLE, f"{free_gb:.1f} GB free")


def check_memory() -> Capability:
    report = collect_system_report()
    if report.memory.total_bytes is None:
        return Capability("RAM", CapabilityState.UNKNOWN, report.memory.source)
    total_gb = report.memory.total_bytes / 1024**3
    if total_gb < 8:
        return Capability(
            "RAM",
            CapabilityState.INCOMPATIBLE,
            f"{total_gb:.1f} GB; CPU inference for speech models needs 8 GB or more",
        )
    return Capability("RAM", CapabilityState.AVAILABLE, f"{total_gb:.1f} GB total")


def check_cpu() -> Capability:
    report = collect_system_report()
    cores = report.cpu.logical_cores
    if not cores:
        return Capability("CPU", CapabilityState.UNKNOWN, "core count could not be determined")
    detail = f"{report.cpu.physical_cores or '?'} physical / {cores} logical"
    if cores < 4:
        return Capability("CPU", CapabilityState.AVAILABLE, f"{detail} — CPU stages will be slow")
    return Capability("CPU", CapabilityState.AVAILABLE, detail)


#: Every probe, in report order.
CAPABILITY_CHECKS = (
    check_python,
    check_pip,
    check_venv,
    check_cpu,
    check_memory,
    check_disk,
    check_ffmpeg,
    check_gpu,
    check_accelerator,
    check_cuda_runtime,
    check_cuda_toolkit,
    check_pytorch,
)


@dataclass
class EnvironmentAudit:
    capabilities: list[Capability] = field(default_factory=list)

    @property
    def blocking(self) -> list[Capability]:
        """Only genuinely-missing or wrong-version capabilities block.

        UNKNOWN is deliberately not blocking: on a CPU-only machine, "CUDA
        state can't be determined because torch isn't installed" is the
        expected answer, not a fault.
        """
        return [c for c in self.capabilities if c.state in BLOCKING_STATES]

    @property
    def unknown(self) -> list[Capability]:
        return [c for c in self.capabilities if c.state is CapabilityState.UNKNOWN]

    @property
    def ok(self) -> bool:
        return not self.blocking

    def get(self, name: str) -> Capability | None:
        for capability in self.capabilities:
            if capability.name == name:
                return capability
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "capabilities": [c.to_dict() for c in self.capabilities],
        }


def run_audit() -> EnvironmentAudit:
    return EnvironmentAudit(capabilities=[check() for check in CAPABILITY_CHECKS])


def format_audit(audit: EnvironmentAudit) -> str:
    lines = ["AARYA Voice Lab — Capability Audit", "=" * 60]
    lines.extend(capability.format_line() for capability in audit.capabilities)
    lines.append("")
    if audit.ok:
        lines.append("No blocking capability problems for the base environment.")
    else:
        lines.append("Blocking problems:")
        lines.extend(f"  - {c.name}: {c.detail}" for c in audit.blocking)
    if audit.unknown:
        lines.append("")
        lines.append("Undetermined (not blocking):")
        lines.extend(f"  ? {c.name}: {c.detail}" for c in audit.unknown)
    lines.append("")
    lines.append("Note: OPTIONAL means absent but not required for the current phase.")
    lines.append("ML toolchain requirements are checked per-environment; see")
    lines.append("`aarya-voice nemo-check` and `aarya-voice whisperx-check`.")
    return "\n".join(lines)
