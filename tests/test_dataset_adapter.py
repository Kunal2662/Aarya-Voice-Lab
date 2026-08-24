from __future__ import annotations

import json

import pytest

from aarya_voice_lab.pipeline.dataset_adapter import (
    DatasetAdapterError,
    FixtureDatasetAdapter,
    NormalizedRecord,
)


def _write_manifest(path, records):
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")


def test_iter_records_normalizes_minimal_entries(tmp_path):
    manifest = tmp_path / "manifest.jsonl"
    _write_manifest(
        manifest,
        [{"record_id": "r1", "audio_ref": "audio/r1.wav", "language": "en"}],
    )
    adapter = FixtureDatasetAdapter(manifest, dataset_id="fixture-corpus", license="CC0-1.0")
    records = list(adapter.iter_records())
    assert records == [
        NormalizedRecord(
            dataset_id="fixture-corpus",
            record_id="r1",
            audio_ref="audio/r1.wav",
            language="en",
            license="CC0-1.0",
        )
    ]


def test_iter_records_preserves_optional_fields(tmp_path):
    manifest = tmp_path / "manifest.jsonl"
    _write_manifest(
        manifest,
        [
            {
                "record_id": "r1",
                "audio_ref": "audio/r1.wav",
                "language": "en",
                "transcript": "hello world",
                "speaker_id": "spk-01",
                "sample_rate": 16000,
                "duration_seconds": 2.5,
                "provenance": "acquired 2026-01-01",
                "metadata": {"split": "dev"},
            }
        ],
    )
    adapter = FixtureDatasetAdapter(manifest, dataset_id="fixture-corpus", license="CC0-1.0")
    record = next(adapter.iter_records())
    assert record.transcript == "hello world"
    assert record.speaker_id == "spk-01"
    assert record.sample_rate == 16000
    assert record.duration_seconds == 2.5
    assert record.provenance == "acquired 2026-01-01"
    assert record.metadata == {"split": "dev"}


def test_speaker_id_is_not_fabricated_when_absent(tmp_path):
    """A dataset that does not expose speaker identity must normalize to
    speaker_id=None -- never an inferred or placeholder value."""
    manifest = tmp_path / "manifest.jsonl"
    _write_manifest(manifest, [{"record_id": "r1", "audio_ref": "audio/r1.wav", "language": "en"}])
    adapter = FixtureDatasetAdapter(manifest, dataset_id="fixture-corpus", license="CC0-1.0")
    record = next(adapter.iter_records())
    assert record.speaker_id is None


def test_iter_records_skips_blank_lines(tmp_path):
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        '{"record_id": "r1", "audio_ref": "a.wav", "language": "en"}\n\n\n'
        '{"record_id": "r2", "audio_ref": "b.wav", "language": "en"}\n',
        encoding="utf-8",
    )
    adapter = FixtureDatasetAdapter(manifest, dataset_id="fixture-corpus", license="CC0-1.0")
    assert [r.record_id for r in adapter.iter_records()] == ["r1", "r2"]


def test_missing_manifest_raises(tmp_path):
    adapter = FixtureDatasetAdapter(tmp_path / "missing.jsonl", dataset_id="fixture-corpus", license="CC0-1.0")
    with pytest.raises(DatasetAdapterError, match="not found"):
        list(adapter.iter_records())


def test_missing_required_field_raises(tmp_path):
    manifest = tmp_path / "manifest.jsonl"
    _write_manifest(manifest, [{"record_id": "r1", "language": "en"}])  # no audio_ref
    adapter = FixtureDatasetAdapter(manifest, dataset_id="fixture-corpus", license="CC0-1.0")
    with pytest.raises(DatasetAdapterError, match="missing required field"):
        list(adapter.iter_records())


def test_invalid_json_line_raises(tmp_path):
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("not json\n", encoding="utf-8")
    adapter = FixtureDatasetAdapter(manifest, dataset_id="fixture-corpus", license="CC0-1.0")
    with pytest.raises(DatasetAdapterError, match="invalid JSON"):
        list(adapter.iter_records())


def test_record_count_matches_iter_records(tmp_path):
    manifest = tmp_path / "manifest.jsonl"
    _write_manifest(
        manifest,
        [
            {"record_id": "r1", "audio_ref": "a.wav", "language": "en"},
            {"record_id": "r2", "audio_ref": "b.wav", "language": "en"},
            {"record_id": "r3", "audio_ref": "c.wav", "language": "en"},
        ],
    )
    adapter = FixtureDatasetAdapter(manifest, dataset_id="fixture-corpus", license="CC0-1.0")
    assert adapter.record_count() == 3


def test_to_dict_round_trips_all_fields():
    record = NormalizedRecord(
        dataset_id="d",
        record_id="r1",
        audio_ref="a.wav",
        language="en",
        license="CC0-1.0",
        transcript="hi",
        speaker_id="spk-01",
        sample_rate=16000,
        duration_seconds=1.0,
        provenance="p",
        metadata={"k": "v"},
    )
    as_dict = record.to_dict()
    assert as_dict["dataset_id"] == "d"
    assert as_dict["speaker_id"] == "spk-01"
    assert as_dict["metadata"] == {"k": "v"}
