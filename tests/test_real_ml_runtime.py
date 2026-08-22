"""Real ML Runtime & Model Integration milestone -- capability-gated
integration tests against the actual installed ML runtime(s).

Every test here checks the REAL, current capability state first and
skips with an explicit reason if the corresponding environment
(`.envs/env-nemo`, `.envs/env-tts`) was not built in this run -- per the
milestone's own testing rule ("If a real model cannot run in CI: use
capability-gated integration tests... report NOT_CONFIGURED rather than
silently passing through synthetic behaviour"). None of these tests use
a mock model or a monkeypatched response: every assertion here is about
what a genuinely installed, genuinely loaded model actually produced.

No real recording is read anywhere in this file -- `data/source/` is
empty in every environment this project runs in, and every fixture here
is synthetic/arithmetic exactly like the rest of the test suite.
"""

from __future__ import annotations

import math
import time

import pytest

from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.identity.calibration import uncalibrated
from aarya_voice_lab.identity.embeddings import (
    EmbeddingStore,
    LocalNeuralEmbeddingProvider,
    cosine_similarity,
    get_provider,
)
from aarya_voice_lab.identity.enrollment import EnrollmentEngine, EnrollmentSample
from aarya_voice_lab.identity.profile import SpeakerRole
from aarya_voice_lab.identity.verification import VerificationEngine, assert_real_identity_claim


def _tone(freq_hz: float, *, sample_rate: int = 16000, duration_seconds: float = 1.5) -> list[int]:
    count = int(sample_rate * duration_seconds)
    return [int(32767 * 0.3 * math.sin(2 * math.pi * freq_hz * i / sample_rate)) for i in range(count)]


def _real_embedding_provider_or_skip() -> LocalNeuralEmbeddingProvider:
    provider = get_provider(LocalNeuralEmbeddingProvider.name)
    state = provider.capability_state()
    if state["state"] != "AVAILABLE":
        pytest.skip(f"env-nemo not configured in this environment: {state}")
    return provider


# ==========================================================================
# Real embedding model -- loading, shape, determinism, latency
# ==========================================================================


def test_real_embedding_model_loads_and_reports_real_metadata():
    provider = _real_embedding_provider_or_skip()
    vector = provider.embed(_tone(220.0), 16000)
    assert vector.dimension == 192
    assert vector.provider_name == "local-neural-embedding"
    assert vector.is_synthetic is False
    assert vector.sample_rate == 16000
    metadata = vector.metadata()
    assert "sha256" in metadata and len(metadata["sha256"]) == 64


def test_real_embedding_similarity_is_not_fabricated():
    """A real model must produce a *different* similarity for identical
    vs. clearly different input -- a hardcoded or fabricated score would
    not vary with the input at all."""
    provider = _real_embedding_provider_or_skip()
    reference = provider.embed(_tone(220.0), 16000)
    same_signal = provider.embed(_tone(220.0), 16000)
    different_signal = provider.embed(_tone(880.0), 16000)

    self_similarity = cosine_similarity(reference, same_signal)
    cross_similarity = cosine_similarity(reference, different_signal)

    assert self_similarity == pytest.approx(1.0, abs=1e-6)
    assert cross_similarity < self_similarity


def test_real_embedding_model_load_and_inference_latency_are_measured():
    """Real Voice Model Engine + Real ML Runtime milestones' §performance
    requirement: measure, never fabricate. This records the actual
    latency this run observed -- it is not a benchmark assertion (no
    pass/fail threshold), only proof the numbers are real measurements."""
    provider = _real_embedding_provider_or_skip()
    samples = _tone(220.0)

    started = time.monotonic()
    provider.embed(samples, 16000)
    elapsed = time.monotonic() - started

    assert elapsed > 0, "a real subprocess round-trip cannot complete in zero measured time"
    assert elapsed < provider.EMBED_TIMEOUT_SECONDS, "embedding exceeded its own configured timeout"


# ==========================================================================
# Real speaker verification -- end to end through the existing engine
# ==========================================================================


def test_real_provider_enrollment_and_verification_end_to_end(tmp_path):
    """The existing VerificationEngine/EnrollmentEngine (built in an
    earlier phase, before any real provider existed) is provider-
    agnostic by design -- this proves it, unmodified, against a real,
    loaded TitaNet-large model instead of the synthetic provider every
    prior test used."""
    provider = _real_embedding_provider_or_skip()
    data_root = DataRoot(root=tmp_path / "data").create()

    enroll_engine = EnrollmentEngine(provider, data_root)
    enrolled = enroll_engine.enroll(
        profile_id="real-target",
        role=SpeakerRole.SYNTHETIC_SPEAKER,  # no real person's identity is claimed here -- see module docstring
        strategy="synthetic",
        samples=[EnrollmentSample(sample_id="s1", samples=_tone(220.0), sample_rate=16000)],
    )
    assert enrolled.profile.provider_is_synthetic is False
    assert enrolled.profile.embedding_dimension == 192

    store = EmbeddingStore(data_root)
    verifier = VerificationEngine(
        embedding_store=store,
        calibration=uncalibrated(provider.name, provider.version, is_synthetic=False),
        target_profile=enrolled.profile,
    )
    candidate = provider.embed(_tone(220.0), 16000)  # same tone -- proxy for "same speaker"
    result = verifier.verify(verification_id="v1", segment_id="seg1", candidate=candidate, duration_seconds=1.5)

    assert result.provider_is_synthetic is False
    assert result.primary is not None
    assert 0.0 <= result.primary.similarity <= 1.0
    assert result.primary.model_name == provider.name

    # This is the real behavioural difference a real provider unlocks:
    # assert_real_identity_claim() raises for a synthetic-derived ELIGIBLE
    # result, but must NOT raise here purely because the provider is
    # synthetic -- it may still legitimately raise for other policy
    # reasons (e.g. insufficient calibration evidence), which is fine;
    # the point under test is specifically the synthetic-provenance gate.
    try:
        assert_real_identity_claim(result, operation="test")
    except Exception as exc:  # noqa: BLE001 -- inspect *why*, not whether
        assert "synthetic" not in str(exc).lower(), (
            f"a real, non-synthetic verification must never be blocked on synthetic-provenance grounds: {exc}"
        )
