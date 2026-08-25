from __future__ import annotations

from aarya_voice_lab.pipeline.dataset_adapter import NormalizedRecord
from aarya_voice_lab.pipeline.training_manifest import build_training_manifest
from aarya_voice_lab.testing.synthetic_audio import generate_speech_like, generate_zero_byte


def _record(record_id, audio_path, *, transcript="hello world", speaker_id=None):
    return NormalizedRecord(
        dataset_id="fixture-corpus",
        record_id=record_id,
        audio_ref=str(audio_path),
        language="en",
        license="CC0-1.0",
        transcript=transcript,
        speaker_id=speaker_id,
    )


def test_valid_record_with_transcript_is_eligible(tmp_path):
    audio = generate_speech_like(tmp_path / "r1.wav", duration_seconds=2.0)
    manifest = build_training_manifest("fixture-corpus", [_record("r1", audio)])

    assert manifest.eligible_record_ids == ("r1",)
    assert manifest.excluded == ()


def test_invalid_audio_is_excluded_with_a_real_reason(tmp_path):
    audio = generate_zero_byte(tmp_path / "r1.wav")
    manifest = build_training_manifest("fixture-corpus", [_record("r1", audio)])

    assert manifest.eligible_record_ids == ()
    assert len(manifest.excluded) == 1
    assert manifest.excluded[0].record_id == "r1"
    assert "audio validation" in manifest.excluded[0].reason


def test_missing_audio_file_is_excluded(tmp_path):
    manifest = build_training_manifest("fixture-corpus", [_record("r1", tmp_path / "does_not_exist.wav")])
    assert manifest.eligible_record_ids == ()
    assert manifest.excluded[0].reason.startswith("audio validation INVALID")


def test_record_without_transcript_is_excluded(tmp_path):
    audio = generate_speech_like(tmp_path / "r1.wav", duration_seconds=2.0)
    manifest = build_training_manifest("fixture-corpus", [_record("r1", audio, transcript=None)])

    assert manifest.eligible_record_ids == ()
    assert manifest.excluded[0].record_id == "r1"
    assert manifest.excluded[0].reason == "no transcript present"


def test_record_with_blank_transcript_is_excluded(tmp_path):
    audio = generate_speech_like(tmp_path / "r1.wav", duration_seconds=2.0)
    manifest = build_training_manifest("fixture-corpus", [_record("r1", audio, transcript="   ")])
    assert manifest.excluded[0].reason == "no transcript present"


def test_speaker_id_is_never_fabricated_when_absent(tmp_path):
    """This module must never invent a speaker_id -- it should not even
    look at the field, only pass judgement on audio validity and
    transcript presence."""
    audio = generate_speech_like(tmp_path / "r1.wav", duration_seconds=2.0)
    record = _record("r1", audio, speaker_id=None)
    manifest = build_training_manifest("fixture-corpus", [record])
    assert record.speaker_id is None  # unchanged by this module
    assert manifest.eligible_record_ids == ("r1",)


def test_mixed_batch_partitions_correctly(tmp_path):
    valid = generate_speech_like(tmp_path / "valid.wav", duration_seconds=2.0)
    invalid = generate_zero_byte(tmp_path / "invalid.wav")
    no_transcript = generate_speech_like(tmp_path / "no_transcript.wav", duration_seconds=2.0)

    records = [
        _record("valid", valid),
        _record("invalid", invalid),
        _record("no_transcript", no_transcript, transcript=None),
    ]
    manifest = build_training_manifest("fixture-corpus", records)

    assert manifest.eligible_record_ids == ("valid",)
    excluded_ids = {e.record_id for e in manifest.excluded}
    assert excluded_ids == {"invalid", "no_transcript"}


def test_manifest_to_dict_round_trips_all_fields(tmp_path):
    audio = generate_speech_like(tmp_path / "r1.wav", duration_seconds=2.0)
    manifest = build_training_manifest("fixture-corpus", [_record("r1", audio)])
    as_dict = manifest.to_dict()
    assert as_dict["dataset_id"] == "fixture-corpus"
    assert as_dict["eligible_record_ids"] == ["r1"]
    assert as_dict["excluded"] == []
    assert "created_at" in as_dict


def test_empty_record_list_produces_an_empty_manifest():
    manifest = build_training_manifest("fixture-corpus", [])
    assert manifest.eligible_record_ids == ()
    assert manifest.excluded == ()
