#!/usr/bin/env python3
"""Reproducible regression reference for IndicF5 generation. Run under
`.envs/env-tts-windows-gpu` (or any interpreter with the same
dependencies as `requirements/tts.txt`'s IndicF5 candidate).

This is the acceptance baseline for "does IndicF5 generation actually
work": `test_indicf5_direct.py` proved *checkpoint loading* works against
the installed PyPI `f5-tts` package, but real generation through that
package produces unintelligible audio (confirmed by direct listening,
multiple hyperparameter sweeps, and an objective mel/vocoder round-trip
check that ruled out the vocoder). Diffing IndicF5's own bundled
`f5_tts` source (shipped inside its HuggingFace repo, and confirmed via
its GitHub `setup.py` to be what `pip install
git+https://github.com/ai4bharat/IndicF5.git` actually installs) against
the installed PyPI `f5-tts` found real, active-by-default behavioral
differences -- e.g. `DiT.text_mask_padding=True`, added to the PyPI
package after this checkpoint existed. Running the checkpoint through
IndicF5's own bundled source, unmodified, produced clearly intelligible
speech. That bundled source is vendored at
`scripts/ml_workers/vendor/indicf5_f5tts/` (see that package's module
docstrings for exact provenance and the two categories of edit made:
import renaming so it doesn't collide with the installed PyPI package,
and a `jieba` -> `rjieba` swap since only `rjieba` is installed).

This script exercises that vendored package exactly the way
`pipeline.indicf5_generation`'s production worker does (same DiT config,
same checkpoint-key normalization, same vocoder, same reference audio),
producing real WAV files a human can listen to. It does not assert
intelligibility -- no automated check can -- it asserts the mechanical
things code CAN verify (strict load succeeds, real non-silent audio is
produced) and prints exactly what to listen to.
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = REPO_ROOT / "scripts" / "ml_workers" / "vendor"
sys.path.insert(0, str(VENDOR_DIR))

import numpy as np
import soundfile as sf
import torch
from huggingface_hub import hf_hub_download
from safetensors.torch import load_file

from indicf5_f5tts.model.backbones.dit import DiT
from indicf5_f5tts.model.cfm import CFM
from indicf5_f5tts.model.utils import get_tokenizer
import indicf5_f5tts.infer.utils_infer as infer_defaults
from indicf5_f5tts.infer.utils_infer import infer_process, load_vocoder, preprocess_ref_audio_text

REPO_ID = "ai4bharat/IndicF5"
#: Verbatim from ai4bharat/IndicF5's own model.py -- confirmed correct by
#: a strict (all-keys-matched) load against the real checkpoint.
MODEL_CFG = dict(dim=1024, depth=22, heads=16, ff_mult=2, text_dim=512, conv_layers=4)
TRANSFORMER_KEY_PREFIX = "ema_model._orig_mod."
EMA_EXCLUDED_KEYS = {"initted", "step"}

#: The model card's own documented usage example -- known-correct
#: reference audio/text pairing.
DEFAULT_REF_AUDIO_FILENAME = "prompts/PAN_F_HAPPY_00001.wav"
DEFAULT_REF_TEXT = (
    "ਭਹੰਪੀ ਵਿੱਚ ਸਮਾਰਕਾਂ ਦੇ ਭਵਨ ਨਿਰਮਾਣ ਕਲਾ ਦੇ ਵੇਰਵੇ ਗੁੰਝਲਦਾਰ ਅਤੇ ਹੈਰਾਨ ਕਰਨ ਵਾਲੇ ਹਨ, "
    "ਜੋ ਮੈਨੂੰ ਖੁਸ਼ ਕਰਦੇ  ਹਨ।"
)

TEST_CASES = [
    ("full_example", "नमस्ते! संगीत की तरह जीवन भी खूबसूरत होता है, बस इसे सही ताल में जीना आना चाहिए."),
    ("short_hindi", "नमस्ते, आज मौसम अच्छा है."),
    ("short_punjabi_same_script", "ਸਤ ਸ੍ਰੀ ਅਕਾਲ, ਅੱਜ ਮੌਸਮ ਬਹੁਤ ਵਧੀਆ ਹੈ।"),
]


def _patch_torchaudio_load_with_soundfile() -> None:
    """torchaudio 2.11.0's default torchcodec backend fails to load its
    DLLs on this machine (confirmed OSError, unrelated to the checkpoint
    issue this script exists to regression-test). Scoped to this
    process only."""
    import torchaudio

    def _load_via_soundfile(path, *args, **kwargs):
        data, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
        return torch.from_numpy(data.T).contiguous(), sample_rate

    torchaudio.load = _load_via_soundfile


def build_model(device: str) -> CFM:
    vocab_path = hf_hub_download(REPO_ID, filename="checkpoints/vocab.txt")
    ckpt_path = hf_hub_download(REPO_ID, filename="model.safetensors")

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
    result = model.load_state_dict(state_dict)
    print(f"load_state_dict: {result}")
    assert not result.missing_keys and not result.unexpected_keys, "checkpoint no longer loads cleanly"
    return model.eval()


def main() -> int:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")

    _patch_torchaudio_load_with_soundfile()

    model = build_model(device)
    vocoder = load_vocoder(vocoder_name="vocos", is_local=False, device=device)

    ref_audio_path = hf_hub_download(REPO_ID, filename=DEFAULT_REF_AUDIO_FILENAME)
    output_dir = Path(__file__).resolve().parent.parent / "indicf5_bundled_reference_output"
    output_dir.mkdir(exist_ok=True)

    for label, gen_text in TEST_CASES:
        print(f"\n=== {label}: {gen_text!r} ===")
        ref_audio, resolved_ref_text = preprocess_ref_audio_text(ref_audio_path, DEFAULT_REF_TEXT)
        audio, sample_rate, _ = infer_process(
            ref_audio, resolved_ref_text, gen_text, model, vocoder, mel_spec_type="vocos", device=device
        )
        assert audio is not None and len(audio) > 0, f"{label}: no audio produced"
        peak = float(np.max(np.abs(audio)))
        assert peak > 0.01, f"{label}: output is effectively silent (peak={peak})"

        out_path = output_dir / f"{label}.wav"
        sf.write(str(out_path), audio, samplerate=sample_rate)
        print(
            f"  peak={peak:.4f} rms={float(np.sqrt(np.mean(audio**2))):.4f} "
            f"dur={len(audio) / sample_rate:.2f}s -> {out_path}"
        )

    print(f"\nAll cases produced real, non-silent audio in {output_dir}.")
    print("Mechanical checks only -- listen to the WAVs to confirm intelligibility.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
