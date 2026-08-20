# AARYA Voice Lab — Phase 3 Checkpoint

**Purpose of this file:** recover and continue this project from a fresh
Claude Code session with no prior context. It is bundled with the Git
history at `VoiceLab-Phase3-Complete.bundle`. This file is a checkpoint,
not a replacement for the repository — the bundle's Git history is the
source of truth; this document is the map.

Generated: see `Generated at` in the final report accompanying this
checkpoint. Do not treat this file's contents as current if it is old —
re-run `git log` and `pytest` before trusting anything below.

---

## 1. Roadmap

| Phase | Scope | Status |
|---|---|---|
| 0 | Foundation, architecture, safety, tooling | ✅ Complete |
| 1 | ML toolchain & environment engineering (specs, no install) | ✅ Complete |
| 2 | Dataset pipeline (technical prep, speaker-agnostic) | ✅ Complete |
| 3 | Speaker identity software architecture (synthetic-only) | ✅ Complete (software) |
| 3.5 (implied) | Real-data enrollment decision, credential/licence sign-off | ⏳ Not started — see §7 |
| 4 | Real dataset processing (requires the dataset access gate) | ⏳ Blocked on Phase 3.5 |
| 5+ | Voice model training/experiments, benchmarking | ⏳ Not started |
| Desktop | Aarya Voice Lab desktop UI (VL-D0–D20) | 🔶 VL-D0 (design system) + VL-D1 (Command Center + operational workspace) complete — see docs/VLD1_COMMAND_CENTER.md. VL-D2+ not started. |

**Current phase: 3, complete (software only).**

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

1. **No real embedding provider exists.** Only `SyntheticEmbeddingProvider`
   (arithmetic over waveform shape) is implemented. A real provider
   (TitaNet, WeSpeaker, etc.) requires a model decision — see the
   COMPATIBILITY.md / TOOLCHAIN.md research from Phase 1 for the
   NeMo/WhisperX isolation findings that still apply.
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
5. **The dataset access gate (`aarya-voice dataset-gate`) has not been
   evaluated for Phase 3** — Phase 2's gate conditions are unchanged;
   Phase 3 identity-specific gate conditions (operator enrollment
   recorded, embedding storage verified, model licences reviewed,
   reviewer availability) were specified in the Phase 3 readiness report
   but are not yet wired into `dataset_gate.py`.
6. **No secondary (independent) verification system is chosen.** The
   engine supports one, but nothing has been selected or installed.
7. **The desktop is partially built.** VL-D0 (design system) and VL-D1
   (Command Center + operational workspace, synthetic data only) exist —
   see docs/VLD0_DESIGN_SYSTEM.md and docs/VLD1_COMMAND_CENTER.md.
   VL-D2 onward (real import, real pipeline execution, a real Claude
   execution transport) does not exist yet.
   `command_center.py` and `contracts.py` are the full extent of desktop
   readiness.
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

In priority order:

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
git log --oneline -6           # expect the "add Phase 3 checkpoint" commit at HEAD
python -m pytest -q            # expect 472 passed
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
