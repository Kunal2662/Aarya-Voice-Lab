# Hardware-Agnostic GPU Detection

**Status: GPU *presence* detection is now real and vendor-neutral. GPU
*execution* remains NVIDIA-only — detecting a device and being able to
run something on it are two different, separately-tracked claims.**

## Where this came from

This is not a new named milestone from the project's own numbered
roadmap (VL-D0–D10, FE-1–FE-10, Hardening, Real ML Architecture, Real ML
Runtime). It closes a specific, real gap found during a current-state
audit of the repository at commit `b201836`: `system_info.get_gpu_info()`
only ever probed for NVIDIA hardware via `nvidia-smi`, silently reporting
"no GPU" on any machine whose only accelerator was AMD or Intel — a
direct violation of this project's own hardware-agnostic principle.

Critically, this gap was not hidden. `pipeline/calibration_engine.py`'s
own module docstring and `HARDWARE_DETECTION_LIMITATION` constant
(written during VL-D7) already disclosed it verbatim: *"GPU check today
only actively probes for NVIDIA hardware via nvidia-smi... AMD, Intel,
and Apple accelerators are architecturally representable... but not yet
actively detected."* `identity.runtime.ComputeBackend` already carried
`ROCM`/`METAL`/`OPENCL`/`VULKAN`/`XPU`/`OTHER` members specifically so
this could be closed later without a schema change. This work closes it.

## What changed

### Detection (`system_info.py`)

`get_gpu_info()` now tries, in order:

1. **NVIDIA** via `nvidia-smi` (unchanged from before — still the first
   check, because `scripts/install_env.sh`'s CUDA-vs-CPU torch wheel
   index decision genuinely depends on this exact signal).
2. **AMD** via `rocm-smi --showproductname --json`, when `nvidia-smi`
   was not found at all (not when it was found but errored — a broken
   NVIDIA tool on what is presumably an NVIDIA machine is a real signal
   worth surfacing directly, not something to paper over by silently
   trying another vendor).
3. **Any vendor**, via a PCI-id enumeration under `/sys/class/drm` —
   works even with zero vendor tools installed, which is what actually
   makes "no GPU detected" honest on a machine whose only accelerator is
   AMD or Intel with no `rocm-smi`/`intel_gpu_top` present. Presence-only:
   no driver/VRAM/model detail is available this way, and the result says
   so (`note="presence-only detection via PCI vendor ID..."`).

`GPUInfo` gained a `vendor: str | None` field ("NVIDIA", "AMD", a
PCI-vendor-derived name, or `None`).

### Capability audit (`environment/audit.py`)

- `check_gpu()` is **unchanged in name and meaning** — still NVIDIA-only,
  by design, because the CUDA wheel decision depends on it. It was
  tightened to require `vendor == "NVIDIA"` specifically (previously
  `available` alone implied NVIDIA, since NVIDIA was the only vendor
  ever detected; that implication broke the moment detection became
  vendor-neutral, so this is a real correctness fix, not just an
  addition — without it, an AMD GPU would have been misreported as an
  available *NVIDIA* GPU).
- `check_accelerator()` is new: `"Accelerator (any vendor)"`, `AVAILABLE`
  for any detected GPU regardless of vendor, `OPTIONAL` when none found.
  Added to `CAPABILITY_CHECKS` (`aarya-voice env-audit` now shows both).

### Calibration engine (`pipeline/calibration_engine.py`)

`HardwareSnapshot.capture()` now also reads the new `Accelerator (any
vendor)` capability: `accelerator_confirmed` is `True` when *either* the
NVIDIA-specific or the vendor-neutral capability is `AVAILABLE`.
`detected_backend` is `ComputeBackend.CUDA` only when NVIDIA GPU + CUDA
runtime are *both* confirmed (unchanged); `ComputeBackend.OTHER` for any
other confirmed accelerator (new) — never a fabricated `ROCM` claim,
because no ROCm runtime check exists yet. `HARDWARE_DETECTION_LIMITATION`
was rewritten to describe this real, current state rather than the
now-stale "not yet detected at all."

### Frontend (`calibration-engine-model.js`)

Mirrors the backend exactly, as this codebase's convention requires:
`captureHardwareSnapshot()` now also checks for the `"Accelerator (any
vendor)"` capability name; `HARDWARE_DETECTION_LIMITATION` text was
updated to match the backend's new wording. `synthetic-fixtures.js`
gained a matching fixture entry.

## What did NOT change

- **No execution path was added for AMD/Intel.** `scripts/install_env.sh`
  still only knows CPU and CUDA torch wheel indices. Running NeMo/
  WhisperX/a TTS model on ROCm or Intel XPU remains unbuilt and
  unplanned until a separate decision is made.
- **No runtime-level check exists for ROCm/Metal/OpenCL/XPU.** A detected
  AMD accelerator yields `ComputeBackend.OTHER`, exactly like an NVIDIA
  GPU without a confirmed CUDA runtime — presence without a confirmed
  working runtime is never upgraded to a specific backend claim.
- **Nothing about the Real ML Runtime milestone's embedding/generation
  scope changed.** `LocalNeuralEmbeddingProvider` (real, `AVAILABLE`) and
  the deferred `LocalNeuralVoiceGenerator`/`LocalTrainingProvider`
  (`NOT_CONFIGURED`, IndicF5 still HuggingFace-gated with no credentials
  available) are unaffected by this work.

## Verification (this environment)

This sandbox has no GPU of any vendor — `/sys/class/drm` does not exist,
`nvidia-smi`/`rocm-smi`/`lspci` are all absent. The AMD and sysfs
detection paths are therefore verified only via mocked unit tests
(`tests/test_system_info.py`: `test_gpu_detection_falls_through_to_amd_
when_nvidia_absent`, `test_gpu_detection_falls_through_to_sysfs_when_no_
vendor_tool_found`, `test_sysfs_gpu_detection_reads_real_pci_vendor_ids`
— the last one exercises the real sysfs-parsing code against a
fabricated `/sys/class/drm` layout, not a mock of the whole function) —
never against real AMD/Intel hardware, which this project has still
never run on. This is recorded honestly in `docs/GPU_STRATEGY.md`'s "Not
verified" section rather than implied to be hardware-tested.

## Testing

- Backend: 8 new tests across `test_system_info.py` (5),
  `test_environment_audit.py` (3), `test_calibration_engine.py` (1).
  Full suite: 777/777 passing, ruff clean.
- Frontend: 1 new test in `calibration-engine-state.test.mjs`. Full
  suite: 375/376 passing — the one failure (`20-processing-blocked`
  visual regression) is a pre-existing, already-self-documented timing
  flake in `frontend/tests/visual-scenarios.mjs` (its own comment: *"a
  blind fixed-length wait here raced that chain under load (observed one
  flake in 8 full harness runs)"*), unrelated to this change, confirmed
  independently (via `git stash`) to reproduce identically before any of
  this session's edits, and confirmed intermittent by re-running (passes
  2 out of 3 consecutive runs).
