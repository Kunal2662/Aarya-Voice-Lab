# VL-D4 — Voice Processing & Conditioning Workspace

> Status: **real processing/conditioning logic, synthetic data only.**
> `pipeline.normalization` is a pre-existing Phase 2 module VL-D4 reuses
> unmodified; `pipeline.processing_profile`, `pipeline.conditioning`,
> `pipeline.processing`, and `pipeline.processing_history` are new this
> phase. Every one of them only ever runs against files
> `testing.synthetic_audio` generates. **REAL RECORDINGS ARE NOT USED
> DURING VL-D4.** See "Real recording activation" below for exactly what
> changes, and does not change automatically, once they are.

## Why this is not a second normalization pipeline

Phase 2 already built `pipeline.normalization` — FFmpeg-gated derived
copies with full provenance (source hash, output hash, config hash, tool
version), source verified byte-identical before and after, honestly
`NormalizationBlocked` when FFmpeg is missing. VL-D4 reuses it exactly
as-is for sample-rate/channel/bit-depth/loudness conditioning. It also
reuses `pipeline.resume.StageFingerprint` for derived-artifact identity
(§17: "same input + profile + config + tool version → reproducible id"
is precisely what `StageFingerprint.digest()` already computes for
pipeline stages generally), and `pipeline.quality.assess_quality()` /
`audio.vad.detect_regions()` for the before/after quality re-check.

What Phase 2 never built, because nothing before VL-D4 needed to trim
silence at a recording's edges without touching its resampled body, or
persist a *history* of derived-artifact versions with rollback, is
covered by four new modules: `pipeline.processing_profile`,
`pipeline.conditioning`, `pipeline.processing`, and
`pipeline.processing_history`.

## Source immutability (§2, unchanged as an absolute rule)

**Source audio is never modified.** Every VL-D4 operation either reads
an existing source file read-only or writes a *new* file under
`data/working/`. This is enforced the same way Phase 2 already enforces
it — `core.data_root.assert_source_writable` — not by a new check VL-D4
introduces. Both new write paths (`condition_boundaries()` and
`normalize_file()`, called through `pipeline.processing.ProcessingQueue`)
re-verify the source's SHA-256 both before writing and after, raising
if it ever changed — "this must never happen" is enforced, not assumed.

## Backend

### `pipeline.processing_profile` — versioned processing configuration

```python
class NoiseConditioningMode(StrEnum):
    OFF = "OFF"
    MEASURE_ONLY = "MEASURE_ONLY"
    LIGHT = "LIGHT"        # real vocabulary, no tool behind it yet
    STANDARD = "STANDARD"  # same

@dataclass(frozen=True)
class BoundaryPolicy:
    trim_leading_silence: bool = True
    trim_trailing_silence: bool = True
    min_trim_seconds: float = 0.1
    pad_seconds: float = 0.05

@dataclass(frozen=True)
class ProcessingProfile:
    profile_id: str; name: str; version: int
    normalization: NormalizationConfig    # reused from pipeline.normalization
    boundary: BoundaryPolicy
    noise_conditioning_mode: NoiseConditioningMode
    quality_thresholds: QualityThresholds  # reused from pipeline.quality
```

Every field lives on a **frozen dataclass** — there is no method that
could mutate one in place. `ProcessingProfileRegistry.create()` refuses
a name that already exists; every subsequent change goes through
`create_version()`, which always appends a new, independently
addressable version. This implements VL-D4 §22's "profiles should be
immutable once used, or changes must create a new version" as the
stronger, unconditional guarantee: there is no "used" tracking to get
wrong, because nothing can ever be edited regardless.

### `pipeline.conditioning` — boundary trim (no FFmpeg) + noise decision

**Boundary conditioning has no FFmpeg dependency at all.** It only crops
and pads existing PCM frames via the stdlib `wave` module (the same
dependency-free tool `testing.synthetic_audio` and
`pipeline.normalization`'s own honesty pattern already use) — it never
resamples or re-encodes, so it works even on a machine without FFmpeg.
Detection reuses `audio.vad.detect_regions()` on the same mono-downmixed
samples every VAD-driven stage already uses; the write step re-opens the
source directly to preserve the original channel layout and bit depth,
since detection never needs those. `compute_boundary_trim()` never trims
past the first/last detected speech region, and ignores an edge silence
run shorter than `BoundaryPolicy.min_trim_seconds` — a natural short
pause before speech is left alone (§10: "prioritize preservation of
speech content").

**Noise conditioning is a decision, not an implementation, in VL-D4.**
`apply_noise_conditioning()`:

| Mode | Outcome |
|---|---|
| `OFF` | not applied — audio unchanged, no claim otherwise |
| `MEASURE_ONLY` | noise floor/SNR are already reported by quality measurements; audio unchanged |
| `LIGHT` / `STANDARD` | **NOT AVAILABLE** — real, closed vocabulary values with no noise-reduction tool wired up yet; never silently downgraded to `MEASURE_ONLY`, never pretended to have run (§11) |

**Telephone/narrowband audio is never treated as a defect here either.**
Nothing in `pipeline.conditioning` inspects sample rate to decide
whether to trim or condition more aggressively (§12) — that distinction
stays exactly where Phase 2's `pipeline.quality` already drew it:
`characteristics`, never a finding.

### `pipeline.processing` — the queue and the decision

```python
class ProcessingStatus(StrEnum):
    QUEUED = "QUEUED"; PREPARING = "PREPARING"; PROCESSING = "PROCESSING"
    QUALITY_CHECK = "QUALITY_CHECK"; SUCCESS = "SUCCESS"; WARNING = "WARNING"
    FAILED = "FAILED"; BLOCKED = "BLOCKED"; CANCELLED = "CANCELLED"

class ProcessingDecision(StrEnum):
    NO_PROCESSING = "NO_PROCESSING"
    LIGHT_CONDITIONING = "LIGHT_CONDITIONING"
    STANDARD_CONDITIONING = "STANDARD_CONDITIONING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
```

`decide_processing()` is a pure function over `AudioMeasurements` and a
`ProcessingDecisionThresholds` config object — it never runs alongside
the measurement that produced its input, keeping VL-D4 §15's
measurement/decision separation as literal as `pipeline.quality`'s own.

`ProcessingQueue` mirrors `pipeline.import_intake.ImportQueue`'s shape
exactly: sequential processing, one broad `except Exception` per item so
a single bad recording can never stop the rest of the batch (§5, §23).
Per item, `process_one()`:

1. **PREPARING** — re-verifies the source hash. A mismatch or an
   unreadable file raises and the item ends **BLOCKED** — processing
   never began at all.
2. **PROCESSING** — boundary conditioning (always attempted, never
   FFmpeg-gated) then normalization (FFmpeg-gated; `NormalizationBlocked`
   is caught and recorded as a **warning**, not a block — the
   boundary-conditioned derived artifact is still valid and useful even
   without normalization).
3. Noise conditioning's decision is recorded; `LIGHT`/`STANDARD`
   unavailability also becomes a warning.
4. **QUALITY_CHECK** — re-measures and re-assesses the derived audio.
5. Terminal state: **SUCCESS** (clean), **WARNING** (completed with a
   caveat — an optional tool was unavailable, or the derived quality
   re-check itself came back FAIL), **BLOCKED**, or **FAILED** (an
   unexpected error). No state is ever silently upgraded to SUCCESS.

Derived-artifact identity (§17) is `build_artifact_fingerprint()`,
built directly on `pipeline.resume.StageFingerprint(stage="voice_processing",
config_hash=profile.config_hash(), input_hashes=(source_sha256,),
tool_version=ffmpeg_version())` — the same source, profile, and tool
version always produce the same `artifact_id`, and nothing about the
identity depends on a filename or a timestamp.

### `pipeline.processing_history` — append-only, with rollback

Mirrors `pipeline.candidate_review`'s persistence pattern exactly: one
`JsonLinesRegistry`-backed log, schema-validated on write, records keyed
by `record_id` (never a timestamp). `record_processing_result()` always
appends. **`rollback()` never deletes or edits** — it appends a new
record whose `output_sha256` matches a prior record's, with `supersedes`
naming the record it displaces as active and `is_rollback=True` marking
it as such (§18: "select previous derived version as active derived
candidate," implemented as "add a new pointer," never "remove
anything").

### Processing feedback — an addition, not a new mechanism

VL-D4 §28 adds `FeedbackType.PROCESSING_FEEDBACK` to VL-D3's existing
`pipeline.feedback` module rather than building a second feedback
system. The category (`TOO_AGGRESSIVE`, `TOO_NOISY`, `TOO_QUIET`,
`OVER_PROCESSED`, `UNDER_PROCESSED`, `BOUNDARY_INCORRECT`,
`QUALITY_DEGRADED`, `GOOD_RESULT`, `OTHER`) is a new, validated
`ProcessingFeedbackCategory` enum, stored in the existing
`attributes["category"]` field `schemas/feedback.schema.json` already
defines as a free-form string dict.
`record_processing_feedback()` validates the category before writing —
same "never a training label" guarantee VL-D3's feedback carries.

## Frontend

### Status vocabulary additions

Three new domains in `frontend/tokens/status.json`, each mirroring the
corresponding backend enum exactly (verified via
`frontend/contracts/generated/`): `processing_status`,
`processing_decision`, `noise_conditioning_mode`.

### New components

All zero-dependency vanilla Web Components:

- `processing-queue.js` — per-item status/progress/current operation/
  warnings/errors, Start/Cancel/Retry/"Retry with another profile," a
  bulk "Retry all failed" — the same shape VL-D2's `avl-import-queue`
  already established for a session-only queue table.
- `processing-profile-editor.js` — list every named profile's latest
  version, with New version / Duplicate / Set default actions. No "edit"
  control exists at all — every change is a new version.
- `before-after-comparison.js` — Source vs. Derived: two
  `avl-audio-player`s (reused from VL-D3 exactly as-is; still a
  synthetic tone, still never a real recording, still never autoplays),
  metadata, and a quality comparison built by reusing
  `avl-quality-profile` **unmodified** for both sides — its
  `.assessment` setter already tolerates a reduced shape lacking
  findings/speech/characteristics, so nothing needed to change there.
- `processing-history-panel.js` — every processing run for a recording,
  oldest first, with "Make active" (rollback) on any non-current record.
- `processing-feedback-form.js` — category + comment, wired to VL-D3's
  existing `FeedbackStore` (reused, not reimplemented).
- `claude-processing-context.js` — the bounded "Ask Claude" affordance
  described below, built on the same `buildReviewClaudeContext()`
  VL-D3's `claude-review-context.js` uses.

### `avl-workspace-processing` — the new workspace

Mounted at `#/processing`, added to `state/router.js`'s `DESTINATIONS`
between `review` and `pipeline`. Composes a **dashboard** (§21 — Total
selected / Queued / Processing / Success / Warning / Failed / Blocked /
Cancelled / average duration / quality improved / quality degraded, all
derived from the real `ProcessingQueueStore`), **profile management**,
a **recordings table** with a "Queue for processing" action per row, the
**processing queue**, and — once a recording is selected — **Before/
After**, **processing history**, and a **processing feedback form**.

### What "processing" means in the browser

The browser has no execution transport to run FFmpeg or write into
`data/working/` (the same constraint every prior phase's Command Center
section has documented — still true here: `NullCommandExecutor` is still
the only `CommandExecutor` implementation that exists). `state/processing-model.js`'s
`ProcessingQueueStore` is therefore a **session-only simulation**: an
enqueued item genuinely walks through QUEUED → PREPARING → PROCESSING →
QUALITY_CHECK with real, visible UI state transitions, then **replays**
the outcome `state/synthetic-fixtures.js` already recorded for that
recording id — never a live FFmpeg run, and never a fabricated
measurement for a recording the fixtures don't cover (an unknown id
gets an explicitly-labelled generic `NO_PROCESSING` placeholder, with a
warning saying so). `exportProcessingPlan()` bridges the same way VL-D2/
VL-D3's `export*Plan()` functions do — JSON shaped closely to the
backend's records, for a future CLI command to consume, never a claim
that anything was actually written to disk.

### Expanded Inspector (§20)

`inspector-router.js`'s `recording` view gained a ninth section,
**Processing**, appended after VL-D3's Provenance section: status/
decision badges, profile/output path/output hash/artifact id, warnings/
errors, Quality before/Quality after (via `avl-quality-profile`, reused
unmodified — see above), the processing history panel, the processing
feedback form, and the bounded "Ask Claude" affordance. Nothing new here
can express speaker identity — VL-D4 never touches that boundary at all
(§2's whole scope is technical derivation, not identity).

### Activity, Command Center, and Claude integration (§25, §26)

- **Activity**: a new `ActivitySource.PROCESSING` value (added to the
  existing closed `ActivitySource` enum in `state/activity-model.js`,
  the same additive pattern VL-D3's `FeedbackType.PROCESSING_FEEDBACK`
  used) — one real event per processing item status transition
  (deduplicated so a status seen twice in a row doesn't double-post) and
  one per profile created/updated.
- **Command Center**: gained a seventh panel, "Processing" — Total
  processed / Success / Warning / Failed / Blocked / average duration,
  read live from `services.processingQueueStore`. An overview only — the
  Processing workspace still owns the detailed queue/profile/before-
  after view, per the same "Command Center = overview, workspace =
  detail" rule VL-D2's Imports panel and VL-D3's Review panel already
  followed.
- **Claude**: `claude-processing-context.js` builds its context through
  the same `buildReviewClaudeContext()` VL-D3 uses — bounded to
  `recording_id`/`batch_id`/`stage: "voice_processing"`/`metric`/
  `warning`/`error`/`config`/`provenance`, passed through the same
  redaction pass regardless. The "ask" itself still routes through
  `NullCommandExecutor`, honestly reporting `NOT_AVAILABLE`.

## Security boundary

Nothing in VL-D4 weakens an existing invariant:

- **Source immutability** — see the dedicated section above; both new
  write paths re-verify the source hash before and after.
- **Dataset access gate** — untouched; VL-D4 never calls
  `pipeline.dataset_gate.evaluate_gate()` or constructs anything that
  would need to.
- **Speaker identity boundary** — no field for it exists anywhere in
  `ProcessingProfile`, `ProcessingItem`, `ProcessingHistoryRecord`, or
  the frontend equivalents; this whole phase operates strictly before
  and outside that boundary.
- **Execution boundary** — the "Ask Claude" affordance and the
  in-browser processing simulation both stay session-local; nothing new
  executes.
- **Path traversal / relative paths only** — derived filenames are
  `<item-id>.<stage>.wav` under `data/working/`, never a caller-supplied
  path; every provenance field is a hash, an id, or a relative name.
- **Provenance** — every `ProcessingHistoryRecord` carries
  `source_sha256`, `output_sha256`, `config_hash`, `tool_version`.
- **Local-first / offline** — no new network call, no new dependency
  (boundary conditioning is stdlib `wave`; normalization was already
  FFmpeg-gated in Phase 2).
- **Secret scanning** — re-verified clean.

## Hardware abstraction (§30)

Nothing in VL-D4 hardcodes a vendor or device. `ffmpeg_version()` (reused
from `pipeline.normalization`) detects FFmpeg's *presence*, not any GPU
or CPU vendor; boundary conditioning has no hardware dependency at all
(pure Python/stdlib). `NoiseConditioningMode.LIGHT`/`STANDARD` are
capability-driven placeholders precisely so that whatever tool
eventually backs them (CPU, NVIDIA, AMD, Apple Silicon, or otherwise)
can be swapped in later without changing the profile schema or the UI
contract — VL-D4 commits to the vocabulary, not an implementation.

## Real recording activation

VL-D4 does not, and cannot by itself, activate real recordings:

- Nothing in this phase constructs a `GateReport` or calls
  `evaluate_gate()`.
- `pipeline.processing.ProcessingQueue` operates on whatever
  `source_path`/`source_sha256` it's handed — nothing about its design
  assumes synthetic data, but VL-D4's own tests, fixtures, and workspace
  usage only ever hand it synthetic files.
- The frontend has no path to real data at all — the Processing
  workspace only ever renders `state/synthetic-fixtures.js`, and its
  queue is an explicit session-only simulation (see above), not a
  connection to the real backend queue.

When real recordings are eventually authorized, `pipeline.processing.ProcessingQueue`
already operates on real audio files and real `DataRoot` paths today —
no architectural change is needed, only real data, real gate approval,
and a real execution transport for the frontend to drive the real
backend queue through (the client-side `ProcessingQueueStore` is still
session-only, exactly like VL-D2's `ImportQueue` was before any
transport existed).

## Testing

```sh
python -m pytest tests/test_voice_processing.py -q   # 40 backend tests
cd frontend && node --test tests/*.test.mjs           # 98 frontend tests total
```

New in VL-D4: 40 backend tests (`tests/test_voice_processing.py`) and 30
frontend tests (15 pure-logic in `processing-state.test.mjs`, 15 real
headless-Chromium scenarios in `processing.test.mjs`, covering all of
§36's scenario list: navigating to Processing, selecting a recording,
selecting a profile, queuing processing, showing progress, showing the
derived artifact, before/after, quality comparison, provenance,
processing history, feedback, a triggered failure state, retry, Command
Center integration, and bounded Claude context — each scenario also
asserts zero unexpected console errors). VL-D0's 10, VL-D1's 19, VL-D2's
16, and VL-D3's 23 re-run unmodified except two assertions updated to
include the new `processing` destination and the Inspector's new
"Processing" section (both legitimate additions, not weakened checks).
Full existing Python suite (559 tests total including VL-D4's) and
`ruff check .` remain green throughout.

## Known limitations

- `ProcessingQueueStore`/`ProcessingHistoryStore` are session-only on the
  frontend, same as every prior phase's client-side store before an
  execution transport existed — a processing run made in the browser
  does not persist past a page reload, and "processing" there is a
  labelled replay of fixture data, never a live FFmpeg/audio operation
  (see "What 'processing' means in the browser" above).
- `NoiseConditioningMode.LIGHT`/`STANDARD` have no implementation behind
  them anywhere in this phase, backend or frontend — by design, not
  oversight; see §11.
- `pipeline.processing.ProcessingDecisionThresholds`'s default SNR
  boundaries are a first-pass judgement call, not tuned against any real
  dataset — acceptable for the framework this phase establishes, revisit
  once real measurements exist.
- Backend processing profiles are in-memory only
  (`ProcessingProfileRegistry` is not `JsonLinesRegistry`-backed) — only
  the processing *history* (derived-artifact provenance and rollback) is
  persisted. Profile persistence, if needed, is a small addition on top
  of the same registry pattern already used elsewhere, not an
  architectural gap.

## Next

**VL-D5 — Voice Preview + Generation Workspace**.
