"""Verify a built environment against its EnvironmentSpec.

Read-only: imports metadata for already-installed packages and inspects
hardware. Never installs, downloads weights, or requests credentials.

Designed to run *inside* the environment being checked (env-nemo's
interpreter checks env-nemo), which is why it depends only on the stdlib
plus this package's base dependencies.
"""

from __future__ import annotations

import importlib.metadata
import sys
from dataclasses import dataclass, field
from typing import Any

from aarya_voice_lab.core.capability import Capability, CapabilityState
from aarya_voice_lab.environment.audit import (
    check_cuda_runtime,
    check_ffmpeg,
    check_gpu,
    check_indicf5_vram_tier,
    check_pytorch,
)
from aarya_voice_lab.environment.specs import (
    EnvironmentId,
    EnvironmentSpec,
    ExternalRequirement,
    get_spec,
)


def _installed_version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _public_version(version: str) -> str:
    """Strip a PEP 440 local version segment (e.g. "2.13.0+cpu" ->
    "2.13.0"). scripts/install_env.sh installs torch from an explicit
    --cpu/--cuda wheel index specifically so pip cannot silently resolve
    a different accelerator build -- that wheel's version always carries
    a local segment identifying it ("+cpu", "+cu130", ...), which is not
    version drift and must not be reported as one."""
    return version.split("+", 1)[0]


def check_package(distribution: str, expected: str) -> Capability:
    """Compare an installed distribution against the spec's expected version.

    A mismatch is INCOMPATIBLE rather than merely informational: the whole
    point of pinning here is that silent version drift (pip resolving a
    different torch to satisfy some other package) is the main failure
    mode this project guards against. A PEP 440 local version segment
    (the "+cpu"/"+cu130" suffix on an accelerator-specific wheel) is not
    drift and is ignored unless the expected spec itself pins one.
    """
    version = _installed_version(distribution)
    if version is None:
        return Capability(distribution, CapabilityState.NOT_AVAILABLE, "not installed in this interpreter")
    if expected.startswith(">=") or expected.startswith("=="):
        # Loose specs are informational only; exact pins are enforced below.
        return Capability(distribution, CapabilityState.AVAILABLE, f"spec: {expected}", version)
    comparable_version = version if "+" in expected else _public_version(version)
    if comparable_version != expected:
        return Capability(
            distribution,
            CapabilityState.INCOMPATIBLE,
            f"expected {expected}; a different version usually means pip "
            "resolved around a conflict — see docs/COMPATIBILITY.md",
            version,
        )
    return Capability(distribution, CapabilityState.AVAILABLE, "matches spec", version)


def check_python_for_spec(spec: EnvironmentSpec) -> Capability:
    actual = f"{sys.version_info.major}.{sys.version_info.minor}"
    version_text = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if spec.python_version.startswith(actual):
        return Capability("Python", CapabilityState.AVAILABLE, f"spec: {spec.python_version}", version_text)
    return Capability(
        "Python",
        CapabilityState.AVAILABLE,
        f"running {actual}; spec targets {spec.python_version}",
        version_text,
    )


def check_model_availability(spec: EnvironmentSpec) -> Capability:
    """Report whether model weights are present — never fetch them."""
    if ExternalRequirement.GATED_MODEL_DOWNLOAD in spec.external_requirements:
        return Capability(
            "Model weights",
            CapabilityState.UNKNOWN,
            "this environment references GATED models; availability is not "
            "probed because probing can trigger an authenticated request. "
            "Weights must be fetched manually after approval.",
        )
    if ExternalRequirement.OPEN_MODEL_DOWNLOAD in spec.external_requirements:
        return Capability(
            "Model weights",
            CapabilityState.NOT_AVAILABLE,
            "not downloaded — Phase 1 deliberately downloads no weights. "
            "Fetch explicitly in a later approved phase.",
        )
    return Capability("Model weights", CapabilityState.OPTIONAL, "no weights required")


@dataclass
class EnvironmentVerification:
    spec: EnvironmentSpec
    capabilities: list[Capability] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """Whether the environment is built and internally consistent.

        Missing model weights do not make an environment unusable — Phase 1
        never downloads them — but an INCOMPATIBLE package does.
        """
        return not any(c.state is CapabilityState.INCOMPATIBLE for c in self.capabilities)

    def to_dict(self) -> dict[str, Any]:
        return {
            "environment": self.spec.env_id.value,
            "usable": self.usable,
            "capabilities": [c.to_dict() for c in self.capabilities],
            "warnings": self.warnings,
            "blockers": self.blockers,
        }


def verify_environment(env_id: EnvironmentId | str) -> EnvironmentVerification:
    spec = get_spec(env_id)
    result = EnvironmentVerification(spec=spec)

    result.capabilities.append(check_python_for_spec(spec))
    for distribution, expected in spec.expected_packages.items():
        result.capabilities.append(check_package(distribution, expected))

    if spec.env_id is not EnvironmentId.BASE:
        result.capabilities.append(check_pytorch())
        result.capabilities.append(check_gpu())
        result.capabilities.append(check_cuda_runtime())
        result.capabilities.append(check_model_availability(spec))

    if spec.env_id is EnvironmentId.WHISPERX:
        ffmpeg = check_ffmpeg()
        if ffmpeg.state is CapabilityState.OPTIONAL:
            # FFmpeg is genuinely required here, unlike in the base env.
            ffmpeg = Capability(
                "FFmpeg",
                CapabilityState.NOT_AVAILABLE,
                "REQUIRED by whisperx for audio decoding",
            )
        result.capabilities.append(ffmpeg)

    if spec.env_id is EnvironmentId.TTS:
        result.capabilities.append(check_indicf5_vram_tier())

    gpu = next((c for c in result.capabilities if c.name == "NVIDIA GPU"), None)
    if gpu is not None and gpu.state is not CapabilityState.AVAILABLE:
        if spec.cpu_supported:
            result.warnings.append(f"No GPU — CPU fallback supported. {spec.cpu_caveat}")
        else:
            result.blockers.append("No GPU, and this environment has no CPU fallback.")

    if spec.requires_approval:
        result.blockers.append(f"REQUIRES APPROVAL: {spec.requires_approval}")

    for requirement in spec.external_requirements:
        if requirement is ExternalRequirement.CREDENTIAL:
            result.blockers.append(
                "REQUIRES CREDENTIAL: an operator-supplied access token is needed. "
                "None is configured, and none will be configured automatically."
            )
        elif requirement is ExternalRequirement.GATED_MODEL_DOWNLOAD:
            result.blockers.append(
                "REQUIRES GATED MODEL: weights are behind an account and a terms "
                "agreement. STOP and obtain approval before proceeding."
            )
        elif requirement is ExternalRequirement.EXTERNAL_SERVICE:
            result.blockers.append("REQUIRES EXTERNAL SERVICE: incompatible with local-first operation.")

    return result


def format_verification(result: EnvironmentVerification) -> str:
    spec = result.spec
    lines = [
        f"AARYA Voice Lab — {spec.env_id.value} verification",
        "=" * 60,
        f"Purpose : {spec.purpose}",
        f"Python  : {spec.python_version}",
        f"Requires: {spec.requirements_file}",
        "",
    ]
    lines.extend(capability.format_line() for capability in result.capabilities)

    if result.warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"  ! {warning}" for warning in result.warnings)

    if result.blockers:
        lines.append("")
        lines.append("STOP CONDITIONS:")
        lines.extend(f"  * {blocker}" for blocker in result.blockers)

    if spec.notes:
        lines.append("")
        lines.append("Notes:")
        lines.extend(f"  - {note}" for note in spec.notes)

    lines.append("")
    if not result.usable:
        lines.append("RESULT: environment has INCOMPATIBLE packages — do not run stages in it.")
    elif any(c.state is CapabilityState.NOT_AVAILABLE for c in result.capabilities):
        lines.append("RESULT: environment is not fully built (see NOT_AVAILABLE above).")
    else:
        lines.append("RESULT: environment matches its specification.")
    return "\n".join(lines)
