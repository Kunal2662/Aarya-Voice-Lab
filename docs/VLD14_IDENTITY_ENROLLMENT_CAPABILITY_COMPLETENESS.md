# VL-D14 — Identity & Enrollment Capability Completeness Bridge

AARYA Voice Lab only. Continues the VL-D0–D13 desktop UI series.

## Scope

Strictly limited to rendering two fields `identity.contracts.desktop_snapshot()`
already delivers to the frontend on every load, and that the frontend has
never displayed:

1. `enrollment.available_strategies`
2. `enrollment.available_providers`

No backend change, no new CLI subcommand, no new export script, no new
contract, no new fetch. `pipeline.stages` and `pipeline.batches` — a
closely related, equally already-fetched, equally unrendered pair found
during the same audit — are explicitly **not** part of this milestone;
they are reserved for VL-D15.

## Evidence

Produced by the read-only audit that preceded this milestone, re-verified
directly against the repository before implementing anything:

- `identity.contracts.enrollment_status()` has returned
  `available_strategies` (`identity.enrollment.describe_strategies()`,
  each entry a real strategy descriptor — `name`, `version`,
  `requires_human_approval`, `permitted_roles`, `minimum_samples`,
  `minimum_total_seconds`) and `available_providers`
  (`identity.embeddings.available_providers()`, sorted real provider
  names) since Phase 3, both tested
  (`tests/test_phase3_identity.py:161,271`,
  `tests/test_voice_model_engine.py:74`).
- `enrollment_status()` is part of `desktop_snapshot()`
  (`identity/contracts.py`'s `desktop_snapshot()` returns
  `"enrollment": enrollment_status(data_root)`), which `workspace-claude.js`
  has fetched on every load since VL-D11.
- Confirmed directly in `workspace-claude.js` before this milestone: the
  Identity & enrollment status panel read `snap.enrollment.real_provider_installed`
  and `snap.enrollment.note`, but never `snap.enrollment.available_strategies`
  or `snap.enrollment.available_providers` — both sat unused in the
  already-fetched snapshot object. This is the same "real data fetched
  every load, silently dropped before render" shape VL-D13 fixed for
  `runtime`/`embeddings`/`preview`; these two fields are the parts of the
  same `desktop_snapshot()` payload VL-D13 left behind.
- Confirmed both fields are non-sensitive: strategy descriptors and
  provider names are software capability metadata, not speaker/profile
  data — neither `docs/SECURITY.md` nor `docs/PRIVACY.md` scopes either
  as protected, so no new security review was required (unlike, say, a
  full profile-list bridge would need).
- `pipeline.stages`/`pipeline.batches` were found in the same audit pass
  (`identity.contracts.pipeline_status()` returns `stages` and
  `batches`, both fetched, neither rendered — only `implemented_count`
  is), but are a distinct payload (`snap.pipeline`, not `snap.enrollment`)
  and were deliberately excluded from this milestone's scope per the
  standing instruction, to keep this diff as small as D10–D13 established.
  Left untouched — reserved for VL-D15.

## Implementation

Mirrors D13's exact shape: no new fetch, no new export script, no new
contract.

`frontend/components/workspace-claude.js`'s existing "Identity &
enrollment status" panel gained two rows, inserted between the existing
`real_provider_installed` sentence and the D13 runtime-components
sentence:

- `snap.enrollment.available_strategies` renders as
  `"Enrollment strategies available: <name>, <name>, ...."`, naming every
  declared strategy by name — or `"No enrollment strategies declared."`
  for an empty array. Never a fabricated default catalogue.
- `snap.enrollment.available_providers` renders as
  `"Embedding providers available: <name>, <name>."`, or
  `"No embedding providers declared."` for an empty array.

Both rows use the same `avl-row avl-row--center` / `avl-type-body-small`
primitives every other row in this panel already uses — no new
component, no new workspace, no redesign. The existing null-snapshot
branch (`if (!snap) { ... }`) is entirely unmodified: a missing/malformed
snapshot still renders the pre-existing "No live identity status
snapshot fetched yet" state, and neither new row is reached in that case.

## Tests

- `frontend/tests/claude-command-center.test.mjs` (real-browser,
  Playwright/headless Chromium): three new scenarios, continuing the
  `#18-20` numbering VL-D13 used —
  - `#21` — a snapshot with three real, distinctly-named strategies
    renders the exact `"Enrollment strategies available: synthetic,
    direct_recording, human_anchored."` sentence.
  - `#22` — the shared fixture's two real providers render as
    `"Embedding providers available: local-neural-embedding,
    synthetic-cosine-projection."` (asserted as the exact sentence, not a
    bare substring match, because `runtime.components` in the shared
    fixture legitimately contains the same provider-name strings for an
    unrelated reason — D13's runtime bridge — so a substring check alone
    would not prove this milestone's row actually rendered).
  - `#23` — both fields empty renders both honest "none declared"
    sentences, and explicitly asserts the non-empty sentence prefixes
    (`"Enrollment strategies available:"` / `"Embedding providers
    available:"`) are absent, so a regression that always renders the
    non-empty branch would be caught.
  - Requirement "a missing/null snapshot still renders the existing 'not
    fetched yet' state" is covered by the pre-existing, unmodified test
    `#14` — this milestone's change does not touch that code path, so no
    new test was added for it (existing coverage already proves it).
- `frontend/tests/identity-status-snapshot.test.mjs` (Node unit, no
  browser): unmodified. It tests `fetchIdentityStatusSnapshot()`'s
  fetch/parse/validation behavior, which this milestone does not touch —
  confirmed still passing (see report).

## Acceptance criteria

- A valid snapshot with real, non-empty `available_strategies`/
  `available_providers` renders both lists by name, verbatim.
- An empty array for either field renders an explicit, honest "none
  declared" sentence for that field — never a blank row, never a
  fabricated default.
- A missing, malformed, or wrong-contract snapshot continues to render
  the pre-existing "not fetched yet" panel state, unchanged.
- No existing test in `identity-status-snapshot.test.mjs` or elsewhere in
  the frontend suite is weakened or made to assert less than before.
- `pipeline.stages` and `pipeline.batches` remain completely untouched —
  not read, not rendered, not mentioned in any new code path.

## What VL-D14 does NOT implement

- `pipeline.stages` / `pipeline.batches` — real, found, explicitly
  reserved for VL-D15 per the standing instruction, not folded in here
  even though they are the same shape of gap.
- No change to `pipeline/training.py`, `pipeline/training_readiness.py`,
  or `identity/review.py` — both were investigated and disqualified by
  VL-D12's and VL-D13's own audits (no real data exists in this
  environment for either to display) and remain untouched.
- No change to the Real ML Runtime milestone's PENDING items (IndicF5
  credential decision, generation, training, Piper substitution) — not
  touched.
- No Core-side `private_voice` authorization or enforcement logic.
- No backend code, CLI, export script, or contract changes of any kind —
  this milestone is a pure frontend render of data the backend already
  produces and already ships to the browser.

## Known limitations

- This machine's local toolchain could not fully verify this change:
  `.venv` is a broken symlink to a non-Windows path and the frontend's
  real-browser test layer requires a Playwright/Chromium install
  hardcoded to a Linux path (`/opt/node22`, `/opt/pw-browsers`) that
  does not exist here. Both are pre-existing environment gaps, unrelated
  to this milestone's code — see the accompanying report for exactly
  what could and could not be executed.
- The visual baseline (`13-claude.png`) was **not** regenerated as part
  of this commit, because doing so requires the same missing Playwright/
  Chromium toolchain. The panel's new rows will cause the next real
  visual-regression run (`tools/visual-baseline.mjs --update 13-claude`,
  on a machine with the toolchain) to show an expected, deliberate diff —
  this must be captured before the visual-regression suite is treated as
  green on this branch.
