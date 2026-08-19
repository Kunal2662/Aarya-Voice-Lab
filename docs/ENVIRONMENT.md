# Environment & Dependency Strategy

> **Nothing in the ML stack below is installed.** Phase 0 installs only
> three lightweight core dependencies. The versions here are the result
> of a compatibility audit and exist to inform a later, approved
> installation phase.
>
> Version facts were verified against PyPI metadata, official docs, and
> model cards on **2026-08-19**. Fast-moving packages should be re-checked
> before any real install.

---

## Recommended Python version

**Python 3.12.**

| Component | Python requirement |
|---|---|
| NeMo Curator | `>=3.11,<3.14` |
| WhisperX | `>=3.10,<3.14` |
| NVIDIA NeMo | metadata `>=3.10`; docs state 3.12+ (tested on 3.13) |
| pyannote.audio | `>=3.10` |
| PyTorch 2.13 | 3.10–3.14 |

The only overlap satisfying every component is **3.12 or 3.13**; 3.12 is
the safer choice as the broader ecosystem targets it. This repository
itself declares `>=3.11,<3.14` since Phase 0 code has no ML dependencies,
but **provision new environments as 3.12** to avoid rework.

Python 3.14+ is not viable — most of the speech stack has no wheels, and
WhisperX explicitly caps below it.

---

## The critical finding: one environment is not possible

**NVIDIA NeMo and WhisperX cannot be installed together.** This is not a
soft warning; it is an unsatisfiable constraint:

| Package | PyTorch pin |
|---|---|
| WhisperX 3.8.6 | `torch~=2.8.0` (i.e. `>=2.8,<2.9`) |
| `nemo-toolkit[cu12]` / `[cu13]` 3.0.0 | `torch==2.12.0+cuXXX` (exact) |
| `nemo_curator[video_cuda12]` | `torch<=2.10.0` |

Three mutually exclusive ranges. **The architecture therefore assumes
separate virtual environments per toolchain role**, and the provider
abstraction in [TOOLCHAIN.md](TOOLCHAIN.md) exists partly to make that
separation survivable — stages communicate through manifest files on
disk, not through a shared Python process.

### Planned environment split

| Env | Role | Python | Key pins |
|---|---|---|---|
| **A** | Diarization / ASR — NVIDIA path | 3.12 | `torch` 2.12 (cu126/cu130), `nemo-toolkit[asr]` 3.0.0 |
| **B** | Diarization / ASR — Whisper path | 3.12 | `torch` 2.8.x, `whisperx` 3.8.6, `pyannote.audio` 4.x |
| **C** | Dataset curation | 3.12 | `nemo-curator` 1.3.0, one modality extra only |
| **D** | TTS / voice model | 3.12 | model-dependent; see [MODEL_STRATEGY.md](MODEL_STRATEGY.md) |
| **base** | This repo, Phase 0 | 3.11–3.13 | `pyyaml`, `jsonschema`, `psutil` |

Other tight-but-satisfiable constraints worth knowing before installing:

- **`lightning` is the fragile one.** NeMo pins `>2.2.1,<=2.4.0`;
  pyannote.audio 4.0.7 needs `>=2.4`. The single satisfying version is
  exactly **2.4.0** (Aug 2024), which predates torch 2.8+. Expect
  runtime breakage rather than a clean resolver error if A and B are
  ever merged.
- **`hydra-core<=1.3.2` / `omegaconf<=2.3`** — NeMo has held these frozen
  since 2023; anything needing hydra 1.4+ conflicts.
- **numpy 2.x is fine** across NeMo, WhisperX, coqui-tts. Only the stale
  PyPI `fish-speech` package (caps at `<=1.26.4`) conflicts.
- **cuDNN split** — torch ≥2.5.1 bundles cuDNN 9; `ctranslate2 <4.5.0`
  only supports cuDNN 8. Mismatch causes segfaults in
  `OperationSet::finalize_internal()`, not a clear error message.
- **`transformers` is unpinned** by NeMo and F5-TTS. Resolving to
  "newest" risks silent API breakage; pin it explicitly when installing.
- **Prefer `nemo-toolkit[asr]` over `nemo-toolkit-asr`** — the latter is
  a pre-release with far harsher exact pins (`fsspec==2024.12.0`).
- **NeMo Curator: install one modality extra at a time** with pip
  (NVIDIA's own guidance); use `uv` or their container otherwise.

---

## ⚠ Credentials required by the WhisperX path

**This is flagged for explicit approval before Phase 1** (see the hard-stop
rules in [PRIVACY.md](PRIVACY.md)):

`pyannote.audio`'s recommended pipeline
(`pyannote/speaker-diarization-community-1`) is a **gated** HuggingFace
model. Using it requires:

1. a **HuggingFace access token**, and
2. accepting a user agreement that includes **sharing contact
   information** and consenting to marketing email about premium
   offerings.

The weights are CC-BY-4.0 and can be used offline *after* a one-time
authenticated download, but the gate itself cannot be bypassed. The
package also carries `pyannoteai-sdk` — a client for a commercial API —
as a **mandatory** dependency.

**Consequence for this project:** the NVIDIA path (Env A) is preferred
for the primary diarization system, because
`nvidia/diar_streaming_sortformer_4spk-v2.1` is **not gated** and needs no
credentials. The WhisperX/pyannote path remains a candidate for the
*independent* verification system, but adopting it is a decision that
requires sign-off, since it introduces a credential dependency and a
third-party account relationship into a project whose defining constraint
is privacy.

No credentials of any kind are needed for Phase 0.

---

## Requirements layering

Dependencies are split so that installing the project never drags in a
multi-gigabyte ML stack:

| File | Contents | Installed in Phase 0 |
|---|---|---|
| `requirements/base.txt` | Core runtime — config, schemas, system info | **Yes** |
| `requirements/audio.txt` | Audio I/O and analysis | No |
| `requirements/diarization.txt` | NeMo / Sortformer (Env A) | No |
| `requirements/transcription.txt` | WhisperX / pyannote (Env B) | No |
| `requirements/tts.txt` | Voice model candidates (Env D) | No |

Each optional file documents which environment it belongs to and warns
against co-installation. **Do not install a requirements file merely
because it exists** — install only what an approved phase needs.

## System-level tools

| Tool | Needed for | Phase 0 |
|---|---|---|
| **FFmpeg** | All audio decode/segment operations | Not required |
| **NVIDIA driver + CUDA** | GPU acceleration (optional) | Not required |
| **git-lfs** | Fetching gated model weights for offline use | Not required |

Check what the current machine has:

```bash
aarya-voice system-info
aarya-voice validate-environment
```

Both work on machines with no GPU, no CUDA, and no FFmpeg.

## CPU-only and GPU execution

The architecture supports **CPU-only** execution: no Phase 0 code path
requires a GPU, and `system_info` treats a missing GPU as informational.
CPU-only diarization and training will be substantially slower, and
training a TTS model on CPU may be impractical — that is a throughput
constraint to plan around, not an architectural blocker.

For GPU, PyTorch 2.13 ships `cu130` as default, retains `cu126` for older
architectures (Pascal/Volta), and **removed CUDA 12.8/12.9 builds**.
CPU-only wheels come from
`https://download.pytorch.org/whl/cpu`. NeMo Sortformer's 4-speaker models
suit this project's 2-speaker material well.

Install nothing GPU-related automatically — always pick the wheel index
that matches the driver reported by `aarya-voice system-info`.
