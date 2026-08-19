# `models/` — Model Storage

Local storage for trained/downloaded voice model artifacts, indexed by the
model registry (see `docs/MODEL_STRATEGY.md` and
`src/aarya_voice_lab/registry/model_registry.py`). No models exist yet —
Phase 0 defines the registry schema only.

## Two model classes

- **Default Voice** models — not derived from private recordings, may
  eventually be distributed more broadly within AARYA.
- **Private Voice** models — derived from the 31 recordings, carry
  additional security metadata (see `docs/SECURITY.md`), are
  admin-only, audit-logged, and must never leave protected storage.

Everything under this directory except `README.md` is git-ignored. Model
checkpoints, weights, and any file that could embed private voice
characteristics must never be committed to this repository.
