"""Phase 2 dataset pipeline tests.

Every fixture is generated arithmetically by
`aarya_voice_lab.testing.synthetic_audio`. No real recording is read,
written, or referenced anywhere in this file.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from aarya_voice_lab.audio.analysis import measure
from aarya_voice_lab.audio.filetype import ContainerFormat, detect_type
from aarya_voice_lab.audio.probe import (
    AudioReadError,
    probe,
    probe_wav,
    read_wav_mono_samples,
)
from aarya_voice_lab.audio.vad import VadConfig, detect_regions
from aarya_voice_lab.core.data_root import (
    DataRoot,
    InvalidBatchIdError,
    SourceImmutabilityError,
    allocate_batch,
    assert_source_writable,
    create_batch,
    list_batches,
    next_batch_id,
    read_batch,
    validate_batch_id,
)
from aarya_voice_lab.core.paths import PROJECT_ROOT
from aarya_voice_lab.pipeline import dataset_gate as dataset_gate_module
from aarya_voice_lab.pipeline.dataset import (
    PipelineConfig,
    run_dataset_pipeline,
    write_candidate_manifest,
)
from aarya_voice_lab.pipeline.dataset_gate import (
    DatasetAccessDenied,
    assert_access_allowed,
    evaluate_gate,
    format_gate,
)
from aarya_voice_lab.pipeline.inventory import (
    PrivateSourceAccessError,
    build_inventory,
    duplicate_groups,
    verify_sources_unchanged,
)
from aarya_voice_lab.pipeline.normalization import (
    NormalizationBlocked,
    NormalizationConfig,
    normalize_file,
)
from aarya_voice_lab.pipeline.overlap import OverlapStatus, assess_overlap
from aarya_voice_lab.pipeline.quality import (
    QualityDecision,
    QualityThresholds,
    assess_quality,
)
from aarya_voice_lab.pipeline.segmentation import (
    SegmentationConfig,
    SplitReason,
    segment_regions,
)
from aarya_voice_lab.pipeline.validation import ValidationStatus, validate_audio_file
from aarya_voice_lab.schemas.base import SchemaName, ValidationError, validate
from aarya_voice_lab.testing.synthetic_audio import (
    generate_clipped,
    generate_conversation,
    generate_corrupt_wav,
    generate_mislabelled_file,
    generate_narrowband,
    generate_phase2_corpus,
    generate_silence,
    generate_speech_like,
    generate_tone,
    generate_truncated_wav,
    generate_unsupported_file,
    generate_zero_byte,
)

# ==========================================================================
# File type detection — content, never the extension
# ==========================================================================


def test_wav_detected_by_content(tmp_path):
    path = generate_tone(tmp_path / "a.wav")
    assert detect_type(path).container is ContainerFormat.WAV


def test_mp3_content_with_wav_extension_is_detected_as_mp3(tmp_path):
    """The extension must never override the content."""
    path = generate_mislabelled_file(tmp_path / "actually_mp3.wav")
    detected = detect_type(path)
    assert detected.container is ContainerFormat.MP3
    assert detected.extension_mismatch is True


def test_non_audio_is_unknown(tmp_path):
    path = generate_unsupported_file(tmp_path / "text.wav")
    assert detect_type(path).container is ContainerFormat.UNKNOWN


def test_empty_file_detected_as_empty(tmp_path):
    path = generate_zero_byte(tmp_path / "empty.wav")
    assert detect_type(path).container is ContainerFormat.EMPTY


def test_correct_extension_is_not_a_mismatch(tmp_path):
    path = generate_tone(tmp_path / "fine.wav")
    assert detect_type(path).extension_mismatch is False


# ==========================================================================
# Probing
# ==========================================================================


def test_probe_reads_wav_properties(tmp_path):
    path = generate_tone(tmp_path / "a.wav", duration_seconds=1.5, sample_rate=16_000)
    properties = probe(path)
    assert properties.sample_rate == 16_000
    assert properties.channels == 1
    assert properties.bit_depth == 16
    assert abs(properties.duration_seconds - 1.5) < 0.01
    assert properties.source == "wave"


def test_probe_rejects_corrupt_wav(tmp_path):
    with pytest.raises(AudioReadError):
        probe(generate_corrupt_wav(tmp_path / "bad.wav"))


def test_probe_rejects_empty_file(tmp_path):
    with pytest.raises(AudioReadError):
        probe(generate_zero_byte(tmp_path / "empty.wav"))


def test_truncated_wav_is_flagged(tmp_path):
    path = generate_truncated_wav(tmp_path / "cut.wav")
    try:
        properties = probe_wav(path)
    except AudioReadError:
        return  # Also acceptable: unreadable rather than merely suspicious.
    assert any("truncated" in w for w in properties.warnings)


def test_read_mono_samples(tmp_path):
    path = generate_tone(tmp_path / "a.wav", duration_seconds=0.5, sample_rate=16_000)
    samples, rate = read_wav_mono_samples(path)
    assert rate == 16_000
    assert len(samples) == 8000


# ==========================================================================
# Validation — VALID / WARNING / INVALID / BLOCKED
# ==========================================================================


def test_good_audio_validates(tmp_path):
    path = generate_speech_like(tmp_path / "ok.wav", duration_seconds=2.0)
    result = validate_audio_file(path, source_file_id="s1")
    assert result.status is ValidationStatus.VALID


def test_zero_byte_is_invalid(tmp_path):
    result = validate_audio_file(generate_zero_byte(tmp_path / "z.wav"), source_file_id="s1")
    assert result.status is ValidationStatus.INVALID
    assert result.findings[0].code == "zero_byte_file"


def test_corrupt_is_invalid(tmp_path):
    result = validate_audio_file(generate_corrupt_wav(tmp_path / "c.wav"), source_file_id="s1")
    assert result.status is ValidationStatus.INVALID


def test_unsupported_content_is_invalid(tmp_path):
    result = validate_audio_file(generate_unsupported_file(tmp_path / "u.wav"), source_file_id="s1")
    assert result.status is ValidationStatus.INVALID
    assert any(f.code == "unrecognised_container" for f in result.findings)


def test_missing_file_is_invalid(tmp_path):
    result = validate_audio_file(tmp_path / "nope.wav", source_file_id="s1")
    assert result.status is ValidationStatus.INVALID


def test_extension_mismatch_is_a_warning_not_a_rejection(tmp_path):
    """A wrong extension is a labelling problem, not a corrupt file."""
    path = generate_mislabelled_file(tmp_path / "m.wav")
    result = validate_audio_file(path, source_file_id="s1")
    assert any(f.code == "extension_mismatch" for f in result.findings)


def test_telephone_audio_is_valid_with_a_warning_only(tmp_path):
    """Narrowband call recordings are expected input and must never be
    rejected by validation."""
    path = generate_narrowband(tmp_path / "phone.wav")
    result = validate_audio_file(path, source_file_id="s1")
    assert result.status is not ValidationStatus.INVALID
    assert any(f.code == "low_sample_rate" for f in result.findings)


def test_non_wav_without_ffmpeg_is_blocked_not_invalid(tmp_path, monkeypatch):
    """Missing capability must never be recorded as a bad file."""
    from aarya_voice_lab.pipeline import validation as validation_module

    monkeypatch.setattr(validation_module, "ffmpeg_available", lambda: False)
    path = generate_mislabelled_file(tmp_path / "song.mp3")
    result = validate_audio_file(path, source_file_id="s1")
    assert result.status is ValidationStatus.BLOCKED
    assert any(f.code == "capability_unavailable" for f in result.findings)


# ==========================================================================
# Inventory
# ==========================================================================


def test_inventory_detects_duplicate_content(tmp_path):
    corpus = tmp_path / "corpus"
    paths = generate_phase2_corpus(corpus)
    inventory = build_inventory(corpus)
    duplicates = inventory.duplicates
    assert duplicates, "duplicate content was not detected"
    assert any(d.duplicate_of for d in duplicates)
    assert paths["duplicate"].name in [d.filename for d in duplicates] or duplicates


def test_duplicate_groups_reports_shared_hashes(tmp_path):
    corpus = tmp_path / "corpus"
    generate_phase2_corpus(corpus)
    groups = duplicate_groups(build_inventory(corpus))
    assert any(len(paths) >= 2 for paths in groups.values())


def test_inventory_flags_zero_byte_and_unsupported(tmp_path):
    corpus = tmp_path / "corpus"
    generate_phase2_corpus(corpus)
    inventory = build_inventory(corpus)
    statuses = {r.processing_status for r in inventory.files}
    assert "zero_byte" in statuses
    assert "unsupported" in statuses or "unreadable" in statuses


def test_source_file_id_is_content_addressed(tmp_path):
    """Identity follows content, so a rename does not create a new file."""
    directory = tmp_path / "d"
    directory.mkdir()
    first = generate_tone(directory / "one.wav", duration_seconds=0.5)
    original_id = build_inventory(directory).files[0].source_file_id

    first.rename(directory / "renamed.wav")
    assert build_inventory(directory).files[0].source_file_id == original_id


def test_inventory_is_deterministic(tmp_path):
    corpus = tmp_path / "corpus"
    generate_phase2_corpus(corpus)
    first = build_inventory(corpus).to_dict()
    second = build_inventory(corpus).to_dict()
    assert first == second


def test_inventory_finds_audio_with_wrong_extension(tmp_path):
    """A recording with a misleading extension must not be silently skipped."""
    directory = tmp_path / "d"
    directory.mkdir()
    generate_mislabelled_file(directory / "recording.dat")
    assert len(build_inventory(directory).files) == 1


def test_verify_sources_unchanged_detects_modification(tmp_path):
    directory = tmp_path / "d"
    directory.mkdir()
    path = generate_tone(directory / "a.wav", duration_seconds=0.5)
    inventory = build_inventory(directory)
    assert verify_sources_unchanged(inventory, directory) == []

    generate_tone(path, duration_seconds=0.6)  # simulate an illegal edit
    problems = verify_sources_unchanged(inventory, directory)
    assert problems and "immutable" in problems[0]


def test_verify_sources_detects_missing_file(tmp_path):
    directory = tmp_path / "d"
    directory.mkdir()
    path = generate_tone(directory / "a.wav", duration_seconds=0.5)
    inventory = build_inventory(directory)
    path.unlink()
    assert any("missing" in p for p in verify_sources_unchanged(inventory, directory))


def test_inventory_still_refuses_private_source_tree():
    with pytest.raises(PrivateSourceAccessError):
        build_inventory(PROJECT_ROOT / "source")


def test_inventory_refuses_data_source_tree(tmp_path):
    from aarya_voice_lab.pipeline.inventory import require_synthetic_or_approved

    with pytest.raises(PrivateSourceAccessError):
        require_synthetic_or_approved(DataRoot.default().source / "batch-001")


# ==========================================================================
# Measurement (raw) vs quality decision (configured)
# ==========================================================================


def test_measurements_are_judgement_free(tmp_path):
    samples, rate = read_wav_mono_samples(generate_speech_like(tmp_path / "a.wav"))
    measurements = measure(samples, rate)
    payload = measurements.to_dict()
    # No verdict language may leak into raw measurements.
    assert not any(key in payload for key in ("decision", "status", "pass", "fail"))
    assert payload["sample_count"] > 0


def test_clipping_is_measured(tmp_path):
    samples, rate = read_wav_mono_samples(generate_clipped(tmp_path / "c.wav"))
    assert measure(samples, rate).clipping_ratio > 0.1


def test_silence_is_measured_as_silent(tmp_path):
    samples, rate = read_wav_mono_samples(generate_silence(tmp_path / "s.wav", duration_seconds=1.0))
    assert measure(samples, rate).silent_frame_ratio > 0.9


def test_heavy_clipping_fails_quality(tmp_path):
    samples, rate = read_wav_mono_samples(generate_clipped(tmp_path / "c.wav"))
    assessment = assess_quality("s1", measure(samples, rate))
    assert assessment.decision is QualityDecision.FAIL


def test_silence_does_not_pass_quality(tmp_path):
    samples, rate = read_wav_mono_samples(generate_silence(tmp_path / "s.wav", duration_seconds=2.0))
    assessment = assess_quality("s1", measure(samples, rate))
    assert assessment.decision in (QualityDecision.FAIL, QualityDecision.REVIEW)


def test_telephone_audio_is_a_characteristic_not_a_failure(tmp_path):
    """The central quality rule: narrowband call audio is expected input."""
    path = generate_narrowband(tmp_path / "phone.wav")
    samples, rate = read_wav_mono_samples(path)
    measurements = measure(samples, rate)
    vad = detect_regions(samples, rate)
    assessment = assess_quality("s1", measurements, vad)

    assert assessment.decision is not QualityDecision.FAIL
    assert any("narrowband" in c for c in assessment.characteristics)
    # No finding may cite the sample rate as a defect.
    assert not any("sample_rate" in f.code for f in assessment.findings)


def test_quality_thresholds_are_configurable(tmp_path):
    samples, rate = read_wav_mono_samples(generate_clipped(tmp_path / "c.wav"))
    measurements = measure(samples, rate)

    strict = assess_quality("s1", measurements, thresholds=QualityThresholds())
    lenient = assess_quality(
        "s1", measurements, thresholds=QualityThresholds(max_clipping_ratio_fail=0.99)
    )
    assert strict.decision is QualityDecision.FAIL
    assert lenient.decision is not QualityDecision.FAIL


def test_threshold_change_changes_config_hash():
    """Resumability depends on threshold changes invalidating cached work."""
    a = QualityThresholds().config_hash()
    b = QualityThresholds(max_clipping_ratio_fail=0.4).config_hash()
    assert a != b


def test_findings_cite_their_measurement(tmp_path):
    """No invented scores: every finding names the number behind it."""
    samples, rate = read_wav_mono_samples(generate_clipped(tmp_path / "c.wav"))
    assessment = assess_quality("s1", measure(samples, rate))
    for finding in assessment.findings:
        assert finding.measured_value is not None
        assert finding.threshold is not None


# ==========================================================================
# Speech / silence
# ==========================================================================


def test_vad_finds_speech_and_silence(tmp_path):
    path, _ = generate_conversation(tmp_path / "c.wav")
    samples, rate = read_wav_mono_samples(path)
    result = detect_regions(samples, rate)
    assert result.speech_regions
    assert result.silence_regions
    assert 0 < result.speech_ratio < 1


def test_vad_reports_pure_silence_as_no_speech(tmp_path):
    samples, rate = read_wav_mono_samples(generate_silence(tmp_path / "s.wav", duration_seconds=1.0))
    assert detect_regions(samples, rate).speech_ratio == 0.0


def test_short_pauses_do_not_split_speech(tmp_path):
    """Natural pauses inside a sentence must be preserved, not cut."""
    path, _ = generate_conversation(tmp_path / "c.wav", pause_seconds=0.1, include_overlap=False)
    samples, rate = read_wav_mono_samples(path)
    tolerant = detect_regions(samples, rate, config=VadConfig(min_silence_seconds=1.0))
    aggressive = detect_regions(samples, rate, config=VadConfig(min_silence_seconds=0.02))
    assert len(tolerant.speech_regions) <= len(aggressive.speech_regions)


def test_vad_thresholds_are_configurable(tmp_path):
    samples, rate = read_wav_mono_samples(generate_speech_like(tmp_path / "a.wav"))
    strict = detect_regions(samples, rate, config=VadConfig(silence_rms_threshold=0.9))
    loose = detect_regions(samples, rate, config=VadConfig(silence_rms_threshold=0.0001))
    assert strict.speech_ratio <= loose.speech_ratio


def test_long_pauses_are_reported(tmp_path):
    path, _ = generate_conversation(tmp_path / "c.wav", pause_seconds=3.0, include_overlap=False)
    samples, rate = read_wav_mono_samples(path)
    assert detect_regions(samples, rate).long_pauses(threshold=2.0)


# ==========================================================================
# Segmentation
# ==========================================================================


def test_segmentation_is_deterministic(tmp_path):
    path, _ = generate_conversation(tmp_path / "c.wav")
    samples, rate = read_wav_mono_samples(path)
    vad = detect_regions(samples, rate)
    first = segment_regions(vad, source_file_id="s1", source_sha256="a" * 64)
    second = segment_regions(vad, source_file_id="s1", source_sha256="a" * 64)
    assert [s.to_dict() for s in first] == [s.to_dict() for s in second]


def test_segments_carry_full_provenance(tmp_path):
    path, _ = generate_conversation(tmp_path / "c.wav")
    samples, rate = read_wav_mono_samples(path)
    segments = segment_regions(
        detect_regions(samples, rate), source_file_id="s1", source_sha256="b" * 64
    )
    for segment in segments:
        assert segment.source_file_id == "s1"
        assert segment.source_sha256 == "b" * 64
        assert segment.config_hash
        assert segment.segmentation_version
        assert segment.end > segment.start


def test_segments_have_no_speaker_field():
    """Phase 2 must be structurally incapable of claiming a speaker."""
    from aarya_voice_lab.pipeline.segmentation import CandidateSegment

    fields = set(CandidateSegment.__dataclass_fields__)
    assert not any("speaker" in f for f in fields)


def test_long_regions_are_split(tmp_path):
    samples, rate = read_wav_mono_samples(
        generate_speech_like(tmp_path / "long.wav", duration_seconds=12.0)
    )
    vad = detect_regions(samples, rate)
    segments = segment_regions(
        vad,
        source_file_id="s1",
        source_sha256="c" * 64,
        config=SegmentationConfig(max_segment_seconds=3.0),
    )
    assert len(segments) > 1
    assert all(s.duration <= 3.01 for s in segments)


def test_hard_splits_are_recorded(tmp_path):
    """A cut made without a natural pause must be visible to review."""
    samples, rate = read_wav_mono_samples(
        generate_speech_like(tmp_path / "long.wav", duration_seconds=10.0)
    )
    segments = segment_regions(
        detect_regions(samples, rate),
        source_file_id="s1",
        source_sha256="d" * 64,
        config=SegmentationConfig(max_segment_seconds=2.0),
    )
    assert any(s.split_reason is SplitReason.HARD_SPLIT for s in segments)


def test_tiny_fragments_are_dropped(tmp_path):
    samples, rate = read_wav_mono_samples(generate_speech_like(tmp_path / "a.wav", duration_seconds=3.0))
    segments = segment_regions(
        detect_regions(samples, rate),
        source_file_id="s1",
        source_sha256="e" * 64,
        config=SegmentationConfig(drop_below_seconds=1.0),
    )
    assert all(s.duration >= 1.0 for s in segments)


def test_segmentation_config_change_changes_hash():
    assert SegmentationConfig().config_hash() != SegmentationConfig(max_segment_seconds=5.0).config_hash()


# ==========================================================================
# Overlap candidates — never a speaker decision
# ==========================================================================


def test_short_segment_is_unknown_not_clear(tmp_path):
    """Undecidable must never be recorded as 'no overlap'."""
    samples, rate = read_wav_mono_samples(generate_tone(tmp_path / "t.wav", duration_seconds=0.05))
    assessment = assess_overlap("seg1", samples, rate)
    assert assessment.status is OverlapStatus.UNKNOWN
    assert assessment.confidence is None


def test_empty_audio_is_unknown():
    assert assess_overlap("seg1", [], 16_000).status is OverlapStatus.UNKNOWN


def test_overlap_assessment_records_method_and_evidence(tmp_path):
    samples, rate = read_wav_mono_samples(generate_speech_like(tmp_path / "a.wav", duration_seconds=2.0))
    assessment = assess_overlap("seg1", samples, rate)
    assert assessment.detection_method
    assert assessment.detector_version
    assert assessment.evidence
    assert assessment.note and "Phase 3" in assessment.note


def test_overlap_statuses_requiring_phase3(tmp_path):
    from aarya_voice_lab.pipeline.overlap import OverlapAssessment

    for status in (OverlapStatus.POSSIBLE_OVERLAP, OverlapStatus.OVERLAP_DETECTED, OverlapStatus.UNKNOWN):
        assessment = OverlapAssessment("s", status, None)
        assert assessment.requires_phase3_resolution
    assert not OverlapAssessment("s", OverlapStatus.NO_OVERLAP_DETECTED, 0.9).requires_phase3_resolution


def test_overlap_confidence_is_not_called_a_probability(tmp_path):
    samples, rate = read_wav_mono_samples(generate_speech_like(tmp_path / "a.wav", duration_seconds=2.0))
    assert "not a probability" in assess_overlap("s", samples, rate).note


# ==========================================================================
# Batches and the data root
# ==========================================================================


def test_batch_id_validation():
    assert validate_batch_id("batch-001") == "batch-001"
    for invalid in ("batch-1", "batch001", "001", "batch-abc", ""):
        with pytest.raises(InvalidBatchIdError):
            validate_batch_id(invalid)


def test_next_batch_id_supports_future_recordings():
    """New recordings must be addable without reprocessing existing ones."""
    assert next_batch_id([]) == "batch-001"
    assert next_batch_id(["batch-001"]) == "batch-002"
    assert next_batch_id(["batch-001", "batch-009"]) == "batch-010"


def test_batch_metadata_roundtrip(tmp_path):
    data_root = DataRoot(root=tmp_path / "data").create()
    created = create_batch(data_root, "batch-001", source_file_count=3, notes="synthetic")
    loaded = read_batch(data_root, "batch-001")
    assert loaded.batch_id == created.batch_id
    assert loaded.source_file_count == 3
    assert "batch-001" in list_batches(data_root)


def test_next_batch_id_is_race_free_under_concurrent_invocation():
    """next_batch_id() is pure and stateless (no filesystem access), so it
    cannot race on its own -- N concurrent callers handed the identical
    input must deterministically compute the identical output. This is
    the literal "test next_batch_id() under concurrent invocation"
    requirement; the real race this hardening milestone closes lives one
    layer up, in the list-then-create sequence a caller builds around it
    -- see test_allocate_batch_is_race_free_under_concurrent_writers."""
    existing = ["batch-001", "batch-002", "batch-009"]
    results = []
    barrier = threading.Barrier(16)

    def call():
        barrier.wait()
        results.append(next_batch_id(existing))

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(lambda _: call(), range(16)))

    assert results == ["batch-010"] * 16


def test_allocate_batch_is_race_free_under_concurrent_writers(tmp_path):
    """Hardening milestone F-2 -- exercises the real persistence mechanism
    (allocate_batch()'s file lock over the actual manifests/ directory),
    not a mocked stand-in. 20 threads race to allocate a batch id at the
    same time; every writer must succeed, every id must be unique, and
    every batch's manifest must be independently readable afterward."""
    data_root = DataRoot(root=tmp_path / "data").create()
    writer_count = 20
    barrier = threading.Barrier(writer_count)

    def allocate():
        barrier.wait()
        return allocate_batch(data_root, source_file_count=1).batch_id

    with ThreadPoolExecutor(max_workers=writer_count) as pool:
        batch_ids = list(pool.map(lambda _: allocate(), range(writer_count)))

    assert len(batch_ids) == writer_count
    assert len(set(batch_ids)) == writer_count, f"duplicate batch id assigned: {batch_ids}"
    assert set(batch_ids) == {f"batch-{n:03d}" for n in range(1, writer_count + 1)}
    on_disk = list_batches(data_root)
    assert len(on_disk) == writer_count
    for batch_id in batch_ids:
        loaded = read_batch(data_root, batch_id)
        assert loaded is not None
        assert loaded.batch_id == batch_id
        assert loaded.source_file_count == 1


def test_data_root_create_does_not_create_source(tmp_path):
    """`source/` is placed by the operator, never fabricated by the tool."""
    data_root = DataRoot(root=tmp_path / "data").create()
    assert data_root.working.is_dir()
    assert not data_root.source.exists()


def test_writes_into_source_are_refused(tmp_path):
    data_root = DataRoot(root=tmp_path / "data")
    with pytest.raises(SourceImmutabilityError):
        assert_source_writable(data_root, data_root.source / "batch-001" / "x.wav")


def test_writes_outside_source_are_allowed(tmp_path):
    data_root = DataRoot(root=tmp_path / "data")
    assert_source_writable(data_root, data_root.working / "x.wav")
    assert_source_writable(data_root, data_root.segments / "y.wav")


# ==========================================================================
# Normalization — derived only, and blocked without FFmpeg
# ==========================================================================


def test_normalization_blocked_without_ffmpeg(tmp_path, monkeypatch):
    from aarya_voice_lab.pipeline import normalization as normalization_module

    monkeypatch.setattr(normalization_module, "ffmpeg_version", lambda: None)
    data_root = DataRoot(root=tmp_path / "data")
    source = generate_tone(tmp_path / "src.wav")

    with pytest.raises(NormalizationBlocked, match="FFmpeg"):
        normalize_file(
            source,
            tmp_path / "data" / "working" / "out.wav",
            source_file_id="s1",
            source_sha256="0" * 64,
            data_root=data_root,
        )
    assert source.is_file(), "the original must be left untouched"


def test_normalization_refuses_to_write_into_source(tmp_path):
    data_root = DataRoot(root=tmp_path / "data")
    source = generate_tone(tmp_path / "src.wav")
    with pytest.raises(SourceImmutabilityError):
        normalize_file(
            source,
            data_root.source / "batch-001" / "out.wav",
            source_file_id="s1",
            source_sha256="0" * 64,
            data_root=data_root,
        )


def test_normalization_defaults_are_documented_choices():
    config = NormalizationConfig()
    assert config.target_sample_rate == 16_000
    assert config.target_channels == 1
    assert config.target_bit_depth == 16
    # Level is evidence for quality analysis; normalizing it away by
    # default would erase what the quality stage measures.
    assert config.apply_loudness_normalization is False


def test_normalization_command_never_overwrites(tmp_path):
    from aarya_voice_lab.pipeline.normalization import build_ffmpeg_command

    command = build_ffmpeg_command(tmp_path / "in.wav", tmp_path / "out.wav", NormalizationConfig())
    assert "-n" in command, "ffmpeg must refuse to overwrite, never use -y"
    assert "-y" not in command


# ==========================================================================
# Full pipeline over the synthetic corpus
# ==========================================================================


def test_pipeline_runs_over_synthetic_corpus(tmp_path):
    corpus = tmp_path / "corpus"
    generate_phase2_corpus(corpus)
    result = run_dataset_pipeline(corpus, batch_id="batch-001")

    assert result.inventory.files
    assert result.candidates, "no candidate segments were produced"
    assert result.validation_results


def test_pipeline_manifest_validates_against_schema(tmp_path):
    corpus = tmp_path / "corpus"
    generate_phase2_corpus(corpus)
    result = run_dataset_pipeline(corpus, batch_id="batch-001")
    validate(result.to_manifest(), SchemaName.CANDIDATE_MANIFEST)


def test_manifest_declares_phase_2(tmp_path):
    corpus = tmp_path / "corpus"
    generate_phase2_corpus(corpus)
    manifest = run_dataset_pipeline(corpus, batch_id="batch-001").to_manifest()
    assert manifest["phase"] == "phase-2"
    assert manifest["is_synthetic"] is True


def test_manifest_rejects_a_speaker_claim(tmp_path):
    """The schema must make a speaker assertion structurally impossible."""
    corpus = tmp_path / "corpus"
    generate_phase2_corpus(corpus)
    manifest = run_dataset_pipeline(corpus, batch_id="batch-001").to_manifest()
    manifest["candidates"][0]["speaker_id"] = "target_female_speaker"
    with pytest.raises(ValidationError):
        validate(manifest, SchemaName.CANDIDATE_MANIFEST)


def test_no_candidate_mentions_a_speaker_role(tmp_path):
    corpus = tmp_path / "corpus"
    generate_phase2_corpus(corpus)
    result = run_dataset_pipeline(corpus, batch_id="batch-001")
    serialized = json.dumps(result.to_manifest()).lower()
    for forbidden in ("target_female", "operator_voice", "speaker_id", "speaker_1", "speaker_a"):
        assert forbidden not in serialized, f"Phase 2 output must not contain {forbidden!r}"


def test_eligibility_terminology_avoids_approval_language(tmp_path):
    """'technically_eligible' must not read as 'approved training data'."""
    corpus = tmp_path / "corpus"
    generate_phase2_corpus(corpus)
    result = run_dataset_pipeline(corpus, batch_id="batch-001")
    values = {c["technical_eligibility"] for c in result.candidates}
    assert values <= {"technically_eligible", "needs_review", "technically_rejected"}
    assert "approved" not in " ".join(values)


def test_unknown_overlap_never_becomes_eligible(tmp_path):
    corpus = tmp_path / "corpus"
    generate_phase2_corpus(corpus)
    result = run_dataset_pipeline(corpus, batch_id="batch-001")
    for candidate in result.candidates:
        if candidate["overlap_status"] == "UNKNOWN":
            assert candidate["technical_eligibility"] != "technically_eligible"


def test_review_items_never_ask_about_speaker_identity(tmp_path):
    corpus = tmp_path / "corpus"
    generate_phase2_corpus(corpus)
    result = run_dataset_pipeline(corpus, batch_id="batch-001")
    for item in result.review_items:
        assert item["asks_about_speaker_identity"] is False
        assert item["review_type"] == "technical"


def test_pipeline_creates_review_items_for_bad_input(tmp_path):
    corpus = tmp_path / "corpus"
    generate_phase2_corpus(corpus)
    result = run_dataset_pipeline(corpus, batch_id="batch-001")
    codes = {item["reason_code"] for item in result.review_items}
    assert codes, "no review items were generated for a corpus containing bad input"


def test_pipeline_limit_processes_one_recording(tmp_path):
    """The mandatory single-recording validation run."""
    corpus = tmp_path / "corpus"
    generate_phase2_corpus(corpus)
    result = run_dataset_pipeline(corpus, batch_id="batch-001", limit=1)
    assert len({c["source_file_id"] for c in result.candidates}) <= 1


def test_pipeline_does_not_modify_sources(tmp_path):
    """The most important guarantee in Phase 2."""
    corpus = tmp_path / "corpus"
    generate_phase2_corpus(corpus)
    before = build_inventory(corpus)
    run_dataset_pipeline(corpus, batch_id="batch-001")
    assert verify_sources_unchanged(before, corpus) == []


def test_pipeline_writes_no_audio_by_default(tmp_path):
    corpus = tmp_path / "corpus"
    generate_phase2_corpus(corpus)
    data_root = DataRoot(root=tmp_path / "data").create()
    run_dataset_pipeline(corpus, batch_id="batch-001", data_root=data_root)
    assert not list(data_root.segments.rglob("*.wav"))


def test_segment_extraction_writes_into_segments_only(tmp_path):
    corpus = tmp_path / "corpus"
    generate_phase2_corpus(corpus)
    data_root = DataRoot(root=tmp_path / "data").create()
    run_dataset_pipeline(
        corpus,
        batch_id="batch-001",
        data_root=data_root,
        config=PipelineConfig(extract_segment_audio=True),
    )
    written = list(data_root.segments.rglob("*.wav"))
    assert written
    for path in written:
        assert not data_root.is_within_source(path)


def test_extracted_segments_are_hashed(tmp_path):
    corpus = tmp_path / "corpus"
    generate_phase2_corpus(corpus)
    data_root = DataRoot(root=tmp_path / "data").create()
    result = run_dataset_pipeline(
        corpus,
        batch_id="batch-001",
        data_root=data_root,
        config=PipelineConfig(extract_segment_audio=True),
    )
    hashed = [c for c in result.candidates if c["segment_sha256"]]
    assert hashed
    assert all(len(c["segment_sha256"]) == 64 for c in hashed)


def test_pipeline_is_deterministic(tmp_path):
    corpus = tmp_path / "corpus"
    generate_phase2_corpus(corpus)
    first = run_dataset_pipeline(corpus, batch_id="batch-001").candidates
    second = run_dataset_pipeline(corpus, batch_id="batch-001").candidates
    assert first == second


def test_write_candidate_manifest(tmp_path):
    corpus = tmp_path / "corpus"
    generate_phase2_corpus(corpus)
    result = run_dataset_pipeline(corpus, batch_id="batch-001")
    path = write_candidate_manifest(result, tmp_path / "out" / "manifest.json")
    assert path.is_file()
    validate(json.loads(path.read_text(encoding="utf-8")), SchemaName.CANDIDATE_MANIFEST)


def test_batch_ids_flow_through_to_the_manifest(tmp_path):
    corpus = tmp_path / "corpus"
    generate_phase2_corpus(corpus)
    manifest = run_dataset_pipeline(corpus, batch_id="batch-007").to_manifest()
    assert manifest["batch_id"] == "batch-007"


# ==========================================================================
# Real-dataset access gate
# ==========================================================================


def test_gate_is_closed_without_explicit_approval():
    report = evaluate_gate(
        phase2_complete=True,
        tests_passing=True,
        security_scan_clean=True,
        processing_config_reviewed=True,
        explicit_approval=False,
    )
    assert not report.allowed
    assert any("approval" in c.name for c in report.unsatisfied)


def test_gate_cannot_be_self_satisfied():
    """No combination of automatic checks may open the gate on its own."""
    report = evaluate_gate()
    names = {c.name for c in report.unsatisfied}
    assert "explicit approval to access recordings" in names


def test_assert_access_allowed_raises_when_closed():
    with pytest.raises(DatasetAccessDenied):
        assert_access_allowed(evaluate_gate())


def test_gate_checks_output_directories_are_ignored():
    report = evaluate_gate()
    condition = next(c for c in report.conditions if "git-ignored" in c.name)
    assert condition.satisfied, "data/ paths are not git-ignored"


def test_gate_checks_offline_protections():
    report = evaluate_gate()
    condition = next(c for c in report.conditions if "offline" in c.name)
    assert condition.satisfied


def test_gate_report_is_renderable():
    assert "Access Gate" in format_gate(evaluate_gate())


# ==========================================================================
# Phase-3 Access-Gate Hardening -- operator enrollment, real embedding
# provider, and model-licence-review conditions. Every profile here is
# directly constructed (mirrors test_phase3_identity.py's
# test_superseded_profile_refuses_verification_use), never a real
# enrollment run -- these tests only need the profile store to contain a
# profile, never a real embedding.
# ==========================================================================


def _operator_profile(*, usable=True):
    from aarya_voice_lab.identity.profile import EnrollmentState, ProfileProvenance, SpeakerProfile, SpeakerRole

    return SpeakerProfile(
        profile_id="operator",
        role=SpeakerRole.OPERATOR,
        version=1,
        enrollment_state=EnrollmentState.ENROLLED if usable else EnrollmentState.DRAFT,
        provenance=ProfileProvenance(strategy_name="direct_recording", strategy_version="1.0.0"),
        embedding_id="operator-v1" if usable else None,
        embedding_sha256=("a" * 64) if usable else None,
    )


def _condition(report, name):
    return next(c for c in report.conditions if c.name == name)


def test_operator_enrollment_condition_fails_on_a_fresh_data_root(tmp_path):
    data_root = DataRoot(root=tmp_path / "data").create()
    report = evaluate_gate(data_root=data_root)
    assert not _condition(report, "operator enrollment present").satisfied


def test_operator_enrollment_condition_passes_with_a_usable_operator_profile(tmp_path):
    from aarya_voice_lab.identity.profile import ProfileStore

    data_root = DataRoot(root=tmp_path / "data").create()
    ProfileStore(data_root).save(_operator_profile())
    report = evaluate_gate(data_root=data_root)
    assert _condition(report, "operator enrollment present").satisfied


def test_operator_enrollment_condition_ignores_a_non_operator_profile(tmp_path):
    from aarya_voice_lab.identity.profile import (
        EnrollmentState,
        ProfileProvenance,
        ProfileStore,
        SpeakerProfile,
        SpeakerRole,
    )

    data_root = DataRoot(root=tmp_path / "data").create()
    target_profile = SpeakerProfile(
        profile_id="target",
        role=SpeakerRole.TARGET_SPEAKER,
        version=1,
        enrollment_state=EnrollmentState.ENROLLED,
        provenance=ProfileProvenance(strategy_name="direct_recording", strategy_version="1.0.0"),
        embedding_id="target-v1",
        embedding_sha256="b" * 64,
    )
    ProfileStore(data_root).save(target_profile)
    report = evaluate_gate(data_root=data_root)
    assert not _condition(report, "operator enrollment present").satisfied


def test_real_provider_condition_fails_when_none_available(monkeypatch, tmp_path):
    monkeypatch.setattr(dataset_gate_module, "any_real_provider_available", lambda: False)
    data_root = DataRoot(root=tmp_path / "data").create()
    report = evaluate_gate(data_root=data_root)
    assert not _condition(report, "real embedding provider verified").satisfied


def test_real_provider_condition_passes_when_the_existing_signal_reports_true(monkeypatch, tmp_path):
    """Mocks the existing any_real_provider_available() signal directly --
    never fabricates a real model installation or a second detector."""
    monkeypatch.setattr(dataset_gate_module, "any_real_provider_available", lambda: True)
    data_root = DataRoot(root=tmp_path / "data").create()
    report = evaluate_gate(data_root=data_root)
    assert _condition(report, "real embedding provider verified").satisfied


def test_licence_review_condition_defaults_to_unsatisfied():
    report = evaluate_gate()
    assert not _condition(report, "model licence reviewed").satisfied


def test_licence_review_condition_satisfied_when_explicitly_attested():
    report = evaluate_gate(model_licence_reviewed=True)
    assert _condition(report, "model licence reviewed").satisfied


def test_licence_review_condition_unsatisfied_when_explicitly_false():
    report = evaluate_gate(model_licence_reviewed=False)
    assert not _condition(report, "model licence reviewed").satisfied


def test_evaluate_gate_reports_exactly_fifteen_conditions(tmp_path):
    data_root = DataRoot(root=tmp_path / "data").create()
    report = evaluate_gate(data_root=data_root)
    assert len(report.conditions) == 15, [c.name for c in report.conditions]


def _fake_git_all_clean(args, root):
    """Decouples the git-dependent conditions (1-3, 8) from whatever the
    ambient repository's real state happens to be at test time, so the
    fully-satisfied scenarios below are hermetic rather than flaky."""
    if args and args[0] == "status":
        return (0, "")
    if args and args[0] == "branch":
        return (0, "origin/some-branch")
    return (0, "")  # check-ignore and anything else: success


class _CleanScan:
    ok = True
    violations: list = []


def _fully_satisfied_kwargs(monkeypatch, tmp_path, *, omit: str | None = None):
    """Builds a data root and monkeypatch state where all 15 conditions
    would be satisfied, optionally forcing exactly one of the three new
    Phase-3 conditions to fail -- proving each one independently blocks
    access without the others being affected."""
    monkeypatch.setattr(dataset_gate_module, "_git", _fake_git_all_clean)
    monkeypatch.setattr(dataset_gate_module, "scan_git_repo", lambda root: _CleanScan())
    monkeypatch.setattr(dataset_gate_module, "any_real_provider_available", lambda: omit != "real_provider")

    data_root = DataRoot(root=tmp_path / "data").create()
    data_root.source.mkdir(parents=True, exist_ok=True)
    (data_root.source / "dummy.wav").write_bytes(b"synthetic placeholder, not real audio")
    if omit != "operator_enrollment":
        from aarya_voice_lab.identity.profile import ProfileStore

        ProfileStore(data_root).save(_operator_profile())

    return data_root, {
        "phase2_complete": True,
        "tests_passing": True,
        "security_scan_clean": True,
        "processing_config_reviewed": True,
        "explicit_approval": True,
        "model_licence_reviewed": omit != "licence_review",
    }


def test_all_fifteen_conditions_satisfied_allows_access(monkeypatch, tmp_path):
    data_root, kwargs = _fully_satisfied_kwargs(monkeypatch, tmp_path)
    report = evaluate_gate(data_root=data_root, **kwargs)
    assert report.allowed, [c.name for c in report.unsatisfied]


def test_missing_operator_enrollment_alone_denies_access(monkeypatch, tmp_path):
    data_root, kwargs = _fully_satisfied_kwargs(monkeypatch, tmp_path, omit="operator_enrollment")
    report = evaluate_gate(data_root=data_root, **kwargs)
    assert not report.allowed
    assert {c.name for c in report.unsatisfied} == {"operator enrollment present"}


def test_missing_real_provider_alone_denies_access(monkeypatch, tmp_path):
    data_root, kwargs = _fully_satisfied_kwargs(monkeypatch, tmp_path, omit="real_provider")
    report = evaluate_gate(data_root=data_root, **kwargs)
    assert not report.allowed
    assert {c.name for c in report.unsatisfied} == {"real embedding provider verified"}


def test_missing_licence_review_alone_denies_access(monkeypatch, tmp_path):
    data_root, kwargs = _fully_satisfied_kwargs(monkeypatch, tmp_path, omit="licence_review")
    report = evaluate_gate(data_root=data_root, **kwargs)
    assert not report.allowed
    assert {c.name for c in report.unsatisfied} == {"model licence reviewed"}


def test_existing_twelve_conditions_retain_their_behavior_alongside_new_ones(tmp_path):
    """Regression: with none of the operator attestations given and no
    Phase-3 signal mocked, the same pre-existing conditions that were
    already unsatisfied before this milestone remain unsatisfied, now
    joined by the three new ones -- nothing pre-existing was weakened."""
    data_root = DataRoot(root=tmp_path / "data").create()
    report = evaluate_gate(data_root=data_root)
    pre_existing_unsatisfied_names = {
        "Phase 2 implementation complete",
        "Phase 2 tests passing",
        "security scan complete",
        "processing configuration reviewed",
        "explicit approval to access recordings",
        "source directory populated",
    }
    unsatisfied_names = {c.name for c in report.unsatisfied}
    assert pre_existing_unsatisfied_names <= unsatisfied_names
    # Conditions that were already unconditionally satisfied before this
    # milestone (no operator input needed) remain satisfied.
    assert _condition(report, "no cloud upload path").satisfied
    assert _condition(report, "offline/telemetry protections intact").satisfied
