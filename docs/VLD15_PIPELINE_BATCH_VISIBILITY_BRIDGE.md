# VL-D15 — Pipeline Batch Visibility Bridge

AARYA Voice Lab only. Continues the VL-D0–D14 desktop UI series.

## Scope

Strictly limited to rendering one field `identity.contracts.desktop_snapshot()`
already delivers to the frontend on every load, and that the frontend has
never displayed: `pipeline.batches` — the real, on-disk batch-id list from
`core.data_root.list_batches()`.

No backend change, no new CLI subcommand, no new export script, no new
contract, no new fetch. `pipeline.stages` — named alongside `batches` as
a candidate by VL-D14's own audit — is **explicitly excluded** from this
milestone; see below.

## Audit finding that reshaped this milestone's scope

VL-D14 treated `pipeline.stages` and `pipeline.batches` as one bundled
sibling gap ("the same shape of gap... reserved for VL-D15"). The
dedicated VL-D15 audit that preceded this implementation checked that
assumption against the repository rather than carrying it forward
unverified, and found it was only half right:

- **`pipeline.batches`** (`core.data_root.list_batches()`, real, dynamic,
  on-disk `batch-NNN` directory names) has **zero** frontend consumer
  anywhere in the repository. Genuine gap.
- **`pipeline.stages`** (`identity.contracts.pipeline_status()`'s
  per-stage `index`/`name`/`phase`/`implemented`/`past_identity_boundary`
  table) is **already implemented and already rendered**, via a separate,
  real, live, routed path that predates this bridge series:
  `frontend/components/workspace-pipeline.js` (VL-D1 §12) fetches the
  static, git-tracked `frontend/contracts/generated/pipeline_stage.json`
  (exported from the same `aarya_voice_lab.pipeline.stages` module) and
  renders it through `avl-pipeline-stage-track` /
  `avl-pipeline-stage-node`. `pipeline-stage-track.js`'s own header
  comment documents that it is designed to consume exactly
  `pipeline_status()["stages"]`'s shape — the two paths already agree by
  construction, since both derive from the same static Python constants
  (`PipelineStage`, `PHASE_2_STAGES`, `SPEAKER_IDENTITY_BOUNDARY`).
  Bridging `desktop_snapshot().pipeline.stages` into the Identity panel
  as well would not close a gap — it would create a second, redundant
  rendering of data VL-D1 already made real and live.

**Therefore: `pipeline.batches` was the only genuine missing field.**
VL-D15 implements only that.

## Implementation

Mirrors D13/D14's exact shape: no new fetch, no new export script, no
new contract, no backend change.

`frontend/components/workspace-claude.js`'s existing "Identity &
enrollment status" panel gained one new row, appended after the existing
D13 preview-loop row:

- `snap.pipeline.batches` renders as `"Batches on disk: batch-001,
  batch-002."`, naming every real batch id verbatim — or `"No batches
  recorded yet."` for an empty array (the honest state on a fresh
  checkout, where `data/manifests/` does not yet exist). Never a
  fabricated batch id, never a status or count beyond the bare id.

The row uses the same `avl-row avl-row--center` / `avl-type-body-small`
primitives every other row in this panel already uses — no new
component, no new workspace, no redesign. The existing null-snapshot
branch is entirely unmodified.

### Explicitly out of scope

- **`pipeline.stages`** — not rendered here; already covered by
  `workspace-pipeline.js` (see audit finding above). No code was added
  for it in this milestone.
- **`BatchMetadata` / `status` / `source_file_count`** — `core.data_root`
  already has a richer real batch record (`create_batch()`/`read_batch()`
  /`BatchMetadata`), but `pipeline_status()` only ever calls the bare
  `list_batches()`, and this milestone renders exactly what
  `desktop_snapshot()` already ships — nothing enriched, nothing new
  fetched from the backend.
- **The existing "Batches" workspace** (`avl-workspace-batches`) is
  **unchanged**. It still renders `syntheticBatches()`/
  `syntheticRecordings()` fixtures exclusively, exactly as it has since
  VL-D1/VL-D2, and this milestone does not touch
  `frontend/components/workspace-batches.js`, `batch-card.js`, or
  `state/synthetic-fixtures.js`. The new Identity-panel row is a
  deliberately separate, smaller surface for the same underlying
  `list_batches()` reality — not a replacement for, and not wired to,
  that workspace.
- No change to `pipeline/training.py`, `pipeline/training_readiness.py`,
  `identity/review.py`, IndicF5, Piper substitution, real-corpus
  validation, or Core-side `private_voice` enforcement.

## Tests

`frontend/tests/claude-command-center.test.mjs` (real-browser, Playwright/
headless Chromium): three new scenarios, continuing the `#21-23`
numbering VL-D14 used —

- `#24` — a snapshot with `pipeline.batches = ["batch-001", "batch-002"]`
  renders the exact `"Batches on disk: batch-001, batch-002."` sentence.
- `#25` — the shared fixture's default empty `pipeline.batches: []`
  renders `"No batches recorded yet."`, and explicitly asserts the
  non-empty sentence prefix (`"Batches on disk:"`) is absent.
- `#26` — with real batch ids present, asserts the Identity panel never
  renders `"synthetic-batch"` — the id prefix `avl-workspace-batches`'s
  unrelated `syntheticBatches()` fixture uses — proving this new row
  cannot be confused with, or accidentally leak, that separate
  workspace's fabricated data.

`frontend/tests/identity-status-snapshot.test.mjs` — **not modified**,
per the standing instruction: the fetch layer (`fetchIdentityStatusSnapshot()`)
is untouched by this milestone, so its existing, contract-agnostic tests
already cover it without change.

## Acceptance criteria

- A valid snapshot with a real, non-empty `pipeline.batches` renders
  every batch id by name, verbatim, in order.
- An empty `pipeline.batches` renders an explicit, honest "no batches
  recorded yet" sentence — never a blank row, never a fabricated id.
- A missing, malformed, or wrong-contract snapshot continues to render
  the pre-existing "not fetched yet" panel state, unchanged.
- The new row never renders content sourced from
  `state/synthetic-fixtures.js`'s `syntheticBatches()`.
- No existing test anywhere in the frontend suite is weakened or made to
  assert less than before.
- `pipeline.stages`, `workspace-pipeline.js`, `pipeline-stage-track.js`,
  and `workspace-batches.js` remain completely untouched.

## Known limitations

- Same local-toolchain gaps as VL-D14: this machine's `.venv` is a broken
  symlink to a non-Windows path, and the frontend's real-browser test
  layer requires a Playwright/Chromium install hardcoded to a Linux path
  (`/opt/node22`, `/opt/pw-browsers`) absent here. Neither gap is related
  to this milestone's code — see the accompanying report for exactly
  what could and could not be executed on this machine.
- The visual baseline (`13-claude.png`) was **not** regenerated as part
  of this commit, for the same reason. The panel's new row will produce
  an expected, deliberate diff on the next real visual-regression run
  performed on a machine with the toolchain.
- `pipeline.batches` is empty on any fresh checkout (`data/manifests/`
  does not exist until a real batch is created) — the new row will
  render "No batches recorded yet." in that state, which is correct and
  not a bug.
