from __future__ import annotations

import pytest

from aarya_voice_lab.pipeline.stages import (
    PHASE_2_STAGES,
    PIPELINE_ORDER,
    SPEAKER_IDENTITY_BOUNDARY,
    SPEAKER_IDENTITY_STAGES,
    PipelineStage,
    determines_speaker_identity,
    is_implemented,
    stage_index,
)
from aarya_voice_lab.review import ManualReviewLog, ReviewQueue
from aarya_voice_lab.voice_service import VoiceService


def test_pipeline_order_starts_at_source_and_ends_at_production():
    assert PIPELINE_ORDER[0] is PipelineStage.SOURCE
    assert PIPELINE_ORDER[-1] is PipelineStage.PRODUCTION_VOICE_MODEL


def test_verification_precedes_manual_review_and_dataset():
    assert stage_index(PipelineStage.SPEAKER_VERIFICATION) < stage_index(PipelineStage.MANUAL_REVIEW)
    assert stage_index(PipelineStage.MANUAL_REVIEW) < stage_index(PipelineStage.VERIFIED_DATASET)


def test_only_phase_2_stages_are_implemented():
    """Phase 2 implements technical preparation and nothing beyond it.

    This replaces the Phase 0 assertion that *nothing* was implemented,
    which became false once Phase 2 landed. The stricter property is kept:
    no stage at or past the speaker-identity boundary may be implemented.
    """
    for stage in PipelineStage:
        if stage in PHASE_2_STAGES:
            assert is_implemented(stage), f"{stage} should be implemented in Phase 2"
        else:
            assert not is_implemented(stage), f"{stage} must NOT be implemented before its phase"


def test_no_speaker_identity_stage_is_implemented():
    """The boundary that matters: Phase 2 must not decide who is speaking."""
    for stage in SPEAKER_IDENTITY_STAGES:
        assert not is_implemented(stage), f"{stage} determines speaker identity and belongs to Phase 3+"


def test_technical_preparation_precedes_all_speaker_work():
    """Every Phase 2 stage must come before the speaker-identity boundary.

    Phase 0 ordered diarization immediately after inventory, which put
    speaker work ahead of quality analysis and segmentation. Phase 2
    corrected that; this test keeps it corrected.
    """
    boundary = stage_index(SPEAKER_IDENTITY_BOUNDARY)
    for stage in PHASE_2_STAGES:
        assert stage_index(stage) < boundary, f"{stage} must precede any speaker-identity stage"


def test_candidate_review_is_distinct_from_manual_review():
    """Phase 2's technical triage and Phase 3's speaker approval are
    separate stages, so a Phase 2 reviewer is never asked about identity."""
    assert PipelineStage.CANDIDATE_REVIEW is not PipelineStage.MANUAL_REVIEW
    assert stage_index(PipelineStage.CANDIDATE_REVIEW) < stage_index(PipelineStage.MANUAL_REVIEW)
    assert not determines_speaker_identity(PipelineStage.CANDIDATE_REVIEW)
    assert determines_speaker_identity(PipelineStage.MANUAL_REVIEW)


def test_review_queue_surfaces_pending_and_ambiguous(synthetic_segment):
    accepted = dict(synthetic_segment)
    pending = dict(synthetic_segment, segment_id="seg-2", acceptance_status="pending")
    flagged = dict(synthetic_segment, segment_id="seg-3", target_speaker_status="manual_review")

    queue = ReviewQueue([accepted, pending, flagged])
    ids = {item.segment_id for item in queue.pending_items()}
    assert ids == {"seg-2", "seg-3"}


def test_review_item_carries_traceability(synthetic_segment):
    pending = dict(synthetic_segment, acceptance_status="pending")
    item = ReviewQueue([pending]).pending_items()[0]
    assert item.source_file_id == "synthetic-source-001"
    assert item.source_start == 0.0
    assert item.source_end == 2.5
    assert item.speaker_id == "spk_0"


def test_record_decision_writes_valid_record(tmp_path):
    log = ManualReviewLog(tmp_path / "reviews.jsonl")
    ReviewQueue.record_decision(
        log,
        review_id="r1",
        segment_id="seg-1",
        reviewer="tester",
        reviewed_at="2026-01-01T00:00:00Z",
        decision="approve",
    )
    assert log.get("r1")["decision"] == "approve"


def test_record_decision_rejects_invalid_decision(tmp_path):
    log = ManualReviewLog(tmp_path / "reviews.jsonl")
    with pytest.raises(ValueError):
        ReviewQueue.record_decision(
            log,
            review_id="r1",
            segment_id="seg-1",
            reviewer="tester",
            reviewed_at="2026-01-01T00:00:00Z",
            decision="looks_fine_to_me",
        )


def test_voice_service_is_abstract():
    """The VoiceService contract must not be instantiable in Phase 0 --
    no provider is implemented."""
    with pytest.raises(TypeError):
        VoiceService()


def test_voice_service_declares_the_full_contract():
    for method in ("list_voice_profiles", "get_voice_profile", "synthesize", "health", "get_model_info"):
        assert method in VoiceService.__abstractmethods__
