import os
import sys

# The installed f5_tts library prints reference/generated text containing
# Devanagari/Gurmukhi script (e.g. preprocess_ref_audio_text's "ref_text"
# log line). Windows' default console codepage (cp1252) cannot encode those
# characters and raises UnicodeEncodeError on print(), so stdout/stderr are
# reconfigured to UTF-8 here -- this only affects this process's own streams,
# no installed package file is modified.
if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import torch
import soundfile as sf
from huggingface_hub import hf_hub_download
from safetensors.torch import load_file

from f5_tts.model import CFM, DiT
from f5_tts.model.utils import get_tokenizer
import f5_tts.infer.utils_infer as infer_defaults
from f5_tts.infer.utils_infer import (
    load_vocoder,
    infer_process,
    preprocess_ref_audio_text,
)

device = "cuda" if torch.cuda.is_available() else "cpu"
print("Device:", device)
if device == "cuda":
    print("GPU:", torch.cuda.get_device_name(0))

repo_id = "ai4bharat/IndicF5"

print("Getting vocab...")
vocab_path = hf_hub_download(
    repo_id,
    filename="checkpoints/vocab.txt"
)

print("Getting checkpoint...")
ckpt_path = hf_hub_download(
    repo_id,
    filename="model.safetensors"
)

print("Loading vocoder...")
vocoder = load_vocoder(
    vocoder_name="vocos",
    is_local=False,
    device=device
)

# f5_tts.infer.utils_infer.load_model() delegates to load_checkpoint(), whose
# EMA key handling only strips the "ema_model." prefix. This checkpoint's real
# parameter keys are "ema_model._orig_mod.<param>" -- the extra "_orig_mod."
# is left over from the original training run saving a torch.compile()-wrapped
# model's state dict. load_checkpoint() would call model.load_state_dict()
# with "_orig_mod."-prefixed keys still in place and raise (strict=True
# default) before this script could ever reach a manual-loading fallback, so
# load_model()/load_checkpoint() cannot be used for this checkpoint at all --
# the model must be built the same way load_model() builds it internally, and
# the state dict loaded here with the correct combined prefix stripped.
print("Building IndicF5...")
model_cfg = dict(dim=1024, depth=22, heads=16, ff_mult=2, text_dim=512, conv_layers=4)
vocab_char_map, vocab_size = get_tokenizer(vocab_path, "custom")
model = CFM(
    transformer=DiT(**model_cfg, text_num_embeds=vocab_size, mel_dim=infer_defaults.n_mel_channels),
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

print("Loading IndicF5 checkpoint...")
state_dict = load_file(ckpt_path, device=device)

TRANSFORMER_PREFIX = "ema_model._orig_mod."
state_dict = {
    k[len(TRANSFORMER_PREFIX):]: v
    for k, v in state_dict.items()
    if k.startswith(TRANSFORMER_PREFIX) and k[len(TRANSFORMER_PREFIX):] not in ("initted", "step")
}

model.load_state_dict(state_dict)
model.eval()

print("IndicF5 model loaded successfully!")

# torchaudio.load() defaults to the torchcodec backend in the installed
# torchaudio 2.11.0, whose native DLLs (libtorchcodec_core{4-9}.dll) fail to
# load on this machine (confirmed: OSError, FFmpeg shared-library packaging
# mismatch per torchcodec's own diagnostic). infer_process() calls
# torchaudio.load() on the reference audio, so it is replaced here with a
# drop-in soundfile-backed implementation, scoped to this process only -- no
# installed package file is modified.
import torchaudio


def _load_via_soundfile(path, *args, **kwargs):
    data, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    waveform = torch.from_numpy(data.T).contiguous()
    return waveform, sample_rate


torchaudio.load = _load_via_soundfile

print("Downloading reference prompt (official model card example)...")
ref_audio_path = hf_hub_download(repo_id, filename="prompts/PAN_F_HAPPY_00001.wav")
ref_text = "ਭਹੰਪੀ ਵਿੱਚ ਸਮਾਰਕਾਂ ਦੇ ਭਵਨ ਨਿਰਮਾਣ ਕਲਾ ਦੇ ਵੇਰਵੇ ਗੁੰਝਲਦਾਰ ਅਤੇ ਹੈਰਾਨ ਕਰਨ ਵਾਲੇ ਹਨ, ਜੋ ਮੈਨੂੰ ਖੁਸ਼ ਕਰਦੇ  ਹਨ।"
gen_text = "नमस्ते! संगीत की तरह जीवन भी खूबसूरत होता है, बस इसे सही ताल में जीना आना चाहिए."

print("Preprocessing reference audio...")
ref_audio, ref_text = preprocess_ref_audio_text(ref_audio_path, ref_text)

print("Running inference...")
audio, sample_rate, _ = infer_process(
    ref_audio,
    ref_text,
    gen_text,
    model,
    vocoder,
    mel_spec_type="vocos",
    device=device,
)

output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "indicf5_test_output.wav")
sf.write(output_path, audio, samplerate=sample_rate)
print(f"IndicF5 inference succeeded! Wrote {output_path}")
