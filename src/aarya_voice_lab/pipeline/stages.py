"""The future dataset pipeline, expressed as an ordered, documented enum.

No stage implementation lives here yet — see docs/DATASET_PIPELINE.md for
the narrative description and docs/TOOLCHAIN.md for candidate tools per
stage. This module exists so other Phase 0 code (manifests, CLI help
text, tests) can reference stage names consistently, and so later phases
have one canonical ordering to implement against.
"""

from __future__ import annotations

from enum import StrEnum


class PipelineStage(StrEnum):
    SOURCE = "source"
    INVENTORY = "inventory"
    SPEAKER_DIARIZATION = "speaker_diarization"
    SPEAKER_IDENTIFICATION = "speaker_identification"
    OVERLAP_DETECTION = "overlap_detection"
    CANDIDATE_EXTRACTION = "candidate_extraction"
    QUALITY_FILTERING = "quality_filtering"
    TRANSCRIPTION = "transcription"
    WORD_ALIGNMENT = "word_alignment"
    SPEAKER_VERIFICATION = "speaker_verification"
    MANUAL_REVIEW = "manual_review"
    VERIFIED_DATASET = "verified_dataset"
    VOICE_MODEL_EXPERIMENTS = "voice_model_experiments"
    FIDELITY_BENCHMARK = "fidelity_benchmark"
    PRODUCTION_VOICE_MODEL = "production_voice_model"


# Canonical order, matching docs/DATASET_PIPELINE.md. Each stage consumes
# the previous stage's output and is expected to preserve traceability
# back to (source_file_id, source_start, source_end) throughout.
PIPELINE_ORDER: tuple[PipelineStage, ...] = tuple(PipelineStage)


def stage_index(stage: PipelineStage) -> int:
    return PIPELINE_ORDER.index(stage)


def is_implemented(stage: PipelineStage) -> bool:
    """Whether real processing logic exists for this stage yet.

    Phase 0 implements none of them against real recordings — this
    function exists so the CLI and tests can assert that fact and so
    later phases have a single flag to flip per stage.
    """
    return False
