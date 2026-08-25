"""Task 1 of the Phase 4 autonomous execution plan -- ML runtime
readiness audit.

Audited: LocalTrainingProvider, LocalNeuralEmbeddingProvider, runtime
detection (identity.runtime), env-nemo path resolution, the generation
runtime (LocalNeuralVoiceGenerator), the embedding provider registry,
and calibration_engine's relationship to these providers.

Finding (fixed by this task): `identity.embeddings._ENV_NEMO_PYTHON` was
hardcoded to the POSIX `bin/python` venv layout
(`.envs/env-nemo/bin/python`), unlike `pipeline.runner.EnvironmentPaths`,
which already resolves `Scripts/python.exe` first on Windows and falls
back to `bin/python`. This meant a real `.envs/env-nemo` built on native
Windows would never be found by the embedding provider, regardless of
whether it was genuinely built -- a real, environment-specific
correctness defect, not a test artifact. Fixed by resolving through
`pipeline.runner.default_environment_root()` instead of a hardcoded
path, anchored to PROJECT_ROOT (not `Path.cwd()`) to preserve the
original path semantics.

No other instance of the same bug class was found:
LocalNeuralVoiceGenerator and LocalTrainingProvider both detect
capability via `importlib.metadata` in-process (no subprocess bridge, no
hardcoded venv path), so they were never affected. calibration_engine.py
does not reference any ML provider's capability state at all -- hardware
detection (GPU/CPU/RAM) and ML runtime capability are, and remain,
separate concerns; no missing integration was found.

CPU path: real, verified (all three providers correctly report their
honest state on CPU-only hardware, confirmed empirically on this
checkout -- no torch, no nemo_toolkit, .envs/env-nemo not built).
GPU path: declared as vocabulary only (ComputeBackend enum), never
exercised for real in this environment -- no GPU-resident ML process
exists anywhere in this project, consistent with prior audits.
No provider was faked or forced to report AVAILABLE; this task changed
only how an already-real check resolves its interpreter path.
"""

from __future__ import annotations

from aarya_voice_lab.environment.specs import EnvironmentId
from aarya_voice_lab.identity.embeddings import _ENV_NEMO_PYTHON
from aarya_voice_lab.pipeline.runner import default_environment_root


def test_env_nemo_python_path_is_anchored_to_project_root():
    """Must resolve under the real project root, never under whatever
    the current working directory happens to be at import time -- a
    Path.cwd()-relative path would silently break when this module is
    imported from a different working directory."""
    from aarya_voice_lab.core.paths import PROJECT_ROOT

    assert str(_ENV_NEMO_PYTHON).startswith(str(PROJECT_ROOT))


def test_env_nemo_python_prefers_windows_layout_when_present(tmp_path):
    fake_env_root = tmp_path / ".envs" / "env-nemo"
    windows_python = fake_env_root / "Scripts" / "python.exe"
    windows_python.parent.mkdir(parents=True)
    windows_python.touch()

    resolved = default_environment_root(EnvironmentId.NEMO, base=tmp_path).python
    assert resolved == windows_python


def test_env_nemo_python_falls_back_to_posix_layout(tmp_path):
    fake_env_root = tmp_path / ".envs" / "env-nemo"
    posix_python = fake_env_root / "bin" / "python"
    # No Scripts/python.exe created -- only the POSIX layout exists.
    resolved = default_environment_root(EnvironmentId.NEMO, base=tmp_path).python
    assert resolved == posix_python


def test_env_nemo_python_matches_the_same_resolution_pipeline_runner_uses():
    """The embedding provider's interpreter path and the generic
    pipeline environment-path resolver must never diverge -- this is
    what this task's fix actually wired together."""
    from aarya_voice_lab.core.paths import PROJECT_ROOT

    expected = default_environment_root(EnvironmentId.NEMO, base=PROJECT_ROOT).python
    assert _ENV_NEMO_PYTHON == expected


def test_local_training_provider_reports_honest_state_without_fabrication():
    from aarya_voice_lab.pipeline.training import LocalTrainingProvider, TrainingProviderState

    provider = LocalTrainingProvider()
    capabilities = provider.capabilities()
    # No torch/nemo_toolkit is installed on any CI/dev checkout this
    # project's own documentation describes -- if this ever becomes
    # AVAILABLE for real, that is a genuine environment change, not
    # something this test should special-case around.
    assert capabilities.state in (TrainingProviderState.AVAILABLE, TrainingProviderState.NOT_CONFIGURED)
    if capabilities.state is TrainingProviderState.NOT_CONFIGURED:
        assert capabilities.missing_requirements


def test_local_neural_voice_generator_uses_in_process_detection_only():
    """Confirms this provider is not affected by the env-nemo-style
    subprocess path bug: it has no isolated-environment interpreter path
    to resolve at all."""
    from aarya_voice_lab.pipeline.generation import LocalNeuralVoiceGenerator

    generator = LocalNeuralVoiceGenerator()
    assert not hasattr(generator, "_run_worker")


def test_embedding_provider_registry_lists_both_synthetic_and_real():
    from aarya_voice_lab.identity.embeddings import SyntheticEmbeddingProvider, available_providers

    names = available_providers()
    assert SyntheticEmbeddingProvider.name in names
    assert "local-neural-embedding" in names


def test_calibration_engine_does_not_reference_ml_provider_state():
    """Documents the audited boundary: hardware calibration and ML
    runtime capability are separate concerns by design, not a missing
    integration."""
    import inspect

    from aarya_voice_lab.pipeline import calibration_engine

    source = inspect.getsource(calibration_engine)
    for forbidden in ("LocalNeuralEmbeddingProvider", "LocalTrainingProvider", "any_real_provider_available"):
        assert forbidden not in source
