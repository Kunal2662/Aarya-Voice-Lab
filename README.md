# AARYA Voice Lab

Standalone, **local-first** research and engineering project for AARYA's
voice system.

> **Status: Phase 3 — Speaker Identity Architecture (software-only).**
> The identity architecture is implemented and tested against synthetic
> fixtures: embedding provider abstraction, pluggable enrollment, speaker
> profiles, verification engine, calibration states, identity review, and
> an append-only audit log.
>
> **No recordings have been accessed. No real embedding has ever been
> computed. No speaker model is installed. No training has occurred. No
> cloud voice API is used.** The only embedding provider is a deterministic
> synthetic one, and every artifact it produces is stamped synthetic so it
> can never be read as a real identity conclusion.

This project is **separate from AARYA Core and AARYA Frontend**. It does
not modify, import from, or integrate with either.

---

## Purpose

The Voice Lab will eventually produce two distinct voice models:

| | **Default Voice** | **Private Voice** |
|---|---|---|
| Source material | Not derived from private recordings | Derived from 31 authorized private recordings |
| Availability | Broader AARYA use | **Admin-only**, permission-gated (`voice.private.use`) |
| Status | PLANNED — not selected yet | PLANNED — no data processed yet |

The Private Voice is based on recordings of an authorized female speaker
who is deceased. That material is **private, immutable, and never enters
Git or any cloud service**. See [`docs/PRIVACY.md`](docs/PRIVACY.md) —
these rules are not optional.

---

## What exists today (Phases 0–3)

| Area | Status |
|---|---|
| Repository structure & source protection | Implemented |
| `.gitignore` rules for audio / models / embeddings / secrets | Implemented |
| Hardware & environment detection | Implemented |
| Capability audit (AVAILABLE/OPTIONAL/INCOMPATIBLE/UNKNOWN/…) | Implemented |
| Environment specs + install/verify scripts | Implemented (**environments not built**) |
| Pipeline filesystem contracts (hashes, resumability) | Implemented |
| Cross-environment stage runner | Implemented (verified with synthetic stages) |
| Synthetic audio fixtures & inventory stage | Implemented |
| TTS candidate matrix & license audit | Implemented (**no model selected**) |
| Dataset manifest / experiment / model / benchmark / stage schemas | Implemented |
| Speaker-safety decision policy | Implemented (policy logic only) |
| Experiment & model registries | Implemented |
| Manual-review data model | Implemented |
| CLI | Implemented |
| Test suite (synthetic fixtures only) | Implemented — 432 tests |
| `VoiceService` interface contract | Defined, **no provider implemented** |
| NeMo / WhisperX / TTS environments | **Specified, NOT installed** |
| Model weights | **None downloaded** |
| Dataset candidate pipeline (Phase 2) | Implemented — synthetic audio only |
| Speaker identity architecture (Phase 3) | Implemented — **synthetic provider only** |
| Real speaker verification | **BLOCKED** — no real provider installed |
| Speaker diarization | **PLANNED** |
| Verified dataset construction | **PLANNED** |
| Voice model training | **PLANNED** |
| Benchmark execution | **PLANNED** (framework/schema only) |
| AARYA Core integration | **PLANNED** — explicitly out of scope here |

---

## Installation

Requires **Python 3.11–3.13**; **3.12 is the recommended target**, because
it is the only version the future ML stack (NeMo, NeMo Curator, WhisperX)
can commonly support. See [`docs/ENVIRONMENT.md`](docs/ENVIRONMENT.md).

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

This installs only lightweight core dependencies (`pyyaml`, `jsonschema`,
`psutil`). **No ML/GPU dependencies are installed** — PyTorch, NeMo,
WhisperX and TTS stacks are deliberately deferred to a later, approved
phase. See [`requirements/`](requirements/) for the layered strategy.

## Usage

```bash
aarya-voice env-audit                # capability states for every prerequisite
aarya-voice system-info              # raw OS/CPU/RAM/GPU/CUDA/FFmpeg/disk facts
aarya-voice validate-environment     # readiness + Git safety scan
aarya-voice validate-config          # validate configs/default.yaml
aarya-voice validate-manifest <path> # validate a record against its schema

aarya-voice nemo-check               # verify env-nemo against its spec
aarya-voice whisperx-check           # verify env-whisperx (reports stop conditions)
aarya-voice tts-check
aarya-voice tts-candidates           # TTS candidate matrix + license audit
aarya-voice inventory <dir>          # catalogue audio (refuses the private source tree)
aarya-voice validate-audio <dir>     # VALID / WARNING / INVALID / BLOCKED
aarya-voice analyze-quality <dir>    # measurements + configured decisions
aarya-voice segment <dir> --dry-run  # candidate segments + manifest
aarya-voice dataset-report <dir>     # summary + technical review queue
aarya-voice dataset-gate             # may we touch the real recordings?

aarya-voice identity-status          # speaker identity architecture status
aarya-voice enrollment-strategies    # pluggable enrollment strategies
aarya-voice calibration-status       # calibration state and its limits
aarya-voice runtime-capabilities     # vendor-neutral component capabilities
aarya-voice identity-audit           # append-only identity audit log
aarya-voice embedding-inventory      # stored embeddings (never their vectors)
aarya-voice synthetic-e2e            # full Phase 3 chain on generated audio
aarya-voice voice-preview-status     # VL-V0 preview contracts (no generation)

aarya-voice experiment --help
aarya-voice benchmark --help
```

Full verification sweep:

```bash
scripts/verify_all.sh
```

Environment detection works on machines with **no GPU, no CUDA, and no
FFmpeg**, reporting missing capabilities rather than failing.

Future commands (`diarize`, `transcribe`, `review`, `build-dataset`,
`train`, `evaluate`) are registered but deliberately refuse to run — they
exit non-zero with a PLANNED notice so no script can accidentally begin
processing private material. Phase 2 commands additionally refuse to read
the private source tree unless explicitly approved.

## Testing

```bash
pytest        # 432 tests, synthetic fixtures only
ruff check .
```

No test uses, references, or requires the real recordings.

---

## Documentation

| Document | Contents |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, module layout, phases |
| [COMPATIBILITY.md](docs/COMPATIBILITY.md) | **Measured** dependency evidence, isolation decision, telemetry finding |
| [ENVIRONMENT.md](docs/ENVIRONMENT.md) | Python/dependency strategy, FFmpeg install |
| [NEMO.md](docs/NEMO.md) | `env-nemo` spec, build, verification |
| [WHISPERX.md](docs/WHISPERX.md) | `env-whisperx` spec — **requires approval** |
| [TTS_MODELS.md](docs/TTS_MODELS.md) | Candidate matrix and license audit |
| [GPU_STRATEGY.md](docs/GPU_STRATEGY.md) | CPU / GPU / high-VRAM machine classes |
| [REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md) | What is and isn't reproducible |
| [SECURITY.md](docs/SECURITY.md) | Speaker safety, verification, private-voice security model |
| [PRIVACY.md](docs/PRIVACY.md) | Data handling rules for the private recordings |
| [DATASET_PIPELINE.md](docs/DATASET_PIPELINE.md) | The Phase 2 dataset pipeline, provenance, and the access gate |
| [PHASE3_IDENTITY.md](docs/PHASE3_IDENTITY.md) | Phase 3 identity architecture, calibration honesty, embedding security |
| [VLD0_DESIGN_SYSTEM.md](docs/VLD0_DESIGN_SYSTEM.md) | VL-D0 design-system foundation: tokens, components, shell, status vocabulary, accessibility |
| [TOOLCHAIN.md](docs/TOOLCHAIN.md) | Provider abstraction & candidate tools |
| [MODEL_STRATEGY.md](docs/MODEL_STRATEGY.md) | Model registry, experiments, TTS candidates |
| [BENCHMARKING.md](docs/BENCHMARKING.md) | Voice quality benchmark framework |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md) | Contributing, Git safety workflow |

## License

See [LICENSE](LICENSE). Note that the license covers this **code only** —
it grants no rights whatsoever to the private recordings, any dataset
derived from them, or the Private Voice model.
