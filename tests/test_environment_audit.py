"""Capability audit must classify, never crash, and never call absence an error."""

from __future__ import annotations

import json

from aarya_voice_lab.core.capability import BLOCKING_STATES, Capability, CapabilityState
from aarya_voice_lab.environment import audit as audit_module
from aarya_voice_lab.environment.audit import (
    CAPABILITY_CHECKS,
    EnvironmentAudit,
    check_cuda_runtime,
    check_ffmpeg,
    check_gpu,
    check_python,
    check_pytorch,
    format_audit,
    run_audit,
)


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
