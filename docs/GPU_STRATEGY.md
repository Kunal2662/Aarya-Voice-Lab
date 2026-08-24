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
| `NVIDIA GPU` | `AVAILABLE` with model/VRAM specifically for NVIDIA (via `nvidia-smi`), or `OPTIONAL` when absent. Stays NVIDIA-specific because the torch wheel index decision below depends on exactly this signal. |
| `Accelerator (any vendor)` | `AVAILABLE` for **any** detected GPU — NVIDIA, AMD (via `rocm-smi`), or any other vendor via a PCI-id sysfs enumeration (`/sys/class/drm`) that needs no vendor tool installed at all — or `OPTIONAL` when none is found. This is the hardware-agnostic signal; read it when the question is "is there an accelerator at all," not "is it NVIDIA." |
| `CUDA runtime` | `AVAILABLE`, `OPTIONAL`, or `UNKNOWN` when torch is absent |
| `CUDA toolkit (nvcc)` | `OPTIONAL` — torch wheels bundle their own runtime |

**Absence of a GPU is never an error.** It reports as `OPTIONAL`, and
`UNKNOWN` (e.g. CUDA state with no torch installed) is not treated as
blocking either — both are asserted by test.

**Detection vs. execution, still distinct.** `Accelerator (any vendor)`
going `AVAILABLE` means a GPU device was found — it is not a claim that
this project can run anything on it. Only NVIDIA has an execution path
today: `scripts/install_env.sh`'s CUDA wheel index, and `torch.cuda.
is_available()` as the runtime check. An AMD or other accelerator being
detected does not mean ROCm/Metal/OpenCL execution works here — no
runtime-level check or install path for those exists yet
(`identity.runtime.ComputeBackend`'s `ROCM`/`METAL`/`OPENCL`/`VULKAN`/
`XPU` members exist precisely so adding one later needs no schema
change).

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
- **AMD detection code remains untested against real hardware**: no AMD
  GPU has been available on any machine this project has run on, so
  `_detect_amd_gpu()` is verified only by mocked unit tests
  (`tests/test_system_info.py`).
- **Intel GPU presence detection *is* now verified against real
  hardware** (VL-D19, `docs/VLD19_WINDOWS_GPU_DETECTION.md`): a real
  Intel integrated GPU was detected via the Windows-native fallback
  (`_detect_gpu_via_windows_wmi()`) on the machine that milestone was
  implemented on — independently confirmed against `Get-CimInstance
  Win32_VideoController` outside the project's own code. Detecting
  presence and being able to run something on that hardware remain two
  different, separately-unverified claims: Intel GPU *execution* is
  still untested, the same honest caveat NVIDIA CUDA execution itself
  already carries above.
