"""Capability audit must classify, never crash, and never call absence an error."""

from __future__ import annotations

import json

from aarya_voice_lab.core.capability import BLOCKING_STATES, Capability, CapabilityState
from aarya_voice_lab.environment import audit as audit_module
from aarya_voice_lab.environment.audit import (
    CAPABILITY_CHECKS,
    INDICF5_VRAM_INSUFFICIENT_BELOW_MIB,
    INDICF5_VRAM_SUPPORTED_AT_OR_ABOVE_MIB,
    EnvironmentAudit,
    check_accelerator,
    check_cuda_runtime,
    check_ffmpeg,
    check_gpu,
    check_indicf5_vram_tier,
    check_python,
    check_pytorch,
    format_audit,
    run_audit,
)
from aarya_voice_lab.system_info import GPUInfo


def test_every_check_returns_a_capability():
    for check in CAPABILITY_CHECKS:
        capability = check()
        assert isinstance(capability, Capability)
        assert isinstance(capability.state, CapabilityState)
        assert capability.name


def test_audit_runs_and_serializes():
    result = run_audit()
    assert result.capabilities
    json.dumps(result.to_dict())


def test_missing_gpu_is_optional_not_an_error(monkeypatch):
    """Phase 1 rule: absence of an NVIDIA GPU must never be an error."""
    monkeypatch.setattr(audit_module.shutil, "which", lambda name: None)
    capability = check_gpu()
    assert capability.state is not CapabilityState.NOT_AVAILABLE
    assert capability.state is not CapabilityState.INCOMPATIBLE
    assert capability.ok


def test_missing_accelerator_is_optional_not_an_error(monkeypatch):
    """Hardware-agnostic rule: same "absence is never an error" contract
    as check_gpu(), for the vendor-neutral capability."""
    monkeypatch.setattr(audit_module.shutil, "which", lambda name: None)
    monkeypatch.setattr("aarya_voice_lab.system_info._detect_gpu_via_sysfs", lambda: None)
    capability = check_accelerator()
    assert capability.state is not CapabilityState.NOT_AVAILABLE
    assert capability.state is not CapabilityState.INCOMPATIBLE
    assert capability.ok


class _FakeReport:
    """Minimal stand-in for SystemReport -- check_gpu()/check_accelerator()
    only ever read .gpu off whatever collect_system_report() returns."""

    def __init__(self, gpu: GPUInfo) -> None:
        self.gpu = gpu


_AMD_GPU = GPUInfo(available=True, devices=[{"name": "Radeon Test GPU"}], detection_method="rocm-smi", vendor="AMD")


def test_accelerator_available_for_a_non_nvidia_device(monkeypatch):
    """The whole point of this capability: it must go AVAILABLE for an
    AMD/other GPU, which check_gpu() (NVIDIA-only) never will."""
    monkeypatch.setattr(audit_module, "collect_system_report", lambda: _FakeReport(_AMD_GPU))
    capability = check_accelerator()
    assert capability.state is CapabilityState.AVAILABLE
    assert capability.version == "AMD"


def test_check_gpu_stays_nvidia_specific_even_when_a_non_nvidia_gpu_is_present(monkeypatch):
    """check_gpu() must not go AVAILABLE just because *some* GPU (e.g.
    AMD, detected via the new vendor-neutral path) is present -- the
    torch-wheel-index decision this capability's name is depended on for
    is specifically about NVIDIA/CUDA."""
    monkeypatch.setattr(audit_module, "collect_system_report", lambda: _FakeReport(_AMD_GPU))
    capability = check_gpu()
    assert capability.state is not CapabilityState.AVAILABLE
    assert capability.ok


def _nvidia_gpu(vram_mib: str) -> GPUInfo:
    return GPUInfo(
        available=True,
        devices=[{"name": "Test NVIDIA GPU", "vram_mib": vram_mib}],
        detection_method="nvidia-smi",
        vendor="NVIDIA",
    )


def test_vram_tier_no_nvidia_gpu_is_optional_not_blocking(monkeypatch):
    """No GPU at all (or a non-NVIDIA one) must never block -- IndicF5's
    CPU fallback exists, even though it is unverified/experimental."""
    monkeypatch.setattr(audit_module, "collect_system_report", lambda: _FakeReport(_AMD_GPU))
    capability = check_indicf5_vram_tier()
    assert capability.state is CapabilityState.OPTIONAL
    assert capability.ok


def test_vram_tier_below_3gb_is_incompatible(monkeypatch):
    """< 3 GB: INSUFFICIENT, do not attempt IndicF5 on GPU -- this must be
    a genuinely blocking state, not merely a warning."""
    monkeypatch.setattr(audit_module, "collect_system_report", lambda: _FakeReport(_nvidia_gpu("2048")))
    capability = check_indicf5_vram_tier()
    assert capability.state is CapabilityState.INCOMPATIBLE
    assert not capability.ok
    assert "insufficient" in capability.detail.lower()


def test_vram_tier_3_to_4gb_is_constrained_but_not_blocking(monkeypatch):
    monkeypatch.setattr(audit_module, "collect_system_report", lambda: _FakeReport(_nvidia_gpu("3584")))
    capability = check_indicf5_vram_tier()
    assert capability.state is CapabilityState.OPTIONAL
    assert capability.ok
    assert "constrained" in capability.detail.lower() or "unverified" in capability.detail.lower()


def test_vram_tier_at_or_above_4gb_reference_config_is_available(monkeypatch):
    """The exact reference machine this tier was measured on: RTX 3050
    Laptop GPU, 4096 MiB."""
    monkeypatch.setattr(audit_module, "collect_system_report", lambda: _FakeReport(_nvidia_gpu("4096")))
    capability = check_indicf5_vram_tier()
    assert capability.state is CapabilityState.AVAILABLE
    assert INDICF5_VRAM_INSUFFICIENT_BELOW_MIB == 3072
    assert INDICF5_VRAM_SUPPORTED_AT_OR_ABOVE_MIB == 4096


def test_vram_tier_available_detail_never_claims_universal_guarantee(monkeypatch):
    """The AVAILABLE tier must always name it as a measured reference
    configuration, never imply every >= 4 GB GPU has actually been tested."""
    monkeypatch.setattr(audit_module, "collect_system_report", lambda: _FakeReport(_nvidia_gpu("8192")))
    capability = check_indicf5_vram_tier()
    assert capability.state is CapabilityState.AVAILABLE
    assert "verified" in capability.detail.lower()
    assert "reference" in capability.detail.lower()


def test_vram_tier_unreadable_vram_is_unknown_not_blocking(monkeypatch):
    unreadable = GPUInfo(
        available=True, devices=[{"name": "Test NVIDIA GPU"}], detection_method="nvidia-smi", vendor="NVIDIA"
    )
    monkeypatch.setattr(audit_module, "collect_system_report", lambda: _FakeReport(unreadable))
    capability = check_indicf5_vram_tier()
    assert capability.state is CapabilityState.UNKNOWN


def test_missing_ffmpeg_is_optional_for_base_environment():
    capability = check_ffmpeg()
    assert capability.state in (CapabilityState.AVAILABLE, CapabilityState.OPTIONAL)


def test_unknown_is_not_blocking():
    """An undeterminable probe must not fail the audit — see check_cuda_runtime
    on a machine with no torch installed."""
    result = EnvironmentAudit(
        capabilities=[
            Capability("a", CapabilityState.AVAILABLE),
            Capability("b", CapabilityState.UNKNOWN, "cannot determine"),
        ]
    )
    assert result.ok
    assert result.unknown
    assert not result.blocking


def test_not_available_is_blocking():
    result = EnvironmentAudit(capabilities=[Capability("x", CapabilityState.NOT_AVAILABLE)])
    assert not result.ok
    assert result.blocking


def test_incompatible_is_blocking():
    result = EnvironmentAudit(capabilities=[Capability("x", CapabilityState.INCOMPATIBLE)])
    assert not result.ok


def test_blocking_states_are_exactly_the_two_hard_failures():
    assert BLOCKING_STATES == {CapabilityState.NOT_AVAILABLE, CapabilityState.INCOMPATIBLE}


def test_current_python_is_supported():
    capability = check_python()
    assert capability.state is CapabilityState.AVAILABLE


def test_pytorch_absent_from_base_env_is_optional():
    """torch belongs in the ML envs, not the base env — its absence here is fine."""
    capability = check_pytorch()
    assert capability.ok


def test_cuda_runtime_without_torch_is_unknown_not_failed():
    capability = check_cuda_runtime()
    assert capability.state in (
        CapabilityState.AVAILABLE,
        CapabilityState.OPTIONAL,
        CapabilityState.UNKNOWN,
    )


def test_format_audit_renders_all_states():
    result = EnvironmentAudit(
        capabilities=[Capability(state.value, state, "detail") for state in CapabilityState]
    )
    text = format_audit(result)
    for state in CapabilityState:
        assert state.value in text


def test_capability_format_line_includes_state():
    line = Capability("FFmpeg", CapabilityState.OPTIONAL, "not installed", "6.0").format_line()
    assert "OPTIONAL" in line and "FFmpeg" in line and "6.0" in line
