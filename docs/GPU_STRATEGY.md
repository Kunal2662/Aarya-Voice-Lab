# GPU Strategy

The project must run across three machine classes. No single machine is
assumed to do everything, and **no stage may require a GPU to exist**.

> Detection is implemented and tested. GPU execution itself is
> **unverified** — the audit machine has no NVIDIA GPU.

## The three situations

### A. CPU-only development machine

The baseline. Everything architectural must work here.

| Suitable for | Notes |
|---|---|
| Dataset engineering, manifests, schema validation | Native fit — no ML needed |
| Inventory, hashing, quality metrics | Cheap |
| Diarization (Sortformer) | Works, substantially slower |
| Transcription (Whisper) | Works, slow; use a smaller model |
| TTS inference (small models) | Feasible |
| **Training / finetuning** | **Not practical** |

Phase 0 and Phase 1 were both developed and verified entirely on a
CPU-only machine (4 cores, 15.7 GB RAM, no CUDA, no FFmpeg).

### B. NVIDIA GPU development machine

Accelerates the pipeline; changes nothing architecturally.

| Suitable for | Notes |
|---|---|
| Accelerated diarization / transcription | The main win |
| TTS inference and iteration | Fast feedback |
| Small-scale experimentation | Depends on VRAM |

Install torch from the CUDA index matching the **detected driver**:

```bash
aarya-voice env-audit                        # read the driver/GPU first
scripts/install_env.sh env-nemo --cuda
```

### C. Temporary high-VRAM GPU machine

Rented or borrowed for a bounded task, then released.

| Suitable for | Notes |
|---|---|
| Heavy training / finetuning | The reason to use one |
| Large-model experiments | VRAM-bound |

**This class carries the highest privacy risk in the whole project.**
Training the Private Voice means the private dataset — and the resulting
model, which can reproduce the speaker's voice — exist on a machine you
do not own and cannot physically control.

Before using one:

- Treat the dataset and any checkpoint as **equivalent to the source
  recordings** ([PRIVACY.md](PRIVACY.md)).
- Prefer a machine with **encrypted storage** you control.
- Assume disks may be recycled: **securely erase** dataset, checkpoints,
  caches, and shell history before releasing the instance.
- Never leave weights in a provider's snapshot, image, or object store.
- Disable telemetry (`source scripts/disable_telemetry.sh`) — a rented
  box is exactly where a default-on crash reporter is least welcome.
- **Do not use a hosted notebook service** that uploads data as part of
  its normal operation.

Whether to use a rented GPU at all is a decision for the training phase,
and it deserves an explicit risk judgement rather than being treated as
routine infrastructure.

## Detection

```bash
aarya-voice env-audit
```

| Capability | Meaning |
|---|---|
| `NVIDIA GPU` | `AVAILABLE` with model/VRAM, or `OPTIONAL` when absent |
| `CUDA runtime` | `AVAILABLE`, `OPTIONAL`, or `UNKNOWN` when torch is absent |
| `CUDA toolkit (nvcc)` | `OPTIONAL` — torch wheels bundle their own runtime |

**Absence of a GPU is never an error.** It reports as `OPTIONAL`, and
`UNKNOWN` (e.g. CUDA state with no torch installed) is not treated as
blocking either — both are asserted by test.

## Wheel index selection

CUDA wheels are pip's default, so a naive install pulls ~15
`nvidia-*-cu12` packages (multiple GB) onto GPU-less machines.
`scripts/install_env.sh` therefore installs torch **first** from an
explicit index:

| Environment | CPU index | CUDA index |
|---|---|---|
| `env-nemo` (torch 2.13.0) | `.../whl/cpu` | `.../whl/cu130` |
| `env-whisperx` (torch 2.8.0) | `.../whl/cpu` | `.../whl/cu126` |

PyTorch 2.13 ships `cu130` as default, retains `cu126` for older
architectures (Pascal/Volta), and **removed CUDA 12.8/12.9 builds**.

## Where the runtime GPU decision belongs

Whether the **production Private Voice** needs a GPU at inference time is
deliberately unanswered. It depends on the selected model, acceptable
latency, and real-time factor — all measured in the benchmark phase
([BENCHMARKING.md](BENCHMARKING.md)). Deciding now, without measurement,
would be guessing.

Note that a CPU-only runtime has a genuine privacy advantage: it widens
the set of machines that can host the Private Voice under your own
control.

## Not verified

- **No GPU was available**, so CUDA execution, driver compatibility,
  VRAM figures, and CUDA wheel installation are all untested.
- No model has been run on any hardware.
- Performance claims (GPU "faster") are architectural expectations, not
  measurements from this project.
