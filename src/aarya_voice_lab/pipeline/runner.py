"""Cross-environment stage execution.

A stage that needs NeMo must run under env-nemo's interpreter; a stage
that needs WhisperX must run under env-whisperx's. This module launches
them as subprocesses and never imports their libraries into the calling
process — that separation is the whole point (docs/COMPATIBILITY.md).

Phase 1 status: the invocation mechanism, preflight checks, and result
recording are implemented and tested with a synthetic stage. The real
diarization/transcription stage bodies are NOT implemented and no private
recording is processed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from aarya_voice_lab.environment.specs import (
    EnvironmentId,
    EnvironmentSpec,
    ExternalRequirement,
    get_spec,
)
from aarya_voice_lab.pipeline.contracts import (
    StageResult,
    StageStatus,
    describe_artifact,
    require_predecessor,
    stage_directory,
)
from aarya_voice_lab.pipeline.stages import PipelineStage

#: Environment variables that disable third-party telemetry in ML stacks.
#: NeMo transitively installs wandb, sentry-sdk, nv-one-logger and
#: OpenTelemetry exporters; all of them can phone home. A local-first
#: project must switch them off explicitly rather than trusting defaults.
TELEMETRY_OFF_ENV: dict[str, str] = {
    "WANDB_MODE": "offline",
    "WANDB_DISABLED": "true",
    "SENTRY_DSN": "",
    "NEMO_TELEMETRY_OPT_OUT": "1",
    "NVIDIA_ONE_LOGGER_DISABLED": "1",
    "OTEL_SDK_DISABLED": "true",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
}

#: Forces HuggingFace libraries to fail rather than silently download.
OFFLINE_ENV: dict[str, str] = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
}


class StageBlocked(RuntimeError):
    """A stop condition prevented the stage from running."""

    def __init__(self, kind: str, message: str, remediation: str | None = None):
        super().__init__(message)
        self.kind = kind
        self.remediation = remediation


def safe_path_is_file(path: Path) -> bool:
    """`Path.exists()`/`Path.is_file()` can *raise* `OSError` rather than
    return `False` for a broken symlink/junction on native Windows --
    confirmed empirically (WinError 1920, "The file cannot be accessed
    by the system") for a `.envs/<name>` environment that was built from
    WSL against a Windows-mounted path: its `bin/python` symlink points
    at `/usr/bin/python3`, which does not exist here. Any such OSError
    means the path is not a usable file, which is exactly what this
    function reports -- never propagated as a crash. See
    docs/ENVIRONMENT.md's "A `.envs/<name>` built from WSL is not usable
    from native Windows" section.
    """
    try:
        return path.is_file()
    except OSError:
        return False


@dataclass(frozen=True)
class EnvironmentPaths:
    """Where a built environment lives on this machine."""

    root: Path

    @property
    def python(self) -> Path:
        windows = self.root / "Scripts" / "python.exe"
        return windows if safe_path_is_file(windows) else self.root / "bin" / "python"

    def exists(self) -> bool:
        return safe_path_is_file(self.python)


def default_environment_root(env_id: EnvironmentId, base: Path | None = None) -> EnvironmentPaths:
    return EnvironmentPaths(root=(base or Path.cwd()) / ".envs" / env_id.value)


def build_subprocess_env(
    *,
    offline: bool = True,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Environment variables for a stage subprocess.

    Telemetry is always disabled. `offline` additionally prevents model
    hubs from downloading, which is the correct default for any stage
    touching private material: a stage should fail loudly rather than
    quietly fetch something.
    """
    env = dict(os.environ)
    env.update(TELEMETRY_OFF_ENV)
    if offline:
        env.update(OFFLINE_ENV)
    if extra:
        env.update(extra)
    return env


def preflight(
    stage: PipelineStage,
    spec: EnvironmentSpec,
    env_paths: EnvironmentPaths,
    *,
    require_ffmpeg: bool = False,
    allow_approval_required: bool = False,
) -> None:
    """Raise StageBlocked if the stage must not run. Checks before acting."""
    if spec.requires_approval and not allow_approval_required:
        raise StageBlocked(
            "gated_model" if ExternalRequirement.GATED_MODEL_DOWNLOAD in spec.external_requirements
            else "external_service_required",
            f"{spec.env_id.value} requires approval before use: {spec.requires_approval}",
            "Obtain explicit sign-off, then re-run with the approval flag set.",
        )

    if ExternalRequirement.CREDENTIAL in spec.external_requirements and not allow_approval_required:
        raise StageBlocked(
            "credential_required",
            f"{spec.env_id.value} requires an operator-supplied credential.",
            "Credentials are never configured automatically. STOP and report.",
        )

    if not env_paths.exists():
        raise StageBlocked(
            "incompatible_environment",
            f"Environment {spec.env_id.value} is not built at {env_paths.root}",
            f"Build it with: scripts/install_env.sh {spec.env_id.value}",
        )

    if require_ffmpeg and shutil.which("ffmpeg") is None:
        raise StageBlocked(
            "missing_dependency",
            "FFmpeg is required for this stage but was not found on PATH.",
            "See docs/ENVIRONMENT.md for per-OS installation instructions.",
        )


def run_stage(
    stage: PipelineStage,
    env_id: EnvironmentId,
    command: list[str],
    run_dir: Path,
    *,
    env_paths: EnvironmentPaths | None = None,
    inputs: list[Path] | None = None,
    require_predecessor_complete: bool = True,
    require_ffmpeg: bool = False,
    allow_approval_required: bool = False,
    offline: bool = True,
    timeout: int = 3600,
) -> StageResult:
    """Execute one stage in its own environment and record the result.

    Always returns a StageResult (written to disk); it does not raise on
    stage failure, because a recorded failure is itself part of the
    contract that lets a run be inspected and resumed.
    """
    spec = get_spec(env_id)
    paths = env_paths or default_environment_root(env_id, run_dir.parent)
    result = StageResult(stage=stage, environment_id=env_id.value)

    run_dir.mkdir(parents=True, exist_ok=True)

    try:
        if require_predecessor_complete:
            require_predecessor(run_dir, stage)
        preflight(
            stage,
            spec,
            paths,
            require_ffmpeg=require_ffmpeg,
            allow_approval_required=allow_approval_required,
        )
    except StageBlocked as blocked:
        result.mark_blocked(blocked.kind, str(blocked), blocked.remediation)
        result.write(run_dir)
        return result
    except Exception as exc:  # noqa: BLE001 - contract violations are recorded, not raised
        result.mark_failed("invalid_input", str(exc))
        result.write(run_dir)
        return result

    for path in inputs or []:
        result.inputs.append(describe_artifact(path, run_dir))

    result.status = StageStatus.RUNNING
    try:
        completed = subprocess.run(
            [str(paths.python), *command],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=run_dir,
            env=build_subprocess_env(offline=offline),
            check=False,
        )
    except subprocess.TimeoutExpired:
        result.mark_failed("execution_error", f"stage timed out after {timeout}s")
        result.write(run_dir)
        return result
    except OSError as exc:
        result.mark_failed("execution_error", f"could not launch stage: {exc}")
        result.write(run_dir)
        return result

    if completed.returncode != 0:
        result.mark_failed(
            "execution_error",
            f"stage exited {completed.returncode}: {(completed.stderr or '').strip()[:2000]}",
        )
        result.write(run_dir)
        return result

    stage_dir = stage_directory(run_dir, stage)
    if stage_dir.is_dir():
        for produced in sorted(stage_dir.iterdir()):
            if produced.is_file() and produced.name != "result.json":
                result.outputs.append(describe_artifact(produced, run_dir))

    result.mark_completed()
    result.write(run_dir)
    return result
