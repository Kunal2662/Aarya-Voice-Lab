#!/usr/bin/env python3
"""Runs INSIDE the isolated `.envs/env-tts` interpreter. Never imported by
the base interpreter, and never imports anything from `aarya_voice_lab` --
the same filesystem/subprocess-contract boundary
`identity.embeddings.EmbeddingProvider`'s docstring describes, applied to
HuggingFace authentication. `huggingface_hub` is a lightweight network
client, but it is still not a base-interpreter dependency
(`requirements/base.txt`'s own header: "Nothing here pulls in... a
network client") -- this worker is how the base interpreter's installer
code reaches it, mirroring `nemo_embedding_worker.py`'s one-shot
request/response-file pattern exactly (this is a quick, infrequent check,
not a reusable resource worth keeping a persistent process alive for,
unlike `indicf5_generation_worker.py`).

**The token itself never appears in this file's own output.** Every
response reports only non-secret facts about the token (whether it is
valid, whose account it belongs to, what it can access) -- never the
token value, a hash of it, or any substring of it.

Request JSON:
    {"mode": "check"} -- report whether a HuggingFace login is already
        cached (from a previous `huggingface-cli login`/`login()` call,
        by this worker or anything else), without requiring a new token.
    {"mode": "login", "token": "<token>"} -- validate the given token via
        a safe, read-only authenticated call (whoami), and if valid,
        persist it via huggingface_hub's own credential storage
        (~/.cache/huggingface/token) -- never into this repository, never
        into an environment variable, never logged.
    {"mode": "check_repo_access", "repo_id": "<repo>"} -- using whatever
        credential is currently active (if any), report whether that
        specific repo is reachable -- distinguishes "no credential" from
        "credential present but this repo's gate was not accepted" from
        "repo is public, no credential needed at all".

Response JSON (always exactly one, even on failure):
    {"ok": true, ...mode-specific fields}
    {"ok": false, "error": "<message>"}  -- the message never contains a
        token value; huggingface_hub's own exceptions do not include it
        either (confirmed: they report the endpoint and status only).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _run_check() -> dict:
    from huggingface_hub import get_token, whoami
    from huggingface_hub.utils import HfHubHTTPError

    # Fast, local, no-network check first: is a token even present? This
    # lets a genuine "never logged in" report as authenticated=False
    # immediately, without needing the network, and without ever being
    # confused with a network failure below.
    if get_token() is None:
        return {"ok": True, "authenticated": False, "detail": "no token cached locally"}

    # A token IS present locally -- confirm it is actually valid via a
    # real network call. Distinguish an HTTP 401 (the token itself is
    # invalid/expired/revoked -- a genuine "not authenticated") from a
    # connection failure (this project's own development network has
    # been repeatedly unreliable) -- the latter must never be reported
    # as "not authenticated", since a cached token that is actually fine
    # would otherwise be misreported.
    try:
        info = whoami()
    except HfHubHTTPError as exc:
        status = getattr(exc.response, "status_code", None) if exc.response is not None else None
        if status == 401:
            return {
                "ok": True,
                "authenticated": False,
                "detail": "cached token was rejected (401) -- invalid or expired",
            }
        return {"ok": False, "error": f"HTTP error validating cached token (status={status}): {type(exc).__name__}"}
    except Exception as exc:  # noqa: BLE001 -- a connection failure is not "not authenticated"; report it as a real error
        return {"ok": False, "error": f"could not reach HuggingFace to validate the cached token: {type(exc).__name__}"}

    auth = info.get("auth", {}) if isinstance(info, dict) else {}
    access_token = auth.get("accessToken", {}) if isinstance(auth, dict) else {}
    fine_grained = access_token.get("fineGrained", {}) if isinstance(access_token, dict) else {}
    return {
        "ok": True,
        "authenticated": True,
        "username": info.get("name"),
        "can_read_gated_repos": bool(fine_grained.get("canReadGatedRepos")),
    }


def _run_login(token: str) -> dict:
    from huggingface_hub import HfApi, login

    if not token or not token.strip():
        return {"ok": False, "error": "token is empty"}

    # Validate FIRST, via a safe read-only call, before persisting anything.
    try:
        info = HfApi(token=token).whoami()
    except Exception as exc:  # noqa: BLE001 -- an invalid/expired token is a normal outcome, report it, don't crash
        return {"ok": False, "error": f"token validation failed ({type(exc).__name__})"}

    # Only huggingface_hub's own credential store is touched -- never a
    # file in this repository, never an environment variable.
    login(token=token, add_to_git_credential=False)

    return {"ok": True, "authenticated": True, "username": info.get("name")}


def _run_check_repo_access(repo_id: str) -> dict:
    from huggingface_hub import HfApi
    from huggingface_hub.utils import GatedRepoError, RepositoryNotFoundError

    if not repo_id:
        return {"ok": False, "error": "repo_id is required"}

    api = HfApi()
    try:
        info = api.model_info(repo_id)
    except GatedRepoError:
        # Kept for defense-in-depth, but empirically model_info() does not
        # raise this for a gated repo (see the `gated` field handling
        # below, which is the real signal this function relies on).
        return {
            "ok": True,
            "accessible": False,
            "gated": True,
            "detail": "repo is gated and the current credential (if any) does not have access approved",
        }
    except RepositoryNotFoundError:
        return {"ok": False, "error": f"repository not found: {repo_id}"}
    except Exception as exc:  # noqa: BLE001 -- always report via the response, never a bare traceback
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # Confirmed empirically (see docs/INDICF5_INSTALLER.md): HuggingFace
    # serves a gated repo's metadata via model_info() to ANY caller,
    # approved or not, anonymous or not -- info.gated only says the repo
    # IS gated, never whether this account's request was approved. Only
    # an actual file download (GatedRepoError from hf_hub_download, which
    # is what indicf5_provisioning_worker.py's real download path already
    # checks) can prove approval. So a gated repo is always reported as
    # not accessible here -- conservative, not a guess -- with a detail
    # explaining why, rather than silently claiming a download would
    # succeed.
    gated = bool(getattr(info, "gated", False))
    if not gated:
        return {"ok": True, "accessible": True, "gated": False}
    return {
        "ok": True,
        "accessible": False,
        "gated": True,
        "detail": (
            "repo is gated (model_info() reports metadata to any caller regardless of approval, so this "
            "cannot by itself confirm accessibility -- a real download attempt is the only authoritative check)"
        ),
    }


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: hf_auth_worker.py <request.json> <response.json>", file=sys.stderr)
        return 2

    request_path, response_path = Path(sys.argv[1]), Path(sys.argv[2])
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        mode = request.get("mode")
        if mode == "check":
            response = _run_check()
        elif mode == "login":
            response = _run_login(request.get("token", ""))
        elif mode == "check_repo_access":
            response = _run_check_repo_access(request.get("repo_id", ""))
        else:
            response = {"ok": False, "error": f"unknown mode: {mode!r}"}
    except Exception as exc:  # noqa: BLE001 -- always report failure via the response file, never a bare traceback
        response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    response_path.write_text(json.dumps(response), encoding="utf-8")
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
