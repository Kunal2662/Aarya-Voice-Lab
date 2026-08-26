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
   zero leakage. This is **held-out evaluation infrastructure being
   ready**, not a model evaluation having been run — no model has been
   trained or scored against either split.
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
