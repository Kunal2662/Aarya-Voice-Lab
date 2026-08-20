"""Phase 2 orchestration: inventory → … → candidate manifest.

Runs the technical-preparation stages over a directory of audio and emits
a candidate manifest. Every stage records provenance through the Phase 1
stage-result contract, so a run is resumable and auditable.

**No stage here determines speaker identity.** The output describes time
spans, quality, and possible overlap. Who is speaking is a Phase 3
question, and none of the record types produced here can express it.
"""

from __future__ import annotations

import json
import wave
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aarya_voice_lab import SCHEMA_VERSION, __version__
from aarya_voice_lab.audio.analysis import measure
from aarya_voice_lab.audio.probe import AudioReadError, read_wav_mono_samples
from aarya_voice_lab.audio.vad import VadConfig, detect_regions
from aarya_voice_lab.core.data_root import DataRoot, assert_source_writable
from aarya_voice_lab.pipeline.contracts import sha256_file
from aarya_voice_lab.pipeline.inventory import Inventory, build_inventory
from aarya_voice_lab.pipeline.overlap import (
    OverlapConfig,
    OverlapStatus,
    assess_overlap,
)
from aarya_voice_lab.pipeline.quality import (
    QualityDecision,
    QualityThresholds,
    assess_quality,
)
from aarya_voice_lab.pipeline.segmentation import (
    SegmentationConfig,
    segment_regions,
)
from aarya_voice_lab.pipeline.validation import (
    ValidationConfig,
    ValidationStatus,
    validate_audio_file,
)
from aarya_voice_lab.schemas.base import SchemaName, validate

PIPELINE_VERSION = "2.0.0"


@dataclass(frozen=True)
class PipelineConfig:
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    quality: QualityThresholds = field(default_factory=QualityThresholds)
    vad: VadConfig = field(default_factory=VadConfig)
    segmentation: SegmentationConfig = field(default_factory=SegmentationConfig)
    overlap: OverlapConfig = field(default_factory=OverlapConfig)
    #: Write extracted segment audio. Off by default: analysis needs only
    #: time spans, and not writing audio keeps derived private data minimal.
    extract_segment_audio: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "validation": self.validation.to_dict(),
            "quality": self.quality.to_dict(),
            "vad": self.vad.to_dict(),
            "segmentation": self.segmentation.to_dict(),
            "overlap": self.overlap.to_dict(),
            "extract_segment_audio": self.extract_segment_audio,
        }


@dataclass
class DatasetRunResult:
    batch_id: str
    dataset_version: str
    inventory: Inventory
    validation_results: list[dict[str, Any]] = field(default_factory=list)
    quality_results: list[dict[str, Any]] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    review_items: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    is_synthetic: bool = True

    def to_manifest(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "dataset_version": self.dataset_version,
            "batch_id": self.batch_id,
            "created_at": datetime.now(UTC).isoformat(),
            "processing_version": __version__,
            "phase": "phase-2",
            "is_synthetic": self.is_synthetic,
            "source_files": [
                {"source_file_id": f.source_file_id, "source_sha256": f.sha256}
                for f in self.inventory.unique_files
            ],
            "candidates": self.candidates,
        }

    def summary(self) -> dict[str, Any]:
        eligible = sum(1 for c in self.candidates if c["technical_eligibility"] == "technically_eligible")
        needs_review = sum(1 for c in self.candidates if c["technical_eligibility"] == "needs_review")
        rejected = sum(1 for c in self.candidates if c["technical_eligibility"] == "technically_rejected")
        return {
            "batch_id": self.batch_id,
            "dataset_version": self.dataset_version,
            "source_files": len(self.inventory.files),
            "unique_sources": len(self.inventory.unique_files),
            "duplicates": len(self.inventory.duplicates),
            "unreadable": len(self.inventory.unreadable),
            "candidate_segments": len(self.candidates),
            "technically_eligible": eligible,
            "needs_review": needs_review,
            "technically_rejected": rejected,
            "review_items": len(self.review_items),
            "warnings": list(self.warnings),
        }


def _extract_segment_wav(
    source: Path,
    destination: Path,
    start: float,
    end: float,
    data_root: DataRoot,
) -> str | None:
    """Write a WAV slice using the stdlib. Returns its hash, or None."""
    assert_source_writable(data_root, destination)
    try:
        with wave.open(str(source), "rb") as reader:
            rate = reader.getframerate()
            channels = reader.getnchannels()
            width = reader.getsampwidth()
            reader.setpos(min(int(start * rate), reader.getnframes()))
            frames = reader.readframes(max(int((end - start) * rate), 0))
    except (wave.Error, OSError, EOFError):
        return None

    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(width)
        writer.setframerate(rate)
        writer.writeframes(frames)
    return sha256_file(destination)


def run_dataset_pipeline(
    directory: Path,
    *,
    batch_id: str = "batch-001",
    dataset_version: str = "0.1.0",
    config: PipelineConfig | None = None,
    data_root: DataRoot | None = None,
    approved: bool = False,
    is_synthetic: bool = True,
    limit: int | None = None,
) -> DatasetRunResult:
    """Run the Phase 2 pipeline over `directory`.

    `limit` processes only the first N source files — used for the
    mandatory single-recording validation run before any full dataset run.
    """
    config = config or PipelineConfig()
    data = data_root or DataRoot.default()

    inventory = build_inventory(directory, approved=approved, batch_id=batch_id)
    result = DatasetRunResult(
        batch_id=batch_id,
        dataset_version=dataset_version,
        inventory=inventory,
        is_synthetic=is_synthetic,
    )

    sources = inventory.unique_files
    if limit is not None:
        sources = sources[:limit]

    for record in sources:
        path = directory / record.path

        # --- validation ----------------------------------------------------
        validation = validate_audio_file(
            path,
            source_file_id=record.source_file_id,
            config=config.validation,
            relative_to=directory,
        )
        result.validation_results.append(validation.to_dict())

        if validation.status is ValidationStatus.INVALID:
            detail = validation.findings[0].message if validation.findings else "unknown"
            result.review_items.append(
                _review_item(record.source_file_id, "invalid_audio", f"validation failed: {detail}")
            )
            continue

        if validation.status is ValidationStatus.BLOCKED:
            result.warnings.append(
                f"{record.source_file_id}: {validation.findings[-1].message}"
            )
            result.review_items.append(
                _review_item(record.source_file_id, "capability_unavailable",
                             "file could not be inspected; FFmpeg is required")
            )
            continue

        # --- decode (WAV only without FFmpeg) -------------------------------
        try:
            samples, sample_rate = read_wav_mono_samples(path)
        except AudioReadError as exc:
            result.warnings.append(f"{record.source_file_id}: {exc}")
            result.review_items.append(
                _review_item(record.source_file_id, "decode_failed", str(exc))
            )
            continue

        bit_depth = record.bit_depth or 16

        # --- measurement, then decision (kept separate) ----------------------
        measurements = measure(samples, sample_rate, bit_depth=bit_depth)
        vad = detect_regions(samples, sample_rate, bit_depth=bit_depth, config=config.vad)
        quality = assess_quality(
            record.source_file_id, measurements, vad, thresholds=config.quality
        )
        result.quality_results.append(quality.to_dict())

        if quality.decision is QualityDecision.FAIL:
            result.review_items.append(
                _review_item(record.source_file_id, "quality_fail",
                             quality.findings[0].message if quality.findings else "quality check failed")
            )
            continue
        if quality.decision is QualityDecision.REVIEW:
            result.review_items.append(
                _review_item(record.source_file_id, "quality_review",
                             quality.findings[0].message if quality.findings else "quality needs review")
            )

        # --- segmentation ----------------------------------------------------
        segments = segment_regions(
            vad,
            source_file_id=record.source_file_id,
            source_sha256=record.sha256,
            config=config.segmentation,
        )

        for segment in segments:
            start_index = int(segment.start * sample_rate)
            end_index = min(int(segment.end * sample_rate), len(samples))
            segment_samples = samples[start_index:end_index]

            overlap = assess_overlap(
                segment.segment_id,
                segment_samples,
                sample_rate,
                bit_depth=bit_depth,
                config=config.overlap,
            )

            segment_hash = None
            if config.extract_segment_audio:
                destination = data.batch_segments(batch_id) / f"{segment.segment_id}.wav"
                segment_hash = _extract_segment_wav(path, destination, segment.start, segment.end, data)

            eligibility, rejection_reason = _decide_technical_eligibility(
                segment.duration, quality.decision, overlap.status, config
            )

            if eligibility == "needs_review":
                result.review_items.append(
                    _review_item(
                        record.source_file_id,
                        "segment_needs_review",
                        rejection_reason or "segment requires technical review",
                        segment_id=segment.segment_id,
                    )
                )

            result.candidates.append(
                {
                    "segment_id": segment.segment_id,
                    "source_file_id": segment.source_file_id,
                    "source_sha256": segment.source_sha256,
                    "segment_sha256": segment_hash,
                    "start_time": round(segment.start, 6),
                    "end_time": round(segment.end, 6),
                    "duration": round(segment.duration, 6),
                    "audio_format": record.container,
                    "sample_rate": sample_rate,
                    "channels": record.channels,
                    "technical_eligibility": eligibility,
                    "technical_rejection_reason": rejection_reason,
                    "quality_status": quality.decision.value,
                    "quality_characteristics": quality.characteristics,
                    "speech_status": "speech_detected" if vad.speech_regions else "no_speech_detected",
                    "overlap_status": overlap.status.value,
                    "overlap_confidence": overlap.confidence,
                    "overlap_detection_method": overlap.detection_method,
                    "overlap_detector_version": overlap.detector_version,
                    "requires_phase3_review": overlap.requires_phase3_resolution,
                    "provenance": {
                        "segmentation_version": segment.segmentation_version,
                        "segmentation_config_hash": segment.config_hash,
                        "quality_thresholds_hash": quality.thresholds_hash,
                        "vad_config_hash": overlap.config_hash,
                        "normalization_applied": False,
                        "normalization_config": None,
                        "split_reason": segment.split_reason.value,
                        "stage": "candidate_manifest",
                    },
                    "processing_version": __version__,
                }
            )

    return result


def _decide_technical_eligibility(
    duration: float,
    quality: QualityDecision,
    overlap: OverlapStatus,
    config: PipelineConfig,
) -> tuple[str, str | None]:
    """Technical suitability only — never a speaker judgement.

    'technically_eligible' means: usable audio of a workable length with
    no unresolved overlap signal. It does NOT mean the segment has been
    approved as target-speaker training data.
    """
    if duration < config.segmentation.min_segment_seconds:
        return "needs_review", (
            f"duration {duration:.2f}s is below the {config.segmentation.min_segment_seconds}s minimum"
        )
    if quality is QualityDecision.FAIL:
        return "technically_rejected", "audio quality failed"
    if overlap in (OverlapStatus.OVERLAP_DETECTED, OverlapStatus.POSSIBLE_OVERLAP):
        return "needs_review", f"overlap signal: {overlap.value}; Phase 3 must adjudicate"
    if overlap is OverlapStatus.UNKNOWN:
        # Never auto-promote an undecidable segment.
        return "needs_review", "overlap could not be determined; not assumed clear"
    if quality is QualityDecision.REVIEW:
        return "needs_review", "audio quality flagged for review"
    return "technically_eligible", None


def _review_item(
    source_file_id: str,
    reason_code: str,
    message: str,
    segment_id: str | None = None,
) -> dict[str, Any]:
    """A Phase 2 review item.

    Deliberately carries no speaker question: Phase 2 reviewers are asked
    only about technical fitness (see docs/DATASET_PIPELINE.md).
    """
    return {
        "source_file_id": source_file_id,
        "segment_id": segment_id,
        "reason_code": reason_code,
        "message": message,
        "review_type": "technical",
        "asks_about_speaker_identity": False,
        "created_at": datetime.now(UTC).isoformat(),
    }


def write_candidate_manifest(result: DatasetRunResult, path: Path) -> Path:
    manifest = result.to_manifest()
    validate(manifest, SchemaName.CANDIDATE_MANIFEST)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return path
