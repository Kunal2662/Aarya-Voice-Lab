# `public_datasets/` — Third-Party Licensed Datasets

This directory holds the local **Public Dataset Registry**
(`registry.jsonl`, git-ignored) and any acquired third-party dataset
content used for training-pipeline development, model experimentation,
generic voice development, or benchmark development.

See [`docs/DATA_POLICY.md`](../docs/DATA_POLICY.md) for the full policy.

## This is a separate track from `datasets/` and `source/`

- `source/` and `datasets/` hold material **derived from the 31 private
  recordings** — the consented real-person track.
- `public_datasets/` holds **third-party, publicly licensed** material —
  a completely different track with different rules.

These tracks must never be mixed. Code that reads one must never
silently also read the other.

## Rules

- Everything under `public_datasets/` (except this README) is
  git-ignored — real third-party dataset content is never committed.
- **A dataset being downloadable does not mean it is approved for use.**
  Every entry in the registry starts at `status: "registered"` (metadata
  only, grants no usage rights) and only becomes usable once its
  `status` is `"approved"` — see
  `aarya_voice_lab.registry.dataset_registry.PublicDatasetRegistry`.
- Every registry entry must record its actual source, license, and the
  specific uses that license permits — never inferred from "it was
  downloadable."
- No consented real-person or private-recording data may ever be
  registered here.
