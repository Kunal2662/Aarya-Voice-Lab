"""Train/validation/test partitioning -- the held-out evaluation set
`docs/BENCHMARKING.md` names as its first unmet methodology requirement
("A held-out evaluation set -- never used in training, or
`speaker_similarity` measures memorization rather than generalization").

No split/partition mechanism existed anywhere in this codebase before this
module (confirmed by a full-repository search for train/validation/test/
split/holdout/leakage terms; the only prior "held-out" usage is
`identity.calibration`'s unrelated speaker-verification-threshold
calibration evidence, not dataset splitting).

## Two evaluation questions, not one

`docs/BENCHMARKING.md` does not disambiguate which of two different,
equally legitimate questions a "held-out set" is meant to answer:

- **SAME_SPEAKER** -- held-out *utterances* from speakers the model has
  otherwise seen. Answers "does this reproduce a known voice faithfully,
  on content it wasn't trained on?" -- the relevant question for the
  Private Voice, where there is exactly one target speaker and
  generalizing to *unseen speakers* is meaningless.
- **HELD_OUT_SPEAKER** -- entire speakers set aside, present in no other
  split. Answers "does this generalize to voices it has never seen at
  all?" -- the relevant question for a multi-speaker corpus like
  LibriSpeech, registered here for training-pipeline development and
  benchmark development, not for cloning any one of its speakers.

Rather than silently picking one interpretation, both are implemented as
explicit `SplitStrategy` values sharing one small mechanism: every
record is deterministically assigned to exactly one partition by slicing
a seeded-shuffle, either per-speaker (SAME_SPEAKER, so every speaker's
own utterances divide across all three partitions) or across the sorted
speaker list itself (HELD_OUT_SPEAKER, so a speaker's entire utterance
set lands in exactly one partition). No record is ever dropped: slicing
`[:n_train]`, `[n_train:n_train+n_val]`, `[n_train+n_val:]` accounts for
every input exactly once, regardless of rounding.

Callers are expected to pass only records already known eligible (e.g.
the subset of `pipeline.training_manifest.build_training_manifest()`'s
`eligible_record_ids`) -- this module does not re-validate audio and does
not decide eligibility; it only partitions.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from aarya_voice_lab.pipeline.dataset_adapter import NormalizedRecord


class SplitStrategy(StrEnum):
    SAME_SPEAKER = "same_speaker"
    HELD_OUT_SPEAKER = "held_out_speaker"


class SplitError(ValueError):
    """Raised for invalid proportions, an empty input, an empty resulting
    partition, or (for HELD_OUT_SPEAKER) a record with no speaker_id.
    This module fails loudly rather than silently producing an unusable
    or misleading evaluation set."""


@dataclass(frozen=True)
class SplitProportions:
    train: float
    validation: float
    test: float

    def validate(self) -> None:
        for name, value in (("train", self.train), ("validation", self.validation), ("test", self.test)):
            if not (0.0 < value < 1.0):
                raise SplitError(f"{name} proportion must be strictly between 0 and 1, got {value!r}")
        total = self.train + self.validation + self.test
        if abs(total - 1.0) > 1e-6:
            raise SplitError(f"proportions must sum to 1.0, got {total!r} (train+validation+test)")

    def to_dict(self) -> dict[str, float]:
        return {"train": self.train, "validation": self.validation, "test": self.test}


@dataclass(frozen=True)
class SplitConfig:
    strategy: SplitStrategy
    proportions: SplitProportions
    seed: int

    def config_hash(self) -> str:
        payload = json.dumps(
            {"strategy": self.strategy.value, "proportions": self.proportions.to_dict(), "seed": self.seed},
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "proportions": self.proportions.to_dict(),
            "seed": self.seed,
            "config_hash": self.config_hash(),
        }


@dataclass(frozen=True)
class DatasetSplit:
    dataset_id: str
    config: SplitConfig
    train_record_ids: tuple[str, ...]
    validation_record_ids: tuple[str, ...]
    test_record_ids: tuple[str, ...]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "config": self.config.to_dict(),
            "train_record_ids": list(self.train_record_ids),
            "validation_record_ids": list(self.validation_record_ids),
            "test_record_ids": list(self.test_record_ids),
            "created_at": self.created_at,
        }


def _slice_three(items: list[Any], proportions: SplitProportions) -> tuple[list[Any], list[Any], list[Any]]:
    n = len(items)
    n_train = round(n * proportions.train)
    n_val = round(n * proportions.validation)
    n_train = min(n_train, n)
    n_val = min(n_val, n - n_train)
    return items[:n_train], items[n_train : n_train + n_val], items[n_train + n_val :]


def split_records(
    dataset_id: str,
    records: list[NormalizedRecord],
    config: SplitConfig,
) -> DatasetSplit:
    """Deterministically partition `records` into train/validation/test.

    Same source manifest + same config (strategy, proportions, seed)
    always produces an identical partition -- `random.Random(config.seed)`
    is seeded fresh here, never shared global state.
    """
    config.proportions.validate()
    if not records:
        raise SplitError("cannot split an empty record list")

    rng = random.Random(config.seed)
    train_ids: list[str] = []
    val_ids: list[str] = []
    test_ids: list[str] = []

    if config.strategy is SplitStrategy.HELD_OUT_SPEAKER:
        missing = sorted(r.record_id for r in records if r.speaker_id is None)
        if missing:
            raise SplitError(
                "held_out_speaker strategy requires every record to have a speaker_id; "
                f"missing for {len(missing)} record(s), e.g. {missing[:5]}"
            )
        speakers = sorted({r.speaker_id for r in records})
        rng.shuffle(speakers)
        train_speakers, val_speakers, test_speakers = _slice_three(speakers, config.proportions)
        train_speakers, val_speakers, test_speakers = set(train_speakers), set(val_speakers), set(test_speakers)
        for record in records:
            if record.speaker_id in train_speakers:
                train_ids.append(record.record_id)
            elif record.speaker_id in val_speakers:
                val_ids.append(record.record_id)
            else:
                test_ids.append(record.record_id)
    else:
        by_speaker: dict[str | None, list[NormalizedRecord]] = defaultdict(list)
        for record in records:
            by_speaker[record.speaker_id].append(record)
        for speaker_id in sorted(by_speaker, key=lambda s: (s is None, s)):
            group = list(by_speaker[speaker_id])
            rng.shuffle(group)
            group_train, group_val, group_test = _slice_three(group, config.proportions)
            train_ids += [r.record_id for r in group_train]
            val_ids += [r.record_id for r in group_val]
            test_ids += [r.record_id for r in group_test]

    train_ids, val_ids, test_ids = tuple(sorted(train_ids)), tuple(sorted(val_ids)), tuple(sorted(test_ids))
    for name, ids in (("train", train_ids), ("validation", val_ids), ("test", test_ids)):
        if not ids:
            raise SplitError(
                f"{name} partition is empty after splitting -- adjust proportions, seed, or provide more data"
            )

    return DatasetSplit(
        dataset_id=dataset_id,
        config=config,
        train_record_ids=train_ids,
        validation_record_ids=val_ids,
        test_record_ids=test_ids,
        created_at=datetime.now(UTC).isoformat(),
    )


@dataclass(frozen=True)
class LeakageReport:
    duplicate_record_ids: tuple[str, ...] = field(default_factory=tuple)
    duplicate_paths: tuple[str, ...] = field(default_factory=tuple)
    duplicate_hashes: tuple[str, ...] = field(default_factory=tuple)
    speaker_leakage: tuple[str, ...] = field(default_factory=tuple)
    unaccounted_record_ids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def clean(self) -> bool:
        return not (
            self.duplicate_record_ids
            or self.duplicate_paths
            or self.duplicate_hashes
            or self.speaker_leakage
            or self.unaccounted_record_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "clean": self.clean,
            "duplicate_record_ids": list(self.duplicate_record_ids),
            "duplicate_paths": list(self.duplicate_paths),
            "duplicate_hashes": list(self.duplicate_hashes),
            "speaker_leakage": list(self.speaker_leakage),
            "unaccounted_record_ids": list(self.unaccounted_record_ids),
        }


def _find_cross_split_duplicates(*groups: list[str]) -> tuple[str, ...]:
    """A value counts as a leak only if it appears in more than one
    *group* -- each group is deduplicated internally first, so a value
    repeating many times within a single split (e.g. one speaker's many
    utterances all landing in the same partition, as intended) is never
    mistaken for cross-split leakage."""
    seen: set[str] = set()
    duplicates: set[str] = set()
    for group in groups:
        for value in set(group):
            if value in seen:
                duplicates.add(value)
            seen.add(value)
    return tuple(sorted(duplicates))


def check_leakage(
    split: DatasetSplit,
    records_by_id: dict[str, NormalizedRecord],
    *,
    content_hashes: dict[str, str] | None = None,
    expected_record_ids: set[str] | None = None,
) -> LeakageReport:
    """Verify a split is actually safe to use for evaluation.

    `records_by_id` must map every id in the split back to the
    `NormalizedRecord` that produced it (for path/speaker lookups).
    `content_hashes` is an optional record_id -> hash map -- "identical
    content hashes where available", since `NormalizedRecord` itself
    carries no checksum field and this module never computes one on its
    own (a dataset adapter's job, not this module's). `expected_record_ids`,
    if given, lets the caller assert that every eligible input record
    landed in exactly one partition and none silently disappeared.
    """
    duplicate_ids = _find_cross_split_duplicates(
        list(split.train_record_ids), list(split.validation_record_ids), list(split.test_record_ids)
    )

    def _paths_for(ids: tuple[str, ...]) -> list[str]:
        return [records_by_id[i].audio_ref for i in ids if i in records_by_id]

    duplicate_paths = _find_cross_split_duplicates(
        _paths_for(split.train_record_ids), _paths_for(split.validation_record_ids), _paths_for(split.test_record_ids)
    )

    duplicate_hashes: tuple[str, ...] = ()
    if content_hashes:

        def _hashes_for(ids: tuple[str, ...]) -> list[str]:
            return [content_hashes[i] for i in ids if i in content_hashes]

        duplicate_hashes = _find_cross_split_duplicates(
            _hashes_for(split.train_record_ids),
            _hashes_for(split.validation_record_ids),
            _hashes_for(split.test_record_ids),
        )

    speaker_leakage: tuple[str, ...] = ()
    if split.config.strategy is SplitStrategy.HELD_OUT_SPEAKER:

        def _speakers_for(ids: tuple[str, ...]) -> list[str]:
            return [records_by_id[i].speaker_id for i in ids if i in records_by_id and records_by_id[i].speaker_id]

        speaker_leakage = _find_cross_split_duplicates(
            _speakers_for(split.train_record_ids),
            _speakers_for(split.validation_record_ids),
            _speakers_for(split.test_record_ids),
        )

    unaccounted: tuple[str, ...] = ()
    if expected_record_ids is not None:
        all_split_ids = set(split.train_record_ids) | set(split.validation_record_ids) | set(split.test_record_ids)
        unaccounted = tuple(sorted(expected_record_ids ^ all_split_ids))

    return LeakageReport(
        duplicate_record_ids=duplicate_ids,
        duplicate_paths=duplicate_paths,
        duplicate_hashes=duplicate_hashes,
        speaker_leakage=speaker_leakage,
        unaccounted_record_ids=unaccounted,
    )
