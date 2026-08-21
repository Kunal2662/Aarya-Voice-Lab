# VL-D9 — Local Session Persistence

AARYA Voice Lab only. Not a JARVIS milestone; nothing in this phase touches
Aarya Core or any other project.

## Purpose

Every prior phase's own "Known limitations" section said the same thing:
all frontend state is session-only. Reload the browser and the Import
queue, review decisions, processing queue/history, preview queue/
history/feedback, evaluations/A-B decisions, and calibration profile
history were all gone — because there is still no execution transport
(`state/command-executor.js`, unchanged since VL-D1) to persist anything
to the backend.

VL-D9 does not add one. It closes the session-only gap the *other* way:
a local-only, browser-local persistence layer that saves and restores
exactly the state each store already represents, using the browser's own
`localStorage` — the same mechanism `theme-toggle.js` has used since
VL-D0 for a single UI preference, extended here to a versioned envelope
per store.

## Architecture

Local-only, browser-local, additive, deterministic, bounded, explicit,
non-cloud, non-executing:

* **Local-only** — there is no network call anywhere in
  `state/session-persistence.js`, no account, no server.
* **Additive** — no store's public API changed shape; each store gained
  a `hydrate()` method (and, for the calibration store, the
  `exportCalibrationPlan()` it was missing) without touching any existing
  method.
* **Deterministic** — saving the same state twice produces the same
  restored shape; hydration never re-derives or re-validates a value,
  it restores what was already computed.
* **Bounded** — exactly six namespaced keys exist, one per store group;
  nothing else in `localStorage` is ever read, written, or cleared.
* **Explicit** — the only way to remove saved state is the "Clear
  session data" control in Settings; nothing clears automatically.
* **Non-executing** — persistence never invokes
  `NullCommandExecutor`/any execution transport; restoring history is
  never a re-run of `run()`/`apply_adjustment()`/`validate_calibration()`
  or their frontend mirrors.

## Storage model

`state/session-persistence.js`'s `SessionPersistence` class wraps
`localStorage` behind one namespaced key per store group:

| Namespace | Key | Backed by |
|---|---|---|
| `import` | `avl-session-v1:import` | `state/import-engine.js`'s `ImportQueue` |
| `review` | `avl-session-v1:review` | `state/review-model.js`'s `CandidateReviewStore` + `FeedbackStore` |
| `processing` | `avl-session-v1:processing` | `state/processing-model.js`'s `ProcessingQueueStore` + `ProcessingHistoryStore` |
| `generation` | `avl-session-v1:generation` | `state/generation-model.js`'s `GenerationQueueStore` + `PreviewHistoryStore` + `PreviewFeedbackStore` |
| `evaluation` | `avl-session-v1:evaluation` | `state/evaluation-model.js`'s `EvaluationStore` + `ABEvaluationStore` |
| `calibration` | `avl-session-v1:calibration` | `state/calibration-engine-model.js`'s `CalibrationProfileStore` |

Each key holds one versioned envelope:

```json
{
  "schema_version": 1,
  "namespace": "review",
  "saved_at": "2026-08-21T00:00:00.000Z",
  "payload": { "...": "one of the pre-existing export*Plan() shapes" }
}
```

`payload` is always exactly what the store's own `exportImportPlan()` /
`exportReviewPlan()` / `exportProcessingPlan()` / `exportGenerationPlan()`
/ `exportEvaluationPlan()` / `exportCalibrationPlan()` already produces —
the same "UI validates, CLI executes" bridge shape every store has
carried since VL-D2/VL-D6/VL-D9, reused rather than re-invented as a
second serialization format. `session-persistence.js` never inspects or
rewrites a payload; every field-level "is this safe to persist" decision
is made once, in each store's own `hydrate()` method, next to the fields
it already knows the shape of.

## Persisted state

Before writing `session-persistence.js`, every existing `export*Plan()`
result was inspected field by field. None of the five pre-existing
export shapes (import/review/processing/generation/evaluation) ever
contained raw audio, an embedding, a secret, a credential, an
authentication token, an arbitrary filesystem path, a speaker-identity
field, or dataset source contents — they are all client-side
metadata/decision/measurement records already, by construction (the
browser never had access to any of those things to begin with). What
each store persists:

* **Import** — `batch_id`, `source`, and per-item `item_id`,
  `original_filename`, `declared_extension`, `size_bytes`,
  `detected_container`, `sha256`, `content_id`, `status`, `warnings`,
  `errors`, `duplicate_of`, `counts`.
* **Review** — review decisions (`segmentId`, `decision`, `reasonCode`,
  `reviewer`, `notes`, `supersedes`, `createdAt`) and feedback records
  (`feedbackType`, `targetId`, `reviewer`, `comment`, `attributes`).
* **Processing** — processing queue items and processing history
  records (recording id, profile id, status, decision, derived-artifact
  metadata, quality measurements — never the derived audio itself,
  which the browser never had).
* **Generation** — generation queue items (including the operator-typed
  preview `text`), preview history, and preview feedback.
* **Evaluation** — evaluation records (dimension scores, listening
  state, reviewer, comment) and A/B decisions.
* **Calibration** — the full append-only `CalibrationProfile` history:
  `run_state`, `calibration_state`, `application_state` (VL-D9
  preserves all three independent axes exactly), `hardware_snapshot`,
  `adjustments`, `agreement_rate`, `applied_*`/`validation` fields.

## Excluded state

Some state is deliberately **not** persisted, or not restored even
though it appears in a payload:

* **Import: `File` objects.** A browser `File` cannot survive JSON
  serialization or a page reload — this is a genuine platform
  constraint, not a policy choice. `ImportQueue.hydrate()` restores the
  validation summary (filename, size, hash, container, status) as
  read-only history; a restored item has no backing file, and `retry()`
  now explicitly refuses to act on one rather than throwing.
* **Import/Processing/Generation: non-terminal (in-flight) queue
  items.** `QUEUED`/`SCANNING`/`HASHING`/`VALIDATING` (import),
  `QUEUED`/`PREPARING`/`PROCESSING`/`QUALITY_CHECK` (processing), and
  `QUEUED`/`PREPARING`/`GENERATING`/`POST_PROCESSING` (generation) items
  all reflect an async `setTimeout`/`await`-driven process that no
  longer exists after a reload. Restoring one would freeze a spinner on
  screen forever and imply work is still happening when it isn't. Only
  terminal-status items are restored; this is tested explicitly (see
  Testing below).
* **Processing profiles, voice profiles, generation models.** These
  were never part of `exportProcessingPlan()`/`exportGenerationPlan()`
  to begin with (only the queue + history/feedback are), so VL-D9
  changes nothing about their scope — they stay session-only, same as
  every prior phase.
* **`GenerationQueueStore.maxConcurrentGenerations`.** A runtime queue
  setting, not part of the persisted export shape; left untouched by
  both save and "Clear session data".
* **Evaluation: a `COMPLETED` record without `listening.listened`, or an
  A/B decision requiring both sides without both `listened_a`/
  `listened_b`.** `hydrate()` re-checks the same invariant
  `record()`/`UnlistenedEvaluationError` enforce at write time — not a
  second validation pass on legitimately-written history (which always
  passes), but a defence against a hand-edited or corrupted
  `localStorage` value being restored as if it were valid.
* **`original_filename` is intentionally *not* excluded.** It looks
  path-like but the browser File API never exposes a full local
  filesystem path — only the basename — so it does not fall under the
  banned "arbitrary filesystem paths" category, and it is safe and
  useful to keep.

## Versioning

Every envelope carries `schema_version: 1` (`SESSION_SCHEMA_VERSION`).
`SessionPersistence.load()` refuses (returns `null` for) any envelope
whose `schema_version` doesn't match exactly, or whose `namespace`
doesn't match the instance reading it — never guesses at an unfamiliar
shape. `SessionPersistence.migrate()` exists as the hook a future schema
bump would use; VL-D9 is the first schema version this app has ever
written, so there is nothing to migrate from yet, and `migrate()` is
correctly a no-op today.

## Hydration

Startup sequence, enforced by `app/main.js`'s ordering:

1. The app initializes every store (fresh, in-memory, default state —
   identical to every prior phase).
2. The persistence layer initializes (`SessionPersistence` instances,
   one per namespace) and checks `isPersistenceAvailable()`.
3. Each namespace's saved envelope loads (if any) and, if valid, its
   store(s) `hydrate()` from it — still before any UI element exists and
   before any `"change"` listener is attached.
4. The shell mounts and `mountWorkspace()` renders whatever state is now
   in the stores — restored or default.
5. Only after all of that does `main()` attach the normal state-change
   listeners: the pre-existing Activity-event listeners, and VL-D9's own
   automatic-save listeners.

Because hydration happens before any listener is attached, and because
`hydrate()` itself never dispatches a `"change"` event, restoring a
session can never itself fire an Activity event, trigger an immediate
redundant save, or loop back into another hydration pass.

## Automatic save

Once persistence is available, each store's `"change"` event is wired to
re-export and save that domain's payload (e.g. `reviewStore`'s and
`feedbackStore`'s `"change"` events both save
`exportReviewPlan(reviewStore, feedbackStore)` under the `review`
namespace). `SessionPersistence.save()` never throws — a quota-exceeded
or otherwise-failed write returns `false` and is silently absorbed,
never breaking the state change that triggered it. If persistence is
unavailable at startup, no auto-save listeners are attached at all; the
app behaves exactly as every pre-VL-D9 phase did, purely in-memory.

## Clear-session behavior

Settings → Storage → **Clear session data** is the only way saved state
is ever removed, and it requires two distinct clicks: the first reveals
exactly what will be cleared and a **Confirm clear** button (with a
**Cancel** escape hatch); only the second click calls
`clearAllSessionData()` (which removes exactly the six namespaced keys
above, and nothing else in `localStorage`) and resets every store's
in-memory state in place. Each store's `reset()` keeps the same object
identity (so existing listeners/service references stay valid) and
dispatches one detail-less `"change"` event so mounted UI updates
immediately. Exactly one Activity event, `session_data_cleared`, is
produced. There is no automatic destructive cleanup anywhere — clearing
only ever happens from this explicit, two-step user action.

## Failure behavior

* **`localStorage` unavailable** (private browsing, storage disabled by
  policy) — `isPersistenceAvailable()` performs a real probe write/
  remove, not just a presence check, so it correctly detects a storage
  object that exists but throws on use. When unavailable: no hydration
  is attempted, no auto-save listeners are attached, the Settings/
  Command Center panels show an honest `offline` badge, and one
  `persistence_unavailable` Activity event is recorded. The app remains
  fully usable — this was also the trigger for fixing a pre-existing gap
  in `theme-toggle.js`, which called `localStorage` directly without a
  try/catch; it now degrades the same way.
* **Malformed / corrupted stored JSON** — `load()` returns `null`
  rather than throwing or guessing; the store starts from its normal
  default state, same as if nothing had ever been saved.
* **Quota exceeded mid-session** — `save()` returns `false`; the state
  change that triggered it is unaffected, the UI keeps working, the
  local save silently falls behind (it will succeed again once space is
  available, e.g. after a "Clear session data").

## Privacy / security boundary

* No real recordings accessed. No raw audio persisted — none of the six
  stores ever held real audio bytes to begin with (see Persisted state
  above).
* No embeddings, no speaker-identity field, anywhere in any persisted
  payload — verified by the same field-by-field inspection this document
  describes, and by `docs/PHASE3_IDENTITY.md`'s standing security
  boundary, unchanged.
* No secret, credential, or authentication token — this app has never
  had one to persist.
* No arbitrary filesystem path — `original_filename` is a browser-
  exposed basename only, never a full path.
* No dataset-access gate touched; no dataset assembly.
* No cloud storage, no network call, anywhere in
  `state/session-persistence.js` or any of its callers.

## Local-only architecture

Everything above lives entirely in the browser that ran it.
`localStorage` is per-origin and per-browser-profile — it never syncs
across devices, never leaves the machine, and is never read by anything
outside this page. Command Center and Settings both describe this as
"local session persistence" / "Session data saved" / "local
persistence" — the word "sync" and the phrase "cloud" never appear
anywhere in VL-D9's UI copy or Activity summaries.

## Known limitations

* A restored Import item is a read-only summary — it can never be
  retried or resumed, because the browser `File` object it needed for
  real hashing/validation cannot survive a reload. This is a platform
  constraint, not something a future version of this design can fix
  without a different intake mechanism entirely.
* Non-terminal (in-flight) Import/Processing/Generation queue items are
  never restored, by design — see Excluded state above.
* There is exactly one schema version today; a future breaking change to
  any `export*Plan()` shape will need a real `migrate()` implementation,
  which does not exist yet because nothing has needed it yet.
* `localStorage` has browser-enforced size limits (typically a few MB
  per origin); a very large synthetic session could theoretically hit
  quota. `save()` degrades honestly (see Failure behavior) rather than
  crashing, but VL-D9 does not implement any storage-size management,
  eviction, or warning beyond that.
* This is still not cross-device, cross-browser, or cross-profile
  persistence, and never will be without a real backend — see What VL-D9
  does NOT implement below.

## What VL-D9 does NOT implement

**Cloud sync.** **Backend persistence.** **Execution transport** (still
`NullCommandExecutor`, unchanged since VL-D1 — see
`state/command-executor.js`). **Backend CLI plan consumption** — the
`export*Plan()` payloads this module persists are the same "hand to a
future CLI command" bridge shape VL-D2 introduced; VL-D9 adds a browser-
local round trip on top of that shape, it does not make the CLI actually
consume them. **Dataset assembly / `build-dataset`** — still out of
scope, still deferred for the same speaker-identity-boundary reason
identified during the VL-D8 audit. Real TTS backend; diarization;
transcription; training; any access to real recordings; any
speaker-identity work — all unchanged and out of scope.

## Testing

* Frontend unit (`frontend/tests/session-persistence.test.mjs`): the
  `SessionPersistence` adapter's save/load/clear/`hasSession`/malformed-
  JSON/incompatible-version/wrong-namespace/localStorage-unavailable/
  deterministic-serialization/namespace-isolation behavior, plus
  `hydrate()`/`reset()` coverage for all six store groups (terminal-only
  restoration for Import/Processing/Generation queues, the
  unlistened-evaluation guard, the calibration profile-id counter bump,
  malformed-record rejection). 19 tests.
* Frontend real-browser (`frontend/tests/session.test.mjs`, headless
  Chromium): 13 scenarios — create state → reload → verify restored;
  state survives navigating between workspaces; the calibration
  three-axis state round-trips a reload intact; Clear session data
  removes state immediately; a reload after clearing starts clean;
  Cancel leaves data intact; persistence-unavailable behavior (storage
  throws on every call, app still boots and works, zero console errors);
  a full multi-domain create-then-reload cycle with zero console errors;
  Command Center's Session panel and Storage badge; the honest
  `session_restored`/`session_data_cleared` Activity events (and a
  standing "never says cloud sync" assertion); Settings' status badge.
* Full frontend regression: 287/287 passing (255 VL-D0-VL-D8 baseline +
  32 new: 19 unit + 13 real-browser).

## Next

**D10 audit** — not yet scoped; to be produced separately after VL-D9's
full regression/commit/bundle/publish completes, per the master
execution instruction covering this phase.
