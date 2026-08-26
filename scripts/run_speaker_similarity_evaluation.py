#!/usr/bin/env python3
"""Real speaker-similarity baseline: wires `pipeline.speaker_similarity`'s
pure pair-selection/scoring logic to the real `LocalNeuralEmbeddingProvider`
(NeMo titanet_large) and a real dataset adapter's output.

Bounded by design (`--max-pairs-per-kind`): each embedding call spawns a
fresh subprocess that reloads the model from disk (no persistent model
server in this project's architecture -- see docs/REAL_ML_RUNTIME_INTEGRATION.md),
so embedding the full corpus is impractical. This produces a real,
reproducible baseline from a bounded, honestly-reported sample -- never
a claim of full-corpus coverage.

Never touches data/source/ (the protected private-recording tree); every
record here comes from a registered public dataset via its adapter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from aarya_voice_lab.audio.probe import read_wav_mono_samples
from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.identity.embeddings import (
    EmbeddingProviderError,
    LocalNeuralEmbeddingProvider,
    get_provider,
)
from aarya_voice_lab.pipeline.dataset_adapter import LibriSpeechDatasetAdapter
from aarya_voice_lab.pipeline.dataset_split import SplitConfig, SplitProportions, SplitStrategy, split_records
from aarya_voice_lab.pipeline.normalization import NormalizationBlocked, NormalizationConfig, normalize_file
from aarya_voice_lab.pipeline.speaker_similarity import evaluate_pairs, select_pairs
from aarya_voice_lab.pipeline.speaker_similarity_experiment import build_experiment_record
from aarya_voice_lab.registry.experiment_registry import ExperimentRegistry


def _make_embed_record(records_by_id, scratch_dir: Path, data_root: DataRoot, provider):
    """Real, on-demand normalize -> decode -> embed for one record_id.
    Returns None on any failure rather than raising, and records the
    reason so the caller can report exactly what failed and why."""
    failures: dict[str, str] = {}

    def embed_record(record_id: str):
        record = records_by_id[record_id]
        source_path = Path(record.audio_ref)
        wav_path = scratch_dir / f"{record_id}.wav"
        try:
            if not wav_path.is_file():
                source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
                normalize_file(
                    source_path,
                    wav_path,
                    source_file_id=record_id,
                    source_sha256=source_sha256,
                    data_root=data_root,
                    config=NormalizationConfig(),
                )
            samples, sample_rate = read_wav_mono_samples(wav_path)
            vector = provider.embed(samples, sample_rate)
            return tuple(vector.values)
        except (NormalizationBlocked, EmbeddingProviderError, OSError) as exc:
            failures[record_id] = str(exc)
            return None

    return embed_record, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", help="LibriSpeech-shaped dataset root")
    parser.add_argument("--dataset-id", default="librispeech-dev-clean")
    parser.add_argument("--strategy", choices=[s.value for s in SplitStrategy], default="same_speaker")
    parser.add_argument("--split-seed", type=int, default=42)
    parser.add_argument("--pair-seed", type=int, default=42)
    parser.add_argument("--max-pairs-per-kind", type=int, default=10)
    parser.add_argument("--scratch-dir", type=Path, default=Path("data/working/similarity-eval"))
    parser.add_argument(
        "--persist", action="store_true", help="Register this run in experiments/registry.jsonl (git-ignored)."
    )
    parser.add_argument("--dataset-version", default="dev-clean")
    parser.add_argument("--dataset-provenance", default="openslr.org/12, CC BY 4.0")
    args = parser.parse_args()

    provider = get_provider(LocalNeuralEmbeddingProvider.name)
    state = provider.capability_state()
    if state["state"] != "AVAILABLE":
        print(f"BLOCKED: embedding provider is not available: {state}", file=sys.stderr)
        return 3

    adapter = LibriSpeechDatasetAdapter(Path(args.root), dataset_id=args.dataset_id)
    records = list(adapter.iter_records())
    records_by_id = {r.record_id: r for r in records}

    split_config = SplitConfig(
        strategy=SplitStrategy(args.strategy), proportions=SplitProportions(0.7, 0.15, 0.15), seed=args.split_seed
    )
    split = split_records(args.dataset_id, records, split_config)
    pairs = select_pairs(split, records_by_id, seed=args.pair_seed, max_pairs_per_kind=args.max_pairs_per_kind)

    args.scratch_dir.mkdir(parents=True, exist_ok=True)
    data_root = DataRoot.default()
    embed_record, failures = _make_embed_record(records_by_id, args.scratch_dir, data_root, provider)

    print(f"Evaluating {len(pairs)} pairs (max {args.max_pairs_per_kind} per kind)...", file=sys.stderr)
    summary = evaluate_pairs(pairs, embed_record)

    output = summary.to_dict()
    output["dataset_id"] = args.dataset_id
    output["split_config"] = split_config.to_dict()
    output["embedding_failures"] = failures
    output["existing_project_thresholds"] = {
        "note": (
            "identity.calibration's default speaker-VERIFICATION acceptance "
            "thresholds (a different use case: live accept/reject decisions, "
            "not a corpus-wide benchmark) -- cited for context only, not applied "
            "as a pass/fail bar for this evaluation."
        ),
        "operator_rejection_threshold": 0.55,
        "target_review_threshold": 0.65,
        "target_acceptance_threshold": 0.85,
    }

    if args.persist:
        import dataclasses
        import subprocess

        from aarya_voice_lab import system_info
        from aarya_voice_lab.pipeline.runner import EnvironmentId, default_environment_root

        def _worker_software_versions() -> dict[str, str]:
            """Real torch/nemo_toolkit versions come from the isolated
            .envs/env-nemo interpreter that actually did the embedding work
            -- the base interpreter deliberately has neither installed (see
            identity.embeddings' module docstring), so querying it would
            report "unknown" for values that are, in fact, known and real."""
            env_python = default_environment_root(EnvironmentId.NEMO).python
            versions = {"python": sys.version.split()[0]}
            try:
                result = subprocess.run(
                    [str(env_python), "-m", "aarya_voice_lab.cli.main", "nemo-check", "--json"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                report = json.loads(result.stdout)
                for capability in report.get("capabilities", []):
                    if capability["name"] in ("torch", "nemo_toolkit") and capability.get("version"):
                        versions[capability["name"]] = capability["version"]
            except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
                pass
            return versions

        record = build_experiment_record(
            dataset_id=args.dataset_id,
            dataset_version=args.dataset_version,
            dataset_provenance=args.dataset_provenance,
            split=split,
            pair_seed=args.pair_seed,
            max_pairs_per_kind=args.max_pairs_per_kind,
            records_by_id=records_by_id,
            summary=summary,
            provider_name=provider.name,
            model_name="titanet_large",
            model_version=provider.version,
            embedding_dimension=192,
            software_versions=_worker_software_versions(),
            hardware=dataclasses.asdict(system_info.collect_system_report()),
        )
        registry = ExperimentRegistry()
        registry.add(record)
        output["persisted_experiment_id"] = record["experiment_id"]
        print(f"Persisted as {record['experiment_id']}", file=sys.stderr)

    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
