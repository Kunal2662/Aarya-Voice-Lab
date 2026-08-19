# `experiments/` — Experiment Tracking

Local storage for experiment run records (see `docs/MODEL_STRATEGY.md` and
`src/aarya_voice_lab/schemas/experiment.py`). Each experiment record tracks
configuration, dataset version, hardware/software environment, and results
for reproducibility — schema only in Phase 0, no real experiments have run.

Everything under this directory except `README.md` is git-ignored: run
records may reference private dataset versions and must not be committed.
Use `aarya-voice experiment --help` for the (Phase 0 stub) CLI surface.
