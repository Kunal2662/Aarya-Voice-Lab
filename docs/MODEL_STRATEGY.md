# Model Strategy

> **PLANNED — no model exists, no model has been selected, no training
> has occurred.** Phase 0 provides the registry, experiment tracking, and
> the `VoiceService` contract.

## Two model lines

| | **Default Voice** | **Private Voice** |
|---|---|---|
| Source | Not from private recordings | 31 private recordings |
| Selection | Chosen/developed separately, later | Derived via the dataset pipeline |
| Access | Broader AARYA use | **Admin-only**, `voice.private.use` |
| Registry `model_type` | `default_voice` | `private_voice` |
| Security metadata | Optional | **Required** (schema-enforced) |

They are kept distinct at the schema level so the security requirements
of one can never be accidentally inherited — or dropped — by the other.
A `private_voice` entry without `security_metadata` fails validation.

## The constraint that shapes everything

The usable dataset will be **small** — one speaker's share of 31
recordings, after removing overlap, low quality, and review rejections.

That rules out training a TTS model from scratch (typically many hours of
clean single-speaker audio) and points to **reference-based / few-shot
voice cloning**, or fine-tuning a multilingual base model that already
knows Marathi phonetics.

A second constraint from the project goal: the Private Voice must sound
like **a natural person, not a telephone recording**. If the source
material carries call-recording characteristics, the model will reproduce
them faithfully — this is a data-quality problem to solve upstream in the
pipeline, not something a better model choice fixes.

## Candidate direction

**AI4Bharat IndicF5** is the leading candidate: MIT weights, Marathi
support, reference-audio cloning suited to a small dataset. See
[TOOLCHAIN.md](TOOLCHAIN.md) for the full comparison, the licensing
rejections (notably XTTS-v2), and the `trust_remote_code` caveat.

For the **Default Voice**, cloning isn't needed, which opens up
cleanly-licensed options like Indic Parler-TTS (Apache-2.0 throughout) or
Piper.

**These are directions, not decisions.** The choice should be made
against measured benchmark results ([BENCHMARKING.md](BENCHMARKING.md)),
not on reputation.

## Model registry

[`registry/model_registry.py`](../src/aarya_voice_lab/registry/model_registry.py),
schema at
[`model_registry.schema.json`](../schemas/model_registry.schema.json).
Tracks name, version, provider, type, language capability, hardware
requirements, model hash, source, **license**, training dataset version,
benchmark results, and status.

License is a first-class field because it is a **hard filter** here —
several capable models are unusable on licensing grounds alone, and that
must be visible at the registry level rather than rediscovered later.

Backed by `models/registry.jsonl` (git-ignored). Statuses: `planned` →
`experimental` → `candidate` → `approved`, or `deprecated`/`rejected`.

The Real Voice Model Engine milestone (`docs/REAL_VOICE_MODEL_ENGINE.md`)
added optional fields for a real training/artifact pipeline —
`architecture`, `lifecycle_state` (see `pipeline/model_lifecycle.py`),
`sample_rate`, `channels`, `preprocessing_version`, `embedding_model_ref`,
`generation_model_ref`, `training_config_hash`, `source_job_id`,
`artifact_checksum` (see `pipeline/model_artifact.py`) — every existing
registry entry remains valid unchanged; these are populated only once a
real training job or artifact actually produces them.

## Experiment tracking

[`registry/experiment_registry.py`](../src/aarya_voice_lab/registry/experiment_registry.py),
schema at [`experiment.schema.json`](../schemas/experiment.schema.json).

Each record captures experiment ID, timestamp, **dataset version**,
model + version, configuration, preprocessing version, training
configuration, **hardware**, **software versions**, metrics, benchmark
references, status, and notes.

The goal is reproducibility: enough recorded state to explain *why* two
runs differed. Hardware and software versions are included because
"same config, different result" is usually neither — it's a different
torch build or a different GPU. `aarya-voice system-info --json` produces
the hardware block directly.

Backed by `experiments/registry.jsonl` (git-ignored — experiment records
reference private dataset versions).

## VoiceService contract

[`voice_service.py`](../src/aarya_voice_lab/voice_service.py) defines the
stable interface AARYA Core would eventually consume:

```python
list_voice_profiles() -> list[VoiceProfile]
get_voice_profile(voice_id) -> VoiceProfile
synthesize(SynthesisRequest) -> SynthesisResult
health() -> HealthStatus
get_model_info(voice_id) -> dict
```

`VoiceProfile` carries `requires_permission`, so Core can enforce
`voice.private.use` without knowing anything about which TTS engine is
behind the interface.

**No provider is implemented.** The class is abstract and cannot be
instantiated — asserted by test. **AARYA Core is not modified, imported,
or integrated with in this repository.**
