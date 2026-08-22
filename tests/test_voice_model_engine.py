"""Real Voice Model Engine milestone -- tests for the new provider
architecture, training job lifecycle, training-readiness assessment,
model lifecycle state machine, and checksum-addressed artifact storage.

Every fixture here is synthetic/arithmetic, exactly like the rest of the
test suite -- no real recording is read, written, or referenced. These
tests assert this environment's REAL, current capability state (no ML
runtime installed) rather than mocking a fake AVAILABLE state, per the
milestone's own "never fabricate a capability" rule.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from aarya_voice_lab.core.config import AaryaVoiceLabConfig
from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.identity.calibration import CalibrationState
from aarya_voice_lab.identity.embeddings import (
    EmbeddingProviderError,
    LocalNeuralEmbeddingProvider,
    ProviderKind,
    SyntheticEmbeddingProvider,
    available_providers,
    get_provider,
)
from aarya_voice_lab.pipeline.generation import (
    GenerationBackendState,
    GenerationBlockedError,
    LocalNeuralVoiceGenerator,
    SyntheticVoiceGenerator,
)
from aarya_voice_lab.pipeline.model_artifact import (
    ArtifactError,
    ArtifactIntegrityError,
    ArtifactStore,
    ModelArtifactFormat,
    ModelArtifactType,
)
from aarya_voice_lab.pipeline.model_lifecycle import (
    VALID_TRANSITIONS,
    InvalidModelTransitionError,
    ModelLifecycleState,
    can_transition,
    transition,
)
from aarya_voice_lab.pipeline.training import (
    LocalTrainingProvider,
    TrainingFailureReason,
    TrainingJobLog,
    TrainingJobStatus,
    TrainingProviderState,
    TrainingQueue,
    build_training_config,
    is_terminal_training_status,
)
from aarya_voice_lab.pipeline.training_readiness import (
    DEFAULT_THRESHOLDS,
    ReadinessFactor,
    TrainingReadinessInput,
    assess_training_readiness,
    thresholds_from_config,
)

# ==========================================================================
# Embedding provider -- real capability detection, never a fabricated vector
# ==========================================================================


def test_local_neural_embedding_provider_is_registered_alongside_synthetic():
    assert set(available_providers()) == {SyntheticEmbeddingProvider.name, LocalNeuralEmbeddingProvider.name}


def test_local_neural_embedding_provider_is_neural_not_synthetic():
    provider = get_provider(LocalNeuralEmbeddingProvider.name)
    assert provider.kind is ProviderKind.NEURAL
    assert not provider.is_synthetic


def test_local_neural_embedding_provider_reports_not_configured_honestly():
    """This is an empirical assertion about THIS interpreter (no
    nemo_toolkit installed), not a mocked stand-in."""
    provider = get_provider(LocalNeuralEmbeddingProvider.name)
    state = provider.capability_state()
    assert state["state"] == "NOT_CONFIGURED"
    assert "nemo_toolkit" in state["missing_requirements"]


def test_local_neural_embedding_provider_refuses_to_embed_when_not_configured():
    provider = get_provider(LocalNeuralEmbeddingProvider.name)
    with pytest.raises(EmbeddingProviderError, match="not configured"):
        provider.embed([1, 2, 3, 4], 16000)


def test_local_neural_embedding_provider_declares_real_preprocessing_requirements():
    provider = get_provider(LocalNeuralEmbeddingProvider.name)
    requirements = provider.preprocessing_requirements()
    assert requirements["sample_rate"] == 16000
    errors = provider.validate_samples([1, 2, 3], sample_rate=8000)
    assert any("sample_rate" in e for e in errors)


def test_synthetic_provider_preprocessing_requirements_base_default():
    """The base EmbeddingProvider.preprocessing_requirements() default
    (empty dict) still works for the pre-existing synthetic provider,
    which never overrode it."""
    provider = get_provider(SyntheticEmbeddingProvider.name)
    assert provider.preprocessing_requirements() == {}
    assert provider.validate_samples([], 16000) == ["signal is empty"]


def test_is_compatible_with_checks_name_and_version():
    a = get_provider(SyntheticEmbeddingProvider.name)
    b = get_provider(SyntheticEmbeddingProvider.name)
    assert a.is_compatible_with(b)
    c = get_provider(LocalNeuralEmbeddingProvider.name)
    assert not a.is_compatible_with(c)


# ==========================================================================
# Generation provider -- real capability detection, never a fabricated audio
# ==========================================================================


def test_local_neural_voice_generator_reports_not_configured_honestly():
    generator = LocalNeuralVoiceGenerator()
    capabilities = generator.get_capabilities()
    assert capabilities.backend_state == GenerationBackendState.NOT_CONFIGURED


def test_local_neural_voice_generator_never_produces_a_fake_preview():
    generator = LocalNeuralVoiceGenerator()
    with pytest.raises(GenerationBlockedError):
        generator.generate_preview({"text": "hello", "sample_rate": 16000})


def test_local_neural_voice_generator_is_a_distinct_backend_from_synthetic():
    assert LocalNeuralVoiceGenerator.name != SyntheticVoiceGenerator.name
    assert not hasattr(LocalNeuralVoiceGenerator, "kind")  # never stamped synthetic


# ==========================================================================
# Training job lifecycle
# ==========================================================================


def test_local_training_provider_capabilities_are_honest():
    provider = LocalTrainingProvider()
    capabilities = provider.capabilities()
    assert capabilities.state == TrainingProviderState.NOT_CONFIGURED
    assert set(capabilities.missing_requirements) >= {"nemo_toolkit", "torch"}


def test_training_job_full_lifecycle_ends_failed_model_unavailable(tmp_path):
    provider = LocalTrainingProvider()
    log = TrainingJobLog(tmp_path / "jobs.jsonl")
    queue = TrainingQueue(provider=provider, job_log=log)
    config = build_training_config(
        model_name="default-voice", model_version="0.1.0", dataset_id="ds-1", provider_name=provider.name
    )
    job = queue.enqueue(config)
    assert job.status == TrainingJobStatus.QUEUED

    result = queue.process_one(job.job_id)

    assert result.status == TrainingJobStatus.FAILED
    assert result.failure_reason == TrainingFailureReason.MODEL_UNAVAILABLE
    assert is_terminal_training_status(result.status)
    assert result.progress is None, "progress must stay None (UNKNOWN), never a fabricated 0%/percentage"
    assert result.duration_seconds is not None and result.duration_seconds >= 0
    assert result.errors


def test_training_job_never_reaches_completed_without_a_real_provider(tmp_path):
    """No matter how many times the queue is processed, a job cannot
    silently transition to COMPLETED when no real training runtime
    exists -- that would be exactly the fabricated-success this
    milestone forbids."""
    provider = LocalTrainingProvider()
    log = TrainingJobLog(tmp_path / "jobs.jsonl")
    queue = TrainingQueue(provider=provider, job_log=log)
    config = build_training_config(
        model_name="default-voice", model_version="0.1.0", dataset_id="ds-1", provider_name=provider.name
    )
    job = queue.enqueue(config)
    queue.process_one(job.job_id)
    # Re-processing a terminal job must be a no-op, not a retry that
    # somehow succeeds.
    result_again = queue.process_one(job.job_id)
    assert result_again.status == TrainingJobStatus.FAILED


def test_training_job_log_persists_and_is_readable(tmp_path):
    provider = LocalTrainingProvider()
    log = TrainingJobLog(tmp_path / "jobs.jsonl")
    queue = TrainingQueue(provider=provider, job_log=log)
    config = build_training_config(
        model_name="default-voice", model_version="0.1.0", dataset_id="ds-1", provider_name=provider.name
    )
    job = queue.enqueue(config)
    queue.process_one(job.job_id)

    stored = log.list()
    assert len(stored) == 1
    assert stored[0]["job_id"] == job.job_id
    assert stored[0]["status"] == "FAILED"


def test_training_queue_cancel_before_processing(tmp_path):
    provider = LocalTrainingProvider()
    log = TrainingJobLog(tmp_path / "jobs.jsonl")
    queue = TrainingQueue(provider=provider, job_log=log)
    config = build_training_config(
        model_name="default-voice", model_version="0.1.0", dataset_id="ds-1", provider_name=provider.name
    )
    job = queue.enqueue(config)
    cancelled = queue.cancel(job.job_id)
    assert cancelled.status == TrainingJobStatus.CANCELLED
    assert cancelled.failure_reason == TrainingFailureReason.CANCELLED
    assert len(log.list()) == 1


def test_training_config_hash_is_deterministic_and_sensitive_to_inputs():
    a = build_training_config(model_name="m", model_version="1", dataset_id="d", provider_name="p")
    b = build_training_config(model_name="m", model_version="1", dataset_id="d", provider_name="p")
    assert a.config_hash == b.config_hash  # job_id differs, hash does not depend on it
    c = build_training_config(model_name="m", model_version="2", dataset_id="d", provider_name="p")
    assert a.config_hash != c.config_hash


def test_training_config_language_defaults_to_undetermined():
    config = build_training_config(model_name="m", model_version="1", dataset_id="d", provider_name="p")
    assert config.language == "und"


def test_training_queue_concurrent_job_creation_is_race_free(tmp_path):
    """Exercises the real persistence mechanism (TrainingJobLog's file
    lock, from the hardening milestone), not a mocked stand-in. N threads
    race to enqueue+process a job at the same time; every job must get a
    unique id and the log must end up with exactly N records."""
    provider = LocalTrainingProvider()
    log = TrainingJobLog(tmp_path / "jobs.jsonl")
    queue = TrainingQueue(provider=provider, job_log=log)
    writer_count = 20
    barrier = threading.Barrier(writer_count)

    def run_one(n):
        config = build_training_config(
            model_name=f"model-{n}", model_version="1", dataset_id="d", provider_name=provider.name
        )
        job = queue.enqueue(config)
        barrier.wait()
        return queue.process_one(job.job_id).job_id

    with ThreadPoolExecutor(max_workers=writer_count) as pool:
        job_ids = list(pool.map(run_one, range(writer_count)))

    assert len(set(job_ids)) == writer_count, "every concurrently-enqueued job must get a unique id"
    assert len(log.list()) == writer_count, "no job record may be lost under concurrent processing"


# ==========================================================================
# Training readiness assessment
# ==========================================================================


def _passing_input(**overrides) -> TrainingReadinessInput:
    defaults = dict(
        sample_count=50,
        total_duration_seconds=600.0,
        sample_rate=16000,
        channels=1,
        mean_clipping_ratio=0.0,
        mean_silence_ratio=0.1,
        mean_snr_db=25.0,
        failing_quality_count=0,
        unprocessed_count=0,
        calibration_state=CalibrationState.PROVISIONAL,
        duplicate_sample_count=0,
    )
    defaults.update(overrides)
    return TrainingReadinessInput(**defaults)


def test_training_readiness_passes_when_every_factor_clears_its_threshold():
    report = assess_training_readiness(_passing_input())
    assert report.ready is True
    assert report.failing_factors == ()


def test_training_readiness_fails_on_insufficient_samples():
    report = assess_training_readiness(_passing_input(sample_count=2, total_duration_seconds=10))
    assert report.ready is False
    failing_names = {f.factor for f in report.failing_factors}
    assert ReadinessFactor.SAMPLE_COUNT in failing_names
    assert ReadinessFactor.TOTAL_DURATION in failing_names


def test_training_readiness_fails_on_uncalibrated_speaker_identity():
    report = assess_training_readiness(_passing_input(calibration_state=CalibrationState.UNCALIBRATED))
    assert report.ready is False
    assert any(f.factor == ReadinessFactor.CALIBRATION_STATE for f in report.failing_factors)


def test_training_readiness_never_treats_unmeasured_snr_as_passing():
    """A None SNR must count as a failure, never be silently assumed clean."""
    report = assess_training_readiness(_passing_input(mean_snr_db=None))
    assert report.ready is False
    assert any(f.factor == ReadinessFactor.SIGNAL_TO_NOISE for f in report.failing_factors)


def test_training_readiness_speaker_consistency_is_informational_only():
    """No real embedding provider exists to measure speaker consistency
    (see LocalNeuralEmbeddingProvider) -- it must never block readiness
    on its own, and must never claim to have measured something it
    can't."""
    report = assess_training_readiness(_passing_input())
    consistency = next(f for f in report.factors if f.factor == ReadinessFactor.SPEAKER_CONSISTENCY)
    assert consistency.passed is True
    assert consistency.measured == "not independently assessed"
    assert "real embedding provider" in consistency.detail


def test_training_readiness_thresholds_come_from_config_not_hardcoded(tmp_path):
    config = AaryaVoiceLabConfig(
        project_name="x",
        schema_version="0.1.0",
        pipeline_version="0.1.0",
        raw={"training_readiness": {"minimum_sample_count": 5}},
    )
    thresholds = thresholds_from_config(config)
    assert thresholds["minimum_sample_count"] == 5
    # Untouched keys still fall back to the documented defaults.
    assert thresholds["required_sample_rate"] == DEFAULT_THRESHOLDS["required_sample_rate"]


def test_training_readiness_provider_requirements_only_tighten_never_loosen():
    # A provider asking for MORE samples than the config default raises the floor.
    report = assess_training_readiness(
        _passing_input(sample_count=25),
        provider_requirements={"minimum_sample_count": 30},
    )
    assert report.thresholds_used["minimum_sample_count"] == 30
    assert report.ready is False

    # A provider asking for FEWER samples than the config default cannot lower it.
    report2 = assess_training_readiness(
        _passing_input(sample_count=25),
        provider_requirements={"minimum_sample_count": 1},
    )
    assert report2.thresholds_used["minimum_sample_count"] == DEFAULT_THRESHOLDS["minimum_sample_count"]


def test_training_readiness_max_thresholds_tighten_downward():
    report = assess_training_readiness(
        _passing_input(mean_clipping_ratio=0.005),
        provider_requirements={"max_clipping_ratio": 0.001},
    )
    assert report.thresholds_used["max_clipping_ratio"] == 0.001
    assert any(f.factor == ReadinessFactor.CLIPPING for f in report.failing_factors)


# ==========================================================================
# Model lifecycle state machine
# ==========================================================================


@pytest.mark.parametrize(
    "current,target",
    [
        (ModelLifecycleState.DRAFT, ModelLifecycleState.TRAINING),
        (ModelLifecycleState.TRAINING, ModelLifecycleState.EVALUATING),
        (ModelLifecycleState.EVALUATING, ModelLifecycleState.VALIDATED),
        (ModelLifecycleState.VALIDATED, ModelLifecycleState.AVAILABLE),
        (ModelLifecycleState.AVAILABLE, ModelLifecycleState.ACTIVE),
        (ModelLifecycleState.ACTIVE, ModelLifecycleState.ARCHIVED),
    ],
)
def test_valid_lifecycle_transitions(current, target):
    assert can_transition(current, target)
    assert transition(current, target) == target


@pytest.mark.parametrize(
    "current,target",
    [
        (ModelLifecycleState.DRAFT, ModelLifecycleState.ACTIVE),
        (ModelLifecycleState.DRAFT, ModelLifecycleState.AVAILABLE),
        (ModelLifecycleState.TRAINING, ModelLifecycleState.VALIDATED),
        (ModelLifecycleState.ARCHIVED, ModelLifecycleState.ACTIVE),
        (ModelLifecycleState.FAILED, ModelLifecycleState.TRAINING),
        (ModelLifecycleState.ACTIVE, ModelLifecycleState.DRAFT),
    ],
)
def test_invalid_lifecycle_transitions_are_rejected(current, target):
    assert not can_transition(current, target)
    with pytest.raises(InvalidModelTransitionError):
        transition(current, target)


def test_failed_is_reachable_while_a_model_is_still_being_produced():
    """FAILED is reachable from every state where a model has not yet
    been judged fit to use (a training/evaluation/validation problem
    must always be representable) -- but not from AVAILABLE or ACTIVE,
    which by design only ever move forward or retire via ARCHIVED: a
    model already judged usable (let alone already serving traffic) is
    not described as having "failed", it is superseded/retired instead."""
    can_still_fail = {
        ModelLifecycleState.DRAFT,
        ModelLifecycleState.TRAINING,
        ModelLifecycleState.EVALUATING,
        ModelLifecycleState.VALIDATED,
    }
    for state in can_still_fail:
        assert ModelLifecycleState.FAILED in VALID_TRANSITIONS[state]
    assert ModelLifecycleState.FAILED not in VALID_TRANSITIONS[ModelLifecycleState.AVAILABLE]
    assert VALID_TRANSITIONS[ModelLifecycleState.ACTIVE] == frozenset({ModelLifecycleState.ARCHIVED})


# ==========================================================================
# Model artifact storage -- checksum-addressed, refuse-to-overwrite
# ==========================================================================


def test_artifact_store_roundtrip(tmp_path):
    data_root = DataRoot(root=tmp_path / "data").create()
    store = ArtifactStore(data_root)
    record = store.save(
        b"fake weights bytes",
        artifact_format=ModelArtifactFormat.ONNX,
        artifact_type=ModelArtifactType.GENERATION_MODEL_WEIGHTS,
        model_name="test-model",
        model_version="1",
        provider_name="local-neural-tts",
    )
    assert record.checksum_sha256 == __import__("hashlib").sha256(b"fake weights bytes").hexdigest()
    loaded = store.load_bytes(record.artifact_id)
    assert loaded == b"fake weights bytes"


def test_artifact_store_refuses_to_overwrite_same_checksum(tmp_path):
    data_root = DataRoot(root=tmp_path / "data").create()
    store = ArtifactStore(data_root)
    payload = b"identical bytes"
    store.save(
        payload,
        artifact_format=ModelArtifactFormat.JSON_METADATA,
        artifact_type=ModelArtifactType.EVALUATION_REPORT,
        model_name="m",
        model_version="1",
        provider_name="p",
    )
    with pytest.raises(ArtifactError, match="already exists"):
        store.save(
            payload,
            artifact_format=ModelArtifactFormat.JSON_METADATA,
            artifact_type=ModelArtifactType.EVALUATION_REPORT,
            model_name="m",
            model_version="1",
            provider_name="p",
        )


def test_artifact_store_never_trusts_a_filename_as_identity(tmp_path):
    """Two different payloads never collide on id even if a caller
    supplies the same model_name/version -- identity is the checksum."""
    data_root = DataRoot(root=tmp_path / "data").create()
    store = ArtifactStore(data_root)
    a = store.save(
        b"payload one",
        artifact_format=ModelArtifactFormat.JSON_METADATA,
        artifact_type=ModelArtifactType.EVALUATION_REPORT,
        model_name="same-name",
        model_version="1",
        provider_name="p",
    )
    b = store.save(
        b"payload two",
        artifact_format=ModelArtifactFormat.JSON_METADATA,
        artifact_type=ModelArtifactType.EVALUATION_REPORT,
        model_name="same-name",
        model_version="1",
        provider_name="p",
    )
    assert a.artifact_id != b.artifact_id


def test_artifact_store_detects_tampering(tmp_path):
    """Security-relevant: bytes modified on disk after storage must be
    detected, never silently trusted."""
    data_root = DataRoot(root=tmp_path / "data").create()
    store = ArtifactStore(data_root)
    record = store.save(
        b"original bytes",
        artifact_format=ModelArtifactFormat.JSON_METADATA,
        artifact_type=ModelArtifactType.EVALUATION_REPORT,
        model_name="m",
        model_version="1",
        provider_name="p",
    )
    tampered_path = store._bin_path(record.artifact_id)
    tampered_path.write_bytes(b"tampered bytes!!")
    with pytest.raises(ArtifactIntegrityError):
        store.load_bytes(record.artifact_id)


def test_artifact_store_rejects_writes_into_source(tmp_path):
    """Defence in depth, mirroring EmbeddingStore's own test: a path bug
    must never let an artifact land in data/source/."""
    from aarya_voice_lab.core.data_root import SourceImmutabilityError

    data_root = DataRoot(root=tmp_path / "data")
    store = ArtifactStore(data_root)
    store.directory = data_root.source  # simulate a path-construction bug
    with pytest.raises(SourceImmutabilityError):
        store.save(
            b"x",
            artifact_format=ModelArtifactFormat.JSON_METADATA,
            artifact_type=ModelArtifactType.EVALUATION_REPORT,
            model_name="m",
            model_version="1",
            provider_name="p",
        )


def test_artifact_store_concurrent_writers_never_collide(tmp_path):
    """Exercises the real filesystem, not a mock: N threads save distinct
    payloads at the same time; every artifact must be independently
    readable afterward with no lost or corrupted record."""
    data_root = DataRoot(root=tmp_path / "data").create()
    store = ArtifactStore(data_root)
    writer_count = 15
    barrier = threading.Barrier(writer_count)

    def save_one(n):
        barrier.wait()
        record = store.save(
            f"payload-{n}".encode(),
            artifact_format=ModelArtifactFormat.JSON_METADATA,
            artifact_type=ModelArtifactType.EVALUATION_REPORT,
            model_name=f"m{n}",
            model_version="1",
            provider_name="p",
        )
        return record.artifact_id

    with ThreadPoolExecutor(max_workers=writer_count) as pool:
        artifact_ids = list(pool.map(save_one, range(writer_count)))

    assert len(set(artifact_ids)) == writer_count
    assert len(store.list_ids()) == writer_count
    for artifact_id in artifact_ids:
        store.load_bytes(artifact_id)  # raises on any integrity mismatch


def test_artifact_store_list_and_delete(tmp_path):
    data_root = DataRoot(root=tmp_path / "data").create()
    store = ArtifactStore(data_root)
    record = store.save(
        b"x",
        artifact_format=ModelArtifactFormat.JSON_METADATA,
        artifact_type=ModelArtifactType.EVALUATION_REPORT,
        model_name="m",
        model_version="1",
        provider_name="p",
    )
    assert record.artifact_id in store.list_ids()
    assert store.delete(record.artifact_id) is True
    assert record.artifact_id not in store.list_ids()
    assert store.delete(record.artifact_id) is False
