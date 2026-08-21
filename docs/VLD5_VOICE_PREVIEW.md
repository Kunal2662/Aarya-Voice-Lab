# VL-D5 — Voice Preview & Generation Workspace

> Status: **real generation-queue/history/feedback logic, synthetic
> audio only.** `pipeline.generation`, `pipeline.voice_profile`,
> `pipeline.generation_models`, `pipeline.preview_history`, and
> `pipeline.preview_feedback` are all new this phase, built directly on
> `identity.preview`'s VL-V0 contracts. Every generated output is a
> mathematically generated sine tone. **REAL RECORDINGS ARE NOT USED
> DURING VL-D5. NO REAL SPEAKER EMBEDDINGS OR TARGET-SPEAKER IDENTITY
> ARE INVOLVED. Synthetic previews are not representations of a real
> person's voice.** See "Real recording activation" below for exactly
> what changes, and does not change automatically, once they are.

## Why this is not a second preview/feedback system

`identity/preview.py` (Phase 3, "VL-V0") already declared
`PreviewProvider`, `PreviewArtifact`, `PreviewKind`, `PreviewFeedback`,
and `PreviewFeedbackOutcome` — contracts only, no implementation,
written specifically "so later phases can implement against a stable
interface." VL-D5 is that later phase. `VoiceGenerator` is
`PreviewProvider` plus three methods the richer workspace needs
(`get_capabilities()`, `validate_request()`, `estimate_requirements()`)
that Phase 3's contract-only stub never required. `PreviewFeedback`/
`PreviewFeedbackOutcome` are reused **unmodified** as the authoritative
feedback record — VL-D5 only adds persistence
(`pipeline.preview_feedback`, a `JsonLinesRegistry`) and a validated
category vocabulary, stored in the existing `attributes["category"]`
field the same way VL-D4's `ProcessingFeedbackCategory` already uses it.

`registry.model_registry.ModelRegistry` (Phase 1's persisted, security-
metadata-carrying audit of *final voice model* artifacts) is
deliberately **not** reused for `pipeline.generation_models` — a
different concern (which generation backends are pluggable right now)
that happens to share the word "model." Forcing Phase 1's
`private_voice`/`default_voice` distinction onto a runtime backend
registry would be an ill fit — the same "build new only where the
existing concept is genuinely different" judgement VL-D3 already applied
to `quality_decision`.

## Scope boundary (§3, absolute)

This is **not** the final high-fidelity voice, **not** the final Aarya
voice, and involves **no** real speaker embeddings or target-speaker
identity. Every concrete backend shipped this phase
(`SyntheticVoiceGenerator`, `UnavailableVoiceGenerator`) is honestly
labelled: outputs are tagged `PreviewKind.SYNTHETIC_FIXTURE`, never
`PreviewKind.GENERATED_SPEECH` (still "PLANNED — never generated yet,"
exactly as `identity/preview.py` already states). Nothing in this phase
claims generated audio is any real person's voice.

## Backend

### `pipeline.voice_profile` — profiles with no speaker fields

```python
class VoiceProfileState(StrEnum):
    SYNTHETIC_PROFILE = "SYNTHETIC_PROFILE"
    UNCALIBRATED = "UNCALIBRATED"

@dataclass(frozen=True)
class VoiceProfile:
    profile_id: str; name: str; version: int
    state: VoiceProfileState = VoiceProfileState.SYNTHETIC_PROFILE
    style_controls: dict[str, str]
    generation_preferences: dict[str, str]
    notes: str | None = None
    created_at: str | None = None
```

**This type cannot express a speaker characteristic.** A future voice
profile may eventually carry speaker/accent/pronunciation/prosody
fields (§8), but VL-D5 must never auto-infer or populate any of them —
so, exactly like `pipeline.segmentation.CandidateSegment` has no field
capable of expressing a speaker role, `VoiceProfile` simply has no field
for any of those characteristics at all. There is nothing to
accidentally leave `None` and nothing to forget to guard. Only
`style_controls`/`generation_preferences` exist — operator-configurable
generation *knobs*, never an inferred trait. `VoiceProfileRegistry`
mirrors `pipeline.processing_profile.ProcessingProfileRegistry` exactly:
`create()` refuses a duplicate name, every later change is a new
`create_version()`.

Dataset → Processed Dataset → Voice Profile → Model → Generation Request
→ Generated Output stay separate, non-merged objects, connected only by
id references (§9).

### `pipeline.generation_models` — pluggable generation backends

```python
@dataclass(frozen=True)
class GenerationModel:
    model_id: str; name: str; version: str
    backend: ComputeBackend             # identity.runtime — vendor-neutral
    capabilities: frozenset[str]        # matched against GENERATION_CONTROLS
    requirements: RuntimeCapability | None = None
    status: str = "not_configured"
```

An in-memory registry — runtime-discovered declarations, not persisted
artifacts (no `JsonLinesRegistry` needed, unlike history below). No
vendor, GPU, or one-inference-engine assumption anywhere: `backend` is
`identity.runtime.ComputeBackend`, the same vocabulary every other phase
already uses. **No RTX 3050 lock-in.**

### `pipeline.generation` — the abstraction, the queue, and the one honest backend

```python
class GenerationBackendState(StrEnum):
    AVAILABLE = "AVAILABLE"; UNAVAILABLE = "UNAVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"; NOT_SUPPORTED = "NOT_SUPPORTED"
    BLOCKED = "BLOCKED"; ERROR = "ERROR"

class GenerationStatus(StrEnum):
    QUEUED = "QUEUED"; PREPARING = "PREPARING"; GENERATING = "GENERATING"
    POST_PROCESSING = "POST_PROCESSING"; READY = "READY"; WARNING = "WARNING"
    FAILED = "FAILED"; CANCELLED = "CANCELLED"; BLOCKED = "BLOCKED"

GENERATION_CONTROLS = frozenset(
    {"voice", "model", "speed", "pitch", "style", "expressiveness", "seed", "output_format"}
)
```

`VoiceGenerator(PreviewProvider)` adds `get_capabilities()` /
`validate_request()` / `estimate_requirements()`. A backend's
`GenerationCapabilities.supported_controls` is a validated subset of
`GENERATION_CONTROLS` — any control outside it renders **NOT AVAILABLE**
for that backend, never a fabricated default (§12).

`SyntheticVoiceGenerator` — the one concrete backend VL-D5 ships —
writes a deterministic sine tone (`testing.synthetic_audio.generate_tone`)
whose frequency/duration derive from the request's seed (or a hash of
the text when no seed is given) and word count. **Same request + config
+ seed reproduces the same output** (verified: two independent requests
built from identical fields hash to the identical `config_hash`).
`UnavailableVoiceGenerator` exists specifically to exercise and
demonstrate the honest `UNAVAILABLE`/`BLOCKED` path — never a
fabricated partial success.

`PreviewRequest` is versioned and never timestamp-identified:
`request_id` is a sequential counter (`preview-req-00001`, …), never
derived from wall-clock time (§7). `config_hash` covers
voice/generation-profile/model/sample-rate/output-format/seed/controls —
independent of `request_id` or the text's content, by design (so
identical config always hashes identically regardless of how many times
it's been requested).

`GenerationQueue` mirrors `pipeline.processing.ProcessingQueue`'s shape
exactly: sequential processing, one broad `except Exception` per item so
a single failed generation can never crash the rest of the queue (§13).
Per item, `process_one()`:

1. **PREPARING** — `validate_request()`. Any error → **BLOCKED**,
   generation never began.
2. **GENERATING** — `generate_preview()`. A `GenerationBlockedError` →
   **BLOCKED**; any other exception → **FAILED**.
3. **POST_PROCESSING** — `build_artifact_fingerprint()` (via
   `pipeline.resume.StageFingerprint`, reused a third time after VL-D4's
   two processing-artifact uses) assigns `artifact_id` — the same
   config + text always produces the same id, never a filename- or
   time-derived one (§17).
4. Terminal: **READY** (clean), **WARNING** (completed with a caveat),
   **BLOCKED**, or **FAILED**. Never silently upgraded to READY.

`build_ab_comparison()` (§16) is deliberately **metadata-only** —
duration/sample-rate/kind/synthetic-flag comparison plus an explicit
disclaimer string. It never computes or claims acoustic similarity;
that requires a validated evaluation engine this project does not have
yet (reserved for a future phase).

### `pipeline.preview_history` — append-only, grouped by voice profile

Mirrors `pipeline.processing_history`'s pattern exactly (`JsonLinesRegistry`,
schema-validated, `record_id`-keyed, never a timestamp), but grouped by
`voice_profile_id` rather than `recording_id` — the stable "lineage" a
sequence of *generations* belongs to, since each regeneration gets an
entirely new `request_id`. **Regeneration never overwrites** — every
generation, first and every one after, appends a new record chained via
`supersedes`. `history()` returns the full "Generation 1, 2, 3…" trail
(§19); `current()` is only ever the latest, never a claim earlier ones
stopped existing; `regeneration_count()` = every record after the first.

### `pipeline.preview_feedback` — listened-before-decision, enforced

Reuses `identity.preview.PreviewFeedback`/`PreviewFeedbackOutcome`
directly rather than a second, competing feedback type. Adds only what
VL-V0 never needed: persistence, and a validated
`PreviewFeedbackCategory` (`VOICE_QUALITY`, `NATURALNESS`, `CLARITY`,
`PRONUNCIATION`, `PACE`, `PITCH`, `PROSODY`, `STYLE`, `ARTIFACTS`,
`OVERALL`).

**"No generated result should be treated as final without a
previewable output" (§15) is enforced as executable code, not a UI
convention.** `record_preview_feedback()` raises `UnlistenedFeedbackError`
if `outcome` is `ACCEPTED`/`REJECTED` and `listened` is `False` — the
same "honesty enforced by construction" pattern the speaker-identity
boundary already uses elsewhere in this project. `REGENERATE`/
`UNCERTAIN` never require listening first, matching the backend exactly.

### Calibration prep (§23)

`pipeline.calibration_prep.summarize_preview_calibration_inputs()`
extends VL-D3's existing module with real counts — total generations,
distinct voice profiles, total regenerations, feedback counts by
outcome/category — always `CalibrationState.UNCALIBRATED`. **No score is
computed.** No AI Calibration Engine exists yet (VL-D7); these are raw
counts for a future engine to read.

## Frontend

### Status vocabulary additions

Three new domains in `frontend/tokens/status.json`, each mirroring the
corresponding backend enum exactly: `generation_status`,
`generation_backend_state`, `voice_profile_state`.

### `state/generation-model.js` — the session-only simulation

Mirrors `state/processing-model.js`'s pattern (session-scoped,
in-memory stores over synthetic fixture data — still no execution
transport to run a real TTS engine). Field-naming departs from VL-D4's
camelCase-only convention on purpose: any record shaped like a backend
`to_dict()` (`PreviewRequest`, `GenerationItem`, `PreviewArtifact`,
`VoiceProfile`, `GenerationModel`, `PreviewHistoryRecord`,
`PreviewFeedback`) keeps that exact snake_case shape, so it drops
straight into the already-shipped VL-D0/D1 components
(`avl-voice-player`, `avl-voice-feedback`, `avl-voice-version`,
`avl-voice-comparison`) that already read `artifact.preview_id`,
`feedback.outcome`, etc. `VoiceProfileStore`, `GenerationModelStore`,
`GenerationQueueStore`, `PreviewHistoryStore`, and a **dedicated**
`PreviewFeedbackStore` (not the generic `FeedbackStore` in
`review-model.js` — this one enforces the listened-before-decision
guard the generic store has no concept of) all live here.

### Real playback (§14)

`avl-audio-player` (VL-D3) gained a playback-speed control
(0.5×–2×). `avl-voice-player` (previously a VL-D0 placeholder wrapping
`avl-playback-controls`/`avl-waveform-container`, both explicitly "no
audio engine yet") was rewritten to compose `avl-audio-player` (real
playback) + `avl-waveform-visualization` (real bars, VL-D3) instead —
the two placeholder components were deleted as dead code. Every existing
caller (`avl-voice-preview-card`, `workspace-voices.js`) gets real
playback for free, with no changes to those callers.

`avl-audio-player` now also dispatches a bubbling, composed
`avl-playback-started` event on real playback start — the mechanism
`avl-preview-feedback-form` uses to gate Accept/Reject on having
actually pressed Play, and the mechanism the app wires a "preview
played" Activity event to (see below).

### New components

- `text-input.js` — real character/word counts, a heuristic (never
  claimed-exact) duration estimate once a backend is selected.
- `generation-settings.js` — Voice profile / Model selects always
  present; Speed/Pitch/Style/Expressiveness/Seed/Output-format only
  rendered as live controls when the selected model's own
  `capabilities` list actually supports them — otherwise "NOT AVAILABLE
  for this model," never a fabricated default.
- `generation-queue.js` — per-request status/progress/current
  operation/warnings/errors, Start/Cancel/Retry/"Open result" — the same
  shape `avl-processing-queue` already established.
- `ab-comparison.js` — two `avl-voice-player`s, a Swap control, and the
  metadata-only comparison table from `buildAbComparison()`, plus
  per-side feedback (reusing `avl-voice-feedback` twice, once per
  column — no new feedback UI needed).
- `preview-feedback-form.js` — embeds its own `avl-voice-player`;
  Accept/Reject stay disabled until an `avl-playback-started` event
  fires from that embedded player, mirroring the backend's
  `UnlistenedFeedbackError` exactly. Category/rating/comment, and the
  same "never a training label" disclosure every feedback form in this
  app carries.
- `generation-history-panel.js` — every generation for a voice profile,
  oldest first, labelled "Generation 1/2/3…" (no rollback action here —
  unlike derived processing artifacts, a preview generation has no
  "make active" concept, only regeneration).
- `claude-generation-context.js` — the bounded "Ask Claude" affordance,
  built on the same `buildReviewClaudeContext()` VL-D4's
  `claude-processing-context.js` uses.

### `avl-workspace-preview` — the new workspace

Mounted at `#/preview`, added to `state/router.js`'s `DESTINATIONS`
between `processing` and `pipeline`. Composes a **dashboard** (Total
requested / Queued / Generating / Ready / Warning / Failed / Blocked /
Cancelled / average duration, all from the real `GenerationQueueStore`),
a **voice profiles table**, the **Generation** section (text input +
settings + Generate button), the **Preview Queue**, **Generated
Outputs** (a card per completed result), and — once an output is
focused — **Feedback**, **A/B Comparison**, and **Provenance**.

Selecting a voice profile row routes through the shared
`selectionModel` exactly like `avl-workspace-processing`, so the
expanded Inspector renders its **Preview** section for whatever profile
is selected.

**A note on rendering and playback safety.** Several store "change"
events can arrive in quick succession (a completed generation's own
status transition, immediately followed by `previewHistoryStore.record()`'s
own change event one Promise-microtask later). Each would otherwise
trigger its own full teardown-and-rebuild of the outputs list — which
can tear an in-flight `<audio>` element out of the document mid-fetch.
`_scheduleRender()` coalesces these into one `setTimeout(…, 0)`-deferred
render. Separately, a click on a card's own embedded playback controls
(Play/Pause/Stop/Seek/Volume/Speed) bubbles up to the card's own
click-to-focus listener too (composed click events cross every shadow
boundary) — that listener now checks `event.composedPath()` for an
interactive control before treating a click as "focus this card," so
pressing Play never triggers an immediate destructive re-render of the
very player whose button was just pressed.

### What "generating" means in the browser

The browser has no execution transport to run a real TTS engine (the
same constraint every prior phase's Command Center section has
documented — `NullCommandExecutor` is still the only `CommandExecutor`
implementation that exists). `GenerationQueueStore` is therefore a
**session-only simulation**: an enqueued request genuinely walks through
QUEUED → PREPARING → GENERATING → POST_PROCESSING with real, visible UI
state transitions, then computes a deterministic
`PreviewArtifact`-shaped record (metadata only — the actual playable
tone is synthesized client-side by `avl-audio-player`/
`state/synthetic-tone.js`, which only needs `preview_id`/
`duration_seconds`, not a real audio file) — never a live TTS run, and
never a claim that any of this represents a real person's voice.

### Expanded Inspector (§20)

`inspector-router.js` gained a new selection kind, `voice-profile`
(distinct from the pre-existing `voice` kind VL-D1's demo voice list
already used), rendering profile identity/state/style-controls/
generation-preferences, plus a **Preview** `<details>` section: latest
generation status/model/output id/hash/config hash/warnings/errors, the
generation history panel, the preview feedback form, and the bounded
"Ask Claude" affordance. Nothing here can express speaker identity —
`VoiceProfile` structurally cannot (see above).

### Activity, Command Center, and Claude integration (§29, §30, §31)

- **Activity**: `ActivitySource.PREVIEW` (already declared in
  `state/activity-model.js` since VL-D0, unused until now) carries one
  real event per generation status transition (deduplicated), one per
  feedback submission (with a distinct `output_accepted`/
  `output_rejected`/`regeneration_requested` status for those outcomes),
  and one per real Play press (`preview_played`, via the
  `avl-playback-started` event, caught by a single document-level
  listener so it works from any nested player anywhere under the
  shell). **Never logs the raw preview text or comment** — only ids,
  model/voice-profile references, and outcome/category (§30).
- **Command Center**: gained an eighth panel, "Preview" — Total
  generated / Ready / Warning / Failed / Blocked / average duration,
  read live from `services.generationQueueStore`. Overview only — the
  Preview workspace still owns the detailed queue/settings/A-B/feedback/
  history view.
- **Claude**: `claude-generation-context.js` builds its context through
  the same `buildReviewClaudeContext()` VL-D4 uses — bounded to
  `recording_id` (repurposed as the request id), `batch_id`
  (repurposed as the voice profile id), `stage: "voice_generation"`,
  `metric`, `warning`, `error`, `config`, `provenance`. Never the raw
  preview text.

## Security boundary

Nothing in VL-D5 weakens an existing invariant:

- **Speaker identity boundary** — no field for it exists anywhere in
  `VoiceProfile`, `PreviewRequest`, `GenerationItem`,
  `PreviewHistoryRecord`, `PreviewFeedback`, or any frontend equivalent;
  this whole phase operates strictly before and outside that boundary.
- **Dataset access gate** — untouched; VL-D5 never calls
  `pipeline.dataset_gate.evaluate_gate()`.
- **Source immutability** — VL-D5 never reads or references anything
  under `data/source/`; every write goes through
  `assert_source_writable()` into the new `data/previews/` directory,
  and `generate_preview()` refuses to overwrite an existing file.
- **Execution boundary** — the "Ask Claude" affordance and the
  in-browser generation simulation both stay session-local.
- **Path traversal / relative paths only** — every provenance field is a
  hash, an id, or a relative name (`previews/<request-id>.wav`).
- **Local-first / offline** — no cloud storage, no cloud generation, no
  remote voice service, no new network dependency.
- **Secret scanning** — re-verified clean.

## Hardware abstraction (§26, §27)

Nothing in VL-D5 hardcodes a vendor or device. `GenerationModel.backend`
is `identity.runtime.ComputeBackend`; `SyntheticVoiceGenerator` reports
`ComputeBackend.CPU` and requires no accelerator at all. **No RTX 3050
lock-in, no CUDA/NVIDIA-specific code path anywhere.**

## Real recording activation

VL-D5 does not, and cannot by itself, activate real recordings or real
voice generation:

- Nothing in this phase constructs a `GateReport` or calls
  `evaluate_gate()`.
- `SyntheticVoiceGenerator` only ever produces a mathematically
  generated tone — there is no code path in it that could read or
  synthesize from real speech, regardless of what `PreviewRequest` it is
  handed.
- The frontend has no path to real data at all — the Preview workspace
  only ever renders `state/synthetic-fixtures.js`-seeded stores, and its
  queue is an explicit session-only simulation (see above).

When a real voice-generation model is eventually authorized,
`pipeline.generation.VoiceGenerator` is the stable interface a real
implementation plugs into — `GenerationQueue`, `preview_history`, and
`preview_feedback` already operate on whatever `VoiceGenerator` they are
handed today, no architectural change needed, only a real backend, real
gate approval, and a real execution transport for the frontend to drive
the real backend queue through.

## Testing

```sh
python -m pytest tests/test_voice_preview.py -q   # 40 backend tests
cd frontend && node --test tests/*.test.mjs        # 143 frontend tests total
```

New in VL-D5: 40 backend tests (`tests/test_voice_preview.py`) and 45
frontend tests (26 pure-logic in `generation-state.test.mjs`, 19 real
headless-Chromium scenarios in `preview.test.mjs`, covering all of
§36's scenario list: opening the workspace, entering text, selecting a
voice profile, selecting a backend, generating, showing the queue,
showing a completed output, playing, seeking, the waveform, A/B
comparison, feedback, regenerating, provenance, history, Command Center
integration, bounded Claude context, the honest unavailable-backend
state, and a full-pass no-console-errors check). VL-D0's 10, VL-D1's
19, VL-D2's 16, VL-D3's 23, and VL-D4's 30 re-run unmodified except one
assertion updated to include the new `preview` destination (a
legitimate addition, not a weakened check). Full existing Python suite
(599 tests total including VL-D5's) and `ruff check .` remain green
throughout.

## Known limitations

- `GenerationQueueStore`/`PreviewHistoryStore`/`PreviewFeedbackStore` are
  session-only on the frontend, same as every prior phase's client-side
  store before an execution transport existed — a generation made in the
  browser does not persist past a page reload, and "generating" there
  computes a deterministic artifact record client-side, never a live TTS
  run (see "What 'generating' means in the browser" above).
- `SyntheticVoiceGenerator`'s frequency/duration heuristic is a simple,
  honestly-labelled placeholder — it is not tuned to sound like speech in
  any way, because it is not speech.
- Backend voice profiles and generation models are in-memory only
  (`VoiceProfileRegistry`/`GenerationModelRegistry` are not
  `JsonLinesRegistry`-backed) — only preview *history* and *feedback*
  are persisted. Persistence, if needed, is a small addition on top of
  the same registry pattern already used elsewhere, not an architectural
  gap.
- `PreviewKind.GENERATED_SPEECH` still has zero implementations anywhere
  in this codebase — by design, not oversight (§24, §25: no accent/
  pronunciation/speaker-matched claim exists yet, reserved for future
  VL-D21/22/23).

## Next

**VL-D6 — Voice Feedback & Human Evaluation Engine**.
