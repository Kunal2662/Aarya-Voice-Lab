# AARYA Core Package-Consumption Contract

Phase 6 of the 8-phase release plan. **AARYA Core is not present in this
workspace** — no Core repository or source tree was found alongside
this checkout, confirmed by search before writing this document, not
assumed. Per this phase's own explicit instruction, this document
therefore **describes the contract Core's consumer side would need to
satisfy, without inventing Core's actual architecture, file layout, or
implementation**. Nothing in this document is implemented code; nothing
here moves Voice Lab logic into Core, and nothing here modifies any
Core repository, because none is available to modify.

## The bridge, restated

```
AARYA Voice Lab                                    AARYA Core
────────────────                                    ──────────
produces a validated                                consumes it via a
.arya-voice package        ──── file ────►           Voice Package Manager
(see VOICE_PACKAGE_SPEC.md)
```

Voice Lab's responsibility ends at producing a package that passes
`pipeline.voice_package.validate_package_archive()` with zero problems.
Everything below this line is Core's responsibility, described here
only so a future Core-side implementer has a precise, already-agreed
contract to build against — not a suggestion that Voice Lab build it.

## Expected consumer-side flow

```
.arya-voice file
      ↓
IMPORT               — read the archive, nothing more
      ↓
VALIDATION            — manifest schema, package-entry allowlist,
                         checksum match (all three already defined in
                         schemas/voice_package_manifest.schema.json and
                         pipeline.voice_package; Core re-implements or
                         vendors the same checks, never trusts a package
                         merely because it came from Voice Lab)
      ↓
COMPATIBILITY CHECK    — manifest.compatibility, manifest.runtime_requirements,
                         manifest.hardware_requirements against the
                         actual Core installation's real capabilities
      ↓
INSTALL                — atomic: either the full package lands correctly
                         or nothing changes on disk
      ↓
REGISTRY                — Core's own voice registry, keyed by
                         manifest.voice_id + manifest.version
      ↓
ACTIVATE / DISABLE / REMOVE / UPDATE
      ↓
RUNTIME                 — Core loads and runs the voice
```

## Required behavior, restated as explicit requirements

| Requirement | Why |
|---|---|
| Re-validate every check Voice Lab already performed | A package could reach Core by a path Voice Lab never touched (manual copy, a future non-Voice-Lab producer); Core must never trust "it came from the right place" as a substitute for checking the bytes |
| No arbitrary code execution from the package | `validate_package_entries()`'s allowlist already excludes every script/executable extension at the Voice Lab side; Core's own importer must apply the same or a stricter allowlist, never merely "whatever this manifest says is fine" |
| No path traversal | Core's own extraction must reject `..` path segments independently of Voice Lab's check — defense in depth, not reliance on the producer |
| No silent overwrite of protected files | Installing `voice-a` must never silently overwrite `voice-b`'s files or any Core system file; a name/id collision is an explicit error, not a merge |
| Atomic installation | A crash or error mid-install must leave the prior state intact (either the old version still active, or nothing installed) — never a half-extracted, half-registered voice |
| Rollback on failure | If any step (validation, compatibility, install, registry) fails, every already-taken action from that install attempt is undone |
| Clear error reporting | Every rejection names which specific check failed (schema field, checksum mismatch, disallowed entry, incompatible runtime) — mirroring `pipeline.voice_package.validate_package_archive()`'s own "return every problem, not just the first" convention |

## What Voice Lab already guarantees, so Core does not have to

- `manifest.type` can never be `"private_voice"` — the manifest schema's
  own enum excludes it (see VOICE_PACKAGE_SPEC.md). Core does not need
  a separate check to keep the Private Voice model out of this
  distribution path; it cannot arrive via `.arya-voice` at all.
- `manifest.integrity.checksum_sha256` is always a real SHA-256 of the
  packaged model bytes, verified at build time
  (`build_package_archive()` recomputes and cross-checks it before
  writing).
- No package Voice Lab produces contains an executable, script, or any
  extension outside `voice_package.ALLOWED_PACKAGE_EXTENSIONS`.

Core should still re-verify all of this independently (see the table
above) — these are guarantees about what Voice Lab *produces*, not a
substitute for Core validating what it *receives*.

## What this document does not do

- Does not implement any part of Core's Voice Package Manager, registry,
  or runtime.
- Does not assume Core's programming language, storage format, or
  process architecture — none of that is knowable without the actual
  Core repository.
- Does not change `pipeline.voice_package` or `pipeline.model_manager`'s
  existing behavior; those already satisfy the Voice-Lab side of this
  contract as described.

## What would change this

Access to the actual AARYA Core repository, so its real architecture,
language, and existing conventions can inform a concrete implementation
plan instead of this abstract contract.
