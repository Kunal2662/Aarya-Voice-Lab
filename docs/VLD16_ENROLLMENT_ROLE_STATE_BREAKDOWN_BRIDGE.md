# VL-D16 — Enrollment Role/State Breakdown Bridge

AARYA Voice Lab only. Continues the VL-D0–D15 desktop UI series.

## 1. Objective

Render the two remaining real, backend-provided enrollment fields that
were already fetched through `identity.contracts.desktop_snapshot()` on
every load of `workspace-claude.js`, but never displayed:

- `enrollment.by_state`
- `enrollment.by_role`

Frontend bridge only. No backend change, no new fetch, no new export
script, no new contract, no snapshot-shape change.

## 2. Existing Backend Evidence

`identity.contracts.enrollment_status()`
([identity/contracts.py:82-110](src/aarya_voice_lab/identity/contracts.py:82))
computes both fields from real `ProfileStore` data:

```python
for profile_id in store.list_profiles():
    ...
    by_state[latest.enrollment_state.value] = by_state.get(...) + 1
    by_role[latest.role.value] = by_role.get(...) + 1
```

`enrollment_status()` is part of `desktop_snapshot()`
(`"enrollment": enrollment_status(data_root)`), which `workspace-claude.js`
has fetched on every load since VL-D11. VL-D14 already bridged two other
fields of this same function (`available_strategies`,
`available_providers`) but did not audit `by_state`/`by_role` — the VL-D16
audit found both still sitting unused in the already-fetched snapshot
object, confirmed via repository-wide search: neither appeared in any
`.js` rendering code, only as always-empty (`{}`) values in the shared
test fixtures.

## 3. Fields Bridged

- `enrollment.by_state` — count of profiles per `EnrollmentState` value.
- `enrollment.by_role` — count of profiles per `SpeakerRole` value.

Both are rendered **exactly as returned**, iterating whatever keys the
backend actually sent — never a hardcoded list of known
states/roles, so an unfamiliar future key still renders.

## 4. Frontend Implementation

`frontend/components/workspace-claude.js`:

- A new module-level helper, `formatCountBreakdown(value)`, formats a
  count-by-key object as `"key: count, key: count"`, or returns `null`
  for anything that isn't a non-array object, or that has zero entries.
  This is the only new abstraction added, and it exists solely because
  the exact same formatting logic is needed twice (state, then role);
  no new component, workspace, or architecture was introduced.
- Two new rows were added to the existing "Identity & enrollment status"
  panel, directly alongside the VL-D14 strategies/providers rows:
  - `snap.enrollment?.by_state` → `"Profiles by state: enrolled: 2,
    pending: 1."`, or `"Profiles by state: no profiles recorded yet."`
  - `snap.enrollment?.by_role` → `"Profiles by role: user: 2, admin: 1."`,
    or `"Profiles by role: no profiles recorded yet."`

Both rows read directly from the already-fetched `desktop_snapshot()`
payload. Neither value is recomputed, derived from `profiles.count`, or
cross-checked against any other frontend state — backend payload → direct
render, exactly as required.

## 5. Empty-State Behavior

- `{}` (the default in every shared test fixture, and the honest state
  on a fresh checkout with no profiles) renders the explicit "no
  profiles recorded yet" sentence for that field — never a fabricated
  `0` count that wasn't actually in the payload.
- A **missing** `by_state`/`by_role` key (backend payload without the
  field at all) renders the identical honest empty sentence via the
  same `formatCountBreakdown(undefined) → null` path — the row degrades
  gracefully rather than throwing or leaving a blank space, and no
  sibling row in the panel is affected.
- A **malformed** value (a string, a number, an array — anything that
  isn't a plain key→count object) is treated the same as missing:
  `formatCountBreakdown` returns `null` for any non-object or array
  input, so the row renders the honest empty sentence instead of
  crashing or printing `"[object Object]"`/`NaN`-shaped output.
- The pre-existing `if (!snap) { ... }` "not fetched yet" branch is
  entirely unmodified — a missing/malformed top-level snapshot still
  renders exactly as it did before this milestone.

## 6. Test Coverage

`frontend/tests/claude-command-center.test.mjs`, continuing the `#27+`
numbering after VL-D15's `#24-26`:

- `#27` — non-empty `by_state` (`{enrolled: 2, pending: 1}`) renders
  both keys and counts verbatim.
- `#28` — non-empty `by_role` (`{user: 2, admin: 1}`) renders both keys
  and counts verbatim.
- `#29` — a third key (`suspended: 3`) renders alongside the other two,
  proving the implementation iterates the real payload rather than
  hardcoding two known categories.
- `#30` — the shared fixture's default empty `{}` for both fields
  renders both honest "no profiles recorded yet" sentences.
- `#31` — a snapshot with `by_state`/`by_role` deleted entirely (not
  just empty) still renders the honest empty sentences for both, and a
  sibling row (`available_providers`) still renders correctly — proving
  a missing field doesn't break the rest of the panel.
- `#32` — malformed values (`by_state` a string, `by_role` a number)
  render the honest empty sentences with zero console errors (asserted
  by `withPage()`'s own teardown, which fails the test on any
  unexpected console error or thrown exception).

`frontend/tests/identity-status-snapshot.test.mjs` — **not modified**,
per the standing instruction: the fetch layer is untouched by this
milestone.

## 7. Verification Results

Run on this machine (Windows, no Playwright/Chromium, broken `.venv`):

| Check | Result |
|---|---|
| `node --test tests/identity-status-snapshot.test.mjs` | **PASS** — 10/10 |
| `node --test tests/claude-command-center.test.mjs` (new `#27-32`) | **BLOCKED BY ENVIRONMENT** — fail with `Cannot find module '.../playwright/index.js'`, identical to every pre-existing real-browser test in this file (including test `#1`, unmodified by this milestone). This is a module-resolution failure before any test body executes; not a logic defect. |
| Full frontend suite (`node --test tests/*.test.mjs`) | 417 tests total (411 + 6 new), **200 pass** (unchanged from before this milestone), 217 fail (211 prior + exactly the 6 new environment-blocked tests). Zero regression in any previously-passing test. |
| `node tools/build-css-variables.mjs --check` | **PASS** — exit 0 |
| `node --check` on both modified files | **PASS** — syntax valid |
| Backend `pytest` | **BLOCKED BY ENVIRONMENT** — `.venv/bin/python` remains a broken symlink to `/home/dragon/.pyenv/versions/3.13.7/bin/python`, unchanged since VL-D14/VL-D15. No backend code was touched by this milestone. |
| Visual baseline (`13-claude.png`) | **BLOCKED BY ENVIRONMENT** — not regenerated; requires the same missing Playwright/Chromium toolchain. |

No test was skipped, weakened, or deleted to obtain a green result.

## 8. Explicit Exclusions

- `embeddings.embedding_ids` — **not rendered**. Its id format
  (`f"{profile_id}-v{version}"`) can embed a caller-chosen `profile_id`
  string, a distinct privacy question this milestone does not decide.
- `pipeline.stages` — already real and rendered via `workspace-pipeline.js`
  / `pipeline-stage-track.js`; not duplicated here.
- `calibration_status()` — not implemented; it is always fed a static
  `uncalibrated_baseline()`, not a persisted per-machine result, and was
  judged not a meaningful bridge candidate.
- `verification_results_view()`, `review_queue_view()`,
  `provenance_chain()` — not implemented; no real persisted verification
  results exist in this environment for any of them to render honestly.
- Training-readiness UI, `IdentityReviewQueue`, IndicF5
  generation/training, Hindi/Marathi real-corpus validation, Core-side
  `private_voice` enforcement — all untouched, all remain out of scope
  for the same reasons recorded in the VL-D11–D15 audits.
- `workspace-batches.js` — not rewired to real `BatchMetadata`; still
  synthetic-only, unchanged.
- `.venv`, Playwright, Chromium, `.python-version` — not touched.

## 9. Environment Limitations

- Backend `pytest` cannot run on this machine (`.venv` broken symlink to
  a non-Windows path). This milestone made no backend changes, so this
  gap doesn't bear on the correctness of what was implemented, but it
  could not be used to positively re-verify the backend.
- The frontend real-browser (Playwright/Chromium) test layer cannot run
  on this machine — hardcoded to `/opt/node22`/`/opt/pw-browsers`, a
  Linux build-machine path. This is the layer that would actually
  render the new rows in a live DOM; it remains unverified here.
- Visual baseline regeneration is blocked by the same Playwright gap.
- Node's built-in unit-test runner, syntax checking, and the CSS
  token-build check all run natively on this machine and did run.

## 10. Final Milestone Status

**VL-D16 — IMPLEMENTATION COMPLETE / ENVIRONMENT-LIMITED VERIFICATION.**

The feature is implemented per the approved scope, exercised by six new
test scenarios that are logically sound and syntactically verified, and
every check available on this machine passes with zero regression. The
scenarios that would provide live-DOM confirmation (the real-browser
suite) and the visual baseline remain blocked by this machine's missing
Playwright/Chromium toolchain — a pre-existing, machine-specific gap
unrelated to this milestone's code, documented rather than claimed as
passing.
