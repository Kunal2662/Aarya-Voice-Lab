"""Objective speaker-similarity evaluation -- the `speaker_similarity`
metric `docs/BENCHMARKING.md`'s schema has always defined but that no code
in this project had ever computed against real speech before this module
(confirmed by a full-repository search: no cosine-similarity or
embedding-comparison function existed anywhere).

This module owns pair selection, cosine similarity, and result
aggregation only -- never the embedding computation itself, which stays
`identity.embeddings`'s job. `evaluate_pairs()` takes an `embed_record`
callback rather than importing a provider directly, so this module has
no dependency on NeMo, subprocess isolation, or any specific provider;
it is exercised in tests with a trivial in-memory callback and, for real
evaluation, wired to `identity.embeddings.LocalNeuralEmbeddingProvider`
by a separate orchestration script.

## Three pair categories, matching three different questions

- `SAME_SPEAKER_HELD_OUT` -- two held-out utterances from the same
  speaker. Answers "is this speaker's voice self-consistent across
  content the split marked as evaluation-only?"
- `DIFFERENT_SPEAKER` -- utterances from two different speakers, both
  held out. The contrast case: similarity here should be materially
  lower than `SAME_SPEAKER_HELD_OUT`, or the embedding space isn't
  actually separating speakers.
- `TRAIN_REFERENCE_TO_HELD_OUT` -- a training-partition utterance
  compared against a held-out utterance of the *same* speaker. Only
  possible when a speaker appears in both partitions, which by
  construction only happens under `dataset_split.SplitStrategy.SAME_SPEAKER`
  -- a `HELD_OUT_SPEAKER` split yields zero pairs in this category,
  correctly, not an error (a held-out speaker never appears in train by
  design).

`select_pairs()` never compares a record against itself and never
selects the same unordered pair twice, regardless of category.
"""

from __future__ import annotations

import math
import random
import statistics
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from aarya_voice_lab.pipeline.dataset_adapter import NormalizedRecord
from aarya_voice_lab.pipeline.dataset_split import DatasetSplit


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"vectors must be the same length, got {len(a)} and {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        raise ValueError("cannot compute cosine similarity against a zero vector")
    return dot / (norm_a * norm_b)


class PairKind(StrEnum):
    SAME_SPEAKER_HELD_OUT = "same_speaker_held_out"
    DIFFERENT_SPEAKER = "different_speaker"
    TRAIN_REFERENCE_TO_HELD_OUT = "train_reference_to_held_out"


@dataclass(frozen=True)
class EvaluationPair:
    pair_id: str
    kind: PairKind
    reference_record_id: str
    candidate_record_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "pair_id": self.pair_id,
            "kind": self.kind.value,
            "reference_record_id": self.reference_record_id,
            "candidate_record_id": self.candidate_record_id,
        }


def _speaker_groups(ids: Sequence[str], records_by_id: dict[str, NormalizedRecord]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for record_id in ids:
        record = records_by_id.get(record_id)
        if record is not None and record.speaker_id is not None:
            groups[record.speaker_id].append(record_id)
    return groups


def select_pairs(
    split: DatasetSplit,
    records_by_id: dict[str, NormalizedRecord],
    *,
    seed: int,
    max_pairs_per_kind: int,
) -> tuple[EvaluationPair, ...]:
    """Deterministically select up to `max_pairs_per_kind` pairs per
    category. A category with no eligible records under the split's own
    strategy yields zero pairs for that category -- never fabricated,
    never an error (see module docstring for `TRAIN_REFERENCE_TO_HELD_OUT`
    under a `HELD_OUT_SPEAKER` split)."""
    if max_pairs_per_kind <= 0:
        raise ValueError(f"max_pairs_per_kind must be positive, got {max_pairs_per_kind}")

    rng = random.Random(seed)
    pairs: list[EvaluationPair] = []
    seen_unordered: set[frozenset[str]] = set()

    def _add(candidates: list[tuple[str, str]], kind: PairKind, prefix: str) -> None:
        rng.shuffle(candidates)
        for a, b in candidates:
            if len(pairs) and len([p for p in pairs if p.kind is kind]) >= max_pairs_per_kind:
                break
            if a == b:
                continue
            key = frozenset((a, b))
            if key in seen_unordered:
                continue
            seen_unordered.add(key)
            pairs.append(EvaluationPair(f"{prefix}-{sum(1 for p in pairs if p.kind is kind)}", kind, a, b))

    held_out_ids = sorted(set(split.validation_record_ids) | set(split.test_record_ids))
    held_out_by_speaker = _speaker_groups(held_out_ids, records_by_id)

    same_speaker_candidates: list[tuple[str, str]] = []
    for ids in held_out_by_speaker.values():
        if len(ids) < 2:
            continue
        ordered = sorted(ids)
        rng.shuffle(ordered)
        same_speaker_candidates.append((ordered[0], ordered[1]))
    _add(same_speaker_candidates, PairKind.SAME_SPEAKER_HELD_OUT, "same-speaker")

    speakers = sorted(held_out_by_speaker)
    different_speaker_candidates: list[tuple[str, str]] = []
    for i in range(len(speakers)):
        for j in range(i + 1, len(speakers)):
            a_ids, b_ids = held_out_by_speaker[speakers[i]], held_out_by_speaker[speakers[j]]
            if a_ids and b_ids:
                different_speaker_candidates.append((rng.choice(sorted(a_ids)), rng.choice(sorted(b_ids))))
    _add(different_speaker_candidates, PairKind.DIFFERENT_SPEAKER, "diff-speaker")

    train_by_speaker = _speaker_groups(split.train_record_ids, records_by_id)
    train_to_held_out_candidates: list[tuple[str, str]] = []
    for speaker_id, held_ids in held_out_by_speaker.items():
        train_ids = train_by_speaker.get(speaker_id)
        if not train_ids:
            continue
        train_to_held_out_candidates.append((rng.choice(sorted(train_ids)), rng.choice(sorted(held_ids))))
    _add(train_to_held_out_candidates, PairKind.TRAIN_REFERENCE_TO_HELD_OUT, "train-to-heldout")

    return tuple(pairs)


@dataclass(frozen=True)
class PairResult:
    pair: EvaluationPair
    similarity: float | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.similarity is not None

    def to_dict(self) -> dict[str, Any]:
        return {"pair": self.pair.to_dict(), "similarity": self.similarity, "error": self.error}


@dataclass(frozen=True)
class KindStatistics:
    kind: PairKind
    count: int
    mean: float | None = None
    median: float | None = None
    stdev: float | None = None
    p10: float | None = None
    p90: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "count": self.count,
            "mean": self.mean,
            "median": self.median,
            "stdev": self.stdev,
            "p10": self.p10,
            "p90": self.p90,
        }


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = fraction * (len(sorted_values) - 1)
    lower, upper = int(math.floor(index)), int(math.ceil(index))
    if lower == upper:
        return sorted_values[lower]
    weight = index - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _kind_statistics(kind: PairKind, scores: list[float]) -> KindStatistics:
    if not scores:
        return KindStatistics(kind=kind, count=0)
    ordered = sorted(scores)
    return KindStatistics(
        kind=kind,
        count=len(scores),
        mean=statistics.mean(scores),
        median=statistics.median(scores),
        stdev=statistics.stdev(scores) if len(scores) > 1 else 0.0,
        p10=_percentile(ordered, 0.10),
        p90=_percentile(ordered, 0.90),
    )


@dataclass(frozen=True)
class SimilarityEvaluationSummary:
    pairs_attempted: int
    pairs_succeeded: int
    pairs_failed: int
    embeddings_attempted: int
    embeddings_succeeded: int
    embeddings_failed: int
    coverage: float
    by_kind: tuple[KindStatistics, ...]
    results: tuple[PairResult, ...] = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pairs_attempted": self.pairs_attempted,
            "pairs_succeeded": self.pairs_succeeded,
            "pairs_failed": self.pairs_failed,
            "embeddings_attempted": self.embeddings_attempted,
            "embeddings_succeeded": self.embeddings_succeeded,
            "embeddings_failed": self.embeddings_failed,
            "coverage": self.coverage,
            "by_kind": [k.to_dict() for k in self.by_kind],
            "results": [r.to_dict() for r in self.results],
        }


def evaluate_pairs(
    pairs: tuple[EvaluationPair, ...],
    embed_record: Callable[[str], tuple[float, ...] | None],
) -> SimilarityEvaluationSummary:
    """`embed_record(record_id)` must return a real embedding vector, or
    `None` on failure -- this function never retries and never fabricates
    a vector. Each distinct record_id is embedded at most once and cached
    for the duration of this call, regardless of how many pairs reference
    it."""
    vector_cache: dict[str, tuple[float, ...] | None] = {}
    embeddings_attempted = 0

    def _get(record_id: str) -> tuple[float, ...] | None:
        nonlocal embeddings_attempted
        if record_id not in vector_cache:
            embeddings_attempted += 1
            vector_cache[record_id] = embed_record(record_id)
        return vector_cache[record_id]

    results: list[PairResult] = []
    for pair in pairs:
        ref_vector = _get(pair.reference_record_id)
        cand_vector = _get(pair.candidate_record_id)
        if ref_vector is None or cand_vector is None:
            results.append(PairResult(pair, None, error="embedding unavailable for reference or candidate"))
            continue
        try:
            results.append(PairResult(pair, cosine_similarity(ref_vector, cand_vector)))
        except ValueError as exc:
            results.append(PairResult(pair, None, error=str(exc)))

    succeeded = [r for r in results if r.ok]
    by_kind = tuple(
        _kind_statistics(kind, [r.similarity for r in succeeded if r.pair.kind is kind]) for kind in PairKind
    )
    embeddings_succeeded = sum(1 for v in vector_cache.values() if v is not None)

    return SimilarityEvaluationSummary(
        pairs_attempted=len(pairs),
        pairs_succeeded=len(succeeded),
        pairs_failed=len(results) - len(succeeded),
        embeddings_attempted=embeddings_attempted,
        embeddings_succeeded=embeddings_succeeded,
        embeddings_failed=embeddings_attempted - embeddings_succeeded,
        coverage=(len(succeeded) / len(pairs)) if pairs else 0.0,
        by_kind=by_kind,
        results=tuple(results),
    )
