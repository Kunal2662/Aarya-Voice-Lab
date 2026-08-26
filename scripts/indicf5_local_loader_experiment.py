#!/usr/bin/env python3
"""EXPERIMENTAL, investigation-only script. Loads the real, official,
already-downloaded `ai4bharat/IndicF5` checkpoint directly, bypassing the
published `model.py`'s broken `AutoModel`/`trust_remote_code` path (see
`docs/REAL_ML_RUNTIME_INTEGRATION.md`'s "model's own published code is
broken" finding: `INF5Model.__init__` calls
`f5_tts.infer.utils_infer.load_model()` without its required `ckpt_path`
argument, and the safetensors-loading code three lines below is
commented out -- the official code path never actually loads real
weights, confirmed empirically with two different `transformers`
versions).

This script does NOT modify the downloaded `model.py`, does NOT touch
`LocalNeuralVoiceGenerator`, and never sets `trust_remote_code=True` --
it constructs the DiT/CFM architecture directly via `f5_tts`'s own
already-installed library code (`f5_tts.model.cfm.CFM`,
`f5_tts.model.DiT`, `f5_tts.model.utils.get_tokenizer`), using the exact
architecture configuration `model.py` itself passes to `load_model()`
(`dim=1024, depth=22, heads=16, ff_mult=2, text_dim=512, conv_layers=4`)
and the exact module-level mel/audio constants
`f5_tts.infer.utils_infer` itself uses (`n_mel_channels=100`,
`hop_length=256`, `win_length=1024`, `n_fft=1024`,
`target_sample_rate=24000`, `ode_method="euler"`) -- nothing here is
guessed.

## Why not just call `f5_tts.infer.utils_infer.load_checkpoint()` as-is

That function's own EMA-checkpoint handling
(`k.replace("ema_model.", "")` for every key) assumes the checkpoint's
real parameter keys are `ema_model.<param>`. This checkpoint's real keys
are `ema_model._orig_mod.<param>` -- an extra `_orig_mod.` layer left
over from the original training run saving a `torch.compile()`-wrapped
model's state dict. `load_checkpoint()`'s own replace call leaves that
prefix in place, which would not match the (uncompiled) target model's
real parameter names. This script strips the *combined* prefix
`ema_model._orig_mod.` instead -- the one concrete difference from the
upstream function, isolated to key-name handling only, changing nothing
about the architecture or the values themselves.

## Why the vocoder is downloaded, not loaded from this checkpoint's own bundled vocoder.* keys

Inspection (`safe_open` header read) found this exact safetensors file
also bundles `vocoder._orig_mod.*` keys (a Vocos-architecture vocoder).
Whether these are the vocoder the model was actually meant to ship with,
or simply a leftover training-time snapshot, is not established by
anything in the model card, `model.py`, or the checkpoint itself -- and
the official `model.py` unconditionally calls
`load_vocoder(vocoder_name="vocos", is_local=False, ...)`, which
downloads the public `charactr/vocos-mel-24khz` checkpoint instead of
ever reading this file's `vocoder.*` keys. Per this investigation's own
"do not silently discard weights unless their purpose is positively
established" rule, the safer, most official-config-faithful choice is
to use the same public vocoder the author's own code path uses, and
leave the bundled `vocoder.*` keys unused and unexplained rather than
guessing they are the intended deployment vocoder.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch
from safetensors.torch import load_file

INDICF5_SNAPSHOT = Path(
    r"C:\Users\DELL-5430\.cache\huggingface\hub\models--ai4bharat--IndicF5"
    r"\snapshots\ba85abedf18dc479a447eaa0eccbd76ab78a47d5"
)
CHECKPOINT_PATH = INDICF5_SNAPSHOT / "model.safetensors"
VOCAB_PATH = INDICF5_SNAPSHOT / "checkpoints" / "vocab.txt"
CONFIG_PATH = INDICF5_SNAPSHOT / "config.json"

# Verbatim from ai4bharat/IndicF5's model.py -- the exact call this
# investigation is working around, not a guess.
MODEL_CFG = dict(dim=1024, depth=22, heads=16, ff_mult=2, text_dim=512, conv_layers=4)

TRANSFORMER_KEY_PREFIX = "ema_model._orig_mod."
VOCODER_KEY_PREFIX = "vocoder._orig_mod."
EMA_EXCLUDED_KEYS = {"initted", "step"}


def inspect_checkpoint() -> dict:
    """Read-only key/shape/prefix summary -- Phase 3 of the investigation."""
    from safetensors import safe_open

    with safe_open(str(CHECKPOINT_PATH), framework="pt") as f:
        keys = list(f.keys())
        prefixes: dict[str, int] = {}
        for k in keys:
            top = k.split(".", 1)[0]
            prefixes[top] = prefixes.get(top, 0) + 1
        return {
            "total_keys": len(keys),
            "top_level_prefixes": prefixes,
            "checkpoint_size_bytes": CHECKPOINT_PATH.stat().st_size,
        }


def build_transformer_state_dict(all_weights: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
    """Strip the combined `ema_model._orig_mod.` prefix -- the one
    concrete fix over `f5_tts.infer.utils_infer.load_checkpoint()`,
    which only strips `ema_model.` and would leave `_orig_mod.` in
    place. Excludes `initted`/`step`, matching that function's own
    exclusion list exactly."""
    result = {}
    for key, value in all_weights.items():
        if not key.startswith(TRANSFORMER_KEY_PREFIX):
            continue
        stripped = key[len(TRANSFORMER_KEY_PREFIX) :]
        if stripped in EMA_EXCLUDED_KEYS:
            continue
        result[stripped] = value
    return result


def load_indicf5_transformer(device: str = "cpu"):
    """Construct the real CFM/DiT model exactly as
    `f5_tts.infer.utils_infer.load_model()` does internally, then load
    this checkpoint's real EMA weights with the corrected key mapping --
    never calling the upstream `load_checkpoint()` (which does not
    handle this checkpoint's extra `_orig_mod.` prefix) and never
    setting `trust_remote_code=True`."""
    import f5_tts.infer.utils_infer as infer_defaults
    from f5_tts.model import CFM, DiT
    from f5_tts.model.utils import get_tokenizer

    vocab_char_map, vocab_size = get_tokenizer(str(VOCAB_PATH), "custom")

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

    all_weights = load_file(str(CHECKPOINT_PATH), device=device)
    transformer_state_dict = build_transformer_state_dict(all_weights)

    # Fail loudly on a mismatch -- strict=True is the default; this call
    # raises RuntimeError naming every missing/unexpected key if the
    # architecture and checkpoint disagree, rather than silently
    # continuing with a partially-loaded model.
    model.load_state_dict(transformer_state_dict)
    return model.eval()


def load_official_vocoder(device: str = "cpu"):
    """Same call the official model.py makes -- the public
    charactr/vocos-mel-24khz vocoder, not this checkpoint's own bundled
    vocoder.* keys (see module docstring for why)."""
    from f5_tts.infer.utils_infer import load_vocoder

    return load_vocoder(vocoder_name="vocos", is_local=False, device=device)


def _patch_torchaudio_load_with_soundfile() -> None:
    """`torchaudio.load()` defaults to the `torchcodec` backend in the
    installed torchaudio 2.11.0, whose native DLLs
    (`libtorchcodec_core{4-9}.dll`) fail to load on this machine --
    confirmed by the real, captured `OSError`/`RuntimeError` this
    investigation hit (an FFmpeg shared-library packaging mismatch, per
    torchcodec's own diagnostic message). `soundfile` is already
    confirmed working throughout this project; this replaces
    `torchaudio.load` with a drop-in, same-shape ([channels, samples]
    tensor, sample_rate) implementation backed by it, scoped to this
    process only -- no installed package file is modified."""
    import soundfile as sf
    import torch
    import torchaudio

    def _load_via_soundfile(path, *args, **kwargs):
        data, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
        # soundfile gives (samples, channels); torchaudio.load's contract is (channels, samples).
        waveform = torch.from_numpy(data.T).contiguous()
        return waveform, sample_rate

    torchaudio.load = _load_via_soundfile


def generate_one_sample(text: str, ref_audio_path: Path, ref_text: str, output_path: Path, device: str = "cpu"):
    _patch_torchaudio_load_with_soundfile()
    import soundfile as sf
    from f5_tts.infer.utils_infer import infer_process, preprocess_ref_audio_text

    timings: dict[str, float] = {}

    t0 = time.monotonic()
    transformer = load_indicf5_transformer(device=device)
    timings["transformer_load_seconds"] = time.monotonic() - t0

    t0 = time.monotonic()
    vocoder = load_official_vocoder(device=device)
    timings["vocoder_load_seconds"] = time.monotonic() - t0

    t0 = time.monotonic()
    ref_audio, resolved_ref_text = preprocess_ref_audio_text(str(ref_audio_path), ref_text)
    timings["ref_audio_preprocess_seconds"] = time.monotonic() - t0

    t0 = time.monotonic()
    audio, final_sample_rate, _ = infer_process(
        ref_audio,
        resolved_ref_text,
        text,
        transformer,
        vocoder,
        mel_spec_type="vocos",
        speed=1.0,
        device=device,
    )
    timings["inference_seconds"] = time.monotonic() - t0

    sf.write(str(output_path), audio, samplerate=final_sample_rate)
    timings["total_seconds"] = sum(timings.values())
    return {
        "output_path": str(output_path),
        "sample_rate": final_sample_rate,
        "sample_count": len(audio),
        "duration_seconds": len(audio) / final_sample_rate,
        "timings": timings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect-only", action="store_true", help="Only run Phase 3 key inspection, no inference.")
    parser.add_argument("--text", default="संगीत की तरह जीवन भी खूबसूरत होता है.")
    parser.add_argument(
        "--ref-audio", type=Path, default=Path(".envs/experiments-scratch/ref_prompt.wav"),
    )
    parser.add_argument(
        "--ref-text",
        default="ਭਹੰਪੀ ਵਿੱਚ ਸਮਾਰਕਾਂ ਦੇ ਭਵਨ ਨਿਰਮਾਣ ਕਲਾ ਦੇ ਵੇਰਵੇ ਗੁੰਝਲਦਾਰ ਅਤੇ ਹੈਰਾਨ ਕਰਨ ਵਾਲੇ ਹਨ, ਜੋ ਮੈਨੂੰ ਖੁਸ਼ ਕਰਦੇ  ਹਨ।",
        help="Verbatim from the official model card's own documented usage example.",
    )
    parser.add_argument("--output", type=Path, default=Path(".envs/experiments-scratch/indicf5_local_sample.wav"))
    args = parser.parse_args()

    if args.inspect_only:
        print(json.dumps(inspect_checkpoint(), indent=2))
        return 0

    result = generate_one_sample(args.text, args.ref_audio, args.ref_text, args.output, device="cpu")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
