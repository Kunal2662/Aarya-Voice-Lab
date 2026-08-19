# WhisperX Environment (`env-whisperx`)

Transcription and word alignment; candidate independent verification.

> ## ⚠ REQUIRES APPROVAL — NOT INSTALLED
>
> This environment cannot be built without an explicit sign-off, because
> installing it necessarily installs a **gated model dependency and a
> commercial API client**. Details below. `scripts/install_env.sh
> env-whisperx` refuses to run without `--i-have-approval`.

## Specification

| | |
|---|---|
| Python | 3.12 |
| torch | **2.8.0** (hard ceiling `~=2.8.0`, i.e. `<2.9`) |
| Package | `whisperx` 3.8.6 (BSD-2-Clause) |
| Requirements | `requirements/transcription.txt` |
| System deps | **FFmpeg required** |
| CPU fallback | Supported, slow |
| Credentials | **Required for diarization** |

### Transitive pins (from resolved metadata, 2026-08-19)

```
torch 2.8.0            torchaudio 2.8.0       torchvision 0.23.0
ctranslate2 4.8.1      faster-whisper 1.2.1   torchcodec 0.7.0
numpy 2.4.6            transformers 4.57.6    huggingface-hub <1.0.0
pyannote-audio 4.0.7   pyannoteai-sdk 0.4.0   nltk, pandas, omegaconf
```

## Why it is isolated from NeMo

WhisperX pins `torch~=2.8.0`. NeMo 3.0.0 resolves to torch 2.13.0 alone.
Co-installing **succeeds**, but silently drags torch down to 2.8.0 —
below NeMo's tested 2.11–2.12 matrix — and with NeMo's CUDA extra it
silently downgrades NeMo itself to 2.7.3. A successful install of the
wrong versions is more dangerous than a failed one. Full evidence in
[COMPATIBILITY.md](COMPATIBILITY.md).

## ⚠ The credential problem

Installing `whisperx` **always** installs:

1. **`pyannote-audio` 4.0.7** — its recommended pipeline,
   `pyannote/speaker-diarization-community-1`, is a **gated** HuggingFace
   model. Access requires an account, an access token, and accepting an
   agreement that **shares your contact information** and consents to
   marketing email.
2. **`pyannoteai-sdk` 0.4.0** — a client for the commercial pyannoteAI
   API, as a **mandatory** dependency.

This is structural. There is no WhisperX install that omits them.

### What is and isn't affected

| Use | Gate triggered? |
|---|---|
| Transcription + word alignment | **No** — Whisper/faster-whisper weights are ungated |
| Diarization via pyannote | **Yes** — token and agreement required |

Audio is processed **locally** either way; the token gates the *download*
of weights, not inference. Weights can be used fully offline after a
one-time authenticated fetch (CC-BY-4.0, git-lfs clone).

**Private audio must never be sent to a hosted pyannoteAI endpoint.**
That would be a cloud upload of private voice material — an absolute
violation of [PRIVACY.md](PRIVACY.md).

### Recommendation

Use WhisperX for **transcription and alignment only**. Keep NeMo
Sortformer as the diarization system — it is ungated and needs no
credentials. Adopting pyannote for independent speaker verification is a
decision that needs sign-off, and should be weighed against alternatives
that carry no account relationship.

**No credentials are configured, and none will be configured
automatically.**

## Verifying

```bash
aarya-voice whisperx-check
```

Exits **3** and prints STOP CONDITIONS covering the approval requirement,
the gated model, and the credential requirement. Exit 3 means "stop
condition", distinct from 1 ("environment broken").

## Other operational notes

- **FFmpeg is required**, unlike in the base environment — `whisperx-check`
  reports it NOT_AVAILABLE rather than OPTIONAL. See
  [ENVIRONMENT.md](ENVIRONMENT.md) for per-OS installation.
- **cuDNN 9** is expected (`ctranslate2` 4.8.1). A system cuDNN 8
  alongside torch's bundled cuDNN 9 causes segfaults in
  `OperationSet::finalize_internal()` rather than a clear error.
- **Marathi ASR quality is materially below English.** Expect transcripts
  to need correction at manual review
  ([DATASET_PIPELINE.md](DATASET_PIPELINE.md)).

## Not verified

- The environment has **not been built**; only dependency resolution was
  tested, on Python 3.11.15.
- No Whisper or pyannote weights downloaded; nothing has been run.
- Marathi transcription quality is unmeasured by this project.
