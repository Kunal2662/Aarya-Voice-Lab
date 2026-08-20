# VL-D1 — Command Center & Operational Workspace

> Status: **first operational layer.** VL-D0's design system is now wired
> to a real (client-side) state layer, a router, and 11 workspaces. There
> is still no real voice generation, no real bulk import, no real
> pipeline execution, and no execution transport behind the Command
> Center — see "Scope and non-goals" below.

## What VL-D1 adds over VL-D0

VL-D0 delivered tokens, primitives, and one static wireframe
(`frontend/shell/index.html`). VL-D1 adds the operational app itself —
`frontend/app/index.html` — plus everything that makes it more than a
gallery of components: a router, a job/task model, an activity model, a
selection model driving the Inspector, 11 real workspaces, and a Claude
Code Command Center that is honest about not having an execution
transport yet.

## Application shell and routing

`frontend/app/main.js` is the one place that wires state to UI. It builds
the VL-D0 `<avl-app-shell>` (sidebar / workspace / inspector /
activity-bar — unchanged from VL-D0), constructs the state-layer
services once, and on every navigation mounts one workspace custom
element into the shell's `workspace` slot.

Routing (`frontend/state/router.js`) is a minimal hash router
(`#/pipeline`, `#/claude`, ...) with a closed `DESTINATIONS` list of
exactly the 11 workspaces VL-D1's spec names. No history-API server
config is needed — this matters because the eventual desktop shell
(still an open choice, see `docs/VLD0_DESIGN_SYSTEM.md` "Why no
framework") may not be a conventional web server. An unrecognised hash
falls back to `command-center` rather than rendering nothing.

## State layer (`frontend/state/`)

Six small, framework-free modules, all `EventTarget`-based pub/sub, all
purely in-memory (no persistence, no network):

- **`job-model.js`** — `Job` shape (id, type, status, start/end time,
  progress, current stage, error, related entity, logs reference) and
  `JobStore`. Job status renders through the **`pipeline_stage`**
  status-vocabulary domain from VL-D0 (`not_started/queued/running/
  success/warning/failed/blocked/paused/cancelled`) rather than a second,
  parallel vocabulary meaning the same thing — a job's status badge and a
  pipeline stage's status badge share one definition and one set of
  colors.
- **`activity-model.js`** — `ActivityEvent` shape and `ActivityStore`.
  `ActivitySource` is the closed 14-value list from VL-D1 §13
  (import/validation/quality/vad/segmentation/review/
  speaker_verification/model/calibration/preview/claude/system/security/
  error). Severity renders through a new **`activity_severity`** domain
  (info/success/warning/danger) added to `frontend/tokens/status.json`.
  `fromCommandCenterEntry()` adapts a real
  `identity/command_center.py` `ActivityEntry.to_dict()` record into this
  shape without duplicating its sanitisation — that log is already
  vector/path-redacted before this module ever sees it.
- **`selection-model.js`** — the single `{kind, id, data}` selection the
  Inspector renders (see below).
- **`router.js`** — described above.
- **`synthetic-fixtures.js`** — the **only** source of batch/recording/
  job/activity/voice/model data in VL-D1. Every id is prefixed
  `synthetic-`, and every record carries `is_synthetic: true` so nothing
  here can be mistaken for real dataset content even out of context.
  Nothing in this file reads `data/` or `source/`.
- **`command-executor.js`** — see "Claude Code Command Center" below.
- **`claude-context.js`** — see "Claude context model" below.

## Job/task model

Matches VL-D1 §7 exactly: id, type, status, start/end time, progress,
current stage, error, related entity, logs reference. `JobStore` is
strictly a client-side record — it runs nothing. `current()` /
`recent()` / `failed()` are the three views the Command Center and
Activity Bar read; `isTerminal()` is the one place "is this job still
doing something" is decided, so the Command Center and the Activity Bar
can't drift into disagreeing about it.

## Pipeline visualization

`avl-workspace-pipeline` renders `avl-pipeline-stage-track` (VL-D0) fed
directly from `frontend/contracts/generated/pipeline_stage.json` — the
same generated export VL-D0 built, still exported from
`pipeline/stages.py`, never recomputed. The phase-2/phase-3+ split and
the speaker-identity boundary are rendered exactly as the backend
reports them.

`avl-pipeline-stage-node` gained one new capability in VL-D1: it is now a
real `<button>` that dispatches `avl-stage-select` on click/Enter/Space
(VL-D1 §12: "support stage selection, stage inspector"). This is the one
change to an existing VL-D0 component in this phase — additive only, the
node's visual output and the VL-D0 browser-smoke test are both unchanged
(re-verified, see Testing below).

## Inspector

`avl-inspector-router` (new) renders one of seven fixed views —
`batch`, `recording`, `pipeline-stage`, `job`, `activity`, `voice`,
`model` — driven entirely by `selection-model.js`. Every workspace that
lets you pick something calls `selectionModel.select(kind, id, data)`
with data it already has in hand; the Inspector never re-fetches. Rows
render through progressive disclosure — a compact label/value list, with
status always shown through the existing status-badge component rather
than a second color scheme.

## Activity Center

`avl-workspace-activity` renders `avl-activity-timeline` (new) with a
native `<select>` source filter. Events sort newest-first. This is the
same `ActivityStore` the Command Center's "recent activity" panel reads
— one store, two views.

## Command Center

`avl-workspace-command-center` is the SYSTEM / PIPELINE / JOBS / ACTIVITY
dashboard VL-D1 §6 asks for. Every number on it is real or honestly
absent:

- **SYSTEM** — Core/Storage render `ready` (this is a local, offline
  static app — there is nothing else to report); Runtime/Hardware render
  `UNKNOWN` through the `hardware` domain (`CapabilityState`) because no
  capability probe has been wired into the browser yet; Claude reflects
  `executor.available()` honestly.
- **PIPELINE** — "Completed (stages implemented)" and "Total stages"
  come straight from the generated `pipeline_stage.json` contract, not a
  guess. "Running"/"Failed" come from `JobStore`. "Queued"/"Warnings"
  render `0` because nothing produces those yet in VL-D1 — shown as real
  zero counts (the store genuinely has none), not as "not available".
- **JOBS** — `avl-job-list` over the full `JobStore`.
- **ACTIVITY** — `avl-activity-timeline` over the 5 most recent events.

## Claude Code Command Center

VL-D0 built the visual shell (`avl-claude-command-shell`) and declared
the context model as an interface only. VL-D1 makes as much of this
*operational* as is honestly possible without building the thing its own
governing spec forbids.

### Why there is still no execution transport

`identity/command_center.py` has always been explicit: it "executes
nothing — the desktop invokes the ordinary CLI so every run passes the
same gates and audit log." VL-D1's spec forbids an unrestricted terminal
or arbitrary shell execution exposed to the browser, and lists "Claude
requires unrestricted shell access" as a hard-stop condition. No
browser-safe transport exists in this project yet — there is no HTTP API
server and no desktop-shell IPC bridge to invoke the CLI through (the
desktop runtime itself is still an open choice from VL-D0). Building one
of those is out of VL-D1's scope on its own; faking one, or fabricating
command output, would violate the project's core honesty requirement.

So `frontend/state/command-executor.js` defines the `CommandExecutor`
interface a real transport will implement later (`available()`,
`execute(command)`), and ships exactly one implementation for VL-D1:
`NullCommandExecutor`, which always reports `available() === false` and
answers `execute()` with `outcome: "not_available"` and a plain-language
explanation — never fabricated output, never a silent no-op. Every UI
surface that touches the executor (`avl-workspace-claude`,
`avl-claude-fix-flow`, the Command Center's SYSTEM panel, the Settings
workspace) shows this state honestly rather than hiding it.

This is not a hard stop on the rest of VL-D1 — building the honest
"not connected" state is not the same as needing unrestricted shell
access, so the remaining 10 workspaces, the job/activity/selection
model, and the whole Command Center dashboard proceed normally.

### Claude context model

`frontend/contracts/claude-context-model.json` (VL-D0) declared the
shape; `frontend/state/claude-context.js`'s `buildClaudeContext()` now
actually builds it: `active_view`, `selection`, `recent_commands`,
`recent_activity` (bounded to 10, reshaped to only
`source/severity/summary/timestamp`), `git_state`, `task_id`,
`error_summary`, `permissions` (defaults to `read_only`, never a wider
tier by default). Every value passes through `redactDeep()` before
leaving the module:

- any key whose name contains `secret`, `credential`, `password`,
  `token`, `api_key`, `apikey`, or `private_key` is replaced with a
  fixed redaction marker, regardless of its value;
- any string value containing a run of 20+ alphanumeric/`_`/`-`
  characters — long enough to plausibly be an opaque credential — is
  masked in place, even under an innocuous key name (defense in depth:
  the key-name check alone assumes callers name their fields honestly);
- short strings (e.g. a 7-12 character Git short hash) are left alone —
  masking those would make the context useless without adding safety;
- every string is truncated at 2000 characters.

`avl-workspace-claude` renders the exact, redacted JSON this function
produces in a read-only preview panel, so what would be sent is never
a mystery.

### Fix workflow

`avl-claude-fix-flow` (new) implements the VL-D1 §16 flow as a real,
if honestly bounded, state machine:

```
ERROR -> VIEW DETAILS -> ASK CLAUDE -> CLAUDE ANALYSIS -> PROPOSE FIX
-> USER APPROVAL -> EXECUTION -> TEST -> RESULT -> AUDIT EVENT
```

"View details" and "Ask Claude" are real, interactive steps — the latter
calls the injected `CommandExecutor`. With `NullCommandExecutor`
(VL-D1's only implementation), the flow stops there and shows the
executor's honest `NOT_AVAILABLE` message; the remaining six steps are
rendered as an upcoming-steps strip, never as if they already ran. A
real executor (VL-D2+) plugs into the same `execute()` contract and lets
the flow progress further — this component does not change when that
happens, only which executor it's given.

## Voice workspace

`avl-workspace-voices` shows the full future lifecycle contract —
GENERATE → PREVIEW → LISTEN → FEEDBACK → REGENERATE → COMPARE → ACCEPT —
with each step marked implemented or not. Today only PREVIEW / LISTEN /
FEEDBACK / COMPARE exist (VL-V0, from VL-D0); GENERATE and REGENERATE
render `(not implemented)` rather than a live-looking control. All data
is synthetic; no real training, embeddings, or recordings are involved.

## Models workspace

`avl-workspace-models` lists the supported compute backends straight
from `frontend/contracts/generated/compute_backend.json`
(`identity/runtime.py`'s `ComputeBackend`) — CPU, ROCm, CUDA, Metal,
OpenCL, Vulkan, XPU, Other, alphabetically, no vendor privileged — plus
synthetic example model cards showing generic runtime/backend/hardware-
compatibility fields.

## Calibration workspace

Two distinct calibration concepts, shown side by side and never
conflated:

1. **Hardware/runtime calibration** — a new `hardware_calibration`
   status domain (`UNCALIBRATED/NOT_TESTED/CALIBRATING/CALIBRATED/
   FAILED/UNKNOWN`) for the future AI Calibration Engine (VL-D15)
   profiling *this host*. No engine exists, so this always shows
   `UNCALIBRATED` with `avl-metric-placeholder`'s honest "Not available"
   for every CPU/RAM/GPU/VRAM/runtime/backend/compatibility field.
2. **Target-speaker verification calibration** — the existing VL-D0
   `avl-calibration-panel`, unchanged, still mirroring
   `identity/calibration.py`'s `CalibrationState` exactly.

These are genuinely different questions ("has this machine been
benchmarked" vs. "does this verification threshold have real evidence
behind it") and VL-D1 keeps them in separate panels with separate
vocabularies rather than reusing one badge for both.

## Import workspace and the dataset access gate

`avl-workspace-import` composes `avl-import-drop-zone` (drag/drop or
file-picker selection — lists file names only, hashes/validates/imports
nothing) with a **real** read of the dataset access gate.

`pipeline/dataset_gate.py`'s `evaluate_gate()` only inspects Git state,
config, and directory protection — it never reads audio — so it's safe
to call for real. `scripts/export_dataset_gate_status.py` does exactly
that, with every attestation left at its default `False`, and writes the
result to `frontend/contracts/live/dataset_gate_status.json`.

This file is deliberately **not** part of the frozen, drift-tested
`frontend/contracts/generated/` set from VL-D0: `evaluate_gate()`'s
output legitimately changes from run to run (branch, working-tree
cleanliness) even with zero code changes, so committing and drift-
testing a snapshot of it would fail on every unrelated commit. Instead
it lives under `frontend/contracts/live/`, is listed in `.gitignore`,
and the Import workspace treats a missing file as an honest "gate not
evaluated in this session" state — never as "access granted" or "access
denied" by default. Run `python scripts/export_dataset_gate_status.py`
to check the real, current gate state at any time; nothing about running
it can open the gate, since `explicit_approval` still defaults to
`False` and this script never sets it otherwise.

## Settings workspace

Appearance (the VL-D0 theme toggle), Storage (a static notice: no cloud
storage, cloud dataset, cloud model storage, or cloud audio processing
is configured or configurable — there is no field for any of them),
Runtime (the same vendor-neutral backend list as the Models workspace),
Logging (a placeholder metric — no audit-log summary endpoint is wired
into the browser yet), Claude integration (the same honest
`executor.available()` state as everywhere else).

## Accessibility

Unchanged from VL-D0's contract, re-verified against the new surface:
`avl-pipeline-stage-node` is a real `<button>` with an `aria-label`
describing its name and status; `avl-workspace-state`'s loading state
announces via the shared `_announce()` live region; every new status
badge still carries a text label, never color alone; `avl-workspace-
activity`'s filter is a native `<select>` (full keyboard support for
free); focus-visible styling is untouched (still `css/base.css`, not
duplicated).

## Testing

```sh
cd frontend && node --test tests/*.test.mjs
```

New in VL-D1 (29 total, up from VL-D0's 10):

- `tests/state-model.test.mjs` (14 tests) — `Job`/`JobStore`,
  `ActivityEvent`/`ActivityStore`, `SelectionModel`, `DESTINATIONS`
  matches the spec's 11 workspaces exactly, `redactDeep`/
  `buildClaudeContext`'s redaction and bounding behaviour, and
  `NullCommandExecutor`'s honesty contract.
- `tests/app-smoke.test.mjs` (5 tests, real headless Chromium) —
  navigates through all 11 workspaces asserting each one mounts and the
  sidebar's active state follows; batch selection and pipeline-stage
  selection both update the Inspector with the real selected data;
  the Import workspace never claims access without evidence; the Claude
  fix-flow's terminal state is the honest "no execution transport"
  message.

VL-D0's original suite (10 tests, `tests/tokens.test.mjs` /
`css-variables.test.mjs`, `contracts-drift.test.mjs`,
`status-vocabulary.test.mjs`, `browser-smoke.test.mjs`) re-runs
unmodified and still passes, confirming the one component change
(`pipeline-stage-node.js`'s new click affordance) didn't break VL-D0's
wireframe.

Backend: the full existing `pytest` suite (472 tests) and `ruff check .`
were re-run before and after this work and remain unmodified and
passing. `tests/test_source_protection.py` was specifically re-checked
given VL-D0's filename-collision lesson (`tokens.css` vs. the
secret-filename scanner) — no new file under `frontend/` or `scripts/`
triggers it.

## Security boundary

Nothing in VL-D1 weakens an existing invariant:

- **Source immutability / dataset gate** — `evaluate_gate()` is called
  read-only, with every attestation defaulting to `False`; nothing in
  the UI can set `explicit_approval`.
- **Speaker identity boundary** — the recording workspace's fields are
  exhaustively technical (format, duration, sample rate, quality,
  processing state); no speaker/identity field exists anywhere in
  `state/synthetic-fixtures.js`'s recording shape or
  `components/recording-row.js`.
- **Execution permissions / audit log** — no command executes; the one
  executor VL-D1 ships is `NullCommandExecutor`.
- **Secret scanning** — re-verified clean (see Testing).
- **Offline behaviour** — every `fetch()` call in VL-D1 targets a
  same-origin static file (`../contracts/...`, `../tokens/...`); there
  is no cloud storage, cloud dataset, cloud model, or cloud audio
  affordance anywhere in the 11 workspaces.

## Scope and non-goals (VL-D1)

Not built, per the governing spec: real bulk import (files are listed,
never hashed/validated/written), real pipeline execution, real voice
generation/training/embeddings, a functioning Claude execution
transport, real hardware/calibration probing, cloud storage of any kind.

## Known limitations

- `avl-workspace-command-center`'s "Queued" and "Warnings" metrics are
  real zero counts from the current (empty-of-those-states) synthetic
  fixtures, not a signal that queuing/warning support doesn't exist —
  worth re-reading once a real job producer exists.
- The Inspector's `job` and `activity` selection kinds are wired in
  `inspector-router.js` but no current workspace dispatches a selection
  into them yet (`avl-job-list`/`avl-activity-timeline` emit their own
  events — `avl-job-select` isn't yet connected to `selectionModel` by
  any workspace). Left in place as the documented target shape rather
  than removed, since VL-D2's job-detail view will want it immediately.
- No visual regression (screenshot) testing exists, same as VL-D0.
- Hardware/runtime values are `UNKNOWN`/"Not available" everywhere —
  no capability probe has been wired into the browser context yet.

## Next

**VL-D2 — Bulk Recording Import & Dataset Workspace**: a real importer
behind `avl-import-drop-zone` that computes content hashes and enforces
`security/source_protection.py`'s immutability rules before anything
touches `source/`; wire `avl-job-select` into the Inspector; begin
designing the actual execution transport the Command Center's
`CommandExecutor` interface is waiting for.
