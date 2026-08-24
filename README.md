# AARYA Voice Lab

Standalone, **local-first** research and engineering project for AARYA's
voice system.

> **Status: Phase 3 — Speaker Identity Architecture, with a real embedding
> provider implemented and verified.** The identity architecture —
> embedding provider abstraction, pluggable enrollment, speaker profiles,
> verification engine, calibration states, identity review, append-only
> audit log, and the real-recording access gate (15 conditions,
> fail-closed) — is implemented and tested. A deterministic synthetic
> embedding provider is always available for development; a real provider
> (NVIDIA NeMo TitaNet-large, subprocess-isolated) is also implemented and
> has been verified end-to-end, computing real embeddings from synthetic
> (sine-tone) audio. It requires a locally built `.envs/env-nemo`
> environment, which is **not built on every checkout** — see
> [Testing](#testing) for exactly what that means for this repository's
> test results.
>
> **No real (private) recording has ever been accessed. No training has
> occurred. No cloud voice API is used.** Every artifact a provider
> produces is stamped synthetic or real accordingly, so a development
> result can never be read as a real identity conclusion. Real Phase 4
> processing of the actual private recordings remains gated on a human
> enrollment-methodology decision and a manually recorded operator
> reference sample — see [`docs/PRIVACY.md`](docs/PRIVACY.md).

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
| Test suite | Implemented — 808 passed, 0 failed, 5 skipped (see [Testing](#testing)) |
| `VoiceService` interface contract | Defined; a real embedding provider is implemented, generation/training remain unimplemented |
| NeMo embedding environment (`env-nemo`) | Implemented, verified — **not built on this checkout** (5 tests skip; see [Testing](#testing)) |
| WhisperX / TTS environments | **Specified, NOT installed** — approval-gated |
| Model weights | **None downloaded on this checkout** — TitaNet-large weights are fetched automatically when `env-nemo` is built |
| Dataset candidate pipeline (Phase 2) | Implemented — synthetic audio only |
| Speaker identity architecture (Phase 3) | Implemented, including a real (non-synthetic) embedding provider |
| Real speaker verification against real recordings | **Not performed** — no real recording has ever been accessed; gated by [`docs/PRIVACY.md`](docs/PRIVACY.md) |
| Real-recording access gate (`dataset-gate`) | Implemented — 15 fail-closed conditions (operator enrollment, real embedding provider, model-licence review, + 12 prior) |
| Cross-vendor, cross-OS GPU detection | Implemented — NVIDIA/AMD/Intel on Linux and Windows; verified on real Intel hardware |
| Native Windows backend support | Implemented — cross-platform file locking, canonical path serialization; backend suite passes cleanly on native Windows |
| Desktop UI (VL-D0–VL-D20 series) | Implemented — see [Documentation](#documentation) below |
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
source .venv/bin/activate     # Windows: .venv\Scripts\activate
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
aarya-voice voice-engine-status      # Real Voice Model Engine provider capability states

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
pytest        # 808 passed, 0 failed, 5 skipped
ruff check .
```

The 5 skips require a real embedding provider (`.envs/env-nemo`, NVIDIA
NeMo TitaNet-large) built locally — optional infrastructure, not part of
this repository. Skipping is the correct, honest outcome when it isn't
built; it is never reported as a pass. See [NEMO.md](docs/NEMO.md) to
build it. Verified clean on native Windows as well as Linux.

No test uses, references, or requires the real (private) recordings.

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
| [VLD1_COMMAND_CENTER.md](docs/VLD1_COMMAND_CENTER.md) | VL-D1 operational workspace: routing, job/activity model, Command Center, Claude context & fix workflow, security boundary |
| [VLD2_DATASET_WORKSPACE.md](docs/VLD2_DATASET_WORKSPACE.md) | VL-D2 bulk import: content-addressed intake, dataset gate, client-side hashing, Dataset Workspace UI, security boundary |
| [VLD3_DATASET_REVIEW.md](docs/VLD3_DATASET_REVIEW.md) | VL-D3 dataset review & quality analysis: candidate review, feedback, overlap candidates, Dataset Review UI, speaker-identity boundary |
| [VLD4_VOICE_PROCESSING.md](docs/VLD4_VOICE_PROCESSING.md) | VL-D4 voice processing & conditioning: processing profiles, boundary trim, normalization, derived-artifact identity, rollback, Processing UI |
| [VLD5_VOICE_PREVIEW.md](docs/VLD5_VOICE_PREVIEW.md) | VL-D5 voice preview & generation: generation backends, voice profiles, preview queue, history, listened-before-decision feedback, A/B comparison, Preview UI |
| [VLD6_VOICE_FEEDBACK.md](docs/VLD6_VOICE_FEEDBACK.md) | VL-D6 voice feedback & human evaluation: dimension scoring, listening state, multi-reviewer disagreement, A/B evaluation, calibration-prep boundary, Feedback UI |
| [VLD7_AI_CALIBRATION.md](docs/VLD7_AI_CALIBRATION.md) | VL-D7 AI Calibration Engine: run-state vs evidence-state, hardware snapshot, bounded parameter adjustments, versioned profiles, rollback, Calibration UI |
| [VLD8_CALIBRATION_APPLICATION.md](docs/VLD8_CALIBRATION_APPLICATION.md) | VL-D8 Calibration Application & Validation Loop: application_state axis, bounded generation-queue concurrency, real before/after batch-count measurement, honest NOT_MEASURABLE |
| [VLD9_SESSION_PERSISTENCE.md](docs/VLD9_SESSION_PERSISTENCE.md) | VL-D9 Local Session Persistence: versioned localStorage envelopes, per-store hydrate()/export, excluded-field safety review, automatic save, explicit Clear session data, honest persistence indicators |
| [VLD10_CLAUDE_COMMAND_CENTER_BRIDGE.md](docs/VLD10_CLAUDE_COMMAND_CENTER_BRIDGE.md) | VL-D10 Claude Command Center Bridge: live read-only command_center_snapshot() wiring, real repository/activity/diagnostics/command-catalogue/verification data, honest missing/malformed handling — no execution transport |
| [VLD11_IDENTITY_STATUS_BRIDGE.md](docs/VLD11_IDENTITY_STATUS_BRIDGE.md) | VL-D11 Identity Status Bridge: evidence-based D11 audit, desktop_snapshot() wired to a new Claude Command Center panel, fixes a real hardcoded `real_provider_installed: False` defect found live in D10's own diagnostics payload |
| [VLD12_MODEL_REGISTRY_BRIDGE.md](docs/VLD12_MODEL_REGISTRY_BRIDGE.md) | VL-D12 Model Registry Bridge: evidence-based D12 audit, real (non-synthetic) model registry entries wired to the Models workspace, `private_voice` entries permanently excluded at the source per docs/SECURITY.md |
| [VLD13_RUNTIME_CAPABILITY_BRIDGE.md](docs/VLD13_RUNTIME_CAPABILITY_BRIDGE.md) | VL-D13 Runtime Capability Bridge: evidence-based D13 audit, `runtime_capabilities()` now declares the real embedding provider's capability only when genuinely installed, `desktop_snapshot()`'s previously-unrendered runtime/embeddings/preview payloads now render honestly in the Claude Command Center |
| [VLD14_IDENTITY_ENROLLMENT_CAPABILITY_COMPLETENESS.md](docs/VLD14_IDENTITY_ENROLLMENT_CAPABILITY_COMPLETENESS.md) | VL-D14 Identity Enrollment Capability Completeness Bridge: real `enrollment.available_strategies` / `available_providers` wired into the Identity panel |
| [VLD15_PIPELINE_BATCH_VISIBILITY_BRIDGE.md](docs/VLD15_PIPELINE_BATCH_VISIBILITY_BRIDGE.md) | VL-D15 Pipeline Batch Visibility Bridge: real on-disk `pipeline.batches` wired into the Identity panel |
| [VLD16_ENROLLMENT_ROLE_STATE_BREAKDOWN_BRIDGE.md](docs/VLD16_ENROLLMENT_ROLE_STATE_BREAKDOWN_BRIDGE.md) | VL-D16 Enrollment Role/State Breakdown Bridge: real `enrollment.by_state` / `by_role` breakdowns wired into the Identity panel |
| [VLD17_VOICE_ENGINE_CAPABILITY_DETAIL_BRIDGE.md](docs/VLD17_VOICE_ENGINE_CAPABILITY_DETAIL_BRIDGE.md) | VL-D17 Voice Engine Capability Detail Bridge: real training-provider and embedding-provider detail/missing-requirements wired into the Models workspace |
| [VLD18_INDICF5_CAPABILITY_HONESTY_BRIDGE.md](docs/VLD18_INDICF5_CAPABILITY_HONESTY_BRIDGE.md) | VL-D18 IndicF5 Capability Honesty Bridge: voice-generation capability detection corrected to IndicF5's real dependencies and HuggingFace gating; no generation implemented |
| [VLD19_WINDOWS_GPU_DETECTION.md](docs/VLD19_WINDOWS_GPU_DETECTION.md) | VL-D19 Windows GPU Presence Detection: closes the Windows detection gap via WMI (`Win32_VideoController`), verified on real Intel hardware |
| [VLD20_PORTABLE_RUNTIME_AUDIT.md](docs/VLD20_PORTABLE_RUNTIME_AUDIT.md) | VL-D20 Portable Runtime Discovery and Audit: read-only hardware-independence audit across the runtime stack; corrected stale documentation, no code defect found |
| [FE1_FRONTEND_POLISH.md](docs/FE1_FRONTEND_POLISH.md) | FE-1 frontend polish pass: Shadow-DOM design-token delivery fix, shared confirmation dialog, responsive desktop shell, real SVG icons, shared CSS utilities, visual identity pass, zero-dependency visual regression harness, real accessibility audit |
| [FE2_VISUAL_REDESIGN.md](docs/FE2_VISUAL_REDESIGN.md) | FE-2 visual redesign pass: denser dashboard stat-tile/icon-badge/meter primitives, real-data-only headline tiles on Command Center and 6 other workspaces, no fabricated hardware gauges or user identity |
| [FE3_VISUAL_SYSTEM.md](docs/FE3_VISUAL_SYSTEM.md) | FE-3 Aarya glass surface system: restrained translucent panel/card/dialog/shell tokens, focus-only accent glow, real-data stat tiles for 4 more workspaces, WCAG AA contrast audit, light/dark theme hardening |
| [FE4_FINAL_COMPLETION.md](docs/FE4_FINAL_COMPLETION.md) | FE-4 through FE-10 final frontend completion: 4-agent whole-app audit, fabricated-status/hardcoded-metric fixes, 5 listener-leak fixes, 2 keyboard-accessibility fixes, dashboard/heading consistency, per-keystroke performance fixes, real Chromium + regression verification |
| [REAL_VOICE_MODEL_ENGINE.md](docs/REAL_VOICE_MODEL_ENGINE.md) | Real Voice Model Engine milestone: real (honestly NOT_CONFIGURED) embedding/generation/training provider architecture, training job lifecycle, training-readiness assessment, model lifecycle + checksum-addressed artifacts, multilingual-ready contracts |
| [REAL_ML_RUNTIME_INTEGRATION.md](docs/REAL_ML_RUNTIME_INTEGRATION.md) | Real ML Runtime & Model Integration milestone: real NeMo TitaNet-large speaker embedding (env-nemo, subprocess-isolated), model decision/license/language audit, deferred voice generation (IndicF5 HuggingFace-gated blocker), checksum-addressed artifact + registry provenance, measured performance |
| [HARDWARE_AGNOSTIC_GPU_DETECTION.md](docs/HARDWARE_AGNOSTIC_GPU_DETECTION.md) | Closes the VL-D7-documented NVIDIA-only detection gap: vendor-neutral GPU presence detection (NVIDIA/AMD/PCI-sysfs), new `Accelerator (any vendor)` capability, honest detection-vs-execution boundary |
| [TOOLCHAIN.md](docs/TOOLCHAIN.md) | Provider abstraction & candidate tools |
| [MODEL_STRATEGY.md](docs/MODEL_STRATEGY.md) | Model registry, experiments, TTS candidates |
| [BENCHMARKING.md](docs/BENCHMARKING.md) | Voice quality benchmark framework |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md) | Contributing, Git safety workflow |

## License

See [LICENSE](LICENSE). Note that the license covers this **code only** —
it grants no rights whatsoever to the private recordings, any dataset
derived from them, or the Private Voice model.
