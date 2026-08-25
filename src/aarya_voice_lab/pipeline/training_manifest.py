"""Training manifest construction -- Task 3 of the current autonomous
execution plan (Real Data Preprocessing).

Chains: `NormalizedRecord` (from a `DatasetAdapter`) -> real audio
validation (`pipeline.validation.validate_audio_file`, the same
structural check this project already applies to the private-recording
pipeline) -> transcript-presence check -> a `TrainingManifest` recording
which records are eligible for a training job and which are excluded,
with a real, specific reason for each exclusion.

Never invents a speaker ID: `NormalizedRecord.speaker_id` passes through
unchanged, present or absent, exactly as `DatasetAdapter` produced it.
Never alters or moves the source audio file -- `validate_audio_file()`
only reads it. Nothing here decides *who* is speaking; that boundary
belongs entirely to Phase 3 (`identity/`), not this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aarya_voice_lab.pipeline.dataset_adapter import NormalizedRecord
from aarya_voice_lab.pipeline.validation import ValidationStatus, validate_audio_file


@dataclass(frozen=True)
class ExcludedRecord:
    record_id: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"record_id": self.record_id, "reason": self.reason}


@dataclass(frozen=True)
class TrainingManifest:
    dataset_id: str
    eligible_record_ids: tuple[str, ...]
    excluded: tuple[ExcludedRecord, ...]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "eligible_record_ids": list(self.eligible_record_ids),
            "excluded": [e.to_dict() for e in self.excluded],
            "created_at": self.created_at,
        }


def build_training_manifest(dataset_id: str, records: list[NormalizedRecord]) -> TrainingManifest:
    """Validate every record's real audio file and transcript presence,
    classifying each as eligible or excluded.

    Audio validation reuses `validate_audio_file()` exactly -- structural
    validity only (readable container, non-zero size, sane duration),
    never a quality judgement (that stays a separate, later concern, per
    `pipeline.validation`'s own established split). A record excluded
    here is excluded for a real, checkable reason, never a guess.
    """
    eligible: list[str] = []
    excluded: list[ExcludedRecord] = []
    for record in records:
        audio_path = Path(record.audio_ref)
        result = validate_audio_file(audio_path, source_file_id=record.record_id)
        if result.status in (ValidationStatus.INVALID, ValidationStatus.BLOCKED):
            reasons = "; ".join(f.message for f in result.findings) or result.status.value
            excluded.append(ExcludedRecord(record.record_id, f"audio validation {result.status.value}: {reasons}"))
            continue
        if not record.transcript or not record.transcript.strip():
            excluded.append(ExcludedRecord(record.record_id, "no transcript present"))
            continue
        eligible.append(record.record_id)
    return TrainingManifest(
        dataset_id=dataset_id,
        eligible_record_ids=tuple(eligible),
        excluded=tuple(excluded),
        created_at=datetime.now(UTC).isoformat(),
    )
