"""Environment specs encode the isolation decision and the stop conditions.

These tests guard properties that, if silently changed, would let the
project drift back into a single shared environment or auto-configure a
credential.
"""

from __future__ import annotations

import json

import pytest

from aarya_voice_lab.core.capability import CapabilityState
from aarya_voice_lab.environment.specs import (
    ENVIRONMENT_SPECS,
    EnvironmentId,
    ExternalRequirement,
    get_spec,
    specs_requiring_approval,
    specs_requiring_credentials,
)
from aarya_voice_lab.environment.verify import (
    check_package,
    format_verification,
    verify_environment,
)


def test_every_environment_id_has_a_spec():
    for env_id in EnvironmentId:
        assert get_spec(env_id).env_id is env_id


def test_nemo_and_whisperx_are_separate_environments():
    """The core isolation decision: they must never share an env."""
    assert EnvironmentId.NEMO != EnvironmentId.WHISPERX
    assert get_spec(EnvironmentId.NEMO).requirements_file != get_spec(EnvironmentId.WHISPERX).requirements_file


def test_nemo_and_whisperx_pin_different_torch_versions():
    """This divergence is the documented reason for isolation. If these ever
    match, revisit docs/COMPATIBILITY.md rather than deleting this test."""
    nemo_torch = get_spec(EnvironmentId.NEMO).expected_packages["torch"]
    whisperx_torch = get_spec(EnvironmentId.WHISPERX).expected_packages["torch"]
    assert nemo_torch != whisperx_torch


def test_nemo_requires_no_credentials():
    """Sortformer is ungated — this is why it is the preferred primary."""
    spec = get_spec(EnvironmentId.NEMO)
    assert ExternalRequirement.CREDENTIAL not in spec.external_requirements
    assert ExternalRequirement.GATED_MODEL_DOWNLOAD not in spec.external_requirements
    assert spec.requires_approval is None


def test_whisperx_is_flagged_for_credentials_and_approval():
    spec = get_spec(EnvironmentId.WHISPERX)
    assert ExternalRequirement.CREDENTIAL in spec.external_requirements
    assert ExternalRequirement.GATED_MODEL_DOWNLOAD in spec.external_requirements
    assert spec.requires_approval


def test_no_environment_requires_a_paid_external_service():
    """Local-first: nothing may depend on a hosted/paid service."""
    for spec in ENVIRONMENT_SPECS.values():
        assert ExternalRequirement.EXTERNAL_SERVICE not in spec.external_requirements


def test_every_environment_supports_cpu():
    """CPU-only development machines must remain viable everywhere."""
    for spec in ENVIRONMENT_SPECS.values():
        assert spec.cpu_supported
        if spec.env_id is not EnvironmentId.BASE:
            assert spec.cpu_caveat, f"{spec.env_id} claims CPU support with no caveat documented"


def test_specs_requiring_credentials_is_exactly_whisperx_and_tts():
    """IndicF5 (env-tts) is a GATED HuggingFace repo — confirmed empirically
    (anonymous download returns 401 GatedRepoError), not assumed. It joined
    WhisperX as the second environment genuinely requiring a credential."""
    assert {s.env_id for s in specs_requiring_credentials()} == {EnvironmentId.WHISPERX, EnvironmentId.TTS}


def test_approval_required_environments_are_flagged():
    """env-tts's approval gate was retired once IndicF5 was selected and
    verified — the reason it existed ("no model selected") no longer
    holds. env-whisperx keeps its gate: a real, unresolved third-party
    credential + gated-model decision."""
    flagged = {s.env_id for s in specs_requiring_approval()}
    assert EnvironmentId.WHISPERX in flagged
    assert EnvironmentId.TTS not in flagged
    assert EnvironmentId.BASE not in flagged


def test_base_environment_has_no_external_requirements():
    assert get_spec(EnvironmentId.BASE).external_requirements == ()


def test_check_package_reports_version_mismatch_as_incompatible():
    """Silent version drift is the main hazard this project guards against."""
    capability = check_package("jsonschema", "0.0.1-not-a-real-version")
    assert capability.state is CapabilityState.INCOMPATIBLE


def test_check_package_reports_missing_distribution():
    capability = check_package("definitely-not-installed-xyz", "1.0.0")
    assert capability.state is CapabilityState.NOT_AVAILABLE


def test_check_package_accepts_loose_spec():
    capability = check_package("jsonschema", ">=4.20")
    assert capability.state is CapabilityState.AVAILABLE


def test_check_package_ignores_local_version_suffix(monkeypatch):
    """Real ML runtime integration milestone -- scripts/install_env.sh
    installs torch from an explicit --cpu/--cuda wheel index specifically
    so the accelerator build is deterministic; that wheel's version
    always carries a PEP 440 local segment ("2.13.0+cpu"). Comparing that
    verbatim against an exact pin ("2.13.0") would report every
    correctly-installed torch as INCOMPATIBLE, which is exactly backwards."""
    import importlib.metadata

    from aarya_voice_lab.environment import verify as verify_module

    def _fake_version(name: str) -> str:
        if name == "torch":
            return "2.13.0+cpu"
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", _fake_version)
    capability = verify_module.check_package("torch", "2.13.0")
    assert capability.state is CapabilityState.AVAILABLE
    assert capability.version == "2.13.0+cpu"


def test_check_package_still_flags_a_real_local_version_mismatch(monkeypatch):
    """If the expected spec itself pins a local segment, that segment is
    still enforced -- only an unpinned expectation ignores it."""
    import importlib.metadata

    monkeypatch.setattr(importlib.metadata, "version", lambda name: "2.13.0+cu130")
    capability = check_package("torch", "2.13.0+cpu")
    assert capability.state is CapabilityState.INCOMPATIBLE


@pytest.mark.parametrize("env_id", list(EnvironmentId))
def test_verification_runs_for_every_environment(env_id):
    result = verify_environment(env_id)
    json.dumps(result.to_dict())
    assert format_verification(result)


def test_whisperx_verification_reports_stop_conditions():
    result = verify_environment(EnvironmentId.WHISPERX)
    assert result.blockers
    joined = " ".join(result.blockers).lower()
    assert "credential" in joined or "gated" in joined


def test_nemo_verification_reports_no_stop_conditions():
    assert verify_environment(EnvironmentId.NEMO).blockers == []


def test_verification_never_reports_weights_as_downloaded():
    """Phase 1 downloads no model weights; verification must not imply otherwise."""
    for env_id in (EnvironmentId.NEMO, EnvironmentId.TTS):
        result = verify_environment(env_id)
        weights = next((c for c in result.capabilities if c.name == "Model weights"), None)
        assert weights is not None
        assert weights.state is not CapabilityState.AVAILABLE
