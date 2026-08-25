# VL-D20 — Portable Runtime Discovery and Audit

AARYA Voice Lab only. Continues the "portable runtime / hardware
independence" theme (`VL-D19/D20`) VL-D19 began closing.

## What VL-D20 Actually Means

No repository document defines a "VL-D20" specification. A full-repository
search (mirroring VL-D19's own discovery process) found the same six
pre-existing references VL-D19 already catalogued, plus one new,
decisive one found this audit:

`identity/runtime.py:181` — `describe_portability()`'s own docstring:
*"Used by **future packaging (VL-D20)** to answer 'can this be shipped
to a machine with no GPU?'"*

Read together with VL-D19's own scope (**runtime detection**), the
repository's own evidence is that **VL-D19 = detection, VL-D20 =
packaging/deployment** — using already-declared portability data to make
a real shipping decision, not more detection work.

## Audit Findings

Traced the full capability path: `system_info` → `environment.audit` →
`core.capability` → `pipeline.calibration_engine` → `identity.runtime`.

- **NVIDIA / AMD / Intel / integrated / discrete detection**: real,
  vendor-neutral, working (`system_info.get_gpu_info()`). Confirmed live
  on this machine's real Intel Iris Xe GPU (VL-D19), and by pre-existing
  mocked tests for NVIDIA/AMD.
- **CPU-only support**: the documented, tested baseline
  (`docs/GPU_STRATEGY.md`'s "situation A") — every architectural check
  (`environment.audit`) treats GPU absence as `OPTIONAL`, never blocking.
- **Windows / Linux**: both now handled in detection (VL-D19 closed the
  Windows gap; sysfs continues to cover Linux). No other OS-specific
  branch exists anywhere in the capability path.
- **Calibration integration**: `pipeline.calibration_engine.HardwareSnapshot.capture()`
  reads `environment.audit`/`system_info` through the same
  `CapabilityState`-shaped abstraction regardless of *which* detection
  method produced the result — confirmed by inspection and by a
  pre-existing test (`test_hardware_snapshot_confirms_non_nvidia_accelerator_as_other_backend`)
  that already covers "a non-NVIDIA accelerator, however detected, must
  set `accelerator_confirmed=True` and `detected_backend=OTHER`." **VL-D19
  required zero changes here** — the abstraction boundary already made
  it detection-method-agnostic by design.
- **Execution/runtime selection**: traced whether any real execution path
  reads detected capability and *acts* on it.
  `identity.embeddings.LocalNeuralEmbeddingProvider` (the one real ML
  execution path this project has) and its worker script
  (`scripts/ml_workers/nemo_embedding_worker.py`) contain **zero**
  references to CUDA, device, GPU, or accelerator selection — confirmed
  by direct search. This is documented, intentional
  (`docs/REAL_ML_RUNTIME_INTEGRATION.md`: "only ever verified on CPU"),
  not a defect: `identity.runtime.RuntimeCapability` declarations are
  **software-component-level, static, and self-declared** (what a
  component *claims* about itself), entirely separate from
  `system_info`/`environment.audit`'s **live, per-machine** detection.
  Nothing currently wires the two together — because nothing in this
  project yet needs to: there is exactly one real inference path, it is
  CPU-only by verified design, and no component has ever needed to
  branch on detected hardware to decide *how* to run.
- **`describe_portability()`**: pure aggregation over the static
  `RuntimeCapability` declarations (currently `SYNTHETIC_PROVIDER_CAPABILITY`,
  `VERIFICATION_ENGINE_CAPABILITY`, conditionally
  `LOCAL_NEURAL_EMBEDDING_CAPABILITY`) — answers "do all currently-known
  *software components* declare CPU-only viability," which is
  orthogonal to "does *this machine* have a GPU." Both axes are real and
  correctly kept separate; this is not a defect.

## Gaps Found

- **Genuine defects**: none found beyond what VL-D19 already fixed.
- **Missing functionality**: an actual packaging/deployment mechanism
  that *consumes* `describe_portability()`'s answer to make a real
  shipping decision does not exist — but neither does any packaging/
  distribution system at all in this project (no installer, no bundler,
  no "build for distribution" step of any kind). Building one now would
  be inventing new architecture with no existing scaffolding to extend,
  which the approved scope explicitly rules out ("does not introduce
  unnecessary architecture").
- **Intentional limitations**: `LocalNeuralEmbeddingProvider` not reading
  detected hardware to select a device is intentional and correctly
  documented, not a gap to close — there is nothing today for it to
  select between (one real path, CPU-only, verified as such).
- **Documentation-only gaps** (the genuine, actionable finding):
  `docs/GPU_STRATEGY.md`'s "Not verified" section claimed *"no AMD or
  Intel GPU was available on any machine this project has run on"* —
  **false** as of VL-D19, which verified a real Intel GPU on real
  hardware. `pipeline.calibration_engine.HARDWARE_DETECTION_LIMITATION`
  (and its frontend mirror in `calibration-engine-model.js`) cited only
  `nvidia-smi`/`rocm-smi`/sysfs as detection methods, omitting VL-D19's
  Windows WMI path. `docs/HARDWARE_AGNOSTIC_GPU_DETECTION.md` had no
  forward pointer to the milestone that closed the gap it described,
  unlike this project's established convention (e.g. VL-D10's doc
  pointing to VL-D11).

## VL-D20 Scope Decision

**Documentation-accuracy correction only. No code-level architectural
change was justified.**

Ranked against the approved criteria: a real packaging/deployment
milestone would score high on "directly follows VL-D19" and "exists in
the architecture's stated direction," but fails "does not introduce
unnecessary architecture" and "minimal scope" — there is no existing
packaging mechanism to extend, and inventing one from nothing is exactly
the kind of speculative scope this project's established discipline
rejects. The documentation corrections, by contrast, are small, entirely
evidence-backed by VL-D19's own real-hardware verification, carry zero
implementation risk, and keep this project's honesty-first standard
intact (a value this project has enforced in every prior milestone).

## Implementation

- `docs/GPU_STRATEGY.md` — "Not verified" section corrected: AMD
  detection remains real-hardware-unverified; Intel GPU *presence*
  detection is now verified real (cites VL-D19 directly); GPU
  *execution* remains unverified for both, unchanged.
- `docs/HARDWARE_AGNOSTIC_GPU_DETECTION.md` — new "## Update" section
  pointing to VL-D19, matching the established cross-referencing
  convention (e.g. `docs/VLD10_CLAUDE_COMMAND_CENTER_BRIDGE.md`'s own
  "Next" section).
- `src/aarya_voice_lab/pipeline/calibration_engine.py` —
  `HARDWARE_DETECTION_LIMITATION` now also names the Windows WMI
  detection path alongside `nvidia-smi`/`rocm-smi`/sysfs.
- `frontend/state/calibration-engine-model.js` — the same
  `HARDWARE_DETECTION_LIMITATION` string updated identically, preserving
  this project's established backend/frontend text-mirroring convention.

No test was added: the only pre-existing test asserting this string's
content (`test_hardware_snapshot_assembly_reuses_environment_audit`,
`assert "nvidia-smi" in snapshot.limitation.lower()`) continues to hold,
since `"nvidia-smi"` remains present — confirmed by inspection.

## Verification

| Check | Kind | Result |
|---|---|---|
| VL-D19 GPU detection re-run on this machine | **Real hardware** | PASS — `available=True, vendor="Intel", detection_method="windows-wmi"`, unchanged from VL-D19 |
| `node --test tests/calibration-engine-state.test.mjs` | **Automated, executed** | **34/34 PASS** — the frontend calibration-engine unit suite runs natively (pure JS, no Playwright) and fully passed |
| `node --test tests/*.test.mjs` (full frontend suite) | **Automated, executed** | 426 tests, 200 pass, 226 fail — identical to the post-VL-D19 baseline; zero regression |
| `node tools/build-css-variables.mjs --check` | **Automated, executed** | PASS |
| `python -m py_compile` on both modified `.py` files | **Static** | PASS |
| `node --check` on the modified `.js` file | **Static** | PASS |
| Backend `pytest` (`test_hardware_snapshot_assembly_reuses_environment_audit` and siblings) | **Automated, executed** *(closed since original writing — see Verification Update)* | 4/4 hardware-snapshot tests pass for real, plus the full suite. Originally blocked by `.venv`'s broken symlink and `core.file_lock`'s then-unconditional `fcntl` import; verified only by direct inspection at the time. |

## Verification Update

`core.file_lock`'s Windows-portability fix (`75933a1`, landed after this
milestone, independently of VL-D19/D20) removed the `fcntl`-import
blocker that had prevented `pytest` from running on native Windows at
all. With that gap closed, the exact cited test and its three siblings
in the same "hardware snapshot" group were run for real:
`test_hardware_snapshot_assembly_reuses_environment_audit`,
`test_hardware_snapshot_never_claims_confirmed_accelerator_without_evidence`,
`test_hardware_snapshot_cuda_confirmed_only_when_both_gpu_and_cuda_available`,
`test_hardware_snapshot_confirms_non_nvidia_accelerator_as_other_backend`
— **4/4 passed**, confirming the inspection-only claim this table
originally recorded (`"nvidia-smi" in snapshot.limitation.lower()`
holds). The full suite was also run for real: **986 passed, 5 skipped,
0 failed**, identical to the VL-D19 baseline — zero regressions. `ruff
check .` passes project-wide. No production code was changed to close
this gap; `HARDWARE_DETECTION_LIMITATION` already named the Windows WMI
path exactly as this milestone originally implemented it.

## VL-19 Regression

Confirmed intact — re-executed live on this machine (see table above);
`system_info.py` was not touched by this milestone.

## Explicit Non-Scope

No RTX-3050-specific logic was added anywhere. No CUDA/NVIDIA-specific
architecture was introduced. No packaging/deployment system was built.
`identity.runtime`'s `RuntimeCapability` vocabulary, `describe_portability()`,
and the D13 runtime-capability bridge are unchanged. `LocalNeuralEmbeddingProvider`
and its worker script are unchanged.
