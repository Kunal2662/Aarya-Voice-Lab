# Real Voice Model Engine — architecture and current capability

**Status at the time this milestone shipped: architecture complete,
capability NOT_CONFIGURED everywhere.** A later milestone,
**"Real ML Runtime & Model Integration"** (`docs/REAL_ML_RUNTIME_INTEGRATION.md`),
installed a real embedding model against the architecture described
below — `identity.embeddings.LocalNeuralEmbeddingProvider` now reports
`AVAILABLE` on a machine that has built `.envs/env-nemo`. Generation and
training remain exactly as described in this document. Read this file
for the architecture; read `docs/REAL_ML_RUNTIME_INTEGRATION.md` for
which parts of it are now real.

Every provider boundary, contract, job/artifact/lifecycle state machine,
and UI surface this milestone adds is real, tested code. At the time
this milestone shipped, no real speaker embedding, no real voice
generation, and no real training run had ever executed anywhere in this
codebase. What changed *in this milestone* is that the *gap* between
"architecture exists" and "a real model runs" was made honestly
representable in code (`NOT_CONFIGURED`, empirically detected) instead
of only in prose — a later milestone then closed part of that gap for
real, using this same architecture unchanged.

See also: `docs/PHASE3_IDENTITY.md` (the identity architecture this
extends), `docs/MODEL_STRATEGY.md` (the model registry this extends),
`docs/TTS_MODELS.md` (the candidate evaluation this reuses verbatim),
`docs/NEMO.md`/`docs/ENVIRONMENT.md` (why no ML runtime is installed
here), and the hardening-milestone report (the concurrency primitive —
`core.file_lock` — this reuses).

## Why every real provider reports NOT_CONFIGURED

This is not a stub left unfinished. It is the correct, honest outcome of
the environment this milestone actually ran in, confirmed empirically
(not assumed) before writing a line of provider code:

- No GPU (`nvidia-smi`: not found).
- No ML framework installed (`import torch`: `ModuleNotFoundError`).
- This project's own tracked configuration already gates every real ML
  environment behind a separate approval step —
  `configs/default.yaml`'s `environments.env-nemo`/`env-whisperx`/
  `env-tts`, the last two explicitly marked `requires_approval: true`.
- `requirements/tts.txt` is explicit: *"NO MODEL HAS BEEN SELECTED...
  Do not install a model merely because it is listed."* Several
  candidates carry licensing constraints (non-commercial weights, a
  defunct licensor, `trust_remote_code=True` needing review) that make
  "just install one" the wrong call for an unattended milestone.
- `data/source/` — the only place real audio could come from — is
  empty in this environment. There is no real recording, private or
  otherwise, for a real model to process here even if one were
  installed.

Given all of that, installing a multi-hundred-megabyte-to-gigabyte ML
dependency and downloading third-party pretrained weights during this
milestone would have been exactly the "silently introduce a ... model
dependency" this milestone's own directive forbade — so the providers
below implement the full boundary and detect capability empirically,
and report `NOT_CONFIGURED` because that is what is actually installed.

## Provider architecture

Three provider abstractions, following the exact shape
`identity.embeddings.EmbeddingProvider` already established before this
milestone (register a class, ask a registry for an instance, call a
small typed interface — never import a specific ML framework into the
domain layer):

| Abstraction | File | Pre-existing? | Real implementation added |
|---|---|---|---|
| `EmbeddingProvider` | `identity/embeddings.py` | Yes (VL Phase 3) | `LocalNeuralEmbeddingProvider` |
| `VoiceGenerator` | `pipeline/generation.py` | Yes (VL-D5) | `LocalNeuralVoiceGenerator` |
| `TrainingProvider` | `pipeline/training.py` | **New this milestone** | `LocalTrainingProvider` |

Each real implementation:

1. Detects capability via `importlib.metadata` against the exact
   candidate packages this project's own docs already named (TitaNet/
   NeMo for embeddings — see `docs/PHASE3_IDENTITY.md`; Piper/IndicF5/
   Parler-TTS for generation — see `requirements/tts.txt`; NeMo/torch
   for training).
2. Reports a real `NOT_CONFIGURED` (or `UNAVAILABLE`/`ERROR`) capability
   state when the check fails — which it always does in this
   environment.
3. Refuses to produce output rather than fabricating it:
   `EmbeddingProvider.embed()` raises `EmbeddingProviderError`;
   `VoiceGenerator.generate_preview()` raises `GenerationBlockedError`;
   `TrainingProvider` jobs end `FAILED` with
   `TrainingFailureReason.MODEL_UNAVAILABLE`.
4. Never falls back to a synthetic provider silently. The synthetic
   providers (`SyntheticEmbeddingProvider`, `SyntheticVoiceGenerator`)
   are unchanged, still exist, and are still what every test and the
   whole existing D0–D10/FE-1–FE-10 frontend runs against — the real
   providers are a *second*, clearly-labelled, honestly-unavailable
   path alongside them, never a replacement.

Adding a real, installed provider later (once an approved environment
exists) means writing one class that implements the existing ABC and
calling `register_provider()`/instantiating it — no change to the
domain layer, the frontend, or any contract this milestone defines.

## Training architecture

`pipeline/training.py` is new. It defines:

- `TrainingJobStatus`: `QUEUED → VALIDATING → PREPARING → TRAINING →
  CHECKPOINTING → EVALUATING → COMPLETED`, plus `FAILED`/`CANCELLED`/
  `TIMEOUT`.
- `TrainingFailureReason`: a closed, machine-readable vocabulary
  (`MODEL_UNAVAILABLE`, `DATASET_INVALID`, `INSUFFICIENT_DATA`,
  `INCOMPATIBLE_MODEL`, `RESOURCE_UNAVAILABLE`, `TRAINING_FAILED`,
  `GENERATION_FAILED`, `ARTIFACT_CORRUPTED`, `CANCELLED`, `TIMEOUT`).
- `TrainingJob`: persisted fields include `progress: float | None` —
  `None` renders as **UNKNOWN**, never a fabricated percentage, and in
  this environment it is always `None` because no provider can measure
  it.
- `TrainingQueue`: sequential processing mirroring
  `pipeline.generation.GenerationQueue`'s exact shape (one broad
  `except Exception` per job, real wall-clock duration measurement).
- `TrainingJobLog`: a `JsonLinesRegistry` subclass, guarded by
  `core.file_lock` (the hardening milestone's concurrency primitive) —
  concurrent job creation is race-free by construction, verified under
  20 concurrent threads in `tests/test_voice_model_engine.py`.

In this environment, every job that runs ends `FAILED` /
`MODEL_UNAVAILABLE`, deterministically, because `LocalTrainingProvider`
found neither `nemo_toolkit` nor `torch` importable. This is asserted
directly in the test suite, not left to be discovered by accident.

## Training-readiness assessment

`pipeline/training_readiness.py` is pure aggregation over already-
measured values (the same shape as `pipeline.evaluation_aggregation`
and `pipeline.calibration_prep`) — it never re-measures audio, only
decides whether an aggregate clears a documented threshold. Every
threshold lives in `configs/default.yaml`'s new `training_readiness`
section (sample count, total/average duration, sample rate, channels,
clipping, silence, SNR), with the defaults documented as conservative
starting points, not measured against any specific model's real
requirements (since none is installed to measure against). A
`TrainingProvider` may raise (never lower) any threshold via
`provider_requirements`.

One factor, `SPEAKER_CONSISTENCY`, is deliberately **informational
only** — it is not independently verifiable without a real embedding
provider, so it never blocks readiness and never claims to have
measured something that cannot currently be measured here.

## Model lifecycle and artifacts

`pipeline/model_lifecycle.py`: `DRAFT → TRAINING → EVALUATING →
VALIDATED → AVAILABLE → ACTIVE → ARCHIVED`, with `FAILED` reachable
from every pre-availability state (but not from `AVAILABLE`/`ACTIVE`,
which only move forward or retire). `transition()` raises for any move
outside `VALID_TRANSITIONS`.

`pipeline/model_artifact.py`: checksum-addressed storage under the new
`data/model_artifacts/` directory, mirroring `pipeline.import_intake`'s
content-addressed pattern — an artifact's identity is its SHA-256, never
its filename; a second write of the same checksum is refused rather
than silently overwritten; `load_bytes()` re-verifies the checksum on
every read and raises `ArtifactIntegrityError` on any mismatch (tested
directly by tampering with stored bytes and confirming detection).

`schemas/model_registry.schema.json` gained optional fields
(`architecture`, `lifecycle_state`, `sample_rate`, `channels`,
`preprocessing_version`, `embedding_model_ref`, `generation_model_ref`,
`training_config_hash`, `source_job_id`, `artifact_checksum`) — every
existing registry record remains valid unchanged; the new fields are
populated only when a real training job or artifact actually produces
them.

## Multilingual architecture

`TrainingConfig.language` is a free-form tag (default `"und"` —
undetermined), never hardcoded to a fixed set. Nothing in the provider
interfaces, the training job schema, or the model registry schema
assumes English, Hindi, or Marathi specifically — a language-aware real
provider needs no interface change to declare which languages it
actually supports (`requirements/tts.txt`'s own candidate notes already
record IndicF5 as Marathi-capable and Piper's `mr_IN` voice, for
example — this project does not claim multilingual generation works
today; only that the architecture does not block it later).

## Frontend integration

The Models workspace (`avl-workspace-models`) gained one new panel,
"Voice Model Engine — provider capability," built entirely from
existing primitives (`avl-panel`, `avl-status-badge`) — no new
workspace, no new design system, no decorative redesign. It reads a
new, gitignored live snapshot
(`frontend/contracts/live/voice_engine_capabilities.json`, written by
`scripts/export_voice_engine_capabilities.py`, exactly mirroring the
existing `command_center_snapshot.json`/`dataset_gate_status.json`
pattern) and renders each provider's real, current capability state as
a status badge — synthetic providers get an explicit "SYNTHETIC —
deterministic test provider" label instead of a badge, so they can
never be mistaken for a real capability. A fresh clone that has not run
the export script shows an honest "not fetched" message, never a blank
panel and never a fabricated state.

Three new `frontend/tokens/status.json` domains
(`training_job_status`, `training_provider_state`, `model_lifecycle`)
back this and any future UI, each drift-tested against its generated
contract by the hardening milestone's exhaustiveness checks in
`frontend/tests/css-variables.test.mjs`.

## CLI

`aarya-voice voice-engine-status [--json]` — the one place to see every
provider's real capability state in one report, human-readable or JSON.

## What this milestone does not claim

- No real speaker embedding has ever been computed by this codebase.
- No real voice has ever been generated.
- No real training run has ever executed.
- No ML dependency was installed and no model weights were downloaded
  during this milestone.
- The `SPEAKER_IDENTITY_BOUNDARY` (`pipeline/stages.py`) and the
  synthetic-provenance invariant (`identity/embeddings.py`) are
  unchanged and still enforced — this milestone adds a second,
  honestly-unavailable path alongside the existing synthetic one, and
  does not weaken either guard.

## What would change this

Building and approving one of the environments `configs/default.yaml`
already names (`env-nemo`, `env-tts`) and registering a real subclass of
`EmbeddingProvider`/`VoiceGenerator`/`TrainingProvider` against it. No
part of this milestone's domain layer, contracts, or frontend needs to
change for that to happen — that is the point of the provider boundary.
