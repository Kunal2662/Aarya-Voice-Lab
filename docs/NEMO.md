# NeMo Environment (`env-nemo`)

Primary speaker diarization. **Built, for a different purpose than
originally documented here.** The Real ML Runtime & Model Integration
milestone built this exact environment (`nemo-toolkit[asr]` 3.0.0, torch
2.13.0+cpu) and used it to load `titanet_large` — a real, working NeMo
*speaker-embedding* model — for `identity.embeddings.LocalNeuralEmbeddingProvider`.
See `docs/REAL_ML_RUNTIME_INTEGRATION.md` for that model decision, its
license, and measured performance.

Sortformer diarization (the model this file was originally written for)
has **not** been exercised — no Sortformer weights have been downloaded
and no diarization stage has run. The rest of this document describes
the diarization use case as originally planned; only the "built" claim
above has changed.

## Why NeMo is the primary system

`nvidia/diar_streaming_sortformer_4spk-v2.1` needs **no HuggingFace
token, no account, and no terms acceptance**. For a project defined by
keeping private material local, a credential-free path is worth
preferring even at some cost in convenience — the alternative
(pyannote via WhisperX) introduces a gated model and a third-party
account relationship. See [COMPATIBILITY.md](COMPATIBILITY.md).

Its 4-speaker capacity comfortably covers 2-speaker source material.

## Specification

| | |
|---|---|
| Python | 3.12 |
| torch | **2.13.0** |
| Package | `nemo-toolkit[asr]` 3.0.0 (Apache-2.0) |
| Requirements | `requirements/diarization.txt` |
| CPU fallback | Supported, slower |
| Credentials | **None** |

Use `nemo-toolkit[asr]`, **not** the `nemo-toolkit-asr` distribution —
the latter is a pre-release carrying exact pins (`fsspec==2024.12.0`)
that collide with the rest of the stack.

torch is pinned at 2.13.0 deliberately: co-installing with WhisperX
drags it down to 2.8.0, below NeMo's tested matrix. That is the entire
reason this environment is isolated.

## Building it

```bash
scripts/install_env.sh env-nemo --cpu      # or --cuda
```

The script installs torch **first** from the explicit CPU or CUDA wheel
index. Without that, pip resolves the default build and pulls roughly 15
`nvidia-*-cu12` packages (multiple GB) onto machines with no GPU.

Check the machine before choosing the accelerator:

```bash
aarya-voice env-audit
```

## Verifying it

```bash
aarya-voice nemo-check          # or --json
```

Reports Python, torch, NeMo, CUDA, GPU, CPU-fallback status, and model
availability. A version that differs from the spec is reported as
**INCOMPATIBLE**, not a warning: it usually means pip resolved around a
conflict and quietly gave you a different toolkit.

Model weights are reported as **NOT_AVAILABLE** by design — Phase 1
downloads nothing.

## ⚠ Telemetry

The NeMo dependency tree includes `wandb`, `sentry-sdk`,
`nv-one-logger-training-telemetry`, OpenTelemetry OTLP exporters, and
`aistore`. None is needed for diarization; all are potential egress
paths for paths, hostnames, and stack traces.

The pipeline runner sets the opt-out variables for **every** stage
subprocess automatically. For interactive work:

```bash
source scripts/disable_telemetry.sh
```

Defence in depth, not a guarantee — verify with network monitoring before
processing private material.

## CPU fallback

Sortformer inference runs on CPU. Expect it to be substantially slower
than GPU; for 31 recordings that is a matter of patience rather than
feasibility. Bulk corpora would need a GPU
([GPU_STRATEGY.md](GPU_STRATEGY.md)).

## Models (download deliberately, later)

| Model | Notes |
|---|---|
| `nvidia/diar_sortformer_4spk-v1` | Offline |
| `nvidia/diar_streaming_sortformer_4spk-v2.1` | Newest; NVIDIA Open Model License |

Both cap at 4 speakers. Neither is gated.

Fetching them requires unsetting `HF_HUB_OFFLINE` — stage subprocesses
run offline by default so they fail loudly instead of downloading
silently.

## Not verified

- CUDA wheel selection and VRAM needs are untested — the environment was
  built and used CPU-only (`--cpu`), no GPU present on this machine.
- Whether NeMo 3.0.0's release ships Sortformer inference code identical
  to `main`; the v2.1 model card recommends installing from `main`. This
  remains unverified because Sortformer itself was never loaded — only
  `titanet_large` (a different model within the same package) was.
- Sortformer diarization end-to-end: no diarization stage has run in
  this environment. `docs/REAL_ML_RUNTIME_INTEGRATION.md` covers only
  the speaker-embedding use case this milestone actually exercised.
