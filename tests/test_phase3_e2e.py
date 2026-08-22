"""Phase 3 synthetic end-to-end, contracts, resumability, and boundary tests."""

from __future__ import annotations

import json

import pytest

from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.identity import contracts
from aarya_voice_lab.identity.calibration import CalibrationState
from aarya_voice_lab.identity.embeddings import SyntheticEmbeddingProvider
from aarya_voice_lab.identity.preview import (
    PreviewArtifact,
    PreviewFeedback,
    PreviewFeedbackOutcome,
    PreviewKind,
    preview_loop_state,
)
from aarya_voice_lab.identity.runtime import (
    SYNTHETIC_PROVIDER_CAPABILITY,
    AccelerationRequirement,
    ComputeBackend,
    describe_portability,
)
from aarya_voice_lab.identity.synthetic_e2e import run_synthetic_e2e
from aarya_voice_lab.identity.verification import VerificationDecision
from aarya_voice_lab.pipeline.resume import build_fingerprint, evaluate_reuse
from aarya_voice_lab.pipeline.stages import (
    PHASE_2_STAGES,
    SPEAKER_IDENTITY_BOUNDARY,
    SPEAKER_IDENTITY_STAGES,
    PipelineStage,
    is_implemented,
    stage_index,
)

# ---------------------------------------------------------------------------
# Full synthetic end-to-end
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def e2e(tmp_path_factory):
    return run_synthetic_e2e(tmp_path_factory.mktemp("phase3-e2e"))


def test_e2e_covers_every_decision_class(e2e):
    decisions = {v.decision for v in e2e.verifications}
    assert VerificationDecision.SYNTHETIC_ONLY in decisions      # positive match
    assert VerificationDecision.REJECTED_OPERATOR in decisions   # negative match
    assert VerificationDecision.REJECTED_OVERLAP in decisions
    assert VerificationDecision.MANUAL_REVIEW in decisions       # unknown overlap / quality
    assert VerificationDecision.REJECTED_LOW_SIMILARITY in decisions  # channel mismatch


def test_e2e_positive_match_scores_high(e2e):
    positive = next(v for v in e2e.verifications if v.segment_id == "seg-positive")
    assert positive.primary.similarity > 0.9
    assert positive.decision is VerificationDecision.SYNTHETIC_ONLY


def test_e2e_negative_match_rejected_by_operator_profile(e2e):
    negative = next(v for v in e2e.verifications if v.segment_id == "seg-negative")
    assert negative.decision is VerificationDecision.REJECTED_OPERATOR


def test_e2e_borderline_channel_mismatch_not_accepted(e2e):
    mismatch = next(v for v in e2e.verifications if v.segment_id == "seg-channel-mismatch")
    assert mismatch.decision in (
        VerificationDecision.REJECTED_LOW_SIMILARITY,
        VerificationDecision.MANUAL_REVIEW,
    )


def test_e2e_nothing_is_promoted(e2e):
    """The single most important E2E property: synthetic provenance blocks
    every promotion, even after confirmed, listened reviews."""
    assert all(not p["promoted"] for p in e2e.promotions)
    assert all("synthetic" in p["reason"] or "human" in p["reason"] for p in e2e.promotions)


def test_e2e_no_real_identity_claims(e2e):
    assert all(v.provider_is_synthetic for v in e2e.verifications)
    assert not any(v.is_real_identity_claim for v in e2e.verifications)


def test_e2e_calibration_is_provisional(e2e):
    assert e2e.calibration.state is CalibrationState.PROVISIONAL
    assert not e2e.calibration.is_statistically_validated


def test_e2e_audit_chain_intact(e2e):
    assert e2e.audit_summary["chain_intact"], e2e.audit_summary["chain_problems"]
    assert e2e.audit_summary["entry_count"] > 0


def test_e2e_provenance_chain_is_complete(e2e):
    for verification in e2e.verifications:
        chain = contracts.provenance_chain(verification, e2e.profiles["target"])
        payload = chain["chain"]
        assert payload["source"]["source_file_id"]
        assert payload["verification"]["fingerprint"]
        assert payload["embedding"]["provider_is_synthetic"] is True
        json.dumps(chain)  # must be JSON-serialisable end to end


def test_e2e_is_deterministic_in_decisions(tmp_path):
    first = run_synthetic_e2e(tmp_path / "run1")
    second = run_synthetic_e2e(tmp_path / "run2")
    assert [v.decision for v in first.verifications] == [v.decision for v in second.verifications]
    assert [round(v.primary.similarity, 9) if v.primary else None for v in first.verifications] == [
        round(v.primary.similarity, 9) if v.primary else None for v in second.verifications
    ]


# ---------------------------------------------------------------------------
# Failure handling: invalid inputs and corrupted artifacts
# ---------------------------------------------------------------------------


def test_invalid_profile_is_refused(tmp_path):
    from aarya_voice_lab.identity.calibration import uncalibrated
    from aarya_voice_lab.identity.embeddings import EmbeddingStore
    from aarya_voice_lab.identity.profile import (
        EnrollmentState,
        ProfileError,
        ProfileProvenance,
        SpeakerProfile,
        SpeakerRole,
    )
    from aarya_voice_lab.identity.verification import VerificationEngine

    data_root = DataRoot(root=tmp_path / "data").create()
    provider = SyntheticEmbeddingProvider()
    draft = SpeakerProfile(
        profile_id="draft", role=SpeakerRole.TARGET_SPEAKER, version=1,
        enrollment_state=EnrollmentState.DRAFT,
        provenance=ProfileProvenance(strategy_name="x", strategy_version="1"),
    )
    engine = VerificationEngine(
        embedding_store=EmbeddingStore(data_root),
        calibration=uncalibrated(provider.name, provider.version, is_synthetic=True),
        target_profile=draft,
    )
    candidate = provider.embed([100] * 32_000, 16_000)
    with pytest.raises(ProfileError):
        engine.verify(
            verification_id="v1", segment_id="s1", candidate=candidate, duration_seconds=2.0
        )


def test_corrupted_embedding_is_refused_at_verification(tmp_path):
    from aarya_voice_lab.identity.calibration import uncalibrated
    from aarya_voice_lab.identity.embeddings import EmbeddingProviderError, EmbeddingStore
    from aarya_voice_lab.identity.enrollment import EnrollmentEngine, EnrollmentSample
    from aarya_voice_lab.identity.profile import SpeakerRole
    from aarya_voice_lab.identity.verification import VerificationEngine

    data_root = DataRoot(root=tmp_path / "data").create()
    provider = SyntheticEmbeddingProvider()
    engine = EnrollmentEngine(provider, data_root)
    enrolled = engine.enroll(
        profile_id="t", role=SpeakerRole.SYNTHETIC_SPEAKER, strategy="synthetic",
        samples=[EnrollmentSample(sample_id="s", samples=[500] * 32_000, sample_rate=16_000)],
    )
    # Corrupt the stored vector.
    store = EmbeddingStore(data_root)
    (store.directory / f"{enrolled.embedding_id}.vec").write_bytes(b"\x01" * provider.dimension * 8)

    verifier = VerificationEngine(
        embedding_store=store,
        calibration=uncalibrated(provider.name, provider.version, is_synthetic=True),
        target_profile=enrolled.profile,
    )
    with pytest.raises(EmbeddingProviderError, match="integrity"):
        verifier.verify(
            verification_id="v1", segment_id="s1",
            candidate=provider.embed([100] * 32_000, 16_000), duration_seconds=2.0,
        )


def test_provider_version_mismatch_is_refused(tmp_path):
    from aarya_voice_lab.identity.embeddings import (
        EmbeddingProviderError,
        EmbeddingVector,
        ProviderKind,
        cosine_similarity,
    )

    provider = SyntheticEmbeddingProvider()
    a = provider.embed([100] * 16_000, 16_000)
    b = EmbeddingVector(
        values=a.values, provider_name=a.provider_name, provider_version="99.0.0",
        provider_kind=ProviderKind.SYNTHETIC, sample_rate=16_000, source_duration_seconds=1.0,
    )
    with pytest.raises(EmbeddingProviderError, match="different providers"):
        cosine_similarity(a, b)


# ---------------------------------------------------------------------------
# Resumability with identity fingerprints
# ---------------------------------------------------------------------------


def test_profile_change_forces_recompute(tmp_path):
    """Re-enrollment must invalidate dependent verification work."""
    stage = PipelineStage.SPEAKER_VERIFICATION
    base = build_fingerprint(
        stage, stage_version="1.0.0",
        config={"profile": "target@v1", "profile_fingerprint": "aaa"},
        input_hashes=["a" * 64],
    )
    changed = build_fingerprint(
        stage, stage_version="1.0.0",
        config={"profile": "target@v2", "profile_fingerprint": "bbb"},
        input_hashes=["a" * 64],
    )
    assert base.digest() != changed.digest()


def test_threshold_change_forces_recompute(tmp_path):
    from aarya_voice_lab.identity.calibration import ThresholdConfig

    stage = PipelineStage.SPEAKER_VERIFICATION
    a = build_fingerprint(stage, stage_version="1.0.0",
                          config={"thresholds": ThresholdConfig().config_hash()}, input_hashes=["a" * 64])
    b = build_fingerprint(stage, stage_version="1.0.0",
                          config={"thresholds": ThresholdConfig(target_acceptance_threshold=0.9).config_hash()},
                          input_hashes=["a" * 64])
    assert a.digest() != b.digest()


def test_interrupted_identity_stage_is_not_reused(tmp_path):
    from aarya_voice_lab.pipeline.contracts import StageResult, StageStatus

    run_dir = tmp_path / "run"
    result = StageResult(stage=PipelineStage.SPEAKER_VERIFICATION, environment_id="base")
    result.status = StageStatus.RUNNING
    result.write(run_dir)

    fingerprint = build_fingerprint(
        PipelineStage.SPEAKER_VERIFICATION, stage_version="1.0.0", config={}, input_hashes=["a" * 64]
    )
    evaluation = evaluate_reuse(run_dir, PipelineStage.SPEAKER_VERIFICATION, fingerprint)
    assert not evaluation.can_reuse


# ---------------------------------------------------------------------------
# Desktop contracts
# ---------------------------------------------------------------------------


def test_contracts_are_json_serialisable(tmp_path):
    data_root = DataRoot(root=tmp_path / "data").create()
    snapshot = contracts.desktop_snapshot(data_root)
    json.dumps(snapshot)
    assert snapshot["contract"] == "desktop_snapshot"
    assert snapshot["contract_version"]


def test_contracts_report_no_real_provider_when_none_is_installed(tmp_path, monkeypatch):
    """Real ML Runtime milestone follow-up (D11 audit): reproducibly
    simulate the not-installed case rather than assuming it -- whether a
    real provider is actually installed now legitimately varies by
    machine (see .envs/env-nemo)."""
    from aarya_voice_lab.identity import embeddings as embeddings_module

    monkeypatch.setattr(embeddings_module, "_ENV_NEMO_PYTHON", tmp_path / "does-not-exist")
    data_root = DataRoot(root=tmp_path / "data").create()
    status = contracts.enrollment_status(data_root)
    assert status["real_provider_installed"] is False
    assert "No real embedding provider is installed" in status["note"]


def test_contracts_report_real_provider_state_honestly(tmp_path):
    """Whatever `any_real_provider_available()` says about THIS
    interpreter, `enrollment_status()` must report exactly that -- never
    a value hardcoded independent of the real, current capability
    state (the defect this test replaces: `real_provider_installed` was
    previously hardcoded False unconditionally)."""
    from aarya_voice_lab.identity.embeddings import any_real_provider_available

    data_root = DataRoot(root=tmp_path / "data").create()
    status = contracts.enrollment_status(data_root)
    assert status["real_provider_installed"] == any_real_provider_available()


def test_embedding_inventory_never_exposes_vectors(tmp_path):
    data_root = DataRoot(root=tmp_path / "data").create()
    payload = contracts.embedding_inventory(data_root)
    assert payload["export_supported"] is False
    assert "values" not in json.dumps(payload)


def test_pipeline_status_reports_boundary(tmp_path):
    data_root = DataRoot(root=tmp_path / "data").create()
    payload = contracts.pipeline_status(data_root)
    assert payload["identity_boundary_stage"] == "speaker_enrollment"
    boundary = payload["identity_boundary_index"]
    for stage in payload["stages"]:
        if stage["phase"] == "phase-2":
            assert stage["index"] < boundary


def test_verification_view_counts_synthetic(tmp_path):
    result = run_synthetic_e2e(tmp_path / "e2e")
    view = contracts.verification_results_view(result.verifications)
    assert view["all_synthetic"] is True
    assert view["real_identity_claims"] == 0


def test_review_queue_view_includes_disagreement(tmp_path):
    result = run_synthetic_e2e(tmp_path / "e2e")
    data_root = DataRoot(root=tmp_path / "e2e" / "data")
    view = contracts.review_queue_view(data_root, result.verifications)
    assert "disagreement" in view
    assert view["review_type"] == "identity"


# ---------------------------------------------------------------------------
# Runtime capability / portability (VL-D19/D20, hardware independence)
# ---------------------------------------------------------------------------


def test_no_vendor_names_in_core_identity_interfaces():
    """Core identity code must not hard-code accelerator vendors."""
    import inspect

    from aarya_voice_lab.identity import contracts as contracts_module
    from aarya_voice_lab.identity import embeddings, enrollment, profile, verification

    for module in (embeddings, enrollment, profile, verification, contracts_module):
        source = inspect.getsource(module).lower()
        for vendor_call in ("torch.cuda", "nvidia-smi", "cudnn"):
            assert vendor_call not in source, f"{module.__name__} hard-codes {vendor_call}"


def test_synthetic_provider_is_cpu_only_and_portable():
    capability = SYNTHETIC_PROVIDER_CAPABILITY
    assert capability.runs_on_cpu
    assert not capability.requires_accelerator
    assert capability.acceleration is AccelerationRequirement.CPU_ONLY


def test_portability_summary_is_honest():
    summary = describe_portability([SYNTHETIC_PROVIDER_CAPABILITY])
    assert summary["cpu_only_viable"] is True
    assert "not verified" in summary["note"] or "not from an executed" in summary["note"]


def test_unknown_acceleration_blocks_cpu_only_claim():
    from aarya_voice_lab.identity.runtime import RuntimeCapability

    unknown = RuntimeCapability(
        component="future-model",
        acceleration=AccelerationRequirement.UNKNOWN,
        supported_backends=(ComputeBackend.CPU,),
    )
    summary = describe_portability([SYNTHETIC_PROVIDER_CAPABILITY, unknown])
    assert summary["cpu_only_viable"] is False
    assert "future-model" in summary["undetermined_components"]


# ---------------------------------------------------------------------------
# VL-V0 preview contracts
# ---------------------------------------------------------------------------


def test_preview_loop_state_shape():
    state = preview_loop_state([], [])
    assert state["generation_implemented"] is False
    assert state["is_accepted"] is False


def test_preview_feedback_loop():
    preview = PreviewArtifact(
        preview_id="p1", kind=PreviewKind.SYNTHETIC_FIXTURE, relative_path="cache/p1.wav",
        sha256="a" * 64, duration_seconds=1.0, sample_rate=16_000,
    )
    feedback = PreviewFeedback(
        feedback_id="f1", preview_id="p1", listener="op",
        outcome=PreviewFeedbackOutcome.REGENERATE, listened=True,
    )
    state = preview_loop_state([preview], [feedback])
    assert state["regeneration_requested"] is True
    assert state["is_accepted"] is False


def test_no_preview_provider_is_implemented():
    from aarya_voice_lab.identity.preview import PreviewProvider

    with pytest.raises(TypeError):
        PreviewProvider()


# ---------------------------------------------------------------------------
# Phase boundary regression guards
# ---------------------------------------------------------------------------


def test_boundary_moved_to_enrollment_and_phase2_unchanged():
    assert SPEAKER_IDENTITY_BOUNDARY is PipelineStage.SPEAKER_ENROLLMENT
    boundary = stage_index(SPEAKER_IDENTITY_BOUNDARY)
    for stage in PHASE_2_STAGES:
        assert stage_index(stage) < boundary


def test_new_identity_stages_are_marked_identity():
    for stage in (
        PipelineStage.SPEAKER_ENROLLMENT,
        PipelineStage.OPERATOR_REJECTION,
        PipelineStage.CONFIDENCE_CLASSIFICATION,
    ):
        assert stage in SPEAKER_IDENTITY_STAGES


def test_pipeline_stages_remain_unimplemented_past_boundary():
    """Phase 3 ships identity *software*, but no pipeline stage runs it
    against real data — is_implemented stays false past the boundary until
    a real-data phase is approved."""
    boundary = stage_index(SPEAKER_IDENTITY_BOUNDARY)
    for index, stage in enumerate(PipelineStage):
        if index >= boundary:
            assert not is_implemented(stage)


def test_candidate_segment_still_has_no_speaker_field():
    from aarya_voice_lab.pipeline.segmentation import CandidateSegment

    assert not any("speaker" in f for f in CandidateSegment.__dataclass_fields__)


def test_candidate_manifest_still_rejects_identity_fields(tmp_path):
    from aarya_voice_lab.schemas.base import SchemaName, ValidationError, validate

    manifest = {
        "schema_version": "0.1.0", "dataset_version": "1", "batch_id": "batch-001",
        "created_at": "2026-01-01T00:00:00Z", "processing_version": "0.1.0",
        "phase": "phase-2", "is_synthetic": True,
        "candidates": [{
            "segment_id": "s", "source_file_id": "f", "source_sha256": "a" * 64,
            "start_time": 0.0, "end_time": 1.0, "duration": 1.0,
            "technical_eligibility": "technically_eligible", "quality_status": "PASS",
            "overlap_status": "NO_OVERLAP_DETECTED", "processing_version": "0.1.0",
            "speaker_id": "target",
        }],
    }
    with pytest.raises(ValidationError):
        validate(manifest, SchemaName.CANDIDATE_MANIFEST)
