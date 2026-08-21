# FE-2 — Visual Redesign Pass 1

AARYA Voice Lab only. Not a JARVIS milestone; nothing in this phase touches
Aarya Core, any other project, or the backend (`src/aarya_voice_lab/**`).

## Purpose

FE-1 fixed the shared frontend surface (confirmation dialogs, icons,
responsive shell, CSS utilities, accessibility) without changing the
app's visual language. FE-2 is that visual pass: a denser
dashboard-style presentation for the workspaces that already compute
real summary numbers, built entirely on top of FE-1's token
architecture — no new framework, no new build step, no rewrite of any
working interaction model.

The starting point was a reference mockup showing a denser dashboard
(colored icon-badge stat tiles, a user/avatar chip, live-looking
hardware gauges). Three explicit ground rules shaped what actually got
built, decided before any code was written:

1. **No fabricated data.** Several of the mockup's specific numbers
   (CPU/GPU utilization percentages, a specific "RTX 3060" GPU model,
   a recording private/shared split, a voice verified/pending split,
   Claude-bridge round-trip latency) have zero backing anywhere in
   this codebase — confirmed by code search before any UI was built.
   None of those were implemented. Where a real number exists, it's
   shown; where it doesn't, the existing honest "Not available"/"Not
   measured" fallback renders instead — the same discipline every
   prior milestone in this app has followed.
2. **No fabricated identity.** The mockup's user avatar + name/role
   chip has no counterpart in this app: there is no login, no
   accounts, no user-identity system at all — it's a local-first,
   single-operator tool. No such element was added anywhere.
3. **No new backend scope.** Hardware capability reporting stays on
   the existing `avl-hardware-profile-card` AVAILABLE/UNKNOWN pattern,
   just restyled — no new hardware-snapshot export was added, even
   though RAM/disk totals and GPU name/driver are real if freshly
   queried, since polling/gauge framing was explicitly out of scope
   for a visual-only pass.

## FE-2.1 — New tokens and primitives

**`tokens/color.json`** gained a `category` group: 5 decorative
accent colors (`violet`, `blue`, `green`, `pink`, `teal`), each with a
`-subtle` background variant, defined for both light and dark themes.
These are purely decorative variety for stat-tile icon badges — never
semantic status, which stays exclusively `status.json`'s existing
domain vocabulary (`avl-status-badge` is untouched).

Three new component primitives, each following the same honest-value
convention as the existing `avl-metric-placeholder`:

- **`components/stat-tile.js`** (`<avl-stat-tile label="..."
  value="..." unit="..." tone="..." icon="...">`) — a labeled number
  in a card with a colored icon badge. Omitting `value` renders "Not
  available" in the same italic/muted treatment as
  `avl-metric-placeholder`, never a fabricated 0. The default slot is
  an optional secondary detail line, left to the caller since only the
  caller knows whether a breakdown is real for that specific count.
- **`components/icon-badge.js`** (`<avl-icon-badge tone="..."
  icon="...">`) — a small colored rounded chip wrapping the existing
  `avl-icon`; `stat-tile` uses it internally, and it's available
  standalone.
- **`components/meter.js`** (`<avl-meter label="..." value="..."
  max="..." tone="...">`) — a horizontal progress bar for the rare
  case where a real percentage exists (e.g. "pipeline stages
  completed / total stages", both already-real counts). Omitting
  `value`/`max` renders "Not measured" instead of a bar at 0%.

Tests: `tests/fe2-primitives.test.mjs` (6 cases), covering rendering,
tone application, honest fallbacks, and slot projection for all three.

## FE-2.2 — Command Center redesign

`workspace-command-center.js`, the flagship screen, gained:

- A real (non-"live") subtitle — this screen has never polled
  anything, so it never claims to be real-time.
- A headline row of 4 `avl-stat-tile`s, each reading an
  already-wired, already-real service the panels below it read the
  same way: **Jobs running** (`jobStore.current().length`, `X failed`
  detail from `jobStore.failed().length`), **Pipeline stages**
  (`pipelineStageContract`'s real implemented/total counts),
  **Models** (`generationModelStore.list().length` — seeded from a
  registered model list at startup, not fabricated), **Voice
  profiles** (`voiceProfileStore.names().length` — genuinely 0 by
  default in a fresh session, since no voice profile exists until one
  is created; that's the honest truth of a local-first per-session
  tool, not a bug).
- A real `avl-meter` inside the existing Pipeline panel showing
  "stages implemented / total stages" as an actual progress bar — the
  one legitimate percentage this screen can honestly show, computed
  from the same two numbers the panel already displayed as plain
  metrics.

No existing panel, store wiring, or data source was removed or
changed — this is additive restyling on top of the same 11-panel
overview that was already there.

## FE-2.3 — Rollout to the other workspaces

Every workspace inherits the new palette/spacing automatically —
that's the point of a token-driven architecture, and required no
per-file changes.

Six more workspaces had their own real dashboard/summary section
(a repeated pattern: a `_dashboardCounts()`/`_counts()` method feeding
a grid of label/value pairs), converted to `avl-stat-tile` the same
way as Command Center's headline row, using the 5 categorical tones
cycled for visual variety and each workspace's own sidebar icon:

- `workspace-batches.js` — Dataset dashboard (files/accepted/warning/
  invalid/blocked/duplicates/batches/processing/candidates/review
  items).
- `workspace-import.js` — the queue's Importing/Accepted/Warnings/
  Invalid/Blocked/Duplicates/Failed counts.
- `workspace-dataset-review.js` — total/analyzed/ready/warning/
  invalid/blocked/review-required/segments/candidates.
- `workspace-processing.js` — the processing dashboard (total/queued/
  processing/success/warning/failed/blocked/cancelled/avg duration/
  quality improved/degraded).
- `workspace-preview.js` — the generation dashboard (equivalent
  counts for the preview/generation queue).
- `workspace-feedback.js` — outputs/unevaluated/evaluated/
  disagreement/total evaluations/reviewers.

Each of these previously rendered its dashboard as either
`avl-metric-placeholder` rows or a hand-rolled `.metric` div — both
replaced 1:1 with `avl-stat-tile`, same labels, same real values, only
the presentation changed. Three existing tests (`feedback.test.mjs`,
`preview.test.mjs`, `processing.test.mjs`) asserted on the old
`.metric .label` DOM shape and were updated to query
`avl-stat-tile[label]` instead — same assertions, same expected label
lists, just pointed at the new markup.

The remaining 8 workspaces (Recordings, Pipeline, Voices, Models,
Calibration, Claude, Activity, Settings) have no natural
"headline dashboard" section — they're lists, forms, or detail views
by design. Per FE-2's own instruction to preserve each workspace's
actual information architecture, none of them were restructured to
manufacture a tile row that wasn't already there; they get the new
visual language exactly the way every workspace does, through tokens.

## Testing

```sh
cd frontend && node --test tests/*.test.mjs
```

New test file: `tests/fe2-primitives.test.mjs`. Updated:
`tests/feedback.test.mjs`, `tests/preview.test.mjs`,
`tests/processing.test.mjs` (dashboard DOM query only, per above).

Visual regression baselines were regenerated for the 10 scenarios
whose rendering actually changed (Command Center in all its captured
states, Import, Batches, Dataset Review, Processing, Preview,
Feedback) and left untouched for the other 10, whose workspaces
weren't part of this pass:

```sh
cd frontend && node tools/visual-baseline.mjs --update
```

Backend regression: the full existing `pytest` suite and `ruff check
.` were re-run unmodified before and after this work; FE-2 touched no
`src/aarya_voice_lab/**` file. One incidental fix surfaced during this
pass's regression, unrelated to FE-2's own changes: an FE-1 test file,
`tests/token-application.test.mjs`, tripped
`security/source_protection.py`'s filename heuristic ("token" reads as
a possible secret/credential filename) — the same class of issue
FE-1's own "Known limitations" already documented for
`tokens.css`/`build-tokens.mjs`, just missed for this one file at the
time. Fixed the same way: renamed to
`tests/css-variable-application.test.mjs`, content unchanged, the
scanner itself untouched.

## Scope and non-goals (FE-2)

Explicitly **not** built or changed in this phase:

- No CPU/GPU/RAM/disk percentage gauges — nothing in this codebase
  measures CPU load or GPU utilization, and building them would mean
  fabricating numbers. `avl-hardware-profile-card`'s existing honest
  AVAILABLE/UNKNOWN capability badges are the only hardware-status UI,
  unchanged in substance.
- No new backend export, endpoint, or polling of any kind.
- No user/avatar/identity chip anywhere — this app has no
  login/account system to represent.
- No dataset/recording/model/voice count that isn't already real and
  already wired through an existing store; no invented "private/
  shared" or "verified/pending" style splits.
- No restructuring of the 8 workspaces that don't have a natural
  dashboard section.
- No migration away from vanilla Web Components/Shadow DOM — no
  React, no other framework, no build step.
- No rewrite of any working interaction model — every pre-existing
  test kept passing unmodified except the 3 noted DOM-query updates
  above.
- No FE-3 work of any kind was started in this phase.

## Next

FE-3 (not started, not scoped here) would be the next frontend
milestone once explicitly requested.
