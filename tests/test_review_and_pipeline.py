from __future__ import annotations

import pytest

from aarya_voice_lab.pipeline.stages import PIPELINE_ORDER, PipelineStage, is_implemented, stage_index
from aarya_voice_lab.review import ManualReviewLog, ReviewQueue
from aarya_voice_lab.voice_service import VoiceService


def test_pipeline_order_starts_at_source_and_ends_at_production():
    assert PIPELINE_ORDER[0] is PipelineStage.SOURCE
    assert PIPELINE_ORDER[-1] is PipelineStage.PRODUCTION_VOICE_MODEL


def test_verification_precedes_manual_review_and_dataset():
    assert stage_index(PipelineStage.SPEAKER_VERIFICATION) < stage_index(PipelineStage.MANUAL_REVIEW)
    assert stage_index(PipelineStage.MANUAL_REVIEW) < stage_index(PipelineStage.VERIFIED_DATASET)


def test_no_pipeline_stage_is_implemented_in_phase_0():
    """Phase 0 acceptance criterion: no real processing exists yet."""
    assert not any(is_implemented(stage) for stage in PipelineStage)


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
