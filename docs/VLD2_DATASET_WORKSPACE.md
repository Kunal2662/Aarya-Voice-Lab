# VL-D2 — Bulk Recording Import & Dataset Workspace

> Status: **real import intake, synthetic data only.**
> `pipeline.import_intake` genuinely hashes, classifies, deduplicates,
> and writes files into `data/source/<batch-id>/` — but only ever files
> VL-D2's own tests hand it. **REAL RECORDINGS ARE NOT USED DURING
> VL-D2.** See "Real recording activation" below for exactly what
> changes, and does not change automatically, once they are.

## Why this is not a second pipeline

Phase 2's `pipeline.inventory` and `core.data_root` already implemented
almost everything a bulk importer needs before VL-D2 started: SHA-256
content hashing, magic-byte detection (`audio.filetype`, never trusting
an extension), zero-byte/corrupt/unsupported detection, duplicate-by-
content detection, and batch metadata that persists as a JSON file
(`create_batch`/`read_batch`/`list_batches`) — restart-safe by
construction, since it's just a file on disk. VL-D2 does not reimplement
any of that (per its own governing spec, §3). What Phase 2 never needed,
because every prior stage assumed `source/` was already populated by a
human out of band, is a controlled way to **write** external files into
`source/` in the first place. That one gap is `pipeline.import_intake`.

## Backend: `pipeline.import_intake`

### The sanctioned exception to source immutability

`core.data_root.assert_source_writable` exists specifically to stop
writes into `source/`. `import_intake.ImportQueue` is the single, narrow
place in the codebase allowed to write there, and it earns that
exception by construction rather than by an override flag:

- the destination filename is always `<sha256><ext>` — **never** the
  caller-supplied filename — so a hostile or accidental name like
  `"../../../etc/passwd"` cannot influence where a byte lands (there is
  no path separator in a hex digest, and the extension comes from the
  *detected* container, not the claimed one);
- the write uses exclusive creation (`"xb"` mode): a destination that
  already exists is never overwritten, only recognised as a duplicate;
- nothing in this module ever renames, edits, or deletes a file once it
  has landed in `source/` — it is exactly as immutable as every other
  source recording from that point on.

`tests/test_import_intake.py::test_path_traversal_style_filename_cannot_influence_destination`
proves this with a maximally hostile display name.

### The import queue

`ImportQueue` models exactly the closed state machine VL-D2 §5 asks for:

```
QUEUED → SCANNING → HASHING → VALIDATING → {ACCEPTED, WARNING, INVALID, BLOCKED, DUPLICATE, FAILED}
QUEUED → CANCELLED   (cancel() — only before processing starts)
{FAILED, INVALID, BLOCKED} → QUEUED → …   (retry() — re-runs _process_one)
```

Every item is processed independently inside a broad
`except Exception` — VL-D2 §5's "one malformed recording must never
crash the entire batch" is a `try`/`except` around each item, not an
aspiration. `tests/test_import_intake.py::test_one_bad_item_does_not_stop_the_rest_of_the_queue`
and `::test_full_synthetic_corpus_classifies_correctly_and_never_crashes`
(which runs the entire deliberately-broken Phase 2 synthetic corpus
through one queue) both verify this directly.

### Duplicate detection, cheap by construction

Because every accepted file is stored as `<sha256><ext>`, finding a
duplicate — within this import, or against *any* prior batch ever
imported — is a filename glob (`find_existing_content`), not a re-hash of
the whole dataset. This is also why the "within-run" and "cross-batch"
duplicate paths collapse into one code path: `ImportQueue` processes
items sequentially, so an accepted item is already on disk (and
therefore already visible to the glob) before its sibling is checked. A
concurrent/parallel processing mode, if ever added, would need to
reintroduce an in-memory pending-hash index for the window before an
item's file exists — noted in the code as the one thing that would need
to change, not built speculatively now.

### Resumability

Re-running an import over files already accepted in a prior batch (or
the same one) is idempotent by content hash — a second `ImportQueue`
constructed against the same `DataRoot` (simulating an application
restart, since it shares no in-memory state with the first) recognises
the content as already present and marks it `DUPLICATE`, never
re-copying it. This is the same "reuse must be earned by hashes/config/
versions matching, never by a timestamp" principle
`pipeline.resume.StageFingerprint` already applies to pipeline stages —
carried into VL-D2 as a principle, not literally the same code, since
import intake precedes the run-directory model that module operates on.
`Batch` identity itself (`batch-NNN`) was already sequential, not
timestamp-based, before VL-D2 (`core.data_root.next_batch_id`).

### The dataset access gate

`ImportQueue.__init__` refuses to construct for a non-synthetic import
unless a `GateReport` from `pipeline.dataset_gate.evaluate_gate()` is
passed in and `.allowed` is `True` — the exact same gate the rest of the
project uses, not a second, parallel one. `is_synthetic=True` is the
default and is all VL-D2's CLI (`aarya-voice import`) ever passes;
there is no `--real`/`--approved` flag on that command at all, by
design — one less footgun than shipping a flag whose only correct value
is "off."

### CLI

```sh
python -m aarya_voice_lab.cli.main import file1.wav file2.wav --batch-id batch-001
python -m aarya_voice_lab.cli.main import /path/to/folder --folder --batch-id batch-001
python -m aarya_voice_lab.cli.main import file1.wav --batch-id batch-001 --json
```

Writes `data/manifests/<batch-id>/import_manifest.json`
(`schemas/import_manifest.schema.json`, `SchemaName.IMPORT_MANIFEST`),
schema-validated before being written.

## Frontend: the client-side import engine

The browser has no execution transport to the backend — the same
constraint VL-D1's Command Center documented (`NullCommandExecutor`),
still true here: no HTTP API server, no desktop-shell IPC bridge. It
cannot write into `data/source/`, cannot see other batches, and cannot
invoke `pipeline.import_intake` directly.

What it *can* do for real, with zero added dependencies:

- read a dropped/selected `File`'s header bytes and classify its
  container by content — `frontend/state/import-engine.js`'s
  `identifyContainer()` is a line-for-line port of `audio/filetype.py`'s
  `_identify()` signature table, verified to agree with the Python
  implementation on the exact byte patterns
  `testing.synthetic_audio`'s fixture generators produce
  (`tests/import-engine.test.mjs`);
- compute a **real** SHA-256 over the file content via
  `crypto.subtle.digest` — proven to match `hashlib.sha256` on the same
  bytes, not merely assumed to;
- detect zero-byte files and within-queue duplicates;
- run the identical closed state machine the backend `ImportQueue` uses,
  with the same per-item failure isolation (one item's
  `file.arrayBuffer()` rejecting doesn't stop the rest of the queue —
  `tests/import-engine.test.mjs`'s failure-isolation test forces this
  with a poisoned `File`).

### What it honestly cannot do

Write an accepted file into `source/`, detect a duplicate against a
batch from a *previous session* (no filesystem access), or create a
persisted `Batch` record. `avl-workspace-import`'s "Copy import plan"
button (`exportImportPlan()`) is the bridge: it produces JSON shaped
closely to `ImportQueue.to_manifest()` — with no `stored_relative_path`
field on any item, because this queue never writes one — for an operator
to hand to the real CLI importer. This is the same "UI validates, CLI
executes" pattern as the Claude Command Center, not a fabricated write.

### A documented gap, not a silent wrong answer

The client-side engine cannot parse WAV frame data (no `wave`-module
equivalent without adding a dependency), so a **corrupt-but-header-valid**
WAV — the exact fixture `testing.synthetic_audio.generate_corrupt_wav()`
produces — is accepted client-side where the backend's
`probe_wav_quietly()` would flag it `INVALID`. `import-engine.test.mjs`
asserts this exact behaviour explicitly (not merely "does not crash") so
the gap stays visible in the test suite rather than silently drifting.
The authoritative validation still happens: the CLI importer (or any
future execution transport) runs the real backend check before anything
is treated as accepted for real.

`crypto.subtle.digest()` is also one-shot over a full in-memory buffer,
not incremental — fine for VL-D2's synthetic fixtures, not yet a
solution for a very large real file without either the File System
Access API (a directory-picker permission grant, not drag/drop) or a
real backend transport to stream-hash. Not implemented in VL-D2; see
Known limitations.

## Dataset Workspace UI

- **Import** (`avl-workspace-import`) — drop zone → `avl-import-queue`
  (real per-row status, bulk select/retry-selected/retry-all-failed/
  cancel, per-row "Ask Claude" on any retryable failure), a live
  progress readout ("Importing X / Y" plus per-status counts, all summed
  from the actual queue — never fabricated), the dataset access gate
  panel (unchanged from VL-D1: reads the gitignored, point-in-time
  `frontend/contracts/live/dataset_gate_status.json` snapshot, or shows
  an honest "not evaluated" state), "Copy import plan", and "Open
  Pipeline" (appears once at least one item is accepted, navigates to
  `#/pipeline` via the shared `Router` instance now exposed on
  `services.router`).
- **Batches** (`avl-workspace-batches`) — gained a Dataset Dashboard
  panel at the top: Total files / Accepted / Warning / Invalid / Blocked
  / Duplicates / Batches / Processing / Candidates / Review items, each
  summed from the synthetic batch/recording fixtures plus the live
  import queue's real counts where one exists — never a placeholder
  number.
- **Recordings** (`avl-workspace-recordings`) — rebuilt as a real
  client-side searchable (filename/ID substring), filterable
  (validation/format/batch, options generated from the actual data, not
  hardcoded), sortable (click any column header, ascending/descending)
  table over the ten VL-D2 §14 columns. Replaces VL-D1's simple
  `avl-recording-row` list component, which is now unused and has been
  removed (see "Superseded from VL-D1" below).
- **Inspector** (`inspector-router.js`'s `recording` view) — gained
  Batch and Pipeline-status rows, plus Speaker identity / Accent
  fidelity / Pronunciation fidelity / Calibration rows that render
  `NOT AVAILABLE` / `NOT ANALYZED` / `NOT CALIBRATED` unconditionally —
  no future-engine field is ever left to guess at a value; VL-D2 has no
  such engines, so these are the only honest values today.
  `dataset-workspace.test.mjs` asserts these exact strings appear and
  that nothing matching a fabricated speaker score does.

### Superseded from VL-D1

`components/recording-row.js` (a single-row synthetic-recording renderer)
is removed. Its only caller, `workspace-recordings.js`, was rebuilt
around a real table for VL-D2 §14's search/filter/sort requirement, and
nothing else referenced it. Deleted rather than left as dead code.

## Activity, Command Center, and Claude integration

- **Activity**: `workspace-import.js` appends one `ActivityEvent` per
  item the *first* time it reaches a terminal status (accepted → success,
  warning → warning, duplicate → info, invalid/blocked/failed →
  danger), sourced as `ActivitySource.IMPORT`. Visible in both the
  Activity workspace and the Command Center's "Recent activity" panel —
  one store, two views, unchanged from VL-D1.
- **Command Center**: gained a fifth panel, "Imports" — Active (queued +
  scanning + hashing + validating) / Accepted / Warnings / Failed
  (failed + invalid + blocked combined), read live from
  `services.importQueue`. An overview only; the Import workspace still
  owns the detailed per-item table, per VL-D2 §22's "Command Center =
  overview, Dataset Workspace = detailed operations."
- **Claude**: a retryable import failure's "Ask Claude" button builds
  its context through the same `buildClaudeContext()` VL-D1's Claude
  workspace uses — bounded to exactly `batch_id`, `item_id`, `stage:
  "import"`, the detected container, status, and the errors/warnings
  this component generated itself, then passed through the shared
  redaction pass regardless. No absolute host path is ever available to
  redact in the first place: a browser `File`'s `.name` is a basename
  only, by platform design — the sandbox already strips the rest.
  `dataset-workspace.test.mjs` clicks this through end-to-end and
  asserts the rendered context is the bounded shape, not a full dump.

## Synthetic fixture strategy

Backend tests reuse `testing.synthetic_audio.generate_phase2_corpus()`
verbatim — it already produces every case VL-D2 §23 asks for (valid,
clipped, narrowband/telephone, zero-byte, corrupt, truncated,
mislabelled, unsupported, and an exact duplicate) — rather than a second,
parallel fixture generator. Frontend tests construct in-memory `File`
objects with byte-for-byte matching signatures (RIFF/WAVE, ID3) so both
suites are provably exercising the same inputs; the large-batch test
(60 synthetic files) proves the queue completes and every item lands in
a terminal state, not just that it doesn't throw.

Nothing under `data/source/`, `source/`, or any real recording is read
or referenced anywhere in VL-D2 — backend or frontend.

## Security boundary

Nothing in VL-D2 weakens an existing invariant:

- **Source immutability** — writes are exclusive-create, content-hash
  named, and the one function permitted to do so is documented and
  tested for path-traversal safety.
- **Dataset access gate** — `ImportQueue` refuses non-synthetic
  construction without a satisfied `GateReport`; the CLI never exposes a
  way to pass one.
- **Speaker identity boundary** — no field for it exists anywhere in the
  recording explorer, the inspector, or the synthetic fixtures; the
  Inspector explicitly labels it `NOT AVAILABLE` rather than omitting the
  row (omitting it would look like an oversight; stating it is honest).
- **Execution boundary** — the client-side engine performs read-only
  browser-local computation (hashing, header inspection) and writes
  nothing to any filesystem; it still routes through the same
  `NullCommandExecutor` honesty as everything else in the Command Center.
- **Path traversal** — proven by construction (hash-named destinations)
  and by a dedicated test using a hostile display name.
- **Secret scanning** — re-verified clean; no new filename collides with
  `security.source_protection`'s sensitive-fragment list (checked
  proactively given VL-D0's `tokens.css` lesson).

## Real recording activation

VL-D2 does not, and cannot by itself, activate real recordings.
Nothing here changes automatically when real recordings become
available:

- `ImportQueue` still refuses a non-synthetic run without a `GateReport`
  whose `explicit_approval` condition is satisfied — and that condition
  can only ever be set by a human attestation passed into
  `evaluate_gate()`, never inferred.
- The CLI (`aarya-voice import`) has no `--real` flag; adding real-import
  support is explicitly out of VL-D2's scope, left for deliberate future
  work once the gate is actually satisfied.
- The client-side engine has no path to real data at all — it only ever
  sees whatever a human drags into the browser tab in that session.

When real recordings are eventually authorized, the same
`pipeline.import_intake.ImportQueue` handles them — construction with
`is_synthetic=False` and a satisfied `GateReport` is already implemented
and tested (`test_non_synthetic_import_with_a_fully_satisfied_gate_report_is_permitted_to_construct`)
— no architectural change is needed, only the human approval this module
was built from day one to never self-grant.

## Testing

```sh
python -m pytest tests/test_import_intake.py -q     # 21 backend tests
cd frontend && node --test tests/*.test.mjs          # 45 frontend tests total
```

New in VL-D2: 21 backend tests (`tests/test_import_intake.py`) and 16
frontend tests (10 in `import-engine.test.mjs`, 6 in
`dataset-workspace.test.mjs`, the latter real headless-Chromium runs).
VL-D0's 10 and VL-D1's 19 re-run unmodified except one assertion in
`app-smoke.test.mjs` updated to match copy that legitimately changed
(the import workspace's honesty boundary moved from "nothing is hashed"
to "nothing is written into `source/`" now that real client-side hashing
exists) — the underlying property the test checks (never claim more than
is true) is unchanged, only the literal string. Full existing Python
suite (493 tests total including VL-D2's) and `ruff check .` remain
green throughout.

## Known limitations

- The client-side engine cannot detect a corrupt-but-header-valid WAV
  (see "A documented gap, not a silent wrong answer" above) — the
  backend's `probe_wav_quietly()` remains the authoritative check.
- Hashing is one-shot, not streaming — fine for VL-D2's fixtures, not
  yet solved for a very large real file client-side.
- Cross-batch duplicate detection only exists on the backend (a
  filesystem glob over already-imported batches); the browser has no way
  to see a prior session's batches at all.
- No true concurrent/parallel item processing — `ImportQueue.process_all()`
  is sequential on both sides. Documented in the code as the one thing
  a future concurrent mode would need to add (a pending-hash index), not
  built speculatively now.
- The Dataset Dashboard's "Processing" and "Candidates" figures are
  currently sourced only from the synthetic batch fixtures (no live batch
  is created from a browser import, since nothing writes to `source/`
  from there) — real once VL-D3's pipeline-execution UI exists.

## Next

**VL-D3 — Dataset Review + Voice Quality Analysis Workspace**.
