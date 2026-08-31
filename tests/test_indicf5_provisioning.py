"""Tests for `pipeline.indicf5_provisioning` -- IndicF5 model/cache
provisioning for the installer (Phase D).

Base-interpreter-safe: nothing here imports `huggingface_hub`/
`safetensors`/`torch` (this module doesn't either -- see its own
docstring). The "not built" and mocked-response tests are deterministic
everywhere; the "real" test is capability-gated on `.envs/env-tts`
actually being provisioned, following the same convention
`test_hf_auth.py`/`test_voice_model_engine.py` already use.
"""

from __future__ import annotations

import pytest

from aarya_voice_lab.pipeline import indicf5_provisioning as provisioning_module
from aarya_voice_lab.pipeline.indicf5_provisioning import (
    FileProvisioningResult,
    ProvisioningError,
    ProvisioningResult,
    ensure_authenticated_then_provision,
    provision,
    verify,
)


def test_provision_raises_when_env_tts_not_built(monkeypatch):
    monkeypatch.setattr(provisioning_module, "_tts_python", lambda: None)
    with pytest.raises(ProvisioningError, match="not built"):
        provision()


def test_verify_raises_when_env_tts_not_built(monkeypatch):
    monkeypatch.setattr(provisioning_module, "_tts_python", lambda: None)
    with pytest.raises(ProvisioningError, match="not built"):
        verify()


def test_ensure_authenticated_then_provision_reports_authentication_failure_first(monkeypatch):
    """Confirms the auth-first ordering: an unauthenticated caller must
    see failure_kind="authentication" immediately, never a confusing
    download error from provision() itself being attempted anyway."""
    from aarya_voice_lab.pipeline.hf_auth import HFAuthStatus

    monkeypatch.setattr(
        provisioning_module, "check_existing_login", lambda: HFAuthStatus(authenticated=False)
    )

    def _fail_if_called():
        raise AssertionError("provision() must not be attempted when not authenticated")

    monkeypatch.setattr(provisioning_module, "provision", _fail_if_called)

    with pytest.raises(ProvisioningError) as exc_info:
        ensure_authenticated_then_provision()
    assert exc_info.value.failure_kind == "authentication"


def test_ensure_authenticated_then_provision_proceeds_when_authenticated(monkeypatch):
    from aarya_voice_lab.pipeline.hf_auth import HFAuthStatus

    monkeypatch.setattr(
        provisioning_module, "check_existing_login", lambda: HFAuthStatus(authenticated=True, username="test-user")
    )
    sentinel = ProvisioningResult(ok=True, files=())
    monkeypatch.setattr(provisioning_module, "provision", lambda: sentinel)

    assert ensure_authenticated_then_provision() is sentinel


@pytest.mark.parametrize("failure_kind", ["authentication", "gated_access", "network", "disk", "corruption", "unknown"])
def test_provisioning_error_carries_its_classified_failure_kind(failure_kind):
    """The five failure kinds Phase D requires callers to be able to
    distinguish, plus "unknown" as an honest catch-all -- never silently
    collapsed into a generic message."""
    error = ProvisioningError("some failure", failure_kind=failure_kind)
    assert error.failure_kind == failure_kind


def test_summary_lines_never_crashes_regardless_of_which_fields_a_response_included():
    """Regression test: verify()'s worker response omitted a "status"
    field that provision()'s always includes -- summary_lines() crashed
    with TypeError formatting None. Both a fully-populated success entry
    and a minimal one (no status/size, matching an early file-existence
    check before a real download attempt) must render without error."""
    result = ProvisioningResult(
        ok=False,
        files=(
            FileProvisioningResult(
                name="vocab", filename="checkpoints/vocab.txt", ok=True, status="already_cached", size_bytes=12345
            ),
            FileProvisioningResult(
                name="checkpoint", filename="model.safetensors", ok=True, status=None, size_bytes=None
            ),
            FileProvisioningResult(
                name="reference_audio", filename="prompts/x.wav", ok=False, error="disk error: No space left on device"
            ),
        ),
    )
    lines = result.summary_lines()
    assert len(lines) == 3
    assert "vocab" in lines[0]
    assert "checkpoint" in lines[1]
    assert "FAILED" in lines[2] and "No space left" in lines[2]


def test_verify_real_when_env_tts_is_provisioned():
    """Capability-gated real integration test, mirroring
    test_hf_auth.py's own convention: if `.envs/env-tts` is built AND
    already provisioned (both true as of this milestone -- see
    docs/INDICF5_INSTALLER.md), this proves the real subprocess bridge
    finds and structurally verifies every required IndicF5 asset -- not
    a mock. Skips (not fails) on a live-network-only failure, matching
    test_hf_auth.py's identical reasoning; any other failure is real and
    must fail the test."""
    if provisioning_module._tts_python() is None:
        pytest.skip("`.envs/env-tts` is not built in this environment -- see docs/INDICF5_INSTALLER.md")
    try:
        result = verify()
    except ProvisioningError as exc:
        if exc.failure_kind == "network":
            pytest.skip(f"network-dependent verification unavailable: {exc}")
        raise
    assert result.ok is True
    names = {f.name for f in result.files}
    assert names == {"vocab", "checkpoint", "reference_audio", "vocoder_config", "vocoder_weights"}
    assert all(f.ok for f in result.files)
