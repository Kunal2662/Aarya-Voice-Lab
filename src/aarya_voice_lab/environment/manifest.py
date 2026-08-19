"""Environment manifests: a machine-readable record of what an environment
actually contains, for reproducibility and for attaching to experiment runs.

Distinct from EnvironmentSpec (what an environment *should* be), this
captures what it *is* on this machine right now: exact installed versions,
interpreter, and hardware. An experiment that cannot name its environment
manifest cannot claim to be reproducible.
"""

from __future__ import annotations

import importlib.metadata
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aarya_voice_lab import __version__
from aarya_voice_lab.system_info import collect_system_report


def installed_packages() -> dict[str, str]:
    """Every installed distribution and its version, sorted."""
    packages = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata["Name"]
        if name:
            packages[name] = distribution.version
    return dict(sorted(packages.items(), key=lambda item: item[0].lower()))


def build_environment_manifest(environment_id: str = "base") -> dict[str, Any]:
    report = collect_system_report()
    return {
        "environment_id": environment_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "aarya_voice_lab_version": __version__,
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
        },
        "platform": {
            "system": report.os.system,
            "release": report.os.release,
            "machine": report.os.machine,
            "platform": report.os.platform,
        },
        "hardware": {
            "cpu": report.cpu.processor,
            "physical_cores": report.cpu.physical_cores,
            "logical_cores": report.cpu.logical_cores,
            "total_ram_bytes": report.memory.total_bytes,
            "gpu_available": report.gpu.available,
            "gpu_devices": report.gpu.devices,
            "nvidia_driver": report.gpu.driver_version,
            "cuda_available": report.cuda.available,
            "cuda_version": report.cuda.cuda_version,
        },
        "tools": {
            "ffmpeg_available": report.ffmpeg.available,
            "ffmpeg_version": report.ffmpeg.version,
        },
        "packages": installed_packages(),
    }


def write_environment_manifest(path: Path, environment_id: str = "base") -> Path:
    manifest = build_environment_manifest(environment_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return path
