from __future__ import annotations

import os
from pathlib import Path

import pytest

from aarya_voice_lab.pipeline.dataset_adapter import LibriSpeechDatasetAdapter, NormalizedRecord
from aarya_voice_lab.pipeline.dataset_split import SplitConfig, SplitProportions, SplitStrategy, split_records
from aarya_voice_lab.pipeline.speaker_similarity import evaluate_pairs, select_pairs
from aarya_voice_lab.pipeline.speaker_similarity_experiment import (
    ReproducibilityCheckError,
    build_experiment_record,
    verify_pair_selection_reproducibility,
)
from aarya_voice_lab.registry.experiment_registry import ExperimentRegistry
from aarya_voice_lab.schemas.base import ValidationError


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


def _fake_vector(record_id: str) -> tuple[float, ...]:
    # Deterministic per-speaker "embedding" -- same speaker -> near-identical
    # vector, different speaker -> orthogonal-ish -- just enough structure
    # for a real, non-degenerate similarity computation in tests.
    speaker = record_id.split("-utt-")[0]
    seed = sum(ord(c) for c in speaker)
    return (float(seed % 7), float(seed % 5), 1.0)


def _run_full_evaluation(records, strategy=SplitStrategy.SAME_SPEAKER, split_seed=1, pair_seed=1, max_pairs=5):
    records_by_id = {r.record_id: r for r in records}
    split_config = SplitConfig(strategy=strategy, proportions=SplitProportions(0.6, 0.2, 0.2), seed=split_seed)
    split = split_records("fixture-corpus", records, split_config)
    pairs = select_pairs(split, records_by_id, seed=pair_seed, max_pairs_per_kind=max_pairs)
    summary = evaluate_pairs(pairs, lambda rid: _fake_vector(rid))
    return records_by_id, split, pairs, summary


# -- expanded pair configuration ----------------------------------------------


def test_evaluation_scales_to_a_larger_bounded_sample():
    records = _many_speaker_records(speaker_count=20, utterances_per_speaker=20)
    _, _, pairs, summary = _run_full_evaluation(records, max_pairs=40)
    assert summary.pairs_attempted == len(pairs)
    assert summary.pairs_succeeded == len(pairs)
    assert summary.coverage == 1.0


# -- persistence / serialization ------------------------------------------------


def test_build_experiment_record_validates_against_the_real_schema(tmp_path):
    records = _many_speaker_records()
    records_by_id, split, pairs, summary = _run_full_evaluation(records)
    record = build_experiment_record(
        dataset_id="fixture-corpus",
        dataset_version="fixture-v1",
        dataset_provenance="synthetic fixture, not a real download",
        split=split,
        pair_seed=1,
        max_pairs_per_kind=5,
        records_by_id=records_by_id,
        summary=summary,
        provider_name="local-neural-embedding",
        model_name="titanet_large",
        model_version="1.0.0",
        embedding_dimension=192,
        software_versions={"torch": "2.13.0+cpu", "nemo_toolkit": "3.0.0"},
    )

    registry = ExperimentRegistry(path=tmp_path / "registry.jsonl")
    registry.add(record)  # raises on schema mismatch -- this is the real check
    assert registry.get(record["experiment_id"]) == record


def test_experiment_id_is_deterministic_for_the_same_configuration():
    records = _many_speaker_records()
    records_by_id, split, pairs, summary = _run_full_evaluation(records)
    kwargs = dict(
        dataset_id="fixture-corpus",
        dataset_version="fixture-v1",
        dataset_provenance="synthetic fixture",
        split=split,
        pair_seed=1,
        max_pairs_per_kind=5,
        records_by_id=records_by_id,
        summary=summary,
        provider_name="local-neural-embedding",
        model_name="titanet_large",
        model_version="1.0.0",
        embedding_dimension=192,
        software_versions={"torch": "2.13.0+cpu"},
    )
    first = build_experiment_record(**kwargs)
    second = build_experiment_record(**kwargs, created_at="2026-01-01T00:00:00+00:00")
    assert first["experiment_id"] == second["experiment_id"]


def test_experiment_id_differs_for_a_different_pair_seed():
    records = _many_speaker_records()
    records_by_id, split, _, summary_a = _run_full_evaluation(records, pair_seed=1)
    _, _, _, summary_b = _run_full_evaluation(records, pair_seed=2)
    record_a = build_experiment_record(
        dataset_id="fixture-corpus", dataset_version="v1", dataset_provenance="p", split=split, pair_seed=1,
        max_pairs_per_kind=5, records_by_id=records_by_id, summary=summary_a, provider_name="local-neural-embedding",
        model_name="titanet_large", model_version="1.0.0", embedding_dimension=192, software_versions={},
    )
    record_b = build_experiment_record(
        dataset_id="fixture-corpus", dataset_version="v1", dataset_provenance="p", split=split, pair_seed=2,
        max_pairs_per_kind=5, records_by_id=records_by_id, summary=summary_b, provider_name="local-neural-embedding",
        model_name="titanet_large", model_version="1.0.0", embedding_dimension=192, software_versions={},
    )
    assert record_a["experiment_id"] != record_b["experiment_id"]


def test_re_registering_the_identical_experiment_is_refused_like_every_other_registry(tmp_path):
    records = _many_speaker_records()
    records_by_id, split, _, summary = _run_full_evaluation(records)
    record = build_experiment_record(
        dataset_id="fixture-corpus", dataset_version="v1", dataset_provenance="p", split=split, pair_seed=1,
        max_pairs_per_kind=5, records_by_id=records_by_id, summary=summary, provider_name="local-neural-embedding",
        model_name="titanet_large", model_version="1.0.0", embedding_dimension=192, software_versions={},
    )
    registry = ExperimentRegistry(path=tmp_path / "registry.jsonl")
    registry.add(record)
    with pytest.raises(ValueError, match="already exists"):
        registry.add(record)


def test_experiment_record_preserves_record_and_speaker_ids_per_pair():
    records = _many_speaker_records()
    records_by_id, split, pairs, summary = _run_full_evaluation(records)
    record = build_experiment_record(
        dataset_id="fixture-corpus", dataset_version="v1", dataset_provenance="p", split=split, pair_seed=1,
        max_pairs_per_kind=5, records_by_id=records_by_id, summary=summary, provider_name="local-neural-embedding",
        model_name="titanet_large", model_version="1.0.0", embedding_dimension=192, software_versions={},
    )
    assert record["configuration"]["pairs"]
    for pair_record in record["configuration"]["pairs"]:
        assert pair_record["reference_speaker_id"] is not None
        assert pair_record["candidate_speaker_id"] is not None
        assert pair_record["reference_record_id"] in records_by_id
        assert pair_record["candidate_record_id"] in records_by_id


# -- deterministic replay / reproducibility -------------------------------------


def test_verify_pair_selection_reproducibility_confirms_a_matching_record():
    records = _many_speaker_records()
    records_by_id, split, pairs, summary = _run_full_evaluation(records)
    record = build_experiment_record(
        dataset_id="fixture-corpus", dataset_version="v1", dataset_provenance="p", split=split, pair_seed=1,
        max_pairs_per_kind=5, records_by_id=records_by_id, summary=summary, provider_name="local-neural-embedding",
        model_name="titanet_large", model_version="1.0.0", embedding_dimension=192, software_versions={},
    )
    matches, recomputed = verify_pair_selection_reproducibility(record, records)
    assert matches is True
    assert len(recomputed) == len(pairs)


def test_verify_pair_selection_reproducibility_detects_a_tampered_record():
    records = _many_speaker_records()
    records_by_id, split, pairs, summary = _run_full_evaluation(records)
    record = build_experiment_record(
        dataset_id="fixture-corpus", dataset_version="v1", dataset_provenance="p", split=split, pair_seed=1,
        max_pairs_per_kind=5, records_by_id=records_by_id, summary=summary, provider_name="local-neural-embedding",
        model_name="titanet_large", model_version="1.0.0", embedding_dimension=192, software_versions={},
    )
    record["configuration"]["pairs"][0]["reference_record_id"] = "tampered-record-id"
    matches, _ = verify_pair_selection_reproducibility(record, records)
    assert matches is False


def test_verify_pair_selection_reproducibility_raises_on_missing_configuration_field():
    del_record = {"configuration": {"dataset_id": "x"}}
    with pytest.raises(ReproducibilityCheckError):
        verify_pair_selection_reproducibility(del_record, [])


# -- invalid persisted data ------------------------------------------------------


def test_registering_a_record_missing_a_required_field_is_refused(tmp_path):
    records = _many_speaker_records()
    records_by_id, split, _, summary = _run_full_evaluation(records)
    record = build_experiment_record(
        dataset_id="fixture-corpus", dataset_version="v1", dataset_provenance="p", split=split, pair_seed=1,
        max_pairs_per_kind=5, records_by_id=records_by_id, summary=summary, provider_name="local-neural-embedding",
        model_name="titanet_large", model_version="1.0.0", embedding_dimension=192, software_versions={},
    )
    del record["model_version"]
    registry = ExperimentRegistry(path=tmp_path / "registry.jsonl")
    with pytest.raises(ValidationError):
        registry.add(record)


# -- leakage checks (re-exercised at this layer) ---------------------------------


def test_persisted_pairs_contain_no_self_comparisons_or_duplicates():
    records = _many_speaker_records(speaker_count=15, utterances_per_speaker=15)
    records_by_id, split, pairs, summary = _run_full_evaluation(records, max_pairs=20)
    record = build_experiment_record(
        dataset_id="fixture-corpus", dataset_version="v1", dataset_provenance="p", split=split, pair_seed=1,
        max_pairs_per_kind=20, records_by_id=records_by_id, summary=summary, provider_name="local-neural-embedding",
        model_name="titanet_large", model_version="1.0.0", embedding_dimension=192, software_versions={},
    )
    seen = set()
    for pair_record in record["configuration"]["pairs"]:
        ref, cand = pair_record["reference_record_id"], pair_record["candidate_record_id"]
        assert ref != cand
        key = frozenset((ref, cand))
        assert key not in seen
        seen.add(key)


# -- backwards compatibility with the 24-pair baseline ---------------------------


def test_max_pairs_per_kind_of_eight_still_produces_a_valid_record(tmp_path):
    """The original milestone's baseline used max_pairs_per_kind=8 (24
    total pairs across 3 categories) -- confirms the persistence layer
    added this milestone handles that exact historical configuration
    without any special-casing."""
    records = _many_speaker_records(speaker_count=10, utterances_per_speaker=10)
    records_by_id, split, pairs, summary = _run_full_evaluation(records, max_pairs=8)
    record = build_experiment_record(
        dataset_id="fixture-corpus", dataset_version="v1", dataset_provenance="p", split=split, pair_seed=1,
        max_pairs_per_kind=8, records_by_id=records_by_id, summary=summary, provider_name="local-neural-embedding",
        model_name="titanet_large", model_version="1.0.0", embedding_dimension=192, software_versions={},
    )
    registry = ExperimentRegistry(path=tmp_path / "registry.jsonl")
    registry.add(record)
    assert record["configuration"]["max_pairs_per_kind"] == 8


# -- bounded real-data integration verification ----------------------------------

REAL_LIBRISPEECH_ROOT = "public_datasets/librispeech/extracted/LibriSpeech/dev-clean"


@pytest.mark.skipif(
    not os.path.isdir(REAL_LIBRISPEECH_ROOT),
    reason="real LibriSpeech dev-clean not present in this environment (git-ignored, never committed)",
)
def test_experiment_record_from_real_metadata_is_schema_valid_and_reproducible(tmp_path):
    """Bounded: builds a real record from real LibriSpeech metadata and a
    fake (non-ML) embed function -- proves the persistence/reproducibility
    layer against real record ids/speaker ids without requiring the slow
    real embedding provider in the portable test suite."""
    adapter = LibriSpeechDatasetAdapter(Path(REAL_LIBRISPEECH_ROOT), dataset_id="librispeech-dev-clean")
    records = list(adapter.iter_records())
    records_by_id, split, pairs, summary = _run_full_evaluation(records, split_seed=42, pair_seed=42, max_pairs=5)

    record = build_experiment_record(
        dataset_id="librispeech-dev-clean",
        dataset_version="dev-clean",
        dataset_provenance="openslr.org/12, CC BY 4.0",
        split=split,
        pair_seed=42,
        max_pairs_per_kind=5,
        records_by_id=records_by_id,
        summary=summary,
        provider_name="local-neural-embedding",
        model_name="titanet_large",
        model_version="1.0.0",
        embedding_dimension=192,
        software_versions={"torch": "2.13.0+cpu", "nemo_toolkit": "3.0.0"},
    )

    registry = ExperimentRegistry(path=tmp_path / "registry.jsonl")
    registry.add(record)

    matches, _ = verify_pair_selection_reproducibility(record, records)
    assert matches is True
