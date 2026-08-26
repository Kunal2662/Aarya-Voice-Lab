from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

from aarya_voice_lab.pipeline.dataset_adapter import LibriSpeechDatasetAdapter, NormalizedRecord
from aarya_voice_lab.pipeline.dataset_split import SplitConfig, SplitProportions, SplitStrategy, split_records
from aarya_voice_lab.pipeline.speaker_similarity import (
    EvaluationPair,
    PairKind,
    PairResult,
    cosine_similarity,
    evaluate_pairs,
    select_pairs,
)


def _record(record_id: str, speaker_id: str) -> NormalizedRecord:
    return NormalizedRecord(
        dataset_id="fixture-corpus",
        record_id=record_id,
        audio_ref=f"audio/{record_id}.wav",
        language="en",
        license="CC BY 4.0",
        transcript="hello",
        speaker_id=speaker_id,
    )


def _many_speaker_records(speaker_count=8, utterances_per_speaker=8) -> list[NormalizedRecord]:
    return [
        _record(f"spk-{s:02d}-utt-{u:02d}", f"spk-{s:02d}")
        for s in range(speaker_count)
        for u in range(utterances_per_speaker)
    ]


# -- metric calculation --------------------------------------------------


def test_cosine_similarity_of_identical_vectors_is_one():
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_similarity_of_opposite_vectors_is_negative_one():
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_similarity_of_orthogonal_vectors_is_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="same length"):
        cosine_similarity([1.0, 2.0], [1.0])


def test_cosine_similarity_rejects_a_zero_vector():
    with pytest.raises(ValueError, match="zero vector"):
        cosine_similarity([0.0, 0.0], [1.0, 1.0])


def test_cosine_similarity_never_fabricates_beyond_the_valid_range():
    # A real property of cosine similarity: bounded to [-1, 1] for any
    # real-valued input, never something implementation-specific.
    a, b = [3.0, -1.0, 4.0, 0.5], [-2.0, 5.0, 0.1, 7.0]
    score = cosine_similarity(a, b)
    assert -1.0 - 1e-9 <= score <= 1.0 + 1e-9


# -- pair selection --------------------------------------------------------


def test_select_pairs_never_compares_a_record_with_itself():
    records = _many_speaker_records()
    config = SplitConfig(strategy=SplitStrategy.SAME_SPEAKER, proportions=SplitProportions(0.6, 0.2, 0.2), seed=1)
    split = split_records("fixture-corpus", records, config)
    records_by_id = {r.record_id: r for r in records}
    pairs = select_pairs(split, records_by_id, seed=1, max_pairs_per_kind=10)
    assert pairs
    for pair in pairs:
        assert pair.reference_record_id != pair.candidate_record_id


def test_select_pairs_never_selects_the_same_unordered_pair_twice():
    records = _many_speaker_records()
    config = SplitConfig(strategy=SplitStrategy.SAME_SPEAKER, proportions=SplitProportions(0.6, 0.2, 0.2), seed=1)
    split = split_records("fixture-corpus", records, config)
    records_by_id = {r.record_id: r for r in records}
    pairs = select_pairs(split, records_by_id, seed=1, max_pairs_per_kind=50)
    seen = set()
    for pair in pairs:
        key = frozenset((pair.reference_record_id, pair.candidate_record_id))
        assert key not in seen
        seen.add(key)


def test_select_pairs_respects_max_pairs_per_kind():
    records = _many_speaker_records(speaker_count=20, utterances_per_speaker=20)
    config = SplitConfig(strategy=SplitStrategy.SAME_SPEAKER, proportions=SplitProportions(0.6, 0.2, 0.2), seed=1)
    split = split_records("fixture-corpus", records, config)
    records_by_id = {r.record_id: r for r in records}
    pairs = select_pairs(split, records_by_id, seed=1, max_pairs_per_kind=3)
    for kind in PairKind:
        assert sum(1 for p in pairs if p.kind is kind) <= 3


def test_select_pairs_rejects_non_positive_max_pairs():
    records = _many_speaker_records()
    config = SplitConfig(strategy=SplitStrategy.SAME_SPEAKER, proportions=SplitProportions(0.6, 0.2, 0.2), seed=1)
    split = split_records("fixture-corpus", records, config)
    records_by_id = {r.record_id: r for r in records}
    with pytest.raises(ValueError, match="positive"):
        select_pairs(split, records_by_id, seed=1, max_pairs_per_kind=0)


def test_train_reference_to_held_out_pairs_are_empty_under_held_out_speaker_strategy():
    """A held-out speaker never appears in train by construction -- this
    category must yield zero pairs, not an error, under this strategy."""
    records = _many_speaker_records(speaker_count=10, utterances_per_speaker=10)
    config = SplitConfig(
        strategy=SplitStrategy.HELD_OUT_SPEAKER, proportions=SplitProportions(0.6, 0.2, 0.2), seed=1
    )
    split = split_records("fixture-corpus", records, config)
    records_by_id = {r.record_id: r for r in records}
    pairs = select_pairs(split, records_by_id, seed=1, max_pairs_per_kind=10)
    assert not any(p.kind is PairKind.TRAIN_REFERENCE_TO_HELD_OUT for p in pairs)


def test_train_reference_to_held_out_pairs_exist_under_same_speaker_strategy():
    records = _many_speaker_records(speaker_count=10, utterances_per_speaker=10)
    config = SplitConfig(strategy=SplitStrategy.SAME_SPEAKER, proportions=SplitProportions(0.6, 0.2, 0.2), seed=1)
    split = split_records("fixture-corpus", records, config)
    records_by_id = {r.record_id: r for r in records}
    pairs = select_pairs(split, records_by_id, seed=1, max_pairs_per_kind=10)
    assert any(p.kind is PairKind.TRAIN_REFERENCE_TO_HELD_OUT for p in pairs)


def test_different_speaker_pairs_are_actually_different_speakers():
    records = _many_speaker_records()
    config = SplitConfig(strategy=SplitStrategy.SAME_SPEAKER, proportions=SplitProportions(0.6, 0.2, 0.2), seed=1)
    split = split_records("fixture-corpus", records, config)
    records_by_id = {r.record_id: r for r in records}
    pairs = select_pairs(split, records_by_id, seed=1, max_pairs_per_kind=20)
    for pair in pairs:
        if pair.kind is PairKind.DIFFERENT_SPEAKER:
            ref_speaker = records_by_id[pair.reference_record_id].speaker_id
            cand_speaker = records_by_id[pair.candidate_record_id].speaker_id
            assert ref_speaker != cand_speaker


# -- deterministic evaluation ------------------------------------------------


def test_select_pairs_is_deterministic_for_the_same_seed():
    records = _many_speaker_records()
    config = SplitConfig(strategy=SplitStrategy.SAME_SPEAKER, proportions=SplitProportions(0.6, 0.2, 0.2), seed=7)
    split = split_records("fixture-corpus", records, config)
    records_by_id = {r.record_id: r for r in records}
    first = select_pairs(split, records_by_id, seed=99, max_pairs_per_kind=10)
    second = select_pairs(split, records_by_id, seed=99, max_pairs_per_kind=10)
    assert first == second


# -- empty / invalid input ----------------------------------------------------


def test_evaluate_pairs_on_empty_input_returns_a_zeroed_summary():
    summary = evaluate_pairs((), lambda record_id: (1.0, 0.0))
    assert summary.pairs_attempted == 0
    assert summary.coverage == 0.0
    assert summary.results == ()


# -- embedding failure handling ------------------------------------------------


def test_evaluate_pairs_records_a_failed_embedding_without_crashing():
    pair = EvaluationPair("p1", PairKind.SAME_SPEAKER_HELD_OUT, "r1", "r2")

    def flaky_embed(record_id):
        return None if record_id == "r2" else (1.0, 0.0, 0.0)

    summary = evaluate_pairs((pair,), flaky_embed)
    assert summary.pairs_succeeded == 0
    assert summary.pairs_failed == 1
    assert summary.results[0].error is not None
    assert summary.embeddings_failed == 1


def test_evaluate_pairs_caches_embeddings_so_a_shared_record_is_embedded_once():
    calls = []

    def counting_embed(record_id):
        calls.append(record_id)
        return (1.0, 0.0)

    pairs = (
        EvaluationPair("p1", PairKind.SAME_SPEAKER_HELD_OUT, "r1", "r2"),
        EvaluationPair("p2", PairKind.SAME_SPEAKER_HELD_OUT, "r1", "r3"),
    )
    summary = evaluate_pairs(pairs, counting_embed)
    assert summary.embeddings_attempted == 3
    assert calls.count("r1") == 1


def test_evaluate_pairs_reports_real_similarity_statistics():
    vectors = {"a": (1.0, 0.0), "b": (0.9, 0.1), "c": (-1.0, 0.0)}
    pairs = (
        EvaluationPair("p1", PairKind.SAME_SPEAKER_HELD_OUT, "a", "b"),
        EvaluationPair("p2", PairKind.DIFFERENT_SPEAKER, "a", "c"),
    )
    summary = evaluate_pairs(pairs, lambda rid: vectors[rid])
    assert summary.pairs_succeeded == 2
    assert summary.coverage == 1.0
    same_speaker_stats = next(k for k in summary.by_kind if k.kind is PairKind.SAME_SPEAKER_HELD_OUT)
    different_speaker_stats = next(k for k in summary.by_kind if k.kind is PairKind.DIFFERENT_SPEAKER)
    assert same_speaker_stats.count == 1
    assert different_speaker_stats.count == 1
    assert same_speaker_stats.mean > different_speaker_stats.mean


# -- result serialization ------------------------------------------------------


def test_summary_to_dict_round_trips():
    pair = EvaluationPair("p1", PairKind.SAME_SPEAKER_HELD_OUT, "r1", "r2")
    summary = evaluate_pairs((pair,), lambda rid: (1.0, 0.0))
    as_dict = summary.to_dict()
    assert as_dict["pairs_attempted"] == 1
    assert as_dict["pairs_succeeded"] == 1
    assert as_dict["results"][0]["pair"]["pair_id"] == "p1"
    assert as_dict["results"][0]["similarity"] == pytest.approx(1.0)


def test_pair_result_ok_reflects_similarity_presence():
    pair = EvaluationPair("p1", PairKind.SAME_SPEAKER_HELD_OUT, "r1", "r2")
    assert PairResult(pair, 0.5).ok is True
    assert PairResult(pair, None, error="boom").ok is False


# -- bounded real-data integration verification -----------------------------

REAL_LIBRISPEECH_ROOT = "public_datasets/librispeech/extracted/LibriSpeech/dev-clean"


@pytest.mark.skipif(
    not os.path.isdir(REAL_LIBRISPEECH_ROOT),
    reason="real LibriSpeech dev-clean not present in this environment (git-ignored, never committed)",
)
def test_select_pairs_against_the_real_librispeech_metadata_is_leakage_free():
    """Bounded: exercises pair selection against real dataset metadata
    (real record ids, real speaker ids) without the slow, ML-runtime-
    dependent real embedding step -- that end-to-end path is verified
    separately, on demand, by scripts/run_speaker_similarity_evaluation.py,
    not as part of the portable test suite."""
    adapter = LibriSpeechDatasetAdapter(Path(REAL_LIBRISPEECH_ROOT), dataset_id="librispeech-dev-clean")
    records = list(adapter.iter_records())
    records_by_id = {r.record_id: r for r in records}

    config = SplitConfig(strategy=SplitStrategy.SAME_SPEAKER, proportions=SplitProportions(0.7, 0.15, 0.15), seed=42)
    split = split_records("librispeech-dev-clean", records, config)
    pairs = select_pairs(split, records_by_id, seed=42, max_pairs_per_kind=10)

    assert pairs
    seen = set()
    for pair in pairs:
        assert pair.reference_record_id != pair.candidate_record_id
        key = frozenset((pair.reference_record_id, pair.candidate_record_id))
        assert key not in seen
        seen.add(key)
        if pair.kind is PairKind.DIFFERENT_SPEAKER:
            ref_speaker = records_by_id[pair.reference_record_id].speaker_id
            cand_speaker = records_by_id[pair.candidate_record_id].speaker_id
            assert ref_speaker != cand_speaker


def test_evaluate_pairs_handles_a_nan_free_real_number_line_correctly():
    # Guards against a future refactor silently introducing NaN through
    # a division; NaN must never compare as a valid similarity.
    pair = EvaluationPair("p1", PairKind.SAME_SPEAKER_HELD_OUT, "r1", "r2")
    summary = evaluate_pairs((pair,), lambda rid: (1.0, 0.0))
    score = summary.results[0].similarity
    assert not math.isnan(score)
