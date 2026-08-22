#!/usr/bin/env python3
"""Real ML Runtime & Model Integration milestone -- register the real,
already-verified TitaNet-large checkpoint as a checksum-addressed
`ModelArtifact` and a `ModelRegistry` entry.

This does not download, train, or fabricate anything. It expects the
checkpoint NeMo itself already fetched and cached while building
`.envs/env-nemo` (see docs/NEMO.md) -- this script only copies those
existing bytes into this project's own checksum-addressed, git-ignored
`data/model_artifacts/` store (pipeline/model_artifact.py) and records a
provenance entry in `models/registry.jsonl` (registry/model_registry.py),
both already git-ignored. Re-running this script is a safe no-op once
the artifact is already registered -- `ArtifactStore.save()` refuses to
overwrite an existing checksum, and this script treats that refusal as
"already registered", not an error.

Usage:
    python scripts/register_real_model_artifacts.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from aarya_voice_lab.core.data_root import DataRoot  # noqa: E402
from aarya_voice_lab.identity.embeddings import LocalNeuralEmbeddingProvider  # noqa: E402
from aarya_voice_lab.pipeline.model_artifact import (  # noqa: E402
    ArtifactError,
    ArtifactStore,
    ModelArtifactFormat,
    ModelArtifactType,
)
from aarya_voice_lab.pipeline.model_lifecycle import ModelLifecycleState  # noqa: E402
from aarya_voice_lab.registry.model_registry import ModelRegistry  # noqa: E402

# The exact NeMo cache path this checkpoint lands in once `from_pretrained`
# has resolved it, per NeMo's own cache layout (NGC key embedded in the
# path -- see docs/NEMO.md). Not something this project controls or can
# predict for a different model; this script is specific to TitaNet-large.
NEMO_CACHE_GLOB = "titanet-l/*/titanet-l.nemo"


def _find_cached_checkpoint() -> Path | None:
    cache_root = Path.home() / ".cache" / "torch" / "NeMo" / "NeMo_3.0.0"
    matches = sorted(cache_root.glob(NEMO_CACHE_GLOB))
    return matches[0] if matches else None


def main() -> int:
    provider = LocalNeuralEmbeddingProvider()
    state = provider.capability_state()
    if state["state"] != "AVAILABLE":
        print(f"local-neural-embedding is not AVAILABLE ({state}); nothing to register.")
        return 1

    checkpoint_path = _find_cached_checkpoint()
    if checkpoint_path is None:
        print(f"no cached checkpoint found under ~/.cache/torch/NeMo/NeMo_3.0.0/{NEMO_CACHE_GLOB}")
        return 1

    payload = checkpoint_path.read_bytes()
    print(f"read {len(payload):,} bytes from {checkpoint_path}")

    data_root = DataRoot.default().create()
    artifact_store = ArtifactStore(data_root)
    try:
        artifact = artifact_store.save(
            payload,
            artifact_format=ModelArtifactFormat.NEMO_CHECKPOINT,
            artifact_type=ModelArtifactType.EMBEDDING_MODEL_WEIGHTS,
            model_name=provider.model_name,
            model_version=provider.version,
            provider_name=provider.name,
            lifecycle_state=ModelLifecycleState.AVAILABLE,
            compatibility_metadata={
                "sample_rate": 16000,
                "embedding_dimension": provider.dimension,
                "architecture": "titanet",
            },
        )
        print(f"stored artifact {artifact.artifact_id} (checksum {artifact.checksum_sha256})")
    except ArtifactError as exc:
        if "already exists" not in str(exc):
            raise
        import hashlib

        checksum = hashlib.sha256(payload).hexdigest()
        from aarya_voice_lab.pipeline.model_artifact import artifact_id_from_checksum

        artifact = artifact_store.load_metadata(artifact_id_from_checksum(checksum))
        print(f"artifact already registered as {artifact.artifact_id} -- leaving it as-is")

    registry = ModelRegistry()
    existing = registry.get(provider.model_name)
    if existing is not None:
        print(f"model registry already has an entry for {provider.model_name!r} -- leaving it as-is")
        return 0

    registry.add(
        {
            "schema_version": "0.1.0",
            "model_name": provider.model_name,
            "version": provider.version,
            "provider": "nvidia-nemo",
            "model_type": "other",
            # Speaker embedding is a spectral/prosodic task, not a
            # content-language task, so this is not a claim of accuracy
            # per language -- it records what is actually known: English
            # is the dominant training-corpus language (Fisher, SWBD,
            # LibriSpeech), Hindi/Marathi are UNVALIDATED by this project
            # (no real Hindi/Marathi recording has been embedded here --
            # see docs/REAL_ML_RUNTIME_INTEGRATION.md language audit).
            "language_capability": ["en (training corpus)", "hi (unvalidated)", "mr (unvalidated)"],
            "hardware_requirements": {"min_vram_gb": 0, "cpu_only_supported": True},
            "model_hash": artifact.checksum_sha256,
            "source": "https://catalog.ngc.nvidia.com/orgs/nvidia/teams/nemo/models/titanet_large",
            "license": "NVIDIA (see NGC model card -- non-commercial research/evaluation terms; "
            "not redistributed by this project, fetched directly from NGC)",
            "training_dataset_version": "Fisher, Switchboard, LibriSpeech, VoxCeleb1, VoxCeleb2 (NVIDIA-trained)",
            "benchmark_results": None,
            "status": "approved",
            "architecture": "titanet",
            "lifecycle_state": ModelLifecycleState.AVAILABLE.value,
            "sample_rate": 16000,
            "channels": 1,
            "preprocessing_version": None,
            "embedding_model_ref": None,
            "generation_model_ref": None,
            "training_config_hash": None,
            "source_job_id": None,
            "artifact_checksum": artifact.checksum_sha256,
            "security_metadata": None,
        }
    )
    print(f"registered model_registry entry for {provider.model_name!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
