# Architecture

> **Phase 0 (this document's original scope) is complete.** The
> repository has since progressed through Phase 1 (environment
> specifications — `env-nemo` built and validated), Phase 2 (dataset
> pipeline, implemented and tested against synthetic audio), and Phase 3
> (speaker identity architecture, including a real, verified embedding
> provider). See the Phase table below,
> [PHASE3_IDENTITY.md](PHASE3_IDENTITY.md), and
> [`PHASE3_CHECKPOINT.md`](../PHASE3_CHECKPOINT.md) for current status.
> Real processing of the private recordings remains gated by
> [`dataset_gate.py`](../src/aarya_voice_lab/pipeline/dataset_gate.py)
> and owner-only prerequisites — nothing below describes that as done.

## Scope boundaries

AARYA Voice Lab is a **standalone** project. It:

- does **not** modify AARYA Core or AARYA Frontend
- does **not** import from, or depend on, either codebase
- does **not** require any cloud service to function

It produces two artifacts for eventual consumption by AARYA Core through
the stable [`VoiceService`](../src/aarya_voice_lab/voice_service.py)
contract: a **Default Voice** model and a **Private Voice** model.

## Design principles

1. **Local-first.** Every capability must work offline. Cloud providers
   may exist only as optional adapters, never as requirements. This is
   enforced concretely — even JSON Schema `$ref` resolution refuses to
   touch the network.
2. **Fail closed.** Ambiguity resolves toward exclusion. An unverifiable
   segment is rejected or sent to review, never accepted.
3. **Provenance over convenience.** Every derived artifact traces back to
   a source recording and timestamp.
4. **Interchangeable providers.** No single diarization, ASR, or TTS
   implementation is baked into the design — partly on principle, partly
   because their dependency constraints make co-installation impossible
   (see [ENVIRONMENT.md](ENVIRONMENT.md)).
5. **Don't build what isn't needed yet.** Phase 0 adds abstraction only
   where a real, identified decision is deferred behind it.

## Module layout

```
src/aarya_voice_lab/
├── __init__.py            # version + SCHEMA_VERSION
├── system_info.py         # hardware/environment detection
├── voice_service.py       # provider-independent VoiceService contract
├── review.py              # manual review data model & queue
├── cli/main.py            # CLI entrypoint
├── core/
│   ├── paths.py           # project root, protected directory registry
│   └── config.py          # YAML config loading
├── security/
│   ├── source_protection.py  # path classification, Git safety scanning
│   └── speaker_policy.py     # conservative speaker eligibility policy
├── pipeline/stages.py     # canonical pipeline stage ordering
├── schemas/
│   ├── base.py            # offline schema loading & validation
│   └── records.py         # validated record builders
└── registry/
    ├── json_registry.py       # JSON Lines registry primitive
    ├── experiment_registry.py
    └── model_registry.py
```

Supporting trees: `schemas/` (JSON Schema definitions), `configs/`,
`manifests/templates/` (synthetic examples), `requirements/`, `docs/`,
`tests/`, and the git-ignored data directories (`source/`, `datasets/`,
`models/`, `experiments/`, `benchmarks/`, `reports/`, `logs/`).

## Why stages communicate through files

The pipeline stages do not call each other in-process. Each reads and
writes **manifest records on disk** conforming to
[`schemas/segment.schema.json`](../schemas/segment.schema.json).

This is a direct consequence of a hard constraint: NeMo and WhisperX pin
incompatible PyTorch versions and **cannot live in the same
interpreter**. A file-based boundary turns that from a blocker into a
non-issue — each stage runs in its own environment, and the manifest is
the contract between them. It also makes every stage independently
resumable, inspectable, and testable with synthetic data.

## Traceability model

Every segment record carries enough provenance to reconstruct where it
came from and how it was judged:

| Field | Answers |
|---|---|
| `source_file_id`, `source_start`, `source_end` | Which recording, and where in it |
| `speaker_id` | Recording-local diarization label |
| `diarization_source`, `diarization_confidence` | Which system decided, how sure |
| `independent_verification_status` | What the second system said |
| `confidence_classification` | Combined HIGH/MEDIUM/LOW judgement |
| `overlap_status` | Whether speakers overlapped |
| `target_speaker_status`, `acceptance_status`, `rejection_reason` | The safety decision and why |
| `processing_version` | Which code version produced this |

`speaker_id` is **recording-local**. Diarization labels like `spk_0` are
assigned per file and carry no meaning across files — the same person may
be `spk_0` in one recording and `spk_1` in another. Global identity comes
only from verification, never from the label.

## Phases

| Phase | Scope | Status |
|---|---|---|
| **0** | Foundation: structure, schemas, safety policy, tooling, docs | **Complete** |
| 1 | Environment build-out: install and validate the ML toolchain | `env-nemo` built and validated — real embedding provider verified (see [REAL_ML_RUNTIME_INTEGRATION.md](REAL_ML_RUNTIME_INTEGRATION.md)); `env-whisperx`/`env-tts` remain not installed, approval-gated |
| 2 | Voice dataset: inventory → validate → normalize → analyze quality → segment → flag overlap → candidate review (speaker-agnostic throughout — diarization was moved *after* this boundary; see [DATASET_PIPELINE.md](DATASET_PIPELINE.md)'s "correction from Phase 0") | Implemented and tested against synthetic audio only; real-data execution is a separate, later gate (below) |
| 3 | Speaker identity architecture / verification | Implemented and tested, including a real (verified) embedding provider — see [PHASE3_IDENTITY.md](PHASE3_IDENTITY.md). Real verification against real recordings is blocked on owner prerequisites, not code |
| 4 | Production voice model + AARYA Core integration | Planned |

Phase 1's ML stack requires **explicit approval** before installing
`env-whisperx`/`env-tts` (`env-nemo` carries no such gate and has already
been built). Phase 2's *architecture* needed no approval to build — it
was implemented and verified entirely against synthetic audio. Touching
the real recordings is a distinct, later gate
(`aarya-voice dataset-gate`, fifteen conditions including explicit human
approval — see
[DATASET_PIPELINE.md](DATASET_PIPELINE.md#the-real-recording-access-gate)),
not a property of "Phase 2" itself.

> A separate, later-established step — real-recording access and
> processing, gated by `aarya-voice dataset-gate` — is also referred to
> as "Phase 4" elsewhere in the repository (see
> [`PHASE3_CHECKPOINT.md`](../PHASE3_CHECKPOINT.md)'s roadmap). It
> precedes this table's Phase 4 in sequence. This table's original
> phase/scope descriptions are preserved rather than renumbered.

## Deliberate non-goals for Phase 0

- No audio processing of any kind
- No model training, fine-tuning, or inference
- No AARYA Core/Frontend integration
- No cloud provider integration
- No populated dataset directories
- No abstraction layers for decisions that haven't been identified yet
