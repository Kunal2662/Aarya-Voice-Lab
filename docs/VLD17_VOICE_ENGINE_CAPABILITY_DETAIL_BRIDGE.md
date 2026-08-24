# VL-D17 — Voice Engine Capability Detail Bridge

AARYA Voice Lab only. Continues the VL-D0–D16 desktop UI series.

**This milestone does NOT enable TTS generation or training, in any way.**
It only exposes, in the browser, the already-existing, already-truthful
capability explanation the backend has computed since the Real Voice
Model Engine milestone. No provider's capability *state* changes as a
result of this work — a provider that was `NOT_CONFIGURED` before this
milestone is still exactly `NOT_CONFIGURED` after it.

## Evidence for the Scope

Produced by the VL-D17 read-only audit, re-verified before implementing
anything:

- `scripts/export_voice_engine_capabilities.py` has, since the Real
  Voice Model Engine milestone, exported the **whole** capability dict
  for each provider — `embedding_providers[].detail`,
  `training_provider.detail`, and `training_provider.missing_requirements`
  included — to `frontend/contracts/live/voice_engine_capabilities.json`.
- `frontend/components/workspace-models.js`'s existing "Voice Model
  Engine — provider capability" panel already fetches this file on every
  load (`this._engineCapabilities`), but its render loop only ever read
  `.name`, `.is_synthetic`, `.state`, and `.backend_state` — `.detail`
  and `.missing_requirements` sat unused in the already-fetched payload,
  the same "real data fetched, silently dropped" shape VL-D11–D16 found
  and fixed elsewhere in this series.
- `cmd_voice_engine_status`'s own CLI text-mode output already prints
  `missing_requirements` in human-readable form, confirming this project
  already treats it as safe, presentable information — it was simply
  never carried into the browser.
- The `detail` strings themselves were inspected at the source
  (`identity/embeddings.py`'s `capability_state()` implementations):
  generic setup instructions, model-load timing, or `str(exc)` — no
  absolute filesystem path, credential, token, or private identifier was
  found in any of them.

## Exact Fields Rendered

1. `embedding_providers[].detail`
2. `training_provider.detail`
3. `training_provider.missing_requirements`

Nothing else. `generation_provider` gained no new rendering — its
`GenerationCapabilities` dataclass has no `detail`/`missing_requirements`
field to bridge.

## Implementation

`frontend/components/workspace-models.js`:

- Two small module-level helpers, `appendCaptionLine(container, text)`
  and `formatMissingRequirements(value)`, format the two shapes of new
  data (a plain string; a real list of package names). Both return
  early/`null` for anything that isn't the expected type — a malformed
  backend value renders nothing, never a fabricated placeholder.
- Inside the existing embedding-providers loop, `provider.detail` is
  appended as a caption sub-line immediately after that provider's row,
  only when it is a non-empty string.
- After the existing training row, `training_provider.detail` is
  appended the same way, followed by `training_provider.missing_requirements`
  formatted as one sentence ("Missing requirements: nemo_toolkit,
  torch.") — only when the array is non-empty.
- The pre-existing provider name labels, `avl-status-badge` elements
  (`training_provider_state` / `generation_backend_state` domains), and
  the synthetic-provider note are entirely unmodified — this is purely
  additive.
- The pre-existing `if (!capabilities) { ... }` "not fetched yet" branch
  is untouched — a missing or malformed top-level snapshot still renders
  exactly as it did before this milestone (verified: malformed JSON
  already throws inside the existing `try`/`catch` around the
  `voice_engine_capabilities.json` fetch, which was already catching it
  and setting `this._engineCapabilities = null` before this milestone;
  no code change was needed there).

No backend change, no new fetch, no new export script, no new contract.

## Tests

`frontend/tests/voice-engine-status.test.mjs` gained a
`withCapabilitiesFile()` helper (ported verbatim from
`claude-command-center.test.mjs`'s established `withFileAt()` pattern,
applied to `frontend/contracts/live/voice_engine_capabilities.json`) so
specific fixture values could be asserted, since this file previously
only had conditional "whatever's on disk" assertions. Nine new
real-browser scenarios, prefixed `VL-D17:` per this file's own existing
"VL-D12:" convention:

1. A real embedding provider's `detail` renders verbatim.
2. A second provider's `detail` renders independently, and each detail
   string appears exactly once (no cross-contamination between rows).
3. `training_provider.detail` renders verbatim.
4. Three `missing_requirements` entries all render (proving iteration,
   not a hardcoded two-item assumption).
5. An empty `missing_requirements` array produces no "Missing
   requirements:" sentence at all, while the unrelated training `detail`
   sentence still renders.
6. `null`/missing `detail` and a `null` `missing_requirements` value
   render safely — the provider/training rows still render normally, no
   `"null"`/`"undefined"` text appears, zero console errors are asserted
   directly (via `page.on("console"/"pageerror")` capture).
7. With a fully-populated fixture, the pre-existing provider name labels
   and all three `avl-status-badge` domain/state pairs are asserted
   unchanged — a regression check proving this milestone is additive.
8. A missing `voice_engine_capabilities.json` still renders the
   pre-existing "No live capability snapshot fetched yet" state.
9. A malformed-JSON `voice_engine_capabilities.json` still renders the
   same "not fetched yet" state, with zero console errors.

## Verification Results

| Check | Result |
|---|---|
| `node --check` on both modified files | **PASS** |
| `node --test tests/voice-engine-status.test.mjs` (4 pre-existing + 9 new) | **BLOCKED BY ENVIRONMENT** — all 13 fail identically with `Cannot find module '.../playwright/index.js'`, including the 4 pre-existing, unmodified tests. Confirmed a module-resolution failure, not a logic defect in this milestone's code. |
| Full frontend suite (`node --test tests/*.test.mjs`) | 426 tests (417 + 9 new), **200 pass** (unchanged from before this milestone), 226 fail (217 prior + exactly the 9 new environment-blocked tests). **Zero regression.** |
| `node tools/build-css-variables.mjs --check` | **PASS** — exit 0 |
| Backend `pytest` | **BLOCKED BY ENVIRONMENT** — `.venv/bin/python` remains a broken symlink to a non-Windows path, unchanged since D14–D16. No backend code was touched. |
| Visual baseline | **NOT REGENERATED** — same missing Playwright/Chromium toolchain. Left unchanged; no screenshot was fabricated or manually created. |

No test was skipped, weakened, or deleted to obtain a green result.

## Acceptance Criteria

- `embedding_providers[].detail` and `training_provider.detail` render
  verbatim when present, and render nothing when absent/null/malformed.
- `training_provider.missing_requirements` renders every entry when the
  array is non-empty, and produces no sentence at all when it is empty
  — never an invented "no missing requirements" message.
- Existing provider names, `avl-status-badge` domains/states, and the
  synthetic-provider note are unchanged.
- The existing "not fetched yet" behavior for a missing or malformed
  snapshot is unchanged.
- No filesystem path, credential, token, or private identifier is
  rendered — confirmed by direct inspection of every `detail`-producing
  code path in `identity/embeddings.py`.
- No provider's capability *state* is altered by this milestone; no TTS
  generation or training becomes possible as a result of this work.

## Explicit Exclusions

Not touched by this milestone, per the approved scope: IndicF5, Piper,
any TTS generation implementation, training execution, training-readiness
UI, `IdentityReviewQueue`, verification/review/provenance views,
`profiles.profiles`, `embeddings.embedding_ids`, `model_registry`'s
`model_type`/`status` fields, `pipeline.stages`, `workspace-batches.js`,
Core-side `private_voice` enforcement, `.venv`, Playwright
installation/configuration, and `.python-version`.

## Environment Limitations

- `.venv/bin/python` remains a broken symlink to a non-Windows path —
  backend `pytest` could not be run to re-verify this milestone (no
  backend code was changed, so this does not bear on correctness, but it
  could not be used for positive confirmation).
- The frontend real-browser (Playwright/Chromium) test layer remains
  hardcoded to `/opt/node22`/`/opt/pw-browsers`, a Linux build-machine
  path absent on this Windows checkout — the 13 real-browser tests in
  `voice-engine-status.test.mjs`, including all 9 new ones, could not
  actually execute in a live DOM here.
- Visual baseline regeneration is blocked by the same gap; the existing
  baseline was left untouched rather than replaced with a fabricated or
  manually-created image.
- Node's built-in unit-test runner, syntax checking, and the CSS
  token-build check all ran natively on this machine and did run.
