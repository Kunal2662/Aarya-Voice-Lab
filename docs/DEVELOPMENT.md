# Development Guide

## Setup

```bash
python -m venv .venv          # Python 3.11-3.13; prefer 3.12
source .venv/bin/activate
pip install -e ".[dev]"
```

Installs only `pyyaml`, `jsonschema`, `psutil` plus dev tools. **Do not
install anything from `requirements/audio.txt`, `diarization.txt`,
`transcription.txt`, or `tts.txt`** — those belong to later, approved
phases and to *separate* virtualenvs
([ENVIRONMENT.md](ENVIRONMENT.md)).

## Checks

```bash
pytest                        # 148 tests
ruff check .
ruff format .
aarya-voice validate-environment
```

All tests use synthetic fixtures. **No test may reference, require, or
create real audio.** A test needing real recordings to pass is a design
error.

## Git safety workflow

**Before every commit:**

```bash
git status                              # only intended files?
git diff --cached                       # review actual content
aarya-voice validate-environment        # scans tracked + staged files
pytest tests/test_source_protection.py
```

Confirm explicitly that the commit contains **no** recordings or audio,
datasets or real manifests, model checkpoints, embeddings or
fingerprints, secrets or credentials, and no large binaries.

The protection is layered because any single layer can be bypassed:

| Layer | Catches |
|---|---|
| `.gitignore` | Files matching private patterns |
| `source_protection.classify_path` | Audio/model/secret-like paths |
| `scan_git_repo` | Anything already tracked or staged |
| `test_git_actually_ignores_private_paths` | Rules present but *ineffective* |
| `test_documentation_and_templates_remain_trackable` | Over-broad rules hiding needed docs |

That last test exists because it caught a real bug: `source/README.md`
and `datasets/README.md` were themselves ignored, so the mandatory
protection documentation would never have been committed.

**Never** use `git add -A` blindly, `git add -f` on an ignored file, or
`--no-verify`. If a legitimate file is being ignored, add a narrow
explicit exception — never loosen a protection pattern.

If private material has already been committed, **stop and report**. Do
not quietly force-push over it; see [PRIVACY.md](PRIVACY.md).

## Conventions

- Format with `ruff`; 120-char lines.
- Type hints on public functions.
- Comments explain **why**, not what. Most code needs none.
- Mark unimplemented capabilities **PLANNED**, explicitly. Never describe
  something as working when it isn't — the phase boundaries in this
  project depend on that being reliable.

## Adding a schema

1. Add `schemas/<name>.schema.json` with `additionalProperties: false`.
2. Add the name to `SchemaName` in `schemas/base.py`.
3. Add a builder in `schemas/records.py`.
4. Add a synthetic example in `manifests/templates/`.
5. Add tests for both valid and **invalid** records.

Cross-schema `$ref`s must resolve **offline**. The registry in
`schemas/base.py` refuses network resolution — a `$ref` to a remote URL
will raise rather than fetch. This is deliberate: a validator that
silently makes network calls would violate the project's local-first
guarantee.

Schemas are versioned via `SCHEMA_VERSION`; bump it on incompatible
changes.

## Branch

Development happens on `claude/aarya-voice-lab-foundation-kx265d`.

## What not to do

- Don't add cloud provider integrations.
- Don't implement pipeline stages before their phase is approved.
- Don't weaken the speaker safety policy toward accepting more data.
- Don't add abstraction for decisions that haven't been identified.
- Don't touch AARYA Core or AARYA Frontend from this repository.
