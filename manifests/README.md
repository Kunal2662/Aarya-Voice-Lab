# `manifests/` — Dataset Manifests

Real dataset manifests (produced by future pipeline runs) are local,
private, and git-ignored — they may reference private recording IDs,
timestamps, and transcripts.

`manifests/templates/` is the exception: it holds versioned, **synthetic**
example manifests used for documentation, schema validation tests, and
onboarding. Nothing under `templates/` is derived from real recordings.
