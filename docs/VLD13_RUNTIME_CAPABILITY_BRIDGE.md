# VL-D13 — Runtime Capability Bridge

AARYA Voice Lab only. Continues the VL-D0–D12 desktop UI series.

## Audit

Re-verified rather than assumed from VL-D12's own report, per this
session's standing instruction to establish D13 scope from repository
evidence:

- `identity/review.py`'s `IdentityReviewQueue` was read in full: a real,
  tested module with zero CLI/frontend exposure. Ruled out as this
  milestone's scope — this environment has no real recordings and no
  real verification results anywhere, so any bridge built for it today
  would only ever render an empty panel. A weaker candidate than the one
  below, which renders real, already-fetched data today.
- `docs/SECURITY.md`/`docs/PRIVACY.md` were checked for other explicit
  gaps beyond what D11/D12 already closed — none found beyond the
  already-known, out-of-scope Core-side-enforcement item.
- **The actual VL-D13 finding**: `identity.contracts.runtime_capabilities()`
  hardcoded exactly two static `RuntimeCapability` entries
  (`SYNTHETIC_PROVIDER_CAPABILITY`, `VERIFICATION_ENGINE_CAPABILITY`) and
  never asked the real, installed `LocalNeuralEmbeddingProvider` for its
  own declaration — despite `identity/runtime.py`'s own module docstring
  stating capabilities are *"Declared by embedding providers,
  verification engines, and (later) voice models, so placement and
  packaging decisions can be made from data instead of assumptions."*
  This is the direct sibling of D11's `real_provider_installed` bug: a
  real capability that exists on this machine, silently absent from a
  contract whose entire purpose is to report it.
- Cross-referenced against `desktop_snapshot()`'s dependency chain: D11
  already fetches the full snapshot (`runtime`, `embeddings`, `preview`
  included), but `workspace-claude.js`'s Identity panel only ever
  rendered `profiles`, `pipeline`, `audit`, and
  `enrollment.real_provider_installed` — `runtime`, `embeddings`, and
  `preview` were fetched every load and never displayed.
- Confirmed via direct inspection that
  `tests/test_phase3_gaps.py::test_shipped_components_are_cpu_only` and
  `test_portability_claim_is_not_overstated` would not break by adding a
  correctly-declared, honestly-CPU-only new component to the list.

## What VL-D13 implements

### Fix: the real embedding provider's capability is declared when installed

`identity.runtime.LOCAL_NEURAL_EMBEDDING_CAPABILITY` (new) declares only
honestly-known facts about `LocalNeuralEmbeddingProvider`: `CPU_ONLY`
acceleration (only ever verified on CPU — see the measured latency table
in `docs/REAL_ML_RUNTIME_INTEGRATION.md`), `PORTABLE_UNVERIFIED`
portability (it depends on a built `.envs/env-nemo` subprocess-isolated
environment, unlike the zero-dependency-portable synthetic provider), and
`min_ram_gb`/`min_vram_gb` left `None` — never measured, so never
claimed. Its `performance_notes` cite the real, already-documented cold/
warm model-load latencies rather than fabricating new numbers.

`identity.contracts.runtime_capabilities()` now appends this capability
**only when** `identity.embeddings.any_real_provider_available()` is
`True` — never unconditionally, which would overstate what a machine
without `.envs/env-nemo` built can actually do, and never omitted when a
real provider genuinely is installed and loaded. The two existing static
capabilities remain unconditionally present, unchanged.

### Bridge: `runtime`/`embeddings`/`preview` reach the panel

No new fetch, no new export script, no new contract wiring was needed —
D11 already delivers all three sub-payloads to the frontend on every
load. `workspace-claude.js`'s existing "Identity & enrollment status"
panel gained:

- Two more stat tiles: real embedding count (`embeddings.count`) and
  the count of declared runtime components (`runtime.components.length`).
- A sentence naming every declared runtime component
  (`runtime.components.map(c => c.component)`), so the real embedding
  provider's presence or absence is visible by name, not just as a
  number.
- `embeddings.note` rendered verbatim — the existing backend contract's
  own honesty statement ("Embeddings are biometric identifiers and have
  no export path"), never re-derived or paraphrased.
- A preview-loop sentence keyed on `preview.generation_implemented`,
  which is always `False` today (voice generation is not implemented in
  this project) — rendered honestly rather than omitted, so the panel
  never implies generation exists by staying silent about it.

All of this lives inside the same panel D11 already built, using the
same primitives (`avl-stat-tile`, `avl-row`) — no new workspace, no new
panel, no redesign.

## Testing

- Backend: 2 new tests in `tests/test_phase3_gaps.py`, mirroring the D11
  `real_provider_installed` capability-gated pattern —
  `test_runtime_capabilities_excludes_real_provider_when_none_is_installed`
  (monkeypatches `_ENV_NEMO_PYTHON` to a nonexistent path, asserts the
  component list is exactly the two static entries) and
  `test_runtime_capabilities_includes_real_provider_honestly` (asserts
  the real provider's component is present if and only if
  `any_real_provider_available()` says so, and that when present it
  still satisfies `runs_on_cpu`/not `requires_accelerator`, so it cannot
  regress `test_shipped_components_are_cpu_only`). Verified live against
  this machine, which has `.envs/env-nemo` built: the exported
  `identity_status_snapshot.json` now genuinely contains a third
  `local-neural-embedding` runtime component.
- Frontend: 3 new real-browser tests in `claude-command-center.test.mjs`
  (#18-20) — all three declared component names render, a snapshot with
  no real provider declared does not fabricate the
  `local-neural-embedding` component, and the embedding-inventory/
  preview-loop honesty sentences render without a fabricated
  generated-speech claim. The shared `realIdentitySnapshotFixture()` was
  extended with realistic `embeddings`/`runtime`/`preview` shapes
  (matching the real backend contracts) rather than the previous
  near-empty stubs, so tests #14-17 continue to exercise the same
  fixture honestly.
- Full regression: 783/783 backend (781 prior + 2 new), ruff clean,
  `validate-environment` passed. Frontend: 22/22 in
  `claude-command-center.test.mjs`, full suite unaffected beyond this
  file and the visual baseline below. Visual regression: `13-claude.png`
  updated for the panel's new rows (`tools/visual-baseline.mjs --update
  13-claude`); the only other visual-regression mismatch is the same
  pre-existing, already-self-documented `20-processing-blocked` timing
  flake `frontend/tests/visual-scenarios.mjs`'s own comment already
  discloses — unrelated to this change, confirmed via the same
  independent method as every prior milestone in this series.

## What VL-D13 does not implement

- No new fetch, export script, or contract — `desktop_snapshot()` already
  delivered `runtime`/`embeddings`/`preview` since D11; this milestone
  only stopped discarding them after fetch and fixed the one real
  omission in what they contained.
- No change to the Real ML Runtime milestone's PENDING items (IndicF5
  credential decision, generation, training, Piper substitution) —
  untouched. `preview.generation_implemented` is rendered exactly as
  `False` and is not made to imply otherwise.
- No Core-side authorization or capability-gating logic — this remains a
  read-only capability *declaration* surface, same boundary as every
  prior D-series milestone; `describe_portability()`'s own note ("not
  from an executed CPU-only run") is unchanged and still applies to the
  new component.
