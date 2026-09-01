# Dataset Pipeline

> ## Phase 2 does not determine speaker identity.
>
> This pipeline prepares audio: it validates, measures, segments, and
> flags. It produces **candidate segments** described by time span,
> quality, and possible overlap. It makes **no claim about who is
> speaking**, and its data structures are built so it cannot.
>
> Speaker identity is decided in **Phase 3**.

**Implemented and tested against synthetic audio only.** The 31 private
recordings have not been accessed, read, or copied.

---

## Stages

```
SOURCE                          read-only originals
  ↓ INVENTORY                   catalogue, hash, detect duplicates/corruption
  ↓ AUDIO VALIDATION            VALID / WARNING / INVALID / BLOCKED
  ↓ NORMALIZATION               derived copies only (requires FFmpeg)
  ↓ QUALITY ANALYSIS            measure, then decide (separately)
  ↓ SPEECH / SILENCE ANALYSIS   activity regions, natural pauses preserved
  ↓ SEGMENTATION                deterministic candidate spans
  ↓ OVERLAP CANDIDATE DETECTION possible overlap flagged, never resolved
  ↓ CANDIDATE MANIFEST          the Phase 2 deliverable
  ↓ CANDIDATE REVIEW            technical triage by a human
━━━━━━━━ speaker-identity boundary ━━━━━━━━
  → PHASE 3: SPEAKER VERIFICATION & SAFETY
```

Canonical ordering: [`pipeline/stages.py`](../src/aarya_voice_lab/pipeline/stages.py).

### A correction from Phase 0

Phase 0 ordered `speaker_diarization` immediately after `inventory`,
placing every speaker-related stage *before* quality analysis and
segmentation. Phase 2 reordered it: all technical preparation happens
first, and `SPEAKER_IDENTITY_BOUNDARY` marks where Phase 3 begins. Three
tests enforce that every Phase 2 stage precedes that boundary.

### Two review stages, deliberately

| Stage | Phase | Reviewer is asked |
|---|---|---|
| `candidate_review` | 2 | Is this audio technically usable? |
| `manual_review` | 3 | Is this the target speaker? |

They are separate stages because collapsing them would put a speaker
question in front of a Phase 2 reviewer. Every Phase 2 review item
carries `asks_about_speaker_identity: false`, asserted by test.

---

## Stage detail

### Inventory

Catalogues every audio file: size, SHA-256, detected container, and
properties where readable.

- **Container detected from content**, never the extension. A recording
  handed over as `.wav` that is really an MP3 is identified correctly and
  the mismatch is recorded. A file with a *missing* extension is still
  inventoried — dropping it would silently lose a recording.
- **`source_file_id` is content-addressed** (`src-<hash prefix>`), so a
  file keeps its identity across renames, machines, and runs. This is
  what makes the stage deterministic.
- Detects **duplicate content** (by hash, regardless of filename),
  zero-byte files, unreadable files, and unsupported formats.
- **Never modifies, moves, or renames** anything.

### Audio validation

| Status | Meaning |
|---|---|
| `VALID` | Usable as-is |
| `WARNING` | Usable; something needs attention |
| `INVALID` | Not usable — corrupt, empty, unrecognised |
| `BLOCKED` | **Cannot be determined here** — a capability is missing |

`BLOCKED` is distinct from `INVALID` on purpose: "we cannot inspect this
without FFmpeg" must never be recorded as "this file is bad". Nothing is
converted or repaired — a failing file is reported, not fixed.

**Telephone recordings are expected input.** Low sample rate produces a
`low_sample_rate` *warning*, never a rejection.

### Normalization

Writes a **new** file to `data/working/`. The original is opened
read-only and re-hashed afterwards to confirm it is byte-identical.

| Setting | Default | Why |
|---|---|---|
| Sample rate | 16 kHz | What NeMo/Sortformer diarization and speaker-verification models expect |
| Channels | mono | Those models operate on one channel; mixing is deterministic |
| Bit depth | 16-bit PCM | Lossless for analysis, universally readable |
| Loudness normalization | **off** | Level is *evidence*; normalizing it away would erase what quality analysis measures |

Note that TTS training generally prefers 22.05/24 kHz. The normalized
copy serves *analysis*; a separate derivation should serve TTS later —
which is precisely why the original is preserved untouched.

**Without FFmpeg the stage is BLOCKED**, the original is left alone, and
no substitute tool is used.

### Quality analysis — measurement and decision are separate

[`audio/analysis.py`](../src/aarya_voice_lab/audio/analysis.py) **only
measures**: peak, RMS, dBFS, crest factor, clipping ratio, DC offset,
zero-crossing rate, noise floor, estimated SNR, silent-frame ratio. It
contains no thresholds.

[`pipeline/quality.py`](../src/aarya_voice_lab/pipeline/quality.py)
turns those numbers into `PASS` / `WARNING` / `REVIEW` / `FAIL` using
configurable thresholds.

This split is not stylistic. The source material is expected to include
call recordings, which are band-limited and quiet by nature. If
measurement and judgement were entangled, "sounds like a phone call"
would silently become "bad audio" and the pipeline would discard its own
dataset.

Such traits are recorded as **characteristics**, not defects:

```
narrowband_8000hz (typical of telephone/call recordings; recorded, not penalised)
compressed_dynamics_crest_4.2db (common in call recordings)
```

Every finding cites the measurement and threshold that produced it — no
score is invented.

### Speech / silence

Energy-based VAD over stdlib-decoded PCM: no model, no download, no GPU.
It detects **acoustic activity**, not speech content and not identity.

The goal is useful segments, not maximal chopping:

- Silence must last `min_silence_seconds` (default 0.3 s) to split a
  region, so pauses inside a sentence survive.
- Activity under `min_speech_seconds` (0.2 s) is discarded as a transient.
- Region edges are padded 0.1 s, because energy-based onset detection
  clips quiet consonants.

### Segmentation

Deterministic: identical audio and configuration produce byte-identical
output, including segment ids.

| Bound | Default | Reasoning |
|---|---|---|
| Minimum | 1.0 s | Below ~1 s there is too little prosodic context for TTS training or reliable verification, and such fragments cost review time |
| Maximum | 20.0 s | Long spans are likelier to contain a speaker change; most TTS pipelines work well below this |
| Drop below | 0.5 s | Unusable fragments |

Splitting prefers an existing silence nearest the midpoint, so cuts land
in real pauses. A cut made without one is recorded as `hard_split` so
review can find it.

`CandidateSegment` **has no speaker field** — a test asserts this.

### Overlap candidate detection

Flags segments that may contain simultaneous speech, so Phase 3 knows
where to look. Heuristic (zero-crossing instability, energy stability)
over stdlib PCM — no model, no network.

| Status | Meaning |
|---|---|
| `NO_OVERLAP_DETECTED` | Heuristics found no indication |
| `POSSIBLE_OVERLAP` | Weak indication |
| `OVERLAP_DETECTED` | Strong indication |
| `UNKNOWN` | **Could not be determined** |

**`UNKNOWN` never becomes eligible automatically.** A segment too short
to judge is `UNKNOWN`, not "clear" — asserted by test. The reported
`overlap_confidence` is a heuristic score, explicitly **not** a
probability, and Phase 3 makes the authoritative determination.

---

## Terminology: "eligible" means *technically* eligible

| Value | Means | Does **not** mean |
|---|---|---|
| `technically_eligible` | Usable audio, workable length, no unresolved overlap | Approved as target-speaker training data |
| `needs_review` | A human must look | — |
| `technically_rejected` | Not usable audio | Not the target speaker |

The manifest also carries `"phase": "phase-2"` so no consumer can mistake
it for a speaker-approved dataset.

---

## Data root

```
data/
  source/      READ-ONLY originals, by batch
  working/     derived intermediates + stage results
  segments/    derived candidate audio
  manifests/   batch metadata + candidate manifests
  reports/     human-readable summaries
  review/      review metadata
  cache/       disposable
```

Everything except the README is git-ignored.

**`source/` immutability is enforced in code**, not just documented:

- `assert_source_writable()` raises `SourceImmutabilityError` for any
  write resolving inside `source/`; every writing stage calls it.
- Reading `source/` requires an explicit approval flag.
- Source hashes are re-verified after processing; a change halts that file.
- FFmpeg is invoked with `-n` (never `-y`), so it cannot overwrite.

### Recordings do not have to live under `data/source/`

Every stage command below takes a `<dir>` argument, and it is not
special-cased to `data/source/` — it accepts **any directory on disk**.
`data/source/` is one *optional* convention for a user who wants their
recordings tracked alongside the project's own directory layout; it is
not a requirement. A user who keeps the recordings on their own drive,
in their own folder, under their own control (which real, private
recordings usually should be) can point every command directly at that
folder instead, and the pipeline reads it in place — nothing is copied
into the repository, and nothing is ever written back into it (every
stage's derived output — manifests, quality reports, segment audio —
lands under `data/`, never under the source directory, regardless of
where that directory is).

`--approved` is required only to read the two specifically-protected
roots this project's own tree defines (`source/` at the repo root and
`data/source/`) — confirmed in code
([`pipeline/inventory.py`](../src/aarya_voice_lab/pipeline/inventory.py)'s
`require_synthetic_or_approved()`), and live-tested against an arbitrary
external directory during the Dataset Software Readiness audit
(`docs/DATASET_31_RECORDING_AUDIT.md`). Pointing at a directory outside
those two roots needs no flag for the read itself to be permitted — but
`--approved` is still what marks the resulting records `is_synthetic:
false` (real data, not a test fixture), which matters regardless of
where the files live, so pass it whenever processing real recordings:

```bash
aarya-voice inventory       "D:\MyRecordings" --approved
aarya-voice validate-audio  "D:\MyRecordings" --approved
aarya-voice analyze-quality "D:\MyRecordings" --approved
aarya-voice segment         "D:\MyRecordings" --approved --dry-run   # inspect first
aarya-voice segment         "D:\MyRecordings" --approved             # then for real
aarya-voice dataset-report  "D:\MyRecordings" --approved
```

Run `aarya-voice dataset-gate` first regardless of which location is
used — it is a deliberate, separate human checklist
(`pipeline/dataset_gate.py`), not something any of the commands above
enforce automatically for you.

### Batches

`batch-001`, `batch-002`, … Nothing is designed around a fixed number of
files; new recordings are added as a new batch with no reprocessing and
no code changes.

---

## Provenance and integrity

```
source SHA-256 → derived artifact SHA-256 → manifest → stage result
```

Every candidate records `source_file_id`, `source_sha256`, exact
timestamps, `segmentation_config_hash`, `quality_thresholds_hash`,
detector versions, and `processing_version`.

**Timestamps are never used** for anything — they are trivially wrong
after a copy or checkout.

## Resumability

A stage may reuse previous output **only** when all of these hold:

- input hashes match
- configuration hash matches
- tool version matches
- stage version matches
- every declared output exists and re-hashes to its recorded value

Any mismatch recomputes. The default answer is recompute: CPU is cheap,
whereas wrongly reusing an artifact silently corrupts a dataset built
from irreplaceable recordings. Interrupted (`running`) and `blocked`
runs are never reusable.

---

## Privacy and offline operation

- No network client anywhere in the pipeline; no cloud provider configured.
- Stage subprocesses default to `HF_HUB_OFFLINE=1` and
  `TRANSFORMERS_OFFLINE=1`, so a stage **fails loudly rather than
  silently downloading**.
- Telemetry opt-outs are applied to every stage subprocess.
- Manifests store **relative** paths, so no record embeds an absolute
  path into private storage.
- All analysis is pure-Python over stdlib-decoded PCM — no numpy, no
  GPU, no model weights.

## Hardware

CPU-only throughout. No GPU, no CUDA, and no FFmpeg is required for the
WAV path; FFmpeg is required only for other containers, and its absence
is reported as `BLOCKED` rather than failing the run.

---

## The real-recording access gate

Twelve conditions, checked mechanically by
[`dataset_gate.py`](../src/aarya_voice_lab/pipeline/dataset_gate.py):

```bash
aarya-voice dataset-gate
```

Phases pushed · clean tree · Phase 2 complete · tests passing · security
scan clean · source protection verified · output dirs git-ignored · no
cloud upload path · offline/telemetry intact · config reviewed ·
**explicit approval**.

**Explicit approval cannot be self-satisfied.** No combination of
automatic checks opens the gate — a test asserts this. Exit code 3 means
access is denied.

### After approval: one recording first

```
DRY RUN → ONE RECORDING → inspect → verify hashes → verify source
unchanged → verify outputs → only then the rest
```

`aarya-voice segment <dir> --limit 1` exists for exactly this. Do not
continue after a failed or suspicious first run.

---

## CLI

```bash
aarya-voice inventory <dir>              # catalogue + duplicates
aarya-voice validate-audio <dir>         # VALID/WARNING/INVALID/BLOCKED
aarya-voice analyze-quality <dir>        # measurements + decisions
aarya-voice segment <dir> [--dry-run] [--limit N] [--extract-audio]
aarya-voice dataset-report <dir>         # summary + review queue
aarya-voice normalize-check              # can normalization run?
aarya-voice dataset-gate                 # may we touch real recordings?
```

All accept `--json` and `--batch-id`. Reading the protected source tree
requires `--approved`.

**Exit codes:** `0` success · `1` check failed · `2` usage error ·
`3` **BLOCKED** (stop condition).

---

## Limitations

Stated plainly:

- **Verified on synthetic audio only.** Behaviour on real recordings is
  unverified.
- **VAD and overlap detection are energy heuristics**, not models. They
  are adequate for producing candidates and finding places to look; they
  are not accurate speech or overlap detection. Both are replaceable
  without changing the stage interface.
- **Estimated SNR is a coarse proxy** that assumes the recording contains
  both quiet and loud passages. It is comparative, not calibrated.
- **Only WAV is processable without FFmpeg.** Everything else is BLOCKED.
- **Normalization is untested end-to-end** — no FFmpeg on the
  development machine, so only its blocked path has been exercised.
- **Segmentation bounds are reasoned, not empirically tuned.** They
  should be revisited once real material has been inspected.
- **Nothing here says anything about who is speaking.**
