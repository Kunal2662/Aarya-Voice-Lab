"""Tests for VL-D4's Voice Processing + Conditioning layer: processing
profiles, boundary conditioning, noise-conditioning decisions, the
processing queue, derived-artifact identity, processing history +
rollback, and processing feedback.

Every fixture is synthetic; nothing here reads or references source/.
"""

from __future__ import annotations

import pytest

from aarya_voice_lab.audio.probe import read_wav_mono_samples
from aarya_voice_lab.audio.vad import detect_regions
from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.pipeline.conditioning import (
    ConditioningBlocked,
    NoiseConditioningOutcome,
    apply_noise_conditioning,
    compute_boundary_trim,
    condition_boundaries,
)
from aarya_voice_lab.pipeline.contracts import sha256_file
from aarya_voice_lab.pipeline.feedback import (
    FeedbackLog,
    ProcessingFeedbackCategory,
    counts_by_type,
    record_processing_feedback,
)
from aarya_voice_lab.pipeline.processing import (
    ProcessingDecision,
    ProcessingDecisionThresholds,
    ProcessingQueue,
    ProcessingStatus,
    build_artifact_fingerprint,
    decide_processing,
)
from aarya_voice_lab.pipeline.processing_history import (
    ProcessingHistoryLog,
    RollbackTargetNotFound,
    current,
    history,
    record_processing_result,
    rollback,
)
from aarya_voice_lab.pipeline.processing_profile import (
    BoundaryPolicy,
    NoiseConditioningMode,
    ProcessingProfileRegistry,
)
from aarya_voice_lab.schemas.base import SchemaName, validate
from aarya_voice_lab.testing.synthetic_audio import (
    generate_clipped,
    generate_narrowband,
    generate_padded_speech,
    generate_speech_like,
    generate_tone,
)


def _data_root(tmp_path):
    root = DataRoot(root=tmp_path / "data")
    (root.source).mkdir(parents=True, exist_ok=True)
    (root.working).mkdir(parents=True, exist_ok=True)
    return root


def _measure_and_vad(path):
    samples, rate = read_wav_mono_samples(path)
    vad = detect_regions(samples, rate)
    return samples, rate, vad


# ---------------------------------------------------------------------------
# Processing profiles
# ---------------------------------------------------------------------------


def test_profile_create_refuses_a_duplicate_name():
    registry = ProcessingProfileRegistry()
    registry.create("default")
    with pytest.raises(ValueError, match="already exists"):
        registry.create("default")


def test_profile_create_version_always_appends_never_edits():
    registry = ProcessingProfileRegistry()
    v1 = registry.create("default")
    v2 = registry.create_version("default", notes="tweaked")
    assert v1.version == 1
    assert v2.version == 2
    assert registry.history("default") == [v1, v2]
    assert registry.latest("default") is v2
    # The original version object is untouched -- frozen dataclass, and
    # no method exists that could mutate it.
    assert v1.notes is None


def test_profile_config_hash_changes_when_a_field_changes():
    registry = ProcessingProfileRegistry()
    v1 = registry.create("default")
    v2 = registry.create_version("default", boundary=BoundaryPolicy(pad_seconds=0.5))
    assert v1.config_hash() != v2.config_hash()


def test_profile_duplicate_creates_an_independent_named_profile():
    registry = ProcessingProfileRegistry()
    registry.create("source", notes="original")
    copy = registry.duplicate("source", "copy")
    assert copy.name == "copy"
    assert copy.version == 1
    assert copy.notes == "original"
    # Versioning one does not affect the other.
    registry.create_version("source")
    assert registry.latest("copy").version == 1


def test_profile_set_default_and_default_reflect_the_latest_version():
    registry = ProcessingProfileRegistry()
    registry.create("a")
    registry.create("b")
    registry.set_default("b")
    assert registry.default().name == "b"
    registry.create_version("b")
    assert registry.default().version == 2


def test_profile_registry_rejects_unknown_field_overrides():
    registry = ProcessingProfileRegistry()
    registry.create("default")
    with pytest.raises(TypeError, match="unknown profile field"):
        registry.create_version("default", speaker_id="nope")


# ---------------------------------------------------------------------------
# Boundary conditioning — no FFmpeg required
# ---------------------------------------------------------------------------


def test_boundary_trim_removes_real_edge_silence(tmp_path):
    data_root = _data_root(tmp_path)
    source = generate_padded_speech(
        data_root.source / "a.wav", leading_silence_seconds=1.0, trailing_silence_seconds=0.8
    )
    samples, rate, vad = _measure_and_vad(source)
    duration = len(samples) / rate
    dest = data_root.working / "a.trimmed.wav"

    record = condition_boundaries(
        source,
        dest,
        source_file_id="src-a",
        source_sha256=sha256_file(source),
        vad=vad,
        duration_seconds=duration,
        data_root=data_root,
        policy=BoundaryPolicy(),
    )
    assert record.leading_trim_seconds > 0.5
    assert record.trailing_trim_seconds > 0.3
    assert dest.is_file()
    assert source.is_file()
    assert sha256_file(source) == record.source_sha256, "source must be untouched"


def test_boundary_trim_is_a_no_op_on_edge_to_edge_speech(tmp_path):
    data_root = _data_root(tmp_path)
    source = generate_speech_like(data_root.source / "a.wav", duration_seconds=2.0)
    samples, rate, vad = _measure_and_vad(source)
    dest = data_root.working / "a.trimmed.wav"

    record = condition_boundaries(
        source,
        dest,
        source_file_id="src-a",
        source_sha256=sha256_file(source),
        vad=vad,
        duration_seconds=len(samples) / rate,
        data_root=data_root,
    )
    assert record.leading_trim_seconds == 0.0
    assert record.trailing_trim_seconds == 0.0
    assert record.output_sha256 == record.source_sha256, "no trim -> byte-identical derived copy"


def test_boundary_trim_never_cuts_a_short_edge_pause(tmp_path):
    data_root = _data_root(tmp_path)
    # A pause shorter than min_trim_seconds must be left alone.
    source = generate_padded_speech(
        data_root.source / "a.wav", leading_silence_seconds=0.05, trailing_silence_seconds=0.05
    )
    samples, rate, vad = _measure_and_vad(source)
    leading, trailing = compute_boundary_trim(vad, len(samples) / rate, BoundaryPolicy(min_trim_seconds=0.1))
    assert leading == 0.0
    assert trailing == 0.0


def test_boundary_trim_respects_a_disabled_edge():
    class _Region:
        def __init__(self, start, end):
            self.start = start
            self.end = end

    class _Vad:
        speech_regions = [_Region(1.0, 3.0)]

    leading, trailing = compute_boundary_trim(_Vad(), 4.0, BoundaryPolicy(trim_leading_silence=False))
    assert leading == 0.0
    assert trailing == 1.0


def test_boundary_conditioning_refuses_to_write_into_source(tmp_path):
    data_root = _data_root(tmp_path)
    source = generate_tone(data_root.source / "a.wav")
    samples, rate, vad = _measure_and_vad(source)
    from aarya_voice_lab.core.data_root import SourceImmutabilityError

    with pytest.raises(SourceImmutabilityError):
        condition_boundaries(
            source,
            data_root.source / "batch-001" / "out.wav",
            source_file_id="src-a",
            source_sha256=sha256_file(source),
            vad=vad,
            duration_seconds=len(samples) / rate,
            data_root=data_root,
        )


def test_boundary_conditioning_blocked_on_source_hash_mismatch(tmp_path):
    data_root = _data_root(tmp_path)
    source = generate_tone(data_root.source / "a.wav")
    samples, rate, vad = _measure_and_vad(source)
    with pytest.raises(ConditioningBlocked, match="hash mismatch"):
        condition_boundaries(
            source,
            data_root.working / "out.wav",
            source_file_id="src-a",
            source_sha256="0" * 64,
            vad=vad,
            duration_seconds=len(samples) / rate,
            data_root=data_root,
        )


def test_boundary_conditioning_refuses_to_overwrite_an_existing_derived_artifact(tmp_path):
    data_root = _data_root(tmp_path)
    source = generate_tone(data_root.source / "a.wav")
    samples, rate, vad = _measure_and_vad(source)
    dest = data_root.working / "out.wav"
    dest.write_bytes(b"already here")
    with pytest.raises(ConditioningBlocked, match="already exists"):
        condition_boundaries(
            source,
            dest,
            source_file_id="src-a",
            source_sha256=sha256_file(source),
            vad=vad,
            duration_seconds=len(samples) / rate,
            data_root=data_root,
        )


# ---------------------------------------------------------------------------
# Noise conditioning — a decision, not an implementation, in VL-D4
# ---------------------------------------------------------------------------


def test_noise_conditioning_off_and_measure_only_never_claim_to_alter_audio():
    off = apply_noise_conditioning(NoiseConditioningMode.OFF)
    measured = apply_noise_conditioning(NoiseConditioningMode.MEASURE_ONLY)
    assert off.outcome == NoiseConditioningOutcome.NOT_APPLIED
    assert measured.outcome == NoiseConditioningOutcome.MEASURED_ONLY


def test_noise_conditioning_light_and_standard_are_honestly_not_available():
    for mode in (NoiseConditioningMode.LIGHT, NoiseConditioningMode.STANDARD):
        result = apply_noise_conditioning(mode)
        assert result.outcome == NoiseConditioningOutcome.NOT_AVAILABLE
        assert "NOT AVAILABLE" in result.note
        assert "unchanged" in result.note


# ---------------------------------------------------------------------------
# Processing decision — separate from measurement
# ---------------------------------------------------------------------------


def test_decide_processing_is_review_required_when_snr_cannot_be_measured():
    from aarya_voice_lab.audio.analysis import AudioMeasurements

    measurements = AudioMeasurements(duration_seconds=1.0, sample_rate=16_000, sample_count=16_000)
    assert decide_processing(measurements) == ProcessingDecision.REVIEW_REQUIRED


def test_decide_processing_thresholds_are_configuration_driven():
    from aarya_voice_lab.audio.analysis import AudioMeasurements

    measurements = AudioMeasurements(
        duration_seconds=1.0, sample_rate=16_000, sample_count=16_000, estimated_snr_db=20.0
    )
    lenient = ProcessingDecisionThresholds(min_snr_db_for_no_processing=15.0)
    strict = ProcessingDecisionThresholds(min_snr_db_for_no_processing=30.0)
    assert decide_processing(measurements, lenient) == ProcessingDecision.NO_PROCESSING
    assert decide_processing(measurements, strict) != ProcessingDecision.NO_PROCESSING


# ---------------------------------------------------------------------------
# Derived artifact identity — deterministic, never filename/timestamp-based
# ---------------------------------------------------------------------------


def test_artifact_fingerprint_is_reproducible_for_identical_inputs():
    registry = ProcessingProfileRegistry()
    profile = registry.create("default")
    fp1 = build_artifact_fingerprint(source_sha256="a" * 64, profile=profile, tool_version="6.0")
    fp2 = build_artifact_fingerprint(source_sha256="a" * 64, profile=profile, tool_version="6.0")
    assert fp1.digest() == fp2.digest()


def test_artifact_fingerprint_changes_when_the_profile_changes():
    registry = ProcessingProfileRegistry()
    profile = registry.create("default")
    other = registry.create_version("default", boundary=BoundaryPolicy(pad_seconds=0.9))
    fp1 = build_artifact_fingerprint(source_sha256="a" * 64, profile=profile, tool_version="6.0")
    fp2 = build_artifact_fingerprint(source_sha256="a" * 64, profile=other, tool_version="6.0")
    assert fp1.digest() != fp2.digest()


def test_artifact_fingerprint_changes_when_the_source_changes():
    registry = ProcessingProfileRegistry()
    profile = registry.create("default")
    fp1 = build_artifact_fingerprint(source_sha256="a" * 64, profile=profile, tool_version="6.0")
    fp2 = build_artifact_fingerprint(source_sha256="b" * 64, profile=profile, tool_version="6.0")
    assert fp1.digest() != fp2.digest()


# ---------------------------------------------------------------------------
# Processing queue
# ---------------------------------------------------------------------------


def test_queue_processes_successfully_without_ffmpeg_as_an_honest_warning(tmp_path, monkeypatch):
    from aarya_voice_lab.pipeline import normalization as normalization_module
    from aarya_voice_lab.pipeline import processing as processing_module

    monkeypatch.setattr(normalization_module, "ffmpeg_version", lambda: None)
    monkeypatch.setattr(processing_module, "ffmpeg_version", lambda: None)

    data_root = _data_root(tmp_path)
    source = generate_padded_speech(data_root.source / "a.wav")
    registry = ProcessingProfileRegistry()
    profile = registry.create("default")
    queue = ProcessingQueue(data_root=data_root)
    item = queue.enqueue(
        recording_id="rec-a", source_path=source, source_sha256=sha256_file(source), profile=profile
    )
    result = queue.process_one(item.item_id)

    assert result.status == ProcessingStatus.WARNING
    assert any("normalization unavailable" in w for w in result.warnings)
    assert result.errors == []
    assert result.derived_artifact is not None
    assert sha256_file(source) == item.source_sha256, "source must be untouched"


def test_queue_never_writes_to_source_even_when_ffmpeg_is_available(tmp_path):
    # Not gated on ffmpeg presence -- asserts the invariant regardless of
    # whether this machine has ffmpeg installed.
    data_root = _data_root(tmp_path)
    source = generate_padded_speech(data_root.source / "a.wav")
    before = sha256_file(source)
    registry = ProcessingProfileRegistry()
    profile = registry.create("default")
    queue = ProcessingQueue(data_root=data_root)
    item = queue.enqueue(
        recording_id="rec-a", source_path=source, source_sha256=before, profile=profile
    )
    queue.process_one(item.item_id)
    assert sha256_file(source) == before


def test_queue_isolates_one_failing_item_from_the_rest_of_the_batch(tmp_path):
    data_root = _data_root(tmp_path)
    good = generate_padded_speech(data_root.source / "good.wav")
    registry = ProcessingProfileRegistry()
    profile = registry.create("default")
    queue = ProcessingQueue(data_root=data_root)

    bad_item = queue.enqueue(
        recording_id="rec-bad", source_path=data_root.source / "missing.wav", source_sha256="0" * 64, profile=profile
    )
    good_item = queue.enqueue(
        recording_id="rec-good", source_path=good, source_sha256=sha256_file(good), profile=profile
    )

    results = queue.process_all()
    assert len(results) == 2
    bad_result = queue.get(bad_item.item_id)
    good_result = queue.get(good_item.item_id)
    assert bad_result.status in (ProcessingStatus.BLOCKED, ProcessingStatus.FAILED)
    assert good_result.status in (ProcessingStatus.SUCCESS, ProcessingStatus.WARNING)


def test_queue_blocks_on_source_hash_mismatch_without_crashing(tmp_path):
    data_root = _data_root(tmp_path)
    source = generate_padded_speech(data_root.source / "a.wav")
    registry = ProcessingProfileRegistry()
    profile = registry.create("default")
    queue = ProcessingQueue(data_root=data_root)
    item = queue.enqueue(recording_id="rec-a", source_path=source, source_sha256="0" * 64, profile=profile)
    result = queue.process_one(item.item_id)
    assert result.status == ProcessingStatus.BLOCKED
    assert any("hash mismatch" in e for e in result.errors)


def test_queue_cancel_only_affects_a_still_queued_item(tmp_path):
    data_root = _data_root(tmp_path)
    source = generate_padded_speech(data_root.source / "a.wav")
    registry = ProcessingProfileRegistry()
    profile = registry.create("default")
    queue = ProcessingQueue(data_root=data_root)
    item = queue.enqueue(
        recording_id="rec-a", source_path=source, source_sha256=sha256_file(source), profile=profile
    )
    cancelled = queue.cancel(item.item_id)
    assert cancelled.status == ProcessingStatus.CANCELLED
    # process_one on a cancelled item is a no-op, not an error.
    result = queue.process_one(item.item_id)
    assert result.status == ProcessingStatus.CANCELLED
    assert result.derived_artifact is None


def test_queue_retry_re_runs_a_blocked_item_with_a_corrected_profile(tmp_path):
    data_root = _data_root(tmp_path)
    source = generate_padded_speech(data_root.source / "a.wav")
    registry = ProcessingProfileRegistry()
    profile = registry.create("default")
    queue = ProcessingQueue(data_root=data_root)
    item = queue.enqueue(recording_id="rec-a", source_path=source, source_sha256="0" * 64, profile=profile)
    queue.process_one(item.item_id)
    assert queue.get(item.item_id).status == ProcessingStatus.BLOCKED

    result = queue.retry(item.item_id)
    # Still hashed against the wrong value -- retry does not silently fix
    # a bad source_sha256, it just re-runs.
    assert result.status == ProcessingStatus.BLOCKED

    # Retrying with the *correct* hash captured via a fresh enqueue instead
    # (retry only swaps the profile, not the recorded source hash) proves
    # retry-with-another-profile is wired correctly.
    other_profile = registry.create_version("default", notes="second attempt")
    item2 = queue.enqueue(
        recording_id="rec-a", source_path=source, source_sha256=sha256_file(source), profile=profile
    )
    result2 = queue.retry(item2.item_id, profile=other_profile)
    assert result2.status in (ProcessingStatus.SUCCESS, ProcessingStatus.WARNING)
    assert queue.get(item2.item_id).profile is other_profile


def test_queue_counts_reflect_real_item_statuses(tmp_path):
    data_root = _data_root(tmp_path)
    source = generate_padded_speech(data_root.source / "a.wav")
    registry = ProcessingProfileRegistry()
    profile = registry.create("default")
    queue = ProcessingQueue(data_root=data_root)
    ok = queue.enqueue(
        recording_id="rec-a", source_path=source, source_sha256=sha256_file(source), profile=profile
    )
    blocked = queue.enqueue(recording_id="rec-b", source_path=source, source_sha256="0" * 64, profile=profile)
    queue.process_one(ok.item_id)
    queue.process_one(blocked.item_id)
    counts = queue.counts()
    assert counts[ProcessingStatus.BLOCKED.value] == 1
    assert counts[ProcessingStatus.SUCCESS.value] + counts[ProcessingStatus.WARNING.value] == 1


def test_queue_before_and_after_quality_measurements_are_never_fabricated(tmp_path):
    data_root = _data_root(tmp_path)
    source = generate_clipped(data_root.source / "a.wav")
    registry = ProcessingProfileRegistry()
    profile = registry.create("default")
    queue = ProcessingQueue(data_root=data_root)
    item = queue.enqueue(
        recording_id="rec-a", source_path=source, source_sha256=sha256_file(source), profile=profile
    )
    result = queue.process_one(item.item_id)
    assert result.quality_before is not None
    assert result.quality_after is not None
    assert result.quality_before["measurements"]["clipping_ratio"] > 0


def test_narrowband_audio_is_processed_without_being_treated_as_a_defect(tmp_path):
    data_root = _data_root(tmp_path)
    source = generate_narrowband(data_root.source / "a.wav")
    registry = ProcessingProfileRegistry()
    profile = registry.create("default")
    queue = ProcessingQueue(data_root=data_root)
    item = queue.enqueue(
        recording_id="rec-a", source_path=source, source_sha256=sha256_file(source), profile=profile
    )
    result = queue.process_one(item.item_id)
    assert any("narrowband" in c for c in result.quality_before["characteristics"])
    assert "narrowband" not in {f["code"] for f in result.quality_before["findings"]}


# ---------------------------------------------------------------------------
# Processing history + rollback
# ---------------------------------------------------------------------------


def _processed_item(tmp_path, *, recording_id="rec-a"):
    data_root = _data_root(tmp_path)
    source = generate_padded_speech(data_root.source / f"{recording_id}.wav")
    registry = ProcessingProfileRegistry()
    profile = registry.create("default")
    queue = ProcessingQueue(data_root=data_root)
    item = queue.enqueue(
        recording_id=recording_id, source_path=source, source_sha256=sha256_file(source), profile=profile
    )
    queue.process_one(item.item_id)
    return queue, item, registry


def test_processing_history_record_validates_against_its_schema(tmp_path):
    queue, item, _ = _processed_item(tmp_path)
    log = ProcessingHistoryLog(tmp_path / "history.jsonl")
    record = record_processing_result(log, item)
    validate(record, SchemaName.PROCESSING_HISTORY)


def test_processing_history_is_append_only_never_overwritten(tmp_path):
    queue, item, registry = _processed_item(tmp_path)
    log = ProcessingHistoryLog(tmp_path / "history.jsonl")
    rec1 = record_processing_result(log, item)

    other_profile = registry.create_version("default", notes="second pass")
    item.profile = other_profile
    queue.process_one(item.item_id)
    rec2 = record_processing_result(log, item, supersedes=rec1["record_id"])

    records = history(log, item.recording_id)
    assert [r["record_id"] for r in records] == [rec1["record_id"], rec2["record_id"]]
    assert current(log, item.recording_id)["record_id"] == rec2["record_id"]
    # The first record is still there, byte-for-byte, after the second.
    assert log.get(rec1["record_id"]) == rec1


def test_processing_history_current_is_none_for_an_unprocessed_recording(tmp_path):
    log = ProcessingHistoryLog(tmp_path / "history.jsonl")
    assert current(log, "never-processed") is None


def test_rollback_appends_a_new_record_pointing_at_the_prior_output(tmp_path):
    queue, item, registry = _processed_item(tmp_path)
    log = ProcessingHistoryLog(tmp_path / "history.jsonl")
    rec1 = record_processing_result(log, item)

    other_profile = registry.create_version("default", notes="second pass")
    item.profile = other_profile
    queue.process_one(item.item_id)
    rec2 = record_processing_result(log, item, supersedes=rec1["record_id"])

    rolled_back = rollback(log, item.recording_id, to_record_id=rec1["record_id"])
    assert rolled_back["output_sha256"] == rec1["output_sha256"]
    assert rolled_back["is_rollback"] is True
    assert rolled_back["supersedes"] == rec2["record_id"]
    assert current(log, item.recording_id)["record_id"] == rolled_back["record_id"]
    # Every prior record is still present -- rollback never deletes.
    assert len(history(log, item.recording_id)) == 3


def test_rollback_to_an_unknown_record_id_raises_rather_than_silently_no_opping(tmp_path):
    queue, item, _ = _processed_item(tmp_path)
    log = ProcessingHistoryLog(tmp_path / "history.jsonl")
    record_processing_result(log, item)
    with pytest.raises(RollbackTargetNotFound):
        rollback(log, item.recording_id, to_record_id="does-not-exist")


def test_rollback_to_a_record_belonging_to_a_different_recording_is_refused(tmp_path):
    log = ProcessingHistoryLog(tmp_path / "history.jsonl")
    queue1, item1, _ = _processed_item(tmp_path, recording_id="rec-a")
    record_processing_result(log, item1)
    with pytest.raises(RollbackTargetNotFound):
        rollback(log, "rec-b", to_record_id="proc-hist-00001")


# ---------------------------------------------------------------------------
# Processing feedback
# ---------------------------------------------------------------------------


def test_processing_feedback_validates_the_category(tmp_path):
    log = FeedbackLog(tmp_path / "feedback.jsonl")
    with pytest.raises(ValueError, match="ProcessingFeedbackCategory"):
        record_processing_feedback(log, target_id="proc-hist-00001", reviewer="operator", category="NOT_REAL")


def test_processing_feedback_is_recorded_with_its_category_in_attributes(tmp_path):
    log = FeedbackLog(tmp_path / "feedback.jsonl")
    record = record_processing_feedback(
        log,
        target_id="proc-hist-00001",
        reviewer="operator",
        category=ProcessingFeedbackCategory.OVER_PROCESSED,
        comment="lost some breath sounds",
    )
    validate(record, SchemaName.FEEDBACK)
    assert record["attributes"]["category"] == "OVER_PROCESSED"
    assert counts_by_type(log)["PROCESSING_FEEDBACK"] == 1


def test_processing_feedback_is_never_a_speaker_or_training_field(tmp_path):
    log = FeedbackLog(tmp_path / "feedback.jsonl")
    record = record_processing_feedback(
        log, target_id="proc-hist-00001", reviewer="operator", category=ProcessingFeedbackCategory.GOOD_RESULT
    )
    assert "speaker" not in json_keys(record)
    assert "training_label" not in json_keys(record)


def json_keys(obj, prefix=""):
    keys = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.add(f"{prefix}{k}")
            keys |= json_keys(v, f"{prefix}{k}.")
    return keys


# ---------------------------------------------------------------------------
# Missing-tool honesty (mirrors test_phase2_pipeline.py's normalization test)
# ---------------------------------------------------------------------------


def test_processing_reports_missing_ffmpeg_honestly_never_a_silent_substitute(tmp_path, monkeypatch):
    from aarya_voice_lab.pipeline import normalization as normalization_module

    monkeypatch.setattr(normalization_module, "ffmpeg_version", lambda: None)
    data_root = _data_root(tmp_path)
    source = generate_padded_speech(data_root.source / "a.wav")
    registry = ProcessingProfileRegistry()
    profile = registry.create("default")
    queue = ProcessingQueue(data_root=data_root)
    item = queue.enqueue(
        recording_id="rec-a", source_path=source, source_sha256=sha256_file(source), profile=profile
    )
    result = queue.process_one(item.item_id)
    assert result.derived_artifact["normalization"] is None
    assert result.derived_artifact["boundary"] is not None, "boundary conditioning must still succeed"


def test_unreadable_source_blocks_rather_than_crashing_the_queue(tmp_path):
    data_root = _data_root(tmp_path)
    corrupt = data_root.source / "corrupt.wav"
    corrupt.write_bytes(b"RIFF____WAVEfmt garbage, not a real wav")
    registry = ProcessingProfileRegistry()
    profile = registry.create("default")
    queue = ProcessingQueue(data_root=data_root)
    item = queue.enqueue(
        recording_id="rec-corrupt", source_path=corrupt, source_sha256=sha256_file(corrupt), profile=profile
    )
    result = queue.process_one(item.item_id)
    assert result.status == ProcessingStatus.BLOCKED
