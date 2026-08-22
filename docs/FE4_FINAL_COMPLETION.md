# FE-4 → FE-10 — Final Frontend Completion

AARYA Voice Lab only. Not a JARVIS milestone; nothing in this phase touches
Aarya Core, any other project, or the backend (`src/aarya_voice_lab/**`).

## Purpose

FE-3 finished the Aarya glass surface system. This is the master
completion program requested against it: FE-4 (whole-application
consistency), FE-5 (interaction completion), FE-6 (responsive +
accessibility hardening), FE-7 (visual system hardening), FE-8 (real-data
honesty audit), FE-9 (performance + architecture hardening), and FE-10
(final validation, single commit). Per the governing directive, every
phase's substance had to be real — audited with evidence, not assumed —
and every genuine defect found had to be fixed, not merely documented.

## Method

Four parallel read-only audits covered the full component tree
(~80+ files) before any code changed, each targeting a different defect
class: workspace/state consistency, accessibility/responsive/interaction
gaps, fabricated or misleadingly-static runtime data, and
performance/architecture issues (listener leaks, render-loop risk,
redundant computation). Findings were classified A (blocking, must fix),
B (small, mechanical, directly in scope, fix), or C (real observation,
larger design question, document rather than guess). This mirrors the
same audit-then-classify discipline FE-3 established.

## Defects found and fixed (Class A)

- **`workspace-recordings.js`'s "Status" column was fully fabricated.**
  Every row unconditionally rendered a `state="running"` status badge,
  regardless of the recording's actual data — a hardcoded literal, never
  read from `recording`. The underlying fixture field
  (`recording.processingState`) turned out to hold a pipeline *stage
  name* (e.g. `"candidate_manifest"`), not a status value from the
  `pipeline_stage` domain's queued/running/success/... vocabulary, so
  there was no real per-recording status to badge honestly. Fixed by
  rendering the real stage name as text instead of fabricating a status.
- **`workspace-command-center.js`'s Pipeline panel hardcoded "Queued"
  and "Warnings" to the literal `0`**, always, even though
  `jobStore.list()` (already read two lines below for "Running"/"Failed")
  has real `QUEUED`/`WARNING` job statuses available. Fixed to filter the
  real job list, matching the pattern already used for the adjacent
  metrics.
- **Five workspace components leaked event listeners on every
  navigation**: `workspace-command-center.js`, `workspace-preview.js`,
  `workspace-feedback.js`, `workspace-processing.js`, and
  `workspace-import.js` all subscribed to app-lifetime singleton stores
  (`jobStore`, `generationQueueStore`, etc.) in `connectedCallback()`/
  `set services()` but had no `disconnectedCallback()` to unsubscribe —
  in contrast to 15+ sibling files (`workspace-dataset-review.js`,
  `workspace-calibration.js`, every `*-queue.js`/`*-history-panel.js`)
  that already do this correctly. Each fresh component instance
  `app/main.js` creates on navigation was pinned alive forever by the
  store's retained listener, growing unboundedly with every visit to
  those five workspaces. Fixed by storing each handler and removing it
  in a new `disconnectedCallback()`, mirroring the existing correct
  pattern exactly.
- **The bulk-import file picker had no keyboard path at all.**
  `import-drop-zone.js`'s native `<input type="file">` was hidden with
  `display: none`, which removes an element from both the tab order and
  the accessibility tree — the wrapping `<label>` has no native
  keyboard-activation behavior of its own. A keyboard-only user could
  not open the file picker; drag/drop is inherently mouse-only. Fixed by
  switching to the same visually-hidden-but-focusable technique
  `css/base.css`'s `.avl-sr-only` already uses (absolute position,
  1×1px, clipped) instead of `display: none`, so the real `<input>` stays
  keyboard-focusable and Enter/Space opens the OS picker natively — no
  custom keyboard handling needed. Verified with real Tab-key traversal
  in Chromium.

## Defects found and fixed (Class B)

- **Two click-to-select rows had no keyboard equivalent**:
  `workspace-voices.js`'s voice header and `workspace-preview.js`'s
  output card (`avl-voice-preview-card`) both wired `click` to select an
  item, with no `keydown`, `role="button"`, or `tabIndex`, unlike every
  other selectable row in the app (`batch-card.js`,
  `workspace-recordings.js`'s table rows, etc.). Fixed both to match the
  established pattern, including the output card's existing
  "don't refocus when the click landed on an embedded Play/Pause/Seek
  control" guard, extended to the new keydown handler via the same
  `composedPath()` check.
- **A real, already-implemented metric was never surfaced anywhere**:
  `CandidateReviewStore.disagreementCount()` (segments where a re-review
  produced a different decision) existed and was tested but no UI read
  it. Added to `state/review-summary.js`'s `summarizeReviewState()` and
  Command Center's Review panel as "Re-review disagreement".
- **Two per-keystroke performance issues**: `workspace-dataset-review.js`
  and `workspace-recordings.js` both recomputed their full dashboard
  counts (5+ filter/reduce passes) on every `_render()` call, including
  every character typed into their search box — even though the counts
  depend only on the full unfiltered row list, never on search/filter
  state. Memoized both on the underlying array's own identity (set once
  in `_load()`), so a search keystroke now only re-runs the actual
  filter/sort pass, not the dashboard recount.
- **`QUALITY_RANK` was defined identically in two files**
  (`workspace-dataset-review.js`, `workspace-processing.js`). Centralized
  in `state/quality-summary.js` (which already owns the related
  `summarizeQuality()` aggregation) so the two call sites can't silently
  drift if the decision vocabulary is ever extended.
- **Dashboard KPI grid consistency**: six workspaces
  (`workspace-preview.js`, `workspace-processing.js`,
  `workspace-feedback.js`, `workspace-dataset-review.js`,
  `workspace-import.js`) rendered their stat-tile row as a bare `<div>`
  while five others already wrapped the equivalent grid in `avl-panel`.
  Wrapped all six to match the majority (and more visually consistent)
  pattern; `workspace-command-center.js`'s headline row was left as its
  own bare `<div>` deliberately — see "Observations, not fixed" below.
- **Section subheading duplication**: four workspaces each declared an
  identical local `h3 { font: var(--avl-type-subheading-weight) ...; }`
  CSS rule instead of reusing the shared `.avl-type-subheading` class
  the way `workspace-calibration.js` already does. Converted all four
  (plus `workspace-dataset-review.js`'s Review Queue heading) to the
  shared class, keeping only each file's own local margin rule.

## Observations, not fixed (Class C) — real findings, deliberately left alone

- **`workspace-preview.js`, `workspace-processing.js`, and
  `workspace-feedback.js` render `state="ready"` unconditionally**,
  never `"empty"`, even when their queue/output lists are genuinely
  empty. Investigated rather than mechanically "fixed" to match
  `workspace-batches.js`'s pattern: unlike batches/voices (where an
  empty list *is* the entire screen, nothing else to do), these three
  workspaces always have real, always-usable top-level content — a
  generation form, a processing-profile editor + recordings table, an
  evaluation queue — regardless of whether any items exist yet. Their
  sub-lists already show honest, granular "No … yet" messaging inline
  (confirmed in `generation-queue.js`, `processing-queue.js`,
  `evaluation-queue.js`). Collapsing the whole workspace into a
  full-page "empty" placeholder would hide that functional UI — a
  regression, not a fix. Left as `"ready"`, matching Command Center's
  same deliberate choice.
- **`workspace-command-center.js`'s headline stat-tile row stays a bare
  `<div>`**, not wrapped in `avl-panel` — this is FE-2's documented
  "hero row" design (see `docs/FE2_VISUAL_REDESIGN.md`), deliberately
  more prominent than the panel grid below it, not an oversight.
- **Command Center's `<p class="subtitle">`** is the only workspace with
  descriptive text under its heading — defensible as the app's one
  overview/landing screen, but a real, visible inconsistency worth a
  product decision if it ever matters.
- **Panel-vs-bare-section grouping split**: `workspace-feedback.js`,
  `workspace-preview.js`, `workspace-processing.js`, and
  `workspace-dataset-review.js`'s detail sections (Evaluate, Generation,
  Processing profiles, Review queue, etc.) are bare `<h3>` + content, not
  `avl-panel`-wrapped, while overview-style workspaces
  (`workspace-settings.js`, `workspace-calibration.js`) wrap every
  section. Reads as "panels for overview screens, bare sections for
  dense interactive workflows" rather than an oversight — a design
  question, not a mechanical fix.
- **Action/control placement has five different conventions** across
  workspaces (a dedicated top-level actions row, a filters row, an
  action buried inside a form, a per-row button, an action nested three
  panels deep) — a real UX inconsistency, but deciding whether a shared
  "workspace actions" slot should exist is a design question outside
  this program's mechanical-fix scope.
- **`workspace-recordings.js`'s validation badge uses `domain="core"`**
  while the structurally identical concept in
  `workspace-dataset-review.js` uses the purpose-built
  `domain="quality_decision"` — two different domain-mappings for the
  same "is this recording OK" signal, an architecture question.
  Table horizontal-scroll wrapping (16 components render `<table>`, none
  wrap themselves in `overflow-x: auto`, relying instead on the
  workspace column's own `overflow: auto`) was checked and confirmed not
  actually broken — content stays reachable via scroll, just not scoped
  as tightly as it could be.
- **`GenerationModelStore.listByBackend()` and
  `PreviewFeedbackStore.countsByCategory()`** are implemented and tested
  but unused — unlike `disagreementCount()`, neither has an obvious
  missing UI slot (no per-backend model list view or feedback-category
  breakdown widget exists anywhere to wire them into), so this reads as
  unused API surface rather than a hidden gap.
- **Average-duration computation** (map → filter-nulls → reduce) appears
  independently in `workspace-processing.js`, `workspace-preview.js`,
  and twice more in `workspace-command-center.js`'s own overview
  re-derivation. Real duplication, but Command Center's copies are
  explicitly documented elsewhere as "overview only, re-derives from the
  same real store rather than depending on the detail workspace" — a
  deliberate design property, not an oversight — so extracting a shared
  helper was judged lower-value than the fixes above and left alone.

## Testing

```sh
cd frontend && node --test tests/*.test.mjs
```

One real test update was required: `dataset-review.test.mjs`'s
"Command Center's Review panel shows real, non-fabricated review counts"
asserted the exact pre-existing metric label list — updated to include
the new "Re-review disagreement" tile (the fix itself, not a weakening;
the assertion is still exact-list, still catches drift).

Visual regression baselines were regenerated for the 7 scenarios whose
rendering actually changed (Import, Recordings, Dataset Review,
Processing, Preview, Feedback, Processing-blocked); the other 13 —
including all three Command Center captures — are byte-identical,
because the Command Center changes (the Queued/Warnings fix, the new
disagreement tile) land inside panels below the fixed 900px capture
viewport, not because nothing changed:

```sh
cd frontend && node tools/visual-baseline.mjs --update
```

Real-Chromium verification covered: all touched workspaces in light
theme, `workspace-preview.js` in dark theme, `workspace-recordings.js`
at the narrow-desktop breakpoint (sidebar collapse, table degrades via
scroll, no layout breakage), the import file input's real keyboard
focusability (`getRootNode().activeElement`, and independently a real
Tab-key traversal reaching it), and the voice-header's
role/tabIndex/aria-label. Zero console errors across every check.

Backend regression: `pytest tests/` (711 passed), `ruff check .` (all
checks passed), and `aarya-voice validate-environment`
("Environment validation: PASSED") were all re-run unmodified; this
program touched no `src/aarya_voice_lab/**` file. A banned-term scan
(JARVIS/NVIDIA/RTX/Tony Stark) across every changed file found nothing.

## Scope and non-goals

Explicitly **not** built or changed in this program:

- No fabricated data, metric, or state anywhere — every fix either
  removed a fabrication or wired up a real, already-existing source;
  nothing was invented to fill a gap.
- No backend capability invented for the sake of an interaction —
  FE-5's interaction-completion review confirmed the existing
  filter/sort/select/dialog/keyboard-shortcut surface already reflects
  real backend/state capability; nothing was added that the app can't
  honestly back.
- No migration away from vanilla Web Components/Shadow DOM — no React,
  no other framework, no build step.
- None of the Class C observations above were "fixed" by guessing at
  the right design decision — each is a real, evidence-backed finding
  left for deliberate human judgment.
- No FE-11 or beyond work of any kind was started.

## Next

Further frontend work (any of the Class C observations above, or a new
milestone) would be the next step once explicitly requested.
