from __future__ import annotations

import json

import pytest

from aarya_voice_lab.pipeline.dataset_adapter import (
    DatasetAdapterError,
    FixtureDatasetAdapter,
    LibriSpeechDatasetAdapter,
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


def _write_librispeech_fixture(root):
    """A tiny, synthetic on-disk tree shaped exactly like the real
    LibriSpeech layout (speaker/chapter/utterance.flac + a sibling
    .trans.txt) -- deliberately not the real ~350MB corpus, so this test
    is portable and needs no download."""
    chapter_dir = root / "1272" / "128104"
    chapter_dir.mkdir(parents=True)
    (chapter_dir / "1272-128104-0000.flac").write_bytes(b"fake flac bytes 0")
    (chapter_dir / "1272-128104-0001.flac").write_bytes(b"fake flac bytes 1")
    (chapter_dir / "1272-128104.trans.txt").write_text(
        "1272-128104-0000 MISTER QUILTER IS THE APOSTLE\n"
        "1272-128104-0001 NOR IS MISTER QUILTER'S MANNER LESS INTERESTING\n",
        encoding="utf-8",
    )
    other_chapter = root / "1272" / "141231"
    other_chapter.mkdir(parents=True)
    (other_chapter / "1272-141231-0000.flac").write_bytes(b"fake flac bytes 2")
    # No .trans.txt for this chapter -- exercises the missing-transcript path.
    return root


def test_librispeech_adapter_yields_real_records_from_the_real_layout(tmp_path):
    root = _write_librispeech_fixture(tmp_path)
    adapter = LibriSpeechDatasetAdapter(root, dataset_id="librispeech-dev-clean")
    records = sorted(adapter.iter_records(), key=lambda r: r.record_id)

    assert [r.record_id for r in records] == [
        "1272-128104-0000",
        "1272-128104-0001",
        "1272-141231-0000",
    ]
    first = records[0]
    assert first.transcript == "MISTER QUILTER IS THE APOSTLE"
    assert first.speaker_id == "1272"
    assert first.language == "en"
    assert first.license == "CC BY 4.0"
    assert first.audio_ref.endswith("1272-128104-0000.flac")
    assert first.metadata == {"chapter_id": "128104"}


def test_librispeech_adapter_never_fabricates_a_transcript_for_a_missing_trans_txt(tmp_path):
    root = _write_librispeech_fixture(tmp_path)
    adapter = LibriSpeechDatasetAdapter(root, dataset_id="librispeech-dev-clean")
    records = {r.record_id: r for r in adapter.iter_records()}
    assert records["1272-141231-0000"].transcript is None


def test_librispeech_adapter_never_fabricates_sample_rate_or_duration(tmp_path):
    """The adapter reads only dataset-native metadata -- it never probes
    the audio itself, so these stay unset rather than guessed."""
    root = _write_librispeech_fixture(tmp_path)
    adapter = LibriSpeechDatasetAdapter(root, dataset_id="librispeech-dev-clean")
    record = next(adapter.iter_records())
    assert record.sample_rate is None
    assert record.duration_seconds is None


def test_librispeech_adapter_missing_root_raises(tmp_path):
    adapter = LibriSpeechDatasetAdapter(tmp_path / "missing", dataset_id="librispeech-dev-clean")
    with pytest.raises(DatasetAdapterError, match="not found"):
        list(adapter.iter_records())


def test_librispeech_adapter_record_count_matches_flac_file_count(tmp_path):
    root = _write_librispeech_fixture(tmp_path)
    adapter = LibriSpeechDatasetAdapter(root, dataset_id="librispeech-dev-clean")
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
