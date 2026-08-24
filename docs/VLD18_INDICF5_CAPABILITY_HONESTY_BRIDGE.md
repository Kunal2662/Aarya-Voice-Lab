# VL-D18 — IndicF5 Capability Honesty Bridge

AARYA Voice Lab only. Follows the VL-D0–D17 desktop UI series, but shifts
from that series' frontend-rendering pattern into the previously-pending
real TTS generation track. This is a **backend-only capability-detection**
milestone.

**Read this distinction before anything else, because this milestone is
easy to misread as more than it is:**

| Term | What it means here |
|---|---|
| **Capability detection** | What this milestone implements: honestly reporting, via `importlib.metadata` only, which of IndicF5's known Python dependencies are importable in this interpreter, and stating (as static text) that HuggingFace access and a `trust_remote_code` review are separately required. |
| **Real model access** | NOT part of this milestone. No HuggingFace credential exists or is created. No network request is made. No weights are downloaded. |
| **Real TTS generation** | NOT part of this milestone, and not unlocked by it. `generate_preview()` still unconditionally raises `GenerationBlockedError` in every scenario this milestone tests. |

## Current Generation Architecture

Built generically in VL-D5, unchanged in shape by this milestone:

```
identity.preview.PreviewProvider (abstract, VL-V0)
        ↓
pipeline.generation.VoiceGenerator
        ↓
   SyntheticVoiceGenerator (real, sine-tone)   LocalNeuralVoiceGenerator (real detection, zero inference)
        ↓
pipeline.generation.GenerationQueue → GenerationItem → PreviewArtifact
```

`LocalNeuralVoiceGenerator` is the provider boundary for a real, local
TTS backend — proven correct in shape by the sibling
`identity.embeddings.LocalNeuralEmbeddingProvider` (real, working, for
speaker embedding). No equivalent worker/inference implementation exists
for generation, and this milestone does not add one.

## Why This Milestone Exists

The VL-D17-preceding read-only audit found that
`LocalNeuralVoiceGenerator.get_capabilities()` checked for generic
`piper-tts`/`torch` presence — not what the *actually approved* candidate
(IndicF5) needs — and had no way to explain *why* it reports
`NOT_CONFIGURED`/`ERROR` beyond a bare state enum value. This mirrors the
exact "silent state, no honest explanation" gap VL-D17 already closed for
the training provider (`TrainingProviderCapabilities.detail`/
`.missing_requirements`). This milestone closes the same gap for
generation, without touching anything that requires model access.

## IndicF5 as Approved Candidate

Unchanged from `docs/TTS_MODELS.md`: **AI4Bharat IndicF5** remains the
sole candidate passing every hard filter (MIT weights, Marathi support,
reference-based cloning, commercial use permitted). Piper remains a
documented fallback candidate only — not installed, not substituted, and
still separately tracked in `requirements/tts.txt` and
`docs/TTS_MODELS.md`. This milestone does not alter that decision.

## Actual Dependency Detection

`LocalNeuralVoiceGenerator.CANDIDATE_DISTRIBUTIONS` changed from the
generic `{piper-tts, torch}` to IndicF5's actual documented dependencies:

```python
CANDIDATE_DISTRIBUTIONS: dict[str, str] = {
    "transformers": "HuggingFace Transformers (required to load IndicF5)",
    "torch": "PyTorch (required by IndicF5)",
    "soundfile": "soundfile (required for IndicF5 audio I/O)",
}
```

Detection remains exactly `importlib.metadata.version()` per distribution
— the same empirical, no-network, no-assumption mechanism already used
for the embedding and training providers. Nothing is installed by this
change; every dependency is still absent in every environment this
project runs in.

## Capability Detail Semantics

`GenerationCapabilities` gained two fields, mirroring
`TrainingProviderCapabilities`'s already-proven shape exactly:

```python
missing_requirements: tuple[str, ...] = field(default_factory=tuple)
detail: str = ""
```

`LocalNeuralVoiceGenerator.get_capabilities()` now returns:

- **No dependency installed** (the real state in every environment this
  project runs in today): `NOT_CONFIGURED`, `missing_requirements` names
  exactly the absent packages (sorted, e.g. `("soundfile", "torch",
  "transformers")`), `detail` names them and appends the access-boundary
  note below.
- **Some or all dependencies importable** (not true anywhere today, but
  handled honestly): `missing_requirements` shrinks or empties
  accordingly; state becomes `ERROR` (never `AVAILABLE`) once every
  dependency is present, because no inference implementation exists —
  `detail` says so explicitly.
- In **every** case, `detail` includes a static, informational sentence
  (`_INDICF5_ACCESS_NOTE`) — never a live check — stating that IndicF5 is
  the approved candidate, that its HuggingFace repository is gated, and
  that its `trust_remote_code=True` load requirement has not undergone
  the required security review.

## HuggingFace Access Boundary

Unchanged, and not tested for or probed by this milestone: IndicF5's
HuggingFace repository requires accepting a contact-sharing agreement
before weights can be downloaded (confirmed previously via a direct,
unauthenticated request returning HTTP 401). This milestone does not
read, write, or check for `HF_TOKEN` or any other credential — the
`detail` text about gating is static prose, true regardless of what
environment variables exist, and would remain accurate even if a
credential were later added (a credential resolves the access gate, not
the missing-dependency or trust_remote_code-review gates).

## `trust_remote_code` Review Boundary

IndicF5 loads with `trust_remote_code=True`, which executes arbitrary
code from the model repository on load. No code in this repository sets,
checks, or bypasses this flag — there is no model-loading code to set it
in. This milestone encodes the review requirement as documentation
(`_INDICF5_ACCESS_NOTE`'s text and this doc) only. **Building an actual
`trust_remote_code` gate/mechanism is explicitly deferred** to whichever
future milestone first writes real inference code — at that point the
repository code must be reviewed and the flag never set silently.

## Why Generation Remains Blocked

- `generate_preview()` is unmodified: it always raises
  `GenerationBlockedError`, in every dependency-presence scenario tested.
- `GenerationBackendState.AVAILABLE` is never returned by
  `get_capabilities()`, regardless of what `importlib.metadata` reports.
- No worker script, model-loading code, or inference code was written.
- No package was installed; no credential exists or was created; no
  network request was made; no model weights were downloaded.

## Tests

`tests/test_voice_model_engine.py`, all using `monkeypatch.setattr(importlib.metadata, "version", ...)` exactly as `test_environment_specs.py`'s established convention does — never a real install, never a network call:

1. `test_local_neural_voice_generator_reports_missing_indicf5_dependencies_honestly` — no dependency installed: `missing_requirements == ("soundfile", "torch", "transformers")`; `detail` names IndicF5, "gated", and "trust_remote_code"; state is `NOT_CONFIGURED`.
2. `test_local_neural_voice_generator_lists_only_the_actually_absent_dependencies` — `torch` simulated present: `missing_requirements == ("soundfile", "transformers")` only; state still not `AVAILABLE`.
3. `test_local_neural_voice_generator_all_dependencies_present_still_never_available` — all three simulated present: `missing_requirements == ()`, state is `ERROR` (never `AVAILABLE`), `detail` still names IndicF5, and `generate_preview()` still raises `GenerationBlockedError`.
4. `test_generation_capabilities_serializes_detail_and_missing_requirements` — `to_dict()` includes the new fields correctly; existing fields (`backend_state`, `compute_backend`, `supported_controls`) are unchanged in shape.
5. `test_generation_capabilities_defaults_stay_backward_compatible` — a construction call that never mentions the new fields (every pre-D18 call site) still works, defaulting to an empty tuple/string, never a fabricated value.

No existing test was modified, weakened, or removed.

## Acceptance Criteria

- `missing_requirements` always contains exactly the IndicF5 dependencies absent from `importlib.metadata`, sorted, never fabricated.
- `detail` always names IndicF5, its HuggingFace gating, and its `trust_remote_code` review requirement — in every dependency-presence scenario.
- `backend_state` is never `AVAILABLE`, under any simulated dependency state.
- `generate_preview()` continues to always raise `GenerationBlockedError`.
- No network call, credential read/write, or file download exists anywhere in the diff.
- `GenerationCapabilities` remains backward compatible — no existing call site (constructed with only `backend_state`/`compute_backend`/`supported_controls`) breaks.

## Security / Privacy Boundaries

- No code reads, writes, or checks for `HF_TOKEN` or any other credential.
- No network request exists anywhere in `pipeline/generation.py`.
- No model weights are downloaded, referenced by path, or assumed present.
- No `trust_remote_code` mechanism was implemented — the requirement is documentation only, deliberately deferred.
- `ArtifactStore`/model registry were not touched — no generation-model artifact entry was created.
- Detection remains 100% local and empirical (`importlib.metadata` only), exactly the same mechanism already used and trusted for the embedding and training providers.

## Explicit Future Work

Deliberately not started here:
- A real `trust_remote_code`-review-gated worker script (mirroring `scripts/ml_workers/nemo_embedding_worker.py`'s subprocess-isolation pattern) — requires the code to actually exist and be reviewed first.
- Building `env-tts` with IndicF5's real dependencies — requires an explicit `--i-have-approval` decision separate from this milestone.
- Rendering `generation_provider.detail`/`.missing_requirements` in `workspace-models.js` — the natural, still-smaller D17-style frontend follow-on; deliberately not bundled into this backend-only milestone.
- Any real generation, audio output, or model registry entry for a generation model.

## Environment Limitations

- Backend `pytest` could not be run: `.venv/bin/python` remains a broken symlink to a non-Windows path. Additionally, this audit discovered a more fundamental blocker for *any* attempt to run this module on native Windows Python — `aarya_voice_lab.core.file_lock` imports the POSIX-only `fcntl` module at import time, so even a from-scratch Windows interpreter cannot import `pipeline.generation` without a Linux/WSL-equivalent environment. This is a structural, pre-existing environment characteristic, not something introduced or fixable by this milestone.
- `ruff` is not installed anywhere on this machine (checked directly) — static-analysis verification for this diff was done manually: line-length checked against the project's configured 120-char limit (no violations), and the diff was read in full for unused imports, unreachable code, and f-string misuse (one f-string-without-placeholder was caught and fixed during implementation).
- `node`-based frontend verification is not applicable — no frontend files were touched by this milestone.
