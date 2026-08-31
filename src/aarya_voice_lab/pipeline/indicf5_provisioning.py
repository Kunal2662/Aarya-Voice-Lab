"""IndicF5 model/cache provisioning for the installer -- Phase D.

Downloads and verifies exactly the files `pipeline.indicf5_generation`'s
production worker needs, via `scripts/ml_workers/
indicf5_provisioning_worker.py` (subprocess-isolated in `.envs/env-tts`,
same reasoning as `pipeline.hf_auth`: `huggingface_hub`/`safetensors`/
`torch` are not base-interpreter dependencies). Never writes anything
into this repository -- every file lands in huggingface_hub's own cache
(`~/.cache/huggingface/hub/...`), which is how "do not place model
weights in Git" is satisfied structurally, not by discipline alone.

Does not modify `pipeline.indicf5_generation`, its worker, or the
vendored `indicf5_f5tts` package -- this module only provisions the
files those already-verified components read.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aarya_voice_lab.core.paths import PROJECT_ROOT
from aarya_voice_lab.environment.specs import EnvironmentId
from aarya_voice_lab.pipeline.hf_auth import check_existing_login
from aarya_voice_lab.pipeline.indicf5_generation import (
    DEFAULT_REF_AUDIO_REPO_FILENAME,
    DEFAULT_REPO_ID,
)
from aarya_voice_lab.pipeline.runner import build_subprocess_env, default_environment_root, safe_path_is_file

_WORKER_SCRIPT = PROJECT_ROOT / "scripts" / "ml_workers" / "indicf5_provisioning_worker.py"
_WORKER_TIMEOUT_SECONDS = 900.0  # model.safetensors is ~1.4 GB; a slow link needs real headroom

#: Mirrors indicf5_provisioning_worker.py's own defaults for the vocoder
#: (not part of pipeline.indicf5_generation's own constants, since that
#: module never names the vocoder repo directly -- load_vocoder() inside
#: the vendored runtime does). Kept here, once, as the single source of
#: truth this module's requests are built from.
VOCODER_REPO_ID = "charactr/vocos-mel-24khz"
VOCODER_CONFIG_FILENAME = "config.yaml"
VOCODER_WEIGHTS_FILENAME = "pytorch_model.bin"


class ProvisioningError(RuntimeError):
    """Raised when the worker cannot be reached, or reports a failure it
    could not classify. A classified failure (authentication/gated_access/
    network/disk/corruption) is available via `.failure_kind`."""

    def __init__(self, message: str, *, failure_kind: str = "unknown", files: list[dict] | None = None) -> None:
        super().__init__(message)
        self.failure_kind = failure_kind
        self.files = files or []


@dataclass(frozen=True)
class FileProvisioningResult:
    name: str
    filename: str
    ok: bool
    status: str | None = None  # "already_cached" | "downloaded", only when ok
    size_bytes: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class ProvisioningResult:
    ok: bool
    files: tuple[FileProvisioningResult, ...] = field(default_factory=tuple)

    def summary_lines(self) -> list[str]:
        lines = []
        for f in self.files:
            if f.ok:
                size = f"{f.size_bytes / 1024**2:.1f} MiB" if f.size_bytes is not None else "?"
                status = f.status or "verified"
                lines.append(f"  [{status:>14}] {f.name} ({f.filename}) -- {size}, verified")
            else:
                lines.append(f"  [{'FAILED':>14}] {f.name} ({f.filename}) -- {f.error}")
        return lines


def _tts_python() -> Path | None:
    """Canonical `.envs/env-tts` only -- the installer's own environment,
    matching `pipeline.hf_auth`'s identical scoping decision."""
    paths = default_environment_root(EnvironmentId.TTS, base=PROJECT_ROOT)
    return paths.python if paths.exists() else None


def _default_request() -> dict[str, Any]:
    return {
        "repo_id": DEFAULT_REPO_ID,
        "ref_audio_filename": DEFAULT_REF_AUDIO_REPO_FILENAME,
        "vocoder_repo_id": VOCODER_REPO_ID,
        "vocoder_config_filename": VOCODER_CONFIG_FILENAME,
        "vocoder_weights_filename": VOCODER_WEIGHTS_FILENAME,
    }


def _run_worker(mode: str, *, timeout: float = _WORKER_TIMEOUT_SECONDS) -> dict:
    python_path = _tts_python()
    if python_path is None or not safe_path_is_file(python_path):
        raise ProvisioningError(
            "env-tts is not built yet -- model provisioning requires it "
            "(see docs/INDICF5_INSTALLER.md's provisioning step).",
            failure_kind="unknown",
        )

    request = {"mode": mode, **_default_request()}
    with tempfile.TemporaryDirectory(prefix="indicf5-provision-") as scratch:
        request_path = Path(scratch) / "request.json"
        response_path = Path(scratch) / "response.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")

        try:
            result = subprocess.run(  # noqa: S603 -- fixed argv, no shell, no untrusted input in argv itself
                [str(python_path), str(_WORKER_SCRIPT), str(request_path), str(response_path)],
                cwd=scratch,
                env=build_subprocess_env(offline=False),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProvisioningError(
                f"provisioning worker timed out after {timeout}s", failure_kind="network"
            ) from exc

        if not response_path.is_file():
            raise ProvisioningError(
                f"provisioning worker exited {result.returncode} with no response file -- "
                f"stderr: {result.stderr[-2000:]}",
                failure_kind="unknown",
            )
        return json.loads(response_path.read_text(encoding="utf-8"))


def _parse_result(response: dict) -> ProvisioningResult:
    files = tuple(
        FileProvisioningResult(
            name=f["name"],
            filename=f["filename"],
            ok=f["ok"],
            status=f.get("status"),
            size_bytes=f.get("size_bytes"),
            error=f.get("error"),
        )
        for f in response.get("files", [])
    )
    return ProvisioningResult(ok=bool(response.get("ok")), files=files)


def provision() -> ProvisioningResult:
    """Ensure every required IndicF5 asset (vocab, checkpoint, default
    reference audio, vocoder config + weights) is present in the
    HuggingFace cache and structurally valid -- downloading only what is
    missing, reusing everything already cached. Requires an authenticated,
    access-approved HuggingFace credential (IndicF5 is gated) -- callers
    should confirm `pipeline.hf_auth.check_existing_login()` first for a
    clearer error than what a bare 401 would give partway through."""
    response = _run_worker("provision")
    if not response.get("ok"):
        raise ProvisioningError(
            response.get("error", "unknown provisioning failure"),
            failure_kind=response.get("failure_kind", "unknown"),
            files=response.get("files", []),
        )
    return _parse_result(response)


def verify() -> ProvisioningResult:
    """Confirm every required asset is already cached and structurally
    valid, WITHOUT downloading anything -- the "can env-tts actually
    locate every required asset" check Phase D's acceptance criterion
    asks for. Raises ProvisioningError (failure_kind="network") if
    anything is missing, naming exactly which file."""
    response = _run_worker("verify")
    if not response.get("ok"):
        raise ProvisioningError(
            response.get("error", "unknown verification failure"),
            failure_kind=response.get("failure_kind", "unknown"),
            files=response.get("files", []),
        )
    return _parse_result(response)


def ensure_authenticated_then_provision() -> ProvisioningResult:
    """Convenience wrapper matching the installer's actual flow: confirm
    a real, working HuggingFace login exists BEFORE attempting
    provisioning, so a missing/expired credential is reported as exactly
    that (Phase C's own precise error) rather than surfacing later as a
    less specific download failure."""
    login_status = check_existing_login()
    if not login_status.authenticated:
        raise ProvisioningError(
            "no authenticated HuggingFace login is configured -- run the credential flow first "
            "(pipeline.hf_auth.prompt_and_login_interactive()).",
            failure_kind="authentication",
        )
    return provision()
