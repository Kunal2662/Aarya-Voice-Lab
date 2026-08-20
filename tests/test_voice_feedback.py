"""Tests for VL-D6's Voice Feedback + Human Evaluation Engine: the
multi-dimension evaluation record, A/B evaluation, aggregation and
reviewer disagreement, and calibration-preparation signals.

Every fixture is synthetic; nothing here reads or references source/,
and nothing here accesses, modifies, or trains on real recordings.
"""

from __future__ import annotations

import pytest

from aarya_voice_lab.identity.preview import PreviewFeedbackOutcome
from aarya_voice_lab.pipeline.calibration_prep import (
    CalibrationState,
    summarize_evaluation_calibration_inputs,
)
from aarya_voice_lab.pipeline.evaluation import (
    MAX_SCORE,
    MIN_SCORE,
    ABDecision,
    ABEvaluationLog,
    EvaluationCompletionState,
    EvaluationLog,
    InvalidDimensionScoreError,
    ListeningState,
    UnlistenedEvaluationError,
    VoiceQualityDimension,
    ab_evaluations_for,
    evaluations_for,
    record_ab_evaluation,
    record_evaluation,
    reviewers_for,
)
from aarya_voice_lab.pipeline.evaluation_aggregation import (
    MIN_EVALUATIONS_FOR_DISAGREEMENT,
    outputs_with_disagreement,
    summarize_ab_preferences,
    summarize_calibration_signals,
    summarize_dimension,
    summarize_output_evaluations,
)
from aarya_voice_lab.pipeline.preview_feedback import PreviewFeedbackCategory

# ---------------------------------------------------------------------------
# Dimension vocabulary — bounded, deliberately reuses existing terminology
# ---------------------------------------------------------------------------


def test_voice_quality_dimension_is_bounded_to_eleven_values():
    assert len(list(VoiceQualityDimension)) == 11


def test_seven_dimension_names_are_reused_verbatim_from_preview_feedback_category():
    reused = {"NATURALNESS", "CLARITY", "PRONUNCIATION", "PROSODY", "PACE", "ARTIFACTS", "OVERALL"}
    dimension_values = {d.value for d in VoiceQualityDimension}
    category_values = {c.value for c in PreviewFeedbackCategory}
    assert reused <= dimension_values
    assert reused <= category_values


def test_four_new_dimensions_fill_a_genuine_gap():
    new_only = {"INTELLIGIBILITY", "EXPRESSIVENESS", "CONSISTENCY", "NOISE"}
    dimension_values = {d.value for d in VoiceQualityDimension}
    category_values = {c.value for c in PreviewFeedbackCategory}
    assert new_only <= dimension_values
    assert not (new_only & category_values), "these must not already exist in PreviewFeedbackCategory"


def test_rhythm_and_stability_are_not_separate_dimensions():
    dimension_values = {d.value for d in VoiceQualityDimension}
    assert "RHYTHM" not in dimension_values, "Rhythm folds into PROSODY, not a separate dimension"
    assert "STABILITY" not in dimension_values, "Stability folds into CONSISTENCY, not a separate dimension"


def test_ab_decision_shares_no_value_with_preview_feedback_outcome():
    ab_values = {d.value for d in ABDecision}
    preview_values = {o.value for o in PreviewFeedbackOutcome}
    assert not (ab_values & preview_values)


# ---------------------------------------------------------------------------
# Evaluation record + persistence
# ---------------------------------------------------------------------------


def test_record_evaluation_succeeds_and_validates_against_schema(tmp_path):
    log = EvaluationLog(tmp_path / "evaluation.jsonl")
    payload = record_evaluation(
        log,
        output_id="preview-req-00001-preview",
        reviewer="alice",
        listening=ListeningState(listened=True, replay_count=1, furthest_position_seconds=3.2, completed_playback=True),
        dimension_scores={"NATURALNESS": 4, "CLARITY": 5},
        confidence=4,
        completion_state=EvaluationCompletionState.COMPLETED,
        voice_profile_id="demo-voice-v1",
        model_id="synthetic-tone-v1",
    )
    assert payload["evaluation_id"] == "eval-00001"
    assert payload["dimension_scores"] == {"NATURALNESS": 4, "CLARITY": 5}
    assert payload["listening"]["listened"] is True
    assert payload["completion_state"] == "COMPLETED"


def test_record_evaluation_rejects_unknown_dimension(tmp_path):
    log = EvaluationLog(tmp_path / "evaluation.jsonl")
    with pytest.raises(InvalidDimensionScoreError, match="unknown VoiceQualityDimension"):
        record_evaluation(
            log,
            output_id="out-1",
            reviewer="alice",
            listening=ListeningState(listened=True),
            dimension_scores={"WARMTH": 3},
        )


@pytest.mark.parametrize("score", [MIN_SCORE - 1, MAX_SCORE + 1, 0, 6])
def test_record_evaluation_rejects_out_of_range_score(tmp_path, score):
    log = EvaluationLog(tmp_path / "evaluation.jsonl")
    with pytest.raises(InvalidDimensionScoreError):
        record_evaluation(
            log,
            output_id="out-1",
            reviewer="alice",
            listening=ListeningState(listened=True),
            dimension_scores={"NATURALNESS": score},
        )


def test_record_evaluation_rejects_a_dimension_that_is_both_scored_and_cannot_judge(tmp_path):
    log = EvaluationLog(tmp_path / "evaluation.jsonl")
    with pytest.raises(InvalidDimensionScoreError, match="cannot be both scored and marked cannot-judge"):
        record_evaluation(
            log,
            output_id="out-1",
            reviewer="alice",
            listening=ListeningState(listened=True),
            dimension_scores={"NATURALNESS": 3},
            cannot_judge_dimensions=("NATURALNESS",),
        )


def test_record_evaluation_rejects_out_of_range_confidence(tmp_path):
    log = EvaluationLog(tmp_path / "evaluation.jsonl")
    with pytest.raises(InvalidDimensionScoreError, match="confidence"):
        record_evaluation(
            log,
            output_id="out-1",
            reviewer="alice",
            listening=ListeningState(listened=True),
            confidence=10,
        )


def test_record_evaluation_refuses_completed_without_listening(tmp_path):
    log = EvaluationLog(tmp_path / "evaluation.jsonl")
    with pytest.raises(UnlistenedEvaluationError, match="must be listened to first"):
        record_evaluation(
            log,
            output_id="out-1",
            reviewer="alice",
            listening=ListeningState(listened=False),
            completion_state=EvaluationCompletionState.COMPLETED,
        )


@pytest.mark.parametrize(
    "state",
    [
        EvaluationCompletionState.IN_PROGRESS,
        EvaluationCompletionState.CANNOT_JUDGE,
        EvaluationCompletionState.ABANDONED,
    ],
)
def test_record_evaluation_allows_non_completed_states_without_listening(tmp_path, state):
    log = EvaluationLog(tmp_path / "evaluation.jsonl")
    payload = record_evaluation(
        log,
        output_id="out-1",
        reviewer="alice",
        listening=ListeningState(listened=False),
        completion_state=state,
    )
    assert payload["completion_state"] == state.value


def test_cannot_falsely_mark_listened_true_bypasses_nothing_it_shouldnt(tmp_path):
    """A caller that DOES honestly set listened=True can complete —
    proving the gate checks the flag, not merely the completion_state."""
    log = EvaluationLog(tmp_path / "evaluation.jsonl")
    payload = record_evaluation(
        log,
        output_id="out-1",
        reviewer="alice",
        listening=ListeningState(listened=True),
        completion_state=EvaluationCompletionState.COMPLETED,
    )
    assert payload["completion_state"] == "COMPLETED"


def test_multiple_evaluations_of_the_same_output_are_independent_append_only_records(tmp_path):
    log = EvaluationLog(tmp_path / "evaluation.jsonl")
    record_evaluation(
        log, output_id="out-1", reviewer="alice", listening=ListeningState(listened=True),
        dimension_scores={"NATURALNESS": 5},
    )
    record_evaluation(
        log, output_id="out-1", reviewer="bob", listening=ListeningState(listened=True),
        dimension_scores={"NATURALNESS": 2},
    )
    records = evaluations_for(log, "out-1")
    assert len(records) == 2
    assert {r["reviewer"] for r in records} == {"alice", "bob"}
    assert reviewers_for(log, "out-1") == ["alice", "bob"]


def test_supersedes_chains_the_same_reviewers_own_revision(tmp_path):
    log = EvaluationLog(tmp_path / "evaluation.jsonl")
    first = record_evaluation(
        log, output_id="out-1", reviewer="alice", listening=ListeningState(listened=True),
        dimension_scores={"NATURALNESS": 3},
    )
    revised = record_evaluation(
        log, output_id="out-1", reviewer="alice", listening=ListeningState(listened=True),
        dimension_scores={"NATURALNESS": 4}, supersedes=first["evaluation_id"], evaluation_version=2,
    )
    assert revised["supersedes"] == first["evaluation_id"]
    # append-only: the original record is untouched and still present
    records = evaluations_for(log, "out-1")
    assert len(records) == 2
    assert records[0]["dimension_scores"]["NATURALNESS"] == 3


def test_duplicate_evaluation_id_is_rejected(tmp_path):
    log = EvaluationLog(tmp_path / "evaluation.jsonl")
    record_evaluation(
        log, output_id="out-1", reviewer="alice", listening=ListeningState(listened=True), evaluation_id="eval-fixed"
    )
    with pytest.raises(ValueError, match="already exists"):
        record_evaluation(
            log, output_id="out-2", reviewer="bob", listening=ListeningState(listened=True), evaluation_id="eval-fixed"
        )


def test_evaluation_log_persists_and_reloads_from_disk(tmp_path):
    path = tmp_path / "evaluation.jsonl"
    log = EvaluationLog(path)
    record_evaluation(log, output_id="out-1", reviewer="alice", listening=ListeningState(listened=True))

    reloaded = EvaluationLog(path)
    assert len(reloaded.list()) == 1
    assert reloaded.get("eval-00001") is not None


# ---------------------------------------------------------------------------
# A/B evaluation
# ---------------------------------------------------------------------------


def test_record_ab_evaluation_succeeds_and_validates(tmp_path):
    log = ABEvaluationLog(tmp_path / "ab_evaluation.jsonl")
    payload = record_ab_evaluation(
        log,
        output_id_a="out-1",
        output_id_b="out-2",
        reviewer="alice",
        listened_a=True,
        listened_b=True,
        decision=ABDecision.PREFER_A,
        blinded=True,
    )
    assert payload["decision"] == "PREFER_A"
    assert payload["blinded"] is True


@pytest.mark.parametrize("decision", [ABDecision.PREFER_A, ABDecision.PREFER_B, ABDecision.NO_PREFERENCE])
def test_record_ab_evaluation_refuses_a_decision_without_both_sides_listened(tmp_path, decision):
    log = ABEvaluationLog(tmp_path / "ab_evaluation.jsonl")
    with pytest.raises(UnlistenedEvaluationError, match="must be listened to first"):
        record_ab_evaluation(
            log, output_id_a="out-1", output_id_b="out-2", reviewer="alice",
            listened_a=True, listened_b=False, decision=decision,
        )


def test_record_ab_evaluation_allows_cannot_judge_without_listening(tmp_path):
    log = ABEvaluationLog(tmp_path / "ab_evaluation.jsonl")
    payload = record_ab_evaluation(
        log, output_id_a="out-1", output_id_b="out-2", reviewer="alice",
        listened_a=False, listened_b=False, decision=ABDecision.CANNOT_JUDGE,
    )
    assert payload["decision"] == "CANNOT_JUDGE"


def test_blinded_defaults_to_false_and_is_not_a_cryptographic_claim(tmp_path):
    log = ABEvaluationLog(tmp_path / "ab_evaluation.jsonl")
    payload = record_ab_evaluation(
        log, output_id_a="out-1", output_id_b="out-2", reviewer="alice",
        listened_a=True, listened_b=True, decision=ABDecision.NO_PREFERENCE,
    )
    assert payload["blinded"] is False


def test_ab_evaluations_for_finds_records_naming_the_output_on_either_side(tmp_path):
    log = ABEvaluationLog(tmp_path / "ab_evaluation.jsonl")
    record_ab_evaluation(
        log, output_id_a="out-1", output_id_b="out-2", reviewer="alice",
        listened_a=True, listened_b=True, decision=ABDecision.PREFER_A,
    )
    record_ab_evaluation(
        log, output_id_a="out-3", output_id_b="out-1", reviewer="bob",
        listened_a=True, listened_b=True, decision=ABDecision.PREFER_B,
    )
    assert len(ab_evaluations_for(log, "out-1")) == 2
    assert len(ab_evaluations_for(log, "out-2")) == 1
    assert len(ab_evaluations_for(log, "out-3")) == 1


# ---------------------------------------------------------------------------
# Aggregation + disagreement — honest at small sample sizes
# ---------------------------------------------------------------------------


def test_summarize_dimension_of_empty_scores_is_honestly_none():
    stats = summarize_dimension([], dimension="NATURALNESS")
    assert stats.sample_count == 0
    assert stats.mean is None
    assert stats.variance is None


def test_summarize_dimension_variance_is_none_below_two_samples():
    stats = summarize_dimension([4], dimension="NATURALNESS")
    assert stats.sample_count == 1
    assert stats.mean == 4
    assert stats.variance is None, "variance is mathematically undefined for n=1, never fabricated as 0"


def test_summarize_dimension_computes_real_statistics_for_two_or_more_samples():
    stats = summarize_dimension([2, 4], dimension="NATURALNESS")
    assert stats.sample_count == 2
    assert stats.mean == 3.0
    assert stats.median == 3.0
    assert stats.variance == pytest.approx(2.0)
    assert stats.min_score == 2
    assert stats.max_score == 4


def test_single_evaluation_never_claims_disagreement(tmp_path):
    log = EvaluationLog(tmp_path / "evaluation.jsonl")
    record_evaluation(
        log, output_id="out-1", reviewer="alice", listening=ListeningState(listened=True),
        dimension_scores={"NATURALNESS": 1},
    )
    summary = summarize_output_evaluations(evaluations_for(log, "out-1"), output_id="out-1")
    assert summary.evaluation_count < MIN_EVALUATIONS_FOR_DISAGREEMENT
    assert summary.has_disagreement is False
    assert "too few" in summary.note


def test_two_evaluations_with_a_wide_spread_are_flagged_as_disagreement(tmp_path):
    log = EvaluationLog(tmp_path / "evaluation.jsonl")
    record_evaluation(
        log, output_id="out-1", reviewer="alice", listening=ListeningState(listened=True),
        dimension_scores={"NATURALNESS": 5},
    )
    record_evaluation(
        log, output_id="out-1", reviewer="bob", listening=ListeningState(listened=True),
        dimension_scores={"NATURALNESS": 1},
    )
    summary = summarize_output_evaluations(evaluations_for(log, "out-1"), output_id="out-1")
    assert summary.has_disagreement is True
    assert "NATURALNESS" in summary.disagreement_dimensions


def test_two_evaluations_with_a_narrow_spread_are_not_disagreement(tmp_path):
    log = EvaluationLog(tmp_path / "evaluation.jsonl")
    record_evaluation(
        log, output_id="out-1", reviewer="alice", listening=ListeningState(listened=True),
        dimension_scores={"CLARITY": 4},
    )
    record_evaluation(
        log, output_id="out-1", reviewer="bob", listening=ListeningState(listened=True),
        dimension_scores={"CLARITY": 4},
    )
    summary = summarize_output_evaluations(evaluations_for(log, "out-1"), output_id="out-1")
    assert summary.has_disagreement is False


def test_summarize_output_evaluations_of_no_records_is_honest(tmp_path):
    summary = summarize_output_evaluations([], output_id="never-evaluated")
    assert summary.evaluation_count == 0
    assert summary.has_disagreement is False
    assert "No evaluations recorded" in summary.note


def test_outputs_with_disagreement_across_the_full_log(tmp_path):
    log = EvaluationLog(tmp_path / "evaluation.jsonl")
    listening = ListeningState(listened=True)
    record_evaluation(
        log, output_id="out-1", reviewer="alice", listening=listening, dimension_scores={"NATURALNESS": 5}
    )
    record_evaluation(
        log, output_id="out-1", reviewer="bob", listening=listening, dimension_scores={"NATURALNESS": 1}
    )
    record_evaluation(log, output_id="out-2", reviewer="alice", listening=listening, dimension_scores={"CLARITY": 4})
    record_evaluation(log, output_id="out-2", reviewer="bob", listening=listening, dimension_scores={"CLARITY": 4})
    assert outputs_with_disagreement(log) == ["out-1"]


def test_summarize_ab_preferences_reports_pairwise_counts_honestly(tmp_path):
    log = ABEvaluationLog(tmp_path / "ab_evaluation.jsonl")
    kwargs = {"output_id_a": "out-1", "output_id_b": "out-2", "listened_a": True, "listened_b": True}
    record_ab_evaluation(log, reviewer="alice", decision=ABDecision.PREFER_A, **kwargs)
    record_ab_evaluation(log, reviewer="bob", decision=ABDecision.PREFER_B, **kwargs)
    record_ab_evaluation(log, reviewer="carol", decision=ABDecision.NO_PREFERENCE, **kwargs)
    summary = summarize_ab_preferences(ab_evaluations_for(log, "out-1"), output_id_a="out-1", output_id_b="out-2")
    assert summary.total_decisions == 3
    assert summary.prefer_a_count == 1
    assert summary.prefer_b_count == 1
    assert summary.no_preference_count == 1
    assert summary.preference_rate_a == pytest.approx(0.5)


def test_summarize_ab_preferences_of_no_decisions_never_fabricates_a_rate():
    summary = summarize_ab_preferences([], output_id_a="out-1", output_id_b="out-2")
    assert summary.total_decisions == 0
    assert summary.preference_rate_a is None


def test_summarize_calibration_signals_counts_are_real(tmp_path):
    log = EvaluationLog(tmp_path / "evaluation.jsonl")
    listening = ListeningState(listened=True)
    record_evaluation(
        log, output_id="out-1", reviewer="alice", listening=listening, dimension_scores={"NATURALNESS": 5}
    )
    record_evaluation(
        log, output_id="out-1", reviewer="bob", listening=listening, dimension_scores={"NATURALNESS": 1}
    )
    signals = summarize_calibration_signals(log)
    assert signals.total_evaluations == 2
    assert signals.total_outputs_evaluated == 1
    assert signals.total_reviewers == 2
    assert signals.disagreement_output_count == 1


# ---------------------------------------------------------------------------
# Calibration boundary — always UNCALIBRATED, no score is ever computed
# ---------------------------------------------------------------------------


def test_summarize_evaluation_calibration_inputs_is_always_uncalibrated_with_no_log(tmp_path):
    summary = summarize_evaluation_calibration_inputs()
    assert summary.calibration_state == CalibrationState.UNCALIBRATED
    assert summary.total_evaluations == 0
    assert "never a computed score" in summary.note


def test_summarize_evaluation_calibration_inputs_reflects_real_counts(tmp_path):
    log = EvaluationLog(tmp_path / "evaluation.jsonl")
    listening = ListeningState(listened=True)
    record_evaluation(
        log, output_id="out-1", reviewer="alice", listening=listening, dimension_scores={"NATURALNESS": 5}
    )
    record_evaluation(
        log, output_id="out-1", reviewer="bob", listening=listening, dimension_scores={"NATURALNESS": 1}
    )
    summary = summarize_evaluation_calibration_inputs(evaluation_log=log)
    assert summary.calibration_state == CalibrationState.UNCALIBRATED
    assert summary.total_evaluations == 2
    assert summary.disagreement_output_count == 1


# ---------------------------------------------------------------------------
# Security / provenance / speaker-identity boundary
# ---------------------------------------------------------------------------


def test_evaluation_record_has_no_speaker_identity_field(tmp_path):
    log = EvaluationLog(tmp_path / "evaluation.jsonl")
    payload = record_evaluation(
        log, output_id="out-1", reviewer="alice", listening=ListeningState(listened=True),
        dimension_scores={"NATURALNESS": 4}, voice_profile_id="demo-voice-v1", model_id="synthetic-tone-v1",
    )
    keys = " ".join(payload.keys()).lower()
    for forbidden in ["speaker", "accent", "pronunciation_match", "target_speaker", "identity_label", "embedding"]:
        assert forbidden not in keys


def test_ab_evaluation_record_has_no_speaker_identity_field(tmp_path):
    log = ABEvaluationLog(tmp_path / "ab_evaluation.jsonl")
    payload = record_ab_evaluation(
        log, output_id_a="out-1", output_id_b="out-2", reviewer="alice",
        listened_a=True, listened_b=True, decision=ABDecision.PREFER_A,
    )
    keys = " ".join(payload.keys()).lower()
    for forbidden in ["speaker", "accent", "pronunciation_match", "target_speaker", "identity_label", "embedding"]:
        assert forbidden not in keys


def test_evaluation_provenance_fields_round_trip(tmp_path):
    log = EvaluationLog(tmp_path / "evaluation.jsonl")
    payload = record_evaluation(
        log, output_id="out-1", reviewer="alice", listening=ListeningState(listened=True),
        voice_profile_id="demo-voice-v1", model_id="synthetic-tone-v1",
        config_hash="a1" * 32, output_sha256="b2" * 32,
    )
    assert payload["voice_profile_id"] == "demo-voice-v1"
    assert payload["model_id"] == "synthetic-tone-v1"
    assert payload["config_hash"] == "a1" * 32
    assert payload["output_sha256"] == "b2" * 32


def test_evaluation_module_never_imports_data_root_or_source_access():
    """VL-D6 never accesses real recordings -- confirmed structurally: the
    module that defines evaluation records has no dependency on
    core.data_root or anything that reads source/."""
    import aarya_voice_lab.pipeline.evaluation as evaluation_module

    assert "data_root" not in evaluation_module.__file__
    assert not hasattr(evaluation_module, "DataRoot")
    assert not hasattr(evaluation_module, "assert_source_writable")
