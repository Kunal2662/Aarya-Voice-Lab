# 31-Recording Dataset Audit &amp; Training Readiness

**Result: the audit could not proceed past the access-gate check.** The
31 source recordings this milestone was asked to assess are not present
anywhere on this machine — this document records what was checked, what
that check found, and exactly what would need to happen before a real
audit (and, much later, an actual training run) becomes possible. No
recordings were accessed, read, copied, or modified, because none could
be located.

See also: [`docs/DATASET_PIPELINE.md`](DATASET_PIPELINE.md) (the
canonical ingestion path this audit would have used),
[`docs/PRIVACY.md`](PRIVACY.md) (the ethical/legal framing this dataset
is governed by), [`docs/REAL_VOICE_MODEL_ENGINE.md`](REAL_VOICE_MODEL_ENGINE.md)
(training architecture), and
[`pipeline/dataset_gate.py`](../src/aarya_voice_lab/pipeline/dataset_gate.py)
(the access gate this document reports the real, current state of).

## What was checked

1. **The canonical location**: `data/source/` (resolved by
   `core.data_root.DataRoot.default().source`, the path every stage in
   the pipeline — inventory, validation, normalization, quality
   analysis, segmentation — reads from). This directory **does not
   exist**. `data/` currently contains only its tracked `README.md`.
2. **A second, older-looking location**: the top-level `source/`
   directory (with its own `README.md`, dated to Phase 0's original
   design). This exists but is **empty** — its own README states it is
   "currently empty and intentionally left that way." This is not the
   path any current code reads; it appears to predate `data/source/`
   becoming the code-canonical location.
3. **Common personal directories on this machine** (`Downloads`,
   `Documents`, `Desktop`, `Music`) — checked for audio files by
   filename only, nothing opened or read. No coherent set of 31
   recordings was found. `Downloads` contains: this project's own
   earlier diagnostic WAV outputs (IndicF5 generation tests from
   Milestones 1–4), a small number of unrelated third-party
   voice-clone samples (ElevenLabs test outputs, a different name), and
   two or three music downloads. None of this constitutes the 31-file
   dataset this milestone describes, and none of it was treated as
   such.
4. **The real, current state of the access gate itself** — run for
   real (`aarya-voice dataset-gate`), which is safe and read-only (it
   inspects Git state, configuration, and directory protection; it
   never reads audio):

   ```
   RESULT: ACCESS DENIED — 9 condition(s) unsatisfied.
   ```

   | Condition | Status | Detail |
   |---|---|---|
   | Phase 0/1 history pushed | PASS | HEAD present on origin |
   | working tree clean | PASS | clean |
   | Phase 2 implementation complete | **FAIL** | attested by operator |
   | Phase 2 tests passing | **FAIL** | attested by operator |
   | security scan complete | **FAIL** | attested by operator |
   | source protection verified | PASS | no protected material tracked |
   | output directories git-ignored | PASS | all `data/` paths ignored |
   | no cloud upload path | PASS | no network client in the pipeline |
   | offline/telemetry protections intact | PASS | stage subprocesses default offline |
   | processing configuration reviewed | **FAIL** | attested by operator |
   | explicit approval to access recordings | **FAIL** | not granted — cannot be self-satisfied |
   | operator enrollment present | **FAIL** | no usable operator-role profile in the profile store |
   | real embedding provider verified | **FAIL** | no real embedding provider installed |
   | model licence reviewed | **FAIL** | attested by operator |
   | source directory populated | **FAIL** | no source recordings present |

## Why the audit stops here

Every later phase this milestone specifies — mechanical quality
measurement, suitability assessment, transcript inventory, training
resource estimation, a proposed split — requires real, measured values
from the actual audio. `pipeline.training_readiness.TrainingReadinessInput`
(the module built specifically for this kind of assessment) states its
own contract directly: *"Every field here must trace back to a real
measurement — this dataclass performs no computation of its own."*
There is nothing to measure. Producing numbers anyway would mean
inventing them, which this milestone's own instructions explicitly
prohibit and which this project's engineering practice throughout has
consistently refused to do for exactly this reason.

## The ethical/authorization context (from `docs/PRIVACY.md`, restated
## accurately, not elaborated on)

This project's own privacy documentation states that the target speaker
is deceased and cannot consent to new uses of her voice, and that the
project's authorization is narrow and personal. That means the
"consent" question this milestone's Phase 9 asks about is not — and can
never be — the speaker's own consent. It is whoever holds the authority
to authorize this narrow, personal use on her behalf. `dataset_gate.py`
already reflects this correctly: "explicit approval" is a pure human
attestation the code cannot infer, default, or derive from file
presence — by design, not by omission. No consent or authorization
metadata was invented or assumed here; none exists to invent, and none
should be inferred from anything technical.

## Minimum required action to make the recordings accessible

In order, since later steps depend on earlier ones:

1. **Place the 31 recordings under `data/source/`** (create the
   directory; it does not exist yet), ideally as a named batch
   (`data/source/batch-001/`, per the existing batch convention — "new
   recordings are added as a new batch with no reprocessing and no
   code changes").
2. **Attest the six operator-attestation gate conditions** that are
   currently unsatisfied (Phase 2 implementation complete, Phase 2
   tests passing, security scan complete, processing configuration
   reviewed, model licence reviewed, and — the one that matters most —
   explicit approval to access the recordings). These are deliberate
   human decisions, not something this session can supply on its own
   behalf.
3. **Resolve the two Phase-3 prerequisites** the Access-Gate Hardening
   milestone added: a usable operator-role enrollment in the profile
   store, and a real (non-synthetic) embedding provider installed and
   loadable.
4. Only then does `aarya-voice dataset-gate` return `ACCESS ALLOWED`,
   and only then should the canonical pipeline
   (`aarya-voice inventory` → `validate-audio` → `analyze-quality` →
   `segment`, per `docs/DATASET_PIPELINE.md`) run — starting with a
   single recording first, exactly as that document specifies, not the
   full batch at once.

## What is already built and waiting, unmodified by this audit

Nothing new was written or changed as part of this milestone. The
following already exist, were reviewed (not modified), and would
receive the real measurements once the recordings are accessible:

- **Ingestion/quality pipeline**: `pipeline/dataset.py`,
  `pipeline/quality.py`, `audio/analysis.py` — measurement and
  judgement deliberately separated (see `docs/DATASET_PIPELINE.md`).
- **Training readiness aggregation**: `pipeline/training_readiness.py`
  — configurable thresholds already defined in `configs/default.yaml`'s
  `training_readiness` section (minimum sample count 20, minimum total
  duration 300 s, minimum average duration 2.0 s, required sample rate
  16 kHz/mono, max clipping ratio 1%, max silence ratio 50%, minimum
  SNR 15 dB) — a floor, not a ceiling; a real `TrainingProvider` may
  require more.
- **Train/validation/test split**: `pipeline/dataset_split.py` — two
  explicit strategies (`SAME_SPEAKER`, the relevant one for a
  single-target-speaker private voice; `HELD_OUT_SPEAKER`, for
  multi-speaker public corpora), deterministic seeded partitioning, no
  record ever silently dropped.
- **Access governance**: `pipeline/dataset_gate.py` (evaluated above,
  live).
- **Package format** (for later, once a model actually exists):
  `docs/VOICE_PACKAGE_SPEC.md`, `pipeline/model_manager.py` — installs
  an already-built `.arya-voice` package; does not build one.

None of this was touched. There is no concrete dataset/training-related
dependency in what was found that requires modifying the installer or
any other already-hardened system, so nothing outside this document was
changed.

## Training readiness status

**INSUFFICIENT DATA.** Not `BLOCKED` in the sense of "data exists but
access is refused" — the recordings themselves were not found anywhere
reasonable to look. Every downstream question this milestone asks
(quality classification, suitability, transcript strategy, RTX 3050
feasibility, a training plan, a split) is unanswerable until real
recordings exist at `data/source/` and the access gate is passed for
real, by a person, not by this session.
