# The `.arya-voice.zip` Package Contract

Task 6 of the autonomous execution plan. This document defines the
versioned manifest contract at the boundary between two **separate**
systems:

```
Voice Lab
    ↓
.arya-voice.zip
    ↓
AARYA Core Voice Package Manager
```

- **Voice Lab** (this repository) creates, trains, validates, and
  benchmarks voices, and produces `.arya-voice.zip` packages.
- **AARYA Core** consumes packages: validates, imports, installs,
  registers, and runs custom voices. Core's importer/installer is a
  **separate system this repository does not contain** — see
  [`ARCHITECTURE.md`](ARCHITECTURE.md)'s scope boundaries and README's
  "AARYA Core integration" row (PLANNED, explicitly out of scope here).

This document and
[`pipeline.voice_package`](../src/aarya_voice_lab/pipeline/voice_package.py)
define only the contract. No `.arya-voice.zip` file has ever been
produced by this project, and none is created, opened, or shipped by
this repository's code — `*.zip` remains git-ignored throughout, as it
was before this task.

## The manifest

Every package's root contains `manifest.json`, validated against
[`schemas/voice_package_manifest.schema.json`](../schemas/voice_package_manifest.schema.json)
and built via `pipeline.voice_package.build_voice_package_manifest()`.

| Field | Meaning |
|---|---|
| `format` | Fixed marker: `"arya-voice-package"` |
| `format_version` | Semver of this manifest contract |
| `voice_id`, `display_name`, `version` | Identity |
| `type` | `"default_voice"` or `"other"` — see below |
| `provider`, `provider_version` | Which engine produced the voice |
| `languages` | BCP-47-ish tags actually supported (never inferred) |
| `model_format` | One of `pipeline.model_artifact.ModelArtifactFormat`'s values |
| `runtime_requirements`, `hardware_requirements`, `memory_requirements_mb` | What Core needs to provide to run it |
| `license` | Never left blank — same rule as [`DATA_POLICY.md`](DATA_POLICY.md) applies to models, not just datasets |
| `provenance` | e.g. a training job id or dataset registry reference |
| `integrity` | `{"algorithm": "sha256", "checksum_sha256": <64 hex chars>}` |
| `compatibility` | e.g. minimum Core version, target platforms |
| `creator` | Optional attribution |

### `type` deliberately excludes `private_voice`

A `.arya-voice.zip` is a distribution artifact. The Private Voice model
requires admin-only, permission-gated, Core-side enforcement
(`voice.private.use`, per [`SECURITY.md`](SECURITY.md) and the model
registry's `security_metadata` block) — the same reasoning VL-D12
already applied when it permanently excluded `private_voice` entries
from every frontend-facing registry method. Extending that here: this
package format has no mechanism to carry or enforce
`security_metadata`, so a private voice must never be offered a path
into it. If Private Voice distribution is ever needed, it requires its
own, separately designed and reviewed mechanism — not a `type` value
silently added to this schema.

## Package contents

Data/model oriented, by design:

```
manifest.json
model.<ext>              # one of the allowed model_format extensions
LICENSE.txt (or similar)
metadata/*.json           # optional additional metadata
```

`pipeline.voice_package.validate_package_entries()` checks a proposed
file listing against a fixed **allowlist**
(`ALLOWED_PACKAGE_EXTENSIONS`) — `.json`, `.txt`, `.md`, and a small set
of model-weight extensions (`.onnx`, `.safetensors`, `.pt`, `.pth`,
`.ckpt`, `.nemo`, `.bin`, `.wav`). This is an allowlist, not a
blocklist, matching the project's fail-closed principle
([`ARCHITECTURE.md`](ARCHITECTURE.md)): an unrecognised extension is
rejected, not silently passed through. No script or executable
extension is on the list — `.py`, `.sh`, `.exe`, `.ps1`, `.dll`, `.so`,
and `.jar` are all rejected by the same mechanism that rejects any other
unlisted type, not by a separate special case. Path-traversal entries
(`..` in any path segment) are rejected regardless of extension.

## Integrity

`integrity.checksum_sha256` follows the exact same naming and format as
`pipeline.model_artifact.ModelArtifact.checksum_sha256` — a package's
model artifact is checksum-addressed the same way this project already
addresses every other model artifact it stores.

## Future work (not implemented by this task)

- **Digital signing.** The `integrity` block is designed to be
  extensible (e.g. a future `signature` field) without a breaking schema
  change, but no signing or PKI mechanism is implemented here. A single
  SHA-256 checksum proves integrity against accidental corruption, not
  authenticity against a malicious package — that is a deliberately
  deferred, separate design decision.
- **AARYA Core's importer/installer.** Out of scope for this repository
  entirely, per its own architectural boundary.
- **Actually producing a package.** No code in this repository zips a
  model artifact and this manifest together yet; that is the natural
  next step once a real, approved model exists to package (see
  [`PHASE3_CHECKPOINT.md`](../PHASE3_CHECKPOINT.md) for what remains
  gated before one does).
