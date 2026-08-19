from __future__ import annotations

import json

import pytest

from aarya_voice_lab.core.paths import PROJECT_ROOT
from aarya_voice_lab.schemas.base import SchemaName, ValidationError, load_schema, validate
from aarya_voice_lab.schemas.records import (
    build_benchmark,
    build_dataset_manifest,
    build_experiment,
    build_manual_review,
    build_model_registry_entry,
    build_segment,
)


def test_every_schema_name_has_a_file():
    for name in SchemaName:
        schema = load_schema(name)
        assert schema["$schema"].startswith("http://json-schema.org/")
        assert "title" in schema


def test_valid_segment_passes(synthetic_segment):
    validate(synthetic_segment, SchemaName.SEGMENT)


def test_valid_manifest_passes(synthetic_manifest):
    validate(synthetic_manifest, SchemaName.DATASET_MANIFEST)


def test_segment_missing_required_field_fails(synthetic_segment):
    del synthetic_segment["speaker_id"]
    with pytest.raises(ValidationError):
        validate(synthetic_segment, SchemaName.SEGMENT)


def test_segment_rejects_unknown_field(synthetic_segment):
    synthetic_segment["audio_bytes"] = "should never exist in a manifest"
    with pytest.raises(ValidationError):
        validate(synthetic_segment, SchemaName.SEGMENT)


def test_segment_rejects_invalid_enum(synthetic_segment):
    synthetic_segment["target_speaker_status"] = "definitely_fine"
    with pytest.raises(ValidationError):
        validate(synthetic_segment, SchemaName.SEGMENT)


def test_segment_rejects_out_of_range_confidence(synthetic_segment):
    synthetic_segment["diarization_confidence"] = 1.5
    with pytest.raises(ValidationError):
        validate(synthetic_segment, SchemaName.SEGMENT)


def test_manifest_validates_nested_segments_via_local_ref(synthetic_manifest):
    """The $ref from dataset_manifest -> segment must resolve offline and
    actually validate nested records (regression guard: an unresolved
    $ref would silently accept anything, or attempt a network fetch)."""
    synthetic_manifest["segments"][0]["overlap_status"] = "not_a_real_value"
    with pytest.raises(ValidationError):
        validate(synthetic_manifest, SchemaName.DATASET_MANIFEST)


def test_private_voice_model_requires_security_metadata():
    with pytest.raises(ValidationError):
        validate(
            {
                "schema_version": "0.1.0",
                "model_name": "leaky-private-model",
                "version": "1.0.0",
                "provider": "local",
                "model_type": "private_voice",
                "status": "experimental",
            },
            SchemaName.MODEL_REGISTRY,
        )


def test_default_voice_model_does_not_require_security_metadata():
    validate(
        {
            "schema_version": "0.1.0",
            "model_name": "default-model",
            "version": "1.0.0",
            "provider": "local",
            "model_type": "default_voice",
            "status": "planned",
        },
        SchemaName.MODEL_REGISTRY,
    )


def test_builders_produce_valid_records():
    segment = build_segment(
        segment_id="s1",
        source_file_id="src1",
        source_start=1.0,
        source_end=3.0,
        speaker_id="spk_0",
        target_speaker_status="manual_review",
        diarization_source="synthetic",
        diarization_confidence=0.5,
        independent_verification_status="not_run",
        overlap_status="unknown",
        language="mr",
        alignment_status="not_run",
        acceptance_status="pending",
        processing_version="0.1.0",
    )
    assert segment["duration"] == 2.0

    build_dataset_manifest(
        dataset_id="d1",
        dataset_version="0.0.1",
        created_at="2026-01-01T00:00:00Z",
        segments=[segment],
        is_synthetic=True,
    )
    build_experiment(
        experiment_id="e1",
        created_at="2026-01-01T00:00:00Z",
        dataset_version="0.0.1",
        model="m",
        model_version="1",
        status="planned",
    )
    build_model_registry_entry(
        model_name="m", version="1", provider="local", model_type="default_voice", status="planned"
    )
    build_benchmark(
        benchmark_id="b1",
        model_name="m",
        model_version="1",
        created_at="2026-01-01T00:00:00Z",
        status="planned",
    )
    build_manual_review(
        review_id="r1",
        segment_id="s1",
        reviewer="tester",
        reviewed_at="2026-01-01T00:00:00Z",
        decision="ambiguous",
    )


def test_benchmark_rejects_unknown_metric():
    with pytest.raises(ValidationError):
        validate(
            {
                "schema_version": "0.1.0",
                "benchmark_id": "b",
                "model_name": "m",
                "model_version": "1",
                "created_at": "2026-01-01T00:00:00Z",
                "status": "completed",
                "metrics": {"vibes": 11.0},
            },
            SchemaName.BENCHMARK,
        )


@pytest.mark.parametrize(
    "filename,schema",
    [
        ("example_dataset_manifest.json", SchemaName.DATASET_MANIFEST),
        ("example_experiment.json", SchemaName.EXPERIMENT),
        ("example_benchmark.json", SchemaName.BENCHMARK),
        ("example_manual_review.json", SchemaName.MANUAL_REVIEW),
    ],
)
def test_shipped_templates_are_valid(filename, schema):
    path = PROJECT_ROOT / "manifests" / "templates" / filename
    with path.open(encoding="utf-8") as fh:
        record = json.load(fh)
    validate(record, schema)


def test_shipped_model_registry_template_is_valid():
    path = PROJECT_ROOT / "manifests" / "templates" / "example_model_registry.json"
    with path.open(encoding="utf-8") as fh:
        records = json.load(fh)
    for record in records:
        validate(record, SchemaName.MODEL_REGISTRY)


def test_tracked_manifest_templates_are_marked_synthetic():
    """Anything shipped in Git that carries dataset segments must declare
    is_synthetic -- a real manifest must never be committed."""
    path = PROJECT_ROOT / "manifests" / "templates" / "example_dataset_manifest.json"
    with path.open(encoding="utf-8") as fh:
        manifest = json.load(fh)
    assert manifest["is_synthetic"] is True
