# Benchmarking Framework

> **PLANNED — framework and schema only.** No benchmark has been run and
> **no benchmark results exist**. Any number appearing in this repository
> is a synthetic placeholder in a template, clearly marked as such.
> `aarya-voice benchmark run` refuses to execute.

## Purpose

Decide between voice models on **measured evidence** rather than
reputation or demo quality, and detect regressions between experiments.

## Metrics

Schema: [`benchmark.schema.json`](../schemas/benchmark.schema.json). All
metrics are individually optional — record only what was actually
measured, never a placeholder.

### Fidelity

| Metric | Range | Meaning |
|---|---|---|
| `speaker_similarity` | 0–1 | Similarity to the target speaker (embedding-based) |
| `naturalness` | 0–5 | MOS-style; sounds like a person, not a synthesizer |
| `intelligibility` | 0–1 | Comprehensibility (ASR round-trip is a proxy) |
| `pronunciation` | 0–1 | Correct phoneme realization |
| `prosody` | 0–5 | Rhythm, stress, intonation |

`speaker_similarity` is the primary fidelity metric for the Private
Voice, but **it must not be optimized alone** — a model can score well on
similarity while sounding robotic. Similarity and naturalness are read
together.

### Language

| Metric | Meaning |
|---|---|
| `marathi_quality` | Primary language of the source material |
| `hindi_quality` | Secondary |
| `english_quality` | Secondary |
| `code_switching_quality` | Mid-sentence language switches |

Code-switching gets its own metric because models often handle each
language acceptably in isolation yet break at the switch — and natural
Marathi speech commonly mixes in Hindi and English.

### Performance

| Metric | Meaning |
|---|---|
| `latency_ms` | Time to first audio |
| `real_time_factor` | Generation time ÷ audio duration (<1.0 = faster than real time) |
| `cpu_memory_mb`, `gpu_memory_mb` | Peak memory |
| `generation_speed_chars_per_sec` | Throughput |
| `artifact_rate` | 0–1 rate of glitches, clicks, dropouts |

Performance is recorded alongside quality because a model that sounds
excellent at RTF 8.0 on a GPU that isn't available may be the wrong
choice. Results are only comparable when the `hardware` block matches —
the schema requires it for that reason.

## Methodology (to be defined)

Before the first real benchmark, the following must be fixed and
documented:

1. **A held-out evaluation set** — never used in training, or
   `speaker_similarity` measures memorization rather than generalization.
   **Infrastructure ready, evaluation itself not run**: see
   [`pipeline.dataset_split`](../src/aarya_voice_lab/pipeline/dataset_split.py).
   It distinguishes two different questions this project's evaluation
   needs never conflate — `SAME_SPEAKER` (held-out utterances from a
   known speaker; the relevant question for the Private Voice, which has
   exactly one target speaker) and `HELD_OUT_SPEAKER` (entire speakers
   set aside; the relevant question for a multi-speaker corpus like the
   registered LibriSpeech dev-clean data). Both are deterministic,
   seeded, and leakage-checked (`check_leakage()`) for duplicate record
   ids, duplicate paths, duplicate content hashes where available, and
   speaker leakage in `HELD_OUT_SPEAKER` mode. Verified against the real,
   registered `librispeech-dev-clean` dataset (2,703 records, 40
   speakers): `HELD_OUT_SPEAKER` split — 1,902/393/408 records across
   28/6/6 speakers, zero leakage on every check; `SAME_SPEAKER` split —
   1,890/407/406 records, all 40 speakers present in every partition,
   zero leakage.

   **Update — a real objective metric has since been computed against
   this infrastructure**: see
   [`pipeline.speaker_similarity`](../src/aarya_voice_lab/pipeline/speaker_similarity.py)
   and
   [`pipeline.speaker_similarity_experiment`](../src/aarya_voice_lab/pipeline/speaker_similarity_experiment.py).
   This computes cosine similarity between real `titanet_large`
   embeddings of real LibriSpeech utterances, across three pair
   categories — `SAME_SPEAKER_HELD_OUT`, `DIFFERENT_SPEAKER`, and
   `TRAIN_REFERENCE_TO_HELD_OUT` (the last correctly yielding zero pairs
   under a `HELD_OUT_SPEAKER` split, by construction, not an error).
   **This is a speaker-similarity baseline for the embedding provider,
   not a voice-model evaluation** — no generation model exists yet, so
   nothing here claims TTS quality, voice-cloning quality, naturalness,
   prosody, or production readiness; `speaker_similarity` is one
   identity/embedding metric among the several this document defines,
   not a complete quality judgement.

   Two real runs against the `SAME_SPEAKER` split (seed 42), against the
   real, registered `librispeech-dev-clean` dataset:

   | Run | Pairs/category | Coverage | Same-speaker mean (stdev) | Different-speaker mean (stdev) | Train→held-out mean (stdev) |
   |---|---|---|---|---|---|
   | Original baseline | 8 | 100% (24/24) | 0.772 (0.099) | 0.079 (0.078) | 0.781 (0.124) |
   | Expanded baseline | 40 | 99.2% (119/120; one embedding hit a real, transient 90s worker timeout) | 0.751 (0.159) | 0.082 (0.102) | 0.746 (0.131) |

   Both runs show the same real pattern: same-speaker similarity
   clusters around 0.75–0.78, different-speaker similarity clusters near
   0 (0.08), and train-reference-to-held-out closely tracks the
   held-out-to-held-out figure — a clean, real separation confirming the
   embedding space discriminates speakers rather than returning noise.
   The full P10/P25/P50/P75/P90/min/max breakdown per category is
   computed by `KindStatistics` and persisted with every run (see
   below); the table above shows mean/stdev only for brevity.

   **Persistence and reproducibility.** Each run is recorded as one
   `experiments/registry.jsonl` entry (git-ignored, per this project's
   existing experiment-registry convention — see
   [MODEL_STRATEGY.md](MODEL_STRATEGY.md)) via
   `speaker_similarity_experiment.build_experiment_record()`, keyed by a
   deterministic `experiment_id` hashed from every input that would
   change the result (dataset id, split config, pair seed,
   max-pairs-per-kind, provider, model version) — re-registering the
   identical experiment is refused, like every other registry in this
   project. The full pair list (record ids, speaker ids, per-pair
   similarity) is persisted alongside the aggregate statistics, so
   `speaker_similarity_experiment.verify_pair_selection_reproducibility()`
   can recompute pair selection from the persisted configuration alone
   and confirm it matches exactly — proven against the real expanded run
   (120/120 pairs matched) — without re-embedding anything, since
   real embedding is the slow step (each call spawns a fresh subprocess
   that reloads the model from disk; see
   `docs/REAL_ML_RUNTIME_INTEGRATION.md`).

   **Limitations, stated plainly.** Both runs draw from one dataset
   (LibriSpeech dev-clean, English, read audiobook narration) — Hindi/
   Marathi speaker-similarity behavior is unmeasured. Sample sizes (24
   and 120 pairs) are small relative to the full 2,703-record corpus by
   design (each embedding is expensive; see above) — these are baselines,
   not an exhaustive characterization. No threshold from this evaluation
   gates anything; the project's existing speaker-*verification*
   acceptance thresholds (`identity.calibration`: 0.55/0.65/0.85) are a
   different use case (live accept/reject decisions) and are not applied
   as a pass/fail bar here.
2. **A fixed text set** per language, covering the code-switching case.
3. **Subjective rating protocol** — who rates, blind or not, how many
   raters. Naturalness and prosody are human judgements; an unstated
   protocol makes scores non-comparable across runs.
4. **Fixed hardware and seeds**, recorded per run.

## Rules

- **Never fabricate results.** An absent measurement is left absent. A
  plausible-looking invented number is worse than a missing one — it will
  be trusted.
- **Record the hardware.** Performance metrics are meaningless without it.
- **Link to the experiment.** Benchmarks reference `experiment_id`, which
  references `dataset_version` — a result should be traceable to the data
  that produced it.
- **Private Voice benchmark outputs are private.** Generated samples are
  private-voice material ([PRIVACY.md](PRIVACY.md)): never committed,
  never uploaded, never used as public demos. `benchmarks/` is
  git-ignored.
