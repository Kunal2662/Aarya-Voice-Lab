"""Tests for `pipeline.hf_auth` -- secure, subprocess-isolated HuggingFace
authentication for the IndicF5 installer (Phase C).

Base-interpreter-safe: nothing here imports `huggingface_hub` (this
module doesn't either -- see its own docstring). The "not configured"
tests are deterministic everywhere; the "real" test is capability-gated
on `.envs/env-tts` actually being built, following the exact convention
`test_voice_model_engine.py`'s embedding-provider tests already use.
"""

from __future__ import annotations

import pytest

from aarya_voice_lab.pipeline import hf_auth as hf_auth_module
from aarya_voice_lab.pipeline.hf_auth import (
    HFAuthError,
    HFAuthStatus,
    check_existing_login,
    check_repo_access,
    login_with_token,
)


def test_check_existing_login_raises_when_env_tts_not_built(tmp_path, monkeypatch):
    monkeypatch.setattr(hf_auth_module, "_tts_python", lambda: None)
    with pytest.raises(HFAuthError, match="not built"):
        check_existing_login()


def test_check_repo_access_raises_when_env_tts_not_built(monkeypatch):
    monkeypatch.setattr(hf_auth_module, "_tts_python", lambda: None)
    with pytest.raises(HFAuthError, match="not built"):
        check_repo_access("ai4bharat/IndicF5")


def test_login_with_token_never_leaks_the_token_value_in_an_error(monkeypatch):
    """Security property: even when the worker call itself fails (e.g. a
    subprocess error unrelated to the token), the token value must never
    appear anywhere in the resulting exception message."""
    secret_token = "hf_totally_secret_value_should_never_appear_ANYWHERE"

    def _fake_run_worker(request, *, timeout=30.0):
        raise HFAuthError("worker exited 1 with no response file -- stderr: some unrelated failure")

    monkeypatch.setattr(hf_auth_module, "_run_worker", _fake_run_worker)
    with pytest.raises(HFAuthError) as exc_info:
        login_with_token(secret_token)
    assert secret_token not in str(exc_info.value)


def test_login_with_token_returns_status_from_worker_response(monkeypatch):
    monkeypatch.setattr(
        hf_auth_module,
        "_run_worker",
        lambda request, timeout=30.0: {"ok": True, "authenticated": True, "username": "test-user"},
    )
    status = login_with_token("irrelevant-in-this-mocked-test")
    assert status == HFAuthStatus(authenticated=True, username="test-user")


def test_check_repo_access_reports_gated_repo_as_not_accessible(monkeypatch):
    """Regression test for a real bug found during the Phase-2 installer
    audit: the worker used to report EVERY repo whose metadata it could
    read as accessible=True, gated=False -- including gated repos,
    because HuggingFace serves a gated repo's metadata to any caller
    regardless of approval (model_info() essentially never raises
    GatedRepoError). Fixed to read ModelInfo.gated and, for a gated repo,
    conservatively report accessible=False rather than assume approval
    it cannot actually confirm without a real download."""
    monkeypatch.setattr(
        hf_auth_module,
        "_run_worker",
        lambda request, timeout=30.0: {
            "ok": True,
            "accessible": False,
            "gated": True,
            "detail": "repo is gated (model_info() reports metadata to any caller regardless of approval...)",
        },
    )
    status = check_repo_access("some/gated-repo")
    assert status.gated is True
    assert status.accessible is False


def test_check_repo_access_reports_public_repo_as_accessible(monkeypatch):
    monkeypatch.setattr(
        hf_auth_module,
        "_run_worker",
        lambda request, timeout=30.0: {"ok": True, "accessible": True, "gated": False},
    )
    status = check_repo_access("bert-base-uncased")
    assert status.gated is False
    assert status.accessible is True


def test_check_existing_login_reports_not_authenticated_honestly(monkeypatch):
    monkeypatch.setattr(
        hf_auth_module,
        "_run_worker",
        lambda request, timeout=30.0: {"ok": True, "authenticated": False, "detail": "no token cached locally"},
    )
    status = check_existing_login()
    assert status.authenticated is False
    assert "no token cached" in status.detail


def test_check_existing_login_real_when_env_tts_is_built():
    """Capability-gated real integration test (mirrors
    test_local_neural_embedding_provider_real_inference_when_configured's
    own convention exactly, skip included): if `.envs/env-tts` is
    actually built in this environment (it is, as of the installer
    Phase B milestone -- see docs/INDICF5_INSTALLER.md), this proves the
    real subprocess bridge works end to end -- not a mock. If it is not
    built (a fresh clone or CI without the ML environment), this skips
    with an honest reason rather than failing on an environment
    difference this test cannot control."""
    if hf_auth_module._tts_python() is None:
        pytest.skip("`.envs/env-tts` is not built in this environment -- see docs/INDICF5_INSTALLER.md")
    try:
        status = check_existing_login()
    except HFAuthError as exc:
        # This call needs live network reachability to huggingface.co,
        # unlike the embedding provider's real-inference precedent (local
        # computation only) -- a transient connection failure here is an
        # environment condition, not a code defect. huggingface_hub
        # itself already retries internally (confirmed: up to 5 attempts
        # with backoff) before this surfaces at all, so this is a real,
        # sustained network issue, not a one-off worth retrying again here.
        if "could not reach huggingface" in str(exc).lower():
            pytest.skip(f"live network to huggingface.co unavailable: {exc}")
        raise
    assert isinstance(status, HFAuthStatus)
    assert isinstance(status.authenticated, bool)


def test_check_repo_access_real_gated_vs_public(monkeypatch):
    """Capability-gated real integration test, same convention as
    test_check_existing_login_real_when_env_tts_is_built. Confirms the
    Phase-2-audit fix against real HuggingFace responses, not a mock:
    a well-known public repo reports gated=False, and IndicF5's own
    (gated) repo reports gated=True -- proving the worker now actually
    reads ModelInfo.gated instead of unconditionally reporting False."""
    if hf_auth_module._tts_python() is None:
        pytest.skip("`.envs/env-tts` is not built in this environment -- see docs/INDICF5_INSTALLER.md")
    network_error_markers = ("could not reach huggingface", "connectionerror", "timeout", "connecterror")
    try:
        public_status = check_repo_access("bert-base-uncased")
        gated_status = check_repo_access("ai4bharat/IndicF5")
    except HFAuthError as exc:
        if any(marker in str(exc).lower() for marker in network_error_markers):
            pytest.skip(f"live network to huggingface.co unavailable: {exc}")
        raise
    assert public_status.gated is False
    assert public_status.accessible is True
    assert gated_status.gated is True


def test_login_with_token_real_invalid_token_is_classified_as_rejected_not_network_failure():
    """Capability-gated real integration test. Regression test for a real
    bug found during the Windows-installer milestone's own real-machine
    testing: hf_auth_worker.py's _run_login() used to catch every
    exception generically as "token validation failed", so a genuinely
    valid token that happened to hit this session's own documented
    network flakiness (WinError 10054 against huggingface.co) was
    misreported exactly like an actually-invalid token -- the "network
    failure must not be falsely reported as invalid authentication" rule
    this module's _run_check() already followed, but _run_login() did
    not. Fixed to mirror _run_check()'s HfHubHTTPError/401 handling. This
    test can only directly prove the "genuinely rejected" half (a real
    invalid token, deterministic); the network-failure half already has
    extensive real evidence recorded in docs/INDICF5_INSTALLER.md."""
    if hf_auth_module._tts_python() is None:
        pytest.skip("`.envs/env-tts` is not built in this environment -- see docs/INDICF5_INSTALLER.md")
    with pytest.raises(HFAuthError) as exc_info:
        login_with_token("hf_this_is_a_deliberately_invalid_garbage_token_00000")
    message = str(exc_info.value).lower()
    if "could not reach huggingface" in message or "connectionerror" in message:
        pytest.skip(f"live network to huggingface.co unavailable: {exc_info.value}")
    assert "rejected" in message or "401" in message, (
        f"an invalid token must be classified as rejected, not a generic/network failure: {exc_info.value}"
    )
