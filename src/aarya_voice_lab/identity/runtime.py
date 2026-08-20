"""Runtime capability metadata — deliberately hardware-agnostic.

Core interfaces name **no vendor, no product, and no specific GPU**. Any
particular machine — whatever GPU it happens to contain — is one
development or test host, never a design target. Hard-coding one would
quietly make every other machine a special case.

So capability is expressed as **data an implementation declares**, not a
branch on vendor names. Code asks "does this component require an
accelerator, and is one present?" — never "is this CUDA?". Adding a new
backend must never require editing decision logic elsewhere.

Backends the architecture must be able to accommodate where technically
supported: NVIDIA, AMD, Intel, integrated GPUs, discrete GPUs, CPU-only
systems, and future accelerators not yet named here. `ComputeBackend`
therefore carries an `OTHER` member so an unanticipated accelerator is
representable without a schema change.

The future AI Calibration Engine (VL-D15) detects the actual hardware and
optimises for it; this module only supplies the vocabulary it will read.
The long-term direction remains a portable runtime that generates and
plays audio on a CPU-only machine (VL-D19 / VL-D20).

Nothing here detects hardware itself — `environment.audit` already does
that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ComputeBackend(StrEnum):
    """Where a component can execute.

    `CPU` is the baseline every component must support unless it declares
    otherwise — it is the only backend guaranteed to exist everywhere.

    The accelerator members below are an open set, listed alphabetically
    rather than by preference: no vendor is privileged, and `OTHER` exists
    so a backend nobody has anticipated is still representable. Decision
    logic reads `AccelerationRequirement`, never a specific member here.
    """

    CPU = "cpu"
    #: AMD ROCm.
    ROCM = "rocm"
    #: NVIDIA CUDA.
    CUDA = "cuda"
    #: Apple Metal.
    METAL = "metal"
    #: Vendor-neutral compute API.
    OPENCL = "opencl"
    #: Cross-vendor graphics/compute.
    VULKAN = "vulkan"
    #: Intel XPU (integrated and discrete).
    XPU = "xpu"
    #: Any accelerator not named above.
    OTHER = "other"


#: Every backend that is not plain CPU. Used to answer "is an accelerator
#: involved?" without naming a vendor.
ACCELERATOR_BACKENDS: frozenset[ComputeBackend] = frozenset(
    b for b in ComputeBackend if b is not ComputeBackend.CPU
)


class AccelerationRequirement(StrEnum):
    #: Runs on CPU; an accelerator is not used at all.
    CPU_ONLY = "cpu_only"
    #: Runs on CPU; an accelerator makes it faster.
    CPU_WITH_OPTIONAL_ACCELERATION = "cpu_with_optional_acceleration"
    #: Cannot run without an accelerator. Must be justified.
    ACCELERATOR_REQUIRED = "accelerator_required"
    #: Not yet determined — must not be assumed either way.
    UNKNOWN = "unknown"


class PortabilityClass(StrEnum):
    """How freely an artifact can move to another machine."""

    #: Runs anywhere Python runs; no accelerator, no large native deps.
    PORTABLE = "portable"
    #: Portable in principle, unverified in practice.
    PORTABLE_UNVERIFIED = "portable_unverified"
    #: Tied to a specific accelerator or platform.
    PLATFORM_BOUND = "platform_bound"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RuntimeCapability:
    """What a component needs, and what it promises.

    Declared by embedding providers, verification engines, and (later)
    voice models, so placement and packaging decisions can be made from
    data instead of assumptions.
    """

    component: str
    acceleration: AccelerationRequirement
    supported_backends: tuple[ComputeBackend, ...] = (ComputeBackend.CPU,)
    portability: PortabilityClass = PortabilityClass.UNKNOWN
    min_ram_gb: float | None = None
    min_vram_gb: float | None = None
    #: Free-form notes for a future calibration engine (VL-D15) to key on.
    performance_notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def runs_on_cpu(self) -> bool:
        return ComputeBackend.CPU in self.supported_backends

    @property
    def requires_accelerator(self) -> bool:
        return self.acceleration is AccelerationRequirement.ACCELERATOR_REQUIRED

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "acceleration": self.acceleration.value,
            "supported_backends": [b.value for b in self.supported_backends],
            "portability": self.portability.value,
            "min_ram_gb": self.min_ram_gb,
            "min_vram_gb": self.min_vram_gb,
            "runs_on_cpu": self.runs_on_cpu,
            "requires_accelerator": self.requires_accelerator,
            "performance_notes": list(self.performance_notes),
        }


#: The synthetic provider is pure arithmetic — the most portable thing here.
SYNTHETIC_PROVIDER_CAPABILITY = RuntimeCapability(
    component="synthetic-cosine-projection",
    acceleration=AccelerationRequirement.CPU_ONLY,
    supported_backends=(ComputeBackend.CPU,),
    portability=PortabilityClass.PORTABLE,
    min_ram_gb=0.5,
    performance_notes=("stdlib only; no numpy, no torch, no accelerator",),
)

#: Verification decision logic is pure Python over already-computed scores.
VERIFICATION_ENGINE_CAPABILITY = RuntimeCapability(
    component="verification-engine",
    acceleration=AccelerationRequirement.CPU_ONLY,
    supported_backends=(ComputeBackend.CPU,),
    portability=PortabilityClass.PORTABLE,
    min_ram_gb=0.5,
    performance_notes=("decision logic only; embedding computation happens in the provider",),
)


def describe_portability(capabilities: list[RuntimeCapability]) -> dict[str, Any]:
    """Summarise whether a set of components could run on a CPU-only host.

    Used by future packaging (VL-D20) to answer "can this be shipped to a
    machine with no GPU?" without inspecting vendor-specific details.
    """
    accelerator_bound = [c.component for c in capabilities if c.requires_accelerator]
    unknown = [c.component for c in capabilities if c.acceleration is AccelerationRequirement.UNKNOWN]
    return {
        "cpu_only_viable": not accelerator_bound and not unknown,
        "accelerator_bound_components": accelerator_bound,
        "undetermined_components": unknown,
        # Honest about the limit of this claim: declarations are not proof.
        "note": (
            "Derived from component declarations, not from an executed CPU-only run. "
            "A portability claim is not verified until it has actually been run on a "
            "machine with no accelerator present."
        ),
    }
