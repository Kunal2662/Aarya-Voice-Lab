#!/usr/bin/env python3
"""Batch-normalize every audio file under a directory into `data/working/<batch_id>/`.

`pipeline.dataset.run_dataset_pipeline()` decodes WAV only (pure stdlib PCM
decode, per this project's "no FFmpeg required for measurement" design) and
has no batch-normalization step wired in before that decode -- so a non-WAV
source directory (e.g. a real public dataset shipped as FLAC/MP3) never
reaches quality/VAD/segmentation at all; every file is recorded as
`decode_failed` and skipped.

This script closes exactly that gap for a real, non-WAV dataset by calling
the existing, already-tested, single-file `pipeline.normalization.normalize_file()`
once per file discovered by the existing `pipeline.inventory.build_inventory()`.
It introduces no new architecture: both functions already existed and are
unmodified; this is orchestration only, mirroring `pipeline.dataset.run_dataset_pipeline()`'s
own per-file-loop shape.

Never touches `data/source/` (protected private tree) -- `build_inventory()`'s
own `require_synthetic_or_approved()` guard still applies to the *input*
directory, and `normalize_file()`'s own `assert_source_writable()` guard
still applies to the *output* path, unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.pipeline.inventory import build_inventory
from aarya_voice_lab.pipeline.normalization import NormalizationBlocked, NormalizationConfig, normalize_file


def normalize_batch(
    directory: Path,
    *,
    batch_id: str,
    approved: bool,
    limit: int | None,
    data_root: DataRoot | None = None,
) -> dict:
    data = data_root or DataRoot.default()
    inventory = build_inventory(directory, approved=approved, batch_id=batch_id)

    sources = inventory.unique_files
    if limit is not None:
        sources = sources[:limit]

    destination_dir = data.batch_working(batch_id)
    records: list[dict] = []
    for record in sources:
        source_path = directory / record.path
        destination = destination_dir / f"{record.source_file_id}.wav"
        if destination.exists():
            records.append(
                {
                    "source_file_id": record.source_file_id,
                    "status": "already_normalized",
                    "output_path": destination.name,
                }
            )
            continue
        try:
            result = normalize_file(
                source_path,
                destination,
                source_file_id=record.source_file_id,
                source_sha256=record.sha256,
                data_root=data,
                config=NormalizationConfig(),
            )
            records.append(result.to_dict())
        except NormalizationBlocked as exc:
            records.append({"source_file_id": record.source_file_id, "status": "blocked", "note": str(exc)})

    return {
        "directory": str(directory),
        "batch_id": batch_id,
        "destination_dir": str(destination_dir),
        "total": len(sources),
        "completed": sum(1 for r in records if r.get("status") == "completed"),
        "already_normalized": sum(1 for r in records if r.get("status") == "already_normalized"),
        "failed": sum(1 for r in records if r.get("status") == "failed"),
        "blocked": sum(1 for r in records if r.get("status") == "blocked"),
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory")
    parser.add_argument("--batch-id", default="batch-001")
    parser.add_argument("--approved", action="store_true", help="Permit reading the protected source tree.")
    parser.add_argument("--limit", type=int, default=None, help="Normalize only the first N discovered files.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    summary = normalize_batch(
        Path(args.directory), batch_id=args.batch_id, approved=args.approved, limit=args.limit
    )

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(
            f"Normalized {summary['completed']}/{summary['total']} "
            f"(already_normalized={summary['already_normalized']}, "
            f"failed={summary['failed']}, blocked={summary['blocked']}) "
            f"-> {summary['destination_dir']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
