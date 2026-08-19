# Reproducibility

What can be reproduced from this repository today, and — stated plainly —
what cannot.

## Honest status

**The base environment is fully reproducible. The ML environments are
not, and cannot be made so from this repository alone.**

| Layer | Reproducible? | Why |
|---|---|---|
| Base environment | **Yes** | 3 pinned deps, installed and tested here |
| Schemas, manifests, contracts | **Yes** | Versioned in Git, validated offline |
| Synthetic audio fixtures | **Yes** | Deterministic; byte-identical across runs (tested) |
| Test suite | **Yes** | 219 tests, no external dependency |
| `env-nemo` | **Partly** | Spec + script are versioned; **requires downloading torch/NeMo** |
| `env-whisperx` | **Partly** | Same, **plus gated weights and a credential** |
| `env-tts` | **No** | No model selected |
| Model weights | **No** | Never committed; must be fetched |

Claiming full reproducibility would be false: building any ML environment
requires downloading multi-gigabyte wheels from PyPI and the PyTorch
index, and — for pyannote — an authenticated, consent-gated fetch. A
machine with no network cannot build them from this repository.

## What is pinned, and where

| Artifact | Role |
|---|---|
| `pyproject.toml` | Base dependencies and Python range |
| `requirements/*.txt` | Layered, per-environment dependency sets |
| `environment/specs.py` | Expected versions per environment, enforced by `*-check` |
| `scripts/install_env.sh` | Exact torch version + wheel index per environment |
| `environment/manifest.py` | Records what an environment *actually* contains |

The distinction between the last two matters: the spec is intent, the
manifest is fact. Reproducing a result requires the manifest.

## Environment manifests

```python
from aarya_voice_lab.environment.manifest import write_environment_manifest
write_environment_manifest(Path("reports/env-nemo.json"), "env-nemo")
```

Captures interpreter, platform, hardware (CPU/RAM/GPU/driver/CUDA),
FFmpeg availability, and **every installed distribution with its exact
version**.

An experiment that cannot name its environment manifest cannot claim to
be reproducible — which is why the experiment schema carries `hardware`
and `software_versions` fields.

## Stage-level reproducibility

Every stage writes a `result.json` conforming to
[`stage_result.schema.json`](../schemas/stage_result.schema.json):

- `environment_id` — **which** environment ran it (they differ in torch version)
- `tool` / `tool_version` / `model` / `model_version`
- `processing_version` — the code that produced it
- `inputs` / `outputs` with **SHA-256 hashes**
- `started_at`, `completed_at`, `duration_seconds`, `hardware`
- `status`, including `blocked` for stop conditions

Because inputs and outputs are hashed, a run can be **resumed**: if a
stage's outputs still match their recorded hashes, downstream work does
not need redoing. Tampering is detected rather than silently inherited —
both behaviours are asserted by test.

## Why version drift is treated as an error

`aarya-voice nemo-check` reports a package version differing from its
spec as **INCOMPATIBLE**, not as a warning. This is deliberate: the
measured behaviour in [COMPATIBILITY.md](COMPATIBILITY.md) is that pip
resolves conflicts by **silently downgrading** — torch 2.13 → 2.8, NeMo
3.0.0 → 2.7.3 — producing an environment that looks healthy and is not
the one specified. Drift is exactly the failure this project must catch.

## Reproducing on a new machine

```bash
git clone <repo> && cd Aarya-Voice-Lab
python3 -m venv .venv && source .venv/bin/activate   # Python 3.12 preferred
pip install -e ".[dev]"

aarya-voice env-audit          # what does this machine have?
scripts/verify_all.sh          # tests, lint, schema + Git safety checks
```

That reproduces everything Phase 1 actually verified. Building the ML
environments is a separate, deliberate, network-dependent step:

```bash
scripts/install_env.sh env-nemo --cpu    # or --cuda
aarya-voice nemo-check
```

## Determinism limits

Reproducible today: schema validation, manifest construction, synthetic
audio generation, hashing, and the full test suite.

**Not yet established:** ML determinism. Model inference varies with
hardware, kernel versions, batch size, and seeds. When real stages are
implemented, seeds must be recorded in `configuration` and results
compared only across matching `hardware` blocks. Nothing in this project
has run a model, so this is an open commitment, not a solved problem.

## External requirements (unavoidable)

| Requirement | Environment | Gated? |
|---|---|---|
| PyPI + PyTorch wheel index | all ML envs | No |
| Sortformer weights | `env-nemo` | **No** |
| Whisper weights | `env-whisperx` | No |
| pyannote diarization weights | `env-whisperx` | **Yes — token + agreement** |
| IndicF5 weights | `env-tts` | **Yes — contact-sharing agreement** |
| FFmpeg | audio stages | No (system package) |

Stage subprocesses run with `HF_HUB_OFFLINE=1` by default, so any stage
needing an undownloaded model **fails loudly** rather than fetching it
silently. Downloads must be enabled deliberately.
