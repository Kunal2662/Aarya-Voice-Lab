"""Phase 3 CLI: identity architecture inspection and synthetic runs.

Every command supports `--json`, emitting the same contract envelopes the
future desktop consumes — one surface, no duplicated policy.

Exit codes follow the project convention: 0 success, 1 check failed,
2 usage error, 3 BLOCKED (stop condition).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.identity import command_center, contracts
from aarya_voice_lab.identity.audit import AuditEventType, AuditLog
from aarya_voice_lab.identity.embeddings import EmbeddingStore, available_providers
from aarya_voice_lab.identity.enrollment import available_strategies, describe_strategies
from aarya_voice_lab.identity.synthetic_e2e import run_synthetic_e2e, uncalibrated_baseline


def cmd_identity_status(args: argparse.Namespace) -> int:
    data_root = DataRoot.default()
    snapshot = contracts.desktop_snapshot(data_root)
    if args.json:
        print(json.dumps(snapshot, indent=2))
        return 0

    profiles = snapshot["profiles"]
    pipeline = snapshot["pipeline"]
    print("AARYA Voice Lab — Identity Status (Phase 3)")
    print("=" * 60)
    print(f"  speaker profiles      : {profiles['count']} ({profiles['usable_count']} usable)")
    print(f"  embeddings stored     : {snapshot['embeddings']['count']}")
    print(f"  audit entries         : {snapshot['audit']['entry_count']}")
    print(f"  audit chain intact    : {snapshot['audit']['chain_intact']}")
    print(f"  identity boundary     : {pipeline['identity_boundary_stage']} @ {pipeline['identity_boundary_index']}")
    print(f"  stages implemented    : {pipeline['implemented_count']}/{len(pipeline['stages'])}")
    print()
    print("  Embedding providers   : " + ", ".join(available_providers()))
    print("  Enrollment strategies : " + ", ".join(available_strategies()))
    print()
    print("  NO real embedding provider is installed.")
    print("  NO real recording has been accessed.")
    print("  NO voice generation exists (VL-V0 contracts only).")
    return 0


def cmd_enrollment_strategies(args: argparse.Namespace) -> int:
    payload = describe_strategies()
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print("Enrollment strategies (pluggable)")
    print("=" * 60)
    for strategy in payload:
        print(f"\n  {strategy['name']} v{strategy['version']}")
        print(f"    human approval required : {strategy['requires_human_approval']}")
        print(f"    permitted roles         : {', '.join(strategy['permitted_roles'])}")
        print(f"    minimum samples         : {strategy['minimum_samples']}")
        print(f"    minimum total seconds   : {strategy['minimum_total_seconds']}")
    print()
    print("No production strategy is hard-coded. The target-speaker approach")
    print("remains an open decision — see docs/PHASE3_IDENTITY.md.")
    return 0


def cmd_calibration_status(args: argparse.Namespace) -> int:
    payload = contracts.calibration_status(uncalibrated_baseline())
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print("Calibration status")
    print("=" * 60)
    print(f"  state    : {payload['state']}")
    print(f"  evidence : {payload['evidence']}")
    print(f"  statistically validated : {payload['is_statistically_validated']}")
    print("\n  Limitations:")
    for limitation in payload["limitations"]:
        print(f"    - {limitation}")
    print(f"\n  {payload['target_speaker_calibration_note']}")
    return 0


def cmd_runtime_capabilities(args: argparse.Namespace) -> int:
    payload = contracts.runtime_capabilities()
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print("Runtime capabilities (vendor-neutral)")
    print("=" * 60)
    for component in payload["components"]:
        print(f"\n  {component['component']}")
        print(f"    acceleration : {component['acceleration']}")
        print(f"    backends     : {', '.join(component['supported_backends'])}")
        print(f"    portability  : {component['portability']}")
    portability = payload["portability"]
    print(f"\n  CPU-only viable : {portability['cpu_only_viable']}")
    print(f"  {portability['note']}")
    return 0


def cmd_audit_log(args: argparse.Namespace) -> int:
    payload = contracts.audit_history(DataRoot.default(), args.subject)
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    summary = payload["summary"]
    print("Identity audit log")
    print("=" * 60)
    print(f"  entries      : {summary['entry_count']}")
    print(f"  chain intact : {summary['chain_intact']}")
    for problem in summary["chain_problems"]:
        print(f"    ! {problem}")
    for event, count in sorted(summary["event_counts"].items()):
        print(f"    {event:<24} {count}")
    return 0 if summary["chain_intact"] else 1


def cmd_embedding_inventory(args: argparse.Namespace) -> int:
    payload = contracts.embedding_inventory(DataRoot.default())
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print("Embedding inventory")
    print("=" * 60)
    print(f"  stored    : {payload['count']}")
    print(f"  directory : {payload['storage_directory']} (git-ignored: {payload['git_ignored']})")
    print(f"  export    : {'supported' if payload['export_supported'] else 'NOT SUPPORTED — by design'}")
    print(f"\n  {payload['note']}")
    return 0


def cmd_embedding_delete(args: argparse.Namespace) -> int:
    """Delete stored embeddings, recording the deletion in the audit log."""
    data_root = DataRoot.default()
    store = EmbeddingStore(data_root)
    audit = AuditLog(data_root)

    targets = store.list_ids() if args.all else ([args.embedding_id] if args.embedding_id else [])
    if not targets:
        print("error: pass an embedding id or --all", file=sys.stderr)
        return 2

    if not args.confirm:
        print(f"Would delete {len(targets)} embedding(s): {targets}")
        print("Re-run with --confirm to delete. This is irreversible.")
        return 0

    deleted = []
    for embedding_id in targets:
        if store.delete(embedding_id):
            deleted.append(embedding_id)
            # The record of a deletion must outlive the data.
            audit.append(
                AuditEventType.EMBEDDING_DELETED,
                actor=args.actor,
                subject_id=embedding_id,
                detail={"reason": args.reason or "not stated"},
            )
    print(f"Deleted {len(deleted)} embedding(s); each deletion is recorded in the audit log.")
    return 0


def cmd_synthetic_e2e(args: argparse.Namespace) -> int:
    """Run the full Phase 3 chain on generated audio, in a temp workspace."""
    with tempfile.TemporaryDirectory(prefix="aarya-phase3-e2e-") as temporary:
        result = run_synthetic_e2e(Path(temporary))
        summary = result.summary()

        if args.json:
            print(
                json.dumps(
                    {
                        "summary": summary,
                        "profiles": result.profiles,
                        "verifications": [v.to_dict() for v in result.verifications],
                        "promotions": result.promotions,
                        "calibration": result.calibration.to_dict() if result.calibration else None,
                        "audit": result.audit_summary,
                    },
                    indent=2,
                )
            )
            return 0

        print("Phase 3 synthetic end-to-end")
        print("=" * 60)
        print(f"  profiles enrolled     : {summary['profiles']}")
        print(f"  verifications         : {summary['verifications']}")
        for decision, count in sorted(summary["by_decision"].items()):
            print(f"      {decision:<26} {count}")
        print(f"  reviews recorded      : {summary['reviews']}")
        print(f"  promoted to dataset   : {summary['promoted_to_dataset']}")
        print(f"  calibration state     : {summary['calibration_state']}")
        print(f"  audit entries         : {summary['audit_entries']}")
        print(f"  audit chain intact    : {summary['audit_chain_intact']}")
        print(f"  all results synthetic : {summary['all_synthetic']}")
        print(f"  real identity claims  : {summary['real_identity_claims']}")
        print()
        print("  Zero promotions and zero real identity claims are the CORRECT")
        print("  outcome: synthetic provenance blocks dataset entry by design.")
        return 0


def cmd_voice_preview_status(args: argparse.Namespace) -> int:
    payload = contracts.voice_preview_status()
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print("VL-V0 Voice Preview & Feedback")
    print("=" * 60)
    print(f"  generation implemented : {payload['generation_implemented']}")
    print(f"  iterations             : {payload['iteration_count']}")
    print(f"\n  {payload['note']}")
    return 0


def cmd_command_center(args: argparse.Namespace) -> int:
    """Backend snapshot for the future desktop Claude Code panel."""
    payload = command_center.command_center_snapshot(DataRoot.default())
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    repo = payload["repository"]
    diag = payload["diagnostics"]
    print("Claude Code Command Center — backend snapshot")
    print("=" * 60)
    print(f"  branch        : {repo['branch']}")
    print(f"  HEAD          : {repo['head_short']}  {repo['head_subject']}")
    print(f"  tree clean    : {repo['working_tree_clean']}")
    print(f"  healthy       : {diag['healthy']}")
    for problem in diag["problems"]:
        print(f"    ! {problem}")
    print(f"  commands      : {payload['commands']['count']}")
    print(f"  activity      : {payload['activity']['count']} recent entries")
    print(f"  real recordings present : {diag['real_recordings_present']}")
    print()
    print("  Contracts only — this surface executes nothing. The desktop")
    print("  invokes the ordinary CLI so gates and audit logging still apply.")
    return 0 if diag["healthy"] else 1


def register(subparsers) -> None:
    p = subparsers.add_parser("identity-status", help="Speaker identity architecture status.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_identity_status)

    p = subparsers.add_parser("enrollment-strategies", help="List pluggable enrollment strategies.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_enrollment_strategies)

    p = subparsers.add_parser("calibration-status", help="Calibration state and its limits.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_calibration_status)

    p = subparsers.add_parser("runtime-capabilities", help="Vendor-neutral component capabilities.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_runtime_capabilities)

    p = subparsers.add_parser("identity-audit", help="Inspect the identity audit log.")
    p.add_argument("--subject", default=None, help="Filter to one subject id.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_audit_log)

    p = subparsers.add_parser("embedding-inventory", help="List stored embeddings (never their vectors).")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_embedding_inventory)

    p = subparsers.add_parser("embedding-delete", help="Delete embeddings and record the deletion.")
    p.add_argument("embedding_id", nargs="?", default=None)
    p.add_argument("--all", action="store_true")
    p.add_argument("--confirm", action="store_true", help="Actually delete. Irreversible.")
    p.add_argument("--actor", default="operator")
    p.add_argument("--reason", default=None)
    p.set_defaults(func=cmd_embedding_delete)

    p = subparsers.add_parser("synthetic-e2e", help="Run the Phase 3 chain end-to-end on generated audio.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_synthetic_e2e)

    p = subparsers.add_parser("command-center", help="Backend snapshot for the desktop Claude panel.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_command_center)

    p = subparsers.add_parser("voice-preview-status", help="VL-V0 preview loop status (contracts only).")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_voice_preview_status)
