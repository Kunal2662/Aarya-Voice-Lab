# VL-D8 — Calibration Application & Validation Loop

AARYA Voice Lab only. Not a JARVIS milestone; nothing in this phase touches
Aarya Core or any other project.

## Purpose

**VL-D7: calibration recommendation.** The AI Calibration Engine could
capture a hardware snapshot, assess evidence readiness, select a
strategy, and *propose* a bounded parameter adjustment. Nothing
consumed the proposal — it sat in a log.

**VL-D8: calibration application + validation.** Closes that loop. A
proposed adjustment can now be **applied** to a real generation queue,
and its runtime effect can be **validated** with a real, deterministic
measurement over synthetic fixtures — never a fabricated number, and
never a voice-quality claim.

## Architecture

### A third independent axis: `application_state`

VL-D7 already established two deliberately independent state axes on a
`CalibrationProfile`:

* `run_state` (`CalibrationRunState`) — did the engine's own process
  complete?
* `calibration_state` (`identity.calibration.CalibrationState`, reused
  unchanged) — is there real evidence behind the profile?

VL-D8 adds a third, equally independent axis:

* `application_state` (`ApplicationState`: `PROPOSED` / `APPLIED` /
  `VALIDATED`) — has a proposed adjustment actually been applied to the
  generation pipeline, and has its effect been measured?

All three axes can move independently. A profile can be
`run_state=CALIBRATED`, `calibration_state=UNCALIBRATED`,
`application_state=VALIDATED` at the same time — completely normal:
the engine finished, there still isn't enough human-evaluation evidence
for anything beyond `UNCALIBRATED`, and a hardware-derived runtime
parameter was applied and measured anyway (hardware readiness never
depends on evaluation evidence — see VL-D7's own readiness model).

### Application lifecycle: `apply_adjustment()`

`pipeline.calibration_engine.apply_adjustment(log, *, profile_id,
parameter_name, queue=None)`:

1. Looks up the source profile and the named adjustment within it.
2. **Re-checks bounds now**, by reconstructing a
   `CalibrationParameterAdjustment` from the stored proposal —
   `__post_init__` raises `ParameterBoundsError` if it is no longer
   self-consistent. The earlier proposal is never trusted blindly.
3. If `queue` (a live `pipeline.generation.GenerationQueue`) is
   supplied, actually sets its `max_concurrent_generations` to the
   proposed value.
4. Appends a **new** `APPLIED` profile version. The source profile is
   never edited. Provenance is tracked via `applied_from_profile_id`,
   kept deliberately distinct from `supersedes` (which retains its
   original "record this displaces as active" meaning from VL-D7's
   rollback).

Applying without a queue is legitimate — it still re-validates bounds
and records the applied value, useful when no live queue exists yet in
the caller's session.

### Validation lifecycle: `validate_calibration()`

`pipeline.calibration_engine.validate_calibration(log, *, profile_id,
queue_factory, baseline_max_concurrent=1)`:

1. Requires an `APPLIED` profile (`ValidationWithoutApplicationError`
   otherwise — validating something never applied would measure
   nothing real).
2. `queue_factory` is a zero-argument callable the caller supplies,
   returning a **fresh** `GenerationQueue` with the same synthetic
   fixture requests enqueued each call. This module still never
   constructs a `DataRoot` or a generator itself — it has no path to
   real recordings, exactly as VL-D7 established.
3. Measures **queue batch count** — a real, deterministic effect of
   `max_concurrent_generations` — before (`baseline_max_concurrent`,
   default 1) vs after (the profile's `applied_value`).
4. Appends a new `VALIDATED` profile version recording the measurement.

### Why batch count, not timing

An earlier design considered measuring wall-clock duration. Timing-based
tests are flaky by nature and would have required either real
threading (an execution-surface risk explicitly ruled out) or asserting
on noisy numbers. Batch count is the real, structural effect of
`max_concurrent_generations` — `pipeline.generation.GenerationQueue.
process_all()` genuinely processes items in batches of that size — and
it is 100% deterministic given a fixed item count and concurrency
value. **This is a queue-batching measurement, not a voice-quality
measurement.** The synthetic tone generator cannot measure voice
quality, and this module never claims it does; every validation note
says so explicitly.

### Honest `NOT_MEASURABLE`

When the fixture set is empty, or the applied concurrency produces the
same batch count as the baseline at that fixture size,
`validation.not_measurable=True` and `measured_delta` is `None` — never
a fabricated delta. This is a normal, expected outcome at small fixture
sizes (e.g. a single-item queue can never show a batching difference),
not an error.

## Bounded generation-queue concurrency

`pipeline.generation.GenerationQueue` gained an opt-in
`max_concurrent_generations` (positive integer or `None`).
`InvalidConcurrencyError` rejects zero, negative, non-integer, and
boolean values — never silently clamped. The default (`None`) preserves
byte-for-byte the pre-VL-D8 behaviour: every queued item processed as
one batch, in the same order, with the same results. Setting a value
changes only how `process_all()` groups items for `last_run_stats()`'s
bookkeeping (`item_count`/`batch_count`/`max_concurrent_generations`) —
no item's outcome depends on batch size, and no threading or
subprocess execution is introduced. The frontend mirrors this exactly
on `state/generation-model.js`'s `GenerationQueueStore` and validates
via the identical `computeBatchCount()` formula
(`state/calibration-engine-model.js`), so the browser measures the same
real effect without needing to drive its own async, UI-progress-
animated queue through a synchronous batch-processing model.

## Append-only history, preserved

Every VL-D7 guarantee holds unchanged: `CalibrationProfileLog` never
overwrites a record. `apply_adjustment()` and `validate_calibration()`
each append exactly one new profile version; repeated application or
repeated validation simply appends further versions, all of them
retained. `rollback()` (VL-D7, untouched) still works across the new
fields — rolling back to a `PROPOSED` profile correctly makes it active
again, and validating that (unapplied) record is still refused.

## Frontend

`state/calibration-engine-model.js`'s `CalibrationProfileStore` gained
`applyAdjustment()`/`validateCalibration()`, mirroring the backend
exactly in record shape and honesty rules. New components:
`avl-calibration-application-panel` (application-state badge, Apply/
Validate actions, applied parameter/value, before/after metrics,
honest `NOT_MEASURABLE`/measured display) wired into
`avl-workspace-calibration` between the proposed-adjustments table and
profile history. `avl-calibration-profile-history` rows are now
click-to-select into the Inspector (`calibration-profile` kind), and
each row's meta line shows `application_state` and, where applicable,
which profile an `APPLIED`/`VALIDATED` record came from.

## Activity / Command Center / Inspector / Claude

* **Activity**: `calibration_applied` and `calibration_validated`
  events, distinct from VL-D7's `calibration_run_completed`/
  `calibration_rolled_back`, driven entirely by the record's own
  `application_state` — never inferred.
* **Command Center**: the existing "Calibration engine" panel gained
  real `Proposed`/`Applied`/`Validated` counts, computed from
  `calibrationStore.history()` — "not available" rather than a
  fabricated number when no runs exist.
* **Inspector**: a new `calibration-profile` selection kind renders
  `run_state`/`calibration_state`/`application_state` as three
  separate fields, plus applied parameter/value/provenance and
  before/after measurement — honestly `—` before a profile is applied
  or validated.
* **Claude context**: `avl-claude-calibration-context`'s bounded shape
  gained `applied_parameter_name`, `applied_value`, and `validation` in
  its `config`, and `application_state` in its `warning` string — still
  routed through the same `NullCommandExecutor` boundary, still no
  filesystem path, no secret, no speaker field.

## Security boundary

* No real recordings accessed or modified. `pipeline.calibration_engine`
  still never imports `DataRoot` (verified by a structural
  source-inspection test) — `validate_calibration()`'s `queue_factory`
  parameter is precisely what keeps that true: the caller, not this
  module, is responsible for constructing any generator.
* No embeddings, no training, no speaker-identity field —
  `CalibrationProfile`'s new fields (`application_state`,
  `applied_from_profile_id`, `applied_parameter_name`, `applied_value`,
  `applied_at`, `validation`) carry only calibration-engine bookkeeping.
* No dataset-access gate touched.
* No arbitrary code execution: `apply_adjustment()`'s application path
  is a closed, named set (`_APPLICATION_TARGETS`) — a parameter this
  engine has no application path for is refused, not silently
  attempted.
* No specific GPU product name (RTX/GTX/GeForce/Radeon or a model
  number) anywhere in the new code.

## Hardware/runtime neutrality

Unchanged from VL-D7: `identity.runtime`'s vendor-neutral vocabulary,
`environment.audit`'s honestly-limited (NVIDIA-probe-only today)
detection, `HardwareSnapshot`'s "not confirmed, not confirmed-absent"
honesty. VL-D8 adds no new hardware probe — the concurrency parameter
it applies is derived purely from CPU core count, already established
in VL-D7.

## Testing

* Backend: 32 new tests appended to `tests/test_calibration_engine.py`
  — queue concurrency (default/valid/invalid/deterministic-regardless-
  of-batching/zero-items), application (new-profile/never-edits-source/
  real-queue-value/without-a-queue/bounds-recheck-at-apply-time/unknown-
  parameter/unknown-profile/unsupported-target/repeated-application/
  schema), validation (without-application/unknown-profile/real-
  measured-delta/honest-not-measurable/never-overwrites-prior/
  provenance-chain/schema/after-rollback), and a full propose-apply-
  validate append-only lifecycle check. Full backend regression:
  711/711 passing, ruff clean.
* Frontend: 15 new state tests
  (`frontend/tests/calibration-engine-state.test.mjs`) + 14 new
  real-browser Playwright scenarios
  (`frontend/tests/calibration.test.mjs`) covering proposal visibility,
  Apply, bounds rejection (via the same production
  `buildParameterAdjustment` path), applied-state display, before/after
  rendering, measured-delta rendering, honest `NOT_MEASURABLE`
  rendering, append-only history, Inspector selection, Activity,
  Command Center, bounded Claude context, and clean existing-workspace
  navigation. Full frontend regression: 255/255 passing (227 baseline +
  28 new).

## Known limitations

* Only one parameter (`max_concurrent_generations`) has an application
  path today (`_APPLICATION_TARGETS`); adding another requires adding
  its handling explicitly, by design — nothing here applies a parameter
  it doesn't recognise.
* Validation measures queue-batching behaviour only. It says nothing
  about voice quality, generation latency in wall-clock terms, or any
  property beyond how many batches a fixed-size fixture set was split
  into.
* The frontend's `computeBatchCount()` mirrors the backend's formula
  but does not literally re-run the async, UI-progress-animated
  `GenerationQueueStore` through a batching loop — the deterministic
  math is verified identical to the backend's, but the live browser
  queue's own item-by-item processing model is unchanged by VL-D8.
* `calibration_state` still can never reach `CALIBRATED` for the target
  speaker, for the same structural reason VL-D7 documented — VL-D8 does
  not change this.
* Session-only in the frontend, same limitation every prior phase's
  stores share — no execution transport exists to persist a profile
  beyond the browser session.

## What VL-D8 does NOT implement

Dataset assembly / `build-dataset` (a separate, real gap identified
during the VL-D8 audit but deliberately deferred — it touches the
technical-review/speaker-identity boundary and needs its own careful
scoping in a future phase); real TTS backend; diarization; transcription;
training; any access to real recordings; any speaker-identity work.

## Next

**VL-D9** — not yet scoped.
