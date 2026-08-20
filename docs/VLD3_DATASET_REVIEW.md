# VL-D3 — Dataset Review & Voice Quality Analysis Workspace

> Status: **real quality/overlap/review logic, synthetic data only.**
> `pipeline.quality`, `pipeline.overlap`, and VAD (`audio.vad`) are all
> pre-existing Phase 2 modules VL-D3 reuses unmodified; `pipeline.candidate_review`,
> `pipeline.feedback`, `pipeline.calibration_prep`, and `pipeline.quality_summary`
> are new this phase. Every one of them only ever runs against files
> `testing.synthetic_audio` generates. **REAL RECORDINGS ARE NOT USED
> DURING VL-D3.** See "Real recording activation" below for exactly what
> changes, and does not change automatically, once they are.

## Why this is not a second quality pipeline

Phase 2 already built the measurement and decision layers this workspace
displays: `audio.analysis.measure()` (duration, sample rate, peak/RMS,
noise floor, estimated SNR, silence ratio, clipping ratio, DC offset),
`audio.vad.detect_regions()` (speech/silence regions), `pipeline.quality.assess_quality()`
(PASS/WARNING/REVIEW/FAIL, config-driven, telephone/narrowband recorded
as a *characteristic* never a defect), and `pipeline.overlap.assess_overlap()`
(a deliberately weak energy/ZCR heuristic that only ever reports a
*candidate*, never a verdict). VL-D3 does not reimplement, rename, or
duplicate any of these — the frontend's `quality_decision` and
`overlap_status` status-vocabulary domains mirror `QualityDecision` and
`OverlapStatus` exactly (verified against `frontend/contracts/generated/`),
adding only one UI-only value each where genuinely needed (see "Status
vocabulary" below).

What Phase 2 never built, because nothing before VL-D3 needed to record
a *decision about a decision*, is a place to persist a reviewer's verdict
on a technical candidate, attach feedback to it, or aggregate any of it
across a dataset. Those four gaps are `pipeline.candidate_review`,
`pipeline.feedback`, `pipeline.calibration_prep`, and `pipeline.quality_summary`.

## The speaker identity boundary (§3)

This is the one rule every other section in this document is written
around. Technical review answers *"is this recording/segment usable"* —
never *"is this Aarya," "who is speaking,"* or *"is this the target
speaker."* That second question belongs to a separate, later
identity/manual-review phase (`review.py`'s `ManualReviewLog`, from
Phase 0 — untouched by VL-D3).

The boundary is enforced by construction, not by a runtime check:

- `schemas/candidate_review.schema.json` pins `review_type` to the
  constant `"technical"` (`additionalProperties: false`), the same
  pattern `schemas/identity_review.schema.json` (Phase 3) already
  established with `review_type: "identity"` — the two schemas can never
  be confused for each other, and neither can validate a document meant
  for the other.
- `reason_code` is a **closed enum**:
  `quality_issue | segmentation_issue | overlap_issue | duration_issue |
  technical_usability | other`. There is no speaker-related value to
  select, so a reviewer cannot record a speaker judgement through this
  path even by accident.
- `CandidateReviewLog` and `pipeline.review.py`'s `ManualReviewLog` are
  two entirely separate registries, writing two separate JSON-Lines
  files. VL-D3 never merges them.
- The frontend's candidate review panel (`components/candidate-review-panel.js`)
  only ever offers Accept / Reject / Needs review with a technical reason
  — it has no UI path to ask or record "is this Aarya?"
- `tests/test_dataset_review.py::test_candidate_review_schema_has_no_speaker_related_property`
  asserts this directly against the schema, not just against one code
  path that happens not to expose it today.

## Backend

### Measurement vs. decision (unchanged from Phase 2, reused as-is)

`audio.analysis.measure()` produces numbers only — no judgement.
`pipeline.quality.assess_quality()` turns those numbers into
PASS/WARNING/REVIEW/FAIL via `QualityThresholds`, an operator-editable
config. Only genuinely unusable audio (near-total silence, heavy
clipping, no detectable activity) reaches FAIL; everything doubtful goes
to REVIEW rather than being silently discarded, because a wrongly-
rejected recording cannot be recovered. Low sample rate and band-limiting
(telephone/call audio) are recorded in `characteristics`, never scored as
a finding — VL-D3's Quality Profile panel renders `characteristics`
in its own section, separate from `findings`, so this distinction is
visible in the UI, not just in the data model.

### `pipeline.candidate_review` — technical review persistence

```python
class CandidateReviewDecision(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"

class CandidateReviewReason(StrEnum):
    QUALITY_ISSUE = "quality_issue"
    SEGMENTATION_ISSUE = "segmentation_issue"
    OVERLAP_ISSUE = "overlap_issue"
    DURATION_ISSUE = "duration_issue"
    TECHNICAL_USABILITY = "technical_usability"
    OTHER = "other"
```

`CandidateReviewLog` is a `registry.json_registry.JsonLinesRegistry` —
the same one-file-per-log, schema-validated-on-write, no-duplicate-IDs
mechanism the rest of the project already uses, keyed by `review_id`
(never a timestamp — VL-D3 §15's "never use timestamp as identity").

**A review decision is never edited.** `record_review_decision()` always
appends; a correction is a new record whose `supersedes` field names the
record it replaces. `current_decision(log, segment_id)` returns the
latest record for a segment; `history(log, segment_id)` returns every
record, oldest first, so nothing is ever silently lost (§22).
`review_disagreement_count()` counts segments whose recorded decisions
disagree across their history — a real signal for calibration prep, not
a fabricated one.

Every record carries `source_sha256`, `config_hash`, `tool_version`, and
`stage_version` — provenance sufficient to answer "what exactly was this
decision made against" without ever storing an absolute path (§16).

### `pipeline.feedback` — structured, non-authoritative operator input

```python
class FeedbackType(StrEnum):
    QUALITY_FEEDBACK = "QUALITY_FEEDBACK"
    SEGMENT_FEEDBACK = "SEGMENT_FEEDBACK"
    CANDIDATE_FEEDBACK = "CANDIDATE_FEEDBACK"
    PLAYBACK_FEEDBACK = "PLAYBACK_FEEDBACK"
```

Same `JsonLinesRegistry` pattern, attached to whatever object it's
about (`target_id`) via `feedback_for()`. **Feedback is never converted
into a training label anywhere in this phase** — `pipeline.calibration_prep`
only ever *counts* it.

### `pipeline.calibration_prep` — honestly uncalibrated, on purpose

`summarize_calibration_inputs()` always returns
`calibration_state=CalibrationState.UNCALIBRATED`, no matter what it
counts. It reports `quality_feedback_count`, `review_disagreement_count`,
`narrowband_count`, `total_recordings`, and per-type feedback counts —
real, current counts a future calibration engine will consume, never a
score this phase invents. This mirrors the same "never fabricate a
number you don't have a basis for" principle `CalibrationState`
established in Phase 3.

### `pipeline.quality_summary` — dataset-level aggregation, pure statistics

`summarize_quality()` computes exactly what VL-D3 §18 asks for from
already-computed `QualityAssessment` records — no new measurement, no
new decision:

- `average_duration_seconds` / `median_duration_seconds`
- `decision_distribution`, `sample_rate_distribution`,
  `warning_code_distribution`
- `channel_distribution` — **only** when the caller supplies
  `channels_by_source_file_id` explicitly. `AudioMeasurements` carries no
  channel count (that's inventory metadata, not an acoustic measurement),
  so this field stays empty rather than inventing a value from data that
  doesn't exist here.
- `duration_distribution`, `snr_distribution`, `speech_ratio_distribution`,
  `silence_ratio_distribution` — bucketed (`<30s`/`30-60s`/`60-120s`/`120s+`,
  `<10dB`/`10-20dB`/`20-30dB`/`30dB+`, `0-25%`/`25-50%`/`50-75%`/`75-100%`),
  with a `not_available` bucket used whenever the underlying measurement
  wasn't computed (e.g. no VAD ran) rather than silently dropping the
  recording from the distribution.
- `narrowband_count`
- `overlap_candidate_count` — **`None`** ("not measured") when the caller
  passes no `overlap_statuses`, and only ever counts `POSSIBLE_OVERLAP` /
  `OVERLAP_DETECTED`, never `NO_OVERLAP_DETECTED` or `UNKNOWN`.

An empty input list returns an all-empty, honestly-`None` summary rather
than raising or fabricating a default.

### Overlap: candidates, never verdicts

`pipeline.overlap.assess_overlap()` (Phase 2, unmodified) is explicit in
its own docstring that its energy/zero-crossing-rate heuristic produces
"weak indicators," not a determination — `confidence` is documented as
"not a probability." VL-D3's overlap review surface
(`components/overlap-review-list.js`) mirrors that honesty in its
copy: every entry is labelled **"OVERLAP CANDIDATE,"** never "confirmed
multi-speaker audio," and a persistent footer note states plainly that
this is a technical signal only and never determines who is speaking.
`tests/test_dataset_review.py::test_conversation_overlap_segment_runs_through_the_honest_candidate_vocabulary`
asserts the module returns a value from the real `OverlapStatus` enum on
a synthetic conversation fixture — not that it detects overlap, since the
heuristic itself makes no such guarantee (the pre-existing Phase 2 test
suite for this module never asserted a positive-detection trigger
either, for the same reason).

## Frontend

### Status vocabulary additions

Three new domains in `frontend/tokens/status.json`, each verified against
the corresponding backend enum via `frontend/contracts/generated/`:

| Domain | States | Relationship to backend |
|---|---|---|
| `quality_decision` | `NOT_ANALYZED, PASS, WARNING, REVIEW, FAIL` | Mirrors `QualityDecision` exactly, plus one UI-only value (`NOT_ANALYZED`) for "no assessment exists yet" — the same superset pattern VL-D1's `pipeline_stage` domain established over `StageStatus`. |
| `overlap_status` | `NO_OVERLAP_DETECTED, POSSIBLE_OVERLAP, OVERLAP_DETECTED, UNKNOWN` | Mirrors `OverlapStatus` exactly, no additions. |
| `candidate_review` | `PENDING, ACCEPTED, REJECTED, NEEDS_REVIEW` | Mirrors `CandidateReviewDecision` exactly, no additions. |

VL-D3 deliberately did **not** introduce the spec's literal
GOOD/ACCEPTABLE/WARNING/POOR/INVALID vocabulary — reusing the real
backend's PASS/WARNING/REVIEW/FAIL enum was the "reuse existing backend
contracts, do not duplicate" governing rule applied to this specific
naming mismatch, consistent with how `pipeline_stage` vs. `StageStatus`
and `hardware_calibration` vs. `CalibrationState` were resolved in prior
phases.

### New components

All zero-dependency vanilla Web Components, no framework, no build step:

- `audio-player.js` — real HTML5 `<audio>` playback of a browser-generated
  sine tone (`state/synthetic-tone.js`, a dependency-free WAV encoder,
  the frontend counterpart to `testing.synthetic_audio.generate_tone()`).
  Play/Pause/Stop/Seek/volume, `autoplay = false` and `loop = false` set
  explicitly (§9), with a visible "Synthetic tone (not a real recording)"
  disclosure. There is no real recording to play, and there will not be
  one until the dataset access gate is satisfied.
- `waveform-visualization.js` — a bar-based amplitude frame with
  silence-region shading, segment-boundary lines, and overlap-candidate
  markers, **plus a full textual legend below it** (segment id/kind/
  start/end, overlap candidate start/end/reason) — the visualization is
  never the only way this information is communicated (§8).
- `quality-profile.js` — the per-recording Quality Profile panel (§17):
  Signal / Noise / Speech / Format / Characteristics / Flags, every value
  read from the assessment object, never computed here. No assessment
  set renders "This recording has not been analyzed yet," not a blank
  or zeroed panel.
- `segment-timeline.js` — segment id/start/end/duration/kind/quality
  state/candidate state; selecting a speech segment fires a `select`
  event a host can react to (the Inspector uses this to drive the
  Technical Review panel).
- `overlap-review-list.js` — overlap candidates for one recording:
  start/end/duration/confidence (labelled "not a probability")/reason,
  with the same honest-labelling footer described above.
- `candidate-review-panel.js` — Accept / Reject / Needs review, a reason
  selector drawn only from `CandidateReviewReason`, a notes field, and a
  full append-only history list. Never asks or renders anything
  speaker-related.
- `feedback-form.js` — records `QUALITY_FEEDBACK` / `SEGMENT_FEEDBACK` /
  `CANDIDATE_FEEDBACK` / `PLAYBACK_FEEDBACK` against a target id, with a
  visible note that feedback is never used as a training label.
- `claude-review-context.js` — the bounded "Ask Claude" affordance
  described below.
- `dataset-quality-summary.js` — renders `state/quality-summary.js`'s
  output as plain text/list tables — no charting library, no canvas
  (§18's "no heavy visualization libraries, minimal frontend
  dependencies").

### `avl-workspace-dataset-review` — the new workspace

Mounted at `#/review`, added to `state/router.js`'s `DESTINATIONS`
between `recordings` and `pipeline`. Composes:

- a **dashboard** (§4) — Total recordings / Analyzed / Not analyzed /
  Ready (PASS) / Warning / Invalid (FAIL) / Blocked / Review required /
  Segments / Candidates, every number derived from the real synthetic
  fixture + quality-assessment data (`Blocked` sums each referenced
  batch's real `blocked` field; `Candidates` counts only `kind: "speech"`
  segments, since silence segments are never review candidates);
- the **Dataset Quality Summary** panel (§18), fed by
  `state/quality-summary.js`'s `summarizeQuality()` — a pure
  frontend-side mirror of the backend's `summarize_quality()` bucket
  boundaries, computed over the same synthetic fixtures;
- **filters** (§19) — search (filename/recording ID/batch ID/content
  ID), batch, quality decision, sample rate, channels, candidate state,
  narrowband-only, overlap-candidates-only;
- **sorting** (§20) — filename, duration, quality (via a fixed
  rank order), SNR, noise floor, speech ratio, warning count; ties break
  on recording id for determinism;
- a **review queue** (§14) — every speech segment across the dataset
  whose current decision (live `CandidateReviewStore` state if reviewed
  this session, otherwise the fixture's default) is `PENDING` or
  `NEEDS_REVIEW`. Re-renders on every `CandidateReviewStore` "change"
  event, so an accepted/rejected segment disappears from the queue
  immediately — a persistent, live view, not a static snapshot.

Selecting any row (table or queue) routes through the same
`SelectionModel` VL-D1/D2 already use, so the Inspector updates exactly
as it does for any other selection kind.

### Expanded Inspector (§21)

`inspector-router.js`'s `recording` view gained eight collapsible
sections, appended after the existing Identity/Metadata/Pipeline rows:
**Quality** (the Quality Profile panel plus the "Ask Claude" affordance),
**Waveform** (the audio player and waveform visualization together),
**Speech / Silence** (ratios and counts from the assessment), **Segments**
(the segment timeline), **Overlap** (the overlap candidate list),
**Technical Review** (the candidate review panel, driven by whichever
segment was last selected in the timeline), **Feedback** (the feedback
form, targeted at the selected recording), and **Provenance** (content
ID, recording ID, batch ID, classification — relative/hash identifiers
only, never a filesystem path). Nothing here renders or references
speaker identity; the existing "Speaker identity: NOT AVAILABLE" row
from VL-D1/D2 is untouched, and no new field anywhere in these eight
sections could carry one — future identity information stays entirely
outside this surface, per §21's own instruction.

### Activity, Command Center, and Claude integration (§23–§25)

- **Activity**: recording a candidate review decision
  (`CandidateReviewStore`'s `change` event, wired in `app/main.js`)
  appends a real `ActivityEvent` — severity keyed to the decision
  (accepted → success, rejected → danger, needs-review → warning) — to
  the shared `ActivityStore`, visible in both the Activity workspace and
  Command Center. Quality-analysis-completed, segmentation-completed,
  overlap-candidate-detected, and batch-review-completed events are
  seeded as synthetic fixture entries in `syntheticActivity()` (the same
  "example of what this event looks like, not a live trigger" pattern
  VL-D1/D2 already used for the four event kinds VL-D1 shipped with) —
  there is no live segmentation/quality-analysis execution transport in
  this phase to generate them for real.
- **Command Center**: gained a sixth panel, "Review" — Review queue /
  Pending candidates / Quality warnings / Recent analyses / Failed
  analyses / Current batch review (`batch-id (decided/total)`), computed
  by `state/review-summary.js`'s `summarizeReviewState()`, re-rendered
  live on every `CandidateReviewStore` change. An overview only — the
  Dataset Review workspace still owns the detailed queue/filters/sorting,
  per the same "Command Center = overview, workspace = detail" rule
  VL-D2's Imports panel already followed.
- **Claude**: `state/claude-context.js` gained `buildReviewClaudeContext()`
  — deliberately narrower than the general `buildClaudeContext()` VL-D1
  built — bounded to exactly the fields §25 names: `recording_id`,
  `batch_id`, `stage`, `metric` (name + value), `warning`, `error`,
  `config`, and `provenance` (hash-only). Rendered read-only in the
  Quality section's "Ask Claude" affordance
  (`components/claude-review-context.js`), and — like every other Claude
  surface in this project — the actual "ask" routes through the same
  `CommandExecutor` interface, which still has only one implementation,
  `NullCommandExecutor`, honestly reporting `NOT_AVAILABLE`. No arbitrary
  filesystem access, no unrestricted shell, no secrets: the same
  redaction pass every other context object passes through masks any
  opaque 20+-character value regardless of field name.

## Accent and preview preparation (§27–§29)

VL-D3 adds no accent identification, phoneme label, accent score, or
preview/voice-generation logic of any kind — none was in scope, and none
was built. What it *does* preserve, unchanged, for a future engine to
consume: sample rate, channel count, duration, speech ratio, segment
boundaries, quality decision, and recorded characteristics (narrowband,
clipping) — exactly the metadata a future accent or Voice Preview stage
would need, already flowing through `QualityAssessment` and the segment
fixtures. The Technical Candidate → Review → Preview Candidate → Future
Voice Preview → User Feedback architecture the spec describes is
realized only as far as "Technical Candidate → Review" in this phase;
nothing downstream of a reviewed candidate exists yet.

## Security boundary

Nothing in VL-D3 weakens an existing invariant:

- **Source immutability** — nothing under VL-D3 reads or writes
  `source/`; segment boundaries and candidate review decisions are
  recorded as separate derived artifacts (`CandidateReviewLog`,
  `FeedbackLog`), never as a modification to any source file.
- **Dataset access gate** — untouched; VL-D3 never calls
  `pipeline.dataset_gate.evaluate_gate()` or constructs anything that
  would need to.
- **Speaker identity boundary** — see the dedicated section above.
- **Execution boundary** — the "Ask Claude" affordance still routes
  through `NullCommandExecutor`; nothing new executes.
- **Path traversal / relative paths only** — every provenance field is a
  hash or an ID, never an absolute path.
- **Provenance** — every `CandidateReviewLog`/`FeedbackLog` record
  carries `source_sha256`, `config_hash`, `tool_version`, `stage_version`.
- **Local-first / offline** — no new network call, no new dependency
  (the client-side WAV encoder is dependency-free, same standard as the
  rest of the frontend).
- **Secret scanning** — re-verified clean.

## Real recording activation

VL-D3 does not, and cannot by itself, activate real recordings:

- Nothing in this phase constructs a `GateReport` or calls
  `evaluate_gate()` — the gate condition (`explicit_approval`) can only
  ever be set by a human attestation passed in elsewhere, never inferred
  here.
- `CandidateReviewLog` and `FeedbackLog` operate on whatever
  `source_file_id`/`segment_id` they're handed — nothing about their
  design assumes synthetic data, but VL-D3's own tests, fixtures, and CLI
  usage only ever hand them synthetic IDs.
- The frontend has no path to real data at all — the Dataset Review
  workspace only ever renders `state/synthetic-fixtures.js`.

When real recordings are eventually authorized, `pipeline.candidate_review`,
`pipeline.feedback`, `pipeline.calibration_prep`, and `pipeline.quality_summary`
already operate on real `QualityAssessment`/`OverlapAssessment` objects
today (they take the same dataclasses `pipeline.quality`/`pipeline.overlap`
already produce for real audio in Phase 2) — no architectural change is
needed, only real data, real gate approval, and a real execution
transport for the frontend to persist a review decision through
(the client-side `CandidateReviewStore`/`FeedbackStore` are still
session-only, exactly like VL-D2's `ImportQueue` was before any transport
existed).

## Testing

```sh
python -m pytest tests/test_dataset_review.py -q   # 26 backend tests
cd frontend && node --test tests/*.test.mjs         # 68 frontend tests total
```

New in VL-D3: 26 backend tests (`tests/test_dataset_review.py`) and 23
frontend tests (11 pure-logic in `dataset-review-state.test.mjs`, 12 real
headless-Chromium scenarios in `dataset-review.test.mjs`, covering all of
§36's scenario list: opening Dataset Review, selecting a recording,
Inspector updates, quality metrics rendering, waveform rendering,
playback controls, segment selection, filters, candidate review, review
queue, feedback, Command Center integration, and bounded Claude context
— each scenario also asserts zero unexpected console errors). VL-D0's
10, VL-D1's 19 (one assertion updated to include the new `review`
destination), and VL-D2's 16 re-run unmodified. Full existing Python
suite (519 tests total including VL-D3's) and `ruff check .` remain green
throughout.

## Known limitations

- `CandidateReviewStore`/`FeedbackStore` are session-only on the
  frontend, same as VL-D2's `ImportQueue` before any execution transport
  existed — a review decision made in the browser does not persist past
  a page reload; there is no `exportReviewPlan()`-consuming CLI command
  yet (the bridge function exists, mirroring VL-D2's `exportImportPlan()`,
  for a future command to consume).
- Segmentation/quality-analysis/overlap-detection are not live browser
  triggers — the corresponding Activity events are seeded synthetic
  fixtures illustrating the event shape, not evidence of a real pipeline
  run.
- The overlap heuristic itself remains weak by design (Phase 2's own
  characterization) — VL-D3 changes nothing about its accuracy, only how
  honestly its output is labelled and reviewed.
- `pipeline.quality_summary`'s duration/SNR/ratio buckets are fixed,
  hardcoded boundaries (not operator-configurable, unlike
  `QualityThresholds`) — acceptable for a first dashboard pass, revisit
  if a real dataset's distribution needs different bucket edges.

## Next

**VL-D4 — Voice Processing + Conditioning Workspace**.
