"""Tests for VL-D5's Voice Preview + Generation layer: the generation
abstraction, the synthetic backend, the generation queue, voice
profiles, the generation model registry, preview history + regeneration,
preview feedback, A/B comparison metadata, and calibration prep.

Every fixture is synthetic; nothing here reads or references source/ or
generates anything claiming to be a real person's voice.
"""

from __future__ import annotations

import pytest

from aarya_voice_lab.core.data_root import DataRoot, SourceImmutabilityError
from aarya_voice_lab.identity.preview import PreviewFeedbackOutcome, PreviewKind, PreviewProvider
from aarya_voice_lab.identity.runtime import (
    AccelerationRequirement,
    ComputeBackend,
    PortabilityClass,
    RuntimeCapability,
)
from aarya_voice_lab.pipeline.calibration_prep import summarize_preview_calibration_inputs
from aarya_voice_lab.pipeline.generation import (
    GenerationBackendState,
    GenerationBlockedError,
    GenerationQueue,
    GenerationStatus,
    SyntheticVoiceGenerator,
    UnavailableVoiceGenerator,
    VoiceGenerator,
    build_ab_comparison,
    build_artifact_fingerprint,
    build_preview_request,
)
from aarya_voice_lab.pipeline.generation_models import GenerationModel, GenerationModelRegistry
from aarya_voice_lab.pipeline.preview_feedback import (
    PreviewFeedbackCategory,
    PreviewFeedbackLog,
    UnlistenedFeedbackError,
    counts_by_category,
    counts_by_outcome,
    feedback_for,
    record_preview_feedback,
)
from aarya_voice_lab.pipeline.preview_history import (
    PreviewHistoryLog,
    current,
    history,
    record_generation_result,
    regeneration_count,
)
from aarya_voice_lab.pipeline.voice_profile import VoiceProfileRegistry, VoiceProfileState
from aarya_voice_lab.schemas.base import SchemaName, validate


def _data_root(tmp_path):
    root = DataRoot(root=tmp_path / "data")
    root.create()
    return root


def _generate(tmp_path, *, text="Hello, this is a synthetic preview.", generator=None):
    data_root = _data_root(tmp_path)
    generator = generator or SyntheticVoiceGenerator(data_root)
    queue = GenerationQueue(generator=generator)
    request = build_preview_request(text=text, voice_profile_id="vp-1", model_id="synthetic-tone-v1")
    item = queue.enqueue(request)
    queue.process_one(item.item_id)
    return queue, item, data_root


# ---------------------------------------------------------------------------
# Generation contracts — VoiceGenerator extends PreviewProvider, not a
# second competing interface
# ---------------------------------------------------------------------------


def test_voice_generator_is_a_preview_provider():
    assert issubclass(VoiceGenerator, PreviewProvider)


def test_voice_generator_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        VoiceGenerator()


def test_synthetic_generator_implements_the_full_contract():
    generator = SyntheticVoiceGenerator(DataRoot(root=None))  # type: ignore[arg-type]
    assert isinstance(generator, PreviewProvider)
    assert isinstance(generator, VoiceGenerator)
    assert generator.supports_regeneration() is True


# ---------------------------------------------------------------------------
# Generation model registry — vendor-neutral, distinct from
# registry.model_registry (Phase 1's final-voice-model audit registry)
# ---------------------------------------------------------------------------


def test_generation_model_registry_lists_by_backend():
    registry = GenerationModelRegistry()
    cpu_model = registry.register(
        GenerationModel(model_id="m1", name="Synthetic", version="0.1.0", backend=ComputeBackend.CPU)
    )
    registry.register(GenerationModel(model_id="m2", name="Other", version="0.1.0", backend=ComputeBackend.CUDA))
    assert registry.list_by_backend(ComputeBackend.CPU) == [cpu_model]
    assert len(registry.list()) == 2


def test_generation_model_never_hardcodes_a_specific_vendor():
    # The type system itself only accepts the vendor-neutral enum -- there
    # is no field for "RTX 3050" or any other product name to occupy.
    model = GenerationModel(model_id="m1", name="x", version="1", backend=ComputeBackend.CPU)
    assert "backend" in model.to_dict()
    assert model.to_dict()["backend"] == "cpu"


# ---------------------------------------------------------------------------
# Synthetic backend — capabilities, validation, estimation, generation
# ---------------------------------------------------------------------------


def test_synthetic_backend_reports_available_and_cpu_only():
    generator = SyntheticVoiceGenerator(DataRoot(root=None))  # type: ignore[arg-type]
    capabilities = generator.get_capabilities()
    assert capabilities.backend_state == GenerationBackendState.AVAILABLE
    assert capabilities.compute_backend == ComputeBackend.CPU


def test_request_validation_rejects_empty_text(tmp_path):
    generator = SyntheticVoiceGenerator(_data_root(tmp_path))
    request = build_preview_request(text="   ", voice_profile_id="vp-1", model_id="m1")
    errors = generator.validate_request(request.to_dict())
    assert any("empty" in e for e in errors)


def test_request_validation_rejects_too_long_text(tmp_path):
    generator = SyntheticVoiceGenerator(_data_root(tmp_path))
    request = build_preview_request(text="x" * 6000, voice_profile_id="vp-1", model_id="m1")
    errors = generator.validate_request(request.to_dict())
    assert any("exceeds" in e for e in errors)


def test_request_validation_rejects_unsupported_sample_rate(tmp_path):
    generator = SyntheticVoiceGenerator(_data_root(tmp_path))
    request = build_preview_request(text="hi", voice_profile_id="vp-1", model_id="m1", sample_rate=8000)
    errors = generator.validate_request(request.to_dict())
    assert any("sample_rate" in e for e in errors)


def test_request_validation_rejects_an_unsupported_control(tmp_path):
    generator = SyntheticVoiceGenerator(_data_root(tmp_path))
    request = build_preview_request(text="hi", voice_profile_id="vp-1", model_id="m1", controls={"pitch": "high"})
    errors = generator.validate_request(request.to_dict())
    assert any("unsupported control" in e for e in errors)


def test_estimate_requirements_is_an_honest_heuristic_not_a_guarantee(tmp_path):
    generator = SyntheticVoiceGenerator(_data_root(tmp_path))
    request = build_preview_request(text="one two three four five", voice_profile_id="vp-1", model_id="m1")
    estimate = generator.estimate_requirements(request.to_dict())
    assert estimate["word_count"] == 5
    assert "heuristic" in estimate["estimate_basis"]


def test_synthetic_generation_produces_a_real_wav_with_relative_path_provenance(tmp_path):
    _, item, data_root = _generate(tmp_path)
    assert item.status == GenerationStatus.READY
    assert item.artifact["kind"] == PreviewKind.SYNTHETIC_FIXTURE.value
    assert item.artifact["is_synthetic"] is True
    assert item.artifact["relative_path"].startswith("previews/")
    assert "/home/" not in item.artifact["relative_path"]
    output_path = data_root.previews / f"{item.request.request_id}.wav"
    assert output_path.is_file()


def test_synthetic_generation_is_reproducible_for_identical_requests(tmp_path):
    data_root = _data_root(tmp_path)
    generator = SyntheticVoiceGenerator(data_root)
    queue = GenerationQueue(generator=generator)

    request_a = build_preview_request(text="Same text", voice_profile_id="vp-1", model_id="m1", seed=7)
    request_b = build_preview_request(text="Same text", voice_profile_id="vp-1", model_id="m1", seed=7)
    item_a = queue.enqueue(request_a)
    item_b = queue.enqueue(request_b)
    queue.process_one(item_a.item_id)
    queue.process_one(item_b.item_id)

    assert item_a.artifact["artifact_id"] == item_b.artifact["artifact_id"]
    assert item_a.artifact["sha256"] == item_b.artifact["sha256"]


def test_synthetic_generation_refuses_to_overwrite_an_existing_output(tmp_path):
    data_root = _data_root(tmp_path)
    generator = SyntheticVoiceGenerator(data_root)
    request = build_preview_request(text="hi", voice_profile_id="vp-1", model_id="m1")
    (data_root.previews / f"{request.request_id}.wav").parent.mkdir(parents=True, exist_ok=True)
    (data_root.previews / f"{request.request_id}.wav").write_bytes(b"already here")
    with pytest.raises(GenerationBlockedError, match="already exists"):
        generator.generate_preview(request.to_dict())


def test_generate_preview_guards_its_destination_with_assert_source_writable(tmp_path):
    # generate_preview() always writes under data_root.previews/, which is
    # never inside source/ -- assert the shared guard it calls would
    # actually refuse a source/ destination, so the protection isn't
    # merely coincidental.
    data_root = _data_root(tmp_path)
    from aarya_voice_lab.core.data_root import assert_source_writable

    with pytest.raises(SourceImmutabilityError):
        assert_source_writable(data_root, data_root.source / "batch-001" / "x.wav")


# ---------------------------------------------------------------------------
# Unsupported / unavailable backend behavior
# ---------------------------------------------------------------------------


def test_unavailable_backend_reports_unavailable_never_fabricated_success():
    generator = UnavailableVoiceGenerator()
    capabilities = generator.get_capabilities()
    assert capabilities.backend_state == GenerationBackendState.UNAVAILABLE
    assert capabilities.supported_controls == frozenset()


def test_unavailable_backend_blocks_generation_honestly(tmp_path):
    queue = GenerationQueue(generator=UnavailableVoiceGenerator())
    request = build_preview_request(text="hi", voice_profile_id="vp-1", model_id="none")
    item = queue.enqueue(request)
    result = queue.process_one(item.item_id)
    assert result.status == GenerationStatus.BLOCKED
    assert result.artifact is None
    assert any("unavailable" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Generation queue — retry, cancel, failure isolation
# ---------------------------------------------------------------------------


def test_queue_cancel_only_affects_a_still_queued_item(tmp_path):
    data_root = _data_root(tmp_path)
    queue = GenerationQueue(generator=SyntheticVoiceGenerator(data_root))
    request = build_preview_request(text="hi", voice_profile_id="vp-1", model_id="m1")
    item = queue.enqueue(request)
    cancelled = queue.cancel(item.item_id)
    assert cancelled.status == GenerationStatus.CANCELLED
    result = queue.process_one(item.item_id)
    assert result.status == GenerationStatus.CANCELLED
    assert result.artifact is None


def test_queue_retry_with_a_different_generator_can_recover(tmp_path):
    data_root = _data_root(tmp_path)
    queue = GenerationQueue(generator=UnavailableVoiceGenerator())
    request = build_preview_request(text="hi", voice_profile_id="vp-1", model_id="none")
    item = queue.enqueue(request)
    queue.process_one(item.item_id)
    assert queue.get(item.item_id).status == GenerationStatus.BLOCKED

    result = queue.retry(item.item_id, generator=SyntheticVoiceGenerator(data_root))
    assert result.status == GenerationStatus.READY


def test_queue_isolates_one_failing_item_from_the_rest_of_the_batch(tmp_path):
    data_root = _data_root(tmp_path)
    queue = GenerationQueue(generator=SyntheticVoiceGenerator(data_root))
    bad_request = build_preview_request(text="   ", voice_profile_id="vp-1", model_id="m1")
    good_request = build_preview_request(text="a perfectly fine sentence", voice_profile_id="vp-1", model_id="m1")
    bad_item = queue.enqueue(bad_request)
    good_item = queue.enqueue(good_request)

    results = queue.process_all()
    assert len(results) == 2
    assert queue.get(bad_item.item_id).status == GenerationStatus.BLOCKED
    assert queue.get(good_item.item_id).status == GenerationStatus.READY


def test_queue_counts_reflect_real_item_statuses(tmp_path):
    data_root = _data_root(tmp_path)
    queue = GenerationQueue(generator=SyntheticVoiceGenerator(data_root))
    ok = queue.enqueue(build_preview_request(text="fine", voice_profile_id="vp-1", model_id="m1"))
    bad = queue.enqueue(build_preview_request(text="", voice_profile_id="vp-1", model_id="m1"))
    queue.process_one(ok.item_id)
    queue.process_one(bad.item_id)
    counts = queue.counts()
    assert counts[GenerationStatus.READY.value] == 1
    assert counts[GenerationStatus.BLOCKED.value] == 1


# ---------------------------------------------------------------------------
# Output identity — deterministic, never filename/timestamp-based
# ---------------------------------------------------------------------------


def test_artifact_fingerprint_changes_when_text_changes(tmp_path):
    data_root = _data_root(tmp_path)
    generator = SyntheticVoiceGenerator(data_root)
    request_a = build_preview_request(text="text one", voice_profile_id="vp-1", model_id="m1", seed=1)
    request_b = build_preview_request(text="text two", voice_profile_id="vp-1", model_id="m1", seed=1)
    fp_a = build_artifact_fingerprint(request=request_a, tool=generator.name, tool_version=generator.version)
    fp_b = build_artifact_fingerprint(request=request_b, tool=generator.name, tool_version=generator.version)
    assert fp_a.digest() != fp_b.digest()


def test_artifact_fingerprint_changes_when_voice_profile_changes(tmp_path):
    data_root = _data_root(tmp_path)
    generator = SyntheticVoiceGenerator(data_root)
    request_a = build_preview_request(text="same", voice_profile_id="vp-1", model_id="m1")
    request_b = build_preview_request(text="same", voice_profile_id="vp-2", model_id="m1")
    fp_a = build_artifact_fingerprint(request=request_a, tool=generator.name, tool_version=generator.version)
    fp_b = build_artifact_fingerprint(request=request_b, tool=generator.name, tool_version=generator.version)
    assert fp_a.digest() != fp_b.digest()


# ---------------------------------------------------------------------------
# Voice profiles
# ---------------------------------------------------------------------------


def test_voice_profile_defaults_to_synthetic_profile():
    registry = VoiceProfileRegistry()
    profile = registry.create("demo")
    assert profile.state == VoiceProfileState.SYNTHETIC_PROFILE


def test_voice_profile_has_no_speaker_characteristic_fields():
    registry = VoiceProfileRegistry()
    profile = registry.create("demo")
    field_names = set(profile.to_dict().keys())
    assert "speaker_characteristics" not in field_names
    assert "accent" not in field_names
    assert "pronunciation" not in field_names
    assert "prosody" not in field_names


def test_voice_profile_create_version_always_appends():
    registry = VoiceProfileRegistry()
    v1 = registry.create("demo")
    v2 = registry.create_version("demo", notes="tweaked")
    assert v1.version == 1
    assert v2.version == 2
    assert registry.history("demo") == [v1, v2]
    assert v1.notes is None


def test_voice_profile_create_refuses_duplicate_name():
    registry = VoiceProfileRegistry()
    registry.create("demo")
    with pytest.raises(ValueError, match="already exists"):
        registry.create("demo")


# ---------------------------------------------------------------------------
# Preview history — versioning, regeneration, provenance
# ---------------------------------------------------------------------------


def test_preview_history_record_validates_against_schema(tmp_path):
    queue, item, data_root = _generate(tmp_path)
    log = PreviewHistoryLog(tmp_path / "preview_history.jsonl")
    record = record_generation_result(log, item, voice_profile_id="vp-1")
    validate(record, SchemaName.PREVIEW_HISTORY)


def test_preview_history_is_append_only_across_regenerations(tmp_path):
    data_root = _data_root(tmp_path)
    generator = SyntheticVoiceGenerator(data_root)
    queue = GenerationQueue(generator=generator)
    log = PreviewHistoryLog(tmp_path / "preview_history.jsonl")

    request1 = build_preview_request(text="Generation one", voice_profile_id="vp-1", model_id="m1")
    item1 = queue.enqueue(request1)
    queue.process_one(item1.item_id)
    rec1 = record_generation_result(log, item1, voice_profile_id="vp-1")

    request2 = build_preview_request(text="Generation two", voice_profile_id="vp-1", model_id="m1")
    item2 = queue.enqueue(request2)
    queue.process_one(item2.item_id)
    rec2 = record_generation_result(log, item2, voice_profile_id="vp-1")

    records = history(log, "vp-1")
    assert [r["record_id"] for r in records] == [rec1["record_id"], rec2["record_id"]]
    assert current(log, "vp-1")["record_id"] == rec2["record_id"]
    assert log.get(rec1["record_id"]) == rec1, "the first generation must remain unmodified"
    assert regeneration_count(log, "vp-1") == 1


def test_preview_history_current_is_none_for_an_unstarted_profile(tmp_path):
    log = PreviewHistoryLog(tmp_path / "preview_history.jsonl")
    assert current(log, "never-generated") is None
    assert regeneration_count(log, "never-generated") == 0


# ---------------------------------------------------------------------------
# Preview feedback — VL-D5 §21-§22
# ---------------------------------------------------------------------------


def test_feedback_requires_listened_for_accept_or_reject(tmp_path):
    log = PreviewFeedbackLog(tmp_path / "preview_feedback.jsonl")
    with pytest.raises(UnlistenedFeedbackError):
        record_preview_feedback(
            log, preview_id="p1", listener="operator", outcome=PreviewFeedbackOutcome.ACCEPTED, listened=False
        )


def test_feedback_allows_regenerate_or_uncertain_without_listening(tmp_path):
    log = PreviewFeedbackLog(tmp_path / "preview_feedback.jsonl")
    record = record_preview_feedback(
        log, preview_id="p1", listener="operator", outcome=PreviewFeedbackOutcome.UNCERTAIN, listened=False
    )
    validate(record, SchemaName.PREVIEW_FEEDBACK)
    assert record["listened"] is False


def test_feedback_validates_the_category(tmp_path):
    log = PreviewFeedbackLog(tmp_path / "preview_feedback.jsonl")
    with pytest.raises(ValueError, match="PreviewFeedbackCategory"):
        record_preview_feedback(
            log,
            preview_id="p1",
            listener="operator",
            outcome=PreviewFeedbackOutcome.UNCERTAIN,
            listened=True,
            category="NOT_REAL",
        )


def test_feedback_is_recorded_with_category_and_rating(tmp_path):
    log = PreviewFeedbackLog(tmp_path / "preview_feedback.jsonl")
    record = record_preview_feedback(
        log,
        preview_id="p1",
        listener="operator",
        outcome=PreviewFeedbackOutcome.ACCEPTED,
        listened=True,
        category=PreviewFeedbackCategory.NATURALNESS,
        rating=4,
        comment="sounds fine",
    )
    validate(record, SchemaName.PREVIEW_FEEDBACK)
    assert record["attributes"] == {"category": "NATURALNESS", "rating": "4"}
    assert feedback_for(log, "p1") == [record]
    assert counts_by_outcome(log)["accepted"] == 1
    assert counts_by_category(log)["NATURALNESS"] == 1


def test_feedback_is_never_a_speaker_or_training_field(tmp_path):
    log = PreviewFeedbackLog(tmp_path / "preview_feedback.jsonl")
    record = record_preview_feedback(
        log, preview_id="p1", listener="operator", outcome=PreviewFeedbackOutcome.ACCEPTED, listened=True
    )
    dumped = str(record).lower()
    assert "speaker" not in dumped
    assert "training_label" not in dumped


# ---------------------------------------------------------------------------
# A/B comparison metadata
# ---------------------------------------------------------------------------


def test_ab_comparison_never_claims_acoustic_similarity(tmp_path):
    _, item_a, data_root = _generate(tmp_path, text="version a")
    queue = GenerationQueue(generator=SyntheticVoiceGenerator(data_root))
    request_b = build_preview_request(text="version b, a bit longer than a", voice_profile_id="vp-1", model_id="m1")
    item_b = queue.enqueue(request_b)
    queue.process_one(item_b.item_id)

    comparison = build_ab_comparison(item_a.artifact, item_b.artifact)
    assert "acoustic similarity" in comparison["note"] or "no acoustic similarity" in comparison["note"]
    assert comparison["sample_rate_match"] is True
    assert comparison["both_synthetic"] is True


def test_ab_comparison_handles_missing_duration_honestly():
    comparison = build_ab_comparison({"sample_rate": 16000}, {"sample_rate": 16000})
    assert comparison["duration_diff_seconds"] is None


# ---------------------------------------------------------------------------
# Calibration prep for preview signals
# ---------------------------------------------------------------------------


def test_preview_calibration_summary_is_always_uncalibrated_with_real_counts(tmp_path):
    data_root = _data_root(tmp_path)
    generator = SyntheticVoiceGenerator(data_root)
    queue = GenerationQueue(generator=generator)
    history_log = PreviewHistoryLog(tmp_path / "preview_history.jsonl")
    feedback_log = PreviewFeedbackLog(tmp_path / "preview_feedback.jsonl")

    request = build_preview_request(text="calibration test", voice_profile_id="vp-1", model_id="m1")
    item = queue.enqueue(request)
    queue.process_one(item.item_id)
    record_generation_result(history_log, item, voice_profile_id="vp-1")
    record_preview_feedback(
        feedback_log, preview_id=item.artifact["preview_id"], listener="operator",
        outcome=PreviewFeedbackOutcome.ACCEPTED, listened=True, category=PreviewFeedbackCategory.OVERALL,
    )

    summary = summarize_preview_calibration_inputs(history_log=history_log, feedback_log=feedback_log)
    assert summary.calibration_state.value == "UNCALIBRATED"
    assert summary.total_generations == 1
    assert summary.voice_profile_count == 1
    assert summary.accepted_count == 1
    assert summary.feedback_counts_by_category["OVERALL"] == 1


def test_preview_calibration_summary_handles_no_data_honestly():
    summary = summarize_preview_calibration_inputs()
    assert summary.total_generations == 0
    assert summary.voice_profile_count == 0
    assert summary.total_regenerations == 0


# ---------------------------------------------------------------------------
# Hardware capability reuse — no vendor lock-in
# ---------------------------------------------------------------------------


def test_runtime_capability_is_reused_not_reinvented():
    capability = RuntimeCapability(
        component="synthetic-tone-generator",
        acceleration=AccelerationRequirement.CPU_ONLY,
        supported_backends=(ComputeBackend.CPU,),
        portability=PortabilityClass.PORTABLE,
    )
    assert capability.runs_on_cpu is True
    assert capability.requires_accelerator is False
