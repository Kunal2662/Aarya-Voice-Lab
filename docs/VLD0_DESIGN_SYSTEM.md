# VL-D0 — Unified UI/UX Design System

> Status: **foundation only.** Tokens, primitives, contracts, and one
> layout wireframe exist. There is no application behind them — no real
> voice cloning, no bulk importer, no pipeline execution, no Claude
> integration, no installer. See "Scope and non-goals" below.

## Product identity

**Aarya Voice Lab** is an independent product with its own branding. It
is not a subsystem of anything else, and it is not called "JARVIS Voice
Lab" anywhere in this codebase. Claude Code is an integrated
development/engineering capability *inside* the application (the Command
Center, §Claude Code UI foundation below) — it is not the product's
identity. An earlier internal doc (`PHASE3_CHECKPOINT.md`) briefly used
"JARVIS × Voice Lab UI" language before this correction; that line has
been fixed as part of VL-D0.

## Why no framework

No frontend code existed anywhere in this repository before VL-D0 — this
audit confirmed it (`git grep`/`find` across the whole tree, before any
file was touched). Nothing needed to be reused, and nothing dictated a
choice. Given that:

- the project's hard invariant is local-first / no cloud dependency, at
  every layer, not just the backend;
- the eventual desktop shell (Tauri, Electron, pywebview, or something
  else) hasn't been chosen and VL-D0 must not force that choice; and
- VL-D0's job is a *design system foundation*, not an application,

the foundation is built as **zero-dependency vanilla Web Components**
(Shadow DOM, native Custom Elements) plus **JSON design tokens** as the
single source of truth. This can be dropped into whatever shell gets
picked later without a rewrite. Tooling is `node` only — no `npm
install`, no bundler, no registry fetch — tested with Node's built-in
`node:test` plus one real-browser smoke test using the Chromium already
installed in this environment (via Playwright, also already installed
globally — no dependency was added to make this possible).

## Layout

See `frontend/README.md` for the directory layout and commands.

## Design tokens

Source of truth: `frontend/tokens/*.json`. Built to CSS custom properties
by `frontend/tools/build-css-variables.mjs` → `frontend/css/variables.css` (a
generated file, verified non-stale by `tests/css-variables.test.mjs`). No
component may reference a raw color, size, or duration — only a token.

- **Color** (`color.json`): semantic names in five groups — `surface`,
  `border`, `text`, `brand`, `state` (success/warning/danger/info) — plus
  a `voice` group specific to this product's domain
  (recording/playback/calibration/review-required/synthetic) and a small
  `pixel-accent` group for the decorative pixel-art system. Every name
  exists once per theme (light, dark); `tests/css-variables.test.mjs` asserts
  the two themes define exactly the same key set, so a theme can never
  silently fall back to an undefined variable.
- **Typography** (`typography.json`): a `readable` family (system UI
  stack) for all real content, a `monospace` family for code/logs, and a
  `pixel-decorative` family for a small, explicit allow-list of
  decorative uses only (see "Pixel-art system" below). No font files are
  bundled in VL-D0 — the contract (scale, weights, line-heights, and the
  decorative-use rule) exists before any specific font asset is chosen.
  All sizes are `rem`, so they scale with the user's OS/browser text
  preference.
- **Spacing** (`spacing.json`): a 4px-based scale, plus radius tokens and
  the shell's layout constants (sidebar width, inspector width, activity
  bar height).
- **Motion** (`motion.json`): a short list of durations and easing
  curves. See "Motion system" below.
- **Status** (`status.json`): the cross-domain status vocabulary. See
  next section.

## Status vocabulary

One JSON file (`frontend/tokens/status.json`) defines every legal status
value across five domains, each rendered through the single
`<avl-status-badge domain state>` component so no two parts of the app
can invent different labels or colors for the same concept:

| Domain | States | Source of truth |
|---|---|---|
| `core` | idle / busy / ready / attention / error / offline | UI-level, no backend equivalent yet |
| `pipeline_stage` | not_started / queued / running / success / warning / failed / blocked / paused / cancelled | UI-only lifecycle layered on top of `pipeline/stages.py`'s `PipelineStage` (stage *identity*) — this is stage *execution status*, a different axis, not a duplicate |
| `voice` | idle / recording / playback / processing / review-required / accepted / rejected | UI-level, keyed to VL-V0 preview feedback outcomes |
| `calibration` | UNCALIBRATED / PROVISIONAL / CALIBRATED | **Mirrors `identity/calibration.py`'s `CalibrationState` exactly** |
| `hardware` | AVAILABLE / NOT_AVAILABLE / OPTIONAL / INCOMPATIBLE / UNKNOWN | **Mirrors `core/capability.py`'s `CapabilityState` exactly** |

The two domains with a real backend enum (`calibration`, `hardware`) are
checked against a **generated export** of that Python enum
(`frontend/contracts/generated/calibration_state.json` and
`capability_state.json`, produced by
`scripts/export_frontend_contracts.py`), and `tests/css-variables.test.mjs`
asserts the two lists are identical. If a backend enum value is ever
added, renamed, or removed without re-running the exporter, this test —
and `tests/contracts-drift.test.mjs`, which reruns the exporter with
`--check` — fail.

Every badge shows a color **and** a text label; color is never the only
signal (see Accessibility below). An unrecognised state renders visibly
as unrecognised (e.g. "Foo (not a recognised voice state)") rather than
silently falling back to a default look — a wrong or stale caller should
be obvious, not invisible.

### Backend runtime status vs. the `pipeline_stage` UI vocabulary

`pipeline/contracts.py` already has a `StageStatus` (a plain string
namespace, not an enum) with six values: `pending / running / completed
/ failed / skipped / blocked`. VL-D0's spec asks for a richer nine-state
UI lifecycle (adding `not_started`, `queued`, `warning`, `paused`,
`cancelled`). Rather than force the backend to grow states it doesn't
need yet, `pipeline_stage` in `status.json` is documented as UI-only
vocabulary; a future integration maps backend `StageStatus` values onto
it (`pending`→`not_started`, `running`→`running`, `completed`→`success`,
`failed`→`failed`, `blocked`→`blocked`, `skipped`→`cancelled`) rather
than the UI inventing progress that hasn't happened. No component
fabricates a runtime state — `avl-pipeline-stage-track` defaults every
stage to `not_started` unless it is explicitly told otherwise.

## Backend contract export

`scripts/export_frontend_contracts.py` (repo root, since it imports the
Python package) is the **only** place that reads a backend enum and
writes its frozen JSON shape to `frontend/contracts/generated/`:
`calibration_state.json`, `capability_state.json`,
`compute_backend.json`, `command_risk.json`, `preview_kind.json`,
`preview_feedback_outcome.json`, `pipeline_stage.json`. Run it after any
backend enum change:

```sh
python scripts/export_frontend_contracts.py          # regenerate
python scripts/export_frontend_contracts.py --check  # verify only (used in CI/tests)
```

One correctness note from building this: `SPEAKER_IDENTITY_STAGES` is a
`frozenset`, and Python's string hash randomization makes frozenset
iteration order vary run-to-run. The exporter re-orders it by canonical
pipeline position before serializing — otherwise the generated file would
"drift" on every regeneration even with no real change. Verified stable
across repeated fresh interpreter runs.

## Application shell

`<avl-app-shell>` lays out four regions via CSS grid: `sidebar` (nav,
fixed width), `workspace` (main content, flexible), `inspector`
(right-hand contextual panel, collapsible), and `activity-bar` (bottom
strip, fixed height). The shell owns layout only — no navigation state,
no data fetching, no routing. `frontend/shell/index.html` demonstrates it
wired up with real (if placeholder-heavy) content; only a handful of
sidebar destinations are wired live, the rest render `disabled` with a
visible "planned" tag rather than being omitted, so the shape of the
eventual navigation is visible without pretending those screens exist.

## Component library

31 custom elements across every category the spec asked for. None
hardcodes a product-specific color — all styling reads token custom
properties through the shared stylesheet every component links into its
Shadow DOM (`base-element.js`'s `_linkSharedStyles()`).

- **Shell**: `avl-app-shell`, `avl-sidebar-nav` (+ `avl-sidebar-item`),
  `avl-activity-bar`, `avl-panel` (used as the inspector region and
  generally).
- **Core primitives**: `avl-button`, `avl-card`, `avl-tabs` (+
  `avl-tab`, full arrow-key/Home/End keyboard navigation per the
  WAI-ARIA tabs pattern), `avl-notice-banner`, `avl-status-badge`,
  `avl-theme-toggle`, `avl-metric-placeholder`.
- **Audio (UI only, no engine)**: `avl-waveform-container` (renders
  supplied peaks or an honest "no waveform data" placeholder — never
  fake audio),  `avl-playback-controls` (dispatches
  `avl-play`/`avl-pause`/`avl-seek`; owns no `<audio>` element).
- **Voice Preview** (VL-V0, tied to `identity/preview.py`):
  `avl-voice-player`, `avl-voice-preview-card`, `avl-voice-status`,
  `avl-voice-feedback` (emits a `PreviewFeedback`-shaped event, writes
  nothing itself), `avl-voice-version`, `avl-voice-comparison`.
- **Pipeline**: `avl-pipeline-stage-track`, `avl-pipeline-stage-node`.
- **Pixel-art**: `avl-pixel-sprite`.
- **Claude Code Command Center** (tied to `identity/command_center.py`):
  `avl-claude-command-shell`, `avl-claude-output-log`,
  `avl-claude-task-status`.
- **Calibration / Hardware / Accent**: `avl-calibration-panel` (tied to
  `identity/calibration.py`), `avl-hardware-profile-card` (tied to
  `core/capability.py`), `avl-accent-panel` (concepts only, no engine exists).
- **Error/recovery**: `avl-error-panel` (progressive disclosure — plain
  summary always visible, technical detail behind `<details>`, an
  optional "Ask Claude" action that dispatches an event rather than
  calling anything itself).

Complex data (a `PreviewArtifact`, a list of `Capability` objects, a
`command_center_snapshot()` payload) is passed via a JS **property**
(`element.artifact = {...}`), never serialized into an HTML attribute —
attributes stay string-only for simple flags/enums, matching how the
platform itself distinguishes the two.

## Pixel-art system

Strictly decorative and environmental. `avl-pixel-sprite` always sets
`aria-hidden="true"` on itself (verified by the browser smoke test) and
never carries information that isn't *also* stated in real text/color
elsewhere — accessibility must never depend on noticing a pixel motif.
Motifs are deterministic 8×8 bit grids defined in the component itself
(`idle-orb`, `calibration-glyph`, `waveform-motif`); no image assets ship
in VL-D0. `typography.json` separately declares a `pixel-decorative` font
family with an explicit allow-list (section glyphs, empty-state art, app
icon, loading motif) and forbid-list (body text, labels, status text,
error messages, anything longer than one short word, anything that is
the *sole* carrier of information).

## Motion system

Durations and easings are tokens (`motion.json`); every component that
animates reads `var(--avl-duration-*)`. `frontend/css/variables.css`
collapses every duration token to `1ms` under
`@media (prefers-reduced-motion: reduce)`, and `base.css` adds a
belt-and-suspenders global override on `animation-duration` /
`transition-duration` for the same media query. No component's *only*
indicator of a state change is motion — motion always accompanies a
text/icon/color change, and looping motion is restricted to explicitly
decorative elements (pixel motifs, spinners), never status text.

## Claude Code UI foundation

`avl-claude-command-shell` is a visual shell only: repository context
line, `avl-claude-output-log` (renders
`identity/command_center.py`'s `activity_feed()` entries verbatim — it
already sanitises vectors/paths, so nothing further is redacted here),
`avl-claude-task-status` (shows a `CommandDescriptor`'s risk tier and, if
gated, its reason — never hidden, matching the backend module's own
design note that a hidden gated command "invites the user to look for a
way around it"), and a command-input row. Submitting dispatches
`avl-command-submit` with the typed text; **nothing here executes
anything** — `identity/command_center.py` itself notes it "executes
nothing... the desktop invokes the ordinary CLI so every run passes the
same gates and audit log," and this UI layer keeps that property.

The **Claude context model** (`frontend/contracts/claude-context-model.json`)
is an interface only — the shape a future "what does Claude currently
know" provider must fill (active view, selection, recent commands,
permission tier) so later work has a stable target. Nothing implements
it in VL-D0.

## AI Calibration UI foundation (VL-D7)

`avl-calibration-panel` renders through the `calibration` status domain,
which is checked byte-for-byte against `CalibrationState`. Given no
record, it shows the honest default — `UNCALIBRATED`, "No evidence.
Thresholds are defaults chosen for safety, not measurement." — the exact
language from `identity/calibration.py`'s own docstring. It is
structurally incapable of showing a number it wasn't given:
`avl-metric-placeholder` renders "Not available" rather than `0`, `—`,
or any other value that could be mistaken for a measurement when no
`value` attribute is set.

## Hardware UI foundation

`avl-hardware-profile-card` renders a list of generic capability rows —
name, state (through the `hardware` domain / `CapabilityState`), and
detail string — exactly as `core/capability.py`'s `Capability` objects
report them. No vendor name, product name, or specific device (RTX 3050
or otherwise) is hardcoded anywhere in this component or its tokens;
whatever the backend names is shown verbatim, consistent with
`identity/runtime.py`'s already-vendor-neutral `ComputeBackend` model.

## Accent/Pronunciation UI foundation

`avl-accent-panel` — concepts only. No pronunciation/accent engine
exists; the panel shows three placeholder metrics (accent region,
deviation score, phoneme confidence), all rendering "Not available," and
a stated note that no engine exists yet.

## Local-first UX

No component in this system makes a network call except to `fetch()` its
own same-origin static assets (tokens, generated contract JSON). There is
no cloud-storage UI of any kind — no "upload," "sync," "connect account,"
or remote-destination affordance anywhere in the component set.
`avl-theme-toggle` persists its one piece of state (light/dark/system
preference) to `localStorage` only.

## Accessibility

- Every interactive element is keyboard-operable: `avl-tabs` implements
  the full WAI-ARIA tabs keyboard pattern (arrows/Home/End move focus and
  selection); buttons and inputs are native `<button>`/`<input>`
  elements, never non-semantic clickable `<div>`s.
- `:focus-visible` gets a token-colored 2px outline everywhere
  (`css/base.css`); it is never removed.
- Status is never color-only (see Status vocabulary): every
  `avl-status-badge` carries a text label alongside its color dot.
- `.avl-sr-only` (screen-reader-only text) and `_announce()` (a
  polite `aria-live` region on `AvlElement`) are available to every
  component for state changes that aren't otherwise visible as text.
- Text sizing uses `rem` throughout (`typography.json`), so it scales
  with the user's OS/browser preference; nothing is fixed in `px`.
- Reduced motion is honoured globally (see Motion system).
- Pixel-art is `aria-hidden` and never the sole carrier of information
  (see Pixel-art system).

This is a foundation-level accessibility *contract*, not a full audit —
no screen-reader software or contrast-analyzer tooling was run in VL-D0;
that belongs to a later milestone once there's a full application to
audit against.

## Error/recovery UX

`avl-error-panel` implements progressive disclosure: a plain-language
`summary` is always visible; `detail` (a stack trace, a raw error
message) sits behind a native `<details>`/`<summary>` disclosure, closed
by default; an optional `claude-action` attribute adds an "Ask Claude"
button that dispatches `avl-ask-claude` with the error context — it does
not call the Command Center itself, keeping the same "dispatch an event,
let the host wire it up" pattern every other component uses.

## Theme decision

**Investigated, not assumed.** The system supports both light and dark
themes, with **light as the CSS default** (`:root`) and dark applying
either automatically via `prefers-color-scheme: dark` or explicitly via
`<html data-theme="dark">`, with an explicit user choice
(`avl-theme-toggle`) always winning over the OS preference once set.

Reasoning: this is a tool for close, sometimes emotionally difficult
listening work (reviewing a deceased person's recordings), potentially
used across long sessions in varied environments — a fixed dark-only
aesthetic would optimize for a "developer tool at night" assumption this
product doesn't actually make, and would leave no accessible option for
users who need higher ambient brightness or have light-sensitivity in the
other direction. Both palettes were built to the same structural token
set (`tests/css-variables.test.mjs` enforces that light and dark define
identical key names), so neither is a second-class citizen implemented
only partially.

## Scope and non-goals (VL-D0)

Explicitly **not** built, per the governing spec: real voice cloning,
training, or recordings; real embeddings; a full bulk importer; pipeline
*execution* UI (only visualization of backend-reported status);
functioning Claude integration (the shell dispatches events; nothing
executes); a functioning Calibration Engine (only the honest-placeholder
UI); a final installer/runtime; any cloud storage. `frontend/shell/index.html`
is a wireframe exercising the component set with clearly-labeled example
data, not the application.

## Testing

```sh
cd frontend && node --test tests/*.test.mjs
```

- `tests/css-variables.test.mjs` — `css/variables.css` is not stale relative to
  `tokens/*.json`; light/dark themes define identical key sets; the
  `calibration`/`hardware` status domains exactly match the generated
  backend enum exports; every status-domain state has a color mapping.
- `tests/contracts-drift.test.mjs` — re-runs
  `scripts/export_frontend_contracts.py --check` so a backend enum change
  without a re-export fails here rather than drifting silently.
- `tests/status-vocabulary.test.mjs` — pure-logic unit tests for label
  formatting and CSS-variable-name derivation, including the failure path
  when `fetch` is unavailable.
- `tests/browser-smoke.test.mjs` — serves `frontend/` over a real (loop-
  back-only) HTTP server and loads `shell/index.html` in the Chromium
  already installed in this environment via Playwright. Asserts every
  referenced custom element actually upgraded, the pipeline track
  rendered real stage data from the generated backend export, the
  calibration panel shows the honest `UNCALIBRATED` default rather than
  a fabricated score, every pixel sprite is `aria-hidden`, and there are
  zero browser console errors.

Backend regression: the full existing `pytest` suite (472 tests) and
`ruff check .` were re-run unmodified before and after this work; VL-D0
touched no `src/aarya_voice_lab/**` file except adding the
non-invasive, additive `scripts/export_frontend_contracts.py`.

## Known limitations

- CSS variable files are named `variables.css`/`build-css-variables.mjs`,
  not `tokens.css`/`build-tokens.mjs`, even though "design token" is the
  file's actual subject: `security/source_protection.py`'s filename scan
  (correctly, defensively) treats any filename containing `token` as a
  possible credential/secret and fails
  `tests/test_source_protection.py::test_repository_has_no_protected_material_tracked`.
  This was caught by re-running the full existing suite after adding
  these files (2 failures) and fixed by renaming rather than by touching
  the security scanner, which stays exactly as strict as before VL-D0.
  The `frontend/tokens/` *directory* name is unaffected — it isn't in
  the scanner's suspicious-directory list — so only the three individual
  filenames needed changing.
- No font files are bundled; `pixel-decorative` and `monospace` families
  fall back to system fonts until a real asset is chosen.
- No visual regression testing (screenshot diffing) exists yet — the
  browser smoke test checks structure/behavior, not pixel appearance.
- No screen-reader software was used to verify the accessibility
  contract above; it is implemented to spec but not manually audited.
- `avl-tabs` and `avl-sidebar-nav` are the only components with full
  custom keyboard-navigation logic; other composite components (cards,
  panels) rely on native element semantics, which is sufficient for
  VL-D0's scope but should be re-checked once real interactive content
  fills them.
- The nine-state `pipeline_stage` UI vocabulary is not yet wired to any
  real stage-execution status — see "Backend runtime status vs. the
  `pipeline_stage` UI vocabulary" above.

## Next

**VL-D1 — Aarya Voice Lab Command Center**: wire `avl-claude-command-shell`
to a real (local, CLI-invoking) execution path behind
`identity/command_center.py`'s existing gates and audit log; give the
sidebar's placeholder destinations real workspace screens; begin the
bulk-import/dataset-review workspace (still without touching the real 31
recordings, per the standing dataset-access-gate rule).
