# VL-D6 — Voice Feedback & Human Evaluation Engine

> Status: **real evaluation/aggregation/disagreement logic, synthetic
> audio only.** `pipeline.evaluation` and `pipeline.evaluation_aggregation`
> are new this phase, built on top of the VL-D5 preview outputs (which
> are themselves synthetic tones). **THIS IS EVALUATION SOFTWARE ONLY —
> NOT ARYA'S VOICE DEVELOPMENT.** VL-D6 never trains, tunes, or
> establishes Aarya's actual voice or identity: no real recordings are
> read, no embeddings are generated, no speaker profile is produced. See
> "Scope boundary" and "Calibration boundary" below.

## Why this is not a second feedback system

`identity.preview.PreviewFeedback`/`PreviewFeedbackOutcome` (reused
unmodified by VL-D5) is a **flat, single-outcome** record: one
accept/reject/regenerate/uncertain decision, one optional category, one
optional rating. It cannot express what VL-D6 actually needs — several
simultaneous dimension scores, a confidence score, a `CANNOT_JUDGE`
completion state per evaluation, and **many independent reviewers**
evaluating the same output and disagreeing with each other. That is a
genuinely broader concern, not a restatement of the same one — the same
"build new only where the existing concept is a genuine mismatch"
judgement VL-D3 already applied to `candidate_review` (vs
`identity_review`) and VL-D5 applied to `generation_models` (vs
`registry.model_registry`).

`pipeline.evaluation` is therefore new. `identity.preview.PreviewFeedback`
and `state/generation-model.js`'s `PreviewFeedbackStore` are **left
completely untouched** — VL-D5's single-output accept/reject/regenerate
loop is a separate, coexisting mechanism, not superseded.

`ABDecision` (`PREFER_A`/`PREFER_B`/`NO_PREFERENCE`/`CANNOT_JUDGE`) is
kept structurally separate from `PreviewFeedbackOutcome` — a comparison
between two outputs is a different judgement axis from one output's
accept/reject fate (verified by a dedicated test asserting zero value
overlap between the two enums).

## Scope boundary (absolute)

VL-D6 is evaluation **software** only. It is explicitly **not**: training
Aarya's voice, creating Aarya's final voice, enrolling Aarya, analyzing
real Aarya recordings, generating Aarya embeddings, tuning Aarya's
accent, or establishing Aarya's speaker identity. It operates on
synthetic/fixture/generated-preview outputs only — real recordings are
never accessed unless the pre-existing dataset access gate explicitly
permits it (default closed, and VL-D6 never calls
`pipeline.dataset_gate.evaluate_gate()` at all).

## Voice quality dimension vocabulary

VL-D6 deliberately does **not** implement the full candidate list of 14
quality terms a spec might suggest. It first audited VL-D5's
`PreviewFeedbackCategory` and reused what already means the same thing:

```python
class VoiceQualityDimension(StrEnum):
    NATURALNESS = "NATURALNESS"        # reused
    CLARITY = "CLARITY"                # reused
    INTELLIGIBILITY = "INTELLIGIBILITY"  # new — "can the words be understood," distinct from CLARITY
    PRONUNCIATION = "PRONUNCIATION"    # reused
    PROSODY = "PROSODY"                # reused — Rhythm folds in here, not a separate dimension
    PACE = "PACE"                      # reused
    EXPRESSIVENESS = "EXPRESSIVENESS"  # new
    CONSISTENCY = "CONSISTENCY"        # new — Stability folds in here, not a separate dimension
    ARTIFACTS = "ARTIFACTS"            # reused
    NOISE = "NOISE"                    # new — background noise, distinct from ARTIFACTS (synthesis glitches)
    OVERALL = "OVERALL"                # reused
```

Eleven values: 7 reused verbatim from `PreviewFeedbackCategory`
(`NATURALNESS`, `CLARITY`, `PRONUNCIATION`, `PROSODY`, `PACE`,
`ARTIFACTS`, `OVERALL`), 4 genuinely new (`INTELLIGIBILITY`,
`EXPRESSIVENESS`, `CONSISTENCY`, `NOISE`). Two candidate terms are
deliberately **folded, not duplicated**: Rhythm is a sub-aspect of
`PROSODY`, Stability is a sub-aspect of `CONSISTENCY` — this exact
mapping is documented in the module docstring, the JSON schema
description, the frontend contract export description, and two dedicated
tests on both the Python and JS sides.

## Backend

### `pipeline.evaluation` — dimension scores, listening state, append-only log

```python
class EvaluationCompletionState(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"; COMPLETED = "COMPLETED"
    CANNOT_JUDGE = "CANNOT_JUDGE"; ABANDONED = "ABANDONED"

@dataclass(frozen=True)
class ListeningState:
    listened: bool = False
    first_listened_at: str | None = None
    replay_count: int = 0
    furthest_position_seconds: float | None = None
    completed_playback: bool = False

@dataclass(frozen=True)
class Evaluation:
    evaluation_id: str; output_id: str; reviewer: str; listening: ListeningState
    dimension_scores: dict[str, int]
    cannot_judge_dimensions: tuple[str, ...]
    confidence: int | None = None
    completion_state: EvaluationCompletionState = EvaluationCompletionState.IN_PROGRESS
    comment: str | None = None
    voice_profile_id: str | None = None; model_id: str | None = None
    config_hash: str | None = None; output_sha256: str | None = None
    evaluation_version: int = 1; supersedes: str | None = None
```

**`ListeningState.furthest_position_seconds` is deliberately not "time
listened."** A reviewer can seek, so this only records the furthest
playback position genuinely reached — never a fabricated listening
duration. Unmeasurable values stay `None`; the frontend never invents a
number the browser cannot actually measure.

**Provenance is named fields, not a free dict.** `Evaluation` has
explicit `voice_profile_id`/`model_id`/`config_hash`/`output_sha256`
rather than a generic `provenance: dict[str, str]`, specifically so the
type is structurally incapable of ever carrying an arbitrary — and thus
potentially speaker-identity-bearing — key. The same "structurally
cannot express it" pattern `VoiceProfile` (VL-D5) already uses for
speaker characteristics.

**Listening-before-decision is enforced in backend code, not UI
convention.** `record_evaluation()` raises `UnlistenedEvaluationError`
when `completion_state == COMPLETED` and the output was never listened
to. `CANNOT_JUDGE` and `ABANDONED` never require listening — a reviewer
may reach `CANNOT_JUDGE` precisely because playback failed. This mirrors
and generalizes VL-D5's `UnlistenedFeedbackError` pattern exactly.

**Append-only, multi-reviewer disagreement representation.** A second
evaluation of the same `output_id` — same or different reviewer — is
always a **new** record, never an edit. This *is* how reviewer
disagreement is represented, not a separate mechanism layered on top.
`supersedes` is reserved narrowly for the *same reviewer* revising their
own prior evaluation.

### `pipeline.evaluation` — A/B evaluation

```python
class ABDecision(StrEnum):
    PREFER_A = "PREFER_A"; PREFER_B = "PREFER_B"
    NO_PREFERENCE = "NO_PREFERENCE"; CANNOT_JUDGE = "CANNOT_JUDGE"

@dataclass(frozen=True)
class ABEvaluation:
    ab_evaluation_id: str; output_id_a: str; output_id_b: str; reviewer: str
    listened_a: bool; listened_b: bool; decision: ABDecision
    blinded: bool = False; comment: str | None = None
```

`record_ab_evaluation()` raises `UnlistenedEvaluationError` for
`PREFER_A`/`PREFER_B`/`NO_PREFERENCE` unless *both* sides were listened
to; `CANNOT_JUDGE` never requires listening.

**`blinded` is UI-level metadata suppression only — never a claim of
true blindness.** The docstring, the function docstring, and the JSON
schema description all say so explicitly: this project has no ability to
alter the audio itself, so "blind" here means the frontend hides the
comparison metadata table and A/B labels, nothing more.

### `pipeline.evaluation_aggregation` — pure statistics, honest about small samples

```python
MIN_EVALUATIONS_FOR_DISAGREEMENT = 2
DISAGREEMENT_SPREAD_THRESHOLD = 2
```

`summarize_dimension()`/`summarize_output_evaluations()`/
`outputs_with_disagreement()`/`summarize_ab_preferences()`/
`summarize_calibration_signals()` are all **pure functions over
already-recorded evaluations** — no new evaluation is computed, only
statistics over records the caller already has (the same
aggregate-over-writes-elsewhere pattern `pipeline.quality_summary`
already established). The caller pre-filters (e.g.
`evaluations_for(log, output_id)`); the aggregation function itself does
no filtering.

Honesty rules, verified by dedicated tests:

- **`variance` is `None`, never `0`, below 2 samples** — variance is
  mathematically undefined at n=1, and `0` would be a fabricated claim
  of perfect agreement.
- **Disagreement is never claimed from 1 evaluation.** It requires both
  `sample_count >= MIN_EVALUATIONS_FOR_DISAGREEMENT` **and**
  `max_score - min_score >= DISAGREEMENT_SPREAD_THRESHOLD`.
- **`preference_rate_a` is `None`, never a fabricated `0.5`,** when zero
  decided A/B preferences exist.
- **No confidence intervals or statistical-significance claims are
  computed anywhere** — none of VL-D6's spec asked for them, and none
  are invented.

### Calibration boundary (deliberately preserved, not extended)

```python
def summarize_evaluation_calibration_inputs(
    *, evaluation_log: EvaluationLog | None = None,
) -> EvaluationCalibrationInputSummary:
    ...
    return EvaluationCalibrationInputSummary(
        calibration_state=CalibrationState.UNCALIBRATED,  # always
        ...
    )
```

`pipeline.calibration_prep` is extended with real evaluation counts —
total evaluations, distinct outputs evaluated, distinct reviewers,
disagreement-output count, completed/cannot-judge counts — but
`calibration_state` is **always** `CalibrationState.UNCALIBRATED`. VL-D6
deliberately does **not** call the pre-existing
`identity.calibration.provisional_from_reviewer_feedback()` itself — that
step, and any move toward a calibrated state, is left to a future,
explicitly-approved phase (VL-D15, the AI Calibration Engine). These are
raw counts for that future engine to read, never a computed score, and
VL-D6 never generates a target-speaker profile, trains a model, generates
embeddings, identifies a real speaker, or auto-converts feedback into an
identity label.

### Schemas

`schemas/evaluation.schema.json` and `schemas/ab_evaluation.schema.json`
— draft-07, `additionalProperties: false` throughout (including the
nested `listening` object), closed vocabularies enforced via explicit
named `properties` for all 11 `dimension_scores` keys (never
`patternProperties`) — defense in depth matching the dataclass-level
validation.

## Frontend

### Status vocabulary addition

One new domain in `frontend/tokens/status.json`,
`evaluation_completion_state`, mirroring
`pipeline.evaluation.EvaluationCompletionState` exactly.

### `state/evaluation-model.js` — the session-only simulation

Mirrors `pipeline.evaluation`/`pipeline.evaluation_aggregation`'s
vocabulary, validation, and honesty rules exactly — a session-scoped,
in-memory simulation over `state/synthetic-fixtures.js` data, same as
every prior phase's client-side store (no execution transport exists yet
to persist an evaluation beyond the session).
`EvaluationStore`/`ABEvaluationStore extends EventTarget`, with the same
listened-before-`COMPLETED` gate and both-sides-listened gate the backend
enforces. Same field-naming convention as `generation-model.js`: records
shaped like a backend `to_dict()` keep that exact snake_case shape;
store/method names stay camelCase.

Two new synthetic fixtures: `syntheticEvaluations()` — two reviewers
(alice, bob) scoring the same output with a deliberately large
`NATURALNESS` spread, demonstrating real, detectable disagreement — and
`syntheticAbEvaluations()` — one A/B decision, unblinded.

### New components

- `rating-panel.js` — one row per `VoiceQualityDimension`: a 1–5 score
  control plus a "Cannot judge" checkbox that disables and clears that
  dimension's score (mirrors the backend rule that a dimension can never
  be both scored and cannot-judge). A controlled widget — it never writes
  to a store itself, only reports its value via `avl-rating-change`.
- `confidence-control.js` — an optional 1–5 self-reported confidence
  score, never defaulted to a fabricated middle value.
- `evaluation-form.js` — embeds its own `avl-voice-player`; "Submit
  evaluation" (`COMPLETED`) stays gated until `avl-playback-started`
  fires from that embedded player, mirroring `UnlistenedEvaluationError`
  exactly. "Cannot judge"/"Abandon" never require listening. Tracks
  replay count / furthest position reached / completed playback from
  `avl-audio-player`'s events (see below) — updated in place, never via a
  full `_render()`, to avoid tearing down a still-playing `<audio>`
  element mid-playback (the same blob-URL race
  `avl-preview-feedback-form.js` already documented and guarded against).
- `evaluation-queue.js` — one row per output with a live-computed status
  (not started / in progress / evaluated) and disagreement flag, computed
  from the store's own records via `summarizeOutputEvaluations()`, never
  a separately tracked and possibly-stale field.
- `evaluation-history-panel.js` — every evaluation ever recorded for an
  output, oldest first, append-only (mirrors
  `avl-generation-history-panel.js`'s "regeneration never overwrites"
  pattern, applied to reviewer records instead of generation attempts).
- `disagreement-view.js` — exactly which dimensions reviewers disagree
  on and the raw score spread behind that call; renders the honest "too
  few reviewers" state rather than silently showing nothing when
  `sample_count < 2`.
- `aggregated-results-panel.js` — full mean/median/variance/range table
  per dimension; variance reads "n/a (needs ≥ 2 samples)" rather than
  `0` when undefined.
- `ab-evaluation.js` — kept **separate** from VL-D5's `ab-comparison.js`.
  Embeds two `avl-evaluation-form`s (so each side still produces its own
  independent, multi-dimension `Evaluation` — genuinely "listen/replay/
  inspect-metadata/rate on both sides"), then a
  `PREFER_A`/`PREFER_B`/`NO_PREFERENCE`/`CANNOT_JUDGE` decision panel
  gated on both sides having been listened to (tracked via
  `avl-playback-started` bubbling out of each embedded form). The
  optional blinding toggle hides the metadata table and swaps A/B labels
  for "Output 1"/"Output 2" — documented, again, as UI-level display only.
- `claude-evaluation-context.js` — the bounded "Ask Claude" affordance,
  built on the same `buildReviewClaudeContext()` every other phase's
  Claude context component uses.

### `avl-audio-player`: two new bubbling events

VL-D6 needed a way to honestly track furthest playback position and
completion from *outside* `avl-audio-player`'s own shadow root, without
duplicating the audio player. Two events were added, both
bubbling+composed like the existing `avl-playback-started`:
`avl-playback-position` (on native `timeupdate`, carrying
`currentTimeSeconds`/`durationSeconds`) and `avl-playback-ended` (on
native `ended`). Purely additive — no existing consumer of
`avl-playback-started` is affected.

### `avl-workspace-feedback` — the new workspace

Mounted at `#/feedback`, added to `state/router.js`'s `DESTINATIONS`
between `preview` and `pipeline`. Composes a **dashboard** (Outputs
available / Unevaluated / Evaluated / Disagreement / Total evaluations /
Reviewers, all from the real `EvaluationStore`), the **Evaluation
Queue**, and — once an output is focused — **Evaluate** (the full rating
form), **A/B Comparison**, **Evaluation History**, **Disagreement**,
**Aggregated Results**, **Calibration Readiness** (reusing
`avl-calibration-panel`, always `UNCALIBRATED`), **Provenance**, and
**Ask Claude**. Evaluation targets are the same generated outputs VL-D5's
Preview workspace produces (`services.generationQueueStore`) — VL-D6
never introduces a second notion of "output."

**A real interaction/rerender bug was found and fixed while testing this
workspace, at its root cause.** Submitting an A/B decision fires
`abEvaluationStore`'s "change" event; the workspace's own
`_scheduleRender()` (the same coalescing pattern VL-D5's Preview
workspace uses to avoid tearing down an in-flight `<audio>` element) was
reacting to that event by fully rebuilding, which **replaced the live
`avl-ab-evaluation` element with a brand-new one** — wiping its
just-recorded status message and both sides' listening state before the
reviewer ever saw the result of their own submission. Two changes fixed
this at the source rather than papering over it: (1) `avl-ab-evaluation`
now only resets `_statusMessage` on its *very first* connect, not on
every reconnect (`if (this._statusMessage === undefined) ...` instead of
an unconditional reset); (2) `avl-workspace-feedback` now **reuses the
same `avl-ab-evaluation` element instance** across re-renders for the
same (focused, compare-with) output pair, instead of recreating it —
the same "don't tear down live interactive state on your own event" fix
category as VL-D5's playback-safety guard, applied to the A/B decision
panel.

### Expanded Inspector

`inspector-router.js`'s existing `voice-profile` selection section gains
an **Evaluation** `<details>` block for that profile's latest
generation's output: History / Disagreement / Aggregated results / Ask
Claude, reading `services.evaluationStore` directly. Genuinely separate
from the pre-existing Feedback block above it, which still reads
`services.previewFeedbackStore` (VL-D5, untouched).

### Activity, Command Center, and Claude integration

- **Activity**: `ActivitySource.EVALUATION` (new, following the same
  additive pattern `PREVIEW` used from VL-D0 to VL-D5). Real events:
  `evaluation_started` (a reviewer picks an output from the queue —
  `avl-evaluation-select` bubbling from `avl-evaluation-queue`),
  `output_listened` (the same physical Play press already logged as
  `PREVIEW`'s "preview played," additionally logged under `EVALUATION`
  specifically when it happened inside an `avl-evaluation-form` —
  detected via `event.composedPath()` carrying an
  `AVL-EVALUATION-FORM` ancestor, so `avl-voice-player`/`avl-audio-player`
  need know nothing about evaluation at all), `evaluation_completed`/
  `evaluation_cannot_judge`/`evaluation_abandoned` (one per real
  submission, by completion state), `disagreement_detected` (a
  de-duplicated event the first time an output's evaluations actually
  meet the aggregation module's own disagreement threshold — never
  re-announced on every subsequent evaluation of an already-flagged
  output), and `ab_decision_submitted`. **Never logs the comment text
  itself**, only ids, reviewer, outcome, and dimension names.
- **Command Center**: gained a ninth panel, "Feedback" — Unevaluated
  outputs / Total evaluations / Completed / Cannot judge / Reviewers /
  Disagreement / A-B decisions, read live from
  `services.evaluationStore`/`services.abEvaluationStore`, plus a
  calibration-prep status badge (always `UNCALIBRATED`). Overview only —
  the Feedback workspace still owns the detailed queue/rating/history/
  disagreement view.
- **Claude**: `claude-evaluation-context.js` builds its context through
  the same `buildReviewClaudeContext()` every other phase's Claude
  integration uses — bounded to `recording_id` (repurposed as the output
  id), `batch_id` (repurposed as the voice profile id),
  `stage: "voice_evaluation"`, `metric`, `warning` (a real disagreement
  summary when one exists), `config`, `provenance`. Never a raw reviewer
  comment beyond what that bounded shape exposes, never a filesystem
  path, never a secret, no unrestricted shell — still only
  `NullCommandExecutor`.

## Security boundary

Nothing in VL-D6 weakens an existing invariant:

- **Speaker identity boundary** — no field for it exists anywhere in
  `Evaluation`, `ABEvaluation`, or any frontend equivalent; a dedicated
  test confirms no key on an `Evaluation` record contains
  `speaker`/`target_speaker`/`identity`/`accent`.
- **Dataset access gate** — untouched; VL-D6 never calls
  `pipeline.dataset_gate.evaluate_gate()`.
- **Source immutability** — VL-D6 never reads or references anything
  under `data/source/`.
- **Execution boundary** — the "Ask Claude" affordance stays
  session-local, still only `NullCommandExecutor`.
- **Provenance is hashes/ids only** — `output_sha256`/`config_hash` are
  hashes; no filesystem path anywhere.
- **Local-first / offline** — no cloud storage, no cloud evaluation
  service, no remote reviewer database, no new network dependency.
- **Secret scanning** — re-verified clean.
- **No arbitrary command execution** anywhere in this phase.

## Hardware abstraction

Nothing in VL-D6 hardcodes a vendor or device — it does no computation
that touches hardware at all (pure aggregation over already-recorded
records). **No RTX 3050 lock-in, no CUDA/NVIDIA-specific code path.**

## Testing

```sh
python -m pytest tests/test_voice_feedback.py -q   # 46 backend tests
cd frontend && node --test tests/*.test.mjs          # 195 frontend tests total
```

New in VL-D6: 46 backend tests (`tests/test_voice_feedback.py` — dimension
vocabulary bounds/reuse/fold, Evaluation record+persistence, A/B
evaluation, aggregation+disagreement, calibration boundary,
security/provenance) and 52 frontend tests (26 pure-logic in
`evaluation-state.test.mjs`, 26 real headless-Chromium scenarios in
`feedback.test.mjs`, covering: opening the workspace, the evaluation
queue, playback, no autoplay, replay tracking, the honest listened gate,
cannot-judge bypassing that gate, rating/confidence/comment submission,
A/B comparison (mount, Prefer A, Prefer B, No preference, Cannot judge,
blinding), disagreement display, history display, aggregated results,
calibration readiness staying `UNCALIBRATED`, Command Center integration,
Activity integration, the bounded Claude context, light theme, dark
theme, and a full-pass no-console-errors check). VL-D0 through VL-D5's
existing suites re-run unmodified except one assertion updated to
include the new `feedback` destination (a legitimate addition, not a
weakened check). Full existing Python suite (645 tests total including
VL-D6's) and `ruff check .` remain green throughout.

## Known limitations

- `EvaluationStore`/`ABEvaluationStore` are session-only on the frontend,
  same as every prior phase's client-side store before an execution
  transport existed — an evaluation made in the browser does not persist
  past a page reload.
- `furthest_position_seconds` is exactly what its name says — a position
  reached, not a guarantee of attentive listening. This is stated
  honestly rather than worked around, since no browser API can measure
  genuine attention.
- No AI Calibration Engine exists yet (VL-D15) — `calibration_state` is
  always `UNCALIBRATED`, by design, not oversight.
- Agreement/disagreement statistics are simple mean/median/variance/
  spread-threshold checks — no fabricated confidence intervals or
  statistical-significance claims exist anywhere in this phase, and none
  are planned until a future phase can justify them with real sample
  sizes.

## Next

**VL-D7 — AI Calibration Engine**.
