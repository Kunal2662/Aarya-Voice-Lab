# AARYA Voice Lab Installer — IndicF5 Runtime Provisioning

Standalone AARYA Voice Lab milestone. Aarya Core integration is explicitly
**out of scope** — this document and the work it records make Voice Lab
itself installable and runnable on a fresh Windows machine; nothing here
touches Core.

## Why this exists

Prior work this session established that AI4Bharat IndicF5 is not just
"selected" (`docs/TTS_MODELS.md`) but **verified end-to-end**: real CUDA
generation, human-confirmed intelligible speech, through a vendored copy
of IndicF5's own bundled F5-TTS source
(`scripts/ml_workers/vendor/indicf5_f5tts/` — see that package's module
docstrings for the full provenance of why PyPI's `f5-tts` package cannot
be used instead). That verification happened by hand, on one already-
configured developer machine. This document records the design and
implementation of making that same verified runtime installable on a
machine that starts with nothing — the target flow:

```
Fresh Windows laptop
   → system/environment checks → runtime installation → Python environment
   → ML/TTS dependencies → IndicF5 runtime → HuggingFace authentication
   → model download/cache → GPU capability detection → runtime validation
   → real speech generation → READY
```

An installer *design report* (architecture, technology choice, phased
implementation order) was reviewed and approved before any of the work
below began. The approved phase order:

**A** VRAM measurement → **B** environment provisioning → **C** HF
authentication → **D** model/cache provisioning → **E** real smoke-test
validation → **F** install reporting → **G** fresh-machine simulation →
**H** full test suite.

## Phase A — Measured GPU memory requirements

**Instrumentation** (purely additive — new response fields only, no
change to load/generation behavior): `scripts/ml_workers/
indicf5_generation_worker.py` now reports `peak_allocated_mib`/
`peak_reserved_mib` on its `load` and `generate` responses, via
`torch.cuda.reset_peak_memory_stats()` / `max_memory_allocated()` /
`max_memory_reserved()`.

**Reference machine:** RTX 3050 Laptop GPU, **4096 MiB total VRAM** (the
4 GB variant). This GPU does not drive the display (hybrid/Optimus
graphics) — baseline usage was 8 MiB before the worker even started, so
essentially the full 4096 MiB was available going in.

**Measured, through the real production worker** (not a reimplementation
— the exact subprocess `IndicF5VoiceGenerator` launches):

| Stage | PyTorch peak allocated | PyTorch peak reserved | `nvidia-smi` system-wide used | Wall time |
|---|---|---|---|---|
| Model + vocoder load | 2634.8 MiB | **~2642 MiB** | 2713 MiB | 3.83s (load itself) |
| Short generation (1.9s output, 32 NFE) | 1403.2 MiB | **~2648 MiB** | 2749 MiB | 12.95s |
| Long generation (~19.1s output, 32 NFE) | 1466.6 MiB | **~2708 MiB** | **~2809 MiB** | 52.91s |

"Reserved" (not "allocated") is the operationally meaningful figure —
what PyTorch's caching allocator actually holds from the driver and will
not release mid-session, i.e. the honest floor for "how much VRAM this
needs to not fail." "Allocated" during generation reads *lower* than
during load because the caching allocator released the transient
checkpoint-deserialization staging buffers between the two stages —
"allocated" only counts live tensors at any instant, not the high-water
mark of everything that ever passed through.

**Observed headroom at the worst point measured:** `nvidia-smi` reported
**~1154 MiB still free** out of 4096 MiB total, after the long
generation.

An extreme-length stress test beyond the ~19.1s long-generation case was
deliberately not run — the load-time transient (2642 MiB) and the two
generation peaks are close together, so a materially higher ceiling was
not expected, and it was not required for the tiering decision below.

## GPU VRAM capability tiers

Implemented in `environment.audit.check_indicf5_vram_tier()`, wired into
`environment.verify.verify_environment()` for `EnvironmentId.TTS` only
(it is workload-specific policy, not a generic machine-state check, so it
deliberately is **not** part of `CAPABILITY_CHECKS`/`run_audit()`).

| VRAM | `CapabilityState` | Meaning |
|---|---|---|
| < 3 GB (`INDICF5_VRAM_INSUFFICIENT_BELOW_MIB = 3072`) | `INCOMPATIBLE` (blocking) | INSUFFICIENT — do not attempt IndicF5 GPU generation |
| 3 GB – < 4 GB | `OPTIONAL` (non-blocking) | CONSTRAINED / UNVERIFIED — not officially supported yet; exposed only as an explicit warned/advanced path if the calling code chooses to |
| ≥ 4 GB (`INDICF5_VRAM_SUPPORTED_AT_OR_ABOVE_MIB = 4096`) | `AVAILABLE` | Supported, **based on the verified 4 GB reference configuration** |
| No NVIDIA GPU detected | `OPTIONAL` (non-blocking) | CPU fallback exists in the code but its timing is unmeasured — see below |
| NVIDIA GPU present, VRAM unreadable | `UNKNOWN` | Tier cannot be determined |

**The ≥ 4 GB tier is deliberately never described as a universal
guarantee.** `check_indicf5_vram_tier()`'s `AVAILABLE` detail text always
names the reference machine and the word "verified" explicitly — this is
enforced by test (`test_vram_tier_available_detail_never_claims_
universal_guarantee`), not merely a documentation promise. A GPU with
6 GB, 8 GB, or 12 GB has *not* been tested; it is expected to work
(strictly more headroom than the reference machine), but that is an
expectation, not a measurement.

The 3–4 GB "constrained" band exists because the reference machine's own
measured peak (~2.71 GB reserved) leaves under 1.3 GB of headroom on a
4 GB card — a 3–4 GB card would have less margin still, and has not been
tested at all.

## CPU execution — explicitly not production-supported yet

Per the approved design decision: CPU execution is **code-supported**
(both the vendored `CFM.sample()` path and the worker fall back to
`device="cpu"` when CUDA is unavailable — no hard block exists anywhere)
but has **no real timing measurement**. `TTS_SPEC.cpu_caveat` and
`check_indicf5_vram_tier()`'s no-GPU detail text both say this explicitly:
treat CPU as experimental/very slow, not verified production support.
This will be revisited once a real CPU timing run is performed — not
before.

## Phase B — Environment provisioning

**Dependency list re-verified from the actual working production
environment** (`pip list --format=freeze` against `.envs/env-tts-
windows-gpu`, the machine this whole IndicF5 verification was performed
on), then narrowed to exactly what the vendored runtime imports — traced
file-by-file (`cfm.py`, `modules.py`, `model/utils.py`, `backbones/
dit.py`, `infer/utils_infer.py`), **not** the full dependency set the
PyPI `f5-tts` package declares (which also pulls in `gradio`, `wandb`,
`bitsandbytes`, `datasets`, `accelerate`, `hydra-core`, `click`,
`transformers_stream_generator`, `cached_path`, `unidecode`, none of
which the vendored code touches at all). `requirements/tts.txt` now
installs only the lean, exact-pinned set:

```
transformers==4.49.0   huggingface_hub==0.36.2   safetensors==0.8.0
soundfile==0.14.0       x-transformers==2.27.4    torchdiffeq==0.2.5
librosa==1.0.0          pypinyin==0.55.0          rjieba==0.2.1
pydub==0.25.1            vocos==0.1.0              matplotlib==3.11.1
tqdm==4.70.0             numpy==2.5.2
```

plus `torch==2.13.0` / `torchaudio==2.11.0`, installed first from an
explicit wheel index (`cu126` for CUDA — **not** `cu130`, PyTorch 2.13's
own default index; `cu126` is the exact index the verified reference
install actually used, and `cu130` has never been tested against this
model). `torchcodec` (a transitive dependency of the full `f5-tts`
package, and the thing whose broken DLL loading the vendored worker
already works around with a `soundfile`-backed patch) is deliberately
**not** listed — nothing in the verified path imports it.

**`environment/specs.py`'s `TTS_SPEC` updated to reflect reality:**

- `purpose`: no longer "NO MODEL SELECTED" — names IndicF5 as selected
  and verified.
- `expected_packages`: `torch`/`torchaudio`/`transformers`, the three
  most version-sensitive pins (mirrors `NEMO_SPEC`/`WHISPERX_SPEC`'s
  existing 2–3-key convention; the full pin list lives in
  `requirements/tts.txt`, not duplicated here).
- `torch_index_cuda`: corrected to `cu126`.
- `external_requirements`: `OPEN_MODEL_DOWNLOAD` → `(GATED_MODEL_DOWNLOAD,
  CREDENTIAL)` — **confirmed empirically, not assumed**: an anonymous
  `hf_hub_download` against `ai4bharat/IndicF5` returns `401
  GatedRepoError`, even though `HfApi().model_info(token=False)`
  (metadata only) succeeds anonymously. A real account with the model's
  access request approved, and a valid token, are required before any
  file can be downloaded.
- `requires_approval`: **retired** (`None`). The reason it existed ("no
  TTS model has been selected") is no longer true. `env-whisperx` keeps
  its own gate unchanged — a real, unresolved third-party account +
  gated, contact-sharing-agreement model, a different and still-open
  concern.
- `cpu_caveat`: rewritten per "CPU execution" above — no longer claims
  "feasible... for small models" (untrue for this model, unmeasured).

**`scripts/install_env.sh` updated:**

- The `env-tts` stop condition (required `--i-have-approval`) is
  removed. `env-whisperx`'s stop condition is unchanged.
- `env-tts`'s torch install now pins `torch==2.13.0 torchaudio==2.11.0`
  from `cu126`/`cpu`, instead of an unpinned `torch` from `cu130`/`cpu`.
- **Two pre-existing bugs found and fixed while actually running this
  script on native Windows for the first time** (previously it had only
  ever been run against WSL/Linux, or not run to completion at all — see
  `docs/ENVIRONMENT.md`'s WSL section):
  1. Hardcoded `python3 -m venv` — on a fresh Windows machine, `python3`
     frequently resolves to a non-functional Windows Store "app
     execution alias" stub (confirmed directly: exits non-zero, prints
     "Python was not found; run without arguments to install from the
     Microsoft Store...") even when a real interpreter is on `PATH` as
     plain `python`. The script now probes both and uses whichever
     actually works.
  2. Hardcoded `$ENV_DIR/bin/python` — wrong on native Windows, where
     `venv` writes `Scripts/python.exe`. Now checks for
     `Scripts/python.exe` first, falling back to `bin/python` — the
     exact same fallback order `pipeline.runner.EnvironmentPaths.python`
     already uses, so the two never disagree about where an
     environment's interpreter lives.
- Prints an explicit, non-blocking note for `env-tts` about the
  HuggingFace gate and the vendored (not PyPI) runtime, since the
  approval-gate message that used to carry this information is gone.

**Environment naming:** the installer targets the canonical
`.envs/env-tts` (matching `EnvironmentId.TTS.value`), not the ad-hoc
`.envs/env-tts-windows-gpu` name the original manual verification used.
`pipeline.indicf5_generation.autodetect_tts_python()`'s existing
`CANDIDATE_ENV_NAMES = ("env-tts-windows-gpu", "env-tts")` already checks
both, in that order, so a freshly-provisioned `.envs/env-tts` is picked
up automatically with **no change needed** to the production provider
code. The original `.envs/env-tts-windows-gpu` is left untouched.

## Phase D — Model/cache provisioning

New, deliberately separate from the verified inference runtime: `scripts/
ml_workers/indicf5_provisioning_worker.py` (subprocess-isolated in
`.envs/env-tts`, same reasoning as the Phase C auth worker) + `pipeline.
indicf5_provisioning` (base-interpreter orchestrator, imports nothing
from `huggingface_hub`/`safetensors`/`torch`). Neither
`indicf5_generation_worker.py` nor the vendored `indicf5_f5tts` package
was touched by this phase.

**Exactly five files are downloaded, matching what the verified
production worker's own `_ensure_loaded()` reads** — no more (specifically
never IndicF5's own bundled `f5_tts` source tree, also hosted in that
repo, which this project already vendors separately):

| Logical name | Repo | File |
|---|---|---|
| vocab | `ai4bharat/IndicF5` | `checkpoints/vocab.txt` |
| checkpoint | `ai4bharat/IndicF5` | `model.safetensors` (~1.4 GB) |
| reference_audio | `ai4bharat/IndicF5` | `prompts/PAN_F_HAPPY_00001.wav` |
| vocoder_config | `charactr/vocos-mel-24khz` | `config.yaml` |
| vocoder_weights | `charactr/vocos-mel-24khz` | `pytorch_model.bin` |

**Caching:** every file goes through `huggingface_hub.hf_hub_download()`,
which checks its own cache (`~/.cache/huggingface/hub/...`) first — an
already-cached file is never re-downloaded. Nothing is ever written into
this repository.

**Failure classification** — five kinds, distinguished precisely (a
`ProvisioningError.failure_kind` on the base-interpreter side):

- `authentication` — no HuggingFace token cached at all (checked locally,
  no network call needed, before attempting any download).
- `gated_access` — a token exists but this specific repo's gate has not
  been approved for that account (`GatedRepoError`).
- `network` — could not reach the Hub and no cached copy exists
  (`LocalEntryNotFoundError`, or a `requests.exceptions.ConnectionError`/
  `Timeout` — checked *before* the generic `OSError` catch below, since
  `requests.exceptions.ConnectionError` is itself an `OSError` subclass
  via `IOError` and would otherwise be misreported as a disk failure).
- `disk` — a genuine filesystem error (permissions, no space) writing the
  downloaded file.
- `corruption` — **verified explicitly, per file, after every download
  (and independently in `verify()` mode, without downloading)**: the
  checkpoint's size (must be ≥ 1 GB) and safetensors header must parse
  with a non-empty tensor list; the vocab file must have a plausible
  line count (≥ 100, not the handful of lines a truncated file would
  leave); the reference WAV must parse via `soundfile.info()` with
  non-zero duration; the vocoder config must parse as non-empty YAML;
  the vocoder weights must meet a minimum size and load via
  `torch.load(..., weights_only=True)`. **Directly tested** against five
  deliberately corrupted files (truncated checkpoint, truncated vocab,
  garbage WAV, empty YAML, undersized weights) — all five correctly
  rejected with `failure_kind="corruption"`.

**`ensure_authenticated_then_provision()`** checks Phase C's
`check_existing_login()` *first*, so an unauthenticated caller sees
`failure_kind="authentication"` immediately rather than a less specific
download error partway through five files.

**Verified for real, end to end**, against the actual `.envs/env-tts`
built in Phase B and this project's own real (already gate-approved) HF
account: `provision()` found all five files already cached (from this
project's own earlier verification work) and structurally verified every
one — including the full 1337.8 MiB checkpoint. A separate, explicit
`verify()` call (no download attempted at all) independently confirmed
`env-tts` can locate and validate every required asset — the direct
acceptance criterion for this phase.

A bug was found and fixed during this verification: `verify()`'s worker
response didn't include a `status` field (only `provision()`'s did),
which crashed the summary formatter on a `None` value — fixed on both
sides (the worker now reports `status="already_cached"` for verify-mode
entries too, and the formatter no longer assumes the field is always
present). Caught by actually running the code, not by inspection.

## Phase E — Real smoke-test validation

New: `scripts/indicf5_smoke_test.py` (standalone, detailed step-by-step
report) and `tests/test_indicf5_smoke.py` (capability-gated pytest
coverage of the same path). Both drive the **full production stack**,
not just the vendored runtime directly (that remains
`scripts/indicf5_bundled_reference_test.py`'s job, unchanged, still
available):

```
IndicF5VoiceGenerator -> GPU worker subprocess -> vendored indicf5_f5tts
  -> RTX 3050 CUDA -> generated WAV -> WAV validation -> (human) intelligibility
```

**Forced onto the canonical `.envs/env-tts`** (built in Phase B), never
the older `.envs/env-tts-windows-gpu`, via `IndicF5VoiceGenerator`'s
existing `tts_python=` constructor override — no change to
autodetection or any other production code.

**Two small, additive enrichments to `pipeline.indicf5_generation`**
(text/messages only, no behavior change, no new fields on
`PreviewArtifact`/`GenerationCapabilities`'s contract): `get_capabilities()`'s
`AVAILABLE` detail string now includes the Phase A VRAM figures already
in the worker's response, and the two "no interpreter found" error
messages now point at the canonical `env-tts` (they previously said
"build env-tts-windows-gpu first", stale advice once Phase B changed
what the installer actually provisions).

**Validated, all of it, for real, twice** (both a full second run of the
whole script as a separate process, and two `generate_preview()` calls
within each run): worker starts; model loads; CUDA is confirmed actually
in use (asserted, not assumed); inference completes; the WAV exists, is
valid, has the correct sample rate (24000) and channel count (1), a
reasonable duration, no NaN/Inf (definitional for the integer-PCM format
actually produced — noted explicitly rather than silently skipped), is
non-silent, and has peak/RMS within sane bounds. The `PreviewArtifact`
contract is checked field-by-field (`kind=generated_speech`,
`is_synthetic=False`, `model_name`, `sha256` matching the real file on
disk).

**Reproducibility / persistent-worker lifecycle**, proven two ways:
`get_capabilities()` called right after a direct worker load completed
in 0.00s (vs. the real load's ~5s); and the worker's own `_run_generate()`
response reports `model_load_seconds=0.0` on a call issued after the
model was already warm — the worker's own ground truth that no reload
happened, not a wall-clock heuristic. (An earlier version of this
script's reproducibility check compared generation time against the
original model-load time instead of comparing the two generation calls
to each other — a bug in the *test*, not the runtime; found and fixed
before this record was written, not left in.)

**Measured** (RTX 3050 Laptop GPU, matches Phase A within measurement
noise): model load ~4.9–5.0s, peak_reserved ~2642 MiB; generation ~21–22s
per call (1.9s output, 32 NFE — consistent with earlier sessions' timing
for this same reference machine and text), peak_reserved ~2648 MiB.

**Failure paths** — deliberately not re-implemented redundantly:
`tests/test_indicf5_generation.py`'s existing 12 tests already cover
missing-model / invalid-environment / worker-startup-failure scenarios
(bogus interpreter path, unreachable worker, never writing a fake
artifact on failure) with clean `GenerationBlockedError`/
`GenerationCapabilities(ERROR/NOT_CONFIGURED, ...)` results — never a
raw traceback. `tests/test_environment_audit.py`'s 6 VRAM-tier tests
(Phase B) cover the "insufficient capability" classification. "CUDA
unavailable" specifically was not additionally tested here: doing so
faithfully would need a genuine CPU-only environment build, which is a
larger undertaking than this phase's scope and was not required to
verify the phase's actual acceptance criterion.

**Human listening required — mechanical validation is not the
acceptance criterion.** Two WAVs from this phase's verification run were
sent for listening: the same text already confirmed intelligible earlier
in this project's work (`नमस्ते, आज मौसम अच्छा है.`), generated twice in
one run to also demonstrate reproducibility.

## Phase F — Installation / capability reporting

New: `pipeline.indicf5_install_report` (aggregator) and a new CLI verb,
`aarya-voice indicf5-report [--json] [--skip-smoke-test]`. Reuses the
existing `Capability`/`CapabilityState` model and environment-audit
architecture throughout — this phase adds no new capability vocabulary,
it assembles already-existing, already-tested checks (`environment.audit
.run_audit()`, `check_indicf5_vram_tier()` from Phase B,
`environment.verify.verify_environment()` via `tts-check --json`,
`pipeline.hf_auth.check_existing_login()` from Phase C,
`pipeline.indicf5_provisioning.verify()` from Phase D) plus two new OS/
architecture facts (Windows version, x64 architecture) in the same
`Capability` shape.

**`scripts/indicf5_smoke_test.py` (Phase E) was not modified, imported
internals of, or duplicated.** It is invoked as a subprocess and treated
as an already-verified black box: its own structured "Summary for the
Phase E report" section (designed in Phase E with exactly this consumer
in mind) is parsed for metrics, and its exit code is the only signal
used for pass/fail. This was a deliberate choice over refactoring Phase
E's logic into a shared library function, specifically to guarantee
Phase E's already-reviewed, already-approved behavior stays completely
untouched.

**Staged, short-circuiting design:** cheap checks (OS/arch, Python, RAM,
disk, VRAM tier, TTS environment packages, HF auth, model/cache) run
first, in order; the first one that's already blocking stops the report
right there with `smoke_test_ran=False` and an honest reason — there is
no point spending 30-60s proving a GPU generation will fail when a
cheaper check already knows why. Only when every cheap check passes does
the real smoke test actually run.

**READY is set if and only if this exact call ran the real smoke test
and it passed** — never inferred from the cheap checks alone, never
cached from an earlier call, never set because "imports succeeded" or
"the model loaded" in isolation. `run_smoke_test=False` (the CLI's
`--skip-smoke-test`) can never produce READY, by construction — verified
by test.

**The 14 failure categories**, each reached via a distinct code path and
covered by a dedicated test: `python_incompatible`, `insufficient_ram`,
`insufficient_disk`, `gpu_unavailable`, `insufficient_vram`,
`cuda_unavailable`, `tts_environment_missing`, `hf_auth_missing`,
`hf_gated_access_denied`, `hf_network_failure`, `model_missing`,
`model_corruption`, `worker_startup_failure`, `model_loading_failure`,
`inference_failure`. When the smoke test itself fails (rather than an
earlier check), the specific category (`model_loading_failure` vs.
`inference_failure`) is inferred from which `PASS:` markers appear in
its captured stdout before the failure — necessarily a best-effort
classification of external process output, not a structured failure
code, and documented as such in the code rather than overclaiming
precision.

**Machine-readable** (`InstallerReport.to_dict()`) and **human-readable**
(`format_installer_report()`) both provided, mirroring
`EnvironmentAudit.to_dict()`/`format_audit()`'s established pattern
exactly. The human-readable form explicitly names which WAV(s) a person
should listen to and states outright that mechanical validation is not
the same claim as intelligibility.

**The HuggingFace token is structurally absent from this module.**
Nothing here imports `huggingface_hub`; the only auth-related data that
flows through is `HFAuthStatus` (`authenticated`, `username`,
`can_read_gated_repos`, `detail`), which never carries a token by
construction (see Phase C). Tested directly: the full report's JSON
serialization never contains the substring "token".

**Two real bugs found and fixed while verifying this phase against
actual hardware:**
1. `_run_smoke_test_subprocess()`'s `subprocess.run()` call didn't
   specify `encoding="utf-8"`, so Windows' default cp1252 locale raised
   `UnicodeDecodeError` decoding the smoke test's own Devanagari
   verification text — the exact same class of issue already fixed
   several times elsewhere this session, missed here until it was
   actually run. Fixed, plus defensive `None`-handling added to the
   output parsers for robustness beyond just this one cause.
2. "IndicF5 VRAM tier" appeared twice in the assembled capability list
   (once from this module's own direct call, once folded in from
   `tts-check --json`'s output, which already includes it via Phase B's
   own wiring) — deduplicated.

**Verified for real, reaching every state**, against the actual
`.envs/env-tts` and this project's own real HF account: a full
`READY` run (every check passed, real smoke test ran and passed, two
WAV paths correctly surfaced); an `hf_network_failure` run (this
session's own recurring live-network flakiness, correctly reported as a
distinct, honest state rather than misreported as "not authenticated");
and an `inference_failure` run (a stale WAV from earlier manual testing
correctly triggered `generate_preview()`'s own "refusing to overwrite"
protection, and the failure surfaced as a clean, one-line message — not
a raw multi-line traceback — in the final report). 14 additional tests
mock every remaining failure category deterministically.

## Phase G — Fresh-machine / clean-installation validation

No disposable VM was available on this machine, so the acceptance test
used the strongest clean-room simulation possible on the real hardware
without ever touching real state: an isolated copy of the working tree
(`tar --exclude=.git --exclude=.envs --exclude=<data dirs> -cf - . |
tar -xf - -C <clean room>`, which excludes machine state as part of the
copy itself rather than copying then deleting it), a from-scratch base
venv and a from-scratch `.envs/env-tts` built entirely inside that copy,
and an isolated `HF_HOME` pointed at an empty directory and then
authenticated with the real token (read once, length-only logged, never
the value). The real `.envs/env-tts`, `.envs/env-tts-windows-gpu`, and
`~/.cache/huggingface` were confirmed untouched throughout by diffing
their mtimes before and after the run.

**What could not be simulated, stated honestly:** no true disposable
VM — this is a same-machine, same-OS-install clean room, not a fresh
Windows install; no winget/Python-provisioning path was exercised —
Phases A–F assumed Python already present, and this phase's "fresh
Python" step means a fresh **venv**, not a fresh Python interpreter
install; no second real HuggingFace account was available to test a
genuinely different identity, so authentication was tested as
"no credentials" → "the operator's own real credential", not
"credential A" → "credential B"; disk-exhaustion and unsupported-GPU
scenarios were not reproduced live (see below) and are covered only by
`check_disk()`/`check_indicf5_vram_tier()`'s existing unit tests, not by
a live low-disk or non-NVIDIA machine.

**Full 19-step lifecycle, run for real inside the clean room:** fresh
base venv → fresh `.envs/env-tts` (confirmed exact version match to the
verified reference — `torch==2.13.0+cu126`, `torchaudio==2.11.0+cu126`,
CUDA available) → NVIDIA GPU/VRAM detection (RTX 3050, 4096 MiB,
`AVAILABLE`) → HF auth from a genuinely empty `HF_HOME`
(`authenticated: False, "no token cached locally"` — confirmed, not
assumed) → real login with the operator's token → from-scratch
provisioning of all five required assets (vocab, vocoder config,
reference audio, vocoder weights, checkpoint) — the **first time this
session** every file reported `status: downloaded` rather than
`already_cached`, since every earlier Phase D test reused the
already-populated real cache (148.9 s for ~1.4 GB) → structural
verification of all five → worker start → model load on CUDA
(`load_seconds≈7.0s`, `peak_allocated≈2635 MiB`) → two independent real
generations of the canonical verification sentence, both non-silent,
correctly formatted, and produced through
`IndicF5VoiceGenerator.generate_preview()` (not a lower-level shortcut)
→ WAV validation → `indicf5-report` reaching a genuinely-earned
`READY`.

**Dependency-isolation checks:** the clean room's `env-tts` was built
with no reference to the real `.envs/env-tts-windows-gpu`, no global
site-packages, no developer-only paths, no pre-existing project cache,
and no manually-set environment variables beyond `HF_HOME` (which the
real installer's own credential flow already supports overriding) — the
version match confirms the pinned `requirements/tts.txt` alone is
sufficient to reproduce the reference environment from nothing.

**Security verification:** the real token was read exactly once, logged
only as a length, never printed, never written to any file this session
created, and never appears in `phase_g_report_final.json` or any
installer log — confirmed by grepping every captured report/log for the
substring "token" (none found beyond field names that never carry a
value) and for a `hf_`-prefixed token pattern (none found).

**Failure/recovery tests, all live:**
1. **Worker-startup failure** — pointing the generator at a
   nonexistent interpreter path produced a clean, actionable error, no
   traceback.
2. **Interrupted-then-retried install** — killing provisioning mid
   -download and retrying found an honest, real characteristic: the
   installer does **not** silently self-heal a partial download; it
   requires the operator to clear the incomplete file (verify()
   reports it as present-but-invalid, which is the correct, safe
   behaviour — it never mistakes a partial file for a complete one).
3. **Genuine, organic network failure during HF auth** — not a
   simulated one. While repeatedly exercising `check_existing_login()`
   during this phase, `whoami()` began failing intermittently against
   this session's network (measured ~17–50% failure rate across
   several sampling windows), root-caused via a full traceback to
   `ConnectionResetError: [WinError 10054]` — a genuine TLS-handshake
   reset during the connection to huggingface.co's auth API,
   distinguishable from the file-download endpoints (100% reliable
   across all 5 asset downloads in this same session). In every
   failing case, the installer's existing exception classification
   (`hf_auth_worker.py`'s `except HfHubHTTPError` → 401 check, `except
   Exception` → generic network failure, ordered exactly as Phase C
   designed it) reported a clean `hf_network_failure`, never crashed,
   never leaked the token, and never misreported the failure as
   "not authenticated". `indicf5-report` itself has no retry logic
   around this single network call (each invocation is a fresh,
   independent check, by design — see Phase F); reaching `READY`
   during this flaky window required the *operator* to retry the
   check, which is exactly the documented, intended behaviour (an
   installer wizard would simply show "couldn't reach HuggingFace, try
   again"). This is real-world evidence the existing design already
   handles the failure mode Phase D/F were built for.
4. **Corrupted model asset** — `model.safetensors` in the isolated
   cache was truncated to 10 MB (from its real 1337.8 MB) and backed
   up first. `verify()` reported a clean `ProvisioningError` —
   `"model.safetensors is only 10485760 bytes -- expected >= 1000000000
   bytes; the cached file is truncated or corrupt"`,
   `failure_kind="corruption"` — and `indicf5-report` surfaced it as
   `model_corruption`, correctly short-circuiting **before** the
   expensive smoke test (the same staged design Phase F verified with
   mocks, now confirmed against a genuinely corrupted file). Restoring
   the backed-up bytes made `verify()` pass again immediately, with no
   installer-side state to reset — confirming clean recovery.
5. **Insufficient disk / unsupported GPU-VRAM** — not reproduced live
   (doing so safely would mean filling a real disk or physically
   swapping hardware); covered only by `check_disk()`'s and
   `check_indicf5_vram_tier()`'s existing unit tests
   (`tests/test_environment_audit.py`), which is a real, honestly-
   stated gap in live coverage, not a claim of having tested it.

**One real, previously-latent bug found and fixed by this phase:**
`scripts/install_env.sh` hardcoded `python3` and
`$ENV_DIR/bin/python`. On this machine, `python3` resolves to a
non-functional Windows Store app-execution-alias stub (confirmed: exits
non-zero, prints "Python was not found; run without arguments to
install from the Microsoft Store"), and native Windows `venv` writes
`Scripts/python.exe`, not `bin/python`. Both are exactly the kind of
"works on the original dev machine, breaks on a fresh one" defect this
phase exists to catch. Fixed: the script now probes `python3` then
falls back to `python`, and checks `Scripts/python.exe` before
`bin/python`, matching `EnvironmentPaths.python`'s own existing
fallback order.

**Second, tooling-only issue found during the simulation itself (not an
installer bug):** the initial clean-room copy attempt used `robocopy`
invoked from Git Bash, which mangled the Windows-style arguments
(`ERROR : Invalid Parameter #3 : "E:/"`); switched to a single-pass
`tar | tar` pipe with excludes baked into the copy. A stray partial
`.envs/env-tts` left over from an aborted `cp -r` attempt hit Windows'
long-path limit on torch's nested `ATen/ops` headers when deleted with
plain `rm -rf`; removed via PowerShell `Remove-Item -LiteralPath "\\?\
<path>"`. Neither issue touched real project state; both are
clean-room-methodology notes, not defects in the installer itself.

**Result: genuine, freshly-earned `READY`**, produced by
`indicf5-report` running entirely inside the clean room against its own
`.envs/env-tts` and its own isolated, freshly-authenticated,
freshly-provisioned `HF_HOME` — the canonical production path
(`IndicF5VoiceGenerator` → GPU worker → vendored AI4Bharat runtime →
RTX 3050 → CUDA) end to end, not a substitute or shortcut. Two
generated WAVs were produced from a machine state that started with no
`.envs/env-tts`, no cached models, no cached credentials, and no prior
installer state.

### Human-validation gate — CLOSED

This project's own rule (established in Milestone 3, restated at the
top of every phase since) is that mechanical WAV validation and human
intelligibility are two different claims, and only the second one
counts as "working." Phase G produces three distinct facts; they are
recorded separately here and must not be collapsed into one another:

1. **Mechanical WAV validation** (machine-checkable, no human needed):
   `preview-req-00001.wav` is 24 kHz, mono, 1.909 s, non-silent
   (peak 0.295, rms 0.033), not clipping. This proves the file is a
   valid, well-formed audio artifact — nothing about what it says.
2. **Real GPU generation** (machine-checkable): produced by
   `IndicF5VoiceGenerator.generate_preview()` on real CUDA hardware
   (RTX 3050, `load_seconds≈6.99s`, model reused with no reload on the
   second call) inside the clean-room simulation — proves the
   production code path executes correctly end to end, not that its
   output is correct speech.
3. **Human listening confirmation** (the only claim that establishes
   intelligibility): the operator listened to `preview-req-00001.wav`
   — spoken text `"नमस्ते, आज मौसम अच्छा है."` — and classified it
   **"Recognizable / intelligible"** via an explicit three-way prompt
   (recognizable / partially recognizable / unintelligible-broken).
   This is the same WAV referenced in fact 1 and 2 above, not a
   regenerated or substitute sample.

With all three facts holding for the same artifact, **the human-audio
validation gate for the real IndicF5 GPU generation path is closed.**
This confirms the generation pipeline built in Milestones 1–4 and
installed by Phases A–G produces genuinely intelligible Hindi speech on
a freshly-provisioned machine. It does **not** confirm production audio
quality, does **not** constitute a trained or fine-tuned custom voice
model (IndicF5's published checkpoint is used as-is, unmodified), does
**not** mean any training has occurred in this project, and does
**not** mean Core integration (wiring this generator into the main
Aarya Voice Lab application) is complete — that remains a distinct,
future milestone, out of scope here.

**Full real-repo test suite** (run separately from the clean-room
copy, against the actual project source at `C:\Projects\Aarya-Voice-Lab`):
1099 passed, 9 skipped, 1 failed — the failed test
(`test_run_stage_executes_in_a_real_interpreter`) is the same
pre-existing, unrelated failure present in every baseline run this
entire session (a `bin/python`-vs-`Scripts/python.exe` fixture-shape
issue in an unrelated synthetic-pipeline test, not touched by any
Phase A–G work). No regressions.

## Installer / release-readiness audit

An audit-and-hardening pass over everything Phases A–G built, run after
the human-validation gate closed, to determine whether the current
installer architecture is robust enough to become the foundation for a
final Windows installer. Not a redesign: every fix below is a small,
evidence-backed correction to something already built, found either by
reading the code against the checklist below or by exercising it live
against real hardware and the real HuggingFace account.

**Five real defects found and fixed, all with live before/after
evidence:**

1. **`check_repo_access()` never actually detected gating.**
   `hf_auth_worker.py`'s `_run_check_repo_access()` called
   `HfApi.model_info(repo_id)` and treated any non-exception result as
   `{"accessible": True, "gated": False}`. Confirmed live: HuggingFace
   serves a gated repo's metadata to *any* caller, approved or not,
   anonymous or not (`model_info()` on `meta-llama/Llama-2-7b-hf`
   succeeded with zero credentials) — `GatedRepoError` is raised by an
   actual file-download call, essentially never by `model_info()`. This
   function reported every reachable repo as ungated, including
   IndicF5's own gated repo. Fixed to read `ModelInfo.gated` and, for a
   gated repo, conservatively report `accessible=False` with an honest
   explanation (this metadata-only check cannot confirm per-account
   download approval — only a real download attempt, which
   `indicf5_provisioning_worker.py`'s already-correct `GatedRepoError`
   handling performs, can). Verified live against three repos before/
   after the fix (`ai4bharat/IndicF5`, `meta-llama/Llama-2-7b-hf`,
   `bert-base-uncased`); regression tests added
   (`tests/test_hf_auth.py`, including one real, capability-gated
   integration test).
2. **No CLI command exposed HuggingFace authentication at all.**
   `pipeline.hf_auth.prompt_and_login_interactive()` existed and was
   already tested, but nothing in `cli/main.py` called it — every token
   entered this entire session was via a Python REPL, not anything an
   installer's end user could run. Directly violates this audit's own
   requirement E ("Token/API-key entry must be possible during installer
   setup"). Added `aarya-voice hf-login` (idempotent — reports "already
   authenticated" and exits 0 without prompting if a valid credential
   exists; `--force` to re-enter one; the token is never printed, matches
   `pipeline.hf_auth`'s existing no-token-in-output guarantee). Verified
   live against the real, already-authenticated account; 3 new tests in
   `tests/test_cli.py`, including one asserting a secret token value
   never appears in captured stdout/stderr.
3. **`verify_environment()`'s STOP CONDITIONS asserted a state it never
   checked.** For any TTS-spec check, the credential/gated-model blocker
   text unconditionally claimed *"None is configured, and none will be
   configured automatically"* and *"STOP and obtain approval before
   proceeding"* — reproduced live on this machine's own `tts-check`,
   which has a real, working HuggingFace login and a fully-downloaded,
   verified model, and still printed both false claims verbatim. Root
   cause: `environment.verify` is deliberately offline/read-only (its own
   docstring) and structurally cannot know the live credential/download
   state — but its blocker text asserted a specific state anyway. Fixed
   to describe the *requirement* honestly without asserting a state this
   module cannot observe, pointing to `aarya-voice indicf5-report` (which
   *can* check) instead. Still correctly listed under STOP CONDITIONS
   (this check genuinely cannot verify the state, so conservative
   flagging is still right) — only the false claim was removed.
4. **The canonical, installer-built environment was not what actually
   ran by default.** `pipeline.indicf5_generation.CANDIDATE_ENV_NAMES`
   tried `env-tts-windows-gpu` (this project's original, ad hoc
   Milestone 1–4 dev environment) *before* `env-tts` (the canonical name
   `scripts/install_env.sh` actually builds, and the one every Phase A–G
   smoke test forced itself onto via an explicit override). On this
   reference machine, where both exist, any caller that constructs
   `IndicF5VoiceGenerator()` *without* an override — the realistic
   default for anything outside this installer's own smoke test —
   silently got the uninstalled, non-canonical environment instead.
   Confirmed live before/after: `autodetect_tts_python()` returned
   `.envs/env-tts-windows-gpu\Scripts\python.exe` before the fix,
   `.envs/env-tts\Scripts\python.exe` after. Reordered so the
   installer-provisioned environment is genuinely what gets used by
   default; the old name is kept only as a fallback for machines that
   still have it. Matching stale docstrings (`indicf5_generation.py`,
   `indicf5_generation_worker.py`) that described the ad hoc environment
   as primary were corrected to match.
5. **No unit test existed for the insufficient-disk path at all** (not
   "not live-tested" — genuinely zero coverage, mocked or otherwise) for
   `check_disk()`'s `NOT_AVAILABLE` branch. This audit's own requirement
   H asks explicitly what covers this; the honest answer had been
   "nothing." Added two deterministic tests
   (`tests/test_environment_audit.py`) mirroring the existing VRAM-tier
   mocking pattern.

**Live tests performed against real hardware and the real account,
newly covering scenarios Phases A–G had not exercised this way:**

- **Idempotent re-run against an existing, valid environment**:
  `scripts/install_env.sh env-tts --cuda` against the real, already-built
  `.envs/env-tts` cleanly refused (`ERROR: .envs/env-tts already exists.
  Remove it deliberately before rebuilding.`, exit 1) without touching
  it — confirmed the environment's torch install was untouched afterward.
- **Re-provisioning against already-cached, valid model assets** (the
  real HuggingFace cache, not Phase G's isolated one): `provision()`
  completed in 5.8s with all five files reported `already_cached`,
  reusing everything.
- **Invalid credential**: `login_with_token()` with a deliberately
  garbage token was cleanly rejected (`HFAuthError: token validation
  failed (HTTPError)`); confirmed the real, working credential was
  untouched afterward (validate-before-persist held under a real
  failure, not just in code review).
- **Gated access classification**: see defect 1 above — now verified
  correct against a real gated-and-approved repo, a real
  gated-and-unapproved repo, and a real public repo.

**Cited from Phase G (not re-run — already real, already sufficient)**:
missing credential (empty `HF_HOME`), network failure during
authentication (a real, organic `WinError 10054` TLS reset — struck
*again*, repeatedly, during this audit's own live testing, each time
handled identically correctly: clean classification, no crash, no leaked
token), interrupted/partial installation, corrupted model asset recovery.

**NOT LIVE-VALIDATED, stated honestly, with what covers each instead:**
GPU below the required VRAM threshold (`test_vram_tier_below_3gb_is_
incompatible` and three sibling tests, mocked); unsupported/non-NVIDIA
GPU (`test_missing_gpu_is_optional_not_an_error`,
`test_check_gpu_stays_nvidia_specific_even_when_a_non_nvidia_gpu_is_
present`, mocked); insufficient disk (the two new tests above, mocked —
previously nothing). None of these three were reproduced on real
hardware: doing so would mean damaging or reconfiguring this machine's
actual GPU/disk state, which this audit's own instructions rule out.

**CPU fallback**: unchanged from Phase B's own honest disclosure —
code-supported (IndicF5's inference path falls back to CPU when CUDA is
unavailable) but never measured for this model, and
`TTS_SPEC.cpu_caveat` says so explicitly. This audit did not attempt a
live CPU generation run; doing so was not among its live-testing
priorities and risked a very long (untimed) blocking call for a
capability already accurately marked experimental.

**Security**: full diff and every new/changed file scanned for
token/secret/password/API-key patterns — none found. Confirmed no
`.wav`/`.safetensors`/`.bin`/`.envs` paths staged. No Windows security
control (Smart App Control, Code Integrity, Defender) was touched or
disabled by anything in this audit.

**Verdict**: see the audit's own final report for the full 26-point
readiness classification. In summary: the installer/provisioning
architecture is sound and the fixes above close every concretely
evidenced gap found; readiness is **CONDITIONAL** specifically because
three hardware/resource-edge scenarios remain unit-tested only (stated
above), and because no actual packaged/distributable Windows installer
artifact exists yet or has been through its own install lifecycle —
this audit hardened the provisioning *architecture* `scripts/
install_env.sh` + the `aarya-voice` CLI already expose, not a
double-clickable installer, which remains future work.

## Windows installer artifact

The deferred decision `docs/WINDOWS_RELEASE.md` named explicitly ("a
fully relocatable... installation layout is a larger, separate
architectural decision this task does not make on its own") — a real,
packaged, double-clickable Windows installer built on top of the
now-hardened provisioning architecture above.

**Framework decision (stopped for and confirmed before implementation,
per this milestone's own instruction not to improvise a major
architectural choice): Inno Setup.** No installer framework existed in
this repository or on the reference machine (checked: NSIS, Inno Setup,
WiX/dotnet, Chocolatey — none present; `winget` and PowerShell were).
Compared against the smallest-viable-options this milestone named (NSIS,
WiX/MSI, MSIX, Tauri, Electron, a pure PowerShell bootstrapper): Inno
Setup is free, a single ~3 MB compiler with no other toolchain
dependency, produces a native wizard (progress pages, install-location
picker, Add/Remove Programs entry, `/VERYSILENT` unattended mode) while
still being simple enough to orchestrate the *existing* provisioning
logic via `Exec()` rather than reimplementing it, and is by far the most
common real-world choice for exactly this shape of problem (a Python
application installer). WiX/MSI was rejected as disproportionate
complexity (needs the .NET SDK, verbose XML authoring) for a
single-user tool; MSIX and Tauri/Electron were rejected as the wrong
shape of tool entirely (sandboxed app-container semantics for MSIX;
whole new GUI-application frameworks, not installer tools, for
Tauri/Electron). Installed via `winget install JRSoftware.InnoSetup`
(6.7.3) — a real, hard-to-reverse system change, confirmed with the
operator before running it.

### Architecture

`installer/AaryaVoiceLab.iss` copies the application source (`src/`,
`scripts/`, `requirements/`, `configs/`, `schemas/`, `docs/`,
`manifests/`, `pyproject.toml`, `README.md`, `LICENSE` — excludes
`.git`, `.envs`, caches, generated data/audio, and the test suite) to a
per-user, no-admin-required location (`%LocalAppData%\AARYA Voice
Lab`), then its `[Code]` section orchestrates the same steps a human
operator has run manually throughout Phases A–G and the audit above:

1. **`scripts/install_env.ps1`** -- a new, native-Windows PowerShell
   port of `install_env.sh`, added specifically because a fresh
   end-user machine cannot be assumed to have Git Bash. Mirrors the
   bash script's logic exactly (same env names, same requirements
   files, same torch index URLs, same version pins) -- `requirements/
   tts.txt` and `environment.specs` remain the single source of truth
   for what gets installed; nothing is duplicated, only the shell.
2. **`scripts/_installer_steps.py`** -- two small, installer-only
   helpers (`login`, `provision`) that call the *existing*
   `pipeline.hf_auth`/`pipeline.indicf5_provisioning` functions
   directly. Needed because `aarya-voice hf-login`'s interactive
   `getpass()` has no console to read from inside a hidden `Exec()`
   child process, and because `indicf5-report` deliberately never
   downloads anything (verify-only) -- provisioning needs an explicit
   trigger on a machine with nothing cached yet. Both retry on a
   classified *network* failure only (this session's own repeated,
   documented flakiness against huggingface.co), never on a genuine
   rejection.
3. **`aarya-voice indicf5-report`** (unchanged) -- the real GPU smoke
   test, run exactly as built in Phase F/G.

`scripts/generate_installer_defines.py` reads `configs/release.yaml`
(the release metadata `docs/WINDOWS_RELEASE.md` already established)
and writes `installer/AaryaVoiceLabDefines.iss` (gitignored, generated,
never a second source of truth) so the installer's product
name/version/publisher/app-id are never hand-duplicated.

**Build** (reproducible, two steps):
```
<env-tts-python> scripts/generate_installer_defines.py
"<Inno Setup install dir>\ISCC.exe" installer/AaryaVoiceLab.iss
```
Output: `installer/dist/AaryaVoiceLab-Setup.exe` (gitignored build
output, matching this project's existing `dist/` convention).

**ONLINE installer, not offline**: downloads PyTorch/CUDA wheels
(~2-3 GB) and the IndicF5 model (~1.4 GB) during setup; does not work
without internet access, and the installer never claims otherwise.

**Uninstall safety**: mirrors `aarya_voice_lab.release.
is_safe_to_delete_without_confirmation()` and `configs/release.yaml`'s
`uninstall_protected_directories` exactly -- `source/`, `data/`,
`models/`, `public_datasets/` are never deleted by the uninstaller,
confirmed live (see below) by seeding them with fake user-data files
and observing they survive a full silent uninstall while the
application files and `.envs` do not.

### Five real defects found and fixed via real-machine Phase 8 testing

Each confirmed with a live before/after run on the RTX 3050 machine, not
inferred from code review:

1. **GPU detection silently installed CPU-only wheels on a real GPU
   machine**, in two layers. First, `Exec()` with a bare
   `'nvidia-smi.exe'` failed to even launch (Inno Setup's `Exec()` does
   not reliably search PATH/System32 for an unqualified filename).
   Switching to the fully-qualified `{sys}\nvidia-smi.exe` *still*
   failed: `Setup.exe` itself is a 32-bit process, so `{sys}`
   (System32) is WOW64-redirected to `SysWOW64`, where the 64-bit-only
   `nvidia-smi.exe` does not exist. Fixed with Inno Setup's documented
   `{sysnative}` escape from that redirection. Confirmed live:
   `nvidia-smi launched=False` before, `launched=True exit=0` after,
   and the resulting `env-tts` correctly built with `torch==2.13.0+cu126`
   (previously silently built CPU-only).
2. **`install_env.ps1` aborted on pip's own normal retry-warning
   output.** `$ErrorActionPreference = "Stop"` made Windows PowerShell
   5.1 treat *any* stderr line from a native command (including pip's
   own transient-network retry warnings -- not a real failure, pip
   retries internally and often succeeds) as a fatal error, aborting the
   whole environment build before pip's own retry logic could finish.
   Confirmed live: a real, valid environment build failed after 49
   seconds on exactly this pattern. Fixed to `"Continue"` -- every
   external command already checks `$LASTEXITCODE` explicitly, which is
   the sole correct source of truth here, not stderr chatter.
3. **A real, valid HuggingFace token was misreported as rejected.**
   `hf_auth_worker.py`'s `_run_login()` (added for the installer's own
   non-interactive token path) caught every exception generically as
   "token validation failed," so a valid token that happened to hit this
   session's own documented network flakiness was indistinguishable
   from an actually-invalid one -- reproduced live, then fixed in two
   passes: first to mirror `_run_check()`'s `HfHubHTTPError`/401
   handling, which *itself* turned out not to fire (`HfApi(token=...).
   whoami()` raises a plain `requests.exceptions.HTTPError`, confirmed
   empirically via its MRO to include `HfHubHTTPError` as a *subclass*,
   not the type actually raised by this call shape) -- corrected to
   catch the broader `requests.exceptions.HTTPError` base class, which
   covers both. Verified live: an invalid token now reports "the token
   was rejected (401) -- invalid or expired" instead of a misleading
   generic message; a real, valid token authenticates correctly.
   Regression test added (`tests/test_hf_auth.py`, real/capability-gated).
4. **A genuinely silent (`/VERYSILENT /SUPPRESSMSGBOXES`) install hung
   indefinitely**, waiting on a `MsgBox()` a human was never present to
   click -- confirmed live (required a manual `taskkill` to unblock;
   the operator saw this exact dialog appear during testing).
   `/SUPPRESSMSGBOXES` only suppresses Inno Setup's own built-in
   dialogs, never a script's own `MsgBox()` calls. Fixed with a
   `SafeMsgBox` wrapper that checks `WizardSilent()` and logs instead
   of blocking when true.
5. **The fix for #4 then broke uninstall entirely.** `WizardSilent()`
   is install-wizard-only; calling it from `CurUninstallStepChanged`
   raised a *fatal* internal error ("Cannot call 'WizardSilent' function
   during Uninstall"), which aborted the whole uninstall before a single
   file was removed -- confirmed live: a real uninstall run left every
   application file in place. Fixed with a second wrapper,
   `SafeMsgBoxUninstall`, using `UninstallSilent()` (the correct,
   context-specific equivalent) instead.

**Security incident, found and closed during this same testing:** an
earlier version of this script accepted the HuggingFace token as a
`/HFTOKEN=...` command-line parameter, to support silent/unattended
installs. Inno Setup itself -- before any of this script's own code
runs -- unconditionally records its own full command line, including
every `/PARAM=value`, into the `/LOG` setup log as a "Setup command
line:" entry. A real, valid token was captured this way during testing
and written in plaintext to a local log file. **Immediately on
discovery**: the two affected log files were located precisely (by
filename, without ever re-typing or re-displaying the secret value
itself) and deleted; the real, standard HuggingFace credential cache
(`~/.cache/huggingface/token`) was confirmed untouched and still valid;
PowerShell's interactive command history was checked and confirmed to
contain no trace (the automated tool invocations that touched the token
never went through a logged interactive console). The exposure was
local to this machine only, in files created and deleted within
minutes, never transmitted anywhere. **Root-cause fixed, not just
patched around**: silent-mode token entry now reads from an
`AARYA_INSTALLER_HFTOKEN` *environment variable* set on the launching
process, never a command-line parameter -- an environment variable is
never part of a process's command line and is not subject to Inno
Setup's own logging. Verified live, twice, that the corrected mechanism
authenticates successfully with zero occurrences of the parameter name
anywhere in the resulting setup log.

**One minor, non-blocking limitation found and accepted rather than
over-engineered a fix for**: some `__pycache__` directories (created at
runtime when Python imports modules, never part of the `[Files]`
manifest Inno Setup's uninstaller tracks) survive uninstall as harmless,
empty-of-user-data debris under the removed application tree. The
critical safety property -- `source/`, `data/`, `models/`,
`public_datasets/` and their contents always survive -- was verified
correct both before and after the uninstall fix above.

### Real installer validation (RTX 3050 machine, the actual compiled
### `.exe`, not the underlying CLI)

Every item below is the *artifact* itself, run via `Start-Process` with
`/VERYSILENT /SUPPRESSMSGBOXES`, polled via its own `/LOG` output --
not a shortcut through the CLI directly:

- **Fresh install** (no pre-existing `.envs/env-tts`, new directory):
  full lifecycle, ~13 minutes end-to-end (CUDA wheel download dominates)
  -- GPU detection → runtime install → auth (existing credential reuse)
  → model download → real GPU smoke test → **READY**. Repeated after
  each fix, most recently as the definitive final confirmation with
  every fix combined.
- **Existing environment / existing cache** (Phase 6.B/C): re-running
  the installer over an already-built `env-tts` and already-cached
  model skipped the ~11-minute environment build entirely (detected via
  `.envs\env-tts\Scripts\python.exe` presence, matching `install_env.
  ps1`'s own refuse-to-overwrite design) and reused the cached model
  (`already_cached`, seconds not minutes) -- full run completed in
  under 4 minutes, reaching READY.
- **Reinstall over an existing installation** (Phase 6.G): identical to
  the above -- confirmed non-destructive (existing `.envs/env-tts` and
  cached model both reused, not rebuilt or re-downloaded).
- **Uninstall**: confirmed twice (once exposing defect #5 above, once
  confirming the fix) -- application files removed, `.envs` removed,
  seeded fake user-data files in `source/`, `data/`, `models/`
  untouched both times.
- **Generated WAV**: mechanically re-validated after the fresh-install
  run (24 kHz, mono, 1.909 s -- identical properties to every prior
  verified generation this session); sent to the operator. Same
  text/model/pipeline already human-confirmed intelligible earlier in
  this project, so this proves the *installer* delivers the
  already-verified runtime, not a new intelligibility check.
- **Invalid HF token via the installer**: exercised indirectly and
  fixed (see defect #3) -- an invalid token now correctly reports
  "rejected (401)", never a generic or misleading failure.
- **Network failure during authentication**: this session's own
  repeated, organic `WinError 10054` flakiness struck the installer's
  own auth/reuse checks multiple times during this exact testing;
  `_installer_steps.py`'s retry logic (network-classified failures
  only, up to 3 attempts) absorbed it correctly every time, matching
  the same principle validated during the Phase G/audit work.

**NOT LIVE-VALIDATED through the installer artifact specifically**
(already covered via the underlying CLI in Phase G/the audit, not
re-run through the compiled `.exe` for time reasons): corrupted model
asset recovery, insufficient disk, unsupported GPU/VRAM. Application
launch is honestly limited to opening a command prompt with a usage
hint -- this project has no packaged GUI application yet to launch
(the `frontend/` directory is a design-system prototype requiring
Node.js, not a finished desktop app; launching it is out of scope for
this CLI/backend-focused installer).

**Signing**: **UNSIGNED DEVELOPMENT BUILD.** No code-signing certificate
exists for this project. A production release would need one (and
would need Windows SmartScreen reputation to build up, or an EV
certificate to bypass that delay) before end users could run it without
an "Unknown Publisher" warning -- not attempted here, and not claimed
as done.
