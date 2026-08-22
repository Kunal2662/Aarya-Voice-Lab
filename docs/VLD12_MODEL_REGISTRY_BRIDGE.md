# VL-D12 — Model Registry Bridge

AARYA Voice Lab only. Continues the VL-D0–D11 desktop UI series.

## Audit

Re-verified rather than assumed from VL-D11's own report:

- `frontend/components/workspace-models.js` was still 100%
  `syntheticModels()` — confirmed live in the file.
- `models/registry.jsonl` still held the real `titanet_large` entry
  (added by the Real ML Runtime milestone), unreachable by any CLI
  command or frontend fetch — confirmed no `models`/`registry`
  subcommand existed anywhere in `cli/main.py`/`cli/phase3.py` (only the
  unrelated `experiment` registry has one).
- The alternative VL-D11 candidate — a training-job/readiness UI —
  was checked directly and ruled out: `pipeline/training_readiness.py`'s
  `assess_training_readiness()` needs real measured audio-quality input
  to produce anything, and `TrainingJobLog` has zero real entries.
  Exposing it now would mean either fabricating a readiness read or
  building real scaffolding around training, which is explicitly
  **PENDING** per this session's standing instruction. Disqualified on
  both size and boundary grounds.
- **Security check before scoping further**: `docs/SECURITY.md` requires
  that a `private_voice` model entry have *"no frontend-only
  authorization"* — the frontend may hide it, but hiding must never be
  the only thing standing between a user and the model. This project has
  no Core-side authorization layer yet, so any bridge built here had to
  exclude `private_voice` entries **at the source**, not just in the UI.

## What VL-D12 implements

Mirrors VL-D10/D11's architecture exactly:

```
registry/model_registry.py:ModelRegistry.list_non_private_models()
        ↓
cli/phase3.py:cmd_model_registry ("model-registry" subcommand)
        ↓
scripts/export_model_registry_snapshot.py
        ↓
frontend/contracts/live/model_registry_snapshot.json   (gitignored)
        ↓
state/model-registry-snapshot.js:fetchModelRegistrySnapshot()
        ↓
workspace-models.js  (new "Model registry" panel)
```

### Security: `private_voice` exclusion at the source

`ModelRegistry.list_non_private_models()` (new) is the **only** method
this milestone's CLI command, export script, and frontend fetch ever
call — never `.list()`, never `list_private_voice_models()`. The
guarantee lives once, at the registry method, rather than being trusted
to every future caller. A dedicated backend test
(`test_list_non_private_models_never_includes_a_private_voice_entry`)
adds a real `private_voice` entry alongside `other`/`default_voice`
entries and asserts it is excluded — not just that the method runs.

### CLI

`aarya-voice model-registry [--json]` — the new subcommand, following
the exact `cmd_*`/`add_parser` pattern already used by `identity-status`/
`command-center`/`voice-engine-status`.

### Frontend panel

A new "Model registry (real, checksum-addressed entries)" panel in the
existing Models workspace, built entirely from existing primitives
(`avl-panel`, `avl-status-badge`) — no new workspace, no redesign. Each
real entry renders name/version/provider and a `model_lifecycle`-domain
badge (a token domain the Real ML Runtime milestone already added,
anticipating exactly this wiring — using it instead of the
mismatched `hardware` domain `avl-model-card`'s synthetic-fixture path
uses avoided passing a `status` value like `"approved"` into a badge
whose vocabulary is `AVAILABLE/NOT_AVAILABLE/OPTIONAL/INCOMPATIBLE/
UNKNOWN`). A `null` `lifecycle_state` (the schema's own "created before
this milestone" case) renders an honest "no lifecycle state recorded"
sentence instead of being defaulted into a fabricated badge value.
Missing/empty snapshots render honest, distinct sentences — never a
blank panel and never a synthetic model dressed up as real.

## Testing

- Backend: 1 new registry test (the private-exclusion test above). CLI
  command verified manually (`model-registry`, `model-registry --json`)
  against the real, live registry.
- Frontend: 10 new unit tests (`model-registry-snapshot.test.mjs`,
  mirroring the D10/D11 fetcher test files exactly) + 2 new real-browser
  tests (`voice-engine-status.test.mjs`): an honest not-fetched/empty/
  real-entries panel, a real entry's lifecycle badge always being a
  valid `model_lifecycle` value, and — the security property this
  milestone exists to protect — the panel text never containing
  `private_voice` under any live-snapshot outcome. The pre-existing
  badge-domain test was extended to allow `model_lifecycle` alongside
  the two domains it already asserted. `app-smoke.test.mjs`'s live-
  snapshot 404 allowlist was extended for the new fetch.
- Full regression: 781/781 backend, ruff clean. Frontend: 401/402 (the
  one failure is the same pre-existing, already-self-documented timing
  flake in `20-processing-blocked` disclosed in prior milestones —
  unrelated to this change).
- Visual baseline `10-models.png` updated for the new panel — same
  "captures this machine's live-snapshot state" caveat already disclosed
  for `10-models.png`/`13-claude.png` in the Real ML Runtime and VL-D11
  milestone docs.

## What VL-D12 does not implement

- No training-job/readiness UI surface — real, found, still deferred
  (needs a new CLI subcommand before an export script can exist, and
  sits adjacent to the explicitly PENDING training item).
- No change to the Real ML Runtime milestone's PENDING items (IndicF5
  credential decision, generation, training, Piper substitution) —
  untouched.
- No Core-side authorization layer was built. This milestone's
  `private_voice` exclusion is a **hiding** measure at the one read path
  that currently exists, exactly as `docs/SECURITY.md` describes as
  acceptable *in addition to*, never *instead of*, real server-side
  enforcement once Core exists. If a `private_voice` entry is ever added
  to this registry, this bridge still must never be the only thing
  standing between a user and it.
