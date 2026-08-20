"""Phase 2 CLI commands: dataset pipeline operations.

Exit codes follow the project convention:

    0  success
    1  a check failed
    2  usage / input error
    3  BLOCKED — a stop condition (missing capability, denied access).
       Deliberately distinct from 1: "cannot proceed safely" is not the
       same as "something is broken".
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.pipeline.dataset import (
    PipelineConfig,
    run_dataset_pipeline,
    write_candidate_manifest,
)
from aarya_voice_lab.pipeline.dataset_gate import evaluate_gate, format_gate
from aarya_voice_lab.pipeline.inventory import (
    PrivateSourceAccessError,
    build_inventory,
    duplicate_groups,
)
from aarya_voice_lab.pipeline.normalization import (
    NormalizationConfig,
    ffmpeg_version,
)
from aarya_voice_lab.pipeline.validation import (
    ValidationConfig,
    ValidationStatus,
    ValidationSummary,
    validate_audio_file,
)


def cmd_inventory(args: argparse.Namespace) -> int:
    directory = Path(args.directory)
    try:
        inventory = build_inventory(
            directory, approved=args.approved, batch_id=args.batch_id, recursive=not args.no_recursive
        )
    except PrivateSourceAccessError as exc:
        print(f"[BLOCKED] {exc}", file=sys.stderr)
        return 3
    except (NotADirectoryError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(inventory.to_dict(), indent=2))
        return 0

    print(f"Inventory of {directory}")
    print(f"  files              : {len(inventory.files)}")
    print(f"  unique content     : {len(inventory.unique_files)}")
    print(f"  duplicates         : {len(inventory.duplicates)}")
    print(f"  unreadable/invalid : {len(inventory.unreadable)}")
    print(f"  total duration     : {inventory.total_duration_seconds:.2f}s")
    duplicates = duplicate_groups(inventory)
    if duplicates:
        print("\nDuplicate content:")
        for digest, paths in duplicates.items():
            print(f"  {digest[:12]}…: {', '.join(paths)}")
    if inventory.unreadable:
        print("\nProblem files:")
        for record in inventory.unreadable:
            print(f"  {record.path}: {record.processing_status} — {record.note}")
    return 0


def cmd_validate_audio(args: argparse.Namespace) -> int:
    directory = Path(args.directory)
    try:
        inventory = build_inventory(directory, approved=args.approved, batch_id=args.batch_id)
    except PrivateSourceAccessError as exc:
        print(f"[BLOCKED] {exc}", file=sys.stderr)
        return 3
    except (NotADirectoryError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    summary = ValidationSummary()
    config = ValidationConfig()
    for record in inventory.files:
        summary.results.append(
            validate_audio_file(
                directory / record.path,
                source_file_id=record.source_file_id,
                config=config,
                relative_to=directory,
            )
        )

    if args.json:
        print(json.dumps(summary.to_dict(), indent=2))
    else:
        print(f"Audio validation — {len(summary.results)} file(s)")
        print(f"  VALID   : {summary.count(ValidationStatus.VALID)}")
        print(f"  WARNING : {summary.count(ValidationStatus.WARNING)}")
        print(f"  INVALID : {summary.count(ValidationStatus.INVALID)}")
        print(f"  BLOCKED : {summary.count(ValidationStatus.BLOCKED)}")
        for result in summary.results:
            if result.status is not ValidationStatus.VALID:
                print(f"\n  {result.path} [{result.status.value}]")
                for finding in result.findings:
                    print(f"     - {finding.code}: {finding.message}")

    if summary.count(ValidationStatus.BLOCKED):
        return 3
    return 1 if summary.count(ValidationStatus.INVALID) else 0


def cmd_analyze_quality(args: argparse.Namespace) -> int:
    """Quality analysis is produced as part of the pipeline run, so this
    command runs the pipeline and reports only its quality output."""
    directory = Path(args.directory)
    try:
        result = run_dataset_pipeline(
            directory,
            batch_id=args.batch_id,
            approved=args.approved,
            is_synthetic=not args.approved,
        )
    except PrivateSourceAccessError as exc:
        print(f"[BLOCKED] {exc}", file=sys.stderr)
        return 3
    except (NotADirectoryError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"quality": result.quality_results}, indent=2))
        return 0

    print(f"Quality analysis — {len(result.quality_results)} file(s)")
    for entry in result.quality_results:
        print(f"\n  {entry['source_file_id']} [{entry['decision']}]")
        for characteristic in entry["characteristics"]:
            print(f"     characteristic: {characteristic}")
        for finding in entry["findings"]:
            print(f"     {finding['decision']}: {finding['code']} — {finding['message']}")
    return 0


def cmd_segment(args: argparse.Namespace) -> int:
    directory = Path(args.directory)
    config = PipelineConfig(extract_segment_audio=args.extract_audio)

    if args.dry_run:
        print("DRY RUN — no files will be written.")

    try:
        result = run_dataset_pipeline(
            directory,
            batch_id=args.batch_id,
            dataset_version=args.dataset_version,
            config=config,
            approved=args.approved,
            is_synthetic=not args.approved,
            limit=args.limit,
        )
    except PrivateSourceAccessError as exc:
        print(f"[BLOCKED] {exc}", file=sys.stderr)
        return 3
    except (NotADirectoryError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    summary = result.summary()
    if not args.dry_run:
        data_root = DataRoot.default().create()
        manifest_path = data_root.batch_manifests(args.batch_id) / "candidate_manifest.json"
        write_candidate_manifest(result, manifest_path)
        summary["manifest_path"] = str(manifest_path)

    if args.json:
        print(json.dumps(summary, indent=2))
        return 0

    print(f"\nSegmentation — batch {summary['batch_id']}")
    print(f"  source files          : {summary['source_files']}")
    print(f"  candidate segments    : {summary['candidate_segments']}")
    print(f"  technically eligible  : {summary['technically_eligible']}")
    print(f"  needs review          : {summary['needs_review']}")
    print(f"  technically rejected  : {summary['technically_rejected']}")
    print(f"  review items          : {summary['review_items']}")
    if "manifest_path" in summary:
        print(f"  manifest              : {summary['manifest_path']}")
    print()
    print("NOTE: 'technically eligible' means usable audio. It is NOT an")
    print("approval as target-speaker data — Phase 2 makes no claim about")
    print("who is speaking. Speaker identity is decided in Phase 3.")
    return 0


def cmd_dataset_report(args: argparse.Namespace) -> int:
    directory = Path(args.directory)
    try:
        result = run_dataset_pipeline(
            directory,
            batch_id=args.batch_id,
            approved=args.approved,
            is_synthetic=not args.approved,
        )
    except PrivateSourceAccessError as exc:
        print(f"[BLOCKED] {exc}", file=sys.stderr)
        return 3
    except (NotADirectoryError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    summary = result.summary()
    if args.json:
        print(json.dumps({"summary": summary, "review_items": result.review_items}, indent=2))
        return 0

    print("AARYA Voice Lab — Dataset Report")
    print("=" * 60)
    for key, value in summary.items():
        if key != "warnings":
            print(f"  {key:<22}: {value}")
    if summary["warnings"]:
        print("\nWarnings:")
        for warning in summary["warnings"]:
            print(f"  ! {warning}")
    if result.review_items:
        print(f"\nReview queue ({len(result.review_items)} item(s)) — technical only:")
        for item in result.review_items[:20]:
            target = item["segment_id"] or item["source_file_id"]
            print(f"  {target}: {item['reason_code']} — {item['message']}")
    print()
    print("Phase 2 does not determine speaker identity.")
    return 0


def cmd_dataset_gate(args: argparse.Namespace) -> int:
    report = evaluate_gate(
        phase2_complete=args.phase2_complete,
        tests_passing=args.tests_passing,
        security_scan_clean=args.security_scan_clean,
        processing_config_reviewed=args.config_reviewed,
        explicit_approval=args.explicit_approval,
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_gate(report))
    return 0 if report.allowed else 3


def cmd_normalize_check(args: argparse.Namespace) -> int:
    """Report whether normalization can run, without normalizing anything."""
    version = ffmpeg_version()
    config = NormalizationConfig()
    payload = {
        "ffmpeg_available": version is not None,
        "ffmpeg_version": version,
        "config": config.to_dict(),
        "config_hash": config.config_hash(),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("Normalization capability")
        print(f"  FFmpeg   : {version or 'NOT AVAILABLE'}")
        print(f"  target   : {config.target_sample_rate} Hz, {config.target_channels}ch, "
              f"{config.target_bit_depth}-bit")
        print(f"  loudness : {'on' if config.apply_loudness_normalization else 'off (level is evidence)'}")
        if version is None:
            print("\n[BLOCKED] FFmpeg is required to normalize audio. Originals are")
            print("left untouched and no substitute tool will be used.")
            print("See docs/ENVIRONMENT.md for installation instructions.")
    return 0 if version else 3


def register(subparsers) -> None:
    """Attach Phase 2 commands to the existing CLI."""
    common_batch = dict(default="batch-001", help="Batch id (default: batch-001).")

    p = subparsers.add_parser("validate-audio", help="Validate audio files (VALID/WARNING/INVALID/BLOCKED).")
    p.add_argument("directory")
    p.add_argument("--batch-id", **common_batch)
    p.add_argument("--approved", action="store_true", help="Permit reading the protected source tree.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_validate_audio)

    p = subparsers.add_parser("analyze-quality", help="Measure audio quality and report decisions.")
    p.add_argument("directory")
    p.add_argument("--batch-id", **common_batch)
    p.add_argument("--approved", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_analyze_quality)

    p = subparsers.add_parser("segment", help="Segment audio into candidate spans and write a manifest.")
    p.add_argument("directory")
    p.add_argument("--batch-id", **common_batch)
    p.add_argument("--dataset-version", default="0.1.0")
    p.add_argument("--limit", type=int, default=None, help="Process only the first N source files.")
    p.add_argument("--extract-audio", action="store_true", help="Also write segment WAV files.")
    p.add_argument("--dry-run", action="store_true", help="Analyse without writing any output.")
    p.add_argument("--approved", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_segment)

    p = subparsers.add_parser("dataset-report", help="Summarise a dataset run and its review queue.")
    p.add_argument("directory")
    p.add_argument("--batch-id", **common_batch)
    p.add_argument("--approved", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_dataset_report)

    p = subparsers.add_parser(
        "dataset-gate",
        help="Check whether access to the real recordings is permitted.",
    )
    p.add_argument("--phase2-complete", action="store_true")
    p.add_argument("--tests-passing", action="store_true")
    p.add_argument("--security-scan-clean", action="store_true")
    p.add_argument("--config-reviewed", action="store_true")
    p.add_argument(
        "--explicit-approval",
        action="store_true",
        help="Attest that explicit human approval to access the recordings has been given.",
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_dataset_gate)

    p = subparsers.add_parser("normalize-check", help="Report whether audio normalization can run.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_normalize_check)
