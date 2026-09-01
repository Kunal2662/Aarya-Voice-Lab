# Dataset Software Readiness — is the pipeline ready to receive the 31 recordings?

A software-only audit: whether Aarya Voice Lab's dataset pipeline is
ready to accept and process the user's 31 recordings **without the
recordings ever being present on, or copied to, the development
machine**. The recordings stay on the user's own RTX 3050 laptop, under
the user's own control, at all times. Nothing here searched for them,
required them, or fabricated any measurement about them — every claim
below is either read from the existing code or tested live against a
single synthetic (silent-tone) WAV file created solely for this audit
and deleted immediately after, never a real recording.

See also: [`docs/DATASET_PIPELINE.md`](DATASET_PIPELINE.md) (the
canonical pipeline this audit verified, now updated with the corrected
workflow this audit's findings prompted),
[`docs/DATASET_31_RECORDING_AUDIT.md`](DATASET_31_RECORDING_AUDIT.md)
(the prior, data-focused audit attempt — corrected by this one),
[`docs/PRIVACY.md`](PRIVACY.md), and
[`docs/REAL_VOICE_MODEL_ENGINE.md`](REAL_VOICE_MODEL_ENGINE.md).

## 1. Current dataset architecture (map)

```
Private-recording track (this document)          Public-dataset track (separate, unrelated)
────────────────────────────────────────          ──────────────────────────────────────────
<user's own directory, anywhere>                   registry/dataset_registry.py
  ↓ inventory (pipeline/inventory.py)                (public_datasets/registry.jsonl)
  ↓ validate-audio (pipeline/validation.py)         pipeline/dataset_adapter.py
  ↓ analyze-quality (pipeline/quality.py,            (DatasetAdapter -> NormalizedRecord)
    audio/analysis.py)                             pipeline/training_manifest.py
  ↓ segment (pipeline/dataset.py, stages.py)          (NormalizedRecord -> TrainingManifest)
  ↓ candidate manifest (data/manifests/)            pipeline/training_readiness.py
━━━━━━━ speaker-identity boundary ━━━━━━━            (aggregates real measurements only)
  → Phase 3: identity/ (speaker verification,
    embeddings, enrollment)
  → [gap -- see §7] would need to reach:
    training_manifest.py / training_readiness.py
```

`pipeline/dataset_gate.py` governs *access* to the private track at
every point along the left column; it does not appear in, and is not
needed by, the public-dataset track on the right (that track's own
governance is `docs/DATA_POLICY.md` + `registry/dataset_registry.py`).
`registry/dataset_registry.py`'s own docstring states this exclusion
explicitly: it "must never be used to record... consented real-person
(target-speaker) data."

## 2. Where end-user recordings are expected

**Not required to be anywhere in particular, and specifically not
required to be on this development machine or inside this
repository.** Confirmed by reading `pipeline/inventory.py`'s
`require_synthetic_or_approved()`: it restricts exactly two directories
(`source/` at the repo root, `data/source/`) and imposes no restriction
on any other path. `data/source/` is a documented *convention* for a
user who wants recordings tracked in the project's own layout — it is
not the only place the software can read from. This distinction was not
clearly stated in the pipeline documentation before this audit (see §9)
and has now been added.

## 3. How the user should import/provide recordings

**No copy, no upload, no import step — point the tool at the folder.**
Live-tested this session, against one synthetic WAV placed in a
directory outside the repository entirely (a scratch location, deleted
immediately after the test; the real recordings were never involved):

```bash
aarya-voice inventory       "<path to the user's own recordings folder>" --approved
aarya-voice validate-audio  "<same path>" --approved
aarya-voice analyze-quality "<same path>" --approved
aarya-voice segment         "<same path>" --approved --dry-run   # inspect first
aarya-voice dataset-report  "<same path>" --approved
```

All four commands ran successfully against the external directory in
this session's live test. `inventory`/`validate-audio` succeeded even
*without* `--approved` (the flag is not required outside the two
protected roots) — `--approved` is still recommended for every real run
because it is what marks resulting records as real data
(`is_synthetic: false`) rather than a test fixture, independent of
where the files are. Confirmed the source directory was byte-for-byte
unchanged after every command, including a real (non-dry-run)
`validate-audio`/`analyze-quality`/`segment --dry-run` sequence — every
stage's derived output (manifests, reports) lands under this project's
own `data/` tree, never back into the source location, regardless of
where that location is. On the RTX 3050 laptop this means: the 31
recordings can stay exactly where the user already keeps them (their
own drive, their own folder), and Aarya Voice Lab reads them in place.

## 4. Dataset Gate readiness

**Real and working**, re-run this session for current confirmation
(unchanged from the prior audit, since nothing about the gate itself
was touched): `aarya-voice dataset-gate` — read-only, inspects Git
state/configuration/directory protection, never reads audio — reports
9 of 15 conditions unsatisfied right now on this development machine
(operator attestations, explicit approval, operator enrollment, a real
embedding provider, source directory populated). This is expected and
correct for a machine that is not where the recordings will actually be
processed. **The gate is a deliberate, separate human checklist, not
something any Phase-2 CLI command enforces automatically** — confirmed
by reading `pipeline/dataset.py` (no reference to `dataset_gate`
anywhere in the actual pipeline orchestration). This matches the
project's own stated philosophy ("explicit approval cannot be
self-satisfied" — a human must consciously run and heed the checklist)
and is not treated here as a defect, though it does mean the checklist
is advisory unless a user actually runs it.

## 5. Audio audit readiness

**Ready, confirmed live.** `inventory` → `validate-audio` →
`analyze-quality` → `segment` all executed successfully against a real
(if synthetic) audio file from an external directory this session,
producing an honest, non-fabricated result at every stage (the crude
sine-wave test tone was correctly flagged `REVIEW`/`low_snr` by quality
analysis — the pipeline did not pretend it was good speech). No code
changes were required for this path; it already works as documented.

## 6. Transcript workflow readiness

**No transcription stage exists in the canonical private-recording
pipeline**, confirmed against `docs/DATASET_PIPELINE.md`'s own stage
list (inventory → validation → normalization → quality → speech/silence
→ segmentation → overlap → candidate manifest → candidate review — no
transcription stage) and by grep: no module under `pipeline/` performs
transcription for this track. `env-whisperx` exists as a separate,
gated environment (`scripts/install_env.sh env-whisperx` requires
`--i-have-approval`, per `docs/WHISPERX.md`) for a **real, unresolved**
reason: it transitively installs `pyannote.audio`, a gated model
requiring a contact-sharing agreement — not something to route around
casually. **Per this milestone's own instruction, WhisperX was not run.**
Training-manifest eligibility (`pipeline/training_manifest.py`) already
excludes any record with no transcript, so the absence of a
transcription stage is *safely* absent — it fails closed, not open.
This remains a real, not-yet-designed piece of the eventual training
path; nothing about it was decided or implemented here.

## 7. Training-readiness workflow readiness

**A real gap, found and documented, not implemented.**
`pipeline/training_manifest.py` (which builds the `eligible_record_ids`
that `pipeline/dataset_split.py` and `pipeline/training_readiness.py`
consume) only accepts `NormalizedRecord` instances — and the only thing
that produces those is `pipeline/dataset_adapter.py`'s `DatasetAdapter`,
whose own docstring says it normalizes "a **public**/third-party
dataset's own record format." Confirmed by grep: no adapter, and
neither `dataset_adapter.py` nor `training_manifest.py`, references the
private pipeline's own `candidate_manifest`/`CandidateSegment` output
at all. **There is currently no bridge from "Phase 2's own deliverable
for the private track" to "what the training-readiness machinery
consumes."**

This was not built during this audit, for three reasons, matching this
milestone's explicit instruction not to implement a large new subsystem
without authorization:

1. The correct shape depends on a decision not yet made: how a
   `CandidateSegment` (which by design carries no speaker field — Phase
   2 makes no speaker claim) combines with Phase 3's speaker-verified
   subset and a future transcript to become one `NormalizedRecord`. That
   is a real design question, not a mechanical wiring task.
2. Every record would be excluded immediately anyway (§6 — no
   transcripts exist yet), so building the bridge now could not be
   exercised or validated against anything real.
3. This project's own established practice throughout every milestone
   this session has been to not build ahead of real, present need.

**Proposed smallest fix, for a later, authorized milestone**: a
`PrivateRecordingAdapter(DatasetAdapter)` that reads a batch's
`candidate_manifest.json` plus the corresponding Phase-3 speaker-
verification result and a transcript source (once one exists), and
yields `NormalizedRecord`s — reusing the existing `DatasetAdapter`
contract exactly as built, adding one new adapter, not a new subsystem.

**Also found, same section, same disposition (documented, not
fixed)**: `pipeline.training.LocalTrainingProvider` detects training
capability via `importlib.metadata` **in whatever interpreter calls
it** — with no subprocess isolation (confirmed: `training.py` states
outright it depends "never on a subprocess"). Every other ML-capability
check in this project (environment verification, IndicF5 generation)
deliberately runs in a *separate*, ML-enabled interpreter precisely
because the base interpreter this CLI normally runs under is kept free
of `torch`/`nemo_toolkit` by design. `LocalTrainingProvider`, checked
from the base interpreter, will therefore always report
`NOT_CONFIGURED` even now that `env-tts` genuinely has PyTorch
installed and verified working — not because training is truly
unavailable, but because the check is architecturally looking in the
wrong interpreter. This is a real inconsistency with the project's own
established subprocess-isolation pattern, adjacent to training
infrastructure, and left for deliberate design authorization rather
than fixed here.

## 8. Privacy/security behavior

Confirmed, live: no recordings were uploaded anywhere (none exist on
this machine to upload); the synthetic test file never left the local
disk; the source directory was verified byte-identical before and
after every pipeline command; `data/` after the entire test still
contains only its tracked `README.md`. `docs/DATASET_PIPELINE.md`'s own
stated guarantees (no network client anywhere in the pipeline, stage
subprocesses default offline, manifests store relative paths only) were
not modified and were not contradicted by anything found.

## 9. Missing software capabilities

1. **Documentation clarity** (fixed this session — see §10): the
   pipeline already supported reading from an arbitrary, user-controlled
   directory, but this was not clearly documented, and the prior audit
   session's own report fell into exactly the resulting misunderstanding.
2. **Private-recording-to-training-manifest bridge** (documented, not
   implemented — §7): a `PrivateRecordingAdapter` proposal is recorded
   for a future, explicitly authorized milestone.
3. **`LocalTrainingProvider` subprocess isolation** (documented, not
   implemented — §7): a real architectural inconsistency, adjacent to
   training infrastructure, left for deliberate authorization.

No other gap was found in the parts of the pipeline this audit
exercised (inventory, validation, quality analysis, segmentation,
dataset-gate).

## 10. Required code changes

**One, documentation-only, already made**: `docs/DATASET_PIPELINE.md`
gained an explicit "Recordings do not have to live under `data/source/`"
section with the corrected, tested workflow;
`docs/DATASET_31_RECORDING_AUDIT.md` received a correcting note.
**No pipeline code was changed** — the capability this audit needed
already existed and worked correctly; the gap was in what the
documentation said, not in what the software did. The two gaps in §7
were deliberately left as documented proposals, not implementations,
per this milestone's explicit instruction.
