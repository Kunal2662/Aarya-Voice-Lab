#!/usr/bin/env python3
"""Export backend enum vocabularies to frontend/contracts/generated/*.json.

VL-D0's UI must consume the backend's status/stage vocabulary, never
duplicate it by hand. This script is the one place that reads the Python
enums and writes their frozen JSON shape; frontend/tests/contracts-drift
re-runs it into a temp dir and diffs against the committed output, so a
backend enum change that isn't re-exported fails CI rather than silently
drifting.

Usage:
    python scripts/export_frontend_contracts.py [--check]

--check exits nonzero if regenerating would change any committed file,
without writing anything (used by the drift test).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from aarya_voice_lab.core.capability import CapabilityState  # noqa: E402
from aarya_voice_lab.identity.calibration import CalibrationState  # noqa: E402
from aarya_voice_lab.identity.command_center import CommandRisk  # noqa: E402
from aarya_voice_lab.identity.preview import PreviewFeedbackOutcome, PreviewKind  # noqa: E402
from aarya_voice_lab.identity.runtime import ComputeBackend  # noqa: E402
from aarya_voice_lab.pipeline.candidate_review import (  # noqa: E402
    CandidateReviewDecision,
    CandidateReviewReason,
)
from aarya_voice_lab.pipeline.feedback import FeedbackType, ProcessingFeedbackCategory  # noqa: E402
from aarya_voice_lab.pipeline.overlap import OverlapStatus  # noqa: E402
from aarya_voice_lab.pipeline.processing import ProcessingDecision, ProcessingStatus  # noqa: E402
from aarya_voice_lab.pipeline.processing_profile import NoiseConditioningMode  # noqa: E402
from aarya_voice_lab.pipeline.quality import QualityDecision  # noqa: E402
from aarya_voice_lab.pipeline.stages import (  # noqa: E402
    PHASE_2_STAGES,
    PIPELINE_ORDER,
    SPEAKER_IDENTITY_BOUNDARY,
    SPEAKER_IDENTITY_STAGES,
)

OUT_DIR = REPO_ROOT / "frontend" / "contracts" / "generated"


def _enum_payload(source: str, enum_cls: type, doc: str) -> dict:
    return {
        "$generated_by": "scripts/export_frontend_contracts.py",
        "$source": source,
        "description": doc,
        "values": [member.value for member in enum_cls],
    }


def _pipeline_stage_payload() -> dict:
    boundary_index = PIPELINE_ORDER.index(SPEAKER_IDENTITY_BOUNDARY)
    return {
        "$generated_by": "scripts/export_frontend_contracts.py",
        "$source": "aarya_voice_lab.pipeline.stages",
        "description": (
            "Canonical stage ordering and the Phase 2/Phase 3 speaker-identity "
            "boundary. The frontend must render this order and this boundary "
            "exactly as given here — it must never compute or guess either."
        ),
        "stages": [stage.value for stage in PIPELINE_ORDER],
        "phase_2_stages": [stage.value for stage in PHASE_2_STAGES],
        # SPEAKER_IDENTITY_STAGES is a frozenset — iteration order is not
        # stable across interpreter runs, so re-order by canonical pipeline
        # position before serialising. Otherwise this file "drifts" on every
        # regeneration even though nothing actually changed.
        "speaker_identity_stages": [
            stage.value for stage in PIPELINE_ORDER if stage in SPEAKER_IDENTITY_STAGES
        ],
        "speaker_identity_boundary": SPEAKER_IDENTITY_BOUNDARY.value,
        "speaker_identity_boundary_index": boundary_index,
    }


def build_payloads() -> dict[str, dict]:
    return {
        "calibration_state.json": _enum_payload(
            "aarya_voice_lab.identity.calibration.CalibrationState",
            CalibrationState,
            "UNCALIBRATED/PROVISIONAL/CALIBRATED. CALIBRATED must never be "
            "shown without backend evidence — the UI may only render what "
            "this endpoint reports, never infer or upgrade a state.",
        ),
        "capability_state.json": _enum_payload(
            "aarya_voice_lab.core.capability.CapabilityState",
            CapabilityState,
            "Hardware/toolchain capability states surfaced by environment "
            "audit and (later) VL-D19 runtime detection.",
        ),
        "compute_backend.json": _enum_payload(
            "aarya_voice_lab.identity.runtime.ComputeBackend",
            ComputeBackend,
            "Vendor-neutral compute backends. The UI must render these as "
            "generic labels (CPU/GPU/backend name) and must never assume or "
            "design around one specific product.",
        ),
        "command_risk.json": _enum_payload(
            "aarya_voice_lab.identity.command_center.CommandRisk",
            CommandRisk,
            "Risk tiers for Claude Code Command Center actions. READ_ONLY "
            "commands need no confirmation; DESTRUCTIVE and GATED always do.",
        ),
        "preview_kind.json": _enum_payload(
            "aarya_voice_lab.identity.preview.PreviewKind",
            PreviewKind,
            "Kinds of voice preview artifact. Only SOURCE_SEGMENT and "
            "SYNTHETIC_FIXTURE exist in practice today; GENERATED_SPEECH is "
            "planned and must render as unavailable, never as if it works.",
        ),
        "preview_feedback_outcome.json": _enum_payload(
            "aarya_voice_lab.identity.preview.PreviewFeedbackOutcome",
            PreviewFeedbackOutcome,
            "Reviewer feedback outcomes for a voice preview.",
        ),
        "pipeline_stage.json": _pipeline_stage_payload(),
        "quality_decision.json": _enum_payload(
            "aarya_voice_lab.pipeline.quality.QualityDecision",
            QualityDecision,
            "PASS/WARNING/REVIEW/FAIL — the quality DECISION, produced by "
            "config-driven thresholds over audio.analysis's raw measurements. "
            "The UI must never compute this itself, and must add its own "
            "NOT_ANALYZED only for a recording no assessment has run on yet.",
        ),
        "overlap_status.json": _enum_payload(
            "aarya_voice_lab.pipeline.overlap.OverlapStatus",
            OverlapStatus,
            "A heuristic acoustic indicator, not a speaker count or a "
            "probability. POSSIBLE_OVERLAP/OVERLAP_DETECTED are candidates for "
            "Phase 3 to resolve, never a confirmed multi-speaker claim.",
        ),
        "candidate_review_decision.json": _enum_payload(
            "aarya_voice_lab.pipeline.candidate_review.CandidateReviewDecision",
            CandidateReviewDecision,
            "Technical candidate review only (review_type='technical'). "
            "Never a speaker-identity decision — see "
            "schemas/candidate_review.schema.json.",
        ),
        "candidate_review_reason.json": _enum_payload(
            "aarya_voice_lab.pipeline.candidate_review.CandidateReviewReason",
            CandidateReviewReason,
            "Closed, technical-only reason codes for a candidate review "
            "decision. No value here can express a speaker judgement.",
        ),
        "feedback_type.json": _enum_payload(
            "aarya_voice_lab.pipeline.feedback.FeedbackType",
            FeedbackType,
            "Feedback categories a human can attach to a recording, segment, "
            "candidate, processing result, or preview. Never converted into a "
            "training label.",
        ),
        "processing_status.json": _enum_payload(
            "aarya_voice_lab.pipeline.processing.ProcessingStatus",
            ProcessingStatus,
            "Voice-processing queue item states (VL-D4). BLOCKED means the "
            "item could not be processed at all (source verification failed); "
            "WARNING means it completed with a caveat (e.g. an optional tool "
            "was unavailable). Neither is ever silently upgraded to SUCCESS.",
        ),
        "processing_decision.json": _enum_payload(
            "aarya_voice_lab.pipeline.processing.ProcessingDecision",
            ProcessingDecision,
            "The processing DECISION (config-driven, from estimated SNR), kept "
            "strictly separate from the measurement that produced it. The UI "
            "must never compute this itself.",
        ),
        "noise_conditioning_mode.json": _enum_payload(
            "aarya_voice_lab.pipeline.processing_profile.NoiseConditioningMode",
            NoiseConditioningMode,
            "OFF and MEASURE_ONLY are implemented; LIGHT and STANDARD are a "
            "real, closed vocabulary with no noise-reduction tool wired up "
            "yet in VL-D4 — the UI must render them as NOT AVAILABLE if "
            "selected, never silently treat them as MEASURE_ONLY.",
        ),
        "processing_feedback_category.json": _enum_payload(
            "aarya_voice_lab.pipeline.feedback.ProcessingFeedbackCategory",
            ProcessingFeedbackCategory,
            "Closed vocabulary for feedback on a processing result, stored in "
            "a PROCESSING_FEEDBACK record's attributes.category.",
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify only; do not write")
    args = parser.parse_args()

    payloads = build_payloads()
    drift = []
    for filename, payload in payloads.items():
        text = json.dumps(payload, indent=2, sort_keys=False) + "\n"
        target = OUT_DIR / filename
        existing = target.read_text() if target.exists() else None
        if existing != text:
            drift.append(filename)
        if not args.check:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            target.write_text(text)

    if args.check and drift:
        print("Frontend contract exports are stale: " + ", ".join(drift), file=sys.stderr)
        print("Run: python scripts/export_frontend_contracts.py", file=sys.stderr)
        return 1
    if not args.check:
        print(f"Wrote {len(payloads)} contract file(s) to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
