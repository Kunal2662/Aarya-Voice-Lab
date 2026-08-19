# Dataset Pipeline

> **PLANNED — no stage is implemented.** Phase 0 defines the stage
> ordering, the record schema each stage reads and writes, and the safety
> policy applied at the verification step. No stage has been run against
> the private recordings.
>
> The CLI commands named below exist but deliberately refuse to execute,
> exiting non-zero with a PLANNED notice.

## The pipeline

```
SOURCE
  ↓  Inventory                  catalogue recordings; no audio modified
  ↓  Speaker Diarization        who spoke when (recording-local labels)
  ↓  Speaker Identification     map local labels → target / operator / unknown
  ↓  Overlap Detection          find simultaneous speech
  ↓  Candidate Extraction       cut candidate segments
  ↓  Quality Filtering          SNR, clipping, silence, duration
  ↓  Transcription              text per segment (mostly Marathi)
  ↓  Word Alignment             word/phoneme timings
  ↓  Speaker Verification       independent second-system check
  ↓  Manual Review              human approve / reject / ambiguous
  ↓  VERIFIED DATASET
  ↓  Voice Model Experiments
  ↓  Fidelity Benchmark
  ↓  PRODUCTION VOICE MODEL
```

Canonical ordering lives in
[`pipeline/stages.py`](../src/aarya_voice_lab/pipeline/stages.py) so code,
docs, and tests can't drift apart.

## Stage notes

**Inventory** — Catalogue the 31 recordings: ID, duration, format, sample
rate, checksum. Originals are opened read-only and never modified.
Assigns the stable `source_file_id` every later record references.

**Speaker Diarization** — Primary system: NeMo Sortformer. Produces
recording-local labels (`spk_0`, `spk_1`) that are **meaningless across
files** — see [SECURITY.md](SECURITY.md).

**Speaker Identification** — Maps local labels to real roles by verifying
against a reference sample, never by label number, filename, or pitch.

**Overlap Detection** — Simultaneous speech is unusable for voice
training: it would teach the model the operator's voice mixed with the
target's. Rejected by default.

**Candidate Extraction** — Cuts candidate segments into new derived
files. Originals untouched. Every segment records its source timestamps.

**Quality Filtering** — SNR, clipping, silence ratio, duration bounds.
Relevant to a stated goal: the Private Voice must sound like a natural
person, **not a telephone/call recording**. Source material recorded over
a call carries band-limiting and codec artifacts that a model will
faithfully reproduce, so quality filtering and any restoration strategy
matter as much as quantity here. *(Whether restoration is viable is an
open question for a later phase — it cannot be answered without listening
to the material, which Phase 0 does not do.)*

**Transcription** — Mostly Marathi, possibly with Hindi/English
code-switching. ASR quality for Marathi is materially worse than for
English; expect transcripts to need correction at manual review.

**Word Alignment** — Word/phoneme-level timings for TTS training.

**Speaker Verification** — The independent second system. Combined with
the primary result to produce the HIGH/MEDIUM/LOW classification driving
[`decide_eligibility()`](../src/aarya_voice_lab/security/speaker_policy.py).

**Manual Review** — A human listens and makes the final call. Data model
in [`review.py`](../src/aarya_voice_lab/review.py); the reviewer sees
transcript, timestamps, speaker assignment, and confidence.
**Automated confidence never substitutes for this step.**

**Verified Dataset** — Only segments that are both automatically eligible
and human-approved. Versioned; never committed to Git.

## Reproducibility

Each stage reads and writes records conforming to
[`segment.schema.json`](../schemas/segment.schema.json). Stages
communicate through **files, not function calls** — a design forced by
NeMo and WhisperX pinning incompatible PyTorch versions
([ENVIRONMENT.md](ENVIRONMENT.md)), and useful anyway: each stage is
independently resumable and inspectable, and `processing_version` on
every record identifies the code that produced it.

## Safety properties

1. **No stage runs without an explicit operation.** Future commands can't
   be triggered incidentally; they refuse to run today.
2. **Originals are read-only** at every stage.
3. **Rejection is the default** for anything uncertain.
4. **Nothing leaves the machine** — no stage uploads audio or transcripts.
5. **Manual review is mandatory** before a segment reaches the dataset.

## Scale expectation

31 recordings, split between two speakers, minus overlap, minus quality
rejections, minus review rejections. The usable target-speaker material
will be **a fraction of the total runtime** — likely well under an hour.

This shapes the model strategy: few-shot / reference-based voice cloning
is far more plausible than training from scratch, which typically needs
many hours of clean single-speaker audio. See
[MODEL_STRATEGY.md](MODEL_STRATEGY.md). The exact yield is unknown and
unknowable until the recordings are actually processed in an approved
phase — do not plan around an assumed number.
