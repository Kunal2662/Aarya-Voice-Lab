# `datasets/` — Derived / Working Datasets

This directory is the (future) working area for datasets derived from
`source/` material during the pipeline described in
`docs/DATASET_PIPELINE.md` — candidate segments, quality-filtered subsets,
transcribed/aligned data, and the final verified dataset used for voice
model experiments.

It is currently **empty**. Phase 0 creates no datasets and processes no
recordings.

## Protection rules

- Everything under `datasets/` (except this README) is excluded via the
  root `.gitignore` — real dataset content is never committed.
- Only files under `manifests/templates/` (synthetic/example data) are
  tracked in Git. Real manifests generated from actual processing runs
  stay local and git-ignored, matching the same rule applied to
  `manifests/`.
- Each dataset version must remain traceable back to source recording ID,
  timestamps, speaker, and verification status per the schema in
  `schemas/segment.schema.json` — but that traceability lives in local
  metadata, not in Git, until an explicit, approved step decides
  otherwise.
- No dataset built from the 31 private recordings may be uploaded to a
  third-party service.

See also: `source/README.md`, `docs/PRIVACY.md`, `docs/DATASET_PIPELINE.md`.
