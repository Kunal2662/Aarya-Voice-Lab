# Real ML Runtime & Model Integration — embedding is real, generation is deferred

**Status: real speaker embedding, real speaker verification. Voice
generation and training remain `NOT_CONFIGURED`, by an explicit decision
made this milestone, not by omission.**

This milestone moved one provider — `identity.embeddings.LocalNeuralEmbeddingProvider`
— from the architecture-only `NOT_CONFIGURED` state the previous
"Real Voice Model Engine" milestone left it in (see
`docs/REAL_VOICE_MODEL_ENGINE.md`) to a genuinely installed, genuinely
loaded, genuinely inferencing model. Generation (`LocalNeuralVoiceGenerator`)
and training (`LocalTrainingProvider`) were in scope for the same
treatment but hit a real, external blocker (below) and were deferred by
explicit user decision rather than silently left half-done.

## Environment audit (performed before any install)

| Check | Result |
|---|---|
| GPU | None (`nvidia-smi`: not found) |
| CPU-only ML feasible | Yes — this milestone ran entirely on CPU |
| Existing approval gates | `scripts/install_env.sh` hard-`exit 3`s for `env-whisperx`/`env-tts` without `--i-have-approval`; `env-nemo` has no such gate (no credentials needed) |
| `configs/default.yaml` | `environments.env-tts.requires_approval: true` confirmed |
| `data/source/` | Empty — no real recording exists anywhere in this environment; every test fixture in this milestone is a synthetic sine tone, exactly like the rest of the test suite |

## Model decision: embedding

**Chosen: NVIDIA NeMo `titanet_large`, via a new `.envs/env-nemo` build.**

- **Why this model.** `docs/NEMO.md` already documented `env-nemo` as
  credential-free (no HuggingFace token, no account, no terms
  acceptance) — the same property that made it the preferred diarization
  path applies equally to speaker embedding. `titanet_large` is served
  from NVIDIA NGC, which required no authentication at all (confirmed:
  `curl -sIL` against the real weights URL returned a plain 302→200).
- **Why not a HuggingFace-hosted alternative.** Considered and rejected
  for embedding specifically because it would have introduced a second,
  unnecessary credential dependency when a credential-free option
  already existed and was already the project's documented preference.
- **License.** NVIDIA NGC model card terms (non-commercial research/
  evaluation use). This project fetches the checkpoint directly from NGC
  at install time and does not redistribute it — the checkpoint is
  stored locally under the existing `data/model_artifacts/` (git-ignored,
  checksum-addressed) purely as a local cache with provenance, not as a
  redistribution.
- **Architecture.** TitaNet-large, 192-dimensional speaker embedding.
  Trained on Fisher, Switchboard, LibriSpeech, VoxCeleb1, VoxCeleb2.
- **Language audit.** Speaker embedding is a spectral/prosodic task, not
  a content-language task, so a per-language accuracy claim is not
  meaningful the way it would be for ASR/TTS. What is actually known:
  the published training corpora are English-dominant (Fisher/SWBD/
  LibriSpeech are English; VoxCeleb1/2 are broad but English-majority).
  **Hindi and Marathi speaker-embedding accuracy is UNVALIDATED by this
  project** — no real Hindi or Marathi recording has ever been embedded
  here (`data/source/` is empty in every environment this project runs
  in; every embedding this milestone computed was from a synthetic sine
  tone). This is recorded honestly in the model registry
  (`models/registry.jsonl`, `titanet_large` entry) rather than inferred
  from any multilingual marketing claim.
- **`trust_remote_code`.** Not applicable — NeMo loads its own
  `.nemo` checkpoint format via `EncDecSpeakerLabelModel.from_pretrained()`,
  no arbitrary remote code execution.

## Model decision: generation — deferred, not silently dropped

**Approved scope, then blocked, then explicitly descoped by the user.**

The user's original approval named `ai4bharat/IndicF5` (MIT license,
Marathi-capable, the sole candidate in `docs/TTS_MODELS.md` passing every
hard filter) for real voice generation, on the condition that its
`trust_remote_code=True` requirement be reviewed before running it.

Before any code review could happen, a hard access blocker was found:

- HuggingFace's own repo metadata for `ai4bharat/IndicF5` reports
  `"gated":"auto"`.
- No `HF_TOKEN` or other HuggingFace credential exists in this
  environment (`env | grep -i "HF_TOKEN\|HUGGING"` returns nothing).
- Confirmed directly, not inferred: `curl -sI` against the actual
  weights file (`model.safetensors`) returned **HTTP 401 Unauthorized**.

This is a legitimate, correctly-functioning consent control on
HuggingFace's side — creating an account or accepting the gating
agreement on the user's behalf would have been inappropriate without the
user directly supplying their own credentials. Piper (GPL-3.0-or-later,
CPU-only, non-gated, `mr_IN` Marathi voices) was identified as
`docs/TTS_MODELS.md`'s own documented non-gated fallback, but it changes
what was actually approved (it cannot clone a voice — Default Voice
generation only), so it was not substituted silently.

**Resolution:** asked the user directly. The user chose to **skip
generation for this milestone** rather than substitute a different model
or supply credentials. `LocalNeuralVoiceGenerator` and
`LocalTrainingProvider` therefore remain exactly as the previous
milestone left them — `NOT_CONFIGURED`, empirically detected, refusing
to fabricate output — and that state is correct and intentional, not an
oversight. Building `env-tts` and picking a generation model remains
future work, gated on either the user obtaining HuggingFace credentials
for IndicF5 or a fresh decision to use a non-gated substitute.

## Update — access granted, real generation attempted, model's own published code is broken

The user later obtained HuggingFace credentials for `ai4bharat/IndicF5`
and authorized continuing. Verified authentication without ever
exposing the token: a `whoami` check confirmed a valid account, and the
same weights-file request that previously returned `401 Unauthorized`
now returned **`302 Found`** (a real redirect to a signed download URL —
the normal shape of an authorized HuggingFace resolve request).

A clean `.envs/env-tts-windows` was built (Python 3.13.14 — the
repository's `configs/default.yaml` declares 3.12 for `env-tts`, and
IndicF5's own model card recommends 3.10, but neither is installed on
this machine; 3.13 was used instead, the same documented deviation
`env-nemo` already made once for the identical reason, and no package
in this dependency set turned out to require an exact Python version).
Installed: `torch==2.13.0+cpu`, `transformers`, `soundfile`, `pydub`,
`huggingface_hub`, `safetensors`, and `f5-tts` (IndicF5's own `model.py`
imports directly from the `f5_tts` package, so it is a real runtime
dependency despite not being one of `LocalNeuralVoiceGenerator`'s
originally-listed three).

**Security review of `model.py` (the file `trust_remote_code=True`
actually executes, fetched and read in full before any execution):**
no obfuscation, no network exfiltration, no shell execution — ordinary,
readable ML loading/inference code. One dead-code observation: the
file's `if __name__ == '__main__':` block uploads a rebuilt model
directory to a third-party's personal HuggingFace repo (`svp19/INF5`)
— clearly leftover development/testing code from the model's author,
but it is **never executed** via `trust_remote_code=True`'s import
mechanism (that guard only fires on direct script execution), so it is
not a live risk. The one substantive finding: `INF5Model.__init__`'s
call to `f5_tts.infer.utils_infer.load_model(...)` omits the function's
required `ckpt_path` argument entirely, and the actual `safetensors`
state-dict loading code three lines below it is commented out — meaning
the real trained IndicF5 weights are never loaded into the model by the
published code, regardless of environment. This is a defect in the
model repository's own code, not something this project can or should
patch — modifying gated third-party remote code to work around its own
bugs would mean silently authoring an unreviewed variant of the model,
exactly what `trust_remote_code=True` review exists to prevent.

**Real generation attempts, both failing, confirming the finding
empirically rather than relying on the code review alone:**

| Attempt | `transformers` version | Result | Elapsed |
|---|---|---|---|
| 1 | 5.16.0 (latest at install time) | `RuntimeError: Tensor on device cpu is not on the expected device meta!` | 155.6s |
| 2 | 4.49.0 (the exact version recorded in the model's own `config.json`) | `TypeError: load_model() missing 1 required positional argument: 'ckpt_path'` | 14.3s |

The second attempt's error is the direct, literal confirmation of the
code-review finding. The model repository's own **open, unresolved**
community discussion ("Fix transformers 5.0.0 compatibility",
`ai4bharat/IndicF5` discussion #33) corroborates that others have hit
breakage in this same loading path — this project's finding is
consistent with, not contradicted by, that report.

~1.4 GB (model repo cache, including the real `model.safetensors` that
`transformers`' own `from_pretrained()` resolved and downloaded before
construction failed) + ~52 MB (the `charactr/vocos-mel-24khz` vocoder,
a public, ungated dependency) were downloaded to the user's global
HuggingFace cache (`~/.cache/huggingface/hub/`) — outside this
repository entirely, nothing committed or copied into it.

**`LocalNeuralVoiceGenerator` was not modified.** Real generation did
not succeed, so per this project's own "never fabricate AVAILABLE"
discipline, `get_capabilities()` continues to report `NOT_CONFIGURED`/
`ERROR` and `generate_preview()` continues to unconditionally raise
`GenerationBlockedError` — exactly as before this attempt.

## What is real now

`identity.embeddings.LocalNeuralEmbeddingProvider`:

- `capability_state()` genuinely loads `titanet_large` (via a subprocess
  into `.envs/env-nemo`, never imported into the base interpreter — see
  Architecture below) and reports `AVAILABLE` only because that load
  actually succeeded, not because a package is merely importable.
- `embed()` runs real inference and returns a real 192-dimensional
  vector, `is_synthetic=False`.
- The pre-existing `EnrollmentEngine`/`VerificationEngine`
  (`identity/enrollment.py`, `identity/verification.py`), built against
  only the synthetic provider in an earlier phase, required **zero code
  changes** to work correctly against this real provider — proof the
  provider abstraction was well-designed from the start.
  `assert_real_identity_claim()`'s synthetic-provenance gate correctly
  does not fire for a real, non-synthetic verification.

## Architecture: subprocess bridge, not a direct import

`identity/embeddings.py`'s long-standing module docstring requires real
providers to "communicate through the filesystem contract" and never be
"imported into the base interpreter, whose dependency set must stay
ML-free." This milestone honors that:

- `scripts/ml_workers/nemo_embedding_worker.py` runs only inside
  `.envs/env-nemo/bin/python`. Two modes: `probe` (load the model, report
  load time) and `embed` (load, run inference on a given WAV path,
  return the vector). Always writes a response file, even on exception;
  exit code mirrors `ok`.
- `LocalNeuralEmbeddingProvider._run_worker()` writes a request JSON,
  invokes the worker via `subprocess.run([...python..., ...script...],
  env={**os.environ, **_NEMO_SUBPROCESS_ENV}, timeout=...)`, and reads
  the response JSON back. The base interpreter never imports `nemo` or
  `torch`.
- Telemetry opt-out is layered onto the subprocess environment
  (`WANDB_MODE=offline`, `SENTRY_DSN=""`, `NEMO_TELEMETRY_OPT_OUT=1`,
  `HF_HUB_DISABLE_TELEMETRY=1`, `DO_NOT_TRACK=1`, etc.), mirroring
  `scripts/disable_telemetry.sh`'s existing interactive pattern, applied
  programmatically here.
- Verified bit-for-bit: a direct in-process NeMo call and the full
  subprocess round-trip from the base interpreter produce identical
  embedding values for the same input.

## Defects found and fixed (Class A — directly blocked this milestone)

1. **`environment/verify.py`'s `check_package()` misreported a correctly
   installed torch as `INCOMPATIBLE`.** `scripts/install_env.sh` installs
   torch from an explicit `--cpu`/`--cuda` wheel index specifically so
   the accelerator build is deterministic; that wheel's version always
   carries a PEP 440 local segment (`2.13.0+cpu`). An exact-string
   comparison against the bare pin (`2.13.0`) reported every correctly
   installed torch as incompatible. Fixed with `_public_version()`,
   which strips the local segment unless the expected spec itself pins
   one. Two regression tests added in `tests/test_environment_specs.py`.
2. **`.envs/` was untracked but not gitignored.** A real, self-created
   risk: any future broad `git add` could have staged multiple gigabytes
   of local ML environment contents. Fixed by adding `.envs/` to
   `.gitignore` immediately upon discovery.
3. **`subprocess.run(env=_NEMO_SUBPROCESS_ENV, ...)` wholesale-replaced
   the environment**, causing `KeyError: 'PATH'` inside the worker.
   Fixed by merging (`{**os.environ, **_NEMO_SUBPROCESS_ENV}`) instead
   of replacing.

None of these were pre-existing latent bugs found by unrelated
exploration — each was hit directly while building this milestone's own
real capability, and each is fixed and regression-tested.

## Model artifact & registry provenance

`scripts/register_real_model_artifacts.py` copies the exact bytes NeMo's
own `from_pretrained()` cached while building `.envs/env-nemo` into this
project's existing checksum-addressed `ArtifactStore`
(`pipeline/model_artifact.py`, under git-ignored `data/model_artifacts/`)
and records a corresponding entry in the model registry
(`registry/model_registry.py`, git-ignored `models/registry.jsonl`).
Idempotent: re-running it recognizes the artifact/registry entry already
exist and leaves them untouched rather than erroring or duplicating.

Real, measured provenance recorded for this run:

- `artifact_id`: `artifact-e838520693f269e7`
- `checksum_sha256`: `e838520693f269e7984f55bc8eb3c2d60ccf246bf4b896d4be9bcabe3e4b0fe3`
- `size_bytes`: 101,621,760
- `artifact_format`: `nemo_checkpoint`
- `model_registry` entry: `titanet_large`, `provider: nvidia-nemo`,
  `model_type: other`, `lifecycle_state: AVAILABLE`

## Evaluation (§20) — what could actually be measured here

No real recording exists in this environment (`data/source/` is empty,
by design — see `docs/PRIVACY.md`), so no speaker-similarity evaluation
against real speech was possible. What was measured instead is a
sanity check that the real model's output is not fabricated — it must
respond to its actual input, unlike a hardcoded or synthetic score:

| Comparison | Cosine similarity |
|---|---|
| Same signal, embedded twice (220 Hz vs. itself) | 1.0 (exact) |
| Near-identical signal (220 Hz vs. 220.0001 Hz) | 0.9997 |
| Clearly different signal (220 Hz vs. 440 Hz) | 0.8487 |
| Clearly different signal (220 Hz vs. 880 Hz) | 0.8496 |

This is a synthetic-signal sanity check, not a speaker-verification
accuracy benchmark — a real accuracy evaluation needs real speech from
real (consenting, enrolled) speakers, which this project does not have
in any environment it runs in. The monotonic drop from "identical" to
"near-identical" to "clearly different" is the property under test: a
fabricated or hardcoded similarity score would not vary with the input
at all.

## Performance — real, measured

| Operation | Measured latency |
|---|---|
| Cold model load (`capability_state()` first call, this run) | 8.57s–86.4s (highly variable — see note) |
| Warm model load (subsequent probe/embed calls) | ~8.4–10.9s each |
| Inference only (in-process, no subprocess overhead) | ~0.13s |

Note on variability: every `embed()`/`capability_state()` call spawns a
**fresh** subprocess into `.envs/env-nemo` and reloads the model from
disk each time — there is no warm, persistent model server in this
milestone's design (the filesystem-contract isolation boundary
intentionally keeps the base interpreter from holding any ML process
state). The 86.4s outlier above was NeMo re-resolving/re-verifying its
on-disk cache under load; typical repeated calls measured 8–11s. A
persistent worker process would remove this per-call reload cost but was
out of scope for this milestone (the architecture explicitly calls for
one-shot subprocess isolation, not a long-lived ML service).

## Reliability investigation — one real, non-reproducible embedding timeout

A 218-embedding real run (`docs/BENCHMARKING.md`'s expanded speaker-
similarity baseline) hit exactly one failure: record `5895-34615-0008`
raised `EmbeddingProviderError: ...worker timed out after 90s` (99.5%
single-attempt success rate; 217/218 succeeded). Investigated rather
than dismissed:

- **The audio itself is ordinary**: 3.055s, 16kHz/mono/16-bit FLAC,
  `pipeline.validation.validate_audio_file()` reports `VALID` with no
  findings — nothing about the file is anomalous.
- **Did not reproduce.** The exact same record, embedded 3 more times
  under controlled conditions: 27.27s, 28.66s, 31.97s — all succeeded,
  all returned bit-identical 192-dimensional output (the model is
  deterministic in eval mode, as expected).
- **Four neighboring/comparison records** (2 from the same chapter, 2
  from different speakers, durations 2.78s–10.06s) all succeeded too,
  27–34s each, with **no correlation between audio duration and
  runtime** — a 10.06s clip embedded faster (29.69s) than a 5.71s clip
  (34.17s), confirming elapsed time is dominated by the fixed
  subprocess-startup + model-reload cost documented above, not by
  input length or inference itself (~0.13s, per the table above).
- **The timeout wraps the entire subprocess**, not just inference:
  `LocalNeuralEmbeddingProvider._run_worker()`'s `subprocess.run(...,
  timeout=...)` spans process launch, the `torch`/`nemo_toolkit` import,
  full model reload from disk, inference, and the JSON response
  round-trip. Confirmed by inspection of both `_run_worker()` and
  `scripts/ml_workers/nemo_embedding_worker.py` — the 90s ceiling was
  never intended to bound inference alone.
- **Root cause classification: `INTERMITTENT_RUNTIME_FAILURE`,
  moderate confidence.** Conclusively ruled out: `RECORD_SPECIFIC_AUDIO_PROBLEM`,
  `MODEL_INFERENCE_PROBLEM` (7/7 controlled attempts across 5 distinct
  records all succeeded with correct, stable output). Most plausible
  contributing factor: transient resource contention on a shared,
  general-purpose machine (`Get-CimInstance Win32_OperatingSystem`
  showed as little as ~2.6 GB of 16 GB physical memory free at points
  during this investigation) colliding with the architecture's already-
  thin timeout margin — this project's own prior measurement recorded
  an 86.4s cold-load outlier once before, well within reach of a 90s
  ceiling under any additional friction. Not proven with certainty:
  nothing was monitoring system resources at the exact moment of the
  original failure, so the specific contending cause cannot be
  identified after the fact.
- **No production code was changed.** Nothing here demonstrates a
  repository-level reliability defect: the timeout fired correctly and
  safely (the caller received a clear, honest `EmbeddingProviderError`,
  never a hang, a crash, or fabricated output), and 7/7 controlled
  reproduction attempts stayed comfortably within the existing 90s
  budget (27–34s). A single ~0.5%-rate transient failure on a shared
  machine is not, by itself, evidence that the timeout, the subprocess
  architecture, or the model choice needs to change.

## Testing

- `tests/test_real_ml_runtime.py` (new): capability-gated integration
  tests against the actual installed runtime — `pytest.skip()`s with an
  explicit reason if `.envs/env-nemo` was not built, never fabricates a
  passing result. Covers real model load + metadata, similarity that
  demonstrably varies with input, latency measurement (no fixed
  threshold, just proof the number is real), and a full enrollment →
  verification round trip through the pre-existing, unmodified engine.
- `tests/test_voice_model_engine.py` / `tests/test_phase3_identity.py`:
  three tests that hardcoded `NOT_CONFIGURED` from the previous
  milestone were rewritten — two to reproducibly simulate the
  not-configured case via monkeypatching the interpreter path to a
  nonexistent location, one to branch on the real, current
  `capability_state()` at test time. Behavior did not regress; the
  assumption these tests encoded became stale the moment the real
  provider started working.
- `frontend/tests/voice-engine-status.test.mjs`: the assertion "no real
  provider should report AVAILABLE in this environment" was true for
  the previous milestone and is no longer true for embedding on a
  machine that built `.envs/env-nemo` — rewritten to assert the
  actually-invariant claim instead: generation and training must never
  claim `AVAILABLE` in this milestone's scope, regardless of what the
  embedding row (which now legitimately varies by machine) says.
- `scripts/export_voice_engine_capabilities.py` was re-run; the live,
  git-ignored snapshot now reflects the real `AVAILABLE` embedding state
  for this machine.

## What this milestone does not claim

- No real voice has been generated (IndicF5 access blocked; Piper not
  substituted without asking; user chose to defer rather than proceed).
- No real training run has executed (`LocalTrainingProvider` is
  unaffected by this milestone — still `NOT_CONFIGURED`).
- No Hindi or Marathi speech has ever been embedded by this codebase —
  only synthetic sine tones (identical to every other test fixture in
  this project) and, for the embedding model specifically, an
  English-dominant published training corpus with unvalidated Hindi/
  Marathi performance.
- The synthetic providers are unchanged and still what every existing
  D0–D10/FE test and frontend run exercises by default — the real
  embedding provider is a second, clearly-labelled, honestly-available
  path alongside them, never a silent replacement.
- `SPEAKER_IDENTITY_BOUNDARY` and the synthetic-provenance invariant are
  unchanged and still enforced.

## What would change this further

- Generation: the user supplying real HuggingFace credentials for
  IndicF5 (resuming the originally-approved path), or a fresh decision
  to build `env-tts` around a non-gated substitute (Piper is the
  documented candidate).
- Training: a trainable path requires either a real generation model to
  fine-tune, or a NeMo-based speaker-adaptation approach neither
  installed nor evaluated in this milestone.
- Real-corpus Hindi/Marathi validation for the embedding model: requires
  real, consented recordings in those languages, which this project does
  not currently have in any environment.
