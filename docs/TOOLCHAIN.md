# Toolchain

> **Nothing below is installed.** Specifications and scripts exist
> (`scripts/install_env.sh`, `aarya-voice nemo-check`), but no ML package
> or model weight has been installed or downloaded.
>
> Constraints verified 2026-08-19 by **executed dependency resolutions** —
> see [COMPATIBILITY.md](COMPATIBILITY.md) for the measurements, including
> a correction to the original NeMo/WhisperX claim and a telemetry finding.

## Selection criteria

A tool must be:

1. **Runnable locally** — anything requiring audio upload is disqualified
   outright, regardless of quality.
2. **Appropriately licensed** — non-commercial and research-only licenses
   are a hard filter, not a footnote.
3. **Credential-free where possible** — gated models add a third-party
   account relationship to a privacy-critical project.
4. **Marathi-capable**, for the stages where language matters.
5. **Replaceable** — no tool should be load-bearing for the architecture.

## Provider abstraction

The project defines abstractions **where a real decision is deferred**,
not everywhere:

| Abstraction | Why it exists |
|---|---|
| `VoiceService` | The TTS model is genuinely undecided; Core needs a stable contract regardless |
| Segment manifest schema | The real integration seam between stages, across incompatible environments |
| `SpeakerVerificationInput` | Lets the safety policy accept results from any diarization system |

There is deliberately **no** `DiarizationProvider`/`ASRProvider` class
hierarchy. Those stages already integrate through manifest files on disk
and run in separate interpreters — an in-process interface for them would
be abstraction with nothing behind it.

## Audio

| Tool | Role | Notes |
|---|---|---|
| **FFmpeg** | Decode, resample, segment | System binary. Detected by `system-info`; not required in Phase 0 |
| `soundfile` | Reading/writing WAV | libsndfile binding |
| `librosa` | Analysis, quality metrics | Heavier; only where needed |

## Speaker diarization

**Primary: NVIDIA NeMo / Sortformer.**

| Model | Notes |
|---|---|
| `nvidia/diar_sortformer_4spk-v1` | Offline |
| `nvidia/diar_streaming_sortformer_4spk-v2.1` | Newest; NVIDIA Open Model License |

Chosen as primary because it is **not gated** — no HuggingFace token, no
account, no contact-sharing agreement. For a project defined by privacy,
a credential-free path is worth real effort to prefer. The 4-speaker
capacity comfortably covers 2-speaker material.

Package: `nemo-toolkit[asr]` 3.0.0 (not the `nemo-toolkit-asr`
pre-release). Apache-2.0. Environment `env-nemo`, torch 2.13.0.

**⚠ Telemetry:** the NeMo dependency tree includes `wandb`, `sentry-sdk`,
`nv-one-logger-training-telemetry`, OpenTelemetry OTLP exporters, and
`aistore`. None is needed for diarization; all are potential egress paths.
Disabled automatically for every stage subprocess and via
`scripts/disable_telemetry.sh` — details in [NEMO.md](NEMO.md).

## Transcription & alignment

**Candidate: WhisperX** — batched Whisper with word-level alignment;
BSD-2-Clause; Python 3.10–3.13.

Two things to weigh before adopting:

1. **It must not share an environment with NeMo.** Co-installing resolves
   but silently downgrades torch to 2.8.0 (below NeMo's tested matrix) —
   and with CUDA extras downgrades NeMo itself. Environment
   `env-whisperx`. See [COMPATIBILITY.md](COMPATIBILITY.md).
2. **Its diarization path requires credentials** — installing whisperx
   *always* pulls `pyannote-audio` 4.0.7 (gated model, contact-sharing
   agreement) and `pyannoteai-sdk` (a commercial API client). Confirmed
   by dependency resolution, not just documentation.

WhisperX for **transcription/alignment only** avoids most of concern (2).
Using pyannote as the independent verification system needs sign-off.
Audio is processed locally either way — the token gates the *download*,
not inference — but private audio must never be sent to a hosted
pyannoteAI endpoint.

Marathi ASR quality is materially below English. Expect manual correction.

## Dataset quality

**NeMo Curator** (Apache-2.0, Python 3.11–3.13, **GPU optional** — every
modality ships a `_cpu` extra). Environment C; install one modality extra
at a time per NVIDIA's guidance.

Simpler VAD and quality metrics (SNR, clipping, silence) may cover this
project's needs without Curator's Ray/RAPIDS/vLLM footprint — evaluate
before adopting.

## Voice generation

**No model has been selected.** Licensing eliminates several popular
options:

| Option | Weights license | Marathi | Cloning | Verdict |
|---|---|---|---|---|
| **AI4Bharat IndicF5** | **MIT** | **Yes** | **Yes** (ref audio) | **Leading candidate** |
| Indic Parler-TTS | Apache-2.0 | Yes (21 langs) | No | Default Voice candidate |
| Piper | per-voice | Yes (`mr_IN`) | No (finetune) | CPU baseline |
| Coqui XTTS-v2 | CPML **non-commercial** | **No** | Yes | **Rejected** |
| F5-TTS (base) | CC-BY-NC-4.0 | No (EN/ZH) | Yes | Rejected |
| Fish Speech | Research-only | No | Yes | **Rejected** |

**XTTS-v2 deserves a specific warning**: it is the most commonly
recommended open voice-cloning model, but its weights are non-commercial
CPML, **Coqui Inc. is defunct so no other terms can ever be granted**,
and it does not support Marathi (Hindi only). Reaching for it by default
would be a mistake.

**IndicF5** fits best — MIT weights, Marathi support, reference-audio
cloning suited to a small dataset. Two caveats: its HF repo is gated
(contact-info agreement, though the license itself is permissive), and it
loads with `trust_remote_code=True`, which **executes arbitrary code from
the model repo**. Review that code before running it anywhere near
private material.

## Explicitly excluded

**ElevenLabs, Google Cloud TTS, Azure TTS, Amazon Polly**, and equivalent
hosted services. They would require uploading the private recordings —
disqualifying, whatever the output quality. They must never become a
requirement, and must never be on the path for the Private Voice.
