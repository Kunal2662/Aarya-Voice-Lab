# AARYA Voice Lab

Standalone, **local-first** research and engineering project for AARYA's
voice system.

> **Status: Phase 0 — Foundation.** This repository currently contains
> architecture, schemas, safety policy, tooling, and documentation only.
> **No voice model has been built. No recordings have been processed. No
> cloud voice API is used.** Capabilities marked *PLANNED* are not
> implemented.

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

## What exists today (Phase 0)

| Area | Status |
|---|---|
| Repository structure & source protection | Implemented |
| `.gitignore` rules for audio / models / embeddings / secrets | Implemented |
| Hardware & environment detection | Implemented |
| Dataset manifest / experiment / model / benchmark schemas | Implemented |
| Speaker-safety decision policy | Implemented (policy logic only) |
| Experiment & model registries | Implemented |
| Manual-review data model | Implemented |
| CLI foundation | Implemented |
| Test suite (synthetic fixtures only) | Implemented |
| `VoiceService` interface contract | Defined, **no provider implemented** |
| Diarization / transcription / alignment | **PLANNED** |
| Dataset construction | **PLANNED** |
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
aarya-voice system-info              # report OS/CPU/RAM/GPU/CUDA/FFmpeg/disk
aarya-voice system-info --json       # machine-readable
aarya-voice validate-environment     # readiness + Git safety scan
aarya-voice validate-config          # validate configs/default.yaml
aarya-voice validate-manifest <path> # validate a record against its schema
aarya-voice experiment --help
aarya-voice benchmark --help
```

Environment detection works on machines with **no GPU, no CUDA, and no
FFmpeg**, reporting missing capabilities rather than failing.

Future commands (`inventory`, `diarize`, `transcribe`, `review`,
`build-dataset`, `train`, `evaluate`) are registered but deliberately
refuse to run — they exit non-zero with a PLANNED notice so no script can
accidentally begin processing private material.

## Testing

```bash
pytest        # 148 tests, synthetic fixtures only
ruff check .
```

No test uses, references, or requires the real recordings.

---

## Documentation

| Document | Contents |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, module layout, phases |
| [ENVIRONMENT.md](docs/ENVIRONMENT.md) | Python/dependency strategy & version research |
| [SECURITY.md](docs/SECURITY.md) | Speaker safety, verification, private-voice security model |
| [PRIVACY.md](docs/PRIVACY.md) | Data handling rules for the private recordings |
| [DATASET_PIPELINE.md](docs/DATASET_PIPELINE.md) | The full future processing pipeline |
| [TOOLCHAIN.md](docs/TOOLCHAIN.md) | Provider abstraction & candidate tools |
| [MODEL_STRATEGY.md](docs/MODEL_STRATEGY.md) | Model registry, experiments, TTS candidates |
| [BENCHMARKING.md](docs/BENCHMARKING.md) | Voice quality benchmark framework |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md) | Contributing, Git safety workflow |

## License

See [LICENSE](LICENSE). Note that the license covers this **code only** —
it grants no rights whatsoever to the private recordings, any dataset
derived from them, or the Private Voice model.
