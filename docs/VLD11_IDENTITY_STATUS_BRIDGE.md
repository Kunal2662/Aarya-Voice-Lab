# VL-D11 — Identity Status Bridge

AARYA Voice Lab only. Continues the VL-D0–D10 desktop UI series, resumed
per the audit VL-D10's own doc called for: *"D11 audit — not yet
scoped; to be produced separately, evidence-based against the actual
D0–D10 implementation."*

## Audit

Before implementing anything, the actual repository state was verified
(`git status`, `git log`) and cross-checked against every prior
milestone's own "Next"/"not yet"/"deferred" notes rather than assumed.
Findings:

- No VL-D11 scope exists anywhere in the docs — confirmed via grep
  across every `docs/VLD*.md` file.
- One real, close match to the VL-D10 precedent's exact shape ("a real,
  tested, CLI-exposed backend read the frontend never fetches") was
  found: `identity.contracts.desktop_snapshot()` — *"one call returning
  everything the desktop needs on load,"* per its own docstring, tested
  since Phase 3 (`tests/test_phase3_e2e.py::test_contracts_are_json_
  serialisable`), CLI-exposed (`aarya-voice identity-status --json`),
  and even named in the Claude Command Center's own catalogue
  (`identity/command_center.py`'s `COMMAND_CATALOGUE`) — but never once
  fetched by the frontend. This is the direct sibling of
  `command_center_snapshot()`, which VL-D10 already bridged.
- `registry/model_registry.py`'s real `titanet_large` entry (added by
  the Real ML Runtime milestone) not being read by `workspace-models.js`
  (still 100% `syntheticModels()`) and `pipeline/training.py`'s job
  log/readiness assessment having no CLI or frontend surface at all were
  both found and are real, but are larger (the training gap needs a new
  CLI subcommand first) or need a CLI addition for parity — left as
  future VL-D12+ candidates, not invented into this milestone's scope.
- **A real, active defect was found while reading `desktop_snapshot()`'s
  dependency chain**: `enrollment_status()` (`identity/contracts.py`)
  and `diagnostics()` (`identity/command_center.py`) both hardcoded
  `"real_provider_installed": False` unconditionally — a hardcoded lie
  since the Real ML Runtime milestone made a real embedding provider
  genuinely installable. `diagnostics()`'s copy of this bug was already
  live inside the committed `command_center_snapshot.json` pattern from
  VL-D10, meaning the Claude Command Center has been capable of
  rendering false hardware-capability data on any machine with
  `.envs/env-nemo` built. Fixed as Class A (directly relevant, real,
  active) per this project's defect policy — see below.

## What VL-D11 implements

### Fix: `real_provider_installed` is now computed, never hardcoded

`identity.embeddings.any_real_provider_available()` (new) checks every
registered provider's real, current `capability_state()` — never
inferred from a provider class merely being registered, since
`LocalNeuralEmbeddingProvider` is always registered whether or not
`.envs/env-nemo` was ever built. Both `enrollment_status()` and
`diagnostics()` now call it instead of hardcoding `False`, and
`enrollment_status()`'s `note` field is dynamic to match. On a machine
with `.envs/env-nemo` built, this makes the check genuinely take the
same ~8-9s the embedding provider's own capability probe costs
elsewhere in the project (`voice-engine-status`, `export_voice_engine_
capabilities.py`) — accepted as consistent with that established,
documented, on-demand-diagnostic-command tradeoff, not a regression to
any latency-sensitive path (neither function is called outside explicit
CLI/export-script invocations).

### Bridge: `desktop_snapshot()` reaches the frontend

Mirrors VL-D10's architecture exactly:

```
identity/contracts.py:desktop_snapshot()
        ↓
scripts/export_identity_status_snapshot.py
        ↓
frontend/contracts/live/identity_status_snapshot.json   (gitignored)
        ↓
state/identity-status-snapshot.js:fetchIdentityStatusSnapshot()
        ↓
workspace-claude.js  (new "Identity & enrollment status" panel)
```

The new panel lives in the existing Claude Command Center workspace
(`workspace-claude.js`), as a sibling section to the existing Command
Center snapshot panel — not a new workspace, not a redesign, built
entirely from existing primitives (`avl-panel`, `avl-stat-tile`). It
shows real profile/usable-profile/pipeline-stage/audit-entry counts and
an honest sentence about whether a real embedding provider is installed
— never a fabricated count, and a missing/malformed snapshot renders
"No live identity status snapshot fetched yet," the same honest-absence
pattern every other live snapshot in this project uses.

## Why not `workspace-voices.js`

The audit considered rendering this in the Voices workspace instead
(speaker profiles are semantically closer to "voices" than to "Claude
Code"), but `workspace-voices.js`'s own header comment explicitly scopes
it to the future voice-*production* lifecycle (Generate → Preview →
... → Accept) and states *"synthetic placeholders only"* throughout.
Mixing in real identity/enrollment/embedding-provider data there would
contradict that workspace's own stated scope. The Claude Command Center
is already the established home for "live system status" panels
(VL-D10's repository/activity/diagnostics), making it the correct,
lowest-risk fit.

## Testing

- Backend: 3 new tests (`tests/test_phase3_e2e.py` x2,
  `tests/test_phase3_gaps.py` x1) replacing two bare
  `assert ... is False` assertions that the real fix correctly no
  longer satisfies universally — one pair reproducibly simulates the
  not-installed case (monkeypatching `_ENV_NEMO_PYTHON` to a nonexistent
  path, mirroring the Real ML Runtime milestone's established pattern),
  the other asserts the field always matches
  `any_real_provider_available()`'s real, current answer.
- Frontend: 10 new unit tests (`identity-status-snapshot.test.mjs`,
  mirroring `command-center-snapshot.test.mjs`'s structure exactly) +
  4 new real-browser tests (`claude-command-center.test.mjs` #14-17):
  honest not-fetched state, real counts rendering, and both
  `real_provider_installed` true/false states rendering honestly.
  `app-smoke.test.mjs` and `claude-command-center.test.mjs`'s existing
  live-snapshot 404 allowlists were extended for the new fetch.
- Full regression: 780/780 backend, ruff clean. Frontend: 389/390 (the
  one failure is the same pre-existing, already-self-documented timing
  flake in `20-processing-blocked` this project's own visual-scenarios.mjs
  comment already discloses — unrelated to this milestone, confirmed via
  the same independent method as the prior milestone).
- Visual baseline `13-claude.png` updated for the new, deliberate panel
  — same "captures this machine's live-snapshot state" caveat already
  disclosed for `10-models.png` in `docs/REAL_ML_RUNTIME_INTEGRATION.md`.

## What VL-D11 does not implement

- Model registry / real artifact display in `workspace-models.js` (still
  `syntheticModels()`) — real, found, deferred as a close-but-larger
  VL-D12 candidate (needs a new CLI subcommand for parity with the
  established pattern). **Update:** implemented — see
  `docs/VLD12_MODEL_REGISTRY_BRIDGE.md`.
- Any training-job/readiness UI surface — real, found, deferred (needs a
  CLI subcommand before an export script can exist at all).
- IndicF5 generation, training, or any change to the Real ML Runtime
  milestone's explicitly PENDING items — untouched, still pending the
  same external HuggingFace-credential decision.
