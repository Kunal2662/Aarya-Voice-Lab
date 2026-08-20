"""AARYA Voice Lab CLI.

Environment & validation (Phase 0/1):
    system-info, env-audit, validate-environment, validate-config,
    validate-manifest, nemo-check, whisperx-check, tts-check,
    tts-candidates

Dataset pipeline (Phase 2):
    inventory, validate-audio, analyze-quality, segment,
    dataset-report, normalize-check, dataset-gate

Planned, not implemented (stubs that refuse to run):
    diarize, transcribe, review, build-dataset, train, evaluate

The planned commands print a PLANNED notice and exit non-zero, so no
script can trigger unimplemented processing by calling a command that
merely "looks" implemented. Phase 2 commands additionally refuse to read
the private source tree unless explicitly approved.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aarya_voice_lab import __version__
from aarya_voice_lab.cli import phase2
from aarya_voice_lab.core.config import ConfigError, load_config
from aarya_voice_lab.core.paths import PROJECT_ROOT
from aarya_voice_lab.environment.audit import format_audit, run_audit
from aarya_voice_lab.environment.specs import EnvironmentId
from aarya_voice_lab.environment.verify import format_verification, verify_environment
from aarya_voice_lab.registry.tts_candidates import TTS_CANDIDATES, private_voice_candidates
from aarya_voice_lab.schemas.base import SchemaName, ValidationError, validate
from aarya_voice_lab.security.source_protection import scan_git_repo
from aarya_voice_lab.system_info import collect_system_report, format_report

PLANNED_COMMANDS = [
    "diarize",
    "transcribe",
    "review",
    "build-dataset",
    "train",
    "evaluate",
]


def _cmd_system_info(args: argparse.Namespace) -> int:
    report = collect_system_report()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(format_report(report))
    return 0


def _cmd_validate_environment(args: argparse.Namespace) -> int:
    ok = True
    report = collect_system_report()

    print("AARYA Voice Lab — Environment Validation")
    print("=" * 40)

    py_ok = sys.version_info >= (3, 10)
    print(f"[{'OK' if py_ok else 'FAIL'}] Python >= 3.10 (found {sys.version.split()[0]})")
    ok &= py_ok

    if report.ffmpeg.available:
        print(f"[OK]   FFmpeg available ({report.ffmpeg.version})")
    else:
        print("[WARN] FFmpeg not found — required for later audio pipeline phases, not for Phase 0")

    if report.gpu.available:
        print(f"[OK]   GPU detected ({len(report.gpu.devices)} device(s))")
    else:
        print("[INFO] No GPU detected — CPU-only execution is supported architecturally")

    scan_result = scan_git_repo(PROJECT_ROOT)
    if scan_result.ok:
        print("[OK]   Git safety scan: no tracked files match private-audio/model/secret patterns")
    else:
        print(f"[FAIL] Git safety scan found {len(scan_result.violations)} violation(s):")
        for violation in scan_result.violations:
            print(f"         - {violation.path}: {violation.reason}")
        ok = False

    print()
    print("Environment validation: " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


def _cmd_validate_manifest(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if not path.is_file():
        print(f"error: manifest file not found: {path}", file=sys.stderr)
        return 2

    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    schema_name = SchemaName(args.schema) if args.schema else _guess_schema(data)
    if schema_name is None:
        print("error: could not infer schema; pass --schema explicitly", file=sys.stderr)
        return 2

    records = data if isinstance(data, list) else [data]
    errors = 0
    for i, record in enumerate(records):
        try:
            validate(record, schema_name)
        except ValidationError as exc:
            errors += 1
            print(f"[FAIL] record {i}: {exc}", file=sys.stderr)

    if errors:
        print(f"\n{errors}/{len(records)} record(s) failed {schema_name.value} validation")
        return 1

    print(f"OK: {len(records)} record(s) valid against schema '{schema_name.value}'")
    return 0


def _guess_schema(data) -> SchemaName | None:
    sample = data[0] if isinstance(data, list) and data else data
    if not isinstance(sample, dict):
        return None
    if "segments" in sample and "dataset_id" in sample:
        return SchemaName.DATASET_MANIFEST
    if "experiment_id" in sample:
        return SchemaName.EXPERIMENT
    if "model_name" in sample and "model_type" in sample:
        return SchemaName.MODEL_REGISTRY
    if "benchmark_id" in sample:
        return SchemaName.BENCHMARK
    if "review_id" in sample:
        return SchemaName.MANUAL_REVIEW
    if "segment_id" in sample and "source_file_id" in sample:
        return SchemaName.SEGMENT
    return None


def _cmd_validate_config(args: argparse.Namespace) -> int:
    path = Path(args.path) if args.path else None
    try:
        config = load_config(path)
    except ConfigError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    print(f"OK: config valid (project_name={config.project_name!r}, schema_version={config.schema_version!r})")
    return 0


def _cmd_env_audit(args: argparse.Namespace) -> int:
    audit = run_audit()
    if args.json:
        print(json.dumps(audit.to_dict(), indent=2))
    else:
        print(format_audit(audit))
    return 0 if audit.ok else 1


def _cmd_env_check(env_id: EnvironmentId):
    def handler(args: argparse.Namespace) -> int:
        result = verify_environment(env_id)
        if getattr(args, "json", False):
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(format_verification(result))
        # Blockers (approval/credentials) are reported, not treated as crashes:
        # exit 3 distinguishes "stop condition" from "broken environment" (1).
        if result.blockers:
            return 3
        return 0 if result.usable else 1

    return handler


def _cmd_tts_candidates(args: argparse.Namespace) -> int:
    if args.json:
        print(json.dumps([c.to_dict() for c in TTS_CANDIDATES], indent=2))
        return 0

    print("AARYA Voice Lab — TTS Candidate Matrix")
    print("=" * 78)
    print("NO MODEL HAS BEEN SELECTED. Licensing is a hard filter; verdicts below")
    print("reflect license/language screening only — no audio has been evaluated.")
    print()
    header = f"{'Model':<32} {'Marathi':<8} {'Clone':<6} {'Commercial':<12} Verdict"
    print(header)
    print("-" * 78)
    for candidate in TTS_CANDIDATES:
        print(
            f"{candidate.name:<32} "
            f"{'yes' if candidate.marathi_support else 'no':<8} "
            f"{'yes' if candidate.reference_voice_cloning else 'no':<6} "
            f"{candidate.commercial_use.value:<12} "
            f"{candidate.verdict.value}"
        )
    print()
    print("Weights licenses:")
    for candidate in TTS_CANDIDATES:
        print(f"  {candidate.name:<32} {candidate.weights_license}")
    print()
    viable = private_voice_candidates()
    print(f"Private Voice candidates passing all hard filters: {len(viable)}")
    for candidate in viable:
        print(f"  - {candidate.name}: {candidate.rationale}")
        for limitation in candidate.known_limitations:
            print(f"      caveat: {limitation}")
    return 0



def _cmd_planned(name: str):
    def handler(args: argparse.Namespace) -> int:
        print(
            f"'{name}' is PLANNED for a later phase and is not implemented.\n"
            "Phase 0 does not process the private recordings. See docs/DATASET_PIPELINE.md "
            "and PHASE 0 acceptance criteria for details.",
            file=sys.stderr,
        )
        return 3

    return handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aarya-voice", description="AARYA Voice Lab CLI (Phase 0 foundation).")
    parser.add_argument("--version", action="version", version=f"aarya-voice-lab {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p = subparsers.add_parser("system-info", help="Report hardware/environment capabilities.")
    p.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    p.set_defaults(func=_cmd_system_info)

    p = subparsers.add_parser("validate-environment", help="Validate the environment is safe/ready for Phase 0 work.")
    p.set_defaults(func=_cmd_validate_environment)

    p = subparsers.add_parser("validate-manifest", help="Validate a manifest/record JSON file against its schema.")
    p.add_argument("path", help="Path to a JSON file (single record or a list of records).")
    p.add_argument(
        "--schema",
        choices=[s.value for s in SchemaName],
        default=None,
        help="Schema to validate against (auto-detected if omitted).",
    )
    p.set_defaults(func=_cmd_validate_manifest)

    p = subparsers.add_parser("validate-config", help="Validate a configs/*.yaml file.")
    p.add_argument("path", nargs="?", default=None, help="Path to config YAML (default: configs/default.yaml).")
    p.set_defaults(func=_cmd_validate_config)

    p = subparsers.add_parser("benchmark", help="Voice model benchmarking (framework only — see docs/BENCHMARKING.md).")
    benchmark_sub = p.add_subparsers(dest="benchmark_command")
    benchmark_sub.add_parser("run", help="PLANNED: not implemented in Phase 0.").set_defaults(
        func=_cmd_planned("benchmark run")
    )
    p.set_defaults(func=lambda args: p.print_help() or 0)

    p = subparsers.add_parser("experiment", help="Experiment registry (framework only — see docs/MODEL_STRATEGY.md).")
    experiment_sub = p.add_subparsers(dest="experiment_command")
    experiment_sub.add_parser("list", help="List recorded experiments.").set_defaults(func=_cmd_experiment_list)
    p.set_defaults(func=lambda args: p.print_help() or 0)

    p = subparsers.add_parser("env-audit", help="Classify every toolchain capability on this machine.")
    p.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    p.set_defaults(func=_cmd_env_audit)

    p = subparsers.add_parser("nemo-check", help="Verify the env-nemo environment against its spec.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_env_check(EnvironmentId.NEMO))

    p = subparsers.add_parser("whisperx-check", help="Verify the env-whisperx environment against its spec.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_env_check(EnvironmentId.WHISPERX))

    p = subparsers.add_parser("tts-check", help="Verify the env-tts environment against its spec.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_env_check(EnvironmentId.TTS))

    p = subparsers.add_parser("tts-candidates", help="Show the TTS candidate matrix and license audit.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_tts_candidates)

    p = subparsers.add_parser(
        "inventory",
        help="Catalogue audio files in a directory (refuses the private source tree).",
    )
    p.add_argument("directory", help="Directory to inventory.")
    p.add_argument("--batch-id", default="batch-001", help="Batch id (default: batch-001).")
    p.add_argument("--no-recursive", action="store_true")
    p.add_argument("--approved", action="store_true", help="Permit reading the protected source tree.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=phase2.cmd_inventory)

    phase2.register(subparsers)

    for name in PLANNED_COMMANDS:
        sp = subparsers.add_parser(name, help=f"PLANNED: {name} is not implemented in Phase 0.")
        sp.set_defaults(func=_cmd_planned(name))

    return parser


def _cmd_experiment_list(args: argparse.Namespace) -> int:
    from aarya_voice_lab.registry.experiment_registry import ExperimentRegistry

    registry = ExperimentRegistry()
    records = registry.list()
    if not records:
        print("No experiments recorded yet.")
        return 0
    for record in records:
        print(f"{record['experiment_id']}  {record['model']}@{record['model_version']}  status={record['status']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
