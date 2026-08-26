from __future__ import annotations

import os
from pathlib import Path

import pytest

from aarya_voice_lab.pipeline.dataset_adapter import LibriSpeechDatasetAdapter, NormalizedRecord
from aarya_voice_lab.pipeline.dataset_split import (
    DatasetSplit,
    LeakageReport,
    SplitConfig,
    SplitError,
    SplitProportions,
    SplitStrategy,
    check_leakage,
    split_records,
)


def _record(record_id: str, speaker_id: str | None, *, audio_ref: str | None = None) -> NormalizedRecord:
    return NormalizedRecord(
        dataset_id="fixture-corpus",
        record_id=record_id,
        audio_ref=audio_ref or f"audio/{record_id}.wav",
        language="en",
        license="CC BY 4.0",
        transcript="hello",
        speaker_id=speaker_id,
    )


def _many_speaker_records(speaker_count: int = 10, utterances_per_speaker: int = 10) -> list[NormalizedRecord]:
    records = []
    for s in range(speaker_count):
        speaker_id = f"spk-{s:02d}"
        for u in range(utterances_per_speaker):
            records.append(_record(f"{speaker_id}-utt-{u:02d}", speaker_id))
    return records


DEFAULT_PROPORTIONS = SplitProportions(train=0.7, validation=0.15, test=0.15)


# -- 1. deterministic split / 11. reproducibility ----------------------------


def test_same_seed_and_config_produce_identical_partitions():
    records = _many_speaker_records()
    config = SplitConfig(strategy=SplitStrategy.SAME_SPEAKER, proportions=DEFAULT_PROPORTIONS, seed=42)
    first = split_records("fixture-corpus", records, config)
    second = split_records("fixture-corpus", list(records), config)
    assert first.train_record_ids == second.train_record_ids
    assert first.validation_record_ids == second.validation_record_ids
    assert first.test_record_ids == second.test_record_ids


def test_different_seed_changes_the_partition_for_a_large_enough_dataset():
    records = _many_speaker_records(speaker_count=20, utterances_per_speaker=20)
    config_a = SplitConfig(strategy=SplitStrategy.SAME_SPEAKER, proportions=DEFAULT_PROPORTIONS, seed=1)
    config_b = SplitConfig(strategy=SplitStrategy.SAME_SPEAKER, proportions=DEFAULT_PROPORTIONS, seed=2)
    split_a = split_records("fixture-corpus", records, config_a)
    split_b = split_records("fixture-corpus", records, config_b)
    assert split_a.train_record_ids != split_b.train_record_ids


# -- 2. configurable proportions ---------------------------------------------


def test_proportions_are_respected_within_rounding():
    records = _many_speaker_records(speaker_count=1, utterances_per_speaker=100)
    config = SplitConfig(
        strategy=SplitStrategy.SAME_SPEAKER, proportions=SplitProportions(0.8, 0.1, 0.1), seed=7
    )
    result = split_records("fixture-corpus", records, config)
    assert len(result.train_record_ids) == 80
    assert len(result.validation_record_ids) == 10
    assert len(result.test_record_ids) == 10


# -- 3. invalid proportion rejection ------------------------------------------


@pytest.mark.parametrize(
    "proportions",
    [
        SplitProportions(0.5, 0.3, 0.3),  # sums to 1.1
        SplitProportions(0.5, 0.5, 0.5),  # sums to 1.5
        SplitProportions(0.0, 0.5, 0.5),  # zero not allowed
        SplitProportions(1.0, 0.0, 0.0),  # zero not allowed
        SplitProportions(-0.1, 0.6, 0.5),  # negative not allowed
    ],
)
def test_invalid_proportions_are_rejected(proportions):
    with pytest.raises(SplitError):
        proportions.validate()


def test_split_records_rejects_invalid_proportions_before_touching_data():
    records = _many_speaker_records()
    bad_config = SplitConfig(strategy=SplitStrategy.SAME_SPEAKER, proportions=SplitProportions(0.5, 0.6, 0.1), seed=1)
    with pytest.raises(SplitError, match="sum to 1.0"):
        split_records("fixture-corpus", records, bad_config)


# -- 4. empty partition rejection --------------------------------------------


def test_empty_input_is_rejected():
    config = SplitConfig(strategy=SplitStrategy.SAME_SPEAKER, proportions=DEFAULT_PROPORTIONS, seed=1)
    with pytest.raises(SplitError, match="empty record list"):
        split_records("fixture-corpus", [], config)


def test_too_few_records_to_fill_every_partition_is_rejected_loudly():
    records = [_record("r1", "spk-01"), _record("r2", "spk-01")]
    config = SplitConfig(strategy=SplitStrategy.SAME_SPEAKER, proportions=DEFAULT_PROPORTIONS, seed=1)
    with pytest.raises(SplitError, match="empty after splitting"):
        split_records("fixture-corpus", records, config)


# -- 5 & 6. duplicate / path overlap detection --------------------------------


def test_check_leakage_reports_clean_for_a_genuinely_disjoint_split():
    records = _many_speaker_records()
    config = SplitConfig(strategy=SplitStrategy.SAME_SPEAKER, proportions=DEFAULT_PROPORTIONS, seed=42)
    result = split_records("fixture-corpus", records, config)
    by_id = {r.record_id: r for r in records}
    report = check_leakage(result, by_id, expected_record_ids=set(by_id))
    assert report.clean is True


def test_check_leakage_detects_a_duplicate_record_id_planted_across_splits():
    records = _many_speaker_records()
    config = SplitConfig(strategy=SplitStrategy.SAME_SPEAKER, proportions=DEFAULT_PROPORTIONS, seed=42)
    result = split_records("fixture-corpus", records, config)
    by_id = {r.record_id: r for r in records}

    tampered = DatasetSplit(
        dataset_id=result.dataset_id,
        config=result.config,
        train_record_ids=result.train_record_ids,
        validation_record_ids=(result.train_record_ids[0], *result.validation_record_ids),
        test_record_ids=result.test_record_ids,
        created_at=result.created_at,
    )
    report = check_leakage(tampered, by_id)
    assert result.train_record_ids[0] in report.duplicate_record_ids
    assert report.clean is False


def test_check_leakage_detects_duplicate_audio_paths_across_splits():
    same_path_records = [
        _record("r1", "spk-01", audio_ref="audio/shared.wav"),
        _record("r2", "spk-01", audio_ref="audio/shared.wav"),
    ] + _many_speaker_records(speaker_count=3, utterances_per_speaker=10)
    config = SplitConfig(strategy=SplitStrategy.SAME_SPEAKER, proportions=DEFAULT_PROPORTIONS, seed=3)
    result = split_records("fixture-corpus", same_path_records, config)
    by_id = {r.record_id: r for r in same_path_records}
    report = check_leakage(result, by_id)
    all_ids = set(result.train_record_ids) | set(result.validation_record_ids) | set(result.test_record_ids)
    def _which_split(record_id):
        if record_id in result.train_record_ids:
            return "train"
        if record_id in result.validation_record_ids:
            return "validation"
        return "test"

    if "r1" in all_ids and "r2" in all_ids and _which_split("r1") != _which_split("r2"):
        assert "audio/shared.wav" in report.duplicate_paths


def test_check_leakage_detects_duplicate_content_hashes_when_provided():
    records = _many_speaker_records(speaker_count=1, utterances_per_speaker=20)
    config = SplitConfig(strategy=SplitStrategy.SAME_SPEAKER, proportions=DEFAULT_PROPORTIONS, seed=5)
    result = split_records("fixture-corpus", records, config)
    by_id = {r.record_id: r for r in records}
    # Force two records (one from train, one from another split) to share a hash.
    other_id = result.validation_record_ids[0] if result.validation_record_ids else result.test_record_ids[0]
    hashes = {r.record_id: f"hash-{r.record_id}" for r in records}
    hashes[other_id] = hashes[result.train_record_ids[0]]
    report = check_leakage(result, by_id, content_hashes=hashes)
    assert hashes[result.train_record_ids[0]] in report.duplicate_hashes


def test_check_leakage_flags_unaccounted_records():
    records = _many_speaker_records()
    config = SplitConfig(strategy=SplitStrategy.SAME_SPEAKER, proportions=DEFAULT_PROPORTIONS, seed=42)
    result = split_records("fixture-corpus", records, config)
    by_id = {r.record_id: r for r in records}
    report = check_leakage(result, by_id, expected_record_ids=set(by_id) | {"phantom-record"})
    assert "phantom-record" in report.unaccounted_record_ids
    assert report.clean is False


# -- 7 & 10. speaker leakage prevention / held-out-speaker mode ---------------


def test_held_out_speaker_mode_puts_every_speaker_entirely_in_one_partition():
    records = _many_speaker_records(speaker_count=10, utterances_per_speaker=5)
    config = SplitConfig(strategy=SplitStrategy.HELD_OUT_SPEAKER, proportions=DEFAULT_PROPORTIONS, seed=9)
    result = split_records("fixture-corpus", records, config)
    by_id = {r.record_id: r for r in records}

    def speakers_in(ids):
        return {by_id[i].speaker_id for i in ids}

    train_speakers, val_speakers, test_speakers = (
        speakers_in(result.train_record_ids),
        speakers_in(result.validation_record_ids),
        speakers_in(result.test_record_ids),
    )
    assert train_speakers.isdisjoint(val_speakers)
    assert train_speakers.isdisjoint(test_speakers)
    assert val_speakers.isdisjoint(test_speakers)

    report = check_leakage(result, by_id, expected_record_ids=set(by_id))
    assert report.speaker_leakage == ()
    assert report.clean is True


def test_held_out_speaker_mode_requires_every_record_to_have_a_speaker_id():
    records = [_record("r1", "spk-01"), _record("r2", None)] + _many_speaker_records(3, 10)
    config = SplitConfig(strategy=SplitStrategy.HELD_OUT_SPEAKER, proportions=DEFAULT_PROPORTIONS, seed=1)
    with pytest.raises(SplitError, match="speaker_id"):
        split_records("fixture-corpus", records, config)


# -- 9. same-speaker evaluation mode ------------------------------------------


def test_same_speaker_mode_gives_every_sufficiently_sampled_speaker_a_presence_in_every_partition():
    records = _many_speaker_records(speaker_count=5, utterances_per_speaker=20)
    config = SplitConfig(strategy=SplitStrategy.SAME_SPEAKER, proportions=DEFAULT_PROPORTIONS, seed=11)
    result = split_records("fixture-corpus", records, config)
    by_id = {r.record_id: r for r in records}

    def speakers_in(ids):
        return {by_id[i].speaker_id for i in ids}

    all_speakers = {f"spk-{s:02d}" for s in range(5)}
    assert speakers_in(result.train_record_ids) == all_speakers
    assert speakers_in(result.validation_record_ids) == all_speakers
    assert speakers_in(result.test_record_ids) == all_speakers


# -- 8. manifest provenance preservation --------------------------------------


def test_split_preserves_dataset_id_and_records_exact_config():
    records = _many_speaker_records()
    config = SplitConfig(strategy=SplitStrategy.HELD_OUT_SPEAKER, proportions=DEFAULT_PROPORTIONS, seed=123)
    result = split_records("librispeech-dev-clean", records, config)
    as_dict = result.to_dict()
    assert as_dict["dataset_id"] == "librispeech-dev-clean"
    assert as_dict["config"]["strategy"] == "held_out_speaker"
    assert as_dict["config"]["seed"] == 123
    assert as_dict["config"]["proportions"] == {"train": 0.7, "validation": 0.15, "test": 0.15}
    assert "config_hash" in as_dict["config"]


def test_leakage_report_to_dict_round_trips():
    report = LeakageReport(duplicate_record_ids=("r1",))
    assert report.to_dict()["clean"] is False
    assert report.to_dict()["duplicate_record_ids"] == ["r1"]


# -- 12. bounded, real-manifest integration test ------------------------------


REAL_LIBRISPEECH_ROOT = "public_datasets/librispeech/extracted/LibriSpeech/dev-clean"


@pytest.mark.skipif(
    not os.path.isdir(REAL_LIBRISPEECH_ROOT),
    reason="real LibriSpeech dev-clean not present in this environment (git-ignored, never committed)",
)
def test_split_against_the_real_librispeech_manifest_is_leakage_free():
    """Bounded integration check against the actual downloaded dataset,
    when present -- never fabricated, and skipped honestly rather than
    faked when the real data isn't on this machine (e.g. a fresh
    checkout, or CI, where the git-ignored dataset was never fetched)."""
    adapter = LibriSpeechDatasetAdapter(Path(REAL_LIBRISPEECH_ROOT), dataset_id="librispeech-dev-clean")
    records = list(adapter.iter_records())
    assert len(records) > 0

    config = SplitConfig(strategy=SplitStrategy.HELD_OUT_SPEAKER, proportions=DEFAULT_PROPORTIONS, seed=42)
    result = split_records("librispeech-dev-clean", records, config)
    by_id = {r.record_id: r for r in records}
    report = check_leakage(result, by_id, expected_record_ids=set(by_id))

    assert report.clean is True
    assert len(result.train_record_ids) + len(result.validation_record_ids) + len(result.test_record_ids) == len(
        records
    )
