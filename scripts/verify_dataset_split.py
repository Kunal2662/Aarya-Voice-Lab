#!/usr/bin/env python3
"""One-shot verification of pipeline.dataset_split against a real dataset
adapter's output: builds both split strategies, checks leakage (using real
content hashes and durations recovered from a prior validate-audio JSON
run, when supplied), and proves reproducibility. Prints a concise
machine-readable summary; writes nothing to the repository.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aarya_voice_lab.pipeline.dataset_adapter import LibriSpeechDatasetAdapter
from aarya_voice_lab.pipeline.dataset_split import (
    SplitConfig,
    SplitProportions,
    SplitStrategy,
    check_leakage,
    split_records,
)


def _load_side_channel(
    validate_json_path: Path | None, inventory_json_path: Path | None
) -> tuple[dict[str, float], dict[str, str]]:
    """Recover real per-record duration (from a prior `validate-audio
    --json` run) and real per-record SHA-256 (from a prior `inventory
    --json` run), both keyed by filename stem -- the same scheme
    LibriSpeechDatasetAdapter uses for record_id. Avoids re-running
    ffprobe/hashing a second time for a report that only needs numbers
    already measured once, for real, earlier in this session."""
    durations: dict[str, float] = {}
    if validate_json_path is not None and validate_json_path.is_file():
        data = json.loads(validate_json_path.read_text(encoding="utf-8"))
        for entry in data.get("results", []):
            record_id = Path(entry["path"]).stem
            duration = entry.get("properties", {}).get("duration_seconds")
            if duration is not None:
                durations[record_id] = duration

    hashes: dict[str, str] = {}
    if inventory_json_path is not None and inventory_json_path.is_file():
        data = json.loads(inventory_json_path.read_text(encoding="utf-8"))
        for entry in data.get("files", []):
            record_id = Path(entry["path"]).stem
            if entry.get("sha256"):
                hashes[record_id] = entry["sha256"]

    return durations, hashes


def _split_summary(name, ids, records_by_id, durations):
    speakers = {records_by_id[i].speaker_id for i in ids if i in records_by_id}
    total_duration = sum(durations.get(i, 0.0) for i in ids)
    print(f"{name}")
    print(f"  records  : {len(ids)}")
    print(f"  speakers : {len(speakers)}")
    print(f"  duration : {total_duration:.1f}s ({total_duration / 3600:.2f}h)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", help="LibriSpeech-shaped dataset root")
    parser.add_argument("--dataset-id", default="librispeech-dev-clean")
    parser.add_argument("--strategy", choices=[s.value for s in SplitStrategy], default="held_out_speaker")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--durations-json", type=Path, default=None, help="prior validate-audio --json output")
    parser.add_argument("--inventory-json", type=Path, default=None, help="prior inventory --json output")
    args = parser.parse_args()

    adapter = LibriSpeechDatasetAdapter(Path(args.root), dataset_id=args.dataset_id)
    records = list(adapter.iter_records())
    records_by_id = {r.record_id: r for r in records}
    durations, hashes = _load_side_channel(args.durations_json, args.inventory_json)

    config = SplitConfig(
        strategy=SplitStrategy(args.strategy), proportions=SplitProportions(0.7, 0.15, 0.15), seed=args.seed
    )
    result = split_records(args.dataset_id, records, config)
    report = check_leakage(result, records_by_id, content_hashes=hashes or None, expected_record_ids=set(records_by_id))

    print(f"Dataset: {args.dataset_id}  ({len(records)} records, strategy={args.strategy}, seed={args.seed})")
    print()
    _split_summary("TRAIN", result.train_record_ids, records_by_id, durations)
    print()
    _split_summary("VALIDATION", result.validation_record_ids, records_by_id, durations)
    print()
    _split_summary("TEST", result.test_record_ids, records_by_id, durations)
    print()
    print("LEAKAGE")
    print(f"  duplicate record ids : {len(report.duplicate_record_ids)}")
    print(f"  duplicate paths      : {len(report.duplicate_paths)}")
    print(f"  duplicate hashes     : {len(report.duplicate_hashes)}")
    print(f"  speaker leakage      : {len(report.speaker_leakage)}")
    print(f"  unaccounted records  : {len(report.unaccounted_record_ids)}")
    print(f"  CLEAN                : {report.clean}")
    print()

    repeat = split_records(args.dataset_id, records, config)
    identical = (
        repeat.train_record_ids == result.train_record_ids
        and repeat.validation_record_ids == result.validation_record_ids
        and repeat.test_record_ids == result.test_record_ids
    )
    other_seed_config = SplitConfig(strategy=config.strategy, proportions=config.proportions, seed=args.seed + 1)
    different_seed_result = split_records(args.dataset_id, records, other_seed_config)
    differs = different_seed_result.train_record_ids != result.train_record_ids

    print("REPRODUCIBILITY")
    print(f"  same seed identical    : {'PASS' if identical else 'FAIL'}")
    print(f"  different seed differs : {'PASS' if differs else 'FAIL'}")

    return 0 if (report.clean and identical and differs) else 1


if __name__ == "__main__":
    sys.exit(main())
