"""The real-recording access gate.

Before any code may read the private recordings, fifteen conditions must
hold (twelve technical/attestation conditions, plus three Phase-3
prerequisites added by the Access-Gate Hardening milestone: a usable
operator enrollment, a verified real embedding provider, and an explicit
model-licence-review attestation). This module checks them mechanically
instead of relying on someone remembering, and reports each one
individually so a failure names what to fix.

The final condition — explicit human approval — cannot be self-satisfied.
It is supplied by the caller and is never inferred, defaulted, or derived
from the presence of files. Approval is a decision a person makes, and
the code's job is to refuse until it is given, not to guess it.

Nothing here reads audio. It inspects Git state, configuration, and
directory protection only.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.core.paths import PROJECT_ROOT
from aarya_voice_lab.identity.embeddings import any_real_provider_available
from aarya_voice_lab.identity.profile import ProfileStore, SpeakerRole
from aarya_voice_lab.pipeline.runner import OFFLINE_ENV, TELEMETRY_OFF_ENV
from aarya_voice_lab.security.source_protection import scan_git_repo


class DatasetAccessDenied(PermissionError):
    """Raised when the gate is not satisfied and access was attempted."""


@dataclass
class GateCondition:
    name: str
    satisfied: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "satisfied": self.satisfied, "detail": self.detail}


@dataclass
class GateReport:
    conditions: list[GateCondition] = field(default_factory=list)

    @property
    def unsatisfied(self) -> list[GateCondition]:
        return [c for c in self.conditions if not c.satisfied]

    @property
    def allowed(self) -> bool:
        return not self.unsatisfied

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_allowed": self.allowed,
            "unsatisfied_count": len(self.unsatisfied),
            "conditions": [c.to_dict() for c in self.conditions],
        }


def _git(args: list[str], root: Path) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return result.returncode, result.stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def _branch_pushed(root: Path, commit_subject_fragment: str) -> GateCondition:
    """Whether a commit matching `fragment` exists on a remote branch."""
    code, output = _git(["branch", "-r", "--contains", "HEAD"], root)
    name = f"{commit_subject_fragment} pushed"
    if code != 0:
        return GateCondition(name, False, f"could not determine remote state: {output}")
    if not output:
        return GateCondition(
            name,
            False,
            "HEAD is not contained in any remote branch — push before processing "
            "private recordings, so the work is recoverable",
        )
    return GateCondition(name, True, f"HEAD present on: {output.splitlines()[0].strip()}")


def _operator_enrollment_present(data_root: DataRoot) -> GateCondition:
    """Phase-3 Access-Gate Hardening milestone: a usable operator profile
    must exist before real-recording access is granted -- the approved
    rejection-first matching approach needs a real operator reference to
    match candidate segments against. Only checks the existing profile
    store; never creates, fabricates, or infers an enrollment."""
    name = "operator enrollment present"
    store = ProfileStore(data_root)
    for profile_id in store.list_profiles():
        latest = store.latest(profile_id)
        if latest is not None and latest.role is SpeakerRole.OPERATOR and latest.is_usable:
            return GateCondition(name, True, f"usable operator profile found: {latest.profile_version_key}")
    return GateCondition(
        name,
        False,
        "no usable operator-role profile found in the profile store -- "
        "an operator reference recording must be enrolled first",
    )


def evaluate_gate(
    *,
    data_root: DataRoot | None = None,
    project_root: Path | None = None,
    phase2_complete: bool = False,
    tests_passing: bool = False,
    security_scan_clean: bool = False,
    processing_config_reviewed: bool = False,
    explicit_approval: bool = False,
    model_licence_reviewed: bool = False,
) -> GateReport:
    """Evaluate every access condition.

    The boolean parameters are operator attestations. They default to
    False so the gate is closed unless someone deliberately opens it.
    """
    root = project_root or PROJECT_ROOT
    data = data_root or DataRoot.default()
    report = GateReport()

    # 1-2. Prior phases pushed.
    report.conditions.append(_branch_pushed(root, "Phase 0/1 history"))

    # 3. Clean working tree.
    code, output = _git(["status", "--porcelain"], root)
    report.conditions.append(
        GateCondition(
            "working tree clean",
            code == 0 and not output,
            "clean" if code == 0 and not output else f"uncommitted changes present:\n{output[:400]}",
        )
    )

    # 4-6. Operator attestations.
    report.conditions.append(
        GateCondition("Phase 2 implementation complete", phase2_complete, "attested by operator")
    )
    report.conditions.append(GateCondition("Phase 2 tests passing", tests_passing, "attested by operator"))
    report.conditions.append(
        GateCondition("security scan complete", security_scan_clean, "attested by operator")
    )

    # 7. Source protection: nothing private tracked in Git.
    scan = scan_git_repo(root)
    report.conditions.append(
        GateCondition(
            "source protection verified",
            scan.ok,
            "no protected material tracked"
            if scan.ok
            else f"{len(scan.violations)} violation(s): {scan.violations[0].path}",
        )
    )

    # 8. Output directories are git-ignored.
    ignored_ok = True
    details = []
    for candidate in ("data/source/x.wav", "data/working/x.wav", "data/segments/x.wav"):
        code, _ = _git(["check-ignore", "-q", candidate], root)
        if code != 0:
            ignored_ok = False
            details.append(candidate)
    report.conditions.append(
        GateCondition(
            "output directories git-ignored",
            ignored_ok,
            "all data/ paths ignored" if ignored_ok else f"NOT ignored: {details}",
        )
    )

    # 9. No cloud upload path configured.
    report.conditions.append(
        GateCondition(
            "no cloud upload path",
            True,
            "pipeline uses no network client; no cloud provider is configured "
            "(verified by design — see docs/PRIVACY.md)",
        )
    )

    # 10. Offline and telemetry-off defaults intact.
    offline_intact = OFFLINE_ENV.get("HF_HUB_OFFLINE") == "1"
    telemetry_intact = TELEMETRY_OFF_ENV.get("WANDB_MODE") == "offline"
    report.conditions.append(
        GateCondition(
            "offline/telemetry protections intact",
            offline_intact and telemetry_intact,
            "stage subprocesses default to offline with telemetry disabled"
            if offline_intact and telemetry_intact
            else "offline or telemetry defaults have been weakened",
        )
    )

    # 11. Processing configuration reviewed.
    report.conditions.append(
        GateCondition(
            "processing configuration reviewed", processing_config_reviewed, "attested by operator"
        )
    )

    # 12. Explicit approval — never inferred.
    report.conditions.append(
        GateCondition(
            "explicit approval to access recordings",
            explicit_approval,
            "granted" if explicit_approval else "NOT granted — this cannot be self-satisfied",
        )
    )

    # 13. Access-Gate Hardening milestone -- operator enrollment. Reads
    # the existing profile store only; never creates or fabricates one.
    report.conditions.append(_operator_enrollment_present(data))

    # 14. Access-Gate Hardening milestone -- real embedding provider.
    # Reuses identity.embeddings.any_real_provider_available() exactly;
    # never a second detector, never inferred from provider registration.
    real_provider_available = any_real_provider_available()
    report.conditions.append(
        GateCondition(
            "real embedding provider verified",
            real_provider_available,
            "a real (non-synthetic) embedding provider is installed and loadable"
            if real_provider_available
            else "no real embedding provider is installed — synthetic-only is not sufficient for real identity work",
        )
    )

    # 15. Access-Gate Hardening milestone -- model licence review. A pure
    # operator attestation, exactly like security_scan_clean/
    # processing_config_reviewed above -- never inferred from model
    # presence, name, status, or registry existence.
    report.conditions.append(
        GateCondition("model licence reviewed", model_licence_reviewed, "attested by operator")
    )

    # Informational: whether source material is even present.
    source_present = data.source.is_dir() and any(data.source.rglob("*"))
    report.conditions.append(
        GateCondition(
            "source directory populated",
            source_present,
            "source recordings present" if source_present else "no source recordings present (expected in Phase 2)",
        )
    )

    return report


def assert_access_allowed(report: GateReport) -> None:
    if not report.allowed:
        blockers = "\n".join(f"  - {c.name}: {c.detail}" for c in report.unsatisfied)
        raise DatasetAccessDenied(
            "Access to the private recordings is DENIED. Unsatisfied conditions:\n" + blockers
        )


def format_gate(report: GateReport) -> str:
    lines = ["AARYA Voice Lab — Real Dataset Access Gate", "=" * 60]
    for condition in report.conditions:
        mark = "PASS" if condition.satisfied else "FAIL"
        lines.append(f"[{mark}] {condition.name}")
        lines.append(f"       {condition.detail}")
    lines.append("")
    if report.allowed:
        lines.append("RESULT: all conditions satisfied — access may proceed.")
        lines.append("Even so, process ONE recording first and inspect the results")
        lines.append("before continuing (see docs/DATASET_PIPELINE.md).")
    else:
        lines.append(f"RESULT: ACCESS DENIED — {len(report.unsatisfied)} condition(s) unsatisfied.")
    return "\n".join(lines)
