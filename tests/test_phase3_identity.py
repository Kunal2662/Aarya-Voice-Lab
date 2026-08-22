"""Phase 3 identity architecture tests.

Everything runs on synthetic fixtures. No real recording, no real speaker
model, no real embedding, anywhere in this file.
"""

from __future__ import annotations

import subprocess

import pytest

from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.core.paths import PROJECT_ROOT
from aarya_voice_lab.identity.audit import AuditEventType, AuditLog
from aarya_voice_lab.identity.calibration import (
    CalibrationError,
    CalibrationEvidence,
    CalibrationRecord,
    CalibrationState,
    ScoreDistribution,
    ThresholdConfig,
    provisional_from_reviewer_feedback,
    provisional_from_synthetic,
    require_calibrated,
    uncalibrated,
)
from aarya_voice_lab.identity.embeddings import (
    EmbeddingProviderError,
    EmbeddingStore,
    ProviderKind,
    SyntheticEmbeddingProvider,
    SyntheticProvenanceError,
    available_providers,
    cosine_similarity,
    get_provider,
)
from aarya_voice_lab.identity.enrollment import (
    EnrollmentEngine,
    EnrollmentError,
    EnrollmentSample,
    HumanApprovalRequired,
    available_strategies,
    get_strategy,
)
from aarya_voice_lab.identity.profile import (
    EnrollmentState,
    ProfileError,
    ProfileProvenance,
    SpeakerProfile,
    SpeakerRole,
)
from aarya_voice_lab.identity.review import (
    IdentityDecision,
    IdentityReviewQueue,
    IdentityReviewRecord,
    ReviewError,
    promote_to_dataset,
)
from aarya_voice_lab.identity.verification import (
    ReviewerFeedback,
    VerificationDecision,
    VerificationEngine,
    assert_real_identity_claim,
)
from aarya_voice_lab.schemas.base import SchemaName, validate
from aarya_voice_lab.testing.synthetic_audio import generate_speech_like

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROVIDER = SyntheticEmbeddingProvider()


def _signal(tmp_path, name: str, freq: float, seconds: float = 3.0):
    from aarya_voice_lab.audio.probe import read_wav_mono_samples

    path = generate_speech_like(tmp_path / name, frequency_hz=freq, duration_seconds=seconds)
    return read_wav_mono_samples(path)


def _sample(tmp_path, name: str, freq: float, sample_id: str, **kwargs) -> EnrollmentSample:
    samples, rate = _signal(tmp_path, name, freq)
    return EnrollmentSample(sample_id=sample_id, samples=samples, sample_rate=rate, **kwargs)


def _engine(tmp_path) -> EnrollmentEngine:
    data_root = DataRoot(root=tmp_path / "data").create()
    return EnrollmentEngine(PROVIDER, data_root)


# ---------------------------------------------------------------------------
# Embedding provider + store
# ---------------------------------------------------------------------------


def test_synthetic_embedding_is_deterministic(tmp_path):
    samples, rate = _signal(tmp_path, "a.wav", 200.0)
    first = PROVIDER.embed(samples, rate)
    second = PROVIDER.embed(samples, rate)
    assert first.values == second.values
    assert first.sha256() == second.sha256()


def test_synthetic_embedding_is_marked_synthetic(tmp_path):
    samples, rate = _signal(tmp_path, "a.wav", 200.0)
    vector = PROVIDER.embed(samples, rate)
    assert vector.is_synthetic
    assert vector.metadata()["provider_is_synthetic"] is True


def test_different_signals_produce_different_embeddings(tmp_path):
    a_samples, rate = _signal(tmp_path, "a.wav", 180.0)
    b_samples, _ = _signal(tmp_path, "b.wav", 320.0)
    a = PROVIDER.embed(a_samples, rate)
    b = PROVIDER.embed(b_samples, rate)
    assert cosine_similarity(a, a) > 0.99
    assert cosine_similarity(a, b) < 0.8


def test_embedding_metadata_never_contains_the_vector(tmp_path):
    samples, rate = _signal(tmp_path, "a.wav", 200.0)
    metadata = PROVIDER.embed(samples, rate).metadata()
    assert "values" not in metadata
    assert "vector" not in metadata


def test_empty_signal_is_refused():
    with pytest.raises(EmbeddingProviderError):
        PROVIDER.embed([], 16_000)


def test_cross_provider_comparison_is_refused(tmp_path):
    samples, rate = _signal(tmp_path, "a.wav", 200.0)
    a = PROVIDER.embed(samples, rate)
    other = SyntheticEmbeddingProvider()
    other.name = "different-provider"
    b = other.embed(samples, rate)
    b = type(b)(
        values=b.values, provider_name="different-provider", provider_version=b.provider_version,
        provider_kind=b.provider_kind, sample_rate=b.sample_rate,
        source_duration_seconds=b.source_duration_seconds,
    )
    with pytest.raises(EmbeddingProviderError, match="different providers"):
        cosine_similarity(a, b)


def test_unknown_provider_is_refused():
    with pytest.raises(EmbeddingProviderError, match="not installed"):
        get_provider("titanet-real")


def test_only_synthetic_provider_can_actually_produce_an_embedding():
    """Real Voice Model Engine milestone -- the provider *registry* now
    also names a real, local-neural provider class (the abstraction real
    providers implement), but no real embedding runtime is installed in
    this environment (confirmed empirically, not assumed -- see
    identity.embeddings.LocalNeuralEmbeddingProvider.capability_state()).
    So the synthetic provider remains the only one that can actually
    embed anything: every other registered provider must report itself
    NOT_CONFIGURED and must refuse to embed rather than silently
    producing a fabricated vector."""
    assert set(available_providers()) == {"synthetic-cosine-projection", "local-neural-embedding"}

    real = get_provider("local-neural-embedding")
    assert real.kind is ProviderKind.NEURAL
    assert not real.is_synthetic
    state = real.capability_state()
    assert state["state"] == "NOT_CONFIGURED"
    with pytest.raises(EmbeddingProviderError):
        real.embed([1, 2, 3], 16000)


def test_store_roundtrip_verifies_integrity(tmp_path):
    data_root = DataRoot(root=tmp_path / "data").create()
    store = EmbeddingStore(data_root)
    samples, rate = _signal(tmp_path, "a.wav", 200.0)
    vector = PROVIDER.embed(samples, rate)
    stored = store.save("emb-1", vector)
    loaded = store.load("emb-1")
    assert loaded.sha256() == stored.sha256


def test_store_detects_corrupted_vector(tmp_path):
    data_root = DataRoot(root=tmp_path / "data").create()
    store = EmbeddingStore(data_root)
    samples, rate = _signal(tmp_path, "a.wav", 200.0)
    store.save("emb-1", PROVIDER.embed(samples, rate))
    (store.directory / "emb-1.vec").write_bytes(b"\x00" * PROVIDER.dimension * 8)
    with pytest.raises(EmbeddingProviderError, match="integrity"):
        store.load("emb-1")


def test_store_delete_removes_vector_and_sidecar(tmp_path):
    data_root = DataRoot(root=tmp_path / "data").create()
    store = EmbeddingStore(data_root)
    samples, rate = _signal(tmp_path, "a.wav", 200.0)
    store.save("emb-1", PROVIDER.embed(samples, rate))
    assert store.delete("emb-1")
    assert store.list_ids() == []
    assert not store.exists("emb-1")


def test_store_never_writes_into_source(tmp_path):
    """The embedding directory lives beside, never inside, source/."""
    data_root = DataRoot(root=tmp_path / "data").create()
    store = EmbeddingStore(data_root)
    assert not data_root.is_within_source(store.directory)


# ---------------------------------------------------------------------------
# Git protection — behavioural, asking Git itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "data/embeddings/profile.vec",
        "data/embeddings/profile.meta.json",
        "data/enrollment/target.v1.json",
        "data/audit/identity.jsonl",
        "anything/embeddings/leak.bin",
        "speaker.vector",
    ],
)
def test_git_ignores_biometric_artifacts(path):
    result = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "check-ignore", "-q", path],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"git does NOT ignore {path}"


def test_identity_source_files_remain_trackable():
    """Protection must not swallow the Phase 3 source code itself."""
    result = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "check-ignore", "-q", "src/aarya_voice_lab/identity/embeddings.py"],
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0


# ---------------------------------------------------------------------------
# Enrollment: pluggable strategies
# ---------------------------------------------------------------------------


def test_strategies_are_pluggable():
    assert set(available_strategies()) >= {"synthetic", "direct_recording", "human_anchored"}


def test_strategy_registry_accepts_new_strategies():
    from aarya_voice_lab.identity.enrollment import EnrollmentStrategy, register_strategy

    class FutureStrategy(EnrollmentStrategy):
        name = "future-test-strategy"
        version = "0.1.0"

        def admit(self, sample):
            return True, None

    register_strategy(FutureStrategy)
    assert "future-test-strategy" in available_strategies()
    assert get_strategy("future-test-strategy").name == "future-test-strategy"


def test_no_production_strategy_is_hard_coded():
    """The engine takes the strategy as a parameter — verify none is baked in."""
    import inspect

    from aarya_voice_lab.identity import enrollment

    source = inspect.getsource(enrollment.EnrollmentEngine)
    assert "human_anchored" not in source
    assert "direct_recording" not in source


def test_synthetic_enrollment_produces_synthetic_profile(tmp_path):
    engine = _engine(tmp_path)
    result = engine.enroll(
        profile_id="p1",
        role=SpeakerRole.SYNTHETIC_SPEAKER,
        strategy="synthetic",
        samples=[_sample(tmp_path, "a.wav", 200.0, "s1")],
    )
    assert result.profile.provider_is_synthetic
    assert result.profile.is_usable
    assert result.profile.enrollment_state is EnrollmentState.ENROLLED


def test_synthetic_strategy_cannot_enroll_a_real_role(tmp_path):
    engine = _engine(tmp_path)
    with pytest.raises(EnrollmentError, match="cannot enroll role"):
        engine.enroll(
            profile_id="p1",
            role=SpeakerRole.TARGET_SPEAKER,
            strategy="synthetic",
            samples=[_sample(tmp_path, "a.wav", 200.0, "s1")],
        )


def test_human_anchored_requires_human_confirmation(tmp_path):
    engine = _engine(tmp_path)
    unconfirmed = _sample(
        tmp_path, "a.wav", 200.0, "s1",
        overlap_status="NO_OVERLAP_DETECTED", quality_status="PASS",
    )
    with pytest.raises(EnrollmentError, match="admissible"):
        engine.enroll(
            profile_id="target",
            role=SpeakerRole.TARGET_SPEAKER,
            strategy="human_anchored",
            samples=[unconfirmed, unconfirmed],
            approved_by="operator",
        )


def test_human_anchored_rejects_unknown_overlap(tmp_path):
    """UNKNOWN overlap must never seed a profile."""
    strategy = get_strategy("human_anchored")
    sample = _sample(
        tmp_path, "a.wav", 200.0, "s1",
        overlap_status="UNKNOWN", quality_status="PASS",
        human_confirmed=True, confirmed_by="operator",
    )
    admitted, reason = strategy.admit(sample)
    assert not admitted
    assert "overlap" in reason


def test_human_anchored_requires_approver_identity(tmp_path):
    engine = _engine(tmp_path)
    good = [
        _sample(
            tmp_path, f"s{i}.wav", 200.0 + i, f"s{i}",
            overlap_status="NO_OVERLAP_DETECTED", quality_status="PASS",
            human_confirmed=True, confirmed_by="operator",
        )
        for i in range(2)
    ]
    with pytest.raises(HumanApprovalRequired):
        engine.enroll(
            profile_id="target",
            role=SpeakerRole.TARGET_SPEAKER,
            strategy="human_anchored",
            samples=good,
            approved_by=None,
        )


def test_human_anchored_enrolls_with_approval(tmp_path):
    engine = _engine(tmp_path)
    good = [
        _sample(
            tmp_path, f"s{i}.wav", 200.0 + i, f"s{i}",
            segment_id=f"seg-{i}", source_file_id="src-1",
            overlap_status="NO_OVERLAP_DETECTED", quality_status="PASS",
            human_confirmed=True, confirmed_by="operator",
        )
        for i in range(2)
    ]
    result = engine.enroll(
        profile_id="target",
        role=SpeakerRole.TARGET_SPEAKER,
        strategy="human_anchored",
        samples=good,
        approved_by="operator",
    )
    assert result.profile.is_usable
    assert result.profile.provenance.approved_by == "operator"
    assert result.profile.provenance.seed_segment_ids == ["seg-0", "seg-1"]
    # Single-source seeds should warn about channel encoding.
    assert any("one source file" in w for w in result.warnings)


def test_enrollment_versioning_and_supersession(tmp_path):
    engine = _engine(tmp_path)

    def enroll():
        return engine.enroll(
            profile_id="p1",
            role=SpeakerRole.SYNTHETIC_SPEAKER,
            strategy="synthetic",
            samples=[_sample(tmp_path, "a.wav", 200.0, "s1")],
        )

    first = enroll()
    second = enroll()
    assert first.profile.version == 1
    assert second.profile.version == 2

    engine.supersede("p1", 2)
    reloaded_v1 = engine.profile_store.load("p1", 1)
    assert reloaded_v1.superseded_by == "p1@v2"
    assert not reloaded_v1.is_usable
    assert engine.profile_store.load("p1", 2).is_usable


def test_superseded_profile_refuses_verification_use(tmp_path):
    profile = SpeakerProfile(
        profile_id="old", role=SpeakerRole.OPERATOR, version=1,
        enrollment_state=EnrollmentState.SUPERSEDED,
        provenance=ProfileProvenance(strategy_name="x", strategy_version="1"),
        superseded_by="old@v2",
    )
    with pytest.raises(ProfileError, match="superseded"):
        profile.require_usable()


def test_profile_schema_validation(tmp_path):
    engine = _engine(tmp_path)
    result = engine.enroll(
        profile_id="p1",
        role=SpeakerRole.SYNTHETIC_SPEAKER,
        strategy="synthetic",
        samples=[_sample(tmp_path, "a.wav", 200.0, "s1")],
    )
    payload = result.profile.to_dict()
    payload.pop("all_versions", None)
    validate(payload, SchemaName.ENROLLMENT_PROFILE)


def test_profile_fingerprint_changes_with_embedding(tmp_path):
    engine = _engine(tmp_path)
    a = engine.enroll(
        profile_id="p1", role=SpeakerRole.SYNTHETIC_SPEAKER, strategy="synthetic",
        samples=[_sample(tmp_path, "a.wav", 200.0, "s1")],
    )
    b = engine.enroll(
        profile_id="p1", role=SpeakerRole.SYNTHETIC_SPEAKER, strategy="synthetic",
        samples=[_sample(tmp_path, "b.wav", 320.0, "s2")],
    )
    assert a.profile.fingerprint() != b.profile.fingerprint()


# ---------------------------------------------------------------------------
# Calibration honesty
# ---------------------------------------------------------------------------


def test_uncalibrated_is_the_default():
    record = uncalibrated("synthetic", "1.0.0", is_synthetic=True)
    assert record.state is CalibrationState.UNCALIBRATED
    assert not record.is_statistically_validated
    assert record.limitations


def test_synthetic_calibration_is_provisional_never_calibrated():
    record = provisional_from_synthetic(
        "c1", [0.9, 0.95, 0.92], [0.4, 0.5], "synthetic", "1.0.0"
    )
    assert record.state is CalibrationState.PROVISIONAL
    assert not record.is_statistically_validated
    assert any("synthetic" in limitation.lower() for limitation in record.limitations)


def test_calibrated_requires_held_out_evidence():
    with pytest.raises(CalibrationError, match="held-out"):
        CalibrationRecord(
            calibration_id="c1",
            state=CalibrationState.CALIBRATED,
            evidence=CalibrationEvidence.SYNTHETIC_FIXTURES,
            thresholds=ThresholdConfig(),
            provider_name="synthetic",
            provider_version="1.0.0",
            provider_is_synthetic=False,
        )


def test_synthetic_provider_can_never_be_calibrated():
    with pytest.raises(CalibrationError, match="synthetic"):
        CalibrationRecord(
            calibration_id="c1",
            state=CalibrationState.CALIBRATED,
            evidence=CalibrationEvidence.OPERATOR_HELD_OUT,
            thresholds=ThresholdConfig(),
            provider_name="synthetic",
            provider_version="1.0.0",
            provider_is_synthetic=True,
        )


def test_reviewer_feedback_calibration_stays_provisional():
    base = uncalibrated("provider", "1.0.0", is_synthetic=False)
    record = provisional_from_reviewer_feedback(
        "c2", base, feedback_count=40, agreement_rate=0.95
    )
    assert record.state is CalibrationState.PROVISIONAL
    assert any("independent ground truth" in limitation for limitation in record.limitations)


def test_require_calibrated_refuses_provisional():
    record = provisional_from_synthetic("c1", [0.9], [0.4], "synthetic", "1.0.0")
    with pytest.raises(CalibrationError, match="requires CALIBRATED"):
        require_calibrated(record, operation="real-data acceptance")


def test_thresholds_are_asymmetric_by_default():
    """Rejection must trigger more readily than acceptance."""
    thresholds = ThresholdConfig()
    assert thresholds.operator_rejection_threshold < thresholds.target_acceptance_threshold


def test_invalid_threshold_ordering_is_refused():
    with pytest.raises(CalibrationError):
        ThresholdConfig(target_review_threshold=0.9, target_acceptance_threshold=0.8)


def test_threshold_hash_changes_with_values():
    assert ThresholdConfig().config_hash() != ThresholdConfig(target_acceptance_threshold=0.9).config_hash()


def test_score_distribution_summary():
    distribution = ScoreDistribution.from_scores("test", [0.1, 0.5, 0.9])
    payload = distribution.to_dict()
    assert payload["count"] == 3
    assert 0.0 < payload["mean"] < 1.0


def test_calibration_schema_validation():
    record = provisional_from_synthetic("c1", [0.9, 0.95], [0.4, 0.5], "synthetic", "1.0.0")
    validate(record.to_dict(), SchemaName.CALIBRATION)


# ---------------------------------------------------------------------------
# Verification engine
# ---------------------------------------------------------------------------


def _verifier(tmp_path, *, with_secondary: bool = True):
    engine = _engine(tmp_path)
    operator = engine.enroll(
        profile_id="operator", role=SpeakerRole.OPERATOR, strategy="direct_recording",
        samples=[
            _sample(tmp_path, "op1.wav", 320.0, "op1"),
            _sample(tmp_path, "op2.wav", 318.0, "op2"),
        ],
    )
    target = engine.enroll(
        profile_id="target", role=SpeakerRole.TARGET_SPEAKER, strategy="direct_recording",
        samples=[
            _sample(tmp_path, "tg1.wav", 180.0, "tg1"),
            _sample(tmp_path, "tg2.wav", 182.0, "tg2"),
        ],
    )
    calibration = uncalibrated(PROVIDER.name, PROVIDER.version, is_synthetic=True)
    return (
        VerificationEngine(
            embedding_store=engine.embedding_store,
            calibration=calibration,
            target_profile=target.profile,
            operator_profile=operator.profile,
            secondary_embedding_store=engine.embedding_store if with_secondary else None,
        ),
        engine,
    )


def _verify(verifier, tmp_path, name, freq, **kwargs):
    samples, rate = _signal(tmp_path, name, freq)
    candidate = PROVIDER.embed(samples, rate)
    defaults = dict(
        verification_id=f"v-{name}",
        segment_id=f"seg-{name}",
        candidate=candidate,
        duration_seconds=len(samples) / rate,
        overlap_status="NO_OVERLAP_DETECTED",
        secondary_candidate=candidate,
    )
    defaults.update(kwargs)
    return verifier.verify(**defaults)


def test_operator_like_audio_is_rejected_first(tmp_path):
    verifier, _ = _verifier(tmp_path)
    result = _verify(verifier, tmp_path, "cand.wav", 320.0)
    assert result.decision is VerificationDecision.REJECTED_OPERATOR
    assert result.operator_score.similarity >= verifier.thresholds.operator_rejection_threshold


def test_target_like_audio_would_be_eligible_but_is_synthetic_only(tmp_path):
    """The critical guard: a synthetic provider can never produce ELIGIBLE."""
    verifier, _ = _verifier(tmp_path)
    result = _verify(verifier, tmp_path, "cand.wav", 181.0)
    assert result.decision is VerificationDecision.SYNTHETIC_ONLY
    assert not result.is_real_identity_claim


def test_dissimilar_audio_is_rejected(tmp_path):
    verifier, _ = _verifier(tmp_path)
    result = _verify(verifier, tmp_path, "cand.wav", 700.0)
    assert result.decision in (
        VerificationDecision.REJECTED_LOW_SIMILARITY,
        VerificationDecision.REJECTED_OPERATOR,
    )


def test_overlap_is_rejected_regardless_of_similarity(tmp_path):
    verifier, _ = _verifier(tmp_path)
    result = _verify(verifier, tmp_path, "cand.wav", 181.0, overlap_status="OVERLAP_DETECTED")
    assert result.decision is VerificationDecision.REJECTED_OVERLAP


def test_unknown_overlap_goes_to_review(tmp_path):
    verifier, _ = _verifier(tmp_path)
    result = _verify(verifier, tmp_path, "cand.wav", 181.0, overlap_status="UNKNOWN")
    assert result.decision is VerificationDecision.MANUAL_REVIEW


def test_missing_secondary_never_yields_eligible(tmp_path):
    verifier, _ = _verifier(tmp_path, with_secondary=False)
    result = _verify(verifier, tmp_path, "cand.wav", 181.0, secondary_candidate=None)
    assert result.decision is VerificationDecision.MANUAL_REVIEW


def test_short_audio_is_insufficient(tmp_path):
    verifier, _ = _verifier(tmp_path)
    result = _verify(verifier, tmp_path, "cand.wav", 181.0, duration_seconds=0.2)
    assert result.decision is VerificationDecision.INSUFFICIENT_AUDIO


def test_poor_quality_routes_to_review(tmp_path):
    verifier, _ = _verifier(tmp_path)
    result = _verify(verifier, tmp_path, "cand.wav", 181.0, quality_acceptable=False)
    assert result.decision is VerificationDecision.MANUAL_REVIEW


def test_calibrated_score_is_null_when_uncalibrated(tmp_path):
    """No fabricated statistical confidence."""
    verifier, _ = _verifier(tmp_path)
    result = _verify(verifier, tmp_path, "cand.wav", 181.0)
    assert result.primary.calibrated_score is None
    assert result.calibration_state is CalibrationState.UNCALIBRATED


def test_verification_result_validates_against_schema(tmp_path):
    verifier, _ = _verifier(tmp_path)
    result = _verify(verifier, tmp_path, "cand.wav", 181.0)
    validate(result.to_dict(), SchemaName.VERIFICATION)


def test_verification_fingerprint_changes_with_profile(tmp_path):
    verifier, engine = _verifier(tmp_path)
    first = _verify(verifier, tmp_path, "cand.wav", 181.0)

    new_target = engine.enroll(
        profile_id="target", role=SpeakerRole.TARGET_SPEAKER, strategy="direct_recording",
        samples=[
            _sample(tmp_path, "tg3.wav", 179.0, "tg3"),
            _sample(tmp_path, "tg4.wav", 183.0, "tg4"),
        ],
    )
    verifier.target_profile = new_target.profile
    second = _verify(verifier, tmp_path, "cand.wav", 181.0)
    assert first.fingerprint() != second.fingerprint()


def test_reviewer_feedback_is_recorded_not_promoted(tmp_path):
    verifier, _ = _verifier(tmp_path)
    result = _verify(verifier, tmp_path, "cand.wav", 181.0)
    original_decision = result.decision
    result.add_feedback(ReviewerFeedback(reviewer="op", outcome="accepted", listened=True))
    assert result.decision is original_decision  # feedback never mutates the decision
    assert result.reviewer_feedback[0].agreed_with_machine in (True, False, None)


def test_invalid_feedback_outcome_is_refused():
    with pytest.raises(Exception, match="Invalid reviewer outcome"):
        ReviewerFeedback(reviewer="op", outcome="looks_great", listened=True)


def test_assert_real_identity_claim_refuses_synthetic(tmp_path):
    verifier, _ = _verifier(tmp_path)
    result = _verify(verifier, tmp_path, "cand.wav", 181.0)
    with pytest.raises(SyntheticProvenanceError):
        assert_real_identity_claim(result, operation="verified dataset build")


# ---------------------------------------------------------------------------
# Identity review and promotion
# ---------------------------------------------------------------------------


def _review_record(segment_id="seg-1", **kwargs):
    defaults = dict(
        review_id=f"rev-{segment_id}",
        segment_id=segment_id,
        verification_id=f"ver-{segment_id}",
        reviewer="operator",
        decision=IdentityDecision.CONFIRM_TARGET,
        listened=True,
    )
    defaults.update(kwargs)
    return IdentityReviewRecord(**defaults)


def test_review_queue_records_and_reads(tmp_path):
    data_root = DataRoot(root=tmp_path / "data").create()
    queue = IdentityReviewQueue(data_root)
    queue.record(_review_record())
    assert queue.latest_for("seg-1")["decision"] == "confirm_target"
    assert queue.approved_segment_ids() == ["seg-1"]


def test_review_without_listening_is_not_approved(tmp_path):
    data_root = DataRoot(root=tmp_path / "data").create()
    queue = IdentityReviewQueue(data_root)
    queue.record(_review_record(listened=False))
    assert queue.approved_segment_ids() == []


def test_later_review_supersedes_earlier(tmp_path):
    data_root = DataRoot(root=tmp_path / "data").create()
    queue = IdentityReviewQueue(data_root)
    queue.record(_review_record())
    queue.record(_review_record(review_id="rev-seg-1b", decision=IdentityDecision.AMBIGUOUS))
    assert queue.latest_for("seg-1")["decision"] == "ambiguous"
    assert queue.approved_segment_ids() == []


def test_non_identity_review_type_is_refused(tmp_path):
    data_root = DataRoot(root=tmp_path / "data").create()
    queue = IdentityReviewQueue(data_root)
    record = _review_record()
    record.review_type = "technical"
    with pytest.raises(ReviewError, match="identity"):
        queue.record(record)


def test_identity_review_schema_validation():
    validate(_review_record().to_dict(), SchemaName.IDENTITY_REVIEW)


def test_promotion_requires_review(tmp_path):
    verifier, _ = _verifier(tmp_path)
    result = _verify(verifier, tmp_path, "cand.wav", 181.0)
    promoted, reason = promote_to_dataset(result, None)
    assert not promoted
    assert "requires a human" in reason


def test_promotion_requires_listening(tmp_path):
    verifier, _ = _verifier(tmp_path)
    result = _verify(verifier, tmp_path, "cand.wav", 181.0)
    review = _review_record(listened=False).to_dict()
    promoted, reason = promote_to_dataset(result, review)
    assert not promoted
    assert "listen" in reason


def test_promotion_refuses_synthetic_provenance(tmp_path):
    """Even a confirmed, listened review cannot promote a synthetic result."""
    verifier, _ = _verifier(tmp_path)
    result = _verify(verifier, tmp_path, "cand.wav", 181.0)
    review = _review_record().to_dict()
    promoted, reason = promote_to_dataset(result, review)
    assert not promoted
    assert "synthetic" in reason


def test_disagreement_tracking(tmp_path):
    data_root = DataRoot(root=tmp_path / "data").create()
    queue = IdentityReviewQueue(data_root)
    queue.record(_review_record(machine_recommendation="eligible"))
    queue.record(
        _review_record(
            segment_id="seg-2",
            review_id="rev-seg-2",
            decision=IdentityDecision.CONFIRM_OPERATOR,
            machine_recommendation="eligible",
        )
    )
    stats = queue.disagreement_rate()
    assert stats["sample_size"] == 2
    assert stats["overturned_acceptances"] == 1


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def test_audit_chain_is_intact_and_ordered(tmp_path):
    data_root = DataRoot(root=tmp_path / "data").create()
    log = AuditLog(data_root)
    for index in range(5):
        log.append(AuditEventType.VERIFICATION_RUN, actor="test", subject_id=f"seg-{index}")
    intact, problems = log.verify_chain()
    assert intact, problems
    assert [e["sequence"] for e in log.read_all()] == [1, 2, 3, 4, 5]


def test_audit_detects_tampering(tmp_path):
    data_root = DataRoot(root=tmp_path / "data").create()
    log = AuditLog(data_root)
    log.append(AuditEventType.VERIFICATION_RUN, actor="test", subject_id="seg-1")
    log.append(AuditEventType.VERIFICATION_RUN, actor="test", subject_id="seg-2")

    content = log.path.read_text(encoding="utf-8").replace("seg-1", "seg-X")
    log.path.write_text(content, encoding="utf-8")
    intact, problems = log.verify_chain()
    assert not intact
    assert problems


def test_audit_detects_deletion(tmp_path):
    data_root = DataRoot(root=tmp_path / "data").create()
    log = AuditLog(data_root)
    for index in range(3):
        log.append(AuditEventType.VERIFICATION_RUN, actor="test", subject_id=f"seg-{index}")
    lines = log.path.read_text(encoding="utf-8").splitlines()
    log.path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
    intact, _ = log.verify_chain()
    assert not intact


def test_audit_never_logs_vectors_or_absolute_paths(tmp_path):
    data_root = DataRoot(root=tmp_path / "data").create()
    log = AuditLog(data_root)
    log.append(
        AuditEventType.EMBEDDING_CREATED,
        actor="test",
        subject_id="emb-1",
        detail={"values": [0.1, 0.2], "path": "/home/private/recording.wav", "nested": {"vector": [1, 2]}},
    )
    entry = log.read_all()[0]
    assert entry["detail"]["values"] == "<redacted: never logged>"
    assert "/home/private" not in str(entry)
    assert entry["detail"]["nested"]["vector"] == "<redacted: never logged>"


def test_deletion_is_auditable(tmp_path):
    data_root = DataRoot(root=tmp_path / "data").create()
    store = EmbeddingStore(data_root)
    log = AuditLog(data_root)
    samples = [100] * 16_000
    store.save("emb-1", PROVIDER.embed(samples, 16_000))
    store.delete("emb-1")
    log.append(AuditEventType.EMBEDDING_DELETED, actor="operator", subject_id="emb-1")
    assert log.filter(AuditEventType.EMBEDDING_DELETED, "emb-1")
    assert store.list_ids() == []
