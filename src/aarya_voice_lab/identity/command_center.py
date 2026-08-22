"""VL-D6/D7/D8/D9 — backend contracts for the Claude Code Command Center.

The future Voice Lab Desktop will host a panel for viewing Claude's
activity, inspecting pipeline context, issuing commands, reading diffs,
running tests and audits, and browsing tasks and logs.

This module supplies the **read contracts and command descriptors** that
panel needs. It deliberately does not execute anything: the desktop asks
Core what commands exist and what state they would act on, then invokes
them through the ordinary CLI. Two consequences follow, both intentional:

* **No policy is duplicated in the UI.** Eligibility, approval rules, and
  calibration honesty stay in Core. The panel renders decisions; it never
  makes them.
* **No arbitrary execution surface is created here.** A backend that
  accepted free-form commands from a UI would be a new, unaudited way to
  reach private material. Commands are *described* so the desktop can
  present them; running one goes through the same CLI, gates, and audit
  log as any other invocation.

Context assembled here is safe to display: it names files, versions, and
counts, never audio, embeddings, or absolute paths into private storage.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from aarya_voice_lab import __version__
from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.core.paths import PROJECT_ROOT
from aarya_voice_lab.identity.audit import AuditLog

COMMAND_CENTER_CONTRACT_VERSION = "1.0.0"


class CommandRisk(StrEnum):
    """How much care a command needs before the desktop runs it."""

    #: Reads state only. Safe to run without confirmation.
    READ_ONLY = "read_only"
    #: Writes local artifacts. Reversible.
    WRITES_LOCAL = "writes_local"
    #: Irreversible, or touches protected material. Confirm explicitly.
    DESTRUCTIVE = "destructive"
    #: Blocked by a gate; cannot run until the gate is satisfied.
    GATED = "gated"


@dataclass(frozen=True)
class CommandDescriptor:
    """One CLI command the desktop may surface.

    `risk` drives the UI affordance: a read-only command can be a button,
    a destructive one needs a confirmation step, and a gated one should be
    shown disabled with its reason rather than hidden — a hidden control
    invites the user to look for a way around it.
    """

    command: str
    summary: str
    risk: CommandRisk
    supports_json: bool = True
    requires_confirmation: bool = False
    gate_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "summary": self.summary,
            "risk": self.risk.value,
            "supports_json": self.supports_json,
            "requires_confirmation": self.requires_confirmation,
            "gate_reason": self.gate_reason,
        }


#: Commands the desktop may present. Kept explicit rather than generated
#: from the parser: a UI should show a curated, described set, not every
#: flag the CLI happens to accept.
COMMAND_CATALOGUE: tuple[CommandDescriptor, ...] = (
    CommandDescriptor("system-info", "Hardware and environment facts.", CommandRisk.READ_ONLY),
    CommandDescriptor("env-audit", "Capability audit with explicit states.", CommandRisk.READ_ONLY),
    CommandDescriptor("validate-environment", "Readiness plus Git safety scan.", CommandRisk.READ_ONLY),
    CommandDescriptor("validate-config", "Validate configs/default.yaml.", CommandRisk.READ_ONLY),
    CommandDescriptor("validate-manifest", "Validate a record against its schema.", CommandRisk.READ_ONLY),
    CommandDescriptor("tts-candidates", "TTS candidate matrix and licence audit.", CommandRisk.READ_ONLY),
    CommandDescriptor("inventory", "Catalogue audio in a directory.", CommandRisk.READ_ONLY),
    CommandDescriptor("validate-audio", "Classify audio VALID/WARNING/INVALID/BLOCKED.", CommandRisk.READ_ONLY),
    CommandDescriptor("analyze-quality", "Measure quality and report decisions.", CommandRisk.READ_ONLY),
    CommandDescriptor(
        "segment",
        "Segment audio into candidates and write a manifest.",
        CommandRisk.WRITES_LOCAL,
    ),
    CommandDescriptor("dataset-report", "Summarise a run and its review queue.", CommandRisk.READ_ONLY),
    CommandDescriptor("identity-status", "Speaker identity architecture status.", CommandRisk.READ_ONLY),
    CommandDescriptor("enrollment-strategies", "List pluggable enrollment strategies.", CommandRisk.READ_ONLY),
    CommandDescriptor("calibration-status", "Calibration state and its limits.", CommandRisk.READ_ONLY),
    CommandDescriptor("runtime-capabilities", "Vendor-neutral component capabilities.", CommandRisk.READ_ONLY),
    CommandDescriptor("identity-audit", "Inspect the identity audit log.", CommandRisk.READ_ONLY),
    CommandDescriptor("embedding-inventory", "List stored embeddings (never vectors).", CommandRisk.READ_ONLY),
    CommandDescriptor(
        "embedding-delete",
        "Permanently delete embeddings; the deletion is audited.",
        CommandRisk.DESTRUCTIVE,
        requires_confirmation=True,
    ),
    CommandDescriptor("synthetic-e2e", "Run the Phase 3 chain on generated audio.", CommandRisk.WRITES_LOCAL),
    CommandDescriptor("voice-preview-status", "VL-V0 preview loop status.", CommandRisk.READ_ONLY),
    CommandDescriptor(
        "dataset-gate",
        "Check whether real-recording access is permitted.",
        CommandRisk.READ_ONLY,
    ),
    CommandDescriptor(
        "diarize",
        "PLANNED — not implemented.",
        CommandRisk.GATED,
        gate_reason="Phase 4+; refuses to run and exits non-zero.",
    ),
    CommandDescriptor(
        "train",
        "PLANNED — not implemented.",
        CommandRisk.GATED,
        gate_reason="No voice model training exists in this project.",
    ),
)


def _envelope(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract": kind,
        "contract_version": COMMAND_CENTER_CONTRACT_VERSION,
        "processing_version": __version__,
        **payload,
    }


def command_catalogue() -> dict[str, Any]:
    """Commands the desktop may surface, with risk annotations."""
    return _envelope(
        "command_catalogue",
        {
            "commands": [c.to_dict() for c in COMMAND_CATALOGUE],
            "count": len(COMMAND_CATALOGUE),
            "note": (
                "Descriptors only. This module executes nothing — the desktop invokes "
                "the ordinary CLI so every run passes the same gates and audit log."
            ),
        },
    )


def _git(args: list[str], root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def repository_context(root: Path | None = None) -> dict[str, Any]:
    """Branch, HEAD, and working-tree state for the context panel."""
    root = root or PROJECT_ROOT
    status = _git(["status", "--porcelain"], root)
    return _envelope(
        "repository_context",
        {
            "branch": _git(["rev-parse", "--abbrev-ref", "HEAD"], root),
            "head": _git(["rev-parse", "HEAD"], root),
            "head_short": _git(["rev-parse", "--short", "HEAD"], root),
            "head_subject": _git(["log", "-1", "--format=%s"], root),
            "working_tree_clean": not status,
            "changed_file_count": len(status.splitlines()) if status else 0,
            "recent_commits": [
                line for line in _git(["log", "--oneline", "-10"], root).splitlines() if line
            ],
        },
    )


def changed_files(root: Path | None = None, *, against: str = "HEAD") -> dict[str, Any]:
    """Changed files with per-file line counts — names and numbers only.

    Deliberately returns statistics rather than diff content: a diff of a
    file under `data/` could contain private material, and this contract
    is meant to be safe to render anywhere.
    """
    root = root or PROJECT_ROOT
    numstat = _git(["diff", "--numstat", against], root)
    files = []
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            added, removed, path = parts
            files.append(
                {
                    "path": path,
                    "added": None if added == "-" else int(added),
                    "removed": None if removed == "-" else int(removed),
                    "binary": added == "-",
                }
            )
    return _envelope(
        "changed_files",
        {
            "against": against,
            "files": files,
            "count": len(files),
            "note": (
                "File names and line counts only. Diff content is not returned: a diff "
                "under data/ could carry private material."
            ),
        },
    )


@dataclass
class ActivityEntry:
    """One item in the activity feed."""

    kind: str
    summary: str
    timestamp: str
    subject_id: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "summary": self.summary,
            "timestamp": self.timestamp,
            "subject_id": self.subject_id,
            "detail": self.detail,
        }


def activity_feed(data_root: DataRoot, *, limit: int = 50) -> dict[str, Any]:
    """Recent identity activity, newest first.

    Sourced from the audit log, which is already sanitised — no vectors,
    no absolute paths — so the feed is safe to display verbatim.
    """
    log = AuditLog(data_root)
    entries = log.read_all()
    recent = list(reversed(entries))[:limit]
    feed = [
        ActivityEntry(
            kind=entry["event_type"],
            summary=f"{entry['event_type']} · {entry['subject_id']}",
            timestamp=entry["timestamp"],
            subject_id=entry["subject_id"],
            detail=entry.get("detail", {}),
        ).to_dict()
        for entry in recent
    ]
    return _envelope(
        "activity_feed",
        {
            "entries": feed,
            "count": len(feed),
            "total_available": len(entries),
            "chain_intact": log.summary()["chain_intact"],
        },
    )


def diagnostics(data_root: DataRoot, root: Path | None = None) -> dict[str, Any]:
    """A health snapshot the panel can show when something looks wrong."""
    from aarya_voice_lab.identity.contracts import pipeline_status
    from aarya_voice_lab.identity.embeddings import any_real_provider_available
    from aarya_voice_lab.security.source_protection import scan_git_repo

    root = root or PROJECT_ROOT
    scan = scan_git_repo(root)
    log = AuditLog(data_root)
    audit_summary = log.summary()
    pipeline = pipeline_status(data_root)

    problems: list[str] = []
    if not scan.ok:
        problems.append(f"{len(scan.violations)} protected-material violation(s) in Git")
    if not audit_summary["chain_intact"]:
        problems.extend(audit_summary["chain_problems"])

    return _envelope(
        "diagnostics",
        {
            "healthy": not problems,
            "problems": problems,
            "git_safety_ok": scan.ok,
            "audit_chain_intact": audit_summary["chain_intact"],
            "stages_implemented": pipeline["implemented_count"],
            "identity_boundary_stage": pipeline["identity_boundary_stage"],
            # Real ML Runtime milestone follow-up (D11 audit): this used to
            # be hardcoded False, which became an active false statement
            # the moment a real embedding provider became genuinely
            # installable -- see identity.embeddings.any_real_provider_available's
            # own docstring for why "registered" is never trusted as
            # "installed".
            "real_provider_installed": any_real_provider_available(),
            "real_recordings_present": bool(
                data_root.source.is_dir() and any(data_root.source.rglob("*"))
            ),
        },
    )


def verification_commands() -> dict[str, Any]:
    """The checks the panel can run, so "run tests" is a described action."""
    return _envelope(
        "verification_commands",
        {
            "commands": [
                {"id": "tests", "label": "Run test suite", "command": ["python", "-m", "pytest", "-q"]},
                {"id": "lint", "label": "Run lint", "command": ["ruff", "check", "."]},
                {"id": "verify_all", "label": "Full verification sweep", "command": ["scripts/verify_all.sh"]},
                {
                    "id": "git_safety",
                    "label": "Git safety scan",
                    "command": ["aarya-voice", "validate-environment"],
                },
                {
                    "id": "synthetic_e2e",
                    "label": "Synthetic end-to-end",
                    "command": ["aarya-voice", "synthetic-e2e", "--json"],
                },
            ],
            "note": "Descriptors only; the desktop runs these through the CLI.",
        },
    )


def command_center_snapshot(data_root: DataRoot, root: Path | None = None) -> dict[str, Any]:
    """Everything the Command Center needs on load, in one call."""
    return _envelope(
        "command_center_snapshot",
        {
            "repository": repository_context(root),
            "commands": command_catalogue(),
            "verification": verification_commands(),
            "activity": activity_feed(data_root),
            "diagnostics": diagnostics(data_root, root),
        },
    )
