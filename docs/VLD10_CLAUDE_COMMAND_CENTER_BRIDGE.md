# VL-D10 — Claude Command Center Bridge

AARYA Voice Lab only. Not a JARVIS milestone; nothing in this phase touches
Aarya Core or any other project.

## Purpose

`identity/command_center.py`'s `command_center_snapshot()` — real git
branch/HEAD/working-tree state, the real identity activity log, a real
git-safety/audit-chain diagnostics read, the command catalogue, and
verification-command descriptors — has existed since VL-D6/D7/D8/D9,
was fully tested, and was CLI-exposed (`aarya-voice command-center`).
Nothing in the frontend ever called it. `workspace-claude.js` hardcoded
`branch: "(not fetched)"`, `head_short: "-------"`, an empty activity
list, and `buildClaudeContext()`'s `git_state` field was `null` at every
call site in the repository — a gap the D0-era
`claude-context-model.json` contract itself named ("`repository`:
`identity/command_center.py` `repository_context()` payload... target
shape for VL-D1+") and that stayed unfilled for nine phases.

VL-D10 closes exactly that gap. It is a **live, read-only snapshot
bridge** — connecting an existing, tested backend read to an existing,
built frontend UI. It is explicitly **not** a command-execution system;
see Read-only behavior below.

## Architecture

```
identity/command_center.py:command_center_snapshot()
        ↓
scripts/export_command_center_snapshot.py
        ↓
frontend/contracts/live/command_center_snapshot.json   (gitignored)
        ↓
state/command-center-snapshot.js:fetchCommandCenterSnapshot()
        ↓
workspace-claude.js  →  claude-command-shell.js
```

This mirrors `scripts/export_dataset_gate_status.py`'s established
pattern exactly: a live, point-in-time read (git state and the audit log
both legitimately change run to run) written to a gitignored file under
`frontend/contracts/live/`, fetched at runtime, and honestly rendered as
"not fetched" when the file doesn't exist rather than guessing at a
value.

## Existing backend source

`identity/command_center.py`, unchanged by D10:

- `repository_context()` — real `git` subprocess calls (branch, HEAD,
  working-tree cleanliness, recent commits). Never a diff, never file
  content.
- `activity_feed()` — the real Phase 3 identity audit log
  (`AuditLog.read_all()`), already sanitized at the source.
- `diagnostics()` — a real git-safety scan (`scan_git_repo`) and
  audit-chain integrity check, plus pipeline stage counts.
- `command_catalogue()` / `verification_commands()` — static, curated
  descriptors (`CommandDescriptor`), each with a `risk` tier
  (`read_only`/`writes_local`/`destructive`/`gated`) and, for a gated
  command, a `gate_reason`.
- `command_center_snapshot()` — bundles all of the above into one
  envelope.

## Live snapshot mechanism

`scripts/export_command_center_snapshot.py` calls
`command_center_snapshot(DataRoot.default(), REPO_ROOT)` and writes the
result to `frontend/contracts/live/command_center_snapshot.json`,
wrapped in the same `$generated_by`/`$live_snapshot`/`note` envelope
`export_dataset_gate_status.py` uses. Not committed (already covered by
the existing `frontend/contracts/live/` `.gitignore` rule — no change
needed there), not part of the drift-tested contract set, and never
invents a field beyond what `command_center_snapshot()` itself already
decided was safe to display.

## Frontend consumption

`state/command-center-snapshot.js`'s `fetchCommandCenterSnapshot(url)`
does the fetch and validation, kept separate from `workspace-claude.js`
so it is unit-testable without a browser DOM:

1. Network failure → `null`.
2. Non-2xx response (including a 404 for "script never run this
   session") → `null`.
3. Malformed JSON → `null`.
4. Well-formed JSON that isn't an object, or whose `contract` field
   isn't `"command_center_snapshot"` → `null` (refuses a stray or
   wrong-source payload rather than rendering it as if it were real).
5. Otherwise → the payload, unmodified.

`workspace-claude.js` fetches once per mount and passes the result (or
`null`) straight to `claude-command-shell.js`'s `.snapshot` and into
`buildClaudeContext()`'s `gitState` — never a fallback object.

## Repository state

`claude-command-shell.js` renders `snapshot.repository.branch` /
`head_short` / `working_tree_clean` / `changed_file_count` in its
context line. **Note on the envelope shape**: `command_center_snapshot()`
spreads each section's fields directly (no `.payload` wrapper) — the
component previously assumed a `.payload`-nested shape that was never
validated against the real backend (an artifact of the original
hardcoded placeholder object), corrected as part of this wiring.

## Activity

The real identity audit log's entries render through the existing
`avl-claude-output-log`. In this synthetic-only project, this feed is
legitimately almost always empty — no real identity operation has
happened — which is itself honest, not a bug.

## Diagnostics

Three states only, driven entirely by `snapshot.diagnostics`:
**unavailable** (no snapshot — offline badge), **healthy**
(`diagnostics.healthy === true` — ready badge), **unhealthy**
(`diagnostics.healthy === false` — attention badge, with the real
`problems` list shown, never hidden). No diagnostic is ever computed in
the browser; every value is exactly what the backend decided.

## Command catalogue

`claude-command-shell.js` renders every `CommandDescriptor` from
`snapshot.commands.commands`: command name, summary, risk tier, and —
for a `gated` command — its real `gate_reason`, always visible rather
than hidden (matching `identity/command_center.py`'s own design note
that a hidden gated control "invites the user to look for a way
around it"). Display only: no row is a button, no row executes anything.

## Verification-command descriptors

`snapshot.verification.commands` — each entry's `label` and the exact
`argv` array the backend describes — rendered as plain text. Never
executed from the browser.

## Missing/malformed snapshot behavior

Identical honest state whether the snapshot file is absent, unreadable,
malformed JSON, or well-formed JSON from a different contract:
"No repository context loaded — snapshot not fetched.", "Diagnostics
unavailable — snapshot not fetched.", "No command catalogue loaded —
snapshot not fetched.", empty activity log, and `buildClaudeContext()`'s
`git_state` stays `null`. Never a fabricated branch name, never an
empty-but-present activity feed presented as if real.

## Security boundary

- Every field rendered is exactly what `identity/command_center.py`
  already decided is safe to display (file names, counts, booleans —
  never a diff, never audio, never a vector, never an absolute path into
  private storage). D10 adds no new backend logic and no new sanitization
  decision.
- The live snapshot file is gitignored and regenerated per run, same as
  `dataset_gate_status.json` — never committed, never a stale claim.
- No new write path, no new execution path, no new permission surface.

## Read-only behavior (non-negotiable)

D10 is a **read-only snapshot bridge**, not command execution. Unchanged
by this phase:

- `state/command-executor.js`'s `NullCommandExecutor` — still the only
  executor, still `available() === false`, still every `execute()` call
  honestly returns `NOT_AVAILABLE`.
- `claude-command-shell.js`'s command-input row still only dispatches
  `avl-command-submit`; nothing in this repository listens for it.
- The command catalogue and verification descriptors are rendered text,
  never a clickable "run" affordance.
- No subprocess execution from the browser, no IPC, no local HTTP
  execution transport, no desktop bridge. Those require a real
  execution transport and a separate, dedicated threat-model review —
  explicitly out of scope here.

## Real git_state and the redaction heuristic

Wiring a real branch name through `buildClaudeContext()` for the first
time (`git_state` was `null` at every call site through D1–D9) surfaced
a genuine false positive: the existing generic opaque-value redaction
heuristic (`state/claude-context.js`'s `OPAQUE_VALUE_PATTERN`, tuned to
catch base64/hex-shaped secrets 20+ characters long) matched ordinary
kebab-case branch names like `phase3-speaker-verification` and masked
them to `<redacted>`. `git_state` is real, developer-chosen, already-
public repository metadata — identical to what
`identity/command_center.py`'s own docstring calls safe to display, and
to what `claude-command-shell.js` already renders in plaintext right
above the same JSON preview — so `buildClaudeContext()` now copies
`git_state` through unredacted after the generic pass runs on everything
else. The generic heuristic itself is untouched: it still catches a
real embedded secret anywhere else in the context object exactly as
before (see the existing `redactDeep` tests in
`tests/state-model.test.mjs`, all still passing unmodified).

## Documentation fixes

Two stale pre-renumbering roadmap references (found during the D10
audit, the same category `VL-D7`'s doc fix already handled once for
"VL-D15") were reworded to neutral headings: `docs/VLD0_DESIGN_SYSTEM.md`
("Hardware UI foundation (VL-D19 / VL-D20)" → "Hardware UI foundation";
"Accent/Pronunciation UI foundation (VL-D21)" → "Accent/Pronunciation UI
foundation"; the inline "`avl-accent-panel` (VL-D21, concepts only)"
reference reworded) and `docs/PHASE3_IDENTITY.md` ("Hardware
independence (VL-D19 / VL-D20)" → "Hardware independence"). No
functional change; no replacement milestone numbers invented.

## Testing

- Frontend unit (`frontend/tests/command-center-snapshot.test.mjs`):
  13 scenarios against a locally-controlled `node:http` server — valid
  snapshot parsed as-is; real repository/activity/diagnostics/command-
  catalogue/verification fields preserved verbatim; a healthy and an
  unhealthy diagnostics payload both render their real state; a missing
  (404), errored (500), malformed-JSON, wrong-contract, non-object, and
  network-unreachable response all resolve to `null`, never throw.
- Frontend real-browser
  (`frontend/tests/claude-command-center.test.mjs`, headless Chromium):
  15 scenarios (the required 12 plus three follow-on cases for an
  unhealthy-diagnostics render and a wrong-contract-payload render) —
  workspace mounts; live snapshot loads and the shell no longer says
  "not fetched"; real branch/HEAD/working-tree state render; activity
  renders from the real snapshot (via the output log's own nested shadow
  root); the command catalogue renders including a gated command's real
  reason; verification descriptors render; diagnostics render honestly
  both healthy and unhealthy; a missing snapshot, a malformed snapshot,
  and a wrong-contract snapshot all remain honest; the Claude context
  preview carries the real (unredacted) `git_state`; a full
  create-then-navigate cycle across snapshot states produces zero
  unexpected console errors.
- Every existing real-browser test file's bad-response allowlist was
  extended to also tolerate the new live snapshot's expected 404
  (mirroring the existing `dataset_gate_status.json` allowance exactly)
  — `app-smoke.test.mjs`, `calibration.test.mjs`, `dataset-review.test.mjs`,
  `dataset-workspace.test.mjs`, `feedback.test.mjs`, `preview.test.mjs`,
  `processing.test.mjs`, `session.test.mjs`. No existing assertion was
  weakened.

## Known limitations

- The identity activity feed is almost always empty in this
  synthetic-only project — an honest reflection of "no real identity
  operation has happened," not a bug, but it means the Activity section
  of the Claude Command Center will typically show little until a real
  Phase 3 identity operation is performed.
- `claude-task-status.js` remains wired to a static `"idle"` state with
  no command selected — it was already compatible with the real
  `CommandDescriptor` shape and needed no change, but D10 doesn't add an
  interactive "select a catalogue row" affordance; that would be a UI
  enhancement, not part of closing the identified gap.
- The command catalogue and verification descriptors are point-in-time,
  same as the rest of the snapshot — re-run
  `scripts/export_command_center_snapshot.py` to refresh.

## What VL-D10 does NOT implement

Command execution. Shell execution. Arbitrary code execution. Desktop
IPC. Execution transport. Backend plan execution. Dataset assembly.
Training. Diarization. Transcription. Real TTS. Real recordings.
Speaker-identity expansion. Cloud sync/storage.

## Next

**D11 audit** — not yet scoped; to be produced separately, evidence-based
against the actual D0–D10 implementation, after D10's full
regression/commit/bundle/publish completes.

**Update:** produced. See `docs/VLD11_IDENTITY_STATUS_BRIDGE.md` —
bridges `identity.contracts.desktop_snapshot()` (D10's sibling function,
left unfetched by the frontend the same way `command_center_snapshot()`
was before this milestone) and fixes a real, active
`real_provider_installed`-hardcoded-False defect discovered live inside
this milestone's own `command_center_snapshot.json` diagnostics payload.
