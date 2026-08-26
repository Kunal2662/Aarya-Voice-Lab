"""Persistence for a speaker-similarity evaluation run, reusing the
existing `registry.experiment_registry.ExperimentRegistry`
(`experiments/registry.jsonl`, git-ignored) rather than inventing a new
registry -- this evaluation is exactly the kind of run
`docs/MODEL_STRATEGY.md` already designed that registry to capture
("dataset version, model + version, configuration, ..., metrics, ...").
`docs/BENCHMARKING.md`'s `benchmark.schema.json` was considered and
rejected for this purpose: it is shaped for grading one trained voice
model's output (`model_name`/`model_version` required, a single scalar
`speaker_similarity` 0-1), not for recording a provider/dataset-level
evaluation methodology with per-category statistics and a full pair
list -- forcing this into that schema would lose almost everything
Phase 3 of this milestone requires recording.

`experiment_id` is deterministic (a hash of every input that would
change the result), not timestamp-based: re-running the identical
experiment attempts to register the identical id, and
`ExperimentRegistry.add()`'s existing refuse-duplicate-id discipline
correctly refuses the second attempt -- the same behavior every other
registry in this project already has for exactly this reason.

Reproducibility comes from the persisted `configuration` block alone:
`verify_pair_selection_reproducibility()` recomputes pair selection from
those exact inputs and confirms it matches the persisted pair list,
without re-embedding anything (which would be slow -- see
scripts/run_speaker_similarity_evaluation.py's own docstring on why).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from aarya_voice_lab.pipeline.dataset_adapter import NormalizedRecord
from aarya_voice_lab.pipeline.dataset_split import (
    DatasetSplit,
    SplitConfig,
    SplitProportions,
    SplitStrategy,
    split_records,
)
from aarya_voice_lab.pipeline.speaker_similarity import EvaluationPair, SimilarityEvaluationSummary, select_pairs

RECORD_SHAPE_VERSION = "1.0.0"


def _config_hash(
    dataset_id: str,
    split_config: SplitConfig,
    pair_seed: int,
    max_pairs_per_kind: int,
    provider_name: str,
    model_version: str,
) -> str:
    payload = json.dumps(
        {
            "dataset_id": dataset_id,
            "split_config": split_config.to_dict(),
            "pair_seed": pair_seed,
            "max_pairs_per_kind": max_pairs_per_kind,
            "provider_name": provider_name,
            "model_version": model_version,
        },
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def build_experiment_record(
    *,
    dataset_id: str,
    dataset_version: str,
    dataset_provenance: str,
    split: DatasetSplit,
    pair_seed: int,
    max_pairs_per_kind: int,
    records_by_id: dict[str, NormalizedRecord],
    summary: SimilarityEvaluationSummary,
    provider_name: str,
    model_name: str,
    model_version: str,
    embedding_dimension: int,
    software_versions: dict[str, str],
    hardware: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build one `experiments/registry.jsonl` entry for a completed
    speaker-similarity evaluation run. Every field `schemas/experiment.schema.json`
    requires or declares is populated from real values already computed
    by the caller -- nothing here is invented."""
    config_hash = _config_hash(dataset_id, split.config, pair_seed, max_pairs_per_kind, provider_name, model_version)
    experiment_id = f"speaker-similarity-{dataset_id}-{config_hash}"

    metrics: dict[str, float] = {
        "pairs_attempted": float(summary.pairs_attempted),
        "pairs_succeeded": float(summary.pairs_succeeded),
        "pairs_failed": float(summary.pairs_failed),
        "coverage": summary.coverage,
    }
    for kind_stats in summary.by_kind:
        prefix = kind_stats.kind.value
        metrics[f"{prefix}_count"] = float(kind_stats.count)
        for field_name in ("mean", "median", "stdev", "minimum", "maximum", "p10", "p25", "p50", "p75", "p90"):
            value = getattr(kind_stats, field_name)
            if value is not None:
                metrics[f"{prefix}_{field_name}"] = value

    pair_records = []
    for result in summary.results:
        pair = result.pair
        ref_record = records_by_id.get(pair.reference_record_id)
        cand_record = records_by_id.get(pair.candidate_record_id)
        pair_records.append(
            {
                "pair_id": pair.pair_id,
                "kind": pair.kind.value,
                "reference_record_id": pair.reference_record_id,
                "candidate_record_id": pair.candidate_record_id,
                "reference_speaker_id": ref_record.speaker_id if ref_record else None,
                "candidate_speaker_id": cand_record.speaker_id if cand_record else None,
                "similarity": result.similarity,
                "error": result.error,
            }
        )

    return {
        "schema_version": "0.1.0",
        "experiment_id": experiment_id,
        "created_at": created_at or datetime.now(UTC).isoformat(),
        "dataset_version": dataset_version,
        "model": model_name,
        "model_version": model_version,
        "configuration": {
            "record_shape_version": RECORD_SHAPE_VERSION,
            "dataset_id": dataset_id,
            "dataset_provenance": dataset_provenance,
            "split_strategy": split.config.strategy.value,
            "split_seed": split.config.seed,
            "split_proportions": split.config.proportions.to_dict(),
            "split_config_hash": split.config.config_hash(),
            "pair_seed": pair_seed,
            "max_pairs_per_kind": max_pairs_per_kind,
            "provider_name": provider_name,
            "embedding_dimension": embedding_dimension,
            "metric": "cosine_similarity",
            "pairs": pair_records,
        },
        "hardware": hardware or {},
        "software_versions": software_versions,
        "metrics": metrics,
        "benchmark_results": None,
        "status": "completed",
        "notes": (
            "Speaker-similarity baseline only -- an identity/embedding metric, "
            "not a claim of TTS quality, voice-cloning quality, model quality, "
            "or production readiness. No training or generation was performed."
        ),
    }


class ReproducibilityCheckError(ValueError):
    """Raised when a persisted experiment record is missing a field
    `verify_pair_selection_reproducibility()` needs to recompute pair
    selection."""


def verify_pair_selection_reproducibility(
    record: dict[str, Any], records: list[NormalizedRecord]
) -> tuple[bool, tuple[EvaluationPair, ...]]:
    """Recompute pair selection from a persisted record's own
    `configuration` and confirm it matches the persisted pair list
    exactly -- no re-embedding required. Returns `(matches, recomputed_pairs)`."""
    try:
        config = record["configuration"]
        dataset_id = config["dataset_id"]
        proportions = SplitProportions(**config["split_proportions"])
        split_config = SplitConfig(
            strategy=SplitStrategy(config["split_strategy"]), proportions=proportions, seed=config["split_seed"]
        )
        pair_seed = config["pair_seed"]
        max_pairs_per_kind = config["max_pairs_per_kind"]
        persisted_pairs = config["pairs"]
    except KeyError as exc:
        raise ReproducibilityCheckError(f"persisted record is missing required field: {exc}") from exc

    records_by_id = {r.record_id: r for r in records}
    split = split_records(dataset_id, records, split_config)
    recomputed_pairs = select_pairs(split, records_by_id, seed=pair_seed, max_pairs_per_kind=max_pairs_per_kind)

    persisted_keys = [(p["kind"], p["reference_record_id"], p["candidate_record_id"]) for p in persisted_pairs]
    recomputed_keys = [(p.kind.value, p.reference_record_id, p.candidate_record_id) for p in recomputed_pairs]
    return persisted_keys == recomputed_keys, recomputed_pairs
