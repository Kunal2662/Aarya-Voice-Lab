# FE-3 — Aarya Glass Surface System

AARYA Voice Lab only. Not a JARVIS milestone; nothing in this phase touches
Aarya Core, any other project, or the backend (`src/aarya_voice_lab/**`).

## Purpose

FE-2 gave the app a denser, more consistent dashboard visual language on
top of FE-1's token architecture. FE-3 is the master implementation pass
requested against a JARVIS/Tony-Stark-styled reference mockup: a
restrained "glass surface" system (subtle translucency, hairline borders,
soft shadows, a reserved accent glow for focus/selection only), applied
consistently across the whole shell and workspace set, with the same
non-negotiables carried over from FE-2 — no fabricated data, no invented
identity, no CPU/GPU/RAM/disk gauges, vanilla Web Components only, real
information architecture preserved per workspace.

## Phase A — Mandatory audit

Before any code changed, two parallel read-only audits covered every
frontend component this phase could touch (~54 files not previously
reviewed in this depth), confirming: no `backdrop-filter`/blur/gradient
existed anywhere in the codebase (a clean slate for the glass system), no
JARVIS/NVIDIA/RTX references, and no third-party UI framework anywhere.
The audit also surfaced several small pre-existing inconsistencies (chip/
row padding drift, `avl-panel`'s missing host styling, duplicate input/
select CSS blocks) that became Phase B/C's actual work list, plus a
handful of Class C observations (correct today, just a style-consistency
question) that this phase intentionally did not touch — see "Known
observations, not fixed" below.

## Phase B — Design foundation

**`tokens/color.json`** gained a `glass`/`shadow` group per theme, every
value a `color-mix(in srgb, var(--avl-color-...) N%, transparent)`
expression referencing existing tokens rather than new literal colors —
so light/dark resolve correctly automatically and the glass system never
introduces a second color palette:

- `glass.surface` / `glass.surface-elevated` — panel vs. dialog/inspector
  opacity (light: 90%/94%, dark: 82%/88% — dark needs less transparency
  to keep the canvas from showing through too strongly).
- `glass.border` — a translucent hairline border, same family.
- `shadow.ambient` / `shadow.elevated` / `shadow.glow` — black-tinted
  ambient/elevated shadows and one accent-tinted glow, the last reserved
  for a glass surface's own `:focus-within` state and never shown at
  rest (the reference mockup's "glow everywhere" look was explicitly
  rejected per this project's own anti-pattern list).

**`css/base.css`** gained shared defaults that were previously duplicated
per-component: `.avl-chip`, a shared `input, select, textarea` baseline,
`.avl-glass`/`.avl-glass--elevated` utility classes, and a new
`.avl-cluster` layout utility. `.avl-cluster` is deliberately a different
shape from the existing `.avl-row` (which forces
`justify-content: space-between`): five components' local `.row`/
`.diagnostics` rules turned out to be packed-left inline groupings
(badge+label, command+tag), not row layouts — converting them to
`avl-row` would have visually broken them, so a correctly-scoped new
utility was added instead of force-fitting the existing one.

Mechanical cleanup across the components that had the padding/duplication
drift the audit found: `status-badge.js`, `quality-profile.js`,
`workspace-voices.js`, `workspace-models.js`, `claude-fix-flow.js`
(3 different chip padding magic numbers → `--avl-space-1`);
`activity-timeline.js`, `calibration-panel.js`, `claude-task-status.js`,
`claude-command-shell.js` (local `.row`/`.diagnostics` rules →
`.avl-cluster`); `workspace-recordings.js`, `workspace-activity.js`,
`processing-profile-editor.js`, `workspace-dataset-review.js`,
`workspace-feedback.js`, `workspace-preview.js` (duplicate `input,
select` rule blocks removed, now inherit base.css's shared default);
`text-input.js`, `waveform-visualization.js` (`6rem` → `--avl-space-24`);
`generation-queue.js`, `processing-queue.js` (progress bar width only,
`--avl-space-24`); `audio-player.js`, `rating-panel.js`,
`confidence-control.js` (remaining magic-number spacing → the matching
`--avl-space-*` token).

## Phase C — Shared primitives

The glass treatment was centralized in the primitives themselves, not
left to each caller:

- **`components/panel.js`** — `avl-panel` previously had no `:host`
  background/border/radius of its own; the audit found only one caller
  (`workspace-command-center.js`) had ever added a border/radius from
  outside, meaning every *other* workspace's panels rendered with no
  visible card boundary at all. Fixed by giving `avl-panel` its own
  glass-surface `:host` styling and removing the now-redundant
  Command-Center-only override — a real cross-workspace visual
  consistency fix, not just a restyle.
- **`components/card.js`** — moved from an opaque solid surface to the
  same glass-surface treatment as `avl-panel`, so cards and panels read
  as one consistent surface family. No external caller styled the
  `avl-card` host, so this was a safe, non-breaking change.
- **`components/confirm-action.js`** — the dialog panel is the app's
  highest surface, so it uses `glass.surface-elevated` (more opaque, more
  shadow) rather than the base panel/card treatment, matching the
  documented hierarchy (canvas → workspace → glass panel → elevated
  surface → focused state). Its `:focus` state — always present the
  instant the dialog opens — is where the reserved accent glow is
  applied, since this component already implements a real focus trap.
- **`components/app-shell.js`** — the sidebar and inspector chrome
  (persistent regions sitting above the plain workspace canvas) gained a
  subtle glass background/border, distinguishing them from the canvas
  without competing with the glass panels inside the workspace itself.
  The activity bar keeps its own existing dedicated background token,
  out of this phase's scope.

## Phase E — Real-data stat tiles for the remaining workspaces

FE-2.3 converted 6 workspaces' dashboard sections to `avl-stat-tile`.
The audit identified 4 more workspaces with genuine computed counts that
had never been surfaced as a headline dashboard, each now getting the
same treatment (5-tone cycle, real values only, honest "0" where a count
is genuinely zero):

- **`workspace-recordings.js`** — Total / Valid / Warning / Invalid,
  computed from the same `validation` field already driving each row's
  status badge.
- **`workspace-voices.js`** — Total / Calibrated / Provisional /
  Uncalibrated, computed from each voice's real `calibrationState`.
- **`workspace-models.js`** — Total models / Backends supported /
  Installed / Not installed, computed from the real model list and the
  vendor-neutral `compute_backend.json` contract already powering the
  "Supported compute backends" panel below it.
- **`workspace-activity.js`** — Total events / Sources active, computed
  from the same `activityStore.list()` the timeline below it already
  renders (a per-source breakdown wasn't added: with 10+ possible
  sources, a tile per source would be visual noise disproportionate to
  its usefulness, so only the two genuinely summary-level numbers were
  surfaced).

## Accessibility

Glass surfaces reduce background opacity, so every changed
background/text pairing was checked against WCAG AA (4.5:1) with a real
Chromium instance: `getComputedStyle()` was used to read each surface's
actual rendered background and text color, the glass surface's alpha was
composited over its parent canvas color, and the contrast ratio was
computed from the result — in both light and dark theme. All checked
pairs pass, with the closest margin being the sidebar's active-item label
(colored accent text on the glass sidebar background) at ~5.6:1 (light)
/ ~5.8:1 (dark) — comfortably above the 4.5:1 minimum but the tightest
case in the system, worth keeping in mind if the accent color token is
ever darkened. Panel headings, stat-tile values, and the confirm-action
dialog's heading/description text all measure 6.5:1 or higher in both
themes. Focus visibility, landmark roles, and heading structure were not
changed by this phase and were re-verified unchanged.

## Known observations, not fixed (Class C)

Flagged by the Phase A audit as correct today and out of this phase's
mechanical-fix scope — an information-architecture or style-consistency
question for a future phase to decide, not a defect this phase silently
accepted:

- `workspace-calibration.js` and `workspace-claude.js` both let their
  `"ready"` render state absorb what could arguably be
  `avl-workspace-state`'s `empty`/`blocked` states (an unavailable
  calibration engine; an unfetched Claude snapshot). `workspace-claude.js`
  already has an explicit code comment documenting this as intentional;
  changing it is a state-machine design decision, not a mechanical fix.
- `claude-task-status.js`'s `.risk` chip and `claude-command-shell.js`'s
  `.catalogue-row .risk` chip use a smaller `padding: 0.1rem
  var(--avl-space-1)` than the standard chip family — deliberately left
  as-is; it's a genuinely smaller "tag" shape, and converting it to the
  standard chip padding would change its visual size, not just its
  token source.
- Three call sites apply a semantic state token directly to text rather
  than routing it through `avl-status-badge`
  (`calibration-application-panel.js:63-64`,
  `calibration-readiness-panel.js:31-32`, `disagreement-view.js:33`) —
  the tokens used are correct, this is a style-consistency question
  about which primitive should own the coloring, left untouched.

## Testing

```sh
cd frontend && node --test tests/*.test.mjs
```

367/368 pass; the one intentional pre-fix failure (visual regression
baselines stale after the glass-surface rendering change) was resolved
by regenerating baselines:

```sh
cd frontend && node tools/visual-baseline.mjs --update
```

All 20 scenarios were rewritten (every workspace's rendering changed at
least slightly due to the new glass panel/card treatment); the suite then
passes 368/368.

One real regression was found and fixed during this phase's own
regression pass, self-caused: `confirm-action.test.mjs`'s test 11
asserted the dialog's non-danger border used
`--avl-color-border-default`, the pre-glass token. Since Phase C
intentionally moved that border to `--avl-color-glass-border` as part of
the elevated-surface treatment, the test's assertion was updated to match
the new, correct implementation (and strengthened with an explicit check
that the danger token specifically is never used in the non-danger case)
rather than reverting the design change.

Backend regression: `pytest tests/` (711 passed) and `ruff check .` (all
checks passed) were re-run unmodified; FE-3 touched no
`src/aarya_voice_lab/**` file. A manual scan of every changed file for
JARVIS/NVIDIA/RTX/vendor-specific language found nothing beyond one
pre-existing header comment in `workspace-models.js` that explicitly
states NVIDIA is *never* privileged — consistent with, not a violation
of, the vendor-neutral rule.

## Scope and non-goals (FE-3)

Explicitly **not** built or changed in this phase:

- No CPU/GPU/RAM/disk gauges, no vendor-specific hardware assumptions —
  same honest AVAILABLE/UNKNOWN capability badges as FE-2, unchanged in
  substance.
- No user/avatar/identity chip — this app still has no login/account
  system to represent.
- No fabricated metric, count, or percentage anywhere; every new
  stat-tile value is read from a store or contract that already existed.
- No migration away from vanilla Web Components/Shadow DOM — no React,
  no other framework, no build step.
- No fix for any of the three Class C observations above — each is a
  design decision for a future phase, not a mechanical defect.
- No FE-4 work of any kind was started in this phase.

## Next

FE-4 (not started, not scoped here) would be the next frontend milestone
once explicitly requested.
