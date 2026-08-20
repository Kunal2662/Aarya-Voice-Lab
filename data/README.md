# `data/` — Pipeline Data Root

All pipeline input and output lives here. **Everything except this README
is git-ignored**, because every subdirectory can contain private voice
material or artifacts derived from it.

The directory is currently **empty of audio**. Phase 2 built and tested
the pipeline entirely on synthetic, generated audio; the real recordings
have not been accessed.

## Layout

| Directory | Contents | Writable? |
|---|---|---|
| `source/` | Original recordings, organised by batch | **NO — read-only** |
| `working/` | Derived intermediates: normalized audio, analyses, stage results | Yes |
| `segments/` | Derived candidate audio segments | Yes |
| `manifests/` | Machine-readable stage contracts and batch metadata | Yes |
| `reports/` | Human-readable summaries | Yes |
| `review/` | Manual-review metadata | Yes |
| `cache/` | Disposable working data | Yes |

## `source/` is immutable

Originals are never modified, moved, renamed, re-encoded, or deleted.
The speaker is deceased; these recordings cannot be remade, so a
destructive mistake is unrecoverable.

This is enforced in code, not just by convention:

- `assert_source_writable()` raises `SourceImmutabilityError` for any
  write whose destination resolves inside `source/`, and every stage that
  writes an artifact calls it.
- The inventory stage refuses to *read* `source/` unless an explicit
  approval flag is passed.
- After any run that reads source files, their SHA-256 hashes are
  re-verified; a change halts processing for that file.

Derived audio always becomes a **new file** in `working/` or `segments/`.

## Batches

Recordings are organised as `batch-001`, `batch-002`, … so new material
can be added later without reprocessing or redesigning anything. Nothing
in the pipeline is written around a fixed number of files.

```
data/source/batch-001/…          originals for that batch
data/working/batch-001/run/      stage results
data/manifests/batch-001/        batch.json, inventory, candidate manifest
```

## Never commit

Recordings, normalized or segmented audio, embeddings, model weights,
transcripts of private material, or credentials. See
[`docs/PRIVACY.md`](../docs/PRIVACY.md).
