# Phase 3 — Speaker Identity Architecture

> ## Status: software complete, synthetic-only
>
> The identity architecture is implemented and tested against generated
> fixtures. **No real recording has been accessed. No real speaker model
> is installed. No real embedding has ever been computed. No training has
> occurred.** The only embedding provider that exists is a deterministic
> synthetic one.
>
> Phase 3 answers *who is speaking* — the question Phase 2 was
> structurally forbidden to touch.

---

## The synthetic-provenance invariant

The central safety property of this phase. A synthetic embedding is
arithmetic over waveform statistics — not a speaker model, and carrying
no information about human identity.

Rather than relying on people remembering that, the fakeness is carried
in the data:

```
provider.is_synthetic  ->  EmbeddingVector.is_synthetic
                       ->  SpeakerProfile.provider_is_synthetic
                       ->  VerificationResult.provider_is_synthetic
                       ->  is_real_identity_claim == False
                       ->  promote_to_dataset() REFUSES
```

A verification that would otherwise be `ELIGIBLE` is converted to
`SYNTHETIC_ONLY`. Even a confirmed, listened human review cannot promote
it. Asserted by test.

## Modules

| Module | Responsibility |
|---|---|
| `identity/embeddings.py` | Provider abstraction, synthetic provider, protected store |
| `identity/profile.py` | Versioned `SpeakerProfile`, immutability, supersession |
| `identity/enrollment.py` | Pluggable engine + three strategies |
| `identity/calibration.py` | Thresholds and the three calibration states |
| `identity/verification.py` | Rejection-first scoring and decisions |
| `identity/review.py` | Identity review queue, promotion gate |
| `identity/audit.py` | Hash-chained append-only audit log |
| `identity/contracts.py` | Read-only JSON contracts for the desktop |
| `identity/runtime.py` | Vendor-neutral capability metadata |
| `identity/preview.py` | VL-V0 preview/feedback contracts |
| `identity/synthetic_e2e.py` | Full synthetic chain |

---

## Embedding provider abstraction

`EmbeddingProvider` is an ABC. Real providers (TitaNet, WeSpeaker, …)
will subclass it **inside their own isolated environment** and
communicate through the filesystem contract — they are never imported
into the base interpreter, whose dependency set stays ML-free.

`SyntheticEmbeddingProvider` projects a waveform onto a fixed cosine bank
and normalises. Measured separation on synthetic fixtures:

| Comparison | Similarity |
|---|---|
| Same signal vs profile | 0.978 |
| Different signal (impostor) | 0.504 |
| Same signal, channel mismatch | 0.562 |

Enough to exercise every code path. **It cannot distinguish two humans**,
and any similarity it reports is about waveform shape, not identity.

### Embeddings are biometric data

A *real* embedding derived from the private recordings is a biometric
identifier of a deceased person; voice characteristics can be partially
reconstructed from such vectors. Protections, all in place before any
real provider exists:

- Stored only under `data/embeddings/`, git-ignored, with behavioural
  tests asking Git directly.
- Manifests and logs carry the **hash and path only** — never the numbers.
- Integrity verified on load; a corrupted vector raises.
- **No export function exists.** No code path writes a vector outside the
  data root.
- Deletion is supported and audited — the record outlives the data.
- The audit log redacts `values`/`vector`/`samples` keys and absolute
  paths automatically.

---

## Pluggable enrollment

The right enrollment approach for the target speaker is **an open
decision** ([the circularity problem](#the-enrollment-circularity)), so no
strategy is hard-coded. A test asserts `EnrollmentEngine` mentions no
strategy by name.

| Strategy | Human approval | Roles | Purpose |
|---|---|---|---|
| `synthetic` | No | synthetic only | Development; cannot enroll a real role |
| `direct_recording` | No | operator, target | Speaker who can record fresh audio |
| `human_anchored` | **Yes** | target, operator | Speaker who cannot record |

`register_strategy()` adds a new one with no change to the engine,
profile model, or verification.

### The enrollment circularity

Verifying "is this her" needs a reference sample of her voice. Her only
recordings are the ones being labelled. Any automatic bootstrap resolves
this by guessing, and a wrong seed propagates silently into the whole
dataset.

`HumanAnchoredEnrollmentStrategy` encodes the recommended resolution. A
seed segment must satisfy **all** of:

- `human_confirmed` is true **and** names a confirmer
- Phase 2 overlap status is exactly `NO_OVERLAP_DETECTED` — `UNKNOWN` is
  refused, because "we could not tell" is not "probably fine"
- Phase 2 quality status is `PASS`
- duration ≥ 1.5 s, and at least **two** seeds, so one mislabelled
  segment cannot define the profile alone

Without `approved_by` the engine raises `HumanApprovalRequired` rather
than degrading to a best guess.

**Automatic seed expansion is not implemented and should be treated as
forbidden by default** — it is how a small initial error becomes a
systematically wrong profile.

---

## Calibration: three explicit states

| State | Meaning |
|---|---|
| `UNCALIBRATED` | No evidence. Thresholds are safety defaults, not measurements. |
| `PROVISIONAL` | Evidence exists but supports no statistical claim. |
| `CALIBRATED` | Validated against labelled held-out data. |

> ### `CALIBRATED` is unreachable for the target speaker
>
> Calibration needs a labelled held-out set. Every recording of her is
> inside the dataset being labelled, and the labels are what verification
> is trying to produce. **This is a property of the data, not a missing
> feature**, and no future code will fix it.

Enforced in code: `CalibrationRecord.__post_init__` refuses `CALIBRATED`
unless evidence is held-out labelled data, and refuses it outright for a
synthetic provider. `require_calibrated()` blocks operations needing it.

### What *can* legitimately be calibrated

- **Operator rejection** — he is alive and can record freely, so his
  samples split into enrollment and held-out sets.
- **Channel sensitivity** — score drop from wideband/narrowband mismatch.
- **Score distributions / deterministic test thresholds** — from
  synthetic fixtures; validates software behaviour only.
- **Reviewer feedback** — genuine evidence, but reviewers saw the machine
  recommendation first, so their agreement is correlated with it and is
  **not independent ground truth**. Stays `PROVISIONAL` permanently.

Every record carries a `limitations` list stating what it does *not*
establish.

---

## Verification: rejection first

The two errors are not equally bad, and the system is built as though
that is true:

| Error | Consequence | Recoverable |
|---|---|---|
| Operator admitted as target | Model trained partly on the wrong person | **No** |
| Her segment rejected | Slightly less data | Yes |

So the thresholds are asymmetric — `operator_rejection_threshold` (0.55)
is far below `target_acceptance_threshold` (0.85), and a test asserts the
ordering. Operator scoring runs **before** target scoring and short-
circuits on a match.

Eligibility itself is delegated to `security/speaker_policy.py`, the
Phase 0 module with 48 tests including an exhaustive sweep. Phase 3
populates its inputs; it does not reimplement the decision, which would
create two policies free to drift apart.

`SYNTHETIC_SPEAKER` maps to policy `UNKNOWN`, so a synthetic profile can
never satisfy the policy as a real target — a second, independent guard
alongside the provenance stamp.

---

## Identity review

Distinct from Phase 2's `candidate_review`, which asks only about
technical fitness. Records are pinned to `review_type: "identity"` and
the queue refuses anything else.

- **Human approval is mandatory for acceptance.** No confidence level
  bypasses it; even `ELIGIBLE` is queued for review.
- **Listening is recorded, not assumed.** `listened: false` is not a review.
- **`ambiguous` is first-class.** On degraded audio "I cannot tell" is
  often correct, and forcing a binary choice is how errors enter.
- **Decisions are immutable**; later records supersede earlier ones.
- **Disagreement is tracked** — without labelled data, reviewers
  overturning machine acceptances is the only early warning that a
  threshold has drifted loose.

`promote_to_dataset()` is the final gate and fails closed on every
missing condition.

---

## Audit log

Hash-chained JSON Lines under `data/audit/`. Each entry links to the
previous; `verify_chain()` detects tampering, reordering, and deletion —
all tested.

**Append-only in the sense that matters**: entries are only added, and
corruption is *detectable*. It is not cryptographically prevented, which
would need an external notary. Stated rather than glossed: this defends
against accident and silent corruption, not a determined attacker with
write access.

---

## Desktop contracts (read-only)

`identity/contracts.py` returns plain JSON envelopes for: speaker
profiles, enrollment status, verification results, review queues,
calibration status, provenance chains, audit history, pipeline status,
embedding inventory, runtime capabilities, and preview status.
`desktop_snapshot()` returns everything in one call.

The GUI **renders**; it must not reimplement policy. Every payload
carries the honesty flags (`provider_is_synthetic`, `calibration_state`,
`is_real_identity_claim`), so a UI cannot present a development result as
a real determination without deliberately ignoring data it was handed.

---

## Claude Code Command Center contracts (VL-D6 / D7 / D8 / D9)

`identity/command_center.py` supplies the future desktop panel that shows
Claude's activity, pipeline context, diffs, and a curated set of runnable
commands. It **executes nothing** — a check on the module's own public
names asserts no `execute`/`run_command`/`shell`/`eval` surface exists.
The desktop presents `COMMAND_CATALOGUE` and invokes each command through
the ordinary CLI, so every run still passes the same gates and audit
logging as a terminal invocation. Duplicating policy into the UI was
considered and rejected for the same reason `contracts.py` never encodes
a decision: Core decides, the desktop renders.

Each `CommandDescriptor` carries a `risk` (`read_only`, `writes_local`,
`destructive`, `gated`). Destructive commands must set
`requires_confirmation`; gated ones must name `gate_reason` rather than
simply disappearing — a hidden control invites hunting for a workaround,
a disabled one with a reason does not.

`changed_files()` returns file names and line counts, never diff content:
a diff under `data/` could carry private material, so the contract that
is safe to render everywhere stops at the numbers. `activity_feed()`
reads the already-sanitised audit log, so nothing it returns needs
separate redaction.

## Local-first, no cloud (VL guiding constraint)

No pipeline, identity, audio, core, or security module imports a network
or cloud client — asserted by an AST-based test that walks every import
in those packages and fails on `requests`, `boto3`, `google`, `azure`,
`smtplib`, and similar. Every storage path Phase 3 uses resolves under
the local `DataRoot`, asserted directly. `EmbeddingStore` is checked for
export-like methods (`export`, `upload`, `sync`, `push`) and has none by
construction — there is no code path that can send a vector anywhere.

## Hardware independence (VL-D19 / VL-D20)

Core interfaces name **no vendor, no product, and no specific GPU**. Any
one development machine — whatever it contains — is a test host, never a
design target: hard-coding one would quietly make every other machine a
special case. A test greps the identity modules for `torch.cuda`,
`nvidia-smi`, `cudnn`, and specific product names (`RTX`, `GTX`, `Radeon`,
`GeForce` + a model number) and fails on a hit.

Components declare capability as data — `AccelerationRequirement`,
`ComputeBackend`, `PortabilityClass` — so a future scheduler or packaging
step can ask "does this need an accelerator?" without branching on vendor
names. `ComputeBackend` enumerates CUDA, ROCm, Metal, OpenCL, Vulkan, and
XPU alongside CPU, plus an open `OTHER` member so an accelerator nobody
has anticipated yet is still representable without a schema change. The
future AI Calibration Engine (VL-D15) detects the actual hardware present
and optimises for it; this module only supplies the vocabulary it reads.

`describe_portability()` states its own limit: declarations are not
proof, and a portability claim is unverified until actually run on a
machine with no accelerator.

## Voice preview (VL-V0)

**Contracts only. No voice generation exists**, and none has ever been
produced by this project. `PreviewProvider` is abstract and cannot be
instantiated.

The requirement it fixes: every future voice-generation operation must
produce something a human can listen to before acceptance. A voice built
from a deceased person's recordings must never be adopted on a similarity
number alone.

---

## Synthetic end-to-end

`aarya-voice synthetic-e2e` runs the whole chain on generated audio:

```
synthetic audio -> candidate -> enrollment -> profile -> embedding
-> verification -> score -> threshold -> decision -> audit -> provenance
```

Covers positive match, negative match, borderline/channel mismatch,
overlap rejection, unknown overlap, poor quality, invalid profile,
corrupted embedding, provider mismatch, and interrupted operations.

Current outcome: **0 promotions, 0 real identity claims** — the correct
result. Synthetic provenance blocks dataset entry by design.

---

## What still depends on real recordings

| Blocked | Why |
|---|---|
| Real speaker verification | No real embedding provider installed |
| Target profile enrollment | Requires the recordings plus human seed selection |
| Operator profile enrollment | Requires a fresh recording from the operator |
| Any statistical calibration | Requires held-out labelled data |
| Threshold validation | Current values are reasoned, never measured |
| Verified dataset | Requires real verification and human review |
| Real accuracy claims | Synthetic fixtures validate plumbing, not accuracy |

**Thresholds (0.55 / 0.65 / 0.85) are reasoned defaults, not measured
values.** They express the intended asymmetry; they have never been
validated against any real voice and must be revisited with real data.
