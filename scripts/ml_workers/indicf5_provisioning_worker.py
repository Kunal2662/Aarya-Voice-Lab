#!/usr/bin/env python3
"""Runs INSIDE the isolated `.envs/env-tts` interpreter. Never imported by
the base interpreter, and never imports anything from `aarya_voice_lab` --
the same filesystem/subprocess-contract boundary
`identity.embeddings.EmbeddingProvider`'s docstring describes, applied to
IndicF5 model provisioning.

Deliberately a SEPARATE file from `indicf5_generation_worker.py`: this
worker downloads and verifies files, `indicf5_generation_worker.py` loads
and generates with them -- the verified inference runtime is not touched
by anything in this file (Phase D's own "do not modify the verified
IndicF5 runtime" requirement, satisfied structurally, not by discipline
alone). Both workers agree on the same repo id / filenames / DiT
config by importing nothing from each other and instead having the base
interpreter's `pipeline.indicf5_generation` module be the single source
of truth those constants are read from (see that module's DEFAULT_REPO_ID
etc.) -- this file receives them via the request JSON instead of
hardcoding a second copy.

Every file this worker touches is exactly what `indicf5_generation_
worker.py`'s own `_ensure_loaded()` downloads: IndicF5's own vocab,
checkpoint, and default reference audio (gated, from `ai4bharat/
IndicF5`), plus the public `charactr/vocos-mel-24khz` vocoder's config
and weights that `load_vocoder()` fetches. No other file from either
repo is downloaded -- specifically not IndicF5's own bundled `f5_tts`
source tree also hosted in that repo, which this project already
vendors separately (`scripts/ml_workers/vendor/indicf5_f5tts/`).

Request JSON:
    {"mode": "provision", "repo_id": ..., "vocab_filename": ...,
     "checkpoint_filename": ..., "ref_audio_filename": ...,
     "vocoder_repo_id": ..., "vocoder_config_filename": ...,
     "vocoder_weights_filename": ...}
        -- ensure every required file is present in the HuggingFace
        cache (huggingface_hub's own cache mechanism: already-cached
        files are reused, never re-downloaded), then verify each one
        structurally. Every field has a hardcoded fallback matching the
        verified runtime's own defaults, so a minimal {"mode":
        "provision"} request still does the right thing.
    {"mode": "verify", ...same fields...} -- the same structural
        verification only, without downloading -- fails if a required
        file is missing rather than fetching it.

Response JSON:
    {"ok": true, "files": [{"name": ..., "status": "already_cached" |
        "downloaded", "path": ..., "size_bytes": ..., "verified": true},
        ...]}
    {"ok": false, "error": "...", "failure_kind": "authentication" |
        "gated_access" | "network" | "disk" | "corruption" | "unknown",
        "files": [...partial progress before the failure...]}

Every failure is classified into exactly one of those five kinds, so the
caller can give an operator a precise, actionable message instead of a
generic "download failed". The failing file's name is always included;
no response ever includes a credential value.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# No stdin/stdout protocol here (unlike indicf5_generation_worker.py) --
# this worker uses request/response FILES, matching hf_auth_worker.py and
# nemo_embedding_worker.py's convention. Only stderr needs UTF-8 for the
# Windows-cp1252-vs-Devanagari reason those other workers already
# document; nothing here prints Indic-script text, but this keeps the
# per-file progress prints below safe regardless.
if sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")

DEFAULT_REPO_ID = "ai4bharat/IndicF5"
DEFAULT_VOCAB_FILENAME = "checkpoints/vocab.txt"
DEFAULT_CHECKPOINT_FILENAME = "model.safetensors"
DEFAULT_REF_AUDIO_FILENAME = "prompts/PAN_F_HAPPY_00001.wav"
DEFAULT_VOCODER_REPO_ID = "charactr/vocos-mel-24khz"
DEFAULT_VOCODER_CONFIG_FILENAME = "config.yaml"
DEFAULT_VOCODER_WEIGHTS_FILENAME = "pytorch_model.bin"

#: Real, measured minimums -- not guesses. model.safetensors is IndicF5's
#: full checkpoint (~1.4 GB per the project's own installer design
#: report); a file far smaller than this is definitely truncated/corrupt,
#: never a legitimate partial variant.
MIN_CHECKPOINT_BYTES = 1_000_000_000
MIN_VOCODER_WEIGHTS_BYTES = 10_000_000


class ProvisioningError(RuntimeError):
    def __init__(self, message: str, *, failure_kind: str) -> None:
        super().__init__(message)
        self.failure_kind = failure_kind


def _classify_and_raise(exc: Exception, *, context: str) -> None:
    """Turn a huggingface_hub/requests/OSError exception into a
    ProvisioningError carrying exactly one of the five failure kinds
    Phase D requires callers be able to distinguish. Order matters:
    requests.exceptions.ConnectionError (network) is itself an OSError
    subclass (via IOError), so it MUST be checked before the generic
    OSError catch below, or a network failure would be misreported as a
    disk failure."""
    from huggingface_hub.utils import GatedRepoError, LocalEntryNotFoundError

    if isinstance(exc, GatedRepoError):
        raise ProvisioningError(
            f"{context}: access not granted for the current HuggingFace account (the repo's gate has not "
            "been approved for it)",
            failure_kind="gated_access",
        ) from exc
    if isinstance(exc, LocalEntryNotFoundError):
        raise ProvisioningError(
            f"{context}: could not reach HuggingFace and no cached copy exists",
            failure_kind="network",
        ) from exc

    try:
        import requests

        if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
            raise ProvisioningError(f"{context}: network error ({type(exc).__name__})", failure_kind="network") from exc
    except ImportError:
        pass

    if isinstance(exc, OSError):
        raise ProvisioningError(f"{context}: disk error ({type(exc).__name__}): {exc}", failure_kind="disk") from exc

    raise ProvisioningError(f"{context}: {type(exc).__name__}: {exc}", failure_kind="unknown") from exc


def _download_one(repo_id: str, filename: str) -> dict:
    from huggingface_hub import get_token, hf_hub_download

    if get_token() is None:
        raise ProvisioningError(
            f"{repo_id}/{filename}: no HuggingFace token cached -- authentication is required for this repo",
            failure_kind="authentication",
        )

    from huggingface_hub.utils import LocalEntryNotFoundError

    # A prior successful download is already on disk; hf_hub_download's
    # own cache check makes this a no-op HEAD request (or fully offline
    # if local_files_only is honored), never a re-download.
    already_cached_before = False
    try:
        cached_path = hf_hub_download(repo_id, filename=filename, local_files_only=True)
        already_cached_before = True
    except LocalEntryNotFoundError:
        pass

    if already_cached_before:
        size = Path(cached_path).stat().st_size
        return {"path": cached_path, "status": "already_cached", "size_bytes": size}

    try:
        print(f"Downloading {repo_id}/{filename} ...", file=sys.stderr)
        path = hf_hub_download(repo_id, filename=filename)
    except Exception as exc:  # noqa: BLE001 -- classified and re-raised as ProvisioningError below
        _classify_and_raise(exc, context=f"{repo_id}/{filename}")
        raise  # unreachable; _classify_and_raise always raises

    size = Path(path).stat().st_size
    return {"path": path, "status": "downloaded", "size_bytes": size}


def _verify_vocab(path: str) -> None:
    text = Path(path).read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line]
    if len(lines) < 100:
        raise ProvisioningError(
            f"vocab.txt has only {len(lines)} lines -- expected a real tokenizer vocabulary (thousands); "
            "the cached file is likely truncated or corrupt",
            failure_kind="corruption",
        )


def _verify_checkpoint(path: str) -> None:
    size = Path(path).stat().st_size
    if size < MIN_CHECKPOINT_BYTES:
        raise ProvisioningError(
            f"model.safetensors is only {size} bytes -- expected >= {MIN_CHECKPOINT_BYTES} bytes; "
            "the cached file is truncated or corrupt",
            failure_kind="corruption",
        )
    try:
        from safetensors import safe_open

        with safe_open(path, framework="pt") as f:
            keys = list(f.keys())
    except Exception as exc:  # noqa: BLE001 -- a parse failure on a plausibly-sized file is corruption, not another category
        raise ProvisioningError(
            f"model.safetensors could not be parsed as a safetensors file ({type(exc).__name__}: {exc}) "
            "-- likely corrupt",
            failure_kind="corruption",
        ) from exc
    if not keys:
        raise ProvisioningError(
            "model.safetensors parsed but contains zero tensors -- corrupt", failure_kind="corruption"
        )


def _verify_reference_audio(path: str) -> None:
    try:
        import soundfile as sf

        info = sf.info(path)
    except Exception as exc:  # noqa: BLE001 -- a parse failure is corruption
        raise ProvisioningError(
            f"reference audio could not be read as a WAV file ({type(exc).__name__}: {exc}) -- likely corrupt",
            failure_kind="corruption",
        ) from exc
    if info.duration <= 0:
        raise ProvisioningError("reference audio has zero duration -- corrupt", failure_kind="corruption")


def _verify_vocoder_config(path: str) -> None:
    import yaml

    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as exc:  # noqa: BLE001 -- a parse failure is corruption
        raise ProvisioningError(
            f"vocoder config.yaml could not be parsed ({type(exc).__name__}: {exc}) -- likely corrupt",
            failure_kind="corruption",
        ) from exc
    if not isinstance(data, dict) or not data:
        raise ProvisioningError(
            "vocoder config.yaml parsed but is empty/not a mapping -- corrupt", failure_kind="corruption"
        )


def _verify_vocoder_weights(path: str) -> None:
    size = Path(path).stat().st_size
    if size < MIN_VOCODER_WEIGHTS_BYTES:
        raise ProvisioningError(
            f"vocoder pytorch_model.bin is only {size} bytes -- expected >= {MIN_VOCODER_WEIGHTS_BYTES} bytes; "
            "the cached file is truncated or corrupt",
            failure_kind="corruption",
        )
    try:
        import torch

        torch.load(path, map_location="cpu", weights_only=True)
    except Exception as exc:  # noqa: BLE001 -- a parse failure on a plausibly-sized file is corruption
        raise ProvisioningError(
            f"vocoder pytorch_model.bin could not be loaded ({type(exc).__name__}: {exc}) -- likely corrupt",
            failure_kind="corruption",
        ) from exc


_VERIFIERS = {
    "vocab": _verify_vocab,
    "checkpoint": _verify_checkpoint,
    "reference_audio": _verify_reference_audio,
    "vocoder_config": _verify_vocoder_config,
    "vocoder_weights": _verify_vocoder_weights,
}


def _required_files(request: dict) -> list[tuple[str, str, str]]:
    """Returns (logical_name, repo_id, filename) tuples, in a fixed,
    deterministic order -- smallest/cheapest-to-verify first, so a
    caller watching progress sees early signal quickly, and the large
    checkpoint download (the one most likely to hit real network trouble)
    is not the first thing attempted."""
    repo_id = request.get("repo_id", DEFAULT_REPO_ID)
    vocoder_repo_id = request.get("vocoder_repo_id", DEFAULT_VOCODER_REPO_ID)
    return [
        ("vocab", repo_id, request.get("vocab_filename", DEFAULT_VOCAB_FILENAME)),
        ("vocoder_config", vocoder_repo_id, request.get("vocoder_config_filename", DEFAULT_VOCODER_CONFIG_FILENAME)),
        ("reference_audio", repo_id, request.get("ref_audio_filename", DEFAULT_REF_AUDIO_FILENAME)),
        (
            "vocoder_weights",
            vocoder_repo_id,
            request.get("vocoder_weights_filename", DEFAULT_VOCODER_WEIGHTS_FILENAME),
        ),
        ("checkpoint", repo_id, request.get("checkpoint_filename", DEFAULT_CHECKPOINT_FILENAME)),
    ]


def _run_provision(request: dict) -> dict:
    files_report: list[dict] = []
    for logical_name, repo_id, filename in _required_files(request):
        try:
            result = _download_one(repo_id, filename)
            _VERIFIERS[logical_name](result["path"])
        except ProvisioningError as exc:
            files_report.append({"name": logical_name, "filename": filename, "ok": False, "error": str(exc)})
            return {"ok": False, "error": str(exc), "failure_kind": exc.failure_kind, "files": files_report}
        files_report.append({"name": logical_name, "filename": filename, "ok": True, "verified": True, **result})
    return {"ok": True, "files": files_report}


def _run_verify(request: dict) -> dict:
    from huggingface_hub import hf_hub_download
    from huggingface_hub.utils import LocalEntryNotFoundError

    files_report: list[dict] = []
    for logical_name, repo_id, filename in _required_files(request):
        try:
            path = hf_hub_download(repo_id, filename=filename, local_files_only=True)
        except LocalEntryNotFoundError:
            files_report.append(
                {"name": logical_name, "filename": filename, "ok": False, "error": "not present in local cache"}
            )
            return {
                "ok": False,
                "error": f"{repo_id}/{filename} is not present in the local cache -- run provisioning first",
                "failure_kind": "network",
                "files": files_report,
            }
        try:
            _VERIFIERS[logical_name](path)
        except ProvisioningError as exc:
            files_report.append({"name": logical_name, "filename": filename, "ok": False, "error": str(exc)})
            return {"ok": False, "error": str(exc), "failure_kind": exc.failure_kind, "files": files_report}
        files_report.append(
            {
                "name": logical_name,
                "filename": filename,
                "ok": True,
                "verified": True,
                "status": "already_cached",
                "path": path,
                "size_bytes": Path(path).stat().st_size,
            }
        )
    return {"ok": True, "files": files_report}


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: indicf5_provisioning_worker.py <request.json> <response.json>", file=sys.stderr)
        return 2

    request_path, response_path = Path(sys.argv[1]), Path(sys.argv[2])
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        mode = request.get("mode")
        if mode == "provision":
            response = _run_provision(request)
        elif mode == "verify":
            response = _run_verify(request)
        else:
            response = {"ok": False, "error": f"unknown mode: {mode!r}", "failure_kind": "unknown"}
    except Exception as exc:  # noqa: BLE001 -- always report failure via the response file, never a bare traceback
        response = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "failure_kind": "unknown"}

    response_path.write_text(json.dumps(response), encoding="utf-8")
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
