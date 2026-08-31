"""Tests for `pipeline.indicf5_install_report` -- the Phase F installer
status/reporting layer.

Mocks every sub-check `build_installer_report()` calls (audit, hf_auth,
provisioning, the smoke-test subprocess) so this suite is deterministic
and fast everywhere, mirroring this project's established mocking
convention (`monkeypatch.setattr(module, "function_name", ...)`). A
single real, capability-gated end-to-end run (proving the actual READY
path) was performed manually during Phase F's own verification -- see
docs/INDICF5_INSTALLER.md; repeating a ~30-60s real GPU run inside the
regular test suite is not appropriate here.
"""

from __future__ import annotations

import json

from aarya_voice_lab.core.capability import Capability, CapabilityState
from aarya_voice_lab.environment.audit import EnvironmentAudit
from aarya_voice_lab.pipeline import indicf5_install_report as report_module
from aarya_voice_lab.pipeline.hf_auth import HFAuthError, HFAuthStatus
from aarya_voice_lab.pipeline.indicf5_install_report import (
    FailureCategory,
    InstallerReadiness,
    _SmokeTestOutcome,
    build_installer_report,
    format_installer_report,
)
from aarya_voice_lab.pipeline.indicf5_provisioning import ProvisioningError, ProvisioningResult


def _stub_happy_path(monkeypatch, *, smoke_ok: bool = True) -> None:
    """Every check succeeds up through (optionally) the smoke test --
    the shared baseline the individual failure tests deviate from one
    check at a time."""
    monkeypatch.setattr(
        report_module,
        "run_audit",
        lambda: EnvironmentAudit(
            capabilities=[
                Capability("Python", CapabilityState.AVAILABLE, version="3.12.10"),
                Capability("RAM", CapabilityState.AVAILABLE, version="16 GB"),
                Capability("Disk space", CapabilityState.AVAILABLE, detail="100 GB free"),
            ]
        ),
    )
    monkeypatch.setattr(
        report_module,
        "check_indicf5_vram_tier",
        lambda: Capability("IndicF5 VRAM tier", CapabilityState.AVAILABLE, "4096 MiB, verified reference config"),
    )
    monkeypatch.setattr(
        report_module,
        "_run_tts_check_json",
        lambda: {
            "capabilities": [
                {"name": "torch", "state": "AVAILABLE", "detail": "matches spec", "version": "2.13.0+cu126"},
                {"name": "CUDA runtime", "state": "AVAILABLE", "detail": "", "version": "12.6"},
            ]
        },
    )
    monkeypatch.setattr(
        report_module, "check_existing_login", lambda: HFAuthStatus(authenticated=True, username="test-user")
    )
    monkeypatch.setattr(
        report_module,
        "verify_provisioning",
        lambda: ProvisioningResult(ok=True, files=()),
    )
    if smoke_ok:
        monkeypatch.setattr(
            report_module,
            "_run_smoke_test_subprocess",
            lambda: _SmokeTestOutcome(
                ok=True,
                detail="all mechanical checks passed",
                wav_paths=("C:\\fake\\preview-1.wav", "C:\\fake\\preview-2.wav"),
            ),
        )


def test_ready_only_when_smoke_test_actually_ran_and_passed(monkeypatch):
    _stub_happy_path(monkeypatch, smoke_ok=True)
    report = build_installer_report()
    assert report.readiness is InstallerReadiness.READY
    assert report.smoke_test_ran is True
    assert report.failure_categories == ()
    assert report.generated_wav_paths == ("C:\\fake\\preview-1.wav", "C:\\fake\\preview-2.wav")


def test_not_ready_when_smoke_test_not_run(monkeypatch):
    """Imports/detection alone are never sufficient -- run_smoke_test=False
    must never produce READY, even if every other check looked fine."""
    _stub_happy_path(monkeypatch, smoke_ok=True)
    report = build_installer_report(run_smoke_test=False)
    assert report.readiness is InstallerReadiness.NOT_READY
    assert report.smoke_test_ran is False


def test_not_ready_when_smoke_test_fails(monkeypatch):
    _stub_happy_path(monkeypatch, smoke_ok=False)
    monkeypatch.setattr(
        report_module,
        "_run_smoke_test_subprocess",
        lambda: _SmokeTestOutcome(
            ok=False, detail="generation failed", failure_category=FailureCategory.INFERENCE_FAILURE
        ),
    )
    report = build_installer_report()
    assert report.readiness is InstallerReadiness.NOT_READY
    assert report.smoke_test_ran is True
    assert FailureCategory.INFERENCE_FAILURE.value in report.failure_categories


def test_insufficient_vram_short_circuits_before_smoke_test(monkeypatch):
    _stub_happy_path(monkeypatch, smoke_ok=True)
    monkeypatch.setattr(
        report_module,
        "check_indicf5_vram_tier",
        lambda: Capability(
            "IndicF5 VRAM tier", CapabilityState.INCOMPATIBLE, "2048 MiB -- below 3072 MiB, INSUFFICIENT"
        ),
    )
    smoke_test_called = False

    def _fail_if_called():
        nonlocal smoke_test_called
        smoke_test_called = True
        raise AssertionError("smoke test must not run when VRAM is already known-insufficient")

    monkeypatch.setattr(report_module, "_run_smoke_test_subprocess", _fail_if_called)

    report = build_installer_report()
    assert report.readiness is InstallerReadiness.NOT_READY
    assert FailureCategory.INSUFFICIENT_VRAM.value in report.failure_categories
    assert report.smoke_test_ran is False
    assert not smoke_test_called


def test_gpu_unavailable_when_no_nvidia_gpu_detected(monkeypatch):
    _stub_happy_path(monkeypatch, smoke_ok=True)
    monkeypatch.setattr(
        report_module,
        "check_indicf5_vram_tier",
        lambda: Capability(
            "IndicF5 VRAM tier", CapabilityState.OPTIONAL, "no NVIDIA GPU detected -- IndicF5 falls back to CPU"
        ),
    )
    report = build_installer_report()
    assert report.readiness is InstallerReadiness.NOT_READY
    assert FailureCategory.GPU_UNAVAILABLE.value in report.failure_categories


def test_tts_environment_missing(monkeypatch):
    _stub_happy_path(monkeypatch, smoke_ok=True)
    monkeypatch.setattr(report_module, "_run_tts_check_json", lambda: None)
    report = build_installer_report()
    assert report.readiness is InstallerReadiness.NOT_READY
    assert FailureCategory.TTS_ENVIRONMENT_MISSING.value in report.failure_categories


def test_hf_auth_missing(monkeypatch):
    _stub_happy_path(monkeypatch, smoke_ok=True)
    monkeypatch.setattr(report_module, "check_existing_login", lambda: HFAuthStatus(authenticated=False))
    report = build_installer_report()
    assert report.readiness is InstallerReadiness.NOT_READY
    assert FailureCategory.HF_AUTH_MISSING.value in report.failure_categories


def test_hf_network_failure_during_auth_check(monkeypatch):
    _stub_happy_path(monkeypatch, smoke_ok=True)

    def _raise_network_error():
        raise HFAuthError("could not reach HuggingFace to validate the cached token: ConnectionError")

    monkeypatch.setattr(report_module, "check_existing_login", _raise_network_error)
    report = build_installer_report()
    assert report.readiness is InstallerReadiness.NOT_READY
    assert FailureCategory.HF_NETWORK_FAILURE.value in report.failure_categories


def test_hf_gated_access_denied(monkeypatch):
    _stub_happy_path(monkeypatch, smoke_ok=True)

    def _raise_gated():
        raise ProvisioningError("access not granted", failure_kind="gated_access")

    monkeypatch.setattr(report_module, "verify_provisioning", _raise_gated)
    report = build_installer_report()
    assert report.readiness is InstallerReadiness.NOT_READY
    assert FailureCategory.HF_GATED_ACCESS_DENIED.value in report.failure_categories


def test_model_corruption_detected(monkeypatch):
    _stub_happy_path(monkeypatch, smoke_ok=True)

    def _raise_corruption():
        raise ProvisioningError("model.safetensors is truncated", failure_kind="corruption")

    monkeypatch.setattr(report_module, "verify_provisioning", _raise_corruption)
    report = build_installer_report()
    assert report.readiness is InstallerReadiness.NOT_READY
    assert FailureCategory.MODEL_CORRUPTION.value in report.failure_categories


def test_model_missing_maps_to_model_missing_category(monkeypatch):
    _stub_happy_path(monkeypatch, smoke_ok=True)

    def _raise_missing():
        raise ProvisioningError("checkpoint not present in cache", failure_kind="network")

    monkeypatch.setattr(report_module, "verify_provisioning", _raise_missing)
    report = build_installer_report()
    assert report.readiness is InstallerReadiness.NOT_READY
    assert FailureCategory.HF_NETWORK_FAILURE.value in report.failure_categories


def test_report_never_contains_a_token_like_field(monkeypatch):
    """Security property: nothing this module reads (HFAuthStatus,
    ProvisioningResult, Capability) has a token field to begin with, so
    the report's JSON serialization structurally cannot include one."""
    _stub_happy_path(monkeypatch, smoke_ok=True)
    report = build_installer_report()
    serialized = json.dumps(report.to_dict())
    assert "token" not in serialized.lower()


def test_to_dict_and_format_never_crash_across_states(monkeypatch):
    for smoke_ok in (True, False):
        _stub_happy_path(monkeypatch, smoke_ok=smoke_ok)
        if not smoke_ok:
            monkeypatch.setattr(
                report_module,
                "_run_smoke_test_subprocess",
                lambda: _SmokeTestOutcome(ok=False, detail="x", failure_category=FailureCategory.MODEL_LOADING_FAILURE),
            )
        report = build_installer_report()
        json.dumps(report.to_dict())  # must not raise
        text = format_installer_report(report)
        assert "READY" in text or "NOT READY" in text


def test_failure_categories_are_deduplicated_and_order_preserved(monkeypatch):
    _stub_happy_path(monkeypatch, smoke_ok=True)
    monkeypatch.setattr(
        report_module,
        "check_indicf5_vram_tier",
        lambda: Capability("IndicF5 VRAM tier", CapabilityState.INCOMPATIBLE, "insufficient"),
    )
    report = build_installer_report()
    assert len(report.failure_categories) == len(set(report.failure_categories))
