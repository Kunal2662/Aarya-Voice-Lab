# Data Policy — Three Separate Tracks

AARYA Voice Lab uses three distinct categories of data. They exist for
different purposes, are governed by different rules, and **must never be
mixed**. No code path may treat one track's data as another's.

| Track | Used for | Governed by |
|---|---|---|
| **Public licensed data** | Training-pipeline development, model experimentation, generic voice development, benchmark development | `public_datasets/` registry (`docs/DATA_POLICY.md`, this file) |
| **Synthetic data** | Deterministic tests, regression tests, architecture validation | `manifests/templates/`, `identity.embeddings.SyntheticEmbeddingProvider`, existing test fixtures |
| **Consented real-person data** | Authorized target-speaker enrollment, real speaker verification, personal voice creation/adaptation | `dataset_gate.py`, `identity/enrollment.py`, [`PRIVACY.md`](PRIVACY.md) |

## The core rule

**A dataset being publicly downloadable does not automatically mean it is
approved for training.** A license permits specific uses under specific
conditions — it must be read and recorded, not assumed from availability.

## Public licensed data — required metadata

Every public/third-party dataset the project registers must have its
following properties documented before it can be approved for any use:

- source (canonical URL, DOI, or publisher)
- version
- license (the actual identifier — never left blank to imply a
  permissive default)
- permitted uses (from this project's fixed use-category list; never
  inferred from "it is downloadable")
- prohibited uses, where the license states any
- language(s)
- speaker/identity metadata restrictions, if the dataset carries any
  per-speaker information
- provenance (how/when it was acquired)
- checksum, where practical
- citation, where the license/terms require attribution

This is recorded by
[`aarya_voice_lab.registry.dataset_registry.PublicDatasetRegistry`](../src/aarya_voice_lab/registry/dataset_registry.py),
following the same append-only, schema-validated pattern as the
experiment and model registries
([`schemas/public_dataset_registry.schema.json`](../schemas/public_dataset_registry.schema.json)).
A registered entry's `status` starts at `"registered"` and grants **no**
usage rights by itself — only `"approved"` clears the gate.

## Consented real-person data

Real-person data is the 31 authorized private recordings and anything
derived from them. It is never downloaded, never public, and is governed
entirely separately by [`PRIVACY.md`](PRIVACY.md),
[`DATASET_PIPELINE.md`](DATASET_PIPELINE.md)'s access gate
(`dataset_gate.py`), and [`PHASE3_IDENTITY.md`](PHASE3_IDENTITY.md)'s
enrollment/verification architecture. Nothing in this document changes
any of those rules, and nothing in the public-dataset registry may
reference or substitute for them.

## Pending decision: no external public dataset has been acquired

Training-pipeline validation work (see the autonomous execution record
that produced this file) considered using a real, well-documented public
corpus (VCTK, LibriSpeech, or similar) to exercise the pipeline against
non-synthetic audio. **No such dataset has been downloaded.** Two
separate gates apply, and neither has been cleared:

1. **Licensing decision** — even a permissively licensed corpus requires
   its license, permitted uses, and any speaker/identity restrictions to
   be read and recorded in the public dataset registry *before* use, per
   this document's core rule. That review has not been performed.
2. **Download authorization** — downloading any file (a multi-hundred-
   megabyte-to-gigabyte dataset archive, in this case) requires the
   repository owner's explicit permission, requested in chat and given
   as a clear yes, before it happens. That permission has not been
   sought or given.

Pipeline-validation work in the interim uses only repository-controlled
synthetic fixtures (`aarya_voice_lab.testing.synthetic_audio`,
`aarya_voice_lab.pipeline.dataset_adapter.FixtureDatasetAdapter`), which
belong to the synthetic track below, not this one. Registering and
approving a real public dataset remains a legitimate, well-scoped future
task once the owner decides to proceed.

## Synthetic data

Used throughout this project's own test suite and architecture
validation. It carries no license concerns and no privacy concerns by
construction (it is generated, not recorded from a real person), but it
also must never be presented as, or silently substituted for, real
public or real consented data — see the synthetic-provenance invariant
in [`PHASE3_IDENTITY.md`](PHASE3_IDENTITY.md).
