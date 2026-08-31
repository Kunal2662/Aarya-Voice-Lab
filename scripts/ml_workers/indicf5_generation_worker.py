#!/usr/bin/env python3
"""Runs INSIDE the isolated `.envs/env-tts-windows-gpu` interpreter. Never
imported by the base interpreter, and never imports anything from
`aarya_voice_lab` -- the same filesystem/subprocess-contract boundary
`identity.embeddings.EmbeddingProvider`'s docstring describes, applied to
generation. `pipeline.indicf5_generation.IndicF5VoiceGenerator` (base
interpreter) launches this script as a long-lived subprocess and talks to
it over stdin/stdout using one JSON object per line in each direction --
unlike `nemo_embedding_worker.py` (one-shot: load, do one thing, exit),
this process stays alive and reuses its loaded model/vocoder across many
requests, so a caller pays the load cost once, not per generation.

Checkpoint compatibility (owned entirely by this file, never by the base
interpreter): `f5_tts.infer.utils_infer.load_model()`/`load_checkpoint()`
only strip an `ema_model.` prefix from checkpoint keys. The real
ai4bharat/IndicF5 checkpoint's transformer weights are stored under
`ema_model._orig_mod.<param>` (an extra `_orig_mod.` left by the original
training run checkpointing a `torch.compile()`-wrapped model), so
`load_model()` itself raises a missing/unexpected-key `RuntimeError`
before ever reaching this file if called on this checkpoint. This worker
never calls `load_model()`/`load_checkpoint()`: it builds the CFM/DiT
model directly, then loads the state dict here with the correct combined
prefix stripped. Verified: a strict `load_state_dict()` with this fix
reports "All keys matched successfully" (see `test_indicf5_direct.py`,
the original regression baseline this fix was first proven against).

That fixed *loading*, but real generation through the installed PyPI
`f5-tts` package (currently 1.1.22) produces unintelligible audio --
confirmed by direct listening, hyperparameter sweeps, and an objective
mel/vocoder round-trip check that ruled out the vocoder. IndicF5's
checkpoint was trained against an *older* F5-TTS than what's on PyPI
today; diffing IndicF5's own bundled source (shipped inside its
HuggingFace repo -- confirmed via its GitHub `setup.py` to be what
`pip install git+https://github.com/ai4bharat/IndicF5.git` actually
installs) against the installed package found real, active-by-default
differences (e.g. `DiT.text_mask_padding=True`, added to PyPI after this
checkpoint existed). Running the checkpoint through IndicF5's own bundled
source, unmodified, produced clearly intelligible speech. That source is
vendored at `scripts/ml_workers/vendor/indicf5_f5tts/` (see that
package's module docstrings for exact provenance) -- this worker imports
from there, not from the installed PyPI `f5_tts`. See
`scripts/indicf5_bundled_reference_test.py` for the standalone,
human-verified regression baseline this worker's construction/loading
code mirrors.

No `trust_remote_code=True` anywhere: the model is built directly from
vendored library code, and only tensor weights are read from the
checkpoint via `safetensors` (which cannot execute code) -- a different,
safer loading strategy than the `AutoModel(trust_remote_code=True)` path
`pipeline.generation.LocalNeuralVoiceGenerator`'s docstring describes as
unreviewed.

Request JSON (one per stdin line):
    {"mode": "load"} -- ensure the model+vocoder are loaded (idempotent;
        a no-op if already loaded this process). Real work happens once
        per process lifetime, not once per request.
    {"mode": "generate", "text": ..., "ref_text": ...,
     "ref_audio_path": "<abs path>"} OR
     {"repo_id": ..., "ref_audio_repo_filename": "<repo-relative path>"},
     "output_path": "<abs path>"} -- ensure loaded, run real inference,
        write a WAV to output_path.
    {"mode": "shutdown"} -- acknowledge and exit cleanly.

Response JSON (always exactly one per request, even on failure):
    {"ok": true, ...mode-specific fields}
    {"ok": false, "error": "<message>"}

stdout is reserved for this protocol only. The real stdout file
descriptor is captured before any import, and `sys.stdout` is then
pointed at `sys.stderr` for the rest of the process -- f5_tts/vocos/tqdm
all print progress/info text during loading and inference, and none of
it may reach the protocol stream.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
sys.path.insert(0, str(_VENDOR_DIR))

_PROTOCOL_STDOUT = sys.stdout
sys.stdout = sys.stderr

# Windows' default console codepage (cp1252) cannot encode the
# Devanagari/Gurmukhi text f5_tts itself prints (e.g.
# preprocess_ref_audio_text's "ref_text" log line) and raises
# UnicodeEncodeError on a bare print() -- reconfigure to UTF-8 so a
# request containing Indic-script reference/generated text can never
# crash this worker. The protocol stream is unaffected: json.dumps()
# escapes non-ASCII by default, so _PROTOCOL_STDOUT never carries a raw
# multi-byte character regardless of this setting.
if sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")
if _PROTOCOL_STDOUT.encoding.lower() != "utf-8":
    _PROTOCOL_STDOUT.reconfigure(encoding="utf-8")

#: Verbatim from ai4bharat/IndicF5's own model.py -- the exact DiT config
#: this checkpoint was trained with, confirmed (not guessed) by a strict
#: load_state_dict() reporting a full key match. Never changed without
#: re-verifying against the checkpoint's real keys.
MODEL_CFG = dict(dim=1024, depth=22, heads=16, ff_mult=2, text_dim=512, conv_layers=4)
TRANSFORMER_KEY_PREFIX = "ema_model._orig_mod."
EMA_EXCLUDED_KEYS = {"initted", "step"}

#: Populated once, on the first "load" or "generate" request, and reused
#: for the rest of this process's life -- the reusable-instance lifecycle
#: IndicF5VoiceGenerator's persistent subprocess exists to provide.
_STATE: dict = {"model": None, "vocoder": None, "device": None}


def _write(obj: dict) -> None:
    _PROTOCOL_STDOUT.write(json.dumps(obj) + "\n")
    _PROTOCOL_STDOUT.flush()


def _reset_cuda_peak_memory(device: str) -> None:
    """Installer Phase A (VRAM capability tier): purely additive
    instrumentation, never changes what gets loaded/generated or how --
    only what gets *reported* about it. Only real work when device is
    "cuda"; a no-op on CPU."""
    if device != "cuda":
        return
    import torch

    torch.cuda.reset_peak_memory_stats()


def _cuda_peak_memory_mib(device: str) -> dict[str, float | None]:
    """Peak allocated/reserved VRAM since the most recent
    `_reset_cuda_peak_memory()` call, in MiB. `allocated` is what PyTorch
    tensors actually hold; `reserved` is what PyTorch's caching allocator
    holds from the driver (always >= allocated, and the more honest
    "how much VRAM would this actually need" figure since the allocator
    does not release memory back to the driver between calls). Both
    `None` on CPU -- there is no VRAM number to report."""
    if device != "cuda":
        return {"peak_allocated_mib": None, "peak_reserved_mib": None}
    import torch

    return {
        "peak_allocated_mib": round(torch.cuda.max_memory_allocated() / 1024**2, 1),
        "peak_reserved_mib": round(torch.cuda.max_memory_reserved() / 1024**2, 1),
    }


def _patch_torchaudio_load_with_soundfile() -> None:
    """torchaudio.load() defaults to the torchcodec backend in the
    installed torchaudio 2.11.0, whose native DLLs
    (libtorchcodec_core{4-9}.dll) fail to load on this machine (confirmed:
    OSError, an FFmpeg shared-library packaging mismatch per torchcodec's
    own diagnostic). infer_process() calls torchaudio.load() on the
    reference audio, so it is replaced here with a drop-in soundfile-
    backed implementation. This is inherently process-safe and never
    "globally alters the environment": it patches an attribute in this
    worker subprocess's own interpreter only, which exits after the
    caller is done with it -- no installed package file is modified, and
    nothing outside this process is affected."""
    import soundfile as sf
    import torch
    import torchaudio

    def _load_via_soundfile(path, *args, **kwargs):
        data, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
        waveform = torch.from_numpy(data.T).contiguous()
        return waveform, sample_rate

    torchaudio.load = _load_via_soundfile


def _ensure_loaded() -> dict:
    if _STATE["model"] is not None:
        return {"already_loaded": True, "device": _STATE["device"], "load_seconds": 0.0}

    import indicf5_f5tts.infer.utils_infer as infer_defaults
    import torch
    from huggingface_hub import hf_hub_download
    from indicf5_f5tts.infer.utils_infer import load_vocoder
    from indicf5_f5tts.model.backbones.dit import DiT
    from indicf5_f5tts.model.cfm import CFM
    from indicf5_f5tts.model.utils import get_tokenizer
    from safetensors.torch import load_file

    _patch_torchaudio_load_with_soundfile()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    _reset_cuda_peak_memory(device)
    started = time.monotonic()

    vocab_path = hf_hub_download("ai4bharat/IndicF5", filename="checkpoints/vocab.txt")
    ckpt_path = hf_hub_download("ai4bharat/IndicF5", filename="model.safetensors")

    vocab_char_map, vocab_size = get_tokenizer(vocab_path, "custom")
    model = CFM(
        transformer=DiT(**MODEL_CFG, text_num_embeds=vocab_size, mel_dim=infer_defaults.n_mel_channels),
        mel_spec_kwargs=dict(
            n_fft=infer_defaults.n_fft,
            hop_length=infer_defaults.hop_length,
            win_length=infer_defaults.win_length,
            n_mel_channels=infer_defaults.n_mel_channels,
            target_sample_rate=infer_defaults.target_sample_rate,
            mel_spec_type=infer_defaults.mel_spec_type,
        ),
        odeint_kwargs=dict(method=infer_defaults.ode_method),
        vocab_char_map=vocab_char_map,
    ).to(device)

    state_dict = load_file(ckpt_path, device=device)
    state_dict = {
        k[len(TRANSFORMER_KEY_PREFIX) :]: v
        for k, v in state_dict.items()
        if k.startswith(TRANSFORMER_KEY_PREFIX) and k[len(TRANSFORMER_KEY_PREFIX) :] not in EMA_EXCLUDED_KEYS
    }
    # Fail loudly (strict=True default) on any mismatch rather than
    # silently continuing with a partially-loaded model.
    model.load_state_dict(state_dict)
    model.eval()

    vocoder = load_vocoder(vocoder_name="vocos", is_local=False, device=device)

    load_seconds = time.monotonic() - started
    memory = _cuda_peak_memory_mib(device)
    _STATE["model"] = model
    _STATE["vocoder"] = vocoder
    _STATE["device"] = device
    return {"already_loaded": False, "device": device, "load_seconds": round(load_seconds, 3), **memory}


def _run_load() -> dict:
    return {"ok": True, **_ensure_loaded()}


def _resolve_ref_audio_path(request: dict) -> str | None:
    if "ref_audio_path" in request:
        return request["ref_audio_path"]
    if "ref_audio_repo_filename" in request:
        from huggingface_hub import hf_hub_download

        repo_id = request.get("repo_id", "ai4bharat/IndicF5")
        return hf_hub_download(repo_id, filename=request["ref_audio_repo_filename"])
    return None


def _run_generate(request: dict) -> dict:
    import soundfile as sf
    from indicf5_f5tts.infer.utils_infer import infer_process, preprocess_ref_audio_text

    text = request.get("text")
    ref_text = request.get("ref_text")
    output_path_str = request.get("output_path")
    if not text or not ref_text or not output_path_str:
        return {"ok": False, "error": "generate request requires text, ref_text, and output_path"}

    ref_audio_path = _resolve_ref_audio_path(request)
    if ref_audio_path is None:
        return {"ok": False, "error": "generate request requires ref_audio_path or ref_audio_repo_filename"}
    if not Path(ref_audio_path).is_file():
        return {"ok": False, "error": f"reference audio does not exist: {ref_audio_path}"}

    load_info = _ensure_loaded()
    model = _STATE["model"]
    vocoder = _STATE["vocoder"]
    device = _STATE["device"]

    # Reset AFTER load (which may have happened in an earlier request, or
    # just now) so this measures generation's own peak in isolation, not
    # load's peak plus generation's incremental peak.
    _reset_cuda_peak_memory(device)
    started = time.monotonic()
    ref_audio, resolved_ref_text = preprocess_ref_audio_text(ref_audio_path, ref_text)
    audio, sample_rate, _spectrogram = infer_process(
        ref_audio,
        resolved_ref_text,
        text,
        model,
        vocoder,
        mel_spec_type="vocos",
        device=device,
    )
    generation_seconds = time.monotonic() - started
    memory = _cuda_peak_memory_mib(device)

    if audio is None:
        return {"ok": False, "error": "inference produced no audio (no text batches)"}

    output_path = Path(output_path_str)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_path), audio, samplerate=sample_rate)

    return {
        "ok": True,
        "output_path": str(output_path),
        "sample_rate": sample_rate,
        "duration_seconds": round(len(audio) / sample_rate, 6),
        "generation_seconds": round(generation_seconds, 3),
        "model_load_seconds": load_info.get("load_seconds"),
        "device": device,
        **memory,
    }


def main() -> int:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            mode = request.get("mode")
            if mode == "load":
                response = _run_load()
            elif mode == "generate":
                response = _run_generate(request)
            elif mode == "shutdown":
                _write({"ok": True})
                return 0
            else:
                response = {"ok": False, "error": f"unknown mode: {mode!r}"}
        except Exception as exc:  # noqa: BLE001 -- always report failure via the response line, never a
            # bare traceback the caller must parse
            response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        _write(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
