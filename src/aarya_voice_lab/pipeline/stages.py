"""Canonical pipeline stage ordering and the phase boundary.

The ordering below was revised in Phase 2. Phase 0 placed speaker
diarization immediately after inventory, which put every speaker-related
stage *before* audio validation, quality analysis, and segmentation. The
Phase 2 pipeline requires the opposite: all technical preparation of the
audio happens first, and nothing touches speaker identity until Phase 3.

Two review stages exist, deliberately:

  CANDIDATE_REVIEW  (Phase 2) — technical triage: corrupt files, poor
                    quality, ambiguous segmentation, possible overlap.
                    Reviewers are NEVER asked who is speaking.
  MANUAL_REVIEW     (Phase 3+) — speaker approval, after verification.

Collapsing them into one stage would blur exactly the boundary this
project must keep sharp.
"""

from __future__ import annotations

from enum import StrEnum


class PipelineStage(StrEnum):
    # --- Phase 2: technical preparation (no speaker identity) -------------
    SOURCE = "source"
    INVENTORY = "inventory"
    AUDIO_VALIDATION = "audio_validation"
    NORMALIZATION = "normalization"
    QUALITY_ANALYSIS = "quality_analysis"
    SPEECH_SILENCE_ANALYSIS = "speech_silence_analysis"
    SEGMENTATION = "segmentation"
    OVERLAP_CANDIDATE_DETECTION = "overlap_candidate_detection"
    CANDIDATE_MANIFEST = "candidate_manifest"
    CANDIDATE_REVIEW = "candidate_review"

    # --- Phase 3+: speaker identity, transcription, modelling -------------
    SPEAKER_DIARIZATION = "speaker_diarization"
    SPEAKER_IDENTIFICATION = "speaker_identification"
    QUALITY_FILTERING = "quality_filtering"
    TRANSCRIPTION = "transcription"
    WORD_ALIGNMENT = "word_alignment"
    SPEAKER_VERIFICATION = "speaker_verification"
    MANUAL_REVIEW = "manual_review"
    VERIFIED_DATASET = "verified_dataset"
    VOICE_MODEL_EXPERIMENTS = "voice_model_experiments"
    FIDELITY_BENCHMARK = "fidelity_benchmark"
    PRODUCTION_VOICE_MODEL = "production_voice_model"


PIPELINE_ORDER: tuple[PipelineStage, ...] = tuple(PipelineStage)

#: Stages Phase 2 owns. Everything after CANDIDATE_REVIEW belongs to a
#: later phase and must not be implemented here.
PHASE_2_STAGES: tuple[PipelineStage, ...] = (
    PipelineStage.INVENTORY,
    PipelineStage.AUDIO_VALIDATION,
    PipelineStage.NORMALIZATION,
    PipelineStage.QUALITY_ANALYSIS,
    PipelineStage.SPEECH_SILENCE_ANALYSIS,
    PipelineStage.SEGMENTATION,
    PipelineStage.OVERLAP_CANDIDATE_DETECTION,
    PipelineStage.CANDIDATE_MANIFEST,
    PipelineStage.CANDIDATE_REVIEW,
)

#: The first stage that reasons about *who* is speaking. Nothing at or
#: after this point may be implemented before Phase 3 is approved.
SPEAKER_IDENTITY_BOUNDARY: PipelineStage = PipelineStage.SPEAKER_DIARIZATION

#: Stages that determine or depend on speaker identity.
SPEAKER_IDENTITY_STAGES: frozenset[PipelineStage] = frozenset(
    {
        PipelineStage.SPEAKER_DIARIZATION,
        PipelineStage.SPEAKER_IDENTIFICATION,
        PipelineStage.SPEAKER_VERIFICATION,
        PipelineStage.MANUAL_REVIEW,
        PipelineStage.VERIFIED_DATASET,
    }
)


def stage_index(stage: PipelineStage) -> int:
    return PIPELINE_ORDER.index(stage)


def is_phase_2_stage(stage: PipelineStage) -> bool:
    return stage in PHASE_2_STAGES


def determines_speaker_identity(stage: PipelineStage) -> bool:
    """Whether a stage reasons about speaker identity.

    Phase 2 code must never run one of these, and no Phase 2 output may
    claim a speaker role.
    """
    return stage in SPEAKER_IDENTITY_STAGES


def is_implemented(stage: PipelineStage) -> bool:
    """Whether real processing logic exists for this stage.

    Phase 2 implements the technical-preparation stages. Everything from
    the speaker-identity boundary onward remains unimplemented until its
    phase is explicitly approved.
    """
    return stage in PHASE_2_STAGES
