"""VL-D2 CLI: bulk import into a batch's `source/` tree.

Deliberately synthetic-only. There is no `--real`/`--approved` flag here
by design — real-recording import is out of VL-D2's scope entirely (see
docs/VLD2_DATASET_WORKSPACE.md "Future real-recording activation"), and
omitting the flag rather than gating it closed is one less footgun than
shipping a flag whose only job is to be left off.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aarya_voice_lab.core.data_root import DataRoot, create_batch, read_batch
from aarya_voice_lab.pipeline.import_intake import ImportQueue, ImportSource, write_import_manifest
from aarya_voice_lab.pipeline.inventory import PrivateSourceAccessError, discover_audio_files


def cmd_import(args: argparse.Namespace) -> int:
    data_root = DataRoot.default()
    data_root.create()
    if read_batch(data_root, args.batch_id) is None:
        create_batch(data_root, args.batch_id)

    if args.folder:
        directory = Path(args.paths[0])
        try:
            paths = discover_audio_files(directory, recursive=not args.no_recursive)
        except (NotADirectoryError, PrivateSourceAccessError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        source = ImportSource.LOCAL_FOLDER
    else:
        paths = [Path(p) for p in args.paths]
        source = ImportSource.LOCAL_FILES

    queue = ImportQueue(data_root=data_root, batch_id=args.batch_id, source=source)
    for path in paths:
        queue.enqueue(path)
    queue.process_all()

    manifest_path = data_root.batch_manifests(args.batch_id) / "import_manifest.json"
    write_import_manifest(queue, manifest_path)

    if args.json:
        print(json.dumps(queue.to_manifest(), indent=2))
        return 0

    print(f"Import into {args.batch_id} ({source.value}, {len(paths)} file(s) queued)")
    for status, count in queue.counts().items():
        if count:
            print(f"  {status:12s}: {count}")

    problems = [item for item in queue.items.values() if item.status in ("failed", "invalid", "blocked")]
    if problems:
        print("\nProblems:")
        for item in problems:
            print(f"  {item.original_filename}: {item.status} — {'; '.join(item.errors)}")

    duplicates = [item for item in queue.items.values() if item.status == "duplicate"]
    if duplicates:
        print("\nDuplicates (not re-stored):")
        for item in duplicates:
            print(f"  {item.original_filename}: already present in {item.duplicate_of}")

    print(f"\nManifest written to {manifest_path}")
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "import",
        help="Bulk-import files or a folder into a batch's source/ tree (synthetic fixtures only).",
    )
    p.add_argument("paths", nargs="+", help="One or more files, or (with --folder) a single directory.")
    p.add_argument(
        "--folder", action="store_true", help="Treat the single given path as a folder to import recursively."
    )
    p.add_argument("--no-recursive", action="store_true", help="With --folder, do not recurse into subdirectories.")
    p.add_argument("--batch-id", default="batch-001", help="Batch id (default: batch-001).")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_import)
