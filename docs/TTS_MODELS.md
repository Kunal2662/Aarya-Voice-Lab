# TTS Candidate Matrix

> **NO MODEL HAS BEEN SELECTED.** This is an evaluation input, not a
> decision. No TTS package is installed, no weights downloaded, nothing
> synthesized. Selection is deferred beyond Phase 1 and belongs to a
> benchmark phase ([BENCHMARKING.md](BENCHMARKING.md)).

Machine-readable source of truth:
[`registry/tts_candidates.py`](../src/aarya_voice_lab/registry/tts_candidates.py).
View it with:

```bash
aarya-voice tts-candidates          # or --json
```

Facts verified 2026-08-19 against PyPI metadata, model cards, and project
READMEs. **Licenses and gating change — re-verify before acting.**

## Screening criteria

Licensing is a **hard filter**, applied before quality is considered at
all. A model that sounds excellent but cannot be licensed for this use is
not a candidate. Verdicts below reflect license and language screening
only: **no audio has been evaluated and no benchmark has run.**

For the Private Voice specifically, a candidate must also support
**reference-based cloning** (the dataset will be small — see
[DATASET_PIPELINE.md](DATASET_PIPELINE.md)) and **Marathi**.

## The matrix

| Model | Weights license | Marathi | Cloning | Commercial | Verdict |
|---|---|---|---|---|---|
| **AI4Bharat IndicF5** | **MIT** | ✅ | ✅ | permitted | **candidate** |
| AI4Bharat Indic Parler-TTS | Apache-2.0 | ✅ | ❌ | permitted | default-voice only |
| Piper | per-voice | ✅ | ❌ | unclear | default-voice only |
| Coqui XTTS-v2 | CPML (non-commercial) | ❌ | ✅ | **prohibited** | **rejected** |
| F5-TTS (base) | CC-BY-NC-4.0 | ❌ | ✅ | **prohibited** | **rejected** |
| Fish Speech / OpenAudio | research-only | ❌ | ✅ | **prohibited** | **rejected** |

**Exactly one candidate passes every hard filter.** That is a thin
position, and worth stating plainly rather than presenting as a
comfortable shortlist.

---

## Candidate detail

### AI4Bharat IndicF5 — leading candidate

| Field | Value |
|---|---|
| Code / weights license | MIT / **MIT** |
| Commercial use | Permitted |
| Attribution | Not required by license |
| Redistribution | Unrestricted by license |
| Languages | 11 Indic, incl. **Marathi** |
| Cloning | Yes — reference audio + transcript |
| Training data | Documented: Rasa, IndicTTS, LIMMITS, IndicVoices-R (~1417h) |
| CPU capable | Yes |
| Size | F5-TTS architecture (~300M class) |

**Known limitations:**
- The HuggingFace repo is **gated** — requires accepting a
  contact-sharing agreement. The *license* is MIT; the *download* is
  gated. These are separate concerns.
- Loads with **`trust_remote_code=True`**, which executes arbitrary code
  from the model repo. **Review that code before running it in any
  environment that can reach private material.** This is the single
  largest security caveat of any candidate here.
- Dependency pins are not published; resolution is untested.
- VRAM, latency, and Marathi quality are **unmeasured by this project**.
- The model card requires that you only clone voices you have permission
  to clone — consistent with this project's authorization, and worth
  recording.

### AI4Bharat Indic Parler-TTS — Default Voice candidate

Cleanest licensing of anything audited: **Apache-2.0 for both code and
weights**, 21 languages including Marathi. **Cannot clone a voice** —
output is steered by a natural-language speaker description — so it
cannot serve the Private Voice. A strong option for a distributable
Default Voice. Not on PyPI; installed from git, so no resolvable version
pin.

### Piper — CPU baseline

ONNX, **no torch at inference**, near-zero dependency conflict risk, and
`mr_IN` voices exist. Cannot clone; a new voice requires finetuning.
Current `piper1-gpl` package is **GPL-3.0-or-later**, a distribution
consideration. Per-voice weight licenses vary and must be checked
individually. Useful as a pipeline smoke test precisely because it drags
in nothing.

---

## Rejected, and why

### Coqui XTTS-v2 — fails two hard filters

The most commonly recommended open cloning model, and **the wrong default
here**:

1. Weights are **CPML, non-commercial** — and **Coqui Inc. dissolved in
   January 2024**, so no entity exists that could grant different terms.
   This cannot be resolved by asking.
2. **Marathi is absent** from its 17 languages (Hindi is present).

Reaching for it out of familiarity would be a mistake. The code lives on
as the maintained `idiap/coqui-ai-TTS` fork (MPL-2.0), but the *weights*
license is what binds.

### F5-TTS (base checkpoints)

MIT code, but **CC-BY-NC-4.0 base weights** and English/Chinese only.
IndicF5 is effectively the MIT-licensed Indic finetune of this
architecture — take that instead.

### Fish Speech / OpenAudio

Current release is **research-only, covering code *and* weights**; older
OpenAudio-S1 weights were CC-BY-NC-SA-4.0. No Marathi. Its PyPI package
is a stale 0.1.0 pinning `numpy<=1.26.4`, which conflicts with the rest
of the stack anyway.

---

## Environment

`env-tts` is specified but **intentionally installs nothing** —
`requirements/tts.txt` has no active entries. `scripts/install_env.sh
env-tts` refuses without `--i-have-approval`, on the grounds that
building the environment before choosing a model would mean installing an
arbitrary candidate.

Keep it separate from `env-nemo` and `env-whisperx`: TTS stacks bring
their own torch and transformers versions.

## Open questions for the selection phase

1. Does IndicF5's Marathi quality hold for **this speaker's** voice from
   a small dataset? Unknowable without the approved dataset phase.
2. Is its `trust_remote_code` requirement acceptable, and can the code be
   audited and pinned to a reviewed revision?
3. Is a single viable candidate enough, or should a second be
   cultivated — e.g. finetuning Piper or Parler-TTS — to avoid a
   single point of failure?
4. Does the Private Voice runtime need a GPU at all? That is a benchmark
   question ([GPU_STRATEGY.md](GPU_STRATEGY.md)).
