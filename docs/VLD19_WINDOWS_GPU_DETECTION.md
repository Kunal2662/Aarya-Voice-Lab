# VL-D19 — Windows GPU Presence Detection

AARYA Voice Lab only. Continues the "hardware-agnostic GPU detection"
work (`docs/HARDWARE_AGNOSTIC_GPU_DETECTION.md`) and the long-standing
"portable runtime / hardware independence" theme this codebase has
referred to as **VL-D19/D20** since before the VL-D0–D18 desktop UI
series began (`identity/runtime.py`, `identity/contracts.py`,
`tests/test_phase3_e2e.py`, `frontend/contracts/generated/capability_state.json`
all already used that name for exactly this theme). No formal VL-D19
specification document existed anywhere in the repository — confirmed by
a full-repository search before implementing anything — so this
milestone's scope was established the same way VL-D14–D18 were: a
read-only audit against actual repository evidence, approved before
implementation.

## Why This Milestone Exists

`system_info.get_gpu_info()`'s vendor-neutral fallback,
`_detect_gpu_via_sysfs()`, reads `/sys/class/drm` — a path that exists
only on Linux. On any Windows machine with neither `nvidia-smi` nor
`rocm-smi` on `PATH`, every detection tier failed and the function
reported "no GPU" unconditionally, **even when a real GPU was physically
present**. This is the same class of bug the hardware-agnostic GPU
detection milestone already fixed once (NVIDIA-only detection bias) —
this time the bias is OS-only, not vendor-only.

This was not a hypothetical: it was reproduced directly, live, on the
machine this milestone was implemented on.

## Evidence

- **Real hardware, independently confirmed**: `Get-CimInstance
  Win32_VideoController` (PowerShell, run directly, no project code
  involved) reports this machine has an **Intel(R) Iris(R) Xe
  Graphics** integrated GPU.
- **Real bug, reproduced with the project's own unmodified code**:
  running `system_info.collect_system_report()` on this machine reported
  `GPU: NOT AVAILABLE (no NVIDIA, AMD, or PCI-enumerable GPU found)`.
- `docs/GPU_STRATEGY.md`'s own "Not verified" section already recorded
  that AMD/Intel detection had never been tested against real hardware
  — this machine is exactly that real, previously-unavailable hardware.
- No repository document defines "VL-D19" beyond the six code/doc
  references to the "portable runtime / hardware independence" theme
  name — reported honestly to the user before implementation rather than
  inventing a specification.

## Implementation

`src/aarya_voice_lab/system_info.py`:

- New `_detect_gpu_via_windows_wmi()`, mirroring `_detect_amd_gpu()`'s
  and `_detect_gpu_via_sysfs()`'s exact shape (`GPUInfo | None`, presence-
  only, never a negative `GPUInfo`):
  - Returns `None` immediately when `platform.system() != "Windows"` —
    this function is never attempted on Linux/macOS.
  - Returns `None` when neither `powershell` nor `pwsh` is on `PATH` —
    same "missing tool → fall through" discipline as `rocm-smi`.
  - Otherwise runs `Get-CimInstance Win32_VideoController | Select-Object
    Name,PNPDeviceID | ConvertTo-Json -Compress` via `subprocess.run`
    (10s timeout, `check=False`, matching every other subprocess call in
    this file exactly).
  - Parses each device's `PNPDeviceID` for a `VEN_XXXX` PCI vendor id —
    the same PCI vendor-id scheme `_PCI_VENDOR_NAMES` already covers for
    the Linux sysfs path — and reuses that same dict, so a device from an
    already-known vendor gets the same friendly name Linux detection
    would give it.
  - Unlike sysfs, WMI's `Name` field gives a real device name for free
    (confirmed: `"Intel(R) Iris(R) Xe Graphics"`, not a generic
    "model unconfirmed" placeholder) — used directly rather than
    discarded.
  - Never claims VRAM (`vram_mib: None` always) — `Win32_VideoController`'s
    `AdapterRAM` field is a known-unreliable 32-bit value on modern
    Windows and this milestone does not attempt to work around that.
- `get_gpu_info()` gained one more fallback tier, tried after the
  existing sysfs check and before the final honest negative — same
  "try each tier, fall through on `None`" pattern already used for
  NVIDIA → AMD → sysfs.
- `GPUInfo.detection_method` gained one new value, `"windows-wmi"`,
  alongside the existing `"nvidia-smi"` / `"rocm-smi"` / `"sysfs-pci-id"`
  / `"none"` — no schema/contract change, since `detection_method` was
  always a free-form `str`.

No other file was modified. `environment/audit.py`'s `check_gpu()`/
`check_accelerator()` and `pipeline/calibration_engine.py`'s
`HardwareSnapshot.capture()` call `get_gpu_info()` and therefore pick
this fix up automatically — verified by inspection, not changed.

## Tests

`tests/test_system_info.py`, mirroring the existing AMD/sysfs test
conventions exactly (`monkeypatch.setattr(system_info.X, "Y", ...)`):

1. `test_windows_wmi_gpu_detection_skipped_on_non_windows` — on a
   simulated non-Windows platform, the function returns `None` without
   ever calling `subprocess.run` (asserted by making that call raise).
2. `test_windows_wmi_gpu_detection_returns_none_when_powershell_absent` —
   confirms the same blanket `shutil.which → None` mock that already
   suppresses the AMD tier in every pre-existing test also suppresses
   this new tier, so no existing test needed modification.
3. `test_windows_wmi_gpu_detection_reads_real_pci_vendor_ids_from_pnp_device_id`
   — exercises the real (unmocked) PNPDeviceID-parsing regex against a
   fabricated payload shaped exactly like the real output this milestone
   observed on real hardware.
4. `test_windows_wmi_gpu_detection_handles_malformed_json` — malformed
   PowerShell output returns `None`, never a crash.
5. `test_gpu_detection_falls_through_to_windows_wmi_when_nothing_else_found`
   — integration-level: `get_gpu_info()` itself reaches and returns the
   new tier's result when every earlier tier is exhausted.

All five were originally verified by hand-executing the equivalent
monkeypatch logic directly against the real, unmodified module on this
machine, outside of pytest, since pytest itself could not be run at the
time this milestone was written (see Environment Limitations below for
why, and Verification Update for how that gap has since closed).

## Verification Update

`core.file_lock`'s Windows-portability fix (`75933a1`, landed after this
milestone) removed the `fcntl`-import blocker that had prevented
`pytest` from running on native Windows at all. With that gap closed,
`pytest tests/test_system_info.py -v` was run for real on this same
machine: **18 passed**, including all 5 tests listed above plus the two
pre-existing regression-risk tests
(`test_gpu_detection_handles_missing_nvidia_smi`,
`test_gpu_detection_reports_honest_negative_when_nothing_found`) — the
same result the original hand-verification predicted, now confirmed by
the real test runner rather than manual re-execution. Real-hardware
detection was independently re-confirmed the same session:
`collect_system_report().gpu` still reports `available=True,
vendor="Intel", detection_method="windows-wmi"`, device name
`"Intel(R) Iris(R) Xe Graphics"` — unchanged from this milestone's
original findings. `ruff check` on both changed files also now passes
(ruff was not installed on the machine this milestone was originally
written on).

## Real Runtime Verification

Performed directly, before and after, on this machine:

| | Before this milestone | After this milestone |
|---|---|---|
| `system_info.collect_system_report().gpu` | `available=False`, `note="no NVIDIA, AMD, or PCI-enumerable GPU found..."` | `available=True`, `vendor="Intel"`, `detection_method="windows-wmi"`, device name `"Intel(R) Iris(R) Xe Graphics"` |
| Independent check (`Get-CimInstance Win32_VideoController`, no project code) | N/A | Confirms the same device name — the fix reports exactly what the OS itself reports, nothing invented |

This is real hardware, not a mock — the first time any GPU-detection
tier in this project has been verified against genuinely present,
non-NVIDIA hardware rather than only mocked unit tests (`docs/GPU_STRATEGY.md`'s
"Not verified" section previously recorded this as untestable in any
environment this project had run in).

## Acceptance Criteria

- `_detect_gpu_via_windows_wmi()` returns `None` on any non-Windows
  platform, unconditionally, without invoking a subprocess.
- On Windows, it returns `None` when PowerShell is unavailable, when the
  WMI query fails, or when its output cannot be parsed as JSON — never a
  crash, never a fabricated positive.
- When a real device is found, its vendor is derived from the same
  `_PCI_VENDOR_NAMES` PCI-vendor-id table the Linux sysfs path already
  uses, and its name is the real name Windows itself reports.
- `get_gpu_info()`'s existing NVIDIA → AMD → sysfs precedence is
  unchanged; the new tier is additive, tried last before the honest
  negative.
- No pre-existing test's assertions were weakened; the two tests whose
  real-Windows behavior could have been affected
  (`test_gpu_detection_handles_missing_nvidia_smi`,
  `test_gpu_detection_reports_honest_negative_when_nothing_found`) were
  confirmed, by direct execution against the real module on this real
  machine, to still pass unmodified.
- Real hardware verification (not just mocked tests) was performed and
  is reported honestly above.

## What This Milestone Does NOT Implement

- **No GPU execution path for AMD/Intel/anything non-NVIDIA.** Detecting
  a device's presence and being able to run inference on it remain two
  separate, separately-unverified claims — unchanged from
  `docs/HARDWARE_AGNOSTIC_GPU_DETECTION.md`'s own statement of this.
  `scripts/install_env.sh` still only knows CPU and CUDA wheel indices.
- **No CUDA/ROCm/Metal runtime-level check.** `get_cuda_info()` is
  unmodified; it still only confirms CUDA via `torch.cuda.is_available()`.
- **No RTX-3050-specific or any other GPU-model-specific logic anywhere**
  — this milestone adds a vendor/OS-neutral presence-detection tier, not
  a hardware-specific branch. The architecture continues to support
  NVIDIA, AMD, Intel, integrated, discrete, and CPU-only systems equally.
- **No change to `identity.runtime`'s `RuntimeCapability`/`ComputeBackend`
  vocabulary, `describe_portability()`, or the D13 runtime-capability
  bridge.** This milestone is entirely inside `system_info.py`'s
  detection layer, several layers below where that vocabulary is
  declared.
- **No packaging/deployment work** — the "VL-D20" half of the
  "VL-D19/D20" theme (shipping a portable runtime to a CPU-only machine)
  is untouched.

## Environment Limitations (at the time this milestone was written)

- Backend `pytest` could not be run: `.venv/bin/python` remained a broken
  symlink to a non-Windows path, and importing the full `aarya_voice_lab`
  package on native Windows Python failed regardless, because
  `core.file_lock` imported the POSIX-only `fcntl` module unconditionally.
  `system_info.py` itself has zero project-internal or third-party
  dependencies (stdlib only), so it — and this milestone's tests, which
  import only `system_info` — could be exercised directly; the full suite
  could not.
- In place of pytest, every new test's logic was verified by hand,
  executing the identical monkeypatch sequence directly against the real,
  unmodified module in a plain Python process on this machine, including
  an explicit regression check against the two pre-existing tests most
  at risk of being affected.
- **Closed** — see Verification Update above. `core.file_lock` gained
  real native-Windows support in a later, unrelated commit (`75933a1`),
  and the full test suite (including this file's tests, run for real
  through pytest) now runs cleanly on native Windows.
- `ruff` is not installed anywhere on this machine; the diff was
  reviewed manually for style/lint issues (line length checked against
  the project's configured 120-character limit; no unused imports;
  `re` added to the top-level import block, matching the existing
  `json`/`platform`/`shutil`/`subprocess` style).
- This machine's own GPU (Intel Iris Xe) served as the real hardware
  verification target — no GPU was simulated or assumed.
