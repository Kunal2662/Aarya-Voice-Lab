"""Tests for VL-D3's Dataset Review layer: candidate_review, feedback,
calibration_prep, quality_summary, plus the new synthetic noisy-speech
fixture against the existing (Phase 2) quality/VAD/overlap modules.

Every fixture is synthetic; nothing here reads or references source/.
"""

from __future__ import annotations

import json

import pytest

from aarya_voice_lab.audio.analysis import measure
from aarya_voice_lab.audio.probe import read_wav_mono_samples
from aarya_voice_lab.audio.vad import VadConfig, detect_regions
from aarya_voice_lab.pipeline.calibration_prep import summarize_calibration_inputs
from aarya_voice_lab.pipeline.candidate_review import (
    CandidateReviewDecision,
    CandidateReviewLog,
    CandidateReviewReason,
    CandidateReviewRecord,
    current_decision,
    history,
    record_review_decision,
    review_disagreement_count,
)
from aarya_voice_lab.pipeline.feedback import (
    FeedbackLog,
    FeedbackRecord,
    FeedbackType,
    counts_by_type,
    feedback_for,
    record_feedback,
)
from aarya_voice_lab.pipeline.overlap import OverlapStatus, assess_overlap
from aarya_voice_lab.pipeline.quality import QualityDecision, assess_quality
from aarya_voice_lab.pipeline.quality_summary import summarize_quality
from aarya_voice_lab.schemas.base import SchemaName, validate
from aarya_voice_lab.testing.synthetic_audio import (
    generate_clipped,
    generate_conversation,
    generate_narrowband,
    generate_noisy_speech,
    generate_silence,
    generate_speech_like,
)


def _measure_file(path):
    samples, rate = read_wav_mono_samples(path)
    return measure(samples, rate), samples, rate


# Short aliases used only to keep review-decision test lines under the
# project's line-length limit; the full names are used everywhere else.
_Decision = CandidateReviewDecision
_Reason = CandidateReviewReason


# ---------------------------------------------------------------------------
# New fixture (generate_noisy_speech) against the existing quality/VAD stack.
# ---------------------------------------------------------------------------


def test_noisy_speech_is_flagged_low_or_moderate_snr_not_rejected(tmp_path):
    path = generate_noisy_speech(tmp_path / "noisy.wav", duration_seconds=3.0)
    measurements, samples, rate = _measure_file(path)
    vad = detect_regions(samples, rate)
    assessment = assess_quality("src-noisy", measurements, vad)

    assert measurements.estimated_snr_db is not None
    # Noisy is a REVIEW/WARNING signal, never an automatic FAIL by itself.
    assert assessment.decision in (QualityDecision.REVIEW, QualityDecision.WARNING, QualityDecision.PASS)
    codes = {f.code for f in assessment.findings}
    if assessment.decision in (QualityDecision.REVIEW, QualityDecision.WARNING):
        assert codes & {"low_snr", "moderate_snr"}


def test_narrowband_is_a_characteristic_never_a_defect(tmp_path):
    path = generate_narrowband(tmp_path / "narrowband.wav", duration_seconds=2.0)
    measurements, samples, rate = _measure_file(path)
    assessment = assess_quality("src-narrowband", measurements)
    assert any("narrowband" in c for c in assessment.characteristics)
    # No finding code should exist purely because of sample rate.
    assert "narrowband" not in {f.code for f in assessment.findings}


def test_heavily_clipped_audio_is_flagged(tmp_path):
    path = generate_clipped(tmp_path / "clipped.wav", duration_seconds=1.0)
    measurements, _, _ = _measure_file(path)
    assessment = assess_quality("src-clipped", measurements)
    assert measurements.clipping_ratio > 0
    assert assessment.decision in (QualityDecision.WARNING, QualityDecision.FAIL)


def test_silence_heavy_recording_is_flagged_review_or_fail(tmp_path):
    path = generate_silence(tmp_path / "silence.wav", duration_seconds=3.0)
    measurements, samples, rate = _measure_file(path)
    vad = detect_regions(samples, rate)
    assessment = assess_quality("src-silence", measurements, vad)
    assert assessment.decision in (QualityDecision.REVIEW, QualityDecision.FAIL)


def test_clean_speech_passes_with_no_findings(tmp_path):
    path = generate_speech_like(tmp_path / "clean.wav", duration_seconds=2.0, amplitude=0.5)
    measurements, samples, rate = _measure_file(path)
    vad = detect_regions(samples, rate)
    assessment = assess_quality("src-clean", measurements, vad)
    assert assessment.decision == QualityDecision.PASS
    assert assessment.findings == []


def test_conversation_overlap_segment_runs_through_the_honest_candidate_vocabulary(tmp_path):
    """The energy-ZCR heuristic is a deliberately weak indicator (see
    pipeline/overlap.py's own docstring) — even the existing Phase 2 test
    suite never asserts it reliably fires POSSIBLE/DETECTED on a
    synthetic mix, only that undecidable stays UNKNOWN rather than being
    assumed clear. This test matches that: it exercises VL-D3's overlap
    fixture end-to-end and asserts the result is always one of the four
    honest statuses, with evidence attached — never a status outside the
    closed vocabulary, and never a claim of certainty."""
    path, turns = generate_conversation(tmp_path / "conversation.wav", include_overlap=True)
    samples, rate = read_wav_mono_samples(path)
    overlap_turn = next(t for t in turns if t.overlapping)
    start_index = int(overlap_turn.start * rate)
    end_index = int(overlap_turn.end * rate)
    segment_samples = samples[start_index:end_index]
    assessment = assess_overlap("seg-overlap", segment_samples, rate)
    assert assessment.status in set(OverlapStatus)
    assert assessment.evidence
    assert "not a speaker count" in (assessment.note or "") or "not a probability" in (assessment.note or "")


def test_non_overlapping_speech_is_not_flagged_as_overlap(tmp_path):
    path = generate_speech_like(tmp_path / "solo.wav", duration_seconds=2.0)
    samples, rate = read_wav_mono_samples(path)
    assessment = assess_overlap("seg-solo", samples, rate)
    assert assessment.status in (OverlapStatus.NO_OVERLAP_DETECTED, OverlapStatus.UNKNOWN)


# ---------------------------------------------------------------------------
# Candidate review: technical-only, append-only history, no speaker leakage.
# ---------------------------------------------------------------------------


def _record(review_id, decision, reason, **overrides):
    fields = dict(
        review_id=review_id,
        segment_id="seg-1",
        source_file_id="src-abc",
        batch_id="batch-001",
        reviewer="operator",
        decision=decision,
        reason_code=reason,
        source_sha256="a" * 64,
        config_hash="cfg-1",
    )
    fields.update(overrides)
    return CandidateReviewRecord(**fields)


def test_candidate_review_schema_has_no_speaker_related_property():
    import pathlib

    schema = json.loads(
        (pathlib.Path(__file__).resolve().parent.parent / "schemas" / "candidate_review.schema.json").read_text()
    )
    property_names = " ".join(schema["properties"].keys()).lower()
    for forbidden in ("speaker", "target_speaker", "is_aarya", "identity"):
        assert forbidden not in property_names
    assert schema["properties"]["review_type"]["const"] == "technical"


def test_record_review_decision_validates_against_schema(tmp_path):
    log = CandidateReviewLog(tmp_path / "candidate_review.jsonl")
    payload = record_review_decision(log, _record("rev-1", _Decision.NEEDS_REVIEW, _Reason.QUALITY_ISSUE))
    validate(payload, SchemaName.CANDIDATE_REVIEW)
    assert payload["review_type"] == "technical"
    assert payload["stage"] == "candidate_review"


def test_review_history_is_never_overwritten_only_appended(tmp_path):
    log = CandidateReviewLog(tmp_path / "candidate_review.jsonl")
    record_review_decision(log, _record("rev-1", _Decision.NEEDS_REVIEW, _Reason.QUALITY_ISSUE))
    record_review_decision(
        log,
        _record("rev-2", _Decision.ACCEPTED, _Reason.TECHNICAL_USABILITY, supersedes="rev-1"),
    )

    past = history(log, "seg-1")
    assert [r["review_id"] for r in past] == ["rev-1", "rev-2"]
    assert past[0]["decision"] == "NEEDS_REVIEW"  # untouched by the later record
    assert current_decision(log, "seg-1")["decision"] == "ACCEPTED"
    assert current_decision(log, "seg-1")["supersedes"] == "rev-1"


def test_current_decision_is_none_for_an_unreviewed_segment(tmp_path):
    log = CandidateReviewLog(tmp_path / "candidate_review.jsonl")
    assert current_decision(log, "seg-never-reviewed") is None
    assert history(log, "seg-never-reviewed") == []


def test_review_disagreement_count_only_counts_segments_with_conflicting_decisions(tmp_path):
    log = CandidateReviewLog(tmp_path / "candidate_review.jsonl")
    record_review_decision(log, _record("rev-1", _Decision.NEEDS_REVIEW, _Reason.QUALITY_ISSUE))
    record_review_decision(
        log,
        _record("rev-2", _Decision.ACCEPTED, _Reason.TECHNICAL_USABILITY, supersedes="rev-1"),
    )
    record_review_decision(
        log,
        _record("rev-3", _Decision.ACCEPTED, _Reason.TECHNICAL_USABILITY, segment_id="seg-2"),
    )
    assert review_disagreement_count(log) == 1  # only seg-1 has two different decisions


def test_review_id_is_used_as_identity_not_timestamp(tmp_path):
    log = CandidateReviewLog(tmp_path / "candidate_review.jsonl")
    record_review_decision(log, _record("rev-1", _Decision.ACCEPTED, _Reason.TECHNICAL_USABILITY))
    with pytest.raises(ValueError):
        # Same review_id twice must be refused -- identity is the id, not a timestamp.
        record_review_decision(log, _record("rev-1", _Decision.REJECTED, _Reason.QUALITY_ISSUE))


def test_review_provenance_persists_relative_and_hash_fields_only(tmp_path):
    log = CandidateReviewLog(tmp_path / "candidate_review.jsonl")
    payload = record_review_decision(log, _record("rev-1", _Decision.ACCEPTED, _Reason.TECHNICAL_USABILITY))
    assert payload["source_sha256"] == "a" * 64
    assert payload["config_hash"] == "cfg-1"
    assert "tool_version" in payload and "stage_version" in payload
    serialised = json.dumps(payload)
    assert str(tmp_path) not in serialised


# ---------------------------------------------------------------------------
# Feedback.
# ---------------------------------------------------------------------------


def test_feedback_is_recorded_and_retrievable_by_target(tmp_path):
    log = FeedbackLog(tmp_path / "feedback.jsonl")
    record_feedback(
        log,
        FeedbackRecord(
            feedback_id="fb-1",
            feedback_type=FeedbackType.SEGMENT_FEEDBACK,
            target_id="seg-1",
            reviewer="operator",
            comment="segment boundary incorrect",
            attributes={"issue": "boundary"},
        ),
    )
    record_feedback(
        log,
        FeedbackRecord(
            feedback_id="fb-2", feedback_type=FeedbackType.QUALITY_FEEDBACK, target_id="seg-2", reviewer="operator"
        ),
    )
    assert len(feedback_for(log, "seg-1")) == 1
    counts = counts_by_type(log)
    assert counts["SEGMENT_FEEDBACK"] == 1
    assert counts["QUALITY_FEEDBACK"] == 1
    assert counts["CANDIDATE_FEEDBACK"] == 0


def test_feedback_schema_validates(tmp_path):
    log = FeedbackLog(tmp_path / "feedback.jsonl")
    payload = record_feedback(
        log,
        FeedbackRecord(
            feedback_id="fb-1", feedback_type=FeedbackType.PLAYBACK_FEEDBACK, target_id="rec-1", reviewer="operator"
        ),
    )
    validate(payload, SchemaName.FEEDBACK)


# ---------------------------------------------------------------------------
# Calibration preparation: real counts, never a fabricated score.
# ---------------------------------------------------------------------------


def test_calibration_summary_is_always_uncalibrated_with_real_counts(tmp_path):
    from aarya_voice_lab.identity.calibration import CalibrationState

    feedback_log = FeedbackLog(tmp_path / "feedback.jsonl")
    record_feedback(
        feedback_log,
        FeedbackRecord(
            feedback_id="fb-1", feedback_type=FeedbackType.QUALITY_FEEDBACK, target_id="seg-1", reviewer="operator"
        ),
    )
    review_log = CandidateReviewLog(tmp_path / "candidate_review.jsonl")
    record_review_decision(review_log, _record("rev-1", _Decision.NEEDS_REVIEW, _Reason.QUALITY_ISSUE))
    record_review_decision(
        review_log,
        _record("rev-2", _Decision.ACCEPTED, _Reason.TECHNICAL_USABILITY, supersedes="rev-1"),
    )

    summary = summarize_calibration_inputs(feedback_log=feedback_log, review_log=review_log)
    assert summary.calibration_state == CalibrationState.UNCALIBRATED
    assert summary.quality_feedback_count == 1
    assert summary.review_disagreement_count == 1
    assert "no ai calibration engine" in summary.note.lower()


def test_calibration_summary_handles_no_data_honestly():
    summary = summarize_calibration_inputs()
    assert summary.quality_feedback_count == 0
    assert summary.review_disagreement_count == 0
    assert summary.total_recordings == 0


# ---------------------------------------------------------------------------
# Quality summary: pure aggregation, never a new measurement.
# ---------------------------------------------------------------------------


def test_quality_summary_computes_real_distributions(tmp_path):
    clean = generate_speech_like(tmp_path / "clean.wav", duration_seconds=2.0, amplitude=0.5)
    narrowband = generate_narrowband(tmp_path / "narrowband.wav", duration_seconds=1.0)

    assessments = []
    for label, path in [("clean", clean), ("narrowband", narrowband)]:
        measurements, samples, rate = _measure_file(path)
        assessments.append(assess_quality(f"src-{label}", measurements))

    summary = summarize_quality(assessments)
    assert summary.recording_count == 2
    assert summary.average_duration_seconds is not None
    assert summary.median_duration_seconds is not None
    assert sum(summary.decision_distribution.values()) == 2
    assert summary.narrowband_count == 1


def test_quality_summary_of_empty_list_is_honestly_empty():
    summary = summarize_quality([])
    assert summary.recording_count == 0
    assert summary.average_duration_seconds is None
    assert summary.median_duration_seconds is None
    assert summary.decision_distribution == {}


def test_quality_summary_channel_distribution_only_from_supplied_data(tmp_path):
    path = generate_speech_like(tmp_path / "a.wav", duration_seconds=1.0)
    measurements, _, _ = _measure_file(path)
    assessment = assess_quality("src-a", measurements)

    without_channels = summarize_quality([assessment])
    assert without_channels.channel_distribution == {}

    with_channels = summarize_quality([assessment], channels_by_source_file_id={"src-a": 1})
    assert with_channels.channel_distribution == {"1": 1}


def test_quality_summary_duration_snr_and_ratio_distributions_are_bucketed_from_real_values(tmp_path):
    clean = generate_speech_like(tmp_path / "clean.wav", duration_seconds=2.0, amplitude=0.5)
    measurements, samples, sample_rate = _measure_file(clean)
    vad = detect_regions(samples, sample_rate)
    assessment = assess_quality("src-clean", measurements, vad)

    summary = summarize_quality([assessment])
    assert sum(summary.duration_distribution.values()) == 1
    assert sum(summary.snr_distribution.values()) == 1
    assert sum(summary.speech_ratio_distribution.values()) == 1
    assert sum(summary.silence_ratio_distribution.values()) == 1
    # A short synthetic tone always lands in the shortest bucket.
    assert summary.duration_distribution == {"<30s": 1}


def test_quality_summary_ratio_bucket_is_not_available_without_vad():
    from aarya_voice_lab.pipeline.quality import QualityAssessment

    assessment = QualityAssessment(
        source_file_id="src-no-vad",
        decision=QualityDecision.PASS,
        measurements={"duration_seconds": 5.0, "sample_rate": 16000, "silent_frame_ratio": 0.1},
        speech={},
    )
    summary = summarize_quality([assessment])
    assert summary.speech_ratio_distribution == {"not_available": 1}


def test_quality_summary_overlap_candidate_count_is_none_when_not_supplied():
    from aarya_voice_lab.pipeline.quality import QualityAssessment

    assessment = QualityAssessment(source_file_id="src-a", decision=QualityDecision.PASS)
    summary = summarize_quality([assessment])
    assert summary.overlap_candidate_count is None


def test_quality_summary_overlap_candidate_count_counts_only_true_candidates():
    from aarya_voice_lab.pipeline.quality import QualityAssessment

    assessment = QualityAssessment(source_file_id="src-a", decision=QualityDecision.PASS)
    summary = summarize_quality(
        [assessment],
        overlap_statuses=[
            OverlapStatus.NO_OVERLAP_DETECTED.value,
            OverlapStatus.POSSIBLE_OVERLAP.value,
            OverlapStatus.OVERLAP_DETECTED.value,
            OverlapStatus.UNKNOWN.value,
        ],
    )
    assert summary.overlap_candidate_count == 2


# ---------------------------------------------------------------------------
# VAD sanity on new fixtures (speech/silence structure).
# ---------------------------------------------------------------------------


def test_vad_speech_ratio_reflects_actual_signal_content(tmp_path):
    silent_path = generate_silence(tmp_path / "silent.wav", duration_seconds=2.0)
    speech_path = generate_speech_like(tmp_path / "speech.wav", duration_seconds=2.0, amplitude=0.5)

    silent_samples, rate = read_wav_mono_samples(silent_path)
    speech_samples, _ = read_wav_mono_samples(speech_path)

    silent_vad = detect_regions(silent_samples, rate, config=VadConfig())
    speech_vad = detect_regions(speech_samples, rate, config=VadConfig())

    assert silent_vad.speech_ratio < speech_vad.speech_ratio
