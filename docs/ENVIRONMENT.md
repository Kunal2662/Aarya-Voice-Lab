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

## The critical finding: environments must be isolated

> **Corrected in Phase 1.** This section originally claimed NeMo and
> WhisperX "cannot be installed together — unsatisfiable". Real
> dependency resolutions run in Phase 1 show that they **do** resolve
> together, and that the actual hazard is worse: pip reaches a solution
> by **silently downgrading** the stack (torch 2.13 → 2.8; with CUDA
> extras, NeMo 3.0.0 → 2.7.3). A successful install of the wrong
> versions is more dangerous than a failed one.
>
> Full measured evidence: **[COMPATIBILITY.md](COMPATIBILITY.md)**.

The conclusion is unchanged — **separate virtual environments per
toolchain role** — but the reason is silent degradation rather than
impossibility. Stages therefore communicate through manifest files on
disk, not a shared Python process (see
[`pipeline/contracts.py`](../src/aarya_voice_lab/pipeline/contracts.py)).

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

| Tool | Needed for | Phase 0/1 |
|---|---|---|
| **FFmpeg** | All audio decode/segment operations | Not required |
| **NVIDIA driver + CUDA** | GPU acceleration (optional) | Not required |
| **git-lfs** | Fetching gated model weights for offline use | Not required |

Check what the current machine has:

```bash
aarya-voice env-audit          # capability states (Phase 1)
aarya-voice system-info        # raw hardware facts
aarya-voice validate-environment
```

All work on machines with no GPU, no CUDA, and no FFmpeg.

### Installing FFmpeg

FFmpeg is a **system package**. This project never installs system
software silently — install it deliberately, then re-run
`aarya-voice env-audit` to confirm it is detected.

| Platform | Command |
|---|---|
| Debian / Ubuntu | `sudo apt update && sudo apt install ffmpeg` |
| Fedora / RHEL | `sudo dnf install ffmpeg` |
| Arch | `sudo pacman -S ffmpeg` |
| macOS (Homebrew) | `brew install ffmpeg` |
| Windows (winget) | `winget install Gyan.FFmpeg` |
| Windows (Chocolatey) | `choco install ffmpeg` |
| Windows (manual) | Download a build from ffmpeg.org, extract, add its `bin\` to `PATH` |

On Windows, confirm `ffmpeg -version` works in a **new** terminal — `PATH`
changes do not apply to already-open shells.

FFmpeg reports as:

- `OPTIONAL` in the base environment (Phase 0/1 need no audio decoding)
- `NOT_AVAILABLE` in `env-whisperx`, where it is genuinely required

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

## A `.envs/<name>` built from WSL is not usable from native Windows

`python -m venv` always writes the POSIX layout (`bin/python`, symlinks
to `/usr/bin/python3`) when run from a WSL/Linux interpreter — even
against a Windows-mounted path like `/mnt/c/Users/.../.envs/env-tts`.
Opening that same `.envs/env-tts` from a native-Windows session later
shows a directory that looks built (packages present under `lib/`) but
whose `bin/python` is a broken symlink pointing at a path
(`/usr/bin/python3`) that does not exist on Windows — every real
provider capability check correctly reports `NOT_CONFIGURED` for it,
which is the honest and correct outcome, not a bug to work around.

This project's own environment-path resolution
(`pipeline.runner.EnvironmentPaths.python`) already looks for
`Scripts/python.exe` first and only falls back to `bin/python`, so a
genuinely native-Windows-built environment is picked up correctly; a
WSL-built one simply never was, and is not silently substituted for.

**If you hit this:** the environment was built from WSL. Delete
`.envs/<name>` and rebuild it from a native Windows shell
(`scripts/install_env.sh` via Git Bash/PowerShell, not `wsl`/`bash`
against the WSL interpreter) — do not attempt to repair the broken
symlinks in place. `.envs/` is git-ignored local machine state; nothing
about this is repository state to fix in code.
