"""IndicF5 installer status/reporting -- Phase F.

Aggregates everything Phases A-E already built into one report with a
single READY/NOT_READY answer, reusing the existing `Capability`/
`CapabilityState` model (`core.capability`) and the existing environment
audit architecture (`environment.audit`/`environment.verify`) throughout
-- this module adds no new capability vocabulary, only assembles
existing, already-tested checks plus a few new OS/architecture facts in
the same shape.

**Never modifies, imports internals of, or duplicates the logic of**
`scripts/indicf5_smoke_test.py` (Phase E, already reviewed and approved)
-- that script is invoked as a subprocess and treated as an already-
verified black box; its own structured "Summary for the Phase E report"
section (designed with exactly this consumer in mind) is parsed for
metrics, and its exit code is the only thing that determines pass/fail.
This keeps Phase E's approved behavior completely untouched by Phase F.

READY is set **only** when this module's own call actually ran the real
smoke test and it passed -- never inferred, never cached from a previous
run, never set merely because earlier diagnostic checks looked fine
(imports/detection alone are never sufficient, per Phase F's own
requirement).

The HuggingFace token is never part of anything this module reads,
stores, or reports -- `pipeline.hf_auth.HFAuthStatus` never carries it,
and nothing here touches `huggingface_hub` directly.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from aarya_voice_lab.core.capability import BLOCKING_STATES, Capability, CapabilityState
from aarya_voice_lab.core.paths import PROJECT_ROOT
from aarya_voice_lab.environment.audit import check_indicf5_vram_tier, run_audit
from aarya_voice_lab.environment.specs import EnvironmentId
from aarya_voice_lab.pipeline.hf_auth import HFAuthError, check_existing_login
from aarya_voice_lab.pipeline.indicf5_provisioning import ProvisioningError
from aarya_voice_lab.pipeline.indicf5_provisioning import verify as verify_provisioning
from aarya_voice_lab.pipeline.runner import default_environment_root, safe_path_is_file
from aarya_voice_lab.system_info import get_os_info

_SMOKE_TEST_SCRIPT = PROJECT_ROOT / "scripts" / "indicf5_smoke_test.py"
_SMOKE_TEST_TIMEOUT_SECONDS = 300.0


class InstallerReadiness(StrEnum):
    READY = "READY"
    NOT_READY = "NOT_READY"


class FailureCategory(StrEnum):
    """The 14 actionable categories Phase F requires distinguishing.
    A report's `failure_categories` names zero or more of these -- zero
    only when readiness is READY."""

    PYTHON_INCOMPATIBLE = "python_incompatible"
    INSUFFICIENT_RAM = "insufficient_ram"
    INSUFFICIENT_DISK = "insufficient_disk"
    GPU_UNAVAILABLE = "gpu_unavailable"
    INSUFFICIENT_VRAM = "insufficient_vram"
    CUDA_UNAVAILABLE = "cuda_unavailable"
    TTS_ENVIRONMENT_MISSING = "tts_environment_missing"
    HF_AUTH_MISSING = "hf_auth_missing"
    HF_GATED_ACCESS_DENIED = "hf_gated_access_denied"
    HF_NETWORK_FAILURE = "hf_network_failure"
    MODEL_MISSING = "model_missing"
    MODEL_CORRUPTION = "model_corruption"
    WORKER_STARTUP_FAILURE = "worker_startup_failure"
    MODEL_LOADING_FAILURE = "model_loading_failure"
    INFERENCE_FAILURE = "inference_failure"


@dataclass(frozen=True)
class InstallerReport:
    readiness: InstallerReadiness
    generated_at: str
    capabilities: tuple[Capability, ...] = field(default_factory=tuple)
    failure_categories: tuple[str, ...] = field(default_factory=tuple)
    smoke_test_ran: bool = False
    smoke_test_detail: str = ""
    generated_wav_paths: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Machine-readable form -- exactly `Capability.to_dict()` for
        every entry, matching `EnvironmentAudit.to_dict()`'s own shape."""
        return {
            "readiness": self.readiness.value,
            "generated_at": self.generated_at,
            "capabilities": [c.to_dict() for c in self.capabilities],
            "failure_categories": list(self.failure_categories),
            "smoke_test_ran": self.smoke_test_ran,
            "smoke_test_detail": self.smoke_test_detail,
            "generated_wav_paths": list(self.generated_wav_paths),
        }


def _tts_python() -> Path:
    return default_environment_root(EnvironmentId.TTS, base=PROJECT_ROOT).python


def _os_capabilities() -> list[Capability]:
    os_info = get_os_info()
    windows_cap = Capability(
        "Windows version",
        CapabilityState.AVAILABLE if os_info.system == "Windows" else CapabilityState.INCOMPATIBLE,
        detail=os_info.platform,
        version=os_info.release,
    )
    #: "AMD64" (Windows' own platform.machine() value) or "x86_64" (POSIX) -- the two 64-bit x86 spellings.
    is_x64 = os_info.machine in ("AMD64", "x86_64")
    arch_cap = Capability(
        "Architecture",
        CapabilityState.AVAILABLE if is_x64 else CapabilityState.INCOMPATIBLE,
        detail="" if is_x64 else "IndicF5's verified wheels are x64 only",
        version=os_info.machine,
    )
    return [windows_cap, arch_cap]


def _run_tts_check_json() -> dict[str, Any] | None:
    """Runs `tts-check --json` using env-tts's OWN interpreter -- reuses
    the existing `environment.verify.verify_environment()` machinery
    exactly as designed (its own docstring: "designed to run inside the
    environment being checked"), which is the only way to get real
    torch/CUDA/GPU facts instead of the base interpreter's honest but
    unhelpful UNKNOWN (base has no torch by design). Returns None if
    env-tts isn't built or the command fails to run at all."""
    tts_python = _tts_python()
    if not safe_path_is_file(tts_python):
        return None
    try:
        result = subprocess.run(  # noqa: S603 -- fixed argv, no shell, no untrusted input
            [str(tts_python), "-m", "aarya_voice_lab.cli.main", "tts-check", "--json"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if not result.stdout.strip():
        return None
    import json

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _parse_smoke_test_summary(stdout: str) -> dict[str, str]:
    """Parses the `key = value` lines under
    "--- Summary for the Phase E report ---", exactly the section
    `scripts/indicf5_smoke_test.py` already prints for this purpose."""
    lines = (stdout or "").splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if "Summary for the Phase E report" in line) + 1
    except StopIteration:
        return {}
    summary: dict[str, str] = {}
    for line in lines[start:]:
        if " = " not in line:
            continue
        key, _, value = line.partition(" = ")
        summary[key.strip()] = value.strip()
    return summary


def _classify_smoke_test_failure(stdout: str, stderr: str) -> tuple[FailureCategory, str]:
    """Best-effort classification from the subprocess's own output --
    the smoke test script's PASS markers indicate how far it got before
    failing. Not perfectly precise (this is external process output being
    parsed, not a structured failure code), but every branch is honest
    about what it actually observed rather than guessing silently."""
    stdout = stdout or ""
    stderr = stderr or ""
    reached_load = "PASS: real model+vocoder load happened" in stdout
    reached_generate = "PASS: PreviewArtifact contract correct" in stdout

    detail = ""
    for line in reversed(stderr.splitlines()):
        if line.strip():
            detail = line.strip()
            break
    if not detail:
        for line in reversed(stdout.splitlines()):
            if line.strip():
                detail = line.strip()
                break

    if not reached_load:
        return FailureCategory.MODEL_LOADING_FAILURE, detail or "model/vocoder failed to load"
    if not reached_generate:
        return FailureCategory.INFERENCE_FAILURE, detail or "generation or WAV validation failed"
    return FailureCategory.INFERENCE_FAILURE, detail or "smoke test failed after initial generation succeeded"


@dataclass(frozen=True)
class _SmokeTestOutcome:
    ok: bool
    detail: str
    failure_category: FailureCategory | None = None
    wav_paths: tuple[str, ...] = ()
    metrics: dict[str, str] = field(default_factory=dict)


def _run_smoke_test_subprocess() -> _SmokeTestOutcome:
    """Invokes the already-verified `scripts/indicf5_smoke_test.py`
    unchanged, as a subprocess of the CURRENT (base) interpreter -- that
    script is itself base-interpreter-safe (stdlib-only WAV validation,
    per its own Phase E design)."""
    try:
        result = subprocess.run(  # noqa: S603 -- fixed argv, no shell, no untrusted input
            [sys.executable, str(_SMOKE_TEST_SCRIPT)],
            capture_output=True,
            text=True,
            # Windows' default locale (cp1252) cannot decode the
            # Devanagari verification text this script prints -- the same
            # class of issue already fixed elsewhere this session
            # (worker subprocesses, console reconfiguration). Without
            # this, capture_output's reader thread raises
            # UnicodeDecodeError and result.stdout/stderr come back None.
            encoding="utf-8",
            errors="replace",
            timeout=_SMOKE_TEST_TIMEOUT_SECONDS,
            check=False,
            cwd=str(PROJECT_ROOT),
        )
    except subprocess.TimeoutExpired:
        return _SmokeTestOutcome(
            ok=False,
            detail=f"smoke test timed out after {_SMOKE_TEST_TIMEOUT_SECONDS}s",
            failure_category=FailureCategory.INFERENCE_FAILURE,
        )
    except OSError as exc:
        return _SmokeTestOutcome(
            ok=False,
            detail=f"could not start the smoke test process: {exc}",
            failure_category=FailureCategory.WORKER_STARTUP_FAILURE,
        )

    if result.returncode != 0:
        category, detail = _classify_smoke_test_failure(result.stdout, result.stderr)
        return _SmokeTestOutcome(ok=False, detail=detail, failure_category=category)

    summary = _parse_smoke_test_summary(result.stdout)
    wav_paths = tuple(p for p in (summary.get("wav1"), summary.get("wav2")) if p)
    return _SmokeTestOutcome(ok=True, detail="all mechanical checks passed", wav_paths=wav_paths, metrics=summary)


def build_installer_report(*, run_smoke_test: bool = True) -> InstallerReport:
    """The full Phase F aggregation. Cheap/fast checks run first and can
    short-circuit before the expensive (tens of seconds) real smoke test
    -- if the machine is already known-blocked (e.g. insufficient VRAM),
    there is no reason to spend a minute proving it further. Every early
    exit still produces a complete, honestly-labelled report; only the
    smoke-test-dependent capabilities (model loading / GPU worker / real
    inference / WAV validation) are absent when skipped, and
    `smoke_test_ran=False` says so explicitly rather than implying they
    were checked."""
    capabilities: list[Capability] = []
    failure_categories: list[FailureCategory] = []

    capabilities.extend(_os_capabilities())
    if any(c.state in BLOCKING_STATES for c in capabilities):
        failure_categories.append(FailureCategory.PYTHON_INCOMPATIBLE)  # architecture mismatch, closest category

    audit = run_audit()
    for cap in audit.capabilities:
        if cap.name not in ("Python", "RAM", "Disk space"):
            continue
        capabilities.append(cap)
        if cap.name == "Python" and cap.state is CapabilityState.INCOMPATIBLE:
            failure_categories.append(FailureCategory.PYTHON_INCOMPATIBLE)
        elif cap.name == "RAM" and cap.state is CapabilityState.INCOMPATIBLE:
            failure_categories.append(FailureCategory.INSUFFICIENT_RAM)
        elif cap.name == "Disk space" and cap.state is CapabilityState.NOT_AVAILABLE:
            failure_categories.append(FailureCategory.INSUFFICIENT_DISK)

    vram_cap = check_indicf5_vram_tier()
    capabilities.append(vram_cap)
    if vram_cap.state is CapabilityState.INCOMPATIBLE:
        failure_categories.append(FailureCategory.INSUFFICIENT_VRAM)
    elif vram_cap.state is CapabilityState.OPTIONAL and "no nvidia gpu detected" in vram_cap.detail.lower():
        failure_categories.append(FailureCategory.GPU_UNAVAILABLE)

    tts_check = _run_tts_check_json()
    if tts_check is None:
        capabilities.append(
            Capability(
                "TTS environment",
                CapabilityState.NOT_AVAILABLE,
                "`.envs/env-tts` is not built -- run Phase B provisioning first (see docs/INDICF5_INSTALLER.md)",
            )
        )
        failure_categories.append(FailureCategory.TTS_ENVIRONMENT_MISSING)
    else:
        for entry in tts_check.get("capabilities", []):
            if entry["name"] == "IndicF5 VRAM tier":
                continue  # already added directly above; tts-check includes it too (Phase B wiring)
            capabilities.append(
                Capability(
                    entry["name"], CapabilityState(entry["state"]), entry.get("detail", ""), entry.get("version")
                )
            )
            if entry["name"] in ("torch", "torchaudio", "transformers", "PyTorch", "CUDA runtime"):
                if CapabilityState(entry["state"]) is CapabilityState.INCOMPATIBLE:
                    failure_categories.append(FailureCategory.CUDA_UNAVAILABLE)

    if not failure_categories:
        try:
            login_status = check_existing_login()
        except HFAuthError as exc:
            capabilities.append(Capability("HuggingFace authentication", CapabilityState.UNKNOWN, str(exc)))
            failure_categories.append(FailureCategory.HF_NETWORK_FAILURE)
        else:
            capabilities.append(
                Capability(
                    "HuggingFace authentication",
                    CapabilityState.AVAILABLE if login_status.authenticated else CapabilityState.NOT_AVAILABLE,
                    detail=login_status.detail
                    or (f"logged in as {login_status.username}" if login_status.username else ""),
                )
            )
            if not login_status.authenticated:
                failure_categories.append(FailureCategory.HF_AUTH_MISSING)

    if not failure_categories:
        try:
            provisioning_result = verify_provisioning()
            capabilities.append(
                Capability(
                    "IndicF5 model/cache",
                    CapabilityState.AVAILABLE if provisioning_result.ok else CapabilityState.NOT_AVAILABLE,
                    detail="; ".join(provisioning_result.summary_lines()) or "all required assets present",
                )
            )
        except ProvisioningError as exc:
            capabilities.append(Capability("IndicF5 model/cache", CapabilityState.NOT_AVAILABLE, str(exc)))
            failure_kind_map = {
                "authentication": FailureCategory.HF_AUTH_MISSING,
                "gated_access": FailureCategory.HF_GATED_ACCESS_DENIED,
                "network": FailureCategory.HF_NETWORK_FAILURE,
                "disk": FailureCategory.INSUFFICIENT_DISK,
                "corruption": FailureCategory.MODEL_CORRUPTION,
            }
            failure_categories.append(failure_kind_map.get(exc.failure_kind, FailureCategory.MODEL_MISSING))

    smoke_test_ran = False
    smoke_test_detail = "not run"
    wav_paths: tuple[str, ...] = ()

    if failure_categories:
        smoke_test_detail = "skipped -- earlier checks already indicate this machine is not ready"
    elif not run_smoke_test:
        smoke_test_detail = "skipped by caller (run_smoke_test=False) -- readiness cannot be confirmed without it"
    else:
        smoke_test_ran = True
        outcome = _run_smoke_test_subprocess()
        smoke_test_detail = outcome.detail
        if outcome.ok:
            wav_paths = outcome.wav_paths
            for name in ("Model loading", "GPU worker", "Real inference", "WAV validation"):
                capabilities.append(Capability(name, CapabilityState.AVAILABLE, detail=smoke_test_detail))
        else:
            if outcome.failure_category is not None:
                failure_categories.append(outcome.failure_category)
            capabilities.append(Capability("Real inference smoke test", CapabilityState.NOT_AVAILABLE, outcome.detail))

    # READY only when this call itself actually ran the smoke test and it
    # passed -- never inferred from earlier checks alone (Phase F's own
    # "imports/detection are never sufficient" requirement).
    readiness = (
        InstallerReadiness.READY
        if (smoke_test_ran and not failure_categories)
        else InstallerReadiness.NOT_READY
    )

    return InstallerReport(
        readiness=readiness,
        generated_at=datetime.now(UTC).isoformat(),
        capabilities=tuple(capabilities),
        # de-duplicated, order-preserving
        failure_categories=tuple(dict.fromkeys(fc.value for fc in failure_categories)),
        smoke_test_ran=smoke_test_ran,
        smoke_test_detail=smoke_test_detail,
        generated_wav_paths=wav_paths,
    )


def format_installer_report(report: InstallerReport) -> str:
    """Human-readable, for a non-developer -- mirrors
    `environment.audit.format_audit()`/`environment.verify.format_verification()`'s
    established free-function convention exactly."""
    lines = [
        "AARYA Voice Lab — IndicF5 Installer Report",
        "=" * 60,
        f"Generated: {report.generated_at}",
        "",
    ]
    lines.extend(c.format_line() for c in report.capabilities)
    lines.append("")
    if report.failure_categories:
        lines.append("Problems found:")
        lines.extend(f"  - {category}" for category in report.failure_categories)
        lines.append("")
    lines.append(f"Real speech-generation test: {report.smoke_test_detail}")
    if report.generated_wav_paths:
        lines.append("Generated audio (a human should listen to confirm it sounds right):")
        lines.extend(f"  - {p}" for p in report.generated_wav_paths)
    lines.append("")
    if report.readiness is InstallerReadiness.READY:
        lines.append("RESULT: READY. IndicF5 generated real, validated speech on this machine.")
    else:
        lines.append("RESULT: NOT READY. See the problems listed above.")
    return "\n".join(lines)
