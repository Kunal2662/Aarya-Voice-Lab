# FE-1 — Frontend Polish Pass 1

AARYA Voice Lab only. Not a JARVIS milestone; nothing in this phase touches
Aarya Core, any other project, or the backend (`src/aarya_voice_lab/**`).

## Purpose

VL-D0 through VL-D10 built the application's functionality workspace by
workspace. FE-1 is the first pass back over the *shared* frontend
surface once all 15 workspaces existed: a shared confirmation dialog
primitive, real SVG icons, a genuinely responsive desktop shell, shared
CSS utilities to cut duplication, a small visual-identity pass, a
visual regression harness, and a real accessibility audit. It adds no
new workspace, no new backend capability, and no new state — see
"Scope and non-goals" below for what stayed deliberately untouched.

## Blocking prerequisite: design-token delivery inside Shadow DOM

Before any FE-1 workstream started, a pre-existing, cross-cutting bug
was found and fixed: `css/variables.css`'s design tokens were declared
under `:root`, but every component links that stylesheet into its own
**Shadow DOM** root (`base-element.js`'s `_linkSharedStyles()`) — and
`:root` never matches inside a shadow tree (this is standard CSS
behavior, not a browser bug; only `:host` can select the shadow host
itself). The practical effect, present since VL-D0: every
`var(--avl-*)` reference in every component fell through to its
CSS-specified initial value or inherited default, not the real token
value, in every component that never happened to receive the value by
inheritance from an ancestor.

Confirmed pre-existing (not introduced by FE-1) via `git stash` against
the pristine VL-D10 commit, and via an isolated, codebase-independent
test proving `:root{--x:red}` in a shadow `<style>` never applies while
`:host{--y:blue}` does.

Fix, applied to `tools/build-css-variables.mjs` (the generator; the
output `css/variables.css` is never hand-edited):

- **Non-theme-reactive tokens** (typography, spacing, radius, layout,
  motion, reduced-motion) — these never need to react to an ancestor
  attribute — changed from `:root { ... }` to `:host, :root { ... }`,
  so they resolve correctly inside every shadow tree directly.
- **Theme-reactive color tokens** — driven by `<html data-theme="dark">`,
  an ancestor attribute no `:host` selector can observe, and a value
  set directly via `:host` would always win over an inherited value
  regardless of specificity, which would break dynamic theme switching
  — stayed `:root`-scoped, but `variables.css`/`base.css` are now
  *also* linked at the real document root (`app/index.html`,
  `shell/index.html`), so `:root` has a genuine `<html>` to match and
  the resolved values inherit down through every shadow boundary (CSS
  custom properties are the one thing that crosses shadow boundaries
  by inheritance).

Verified via `tests/token-application.test.mjs` (new): real
`getComputedStyle()` measurements for color (static and dark-toggle
reactivity), spacing, border-radius, typography, layout grid, motion
duration, reduced-motion collapse, a multi-workspace token consumer,
and the document body background — not just that the CSS file
contains the right text, but that the browser actually resolves it.

## FE-1.1 — Shared confirmation dialog (`avl-confirm-action`)

`components/confirm-action.js`. Every destructive/confirming action in
the app (currently: Settings' "Clear session data") now goes through
one real, tested dialog primitive instead of an ad hoc
`confirm()`-style pattern per component:

- `role="dialog"` `aria-modal="true"`, `aria-labelledby`/
  `aria-describedby` pointing at internal shadow-scoped title/
  description text.
- Focus moves into the dialog on open, returns to the triggering
  element on close.
- `Escape` dispatches `avl-dialog-cancel`; clicking the backdrop does
  the same.
- A real `Tab`/`Shift+Tab` focus trap. Action buttons are provided by
  the caller via `slot="actions"` (light-DOM children), not hardcoded
  — the trap resolves each slotted element to its real focusable
  target (`{host, target}` pairs), since `document.activeElement`
  retargets to a custom element's *host*, not its innermost shadow
  descendant, once focus is inside a nested shadow tree, and elements
  like `<avl-button>` aren't natively focusable themselves.

`workspace-settings.js`'s session-clear flow uses plain native
`<button>` action elements (deliberately not `<avl-button>`) because
the existing, untouched `tests/session.test.mjs` queries
`shadowRoot.querySelectorAll("button")` directly — documented in a
code comment at the call site rather than silently diverging from the
"use avl-button" recommendation.

Tests: `tests/confirm-action.test.mjs` (11 cases).

## FE-1.2 — Responsive/adaptive desktop shell

The shell previously had one fixed desktop layout. `app-shell.js` and
`sidebar-nav.js` now respond to a `75rem` narrow-desktop breakpoint
(still desktop-only — this is not a mobile/stacked layout, which
remains explicitly out of scope, see below):

- Below `75rem`, the sidebar collapses to an icon rail
  (`--avl-layout-sidebar-width-collapsed`); each nav item keeps its
  `aria-label`/`title` so the accessible name and tooltip survive
  collapse, and icons stay visible.
- `app-shell.js` reallocates the freed column width to the workspace
  area.
- The Inspector, keyboard navigation into collapsed items, and the
  pre-existing `60rem` shell minimum-width floor all keep working —
  the floor's own text claim was previously non-functional (a
  side-effect of the Shadow-DOM token bug above); fixing token
  delivery made it genuinely enforced, confirmed by measuring real
  rendered/scroll width at a `700px` viewport.

Tests: `tests/responsive-shell.test.mjs` (11 cases).

## FE-1.3 — Real SVG icon system

`components/icon.js`, `<avl-icon name="..." size="..." label="...">`.
Replaces ad hoc Unicode glyphs (`◆`, `✕`, etc.) used as icons across
the sidebar and elsewhere with real, hand-authored SVG icons:
`currentColor` stroke (inherits text color, respects theme), default
size from `--avl-space-4`, `aria-hidden` by default (decorative) or
`role="img"` + `aria-label` when a `label` attribute is set, and a
visible "?" fallback glyph for an unrecognized name rather than
rendering nothing. `sidebar-nav.js` and `app/main.js`'s
`DESTINATION_META` were switched to icon names; `notice-banner.js`'s
dismiss control (FE-1.6) was the one other remaining Unicode-glyph
spot and was switched too.

Tests: `tests/icon.test.mjs` (6 cases).

## FE-1.5 — Shared CSS utility system

Roughly 20 components had near-duplicate `.row { display: flex;
justify-content: space-between; ... }`-shaped rules, each hand-copied
per component. `css/base.css` gained shared utility classes —
`.avl-row`, `.avl-row--bordered`, `.avl-row--center`, `.avl-stack`,
`.avl-label` — and 9 components (`inspector-router.js`,
`before-after-comparison.js`, `hardware-profile-card.js`,
`workspace-feedback.js`, `workspace-preview.js`,
`evaluation-history-panel.js`, `generation-history-panel.js`,
`processing-history-panel.js`, `overlap-review-list.js`) were migrated
to them, each local `.row` rule replaced by a comment pointing at the
shared class. The split into a base class plus a separate
`--center` modifier (rather than one merged class) preserved each
migrated component's exact prior alignment behavior — one cluster
used `align-items: center`, the other didn't, and folding them
together would have silently changed one of them.

Tests: `tests/css-utilities.test.mjs` (4 cases, including a source-text
check that the old `.row {` rule is actually gone from each migrated
file).

## FE-1.6 — Aarya visual identity pass

Small, deliberately non-disruptive refinements — not a redesign:

- `notice-banner.js`'s dismiss control uses a real `<avl-icon
  name="close">` instead of a raw `"✕"` Unicode character (completing
  FE-1.3's principle for the one other place it still applied), with
  the icon staying decorative (`aria-hidden`) since the button's own
  `aria-label="Dismiss notice"` already carries the accessible name.
- `metric-placeholder.js`'s `.value` gained `font-variant-numeric:
  tabular-nums`, so a column of metric values stays digit-aligned.

Tests: `tests/visual-identity.test.mjs` (3 cases).

## FE-1.7 — Visual regression harness

Zero-dependency, matching every other tool in this project: no
image-diff package, exact byte-for-byte PNG comparison instead.
`tests/visual-scenarios.mjs` is the single source of truth for 20
scenarios (all 15 routed workspaces in their default state, plus dark
theme, narrow desktop, a confirmation dialog open, the Inspector with
a real selection, and processing's real BLOCKED status), shared by:

- `tools/visual-baseline.mjs` — CLI: `--update` writes
  `tests/visual-baselines/*.png` (committed to the repo, reviewed like
  any other diff, never silently regenerated); no flag compares the
  current app against them.
- `tests/visual-regression.test.mjs` — the same comparison as a normal
  `node --test` case, so a rendering regression fails the suite like
  any other test.

Determinism, the harness's core design problem, needed two independent
fixes:

1. **Animation** — `page.emulateMedia({ reducedMotion: "reduce" })`
   before navigation activates the app's own existing global
   `prefers-reduced-motion` CSS contract (every `--avl-duration-*`
   token collapses to `1ms`, `animation-iteration-count: 1`), so the
   two infinite CSS animations in the codebase settle into a fixed,
   repeatable end state instead of a wall-clock-dependent frame.
2. **Headless-Chromium rasterization jitter** — a separate problem
   from animation: two consecutive captures of an unchanged scenario
   could still differ byte-for-byte (confirmed: DOM text content
   byte-identical between captures via a diagnostic script, yet PNG
   bytes differed), from sub-pixel anti-aliasing/compositing
   non-determinism in the default rasterizer. Fixed with Chromium
   launch flags forcing a deterministic software rendering path:
   `--force-color-profile=srgb --disable-lcd-text
   --disable-partial-raster --disable-skia-runtime-opts
   --run-all-compositor-stages-before-draw --disable-gpu
   --font-render-hinting=none` (both the CLI tool and the test file
   use the identical flag list).

A third, separate issue surfaced during hardening: the
`20-processing-blocked` scenario triggered `processing-model.js`'s
real async stage chain (PREPARING → PROCESSING → QUALITY_CHECK →
final status, ~450ms) and then used a blind `1200ms` wait before
capturing — a race, not a rendering artifact, that showed up as one
flake in 8 full-harness runs. Fixed by polling for the actual
`avl-status-badge[state="BLOCKED"]` to land (bounded by a 5s deadline)
instead of guessing a fixed delay.

Verified stable across many repeated full 20-scenario comparison runs
after both fixes, including the specific scenario the timing fix
targeted.

Known, honest gap (documented rather than papered over): a genuine
mid-flight "loading" frame and a forced error/exception state are
*not* covered — both would need either a fabricated timing race or
code changes to force a synthetic exception, and either risks exactly
the kind of flaky/fabricated capture this harness exists to avoid.
Calibration's own honest "No calibration run yet" default state
doubles as the empty-state coverage that *is* included.

## FE-1.8 — Accessibility audit

See the "FE-1.8 accessibility audit" subsection under "Accessibility"
in [VLD0_DESIGN_SYSTEM.md](VLD0_DESIGN_SYSTEM.md) for the full
methodology and findings — this is the "later milestone" that
document's own Accessibility section deferred a real audit to. In
short: a programmatic audit ran against a real browser across all 15
routes and 5 dynamic states, checking accessible names, heading
hierarchy, table headers, selectable-row keyboard reachability,
decorative-icon handling, form labels, dialog semantics, and focus
visibility. One real gap was found and fixed — the Inspector panel had
no landmark role and skipped a heading level — everything else the
audit checked passed with zero findings, confirming the VL-D0-era
accessibility contract held up under a real, evidence-based check
rather than only being asserted.

## Testing

```sh
cd frontend && node --test tests/*.test.mjs
```

New test files added in FE-1: `token-application.test.mjs`,
`confirm-action.test.mjs`, `icon.test.mjs`, `responsive-shell.test.mjs`,
`css-utilities.test.mjs`, `visual-identity.test.mjs`,
`visual-regression.test.mjs`. One existing file
(`calibration-profile-history.js`'s Inspector-selection keyboard
handling) gained a new case in the existing `calibration.test.mjs`
rather than a new file, matching the component it extends.

Visual regression baselines (`tests/visual-baselines/*.png`) are
regenerated deliberately, never automatically:

```sh
cd frontend && node tools/visual-baseline.mjs --update            # all scenarios
cd frontend && node tools/visual-baseline.mjs --update NAME       # one scenario
cd frontend && node tools/visual-baseline.mjs                     # compare only, exit 1 on diff
```

Backend regression: the full existing `pytest` suite and `ruff check
.` were re-run unmodified before and after this work; FE-1 touched no
`src/aarya_voice_lab/**` file.

## Scope and non-goals (FE-1)

Explicitly **not** built or changed, per the governing directive for
this phase:

- No migration away from vanilla Web Components/Shadow DOM — no React,
  no other framework, no build step.
- No second design-token system — the one bug fixed (see "Blocking
  prerequisite" above) was in *delivery* of the existing tokens, not a
  new token architecture.
- No backend change of any kind.
- No `frontend/state/**` change beyond what the token-delivery fix and
  the Inspector heading fix genuinely required — no new store, no
  schema change.
- No mobile/stacked layout — FE-1.2's responsive shell is a
  narrow-*desktop* breakpoint only; small-screen/touch layouts remain
  future scope.
- No rewrite of any working D0–D10 interaction model — every existing
  test from prior milestones was re-run and kept passing unmodified
  throughout FE-1 (aside from the one new case added to
  `calibration.test.mjs` above).
- No FE-2 work of any kind was started in this phase.

## Next

FE-2 (not started, not scoped here) would be the next frontend
milestone once explicitly requested.
