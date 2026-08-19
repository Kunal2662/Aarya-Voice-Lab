# Data Privacy & Handling Rules

These rules govern all work in this repository. They are not
recommendations. If a task appears to require violating one, **stop and
escalate** rather than working around it.

---

## The material

31 private recordings containing two speakers:

- the **operator** (project owner), and
- the **target female speaker**, who is deceased and whose voice is
  authorized for the Private Voice model.

The recordings are mostly **Marathi**. They are the sole source material
for the Private Voice and cannot be re-recorded or replaced. Their
irreplaceability is why the handling rules below are strict.

**As of Phase 0, none of these recordings have been accessed, copied,
inspected, transcribed, diarized, or processed in any way.** They are not
present in this repository or its environment.

---

## Absolute rules

### 1. Never commit private material to Git

The following must never appear in Git history:

- original recordings, extracted audio, or processed audio
- private voice datasets or dataset manifests built from real recordings
- speaker embeddings or voice fingerprints
- generated private-voice samples
- model checkpoints containing private voice information
- private voice models
- secrets, credentials, or API keys

Enforced by the root `.gitignore`, by
`aarya_voice_lab.security.source_protection`, and by tests that ask Git
itself whether the protected paths are actually ignored.

**Git history is effectively permanent.** A private recording committed
once and "deleted" in a later commit is still in the history, still in
every clone, and still on any remote it reached. There is no clean
recovery — prevention is the only control that works.

### 2. Never upload private material

No script, CLI command, test, CI job, or dependency in this repository
may transmit source material or derived private data to any network
destination. This includes:

- cloud storage and file-sharing services
- hosted transcription/diarization/TTS APIs
- crash reporters, telemetry, and analytics
- model hubs (including "private" repositories)
- pastebins, gists, and diagram/rendering services

If a tool requires uploading audio to function, **it is disqualified** —
see [TOOLCHAIN.md](TOOLCHAIN.md).

This rule shaped a concrete engineering decision: JSON Schema validation
resolves all `$ref`s from local files and **refuses** remote resolution,
so validating a manifest can never quietly make a network request.

### 3. Originals are immutable

Once introduced, original recordings are read-only. Never edit,
re-encode, denoise, trim, rename, or overwrite them in place. Every
transformation writes a *new* derived artifact and records its
provenance. A destructive operation on the originals is unrecoverable.

### 4. Processing requires explicit approval

Phase 0 defines architecture only. Diarization, transcription,
extraction, dataset construction, and training against the real
recordings begin only in an explicitly approved later phase. The future
CLI commands for these operations are stubs that refuse to run.

### 5. Derived data inherits the same protection

A transcript, an embedding, a 3-second segment, or a fine-tuned
checkpoint derived from the recordings is **just as private as the
recordings**. A voice model in particular can reproduce the speaker's
voice — treat it as equivalent to the source material, not as a
derivative work with relaxed handling.

### 6. Local-first, always

The project must function without any cloud API. Cloud providers may
never become a requirement. ElevenLabs, Google Cloud TTS, Azure TTS,
Amazon Polly and equivalents are **not used in Phase 0** and must never
be on the path for the Private Voice.

---

## Ethical position

The target speaker is deceased and cannot consent to new uses of her
voice. The authorization covering this project is narrow and personal.
That imposes obligations beyond what the technical rules encode:

- The Private Voice is for the authorized private purpose only — not for
  demos, marketing, public samples, or distribution.
- No synthesized output should be presented as a genuine recording of
  the speaker.
- Access stays restricted to AARYA administrators
  ([SECURITY.md](SECURITY.md)), and use is audit-logged.
- The narrowest viable dataset is preferable to the largest one. If a
  segment is doubtful, exclude it.

---

## If something goes wrong

**Stop immediately and report** if:

- real recordings appear unexpectedly in the working environment
- private material has been committed or pushed
- a tool or dependency requires cloud upload or credentials
- a proposed operation would modify or destroy the originals
- a model would embed private voice data in an unsafe or distributable way

Do not attempt to quietly clean up a leak to a remote by force-pushing
over it: the exposure has already occurred and needs to be handled
deliberately, including credential/access review and a decision about the
remote's history.
