# VL-D7 — AI Calibration Engine

AARYA Voice Lab only. Not a JARVIS milestone; nothing in this phase touches
Aarya Core or any other project.

VL-D7 is the "future AI Calibration Engine" every earlier phase (VL-D1,
VL-D3, VL-D5, VL-D6, and Phase 3's `identity.calibration`/`identity.runtime`)
prepared a place for but never built. It reads the raw counts those phases
already collect, detects this host's capabilities through the probes
`environment.audit` already runs, and produces a versioned, append-only
`CalibrationProfile` — honestly reporting insufficient evidence far more
often than it reports anything else.

## Why this is not a second calibration system

Two calibration-shaped things already existed before VL-D7:

* `identity.calibration.CalibrationState` (`UNCALIBRATED`/`PROVISIONAL`/
  `CALIBRATED`) — whether a **target-speaker verification threshold** has
  real, held-out evidence behind it. `CALIBRATED` is unreachable for the
  target speaker by construction (see that module's own docstring).
* The `hardware_calibration` frontend status domain — reserved since
  VL-D1 for "the future AI Calibration Engine's process state," six
  values (`UNCALIBRATED`/`NOT_TESTED`/`CALIBRATING`/`CALIBRATED`/
  `FAILED`/`UNKNOWN`), never backed by real state until now.

VL-D7 does not duplicate either. It **reuses** `CalibrationState` unchanged
as the evidence axis of a `CalibrationProfile`, and it **implements**
`CalibrationRunState` — a new backend enum with the exact same six values
the frontend already reserved — as the process axis. `pipeline.calibration_engine`
is genuinely new because nothing before it assessed readiness, selected a
strategy, proposed a bounded parameter, or persisted a versioned,
rollback-capable profile; `pipeline.calibration_prep` (VL-D3/VL-D5/VL-D6)
already did the counting this phase reads, and is not re-implemented.

## The central honesty rule: two independent axes

```
CalibrationRunState        — did the engine's own run finish?
identity.calibration.CalibrationState — is there real evidence behind the result?
```

A successful run (`run_state=CALIBRATED`) paired with `calibration_state=
UNCALIBRATED` or `calibration_state=PROVISIONAL` is the **expected, honest
outcome** whenever evaluation evidence is thin or absent — not a bug, and
never hidden or merged in the UI. `calibration_state=CALIBRATED` is never
produced by this engine: it requires labelled held-out data this project
does not have, for exactly the reason `identity.calibration`'s own
docstring gives. Every `CalibrationProfile` this engine ever writes has
`calibration_state` in `{UNCALIBRATED, PROVISIONAL}` only — enforced
structurally by reusing `identity.calibration.CalibrationRecord`'s own
`__post_init__` guard, not by a separate check here.

## Scope boundary (absolute)

VL-D7 is calibration-engine **software** only:

* No real recordings are accessed. `pipeline.calibration_engine` never
  imports `DataRoot` and never reaches `data_root.source`.
* No embeddings are generated, no model is trained, no speaker identity
  is inferred or stored. `CalibrationProfile` has no field that could
  carry one — the same "structurally cannot express it" pattern as
  `VoiceProfile` (VL-D5) and `Evaluation` (VL-D6).
* No dataset-access gate is touched, bypassed, or weakened.
* Bounded parameter adjustments in this phase are **hardware/runtime
  performance parameters only** (currently: recommended generation
  concurrency, derived from detected CPU core count). No voice-quality
  parameter is ever adjusted automatically — that would require calibrated
  quality evidence this project does not have, and proposing one anyway
  would be exactly the fabricated-improvement claim this project must
  never make.
* Hardware-agnostic: no RTX/NVIDIA/CUDA-specific architecture. See
  "Hardware abstraction" below for the honest limit of what is actually
  detected today.

## Backend

### `pipeline.calibration_engine` — the engine itself

* `CalibrationRunState` — `UNCALIBRATED`/`NOT_TESTED`/`CALIBRATING`/
  `CALIBRATED`/`FAILED`/`UNKNOWN`. Mirrors the frontend's
  `hardware_calibration` domain exactly. `CALIBRATING` is a UI-facing
  transient state; `run_calibration()` is synchronous and only ever
  returns a terminal state.
* `CalibrationStrategy` — `NONE` (no run attempted, or hardware capture
  failed), `HARDWARE_ONLY` (evidence insufficient — hardware-derived
  parameters only), `HARDWARE_AND_FEEDBACK` (enough reviewer-feedback
  evidence to also reach `PROVISIONAL` evidence — never `CALIBRATED`).
* `HardwareSnapshot.capture()` — reads `environment.audit.run_audit()`
  and `system_info.collect_system_report()`; adds no new probe.
  `detected_backend` is `None`, not `ComputeBackend.CPU`, when no
  accelerator is confirmed present — on non-NVIDIA hardware that is an
  honest "not confirmed," not a verified fact (see "Hardware
  abstraction").
* `CalibrationParameterAdjustment` — `parameter_name`, `previous_value`,
  `proposed_value`, `min_bound`, `max_bound`, `rationale`,
  `evidence_reference`, all required. `__post_init__` refuses a proposal
  outside its own declared bounds (`ParameterBoundsError`) or with
  inverted bounds — never silently clamped.
* `propose_hardware_adjustments()` — the one adjustment this phase
  proposes: `max_concurrent_generations`, bounded `[1, 8]`, derived from
  `HardwareSnapshot.logical_cores`.
* `assess_readiness()` — reads the already-computed
  `EvaluationCalibrationInputSummary`/`PreviewCalibrationInputSummary`
  from `pipeline.calibration_prep`; never re-derives a count.
  `MIN_EVIDENCE_FOR_PROVISIONAL = 2`, mirroring
  `pipeline.evaluation_aggregation.MIN_EVALUATIONS_FOR_DISAGREEMENT` —
  below that, "sufficient evidence" isn't a meaningful statement either.
* `select_strategy()` — `HARDWARE_ONLY` below the evidence threshold,
  `HARDWARE_AND_FEEDBACK` at or above it.
* `run_calibration()` — the orchestrator. Captures a hardware snapshot,
  assesses readiness, selects a strategy, proposes adjustments, and —
  only when evidence is sufficient — calls
  `identity.calibration.provisional_from_reviewer_feedback()` with a
  **real, computed** agreement rate (via
  `pipeline.evaluation_aggregation.outputs_with_disagreement`, never a
  fabricated number). This is the exact call VL-D6 built and
  deliberately left for "a future, explicitly-approved phase" — this is
  that phase. A hardware-capture failure produces `run_state=FAILED`
  and an honest `UNCALIBRATED` evidence state; it never raises past the
  caller.
* `CalibrationProfile` / `CalibrationProfileLog` — frozen, versioned,
  append-only via `JsonLinesRegistry` (same pattern as
  `candidate_review`, `processing_history`, `preview_history`,
  `evaluation`). `DataRoot.calibration` is the new (additive) subdirectory
  these profiles live under, mirroring `DataRoot.previews`.
* `rollback()` — appends a new record reinstating a prior profile's
  content as active, with `supersedes`/`is_rollback=True` — the exact
  pattern `pipeline.processing_history.rollback()` established. Never
  deletes or mutates history.

### What was *not* rebuilt

`identity.calibration`, `identity.runtime`, `core.capability`,
`system_info`, `environment.audit`, `pipeline.calibration_prep`,
`pipeline.quality_summary`, `pipeline.evaluation_aggregation`,
`registry.json_registry.JsonLinesRegistry` — all reused exactly as they
stood before this phase. `identity.calibration` itself was not modified.

### `VL-D15` → `VL-D7`

Nine backend/frontend/doc comments and one JSON Schema description
referred to "the future AI Calibration Engine (VL-D15)" — a stale
forward-reference from when this milestone's number hadn't been fixed
yet. All corrected to `VL-D7` (the number every phase's own final report
had already converged on). Historical narrative in earlier phase docs
(VL-D0/VL-D1/VL-D5/VL-D6/PHASE3_IDENTITY) was left otherwise untouched —
only the misnumbered forward-reference was corrected, per the approved
audit decision.

### Schemas

`schemas/calibration_profile.schema.json` — draft-07,
`additionalProperties: false` throughout including the nested
`hardware_snapshot`/`adjustments`/`evidence_counts` objects, required
list matching `CalibrationProfile.to_dict()` exactly. Registered as
`SchemaName.CALIBRATION_PROFILE`.

## Frontend

### `state/calibration-engine-model.js` — the session-only simulation

Mirrors the backend module exactly, including the run-state/evidence-state
independence rule and the never-`CALIBRATED`-evidence guarantee.
`captureHardwareSnapshot()` reads only what a browser can honestly report
(`navigator.hardwareConcurrency`, `navigator.deviceMemory` where
available) plus a supplied `Capability[]` fixture
(`syntheticHardwareCapabilities()` in `synthetic-fixtures.js`) — never a
fabricated measurement. `CalibrationProfileStore` is session-only, like
every other VL-D5/VL-D6 store: there is still no execution transport to
persist a profile beyond the session.

### New components

`avl-calibration-run-panel` (the two badges, side by side, deliberately
never merged), `avl-calibration-readiness-panel`, `avl-calibration-parameter-adjustments`,
`avl-calibration-profile-history` (list + rollback, mirrors
`avl-processing-history-panel` exactly), `avl-claude-calibration-context`
(bounded, reuses `buildReviewClaudeContext`).

### `avl-workspace-calibration` — three panels, clearly separated

1. **AI Calibration Engine** (new) — run panel, readiness, proposed
   adjustments, profile history/rollback, Ask Claude.
2. **Hardware capabilities** — `avl-hardware-profile-card`, built in
   VL-D0 and never wired to real data until now, now fed the same
   `Capability[]` fixture the engine itself reads.
3. **Target-speaker verification calibration** — `avl-calibration-panel`,
   completely unchanged.

### Command Center, Activity, Claude

A new "Calibration engine" overview panel (run state, evidence state,
strategy, agreement rate, profile-run count, adjustment count — every
number real or "not available," never fabricated). The Feedback panel's
previously-hardcoded `UNCALIBRATED` "Calibration prep" badge now reads
the real current profile's evidence state. `ActivitySource.CALIBRATION`
(declared in VL-D1, unused until now) gets one event per run/rollback.

## Security boundary

* `pipeline.calibration_engine` never imports `DataRoot`, never reaches
  `data_root.source`/`.embeddings`/`.enrollment` — verified by a
  structural source-inspection test, not just an assertion.
* No specific GPU product name (RTX/GTX/GeForce/Radeon/a model number)
  appears anywhere in the module.
* `CalibrationProfile` carries no `speaker_id`/`target_speaker`/`voice_id`/
  `embedding`/`speaker_name` field — verified directly on a real
  produced record, both backend and frontend.
* No cloud storage, no network call, no arbitrary command execution —
  `claude-calibration-context.js` routes through the same
  `NullCommandExecutor` boundary every prior phase uses.

## Hardware abstraction

`identity.runtime.ComputeBackend`/`AccelerationRequirement`/
`RuntimeCapability` supply the vendor-neutral vocabulary; nothing in
`calibration_engine` branches on a vendor name — only on
`CapabilityState`/`ComputeBackend` values. The honest limit, stated
plainly rather than hidden: `environment.audit.check_gpu()` today only
actively probes for NVIDIA hardware via `nvidia-smi`. An AMD, Intel, or
Apple accelerator is architecturally representable (`ComputeBackend` has
`ROCM`/`METAL`/`OPENCL`/`VULKAN`/`XPU`/`OTHER` precisely so it needs no
schema change later) but is **not yet actively detected** — `HardwareSnapshot`
reports this limitation verbatim (`HARDWARE_DETECTION_LIMITATION`) rather
than reporting "no accelerator" as a confirmed fact on non-NVIDIA hardware.
`accelerator_confirmed=False` therefore means "not confirmed," never
"confirmed absent."

## Testing

* Backend: 34 new tests (`tests/test_calibration_engine.py`) — zero/single/
  sufficient evidence, strategy selection, hardware snapshot honesty
  (including the CPU-only and CUDA-confirmed paths), bounded-parameter
  acceptance/rejection, run-state/evidence-state independence, profile
  versioning, append-only history, rollback (including unknown-target),
  provenance, schema validation, and the security/vendor-hardcoding
  checks above. Full backend regression: 679/679 passing.
* Frontend: 18 new state tests (`calibration-engine-state.test.mjs`) +
  14 new real-browser Playwright scenarios (`calibration.test.mjs`) —
  open workspace, honest empty state, zero-evidence run, readiness
  display, bounded-adjustment display, append-only history, rollback,
  reaching `PROVISIONAL` after real evaluation evidence, Command Center,
  Activity, Claude context, light theme, dark theme, no console errors.
  Full frontend regression: 227/227 passing (195 baseline + 32 new).

## Known limitations

* Accelerator detection is NVIDIA-only in practice today (see "Hardware
  abstraction") — an honest, stated limit of `environment.audit`, not
  something this phase silently works around.
* The only parameter this phase adjusts is generation concurrency,
  derived from CPU core count. No other runtime parameter is calibrated
  yet, and no voice-quality parameter is calibrated at all.
* `agreement_rate` is a real ratio, never a confidence interval or a
  statistical-significance claim — consistent with VL-D6's own honesty
  rule for small samples.
* The engine is session-only in the frontend (no execution transport to
  persist a profile beyond the browser session), same limitation every
  prior phase's stores share.
* `calibration_state` can never reach `CALIBRATED` in this project for
  the target speaker — this is a property of the data, not a gap this
  phase or any future one can close by better code.

## Next

**VL-D8** — not yet defined. VL-D7 completes the calibration-engine
infrastructure line every prior phase referenced; the next milestone is
open for scoping.
