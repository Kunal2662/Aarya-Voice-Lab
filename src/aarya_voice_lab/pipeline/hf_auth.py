"""Secure HuggingFace authentication for the IndicF5 installer -- Phase C.

`huggingface_hub` is a lightweight network client, but it is still not a
base-interpreter dependency (`requirements/base.txt`'s own header:
"Nothing here pulls in... a network client") -- this module never imports
it. All real work happens in `scripts/ml_workers/hf_auth_worker.py`, run
as a subprocess under `.envs/env-tts`'s interpreter, mirroring
`identity.embeddings.LocalNeuralEmbeddingProvider`'s exact isolation
pattern and its one-shot request/response-file protocol.

## The token, end to end

- **Input**: `getpass.getpass()` -- no terminal echo. Never `input()`.
- **Validation**: a safe, read-only authenticated call (`whoami()`)
  inside the worker -- never a full model download just to test a token.
- **Storage**: `huggingface_hub.login()`'s own credential cache
  (`~/.cache/huggingface/token`) -- never a file in this repository,
  never an environment variable, never `configs/*.yaml`.
- **Logging**: the token value is never returned by the worker, never
  written to this module's own log/print calls, and never included in
  any exception message raised here (`huggingface_hub`'s own exceptions
  report the endpoint and HTTP status, not the credential used).
- **Reuse**: `check_existing_login()` is always tried first -- a
  previously-configured login (from this installer or from
  `huggingface-cli login` run manually) is detected and reused without
  re-prompting.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path

from aarya_voice_lab.core.paths import PROJECT_ROOT
from aarya_voice_lab.environment.specs import EnvironmentId
from aarya_voice_lab.pipeline.runner import build_subprocess_env, default_environment_root, safe_path_is_file

_WORKER_SCRIPT = PROJECT_ROOT / "scripts" / "ml_workers" / "hf_auth_worker.py"
_WORKER_TIMEOUT_SECONDS = 30.0


class HFAuthError(RuntimeError):
    """Raised when the worker cannot be reached or reports a failure.
    Never carries a token value -- see module docstring."""


@dataclass(frozen=True)
class HFAuthStatus:
    authenticated: bool
    username: str | None = None
    can_read_gated_repos: bool | None = None
    detail: str = ""


@dataclass(frozen=True)
class RepoAccessStatus:
    accessible: bool
    gated: bool
    detail: str = ""


def _tts_python() -> Path | None:
    """The env-tts interpreter this module's worker subprocess needs --
    canonical name only (`EnvironmentId.TTS`, i.e. `.envs/env-tts`), not
    the ad-hoc `env-tts-windows-gpu` name `pipeline.indicf5_generation`
    also falls back to. The installer provisions the canonical name
    (see docs/INDICF5_INSTALLER.md); HF auth is installer-only code, so
    it targets exactly what the installer itself builds."""
    paths = default_environment_root(EnvironmentId.TTS, base=PROJECT_ROOT)
    return paths.python if paths.exists() else None


def _run_worker(request: dict, *, timeout: float = _WORKER_TIMEOUT_SECONDS) -> dict:
    python_path = _tts_python()
    if python_path is None or not safe_path_is_file(python_path):
        raise HFAuthError(
            "env-tts is not built yet -- HuggingFace authentication requires it "
            "(see docs/INDICF5_INSTALLER.md's provisioning step)."
        )

    with tempfile.TemporaryDirectory(prefix="hf-auth-") as scratch:
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
            raise HFAuthError(f"HuggingFace auth worker timed out after {timeout}s") from exc

        if not response_path.is_file():
            # stderr is included for diagnostics; the worker never writes
            # a token value to stderr (only exception type names, per its
            # own docstring), so this cannot leak a credential.
            raise HFAuthError(
                f"auth worker exited {result.returncode} with no response file -- stderr: {result.stderr[-2000:]}"
            )
        response = json.loads(response_path.read_text(encoding="utf-8"))
        if not response.get("ok"):
            raise HFAuthError(response.get("error", "unknown auth worker failure"))
        return response


def check_existing_login() -> HFAuthStatus:
    """Real, current state -- calls the worker; never assumes based on
    whether a token was ever entered in this process."""
    response = _run_worker({"mode": "check"})
    return HFAuthStatus(
        authenticated=bool(response.get("authenticated")),
        username=response.get("username"),
        can_read_gated_repos=response.get("can_read_gated_repos"),
        detail=response.get("detail", ""),
    )


def login_with_token(token: str) -> HFAuthStatus:
    """Validate and persist a token. The caller (e.g. an interactive CLI
    prompt) is responsible for how `token` was obtained; this function
    itself never prints, logs, or stores it anywhere outside
    huggingface_hub's own credential cache (inside the worker)."""
    response = _run_worker({"mode": "login", "token": token})
    return HFAuthStatus(authenticated=bool(response.get("authenticated")), username=response.get("username"))


def prompt_and_login_interactive(*, prompt: str = "HuggingFace access token (input hidden): ") -> HFAuthStatus:
    """Masked terminal input via `getpass` -- no echo, and the value never
    passes through a shell history, a log call, or a print statement
    anywhere in this process."""
    token = getpass(prompt)
    return login_with_token(token)


def check_repo_access(repo_id: str) -> RepoAccessStatus:
    """Whether `repo_id` is public or gated, using only metadata (no
    download). A public repo reports `accessible=True`. A gated repo
    always reports `accessible=False`, `gated=True`, even if the current
    credential is actually approved for it: HuggingFace serves a gated
    repo's metadata to any caller regardless of approval, so metadata
    alone cannot confirm this account's access -- only a real download
    attempt can (see `pipeline.indicf5_provisioning`, which performs
    exactly that and classifies `GatedRepoError` correctly). Use this
    function to detect "this repo is gated at all", not "am I approved
    for it"."""
    response = _run_worker({"mode": "check_repo_access", "repo_id": repo_id})
    return RepoAccessStatus(
        accessible=bool(response.get("accessible")),
        gated=bool(response.get("gated")),
        detail=response.get("detail", ""),
    )
