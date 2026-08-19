# Compatibility Audit

Evidence for the environment-isolation decision. Everything here comes
from **dependency resolutions actually executed** on 2026-08-19 with
`pip install --dry-run --ignore-installed` on Linux x86_64 / CPython
3.11.15 — not from documentation or recollection.

> **Nothing was installed.** Dry-run resolution computes the install plan
> without downloading or installing packages.

---

## Correction to a Phase 0 finding

Phase 0 recorded that NeMo and WhisperX "cannot be installed together —
unsatisfiable constraints". **That is wrong, and the real behaviour is
more dangerous.** They *do* resolve together. pip reaches a solution by
silently degrading the stack.

### Measured results

| Requested | Resulting `nemo-toolkit` | Resulting `torch` |
|---|---|---|
| `nemo-toolkit[asr]` | 3.0.0 | **2.13.0** |
| `whisperx` | — | **2.8.0** |
| `nemo-toolkit[asr]` + `whisperx` | 3.0.0 | **2.8.0** ← downgraded |
| `nemo-toolkit[asr,cu12]` + `whisperx` | **2.7.3** ← downgraded | 2.8.0 |

Every one of these resolved successfully. No error, no warning.

### Why this still means isolation

The hazard is not a failed install — it is a **successful install of the
wrong thing**:

1. Co-installing drags torch from **2.13.0 down to 2.8.0**, because
   WhisperX pins `torch~=2.8.0` (a hard `<2.9` ceiling). NeMo 3.0.0's
   tested matrix is torch **2.11–2.12**. The combined environment runs
   NeMo on a torch it was never validated against.
2. Adding NeMo's CUDA extra makes pip **silently downgrade NeMo itself**
   from 3.0.0 to 2.7.3 — a different toolkit generation, with harsher
   transitive pins (`fsspec==2024.12.0` exact).
3. `lightning` resolves to exactly **2.4.0**, the single version
   satisfying both NeMo (`>2.2.1,<=2.4.0`) and pyannote (`>=2.4`). That
   release predates torch 2.8 by roughly two years.

A resolver "success" that quietly changes your diarization toolkit
version is worse than a clean failure: it produces an environment that
looks fine and behaves subtly differently. **Isolation is retained — for
this reason, not the one Phase 0 gave.**

### Decision

| Environment | torch | Rationale |
|---|---|---|
| `env-nemo` | 2.13.0 | NeMo 3.0.0 on a modern torch, undegraded |
| `env-whisperx` | 2.8.0 | WhisperX's ceiling, isolated so it constrains nothing else |
| `env-tts` | model-dependent | TTS stacks bring their own torch/transformers |

Enforced by `EnvironmentSpec.expected_packages` and asserted by
`tests/test_environment_specs.py`. `aarya-voice nemo-check` reports a
version mismatch as **INCOMPATIBLE**, precisely because silent drift is
the failure mode this project guards against.

---

## ⚠ Telemetry pulled in by the ML stack

The `nemo-toolkit[asr]` resolution installs **four independent reporting
stacks**, none required for diarization:

| Package | What it does |
|---|---|
| `wandb` 0.28.2 | Weights & Biases cloud experiment tracking |
| `sentry-sdk` 2.68.0 | Remote crash/error reporting |
| `nv-one-logger-training-telemetry` 2.3.1 | NVIDIA usage telemetry |
| `opentelemetry-exporter-otlp-*` 1.44.0 | OTLP trace/metric exporters |

Also present: `aistore` (remote object store client).

For a project whose defining rule is that private material never leaves
the machine, defaults are not acceptable. These are unlikely to transmit
audio, but they can transmit **file paths, hostnames, stack traces, and
run metadata** — and file paths alone can leak the structure of private
source material.

**Mitigation, applied in two places:**

- `scripts/disable_telemetry.sh` for interactive shells.
- `TELEMETRY_OFF_ENV` in `pipeline/runner.py`, applied to **every** stage
  subprocess automatically — asserted by test.

Stage subprocesses additionally default to `HF_HUB_OFFLINE=1` /
`TRANSFORMERS_OFFLINE=1`, so a stage **fails loudly rather than silently
downloading** a model. Downloads require passing `offline=False`
deliberately.

This is defence in depth, **not a guarantee**. Verify with network
monitoring before processing private material.

---

## ⚠ pyannote is unavoidable with WhisperX

Installing `whisperx` transitively installs:

- `pyannote-audio` 4.0.7 — its diarization pipeline is a **gated**
  HuggingFace model needing a token and acceptance of a contact-sharing
  agreement
- `pyannoteai-sdk` 0.4.0 — a client for a **commercial** API

This is structural, not optional: you cannot install WhisperX without
them. Using WhisperX for **transcription and alignment only** avoids
triggering the gate (audio is processed locally; the token gates the
*download*). Using pyannote for diarization does not.

**Consequence:** NeMo Sortformer is the primary diarization system —
`nvidia/diar_streaming_sortformer_4spk-v2.1` is ungated and needs no
credentials. Adopting pyannote for independent verification requires
explicit sign-off.

`aarya-voice whisperx-check` reports these as STOP CONDITIONS and exits
3. `scripts/install_env.sh env-whisperx` refuses to run without
`--i-have-approval`.

---

## Python version

| Component | Requirement |
|---|---|
| NeMo Curator | `>=3.11,<3.14` |
| WhisperX | `>=3.10,<3.14` |
| NVIDIA NeMo | metadata `>=3.10`; docs state 3.12+ |
| pyannote.audio | `>=3.10` |
| PyTorch 2.13 | 3.10–3.14 |

**Target: Python 3.12** — the widest common ground. This repository
declares `>=3.11,<3.14` because the base environment has no ML
dependencies; the ML environments should be built on 3.12.

**Verified caveat:** this audit ran on **3.11.15**, not 3.12. The
resolutions above are therefore confirmed for 3.11 and *expected* to hold
on 3.12. Re-verify when a 3.12 interpreter is available.

---

## Other constraints (from resolved metadata)

- **numpy 2.x is fine** — resolved to 2.4.6 across NeMo, WhisperX, and
  their dependents. Only the stale PyPI `fish-speech` (caps `<=1.26.4`)
  conflicts, and that candidate is rejected on licensing anyway.
- **`hydra-core` 1.3.2 / `omegaconf` 2.3.0** — NeMo holds these frozen;
  anything needing hydra 1.4+ breaks it.
- **cuDNN** — `ctranslate2` resolved to 4.8.1 (cuDNN 9, matching torch's
  bundled version). A *system* cuDNN 8 alongside torch's cuDNN 9 causes
  segfaults in `OperationSet::finalize_internal()`, not a clear error.
- **CUDA wheels are the default** — the plain resolution pulled ~15
  `nvidia-*-cu12` packages (multiple GB) even on this GPU-less machine.
  `scripts/install_env.sh` installs torch from the explicit CPU or CUDA
  index *first* to prevent that.
- **`transformers` is unpinned** by NeMo — resolved to 4.57.6. Pin it
  explicitly at install time; "newest" risks silent API breakage.

---

## What is NOT verified

Stated honestly, because the brief requires documenting tested state
rather than assumptions:

- **No environment has been built.** Only resolution was tested. Import
  success, runtime behaviour, and GPU execution are unverified.
- **No model weights downloaded**, so no model has been loaded or run.
- **Not verified on Python 3.12** (this machine has 3.11.15).
- **No GPU available here**, so CUDA wheel selection, driver
  compatibility, and VRAM figures are untested.
- **IndicF5's dependency pins are unpublished**; its resolution is
  untested.
- Whether NeMo 3.0.0's release ships Sortformer inference code identical
  to `main` (the v2.1 model card recommends installing from `main`).
