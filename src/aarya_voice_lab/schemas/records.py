"""Typed record helpers layered over the JSON Schemas in /schemas.

Each function builds a plain dict (the wire format used everywhere else
in this codebase) and validates it against its schema before returning.
Keeping records as dicts (rather than heavier ORM-like classes) matches
how they're actually stored: one JSON object per line/file in a
git-ignored local manifest.
"""

from __future__ import annotations

from typing import Any

from aarya_voice_lab import SCHEMA_VERSION
from aarya_voice_lab.schemas.base import SchemaName, validate


def build_segment(
    *,
    segment_id: str,
    source_file_id: str,
    source_start: float,
    source_end: float,
    speaker_id: str,
    target_speaker_status: str,
    diarization_source: str,
    diarization_confidence: float,
    independent_verification_status: str,
    overlap_status: str,
    language: str,
    alignment_status: str,
    acceptance_status: str,
    processing_version: str,
    transcript: str | None = None,
    audio_quality: dict[str, Any] | None = None,
    rejection_reason: str | None = None,
    confidence_classification: str | None = None,
    schema_version: str = SCHEMA_VERSION,
) -> dict[str, Any]:
    record = {
        "schema_version": schema_version,
        "segment_id": segment_id,
        "source_file_id": source_file_id,
        "source_start": source_start,
        "source_end": source_end,
        "duration": round(source_end - source_start, 6),
        "speaker_id": speaker_id,
        "target_speaker_status": target_speaker_status,
        "diarization_source": diarization_source,
        "diarization_confidence": diarization_confidence,
        "independent_verification_status": independent_verification_status,
        "overlap_status": overlap_status,
        "language": language,
        "transcript": transcript,
        "alignment_status": alignment_status,
        "audio_quality": audio_quality,
        "acceptance_status": acceptance_status,
        "rejection_reason": rejection_reason,
        "processing_version": processing_version,
    }
    if confidence_classification is not None:
        record["confidence_classification"] = confidence_classification
    validate(record, SchemaName.SEGMENT)
    return record


def build_dataset_manifest(
    *,
    dataset_id: str,
    dataset_version: str,
    created_at: str,
    segments: list[dict[str, Any]],
    description: str | None = None,
    is_synthetic: bool = False,
    schema_version: str = SCHEMA_VERSION,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": schema_version,
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "created_at": created_at,
        "is_synthetic": is_synthetic,
        "segments": segments,
    }
    if description is not None:
        record["description"] = description
    validate(record, SchemaName.DATASET_MANIFEST)
    return record


def build_experiment(
    *,
    experiment_id: str,
    created_at: str,
    dataset_version: str,
    model: str,
    model_version: str,
    status: str,
    configuration: dict[str, Any] | None = None,
    preprocessing_version: str | None = None,
    training_configuration: dict[str, Any] | None = None,
    hardware: dict[str, Any] | None = None,
    software_versions: dict[str, str] | None = None,
    metrics: dict[str, float] | None = None,
    benchmark_results: list[str] | None = None,
    notes: str | None = None,
    schema_version: str = SCHEMA_VERSION,
) -> dict[str, Any]:
    record = {
        "schema_version": schema_version,
        "experiment_id": experiment_id,
        "created_at": created_at,
        "dataset_version": dataset_version,
        "model": model,
        "model_version": model_version,
        "configuration": configuration or {},
        "preprocessing_version": preprocessing_version,
        "training_configuration": training_configuration or {},
        "hardware": hardware or {},
        "software_versions": software_versions or {},
        "metrics": metrics or {},
        "benchmark_results": benchmark_results,
        "status": status,
        "notes": notes,
    }
    validate(record, SchemaName.EXPERIMENT)
    return record


def build_model_registry_entry(
    *,
    model_name: str,
    version: str,
    provider: str,
    model_type: str,
    status: str,
    language_capability: list[str] | None = None,
    hardware_requirements: dict[str, Any] | None = None,
    model_hash: str | None = None,
    source: str | None = None,
    license: str | None = None,
    training_dataset_version: str | None = None,
    benchmark_results: list[str] | None = None,
    security_metadata: dict[str, Any] | None = None,
    schema_version: str = SCHEMA_VERSION,
) -> dict[str, Any]:
    record = {
        "schema_version": schema_version,
        "model_name": model_name,
        "version": version,
        "provider": provider,
        "model_type": model_type,
        "language_capability": language_capability or [],
        "hardware_requirements": hardware_requirements or {},
        "model_hash": model_hash,
        "source": source,
        "license": license,
        "training_dataset_version": training_dataset_version,
        "benchmark_results": benchmark_results,
        "status": status,
        "security_metadata": security_metadata,
    }
    validate(record, SchemaName.MODEL_REGISTRY)
    return record


def build_benchmark(
    *,
    benchmark_id: str,
    model_name: str,
    model_version: str,
    created_at: str,
    status: str,
    metrics: dict[str, float] | None = None,
    hardware: dict[str, Any] | None = None,
    notes: str | None = None,
    schema_version: str = SCHEMA_VERSION,
) -> dict[str, Any]:
    record = {
        "schema_version": schema_version,
        "benchmark_id": benchmark_id,
        "model_name": model_name,
        "model_version": model_version,
        "created_at": created_at,
        "status": status,
        "hardware": hardware or {},
        "metrics": metrics or {},
        "notes": notes,
    }
    validate(record, SchemaName.BENCHMARK)
    return record


def build_manual_review(
    *,
    review_id: str,
    segment_id: str,
    reviewer: str,
    reviewed_at: str,
    decision: str,
    notes: str | None = None,
    schema_version: str = SCHEMA_VERSION,
) -> dict[str, Any]:
    record = {
        "schema_version": schema_version,
        "review_id": review_id,
        "segment_id": segment_id,
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "decision": decision,
        "notes": notes,
    }
    validate(record, SchemaName.MANUAL_REVIEW)
    return record
