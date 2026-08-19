# Security Model

Covers two distinct concerns: keeping the operator's voice **out** of the
Private Voice dataset, and keeping the resulting Private Voice model
**restricted**.

> Phase 0 implements the *decision policy* (as pure, tested logic) and the
> *schema constraints*. Enforcement in AARYA Core is PLANNED and out of
> scope here.

---

## Part 1 — Speaker safety

### The requirement

The 31 recordings contain two speakers: the **operator** and the **target
female speaker**. The Private Voice dataset must contain **only** the
target speaker. An operator-voice segment leaking into the dataset would
contaminate the trained model with the wrong person's voice — a failure
that is difficult to detect after training and expensive to reverse.

### The policy

Implemented in
[`security/speaker_policy.py`](../src/aarya_voice_lab/security/speaker_policy.py):

| Situation | Decision |
|---|---|
| Target female speaker, both systems agree, high confidence | **ELIGIBLE** |
| Operator voice | **REJECT** |
| Both speakers / overlap detected | **REJECT** (by default) |
| Ambiguous, conflicting, or medium confidence | **MANUAL REVIEW** |
| Unknown speaker or unknown overlap status | **MANUAL REVIEW** |
| Low confidence | **REJECT** |

The policy is **fail-closed**: `ELIGIBLE` is reachable only when every
condition is affirmatively satisfied. A test asserts this exhaustively
across all role/overlap combinations — including that a secondary system
claiming "target" can never override a primary identification of the
operator's voice.

### What must NOT be trusted as evidence

Signals that seem informative but are not reliable identity evidence:

- **Speaker number** — `spk_0`/`spk_1` are assigned per recording. They
  are not consistent across files, and assuming otherwise would
  systematically mislabel entire recordings.
- **Filename** — naming conventions drift and were never designed as
  ground truth.
- **Pitch** — overlaps heavily between speakers and varies with emotion,
  health, and recording conditions.
- **Gender classification** — a gender classifier confirms a category,
  not an identity. Both a match and a mismatch are compatible with the
  wrong person.

Identity comes only from **speaker verification against a reference**,
corroborated by a second independent system.

### Two-system verification

```
Primary system (NVIDIA NeMo / SortFormer)
        +
Independent verification (second system)
        +
Speaker consistency
        +
Audio quality
        ↓
   confidence classification
        ↓
HIGH   → eligible
MEDIUM → manual review
LOW    → reject / manual review
```

Confidence is taken from the **weakest** contributing system, not the
average — averaging would let one overconfident system mask another's
uncertainty.

Two systems are used because they fail differently; agreement between
independent methods is much stronger evidence than one high score. **If
the secondary system has not run, the result is never ELIGIBLE** — it
goes to manual review.

**Preferred primary:** NeMo Sortformer
(`nvidia/diar_streaming_sortformer_4spk-v2.1`) — ungated, no credentials,
4-speaker capacity covers 2-speaker material.

**Secondary candidate:** WhisperX/pyannote — but see the credentials
warning in [ENVIRONMENT.md](ENVIRONMENT.md); adopting it requires
sign-off because it introduces a gated model and a third-party account.

---

## Part 2 — Private Voice model security

**PLANNED — documentation only. None of this is implemented in Phase 0,
and its enforcement belongs in AARYA Core, not here.**

### Requirements

| Control | Requirement |
|---|---|
| Permission | `voice.private.use` |
| Authorization | **Admin-only** |
| Enforcement point | **AARYA Core** — server-side |
| Audit | Every use audit-logged |
| Storage | Protected model storage, restricted ACL |
| Frontend | **No frontend-only authorization** |
| Raw material | **No raw recordings exposed to the frontend, ever** |
| Distribution | No unnecessary distribution of the model |

### Why enforcement cannot live in the frontend

A frontend check is a UI affordance, not a security control — anyone able
to call the API directly bypasses it entirely. The permission must be
verified server-side in Core on every synthesis request. The frontend may
*hide* the private voice from users who lack the permission, but hiding
must never be the only thing standing between a user and the model.

The model registry schema encodes this: a `private_voice` entry
**requires** a `security_metadata` block, and records
`frontend_direct_access` explicitly so a later Core-side check has a
concrete field to enforce against. A private model entry missing this
metadata fails validation — tested.

### Treat the model as equivalent to the recordings

A voice model can reproduce the speaker's voice on demand. It is not a
safely-abstracted derivative — for handling purposes it is **the same
sensitive material as the source audio**, and inherits every rule in
[PRIVACY.md](PRIVACY.md): never committed, never uploaded, never
distributed casually.

---

## Repository security

- **Secrets never enter the repo.** No credentials, tokens, or API keys
  in code, config, or tests. `.gitignore` blocks common secret patterns
  and `source_protection` flags secret-like filenames.
- **Logs must not leak.** No raw audio, no transcripts derived from
  private recordings, and no credentials in logs or error messages.
- **Validation is offline.** Schema resolution never makes network
  requests, so no local file path or manifest content can leak through a
  validation call.
- **Pre-commit safety scan.** `aarya-voice validate-environment` scans
  everything Git tracks or has staged for audio, model artifacts, and
  secret-like names. See [DEVELOPMENT.md](DEVELOPMENT.md).
- **`trust_remote_code` is a code-execution risk.** Some candidate TTS
  models (notably IndicF5) require `trust_remote_code=True`, which runs
  arbitrary code from the model repo. Review that code before running it
  in an environment that can reach private material.
