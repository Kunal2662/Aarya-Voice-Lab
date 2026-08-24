# AARYA Voice Lab — Phase 3 Checkpoint

**Purpose of this file:** recover and continue this project from a fresh
Claude Code session with no prior context. It is bundled with the Git
history at `VoiceLab-Phase3-Complete.bundle`. This file is a checkpoint,
not a replacement for the repository — the bundle's Git history is the
source of truth; this document is the map.

Generated: see `Generated at` in the final report accompanying this
checkpoint. Do not treat this file's contents as current if it is old —
re-run `git log` and `pytest` before trusting anything below.

> **Reconciliation note (added at `HEAD bb8132e`, doc-only pass).** This
> file was written just after commit `3b95790` and was not updated
> through the ~20 commits since (VL-D2 through VL-D20, the Real Voice
> Model Engine and Real ML Runtime Integration milestones, native-Windows
> hardening, and the Phase-3 Access-Gate Hardening milestone). §1, §5,
> and §7 below have been corrected where they were factually superseded;
> the rest of this document — including its numeric snapshots (§4) and
> historical git-state description (§2) — is preserved as an accurate
> record of *that* checkpoint, not of today. For current, authoritative
> status, see [`README.md`](README.md).

---

## 1. Roadmap

| Phase | Scope | Status |
|---|---|---|
| 0 | Foundation, architecture, safety, tooling | ✅ Complete |
| 1 | ML toolchain & environment engineering | ✅ `env-nemo` built and validated — real embedding provider verified (see `docs/REAL_ML_RUNTIME_INTEGRATION.md`); `env-whisperx`/`env-tts` remain not installed, approval-gated |
| 2 | Dataset pipeline (technical prep, speaker-agnostic) | ✅ Complete — implemented and tested against synthetic audio only |
| 3 | Speaker identity software architecture | ✅ Complete, including a real (non-synthetic) embedding provider verified end-to-end on synthetic audio (see `docs/REAL_ML_RUNTIME_INTEGRATION.md`). No real recording has ever been accessed by any provider. |
| 3.5 (implied) | Real-data enrollment decision, credential/licence sign-off | ⏳ Enrollment-methodology decision for the target speaker: **not started, owner decision required.** Embedding-provider licence has been researched and documented (NeMo `titanet_large`, NVIDIA NGC non-commercial research/evaluation terms); the `model_licence_reviewed` **gate attestation** itself is still a separate, unmade owner action (defaults `False`) — see §7 |
| 4 | Real dataset processing (requires the dataset access gate) | ⏳ Blocked on Phase 3.5 — see §7 for exactly which of the gate's 15 conditions remain unmet |
| 5+ | Voice model training/experiments, benchmarking | ⏳ Not started. Voice generation was explicitly evaluated and **deferred by direct user decision** (IndicF5 HuggingFace-gated; Piper not substituted without asking) — see `docs/REAL_ML_RUNTIME_INTEGRATION.md` |
| Desktop | Aarya Voice Lab desktop UI (VL-D0–D20) | ✅ Complete. VL-D0 through VL-D20 all shipped (21 milestones; see `README.md`'s Documentation table for the full list) — this row is far stale in earlier drafts of this file, which described only VL-D0–D2 as done. |

**Current phase: 3, complete — including a real, verified embedding
provider. Phase 4 is blocked on owner prerequisites only (§7), not on
any remaining engineering work.**

---

## 2. Git state

```
Branch:  claude/phase3-speaker-verification
Remote:  https://github.com/Kunal2662/Aarya-Voice-Lab
Working tree: clean (as of the commit containing this file)
```

Commit chain (linear, no rewrites). This file is committed by
`chore: add Phase 3 checkpoint`, one commit **after** the gap-closure
commit listed below — run `git log --oneline -6` on restore to see the
exact hash, since this file cannot name its own commit's hash in advance:

```
1fbfdf2  chore: initialize AARYA Voice Lab foundation           (Phase 0)
a9bfc2e  feat: establish voice lab ML toolchain                 (Phase 1)
f44574d  feat: implement dataset processing pipeline            (Phase 2)
9c25806  feat: implement speaker identity architecture          (Phase 3, synthetic-only)
84fb0e5  feat: close Phase 3 gaps against expanded spec          (Phase 3, gap closure)
<next>   chore: add Phase 3 checkpoint                           (this file)
```

### Remote status — READ THIS FIRST

As of this checkpoint, **GitHub has only**:
- `main` (the user's own init commit)
- `claude/aarya-voice-lab-foundation-kx265d` (Phase 0+1, pushed)

**`claude/phase2-dataset-pipeline` and `claude/phase3-speaker-verification`
are NOT on GitHub.** Every push attempt from this session returns:

```
fatal: unable to access '...': The requested URL returned error: 403
```

The Claude GitHub App has read-only access to this repo. This is not a
retry-able failure — it needs the repo owner to grant write access
(`claude.ai/admin-settings/claude-tag`) or to push the accompanying
`.bundle` file manually from their own machine. **A prior bundle
(`VoiceLab-Missing-Phase2-Phase3.bundle`) was already delivered to the
user for exactly this purpose** and its push flow was verified against a
real clone of the GitHub repo. This checkpoint's bundle supersedes it
(includes everything that one did, plus the gap-closure commit).

**On resuming:** check `git ls-remote --heads origin` before assuming
anything about remote state — it may have changed since this checkpoint
if the user pushed the earlier bundle manually.

---

## 3. Architecture summary

### Phase 0–2 (protected baseline — do not weaken)

- `src/aarya_voice_lab/pipeline/` — stage ordering, filesystem contracts,
  dataset pipeline (inventory → validation → normalization → quality →
  VAD → segmentation → overlap detection → candidate manifest →
  candidate_review). `SPEAKER_IDENTITY_BOUNDARY` marks where Phase 3
  begins; nothing before it may reason about speaker identity.
- `src/aarya_voice_lab/audio/` — file-type detection (content, not
  extension), stdlib WAV probing, pure-Python signal analysis, VAD.
- `src/aarya_voice_lab/security/speaker_policy.py` — the Phase 0
  eligibility policy (`decide_eligibility`). Phase 3's verification
  engine calls this rather than reimplementing it.
- `CandidateSegment` (pipeline/segmentation.py) has **no speaker field**
  by construction. `candidate_manifest.schema.json` has
  `additionalProperties: false` and rejects any speaker-identity key.

### Phase 3 (this checkpoint — software only)

All in `src/aarya_voice_lab/identity/`:

| Module | Role |
|---|---|
| `embeddings.py` | `EmbeddingProvider` ABC, `SyntheticEmbeddingProvider` (deterministic, no ML deps), `EmbeddingStore` (hash-verified, git-ignored, no export path) |
| `profile.py` | Versioned, immutable `SpeakerProfile`; supersession chain; `ProfileStore` |
| `enrollment.py` | Pluggable `EnrollmentStrategy` registry — `synthetic`, `direct_recording`, `human_anchored` shipped; none hard-coded as "the" production strategy |
| `calibration.py` | `CalibrationState` = `UNCALIBRATED` / `PROVISIONAL` / `CALIBRATED`; `CALIBRATED` is structurally unreachable for a synthetic provider and requires held-out evidence that does not exist for the target speaker |
| `verification.py` | `VerificationEngine` — rejection-first (operator checked before target); delegates eligibility to `security.speaker_policy`; `ELIGIBLE` + synthetic provider → forced to `SYNTHETIC_ONLY` |
| `review.py` | `IdentityReviewQueue`, separate from Phase 2's `candidate_review`; `promote_to_dataset()` refuses anything unreviewed, unheard, or synthetic |
| `audit.py` | Hash-chained append-only `AuditLog`; `verify_chain()` detects tampering |
| `contracts.py` | Read-only JSON contracts for the future desktop (profiles, enrollment status, review queue, calibration, provenance, pipeline status, embedding inventory) |
| `command_center.py` | **(gap-closure)** Claude Code Command Center backend: command catalogue with risk levels, repo context, changed-file stats (no diff content), sanitised activity feed, diagnostics. Executes nothing. |
| `runtime.py` | **(gap-closure, revised)** Vendor-neutral capability declarations — no GPU product named anywhere in Core |
| `preview.py` | VL-V0 contracts (`PreviewArtifact`, `PreviewFeedback`) — no generation implemented |
| `synthetic_e2e.py` | Full synthetic chain: audio → enrollment → profile → embedding → verification → review → (refused) promotion → audit |

New schemas: `enrollment_profile`, `verification`, `identity_review`,
`calibration` (all under `schemas/`).

New CLI (`src/aarya_voice_lab/cli/phase3.py`): `identity-status`,
`enrollment-strategies`, `calibration-status`, `runtime-capabilities`,
`identity-audit`, `embedding-inventory`, `embedding-delete`,
`synthetic-e2e`, `voice-preview-status`, `command-center`.

New data root directories (all git-ignored, verified behaviourally):
`data/embeddings/`, `data/enrollment/`, `data/audit/`.

---

## 4. Tests, lint, security

```
Full suite:         472 passed, 0 failed
Phase 0-2 (isolated): 327 passed
Phase 3 (identity + e2e + gaps): 145 passed
Ruff:                clean
```

*(Historical snapshot at this checkpoint's original commit. Current, as
of `HEAD bb8132e`: 808 passed, 0 failed, 5 skipped; ruff clean; verified
on native Windows — see `README.md`'s Testing section.)*

Security scan (this checkpoint):
- No secret patterns (`hf_*`, `sk-*`, `ghp_*`, AWS keys, PEM headers) in
  tracked content.
- No `.env`/`.pem`/`.key`/`.crt` files tracked.
- No audio/model/embedding files (`.wav`, `.mp3`, `.vec`, `.npy`, `.pt`,
  `.ckpt`, `.safetensors`) anywhere in the worktree.
- `data/` and `source/` contain only their README files.
- `.gitignore`: zero deletions across all three feature commits — only
  ever extended.
- AST-walked import scan: no `requests`/`boto3`/`google`/`azure`/etc. in
  `pipeline`, `identity`, `audio`, `core`, `security`.
- No GPU product name (RTX/GTX/Radeon/GeForce + number) anywhere in Core.

Synthetic E2E (`aarya-voice synthetic-e2e`) on this checkpoint:

```
profiles enrolled     : 2
verifications         : 6  (manual_review, rejected_low_similarity,
                             rejected_operator, rejected_overlap,
                             synthetic_only — full decision variety)
promoted to dataset   : 0
audit chain intact    : True
all results synthetic : True
real identity claims  : 0
```

Zero promotions and zero real identity claims are the **correct**
outcome — that's the synthetic-provenance guard working, not a failure.

---

## 5. Known limitations (everything still dependent on real data)

Stated plainly, per project convention — never claim more than is true:

1. **~~No real embedding provider exists.~~ Superseded — a real provider
   now exists.** The Real ML Runtime Integration milestone built and
   verified `identity.embeddings.LocalNeuralEmbeddingProvider` (NVIDIA
   NeMo `titanet_large`, via `.envs/env-nemo`) — see
   `docs/REAL_ML_RUNTIME_INTEGRATION.md`. `SyntheticEmbeddingProvider`
   is unchanged and still what every existing test and frontend runs
   against by default; the real provider is a second, honestly-labelled
   path alongside it. It has only ever embedded synthetic (sine-tone)
   audio — no real recording has been embedded by either provider. A
   secondary (independent) verification provider remains unchosen (item
   6 below), and the COMPATIBILITY.md / TOOLCHAIN.md NeMo/WhisperX
   isolation findings from Phase 1 still apply to that decision.
2. **The enrollment strategy for the target speaker is undecided.**
   `human_anchored` is implemented as an architecture and enforces its
   rules (human confirmation, `NO_OVERLAP_DETECTED`, `PASS` quality,
   minimum seed count) but has never been exercised against real seed
   segments, because there are none yet.
3. **`CALIBRATED` is unreachable for the target speaker by design**, not
   as a temporary gap — there is no held-out labelled set and cannot be
   one until real, labelled data exists that this project's own
   architecture forbids fabricating.
4. **No real audio has ever been embedded, enrolled, verified, or
   reviewed.** Every profile, score, and review in the test suite and
   the synthetic E2E is built from generated sine/harmonic waveforms.
5. **~~The dataset access gate has not been evaluated for Phase 3.~~
   Superseded — done.** The Phase-3 Access-Gate Hardening milestone
   (commit `80a23b8`) wired exactly the conditions this item named —
   operator enrollment presence, real embedding provider verification,
   and a model-licence-review attestation — into `dataset_gate.py`,
   bringing it from 12 to 15 conditions. This is a **mechanical/attestation
   gate only**: the operator-enrollment and real-provider checks read
   real state (and both would fail on a fresh checkout today, since no
   operator profile has been enrolled), and the licence-review, approval,
   and other attestations still default to `False` and are never
   inferred. Wiring the checks is complete; satisfying them (§7) is not.
6. **No secondary (independent) verification system is chosen.** The
   engine supports one, but nothing has been selected or installed.
7. **~~The desktop is partially built (VL-D0/D1 only).~~ Superseded —
   the full VL-D0 through VL-D20 series is complete.** See `README.md`'s
   Documentation table for all 21 entries. Desktop readiness now extends
   well beyond `command_center.py`/`contracts.py` — every workspace
   (dataset import/review, voice processing/preview/feedback, AI
   calibration, session persistence, and a series of live-data "bridge"
   milestones, VL-D10–D20) is implemented and tested. **What this item's
   original caveat still correctly implies stands, though:** the desktop
   renders real backend state honestly (including `NOT_CONFIGURED`/
   gated states) rather than executing anything itself — see
   `docs/PHASE3_IDENTITY.md`'s Command Center section for the
   no-execution-surface guarantee, which is unchanged.
8. **No FFmpeg on the development machine** — Phase 2's normalization
   success path (not just its BLOCKED path) remains unverified end-to-end.

---

## 6. Configuration / schema / documentation changes this checkpoint

- `schemas/`: 4 new files (unchanged from prior checkpoint) —
  `enrollment_profile`, `verification`, `identity_review`, `calibration`.
- `configs/default.yaml`: unchanged this commit.
- `.gitignore`: unchanged this commit (embeddings/enrollment/audit
  protection was added in `9c25806`, verified again here).
- `docs/PHASE3_IDENTITY.md`: two sections rewritten/added — hardware
  independence (corrected to match the vendor-neutral `runtime.py`
  reframe) and a new Command Center + local-first section.
- `src/aarya_voice_lab/identity/runtime.py`: `ComputeBackend` gained
  `ROCM`, `OPENCL`, `VULKAN`, `OTHER`; docstring reframed away from
  RTX-3050-as-target language per explicit spec instruction.

---

## 7. Next-phase requirements (before real-data work)

### Current status of each item (reconciliation pass, `HEAD bb8132e`)

| # | Requirement | Status |
|---|---|---|
| 1 | Push this bundle / grant GitHub write access | ✅ **Done — superseded.** This branch has been pushing directly to `origin` throughout the current session; the bundle-recovery situation this item describes no longer applies. |
| 2 | Decide the enrollment approach for the target speaker | ⏳ **Still open — owner decision required.** No code change resolves this; it remains "an architectural decision for the repo owner, not something to default." |
| 3 | Choose and licence-check a real embedding provider | ✅ **Done.** NVIDIA NeMo `titanet_large` chosen, built (`.envs/env-nemo`), and licence-documented (NGC non-commercial research/evaluation terms) — see `docs/REAL_ML_RUNTIME_INTEGRATION.md`. A **secondary** provider (different model family) remains unchosen. The `model_licence_reviewed` **gate attestation** is a separate owner action, still not given (defaults `False`) — documenting the licence is not the same as attesting it through the gate, and this file does not mark that attestation complete. |
| 4 | Wire Phase 3-specific conditions into `dataset_gate.py` | ✅ **Done.** The Phase-3 Access-Gate Hardening milestone (commit `80a23b8`) added the three conditions this item named — operator enrollment presence, real embedding provider verification, model-licence-review attestation — bringing the gate to 15 conditions total. |
| 5 | Record an operator enrollment sample | ⏳ **Still open — owner action required.** No usable operator-role profile exists in the profile store on any checkout audited this session; `dataset_gate.py`'s "operator enrollment present" condition reads this directly and would fail today. |
| 6 | Begin Phase 4 only after 1–5 | ⏳ **Blocked on items 2 and 5 only** — 1, 3, and 4 are done. Every other `dataset_gate.py` condition (explicit approval, `phase2_complete`, `tests_passing`, `security_scan_clean`, `processing_config_reviewed`, `model_licence_reviewed`) is a pure operator attestation, "cannot be self-satisfied" by design. None has been fabricated, defaulted, or marked complete by this reconciliation. |

The original numbered list is preserved below for history — its text is
unchanged from when it was written; read it alongside the table above,
not in place of it.

### Original list (unchanged, priority order as originally written)

1. **Push this bundle** (or grant GitHub App write access) so Phase 2
   and Phase 3 are recoverable from GitHub, not only from bundles.
2. **Decide the enrollment approach for the target speaker.** The
   circularity problem (her only recordings are the ones being
   labelled) was analysed in the Phase 3 readiness report; the
   recommended resolution is a human-anchored seed with rejection-first
   matching against a directly-recorded operator profile. This is an
   architectural decision for the repo owner, not something to default.
3. **Choose and licence-check a real embedding provider** (and, if used,
   a secondary one from a different model family — co-installing NeMo
   and WhisperX-family stacks was shown in Phase 1 to silently downgrade
   versions rather than fail cleanly, so keep them in separate
   environments).
4. **Wire Phase 3-specific conditions into `dataset_gate.py`** — the
   Phase 2 gate does not yet check operator enrollment, embedding
   storage verification, or model licence review.
5. **Record an operator enrollment sample** (needed regardless of which
   embedding provider is chosen, since rejection-first matching needs
   it).
6. Only after 1–5: begin Phase 4 (real dataset processing), starting
   with the single-recording validation run the project's own rules
   require before any bulk run.

---

## 8. Continuation instructions for a fresh session

```bash
# 1. Restore from the bundle
git clone VoiceLab-Phase3-Complete.bundle Aarya-Voice-Lab
cd Aarya-Voice-Lab
git checkout claude/phase3-speaker-verification

# 2. Point at the real remote and check its actual state
git remote set-url origin https://github.com/Kunal2662/Aarya-Voice-Lab.git
git ls-remote --heads origin   # do NOT assume the checkpoint's remote status is current

# 3. Verify the checkpoint is accurate
git log --oneline -6           # this checkpoint's own commit is now ~20 commits behind HEAD, not at HEAD — see the reconciliation note near the top of this file
python -m pytest -q            # 472 passed at this checkpoint's original writing; 808 passed, 0 failed, 5 skipped as of HEAD bb8132e (see README.md)
ruff check .                   # expect clean
aarya-voice synthetic-e2e      # expect 0 promotions, 0 real identity claims

# 4. Read this file's §5 (limitations) and §7 (next steps) before
#    doing anything else. Do not assume Phase 3 is "done" beyond
#    "software architecture complete, synthetic-only" — it is.
```

If `git log` or `pytest` disagree with this document, trust them, not
this file — re-derive the state and update this checkpoint before
proceeding.

**Do not, in any continuation:**
- access, copy, or reference the real 31 recordings without the dataset
  gate returning `access_allowed: true` including explicit human
  approval (which cannot be attested by the agent itself);
- weaken `SPEAKER_IDENTITY_BOUNDARY`, merge `candidate_review` with
  `manual_review`, or add a speaker field to `CandidateSegment`;
- represent a `PROVISIONAL` calibration as `CALIBRATED`;
- introduce a cloud storage or cloud API dependency;
- hard-code a specific GPU vendor or product into a Core interface.
