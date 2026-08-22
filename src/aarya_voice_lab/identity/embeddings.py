"""Embedding provider abstraction and protected storage.

An **embedding** here is a fixed-length vector summarising a voice. Real
providers (TitaNet, WeSpeaker, ...) are not installed and are not
implemented; this module defines the interface they will satisfy and
ships one deterministic synthetic provider for development and testing.

## The synthetic-provenance invariant

A synthetic embedding is arithmetic over waveform statistics. It is
**not** a speaker model and carries no information about human identity.
Every artifact derived from one is stamped `provider_is_synthetic=True`,
and that stamp propagates through profiles, verifications, and the
verified dataset. Downstream code refuses to treat synthetic-derived
results as real identity conclusions.

This mirrors the Phase 2 speaker boundary: rather than relying on people
remembering that the development provider is fake, the fakeness is
carried in the data and enforced by code.

## Biometric classification

A **real** embedding derived from the private recordings is a biometric
identifier of a deceased person. Current research shows voice
characteristics can be partially reconstructed from such vectors, so they
inherit every protection the recordings have: never committed, never
uploaded, never exported. Vectors live only under `data/embeddings/`;
manifests carry the hash and a relative path, never the numbers.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from aarya_voice_lab.core.data_root import DataRoot, assert_source_writable

#: Bump when a provider's output changes meaning; invalidates cached work.
SYNTHETIC_PROVIDER_VERSION = "1.0.0"
SYNTHETIC_EMBEDDING_DIMENSION = 64


class EmbeddingProviderError(RuntimeError):
    """Raised when an embedding cannot be produced."""


class SyntheticProvenanceError(PermissionError):
    """Raised when synthetic-derived data is used where real data is required.

    This is a safety stop, not a bug: it means something tried to treat a
    development artifact as a real identity conclusion.
    """


class ProviderKind(StrEnum):
    #: Deterministic arithmetic. Not a speaker model. Development only.
    SYNTHETIC = "synthetic"
    #: A real speaker-embedding model. None is implemented yet.
    NEURAL = "neural"


@dataclass(frozen=True)
class EmbeddingVector:
    """A vector plus the provenance needed to interpret it.

    `values` is deliberately a plain tuple of floats: no numpy dependency,
    so the base environment stays free of ML packages.
    """

    values: tuple[float, ...]
    provider_name: str
    provider_version: str
    provider_kind: ProviderKind
    sample_rate: int
    source_duration_seconds: float

    @property
    def dimension(self) -> int:
        return len(self.values)

    @property
    def is_synthetic(self) -> bool:
        return self.provider_kind is ProviderKind.SYNTHETIC

    def to_bytes(self) -> bytes:
        """Deterministic binary form, used for hashing and storage."""
        return struct.pack(f"<{len(self.values)}d", *self.values)

    def sha256(self) -> str:
        digest = hashlib.sha256()
        digest.update(self.to_bytes())
        # Provenance is part of identity: the same numbers from a different
        # provider are not the same embedding.
        digest.update(f"|{self.provider_name}|{self.provider_version}|{self.provider_kind}".encode())
        return digest.hexdigest()

    def metadata(self) -> dict[str, Any]:
        """Everything about the embedding EXCEPT the vector itself.

        This is what may appear in a manifest, log, or report.
        """
        return {
            "dimension": self.dimension,
            "provider_name": self.provider_name,
            "provider_version": self.provider_version,
            "provider_kind": self.provider_kind.value,
            "provider_is_synthetic": self.is_synthetic,
            "sample_rate": self.sample_rate,
            "source_duration_seconds": round(self.source_duration_seconds, 6),
            "sha256": self.sha256(),
        }


class EmbeddingProvider(ABC):
    """Contract every embedding provider satisfies.

    Real providers will subclass this inside their own isolated
    environment (`env-nemo`, `env-verify`) and communicate through the
    filesystem contract — they are never imported into the base
    interpreter, whose dependency set must stay ML-free.
    """

    name: str = "abstract"
    version: str = "0.0.0"
    kind: ProviderKind = ProviderKind.NEURAL
    dimension: int = 0

    @abstractmethod
    def embed(self, samples: list[int], sample_rate: int, *, bit_depth: int = 16) -> EmbeddingVector:
        """Compute an embedding for one mono PCM signal."""

    @property
    def is_synthetic(self) -> bool:
        return self.kind is ProviderKind.SYNTHETIC

    def preprocessing_requirements(self) -> dict[str, Any]:
        """What the caller must guarantee about the signal before calling
        `embed()` -- e.g. required sample rate, channel count, minimum
        duration. The base implementation declares no requirement; a real
        provider must override this with its model's actual constraints
        rather than silently accepting anything."""
        return {}

    def validate_samples(self, samples: list[int], sample_rate: int) -> list[str]:
        """Return validation error messages against
        `preprocessing_requirements()`; an empty list means the signal is
        acceptable to `embed()`. Providers with real requirements must
        override this -- the base implementation only checks for an
        empty or non-positive-rate signal, the two conditions `embed()`
        itself always rejects."""
        errors = []
        if not samples:
            errors.append("signal is empty")
        if sample_rate <= 0:
            errors.append(f"invalid sample rate: {sample_rate}")
        required_rate = self.preprocessing_requirements().get("sample_rate")
        if required_rate is not None and sample_rate != required_rate:
            errors.append(f"sample_rate must be {required_rate}, got {sample_rate}")
        return errors

    def is_compatible_with(self, other: EmbeddingProvider | dict[str, Any]) -> bool:
        """Whether an embedding from `other` can be meaningfully compared
        against one from this provider. Mirrors `cosine_similarity()`'s
        own name+version equality check, exposed here so a caller can ask
        the question before attempting a comparison."""
        other_name = other.name if isinstance(other, EmbeddingProvider) else other.get("provider_name")
        other_version = other.version if isinstance(other, EmbeddingProvider) else other.get("provider_version")
        return self.name == other_name and self.version == other_version

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "kind": self.kind.value,
            "dimension": self.dimension,
            "is_synthetic": self.is_synthetic,
            "preprocessing_requirements": self.preprocessing_requirements(),
        }


class SyntheticEmbeddingProvider(EmbeddingProvider):
    """Deterministic, dependency-free embeddings for development.

    Projects the waveform onto a fixed bank of cosine basis functions and
    normalises the result. Signals with different spectral content land in
    different directions, which is enough to exercise every code path in
    enrollment, matching, thresholds, and review.

    It is **not** a speaker model. It cannot distinguish two humans, and
    any similarity it reports is a statement about waveform shape, not
    identity. Its output is stamped synthetic so nothing downstream can
    quietly rely on it.
    """

    name = "synthetic-cosine-projection"
    version = SYNTHETIC_PROVIDER_VERSION
    kind = ProviderKind.SYNTHETIC
    dimension = SYNTHETIC_EMBEDDING_DIMENSION

    def __init__(self, dimension: int = SYNTHETIC_EMBEDDING_DIMENSION):
        self.dimension = dimension

    def embed(self, samples: list[int], sample_rate: int, *, bit_depth: int = 16) -> EmbeddingVector:
        if not samples:
            raise EmbeddingProviderError("cannot embed an empty signal")
        if sample_rate <= 0:
            raise EmbeddingProviderError(f"invalid sample rate: {sample_rate}")

        max_amplitude = 2 ** (bit_depth - 1) - 1
        count = len(samples)

        # Project onto a cosine bank. Frequencies are geometrically spaced
        # so low bands (where voice energy lives) get finer resolution.
        accumulators = [0.0] * self.dimension
        for index in range(self.dimension):
            frequency = 50.0 * (1.06 ** index)
            omega = 2.0 * math.pi * frequency / sample_rate
            real = 0.0
            imaginary = 0.0
            # Stride keeps cost bounded for long signals while staying
            # deterministic for a given input length.
            stride = max(count // 4000, 1)
            taken = 0
            for position in range(0, count, stride):
                value = samples[position] / max_amplitude
                angle = omega * position
                real += value * math.cos(angle)
                imaginary += value * math.sin(angle)
                taken += 1
            magnitude = math.sqrt(real * real + imaginary * imaginary) / max(taken, 1)
            accumulators[index] = magnitude

        norm = math.sqrt(sum(v * v for v in accumulators))
        values = tuple(v / norm for v in accumulators) if norm > 0 else tuple(accumulators)

        return EmbeddingVector(
            values=values,
            provider_name=self.name,
            provider_version=self.version,
            provider_kind=self.kind,
            sample_rate=sample_rate,
            source_duration_seconds=count / sample_rate,
        )


class LocalNeuralEmbeddingProvider(EmbeddingProvider):
    """Real Voice Model Engine milestone -- the provider boundary for a
    real, local speaker-embedding model, with genuine capability
    detection instead of a fabricated result.

    This class performs no arithmetic of its own and stamps nothing
    synthetic: `kind` is `ProviderKind.NEURAL`. It checks, via
    `importlib.metadata` (empirically, not assumed), for either of the
    two real candidates this project's own documentation already named
    (`docs/PHASE3_IDENTITY.md`'s module docstring: "TitaNet, WeSpeaker,
    …", via NVIDIA NeMo or a generic torch-based model). **Neither is
    installed in this interpreter.** Installing one is a separate,
    approval-gated step (`configs/default.yaml`'s
    `environments.env-nemo`), not something this class does on its own.

    So `embed()` here always raises `EmbeddingProviderError` naming
    exactly what is missing -- it never falls back to
    `SyntheticEmbeddingProvider`'s arithmetic and never fabricates a
    vector. This satisfies the "real provider behind the same
    abstraction, honest about unavailability" requirement without
    silently downloading a model or a dependency during this milestone.
    """

    name = "local-neural-embedding"
    version = "1.0.0"
    kind = ProviderKind.NEURAL
    #: TitaNet-family dimension, per NVIDIA's published model card --
    #: documented so a real implementation's output shape is already
    #: known and testable even before the model itself is installed.
    dimension = 192

    #: Distribution name -> what it would provide. Checked via
    #: importlib.metadata, never assumed present.
    CANDIDATE_DISTRIBUTIONS: dict[str, str] = {
        "nemo_toolkit": "NVIDIA NeMo (TitaNet speaker-embedding models)",
    }

    def _installed(self) -> dict[str, str | None]:
        import importlib.metadata

        found: dict[str, str | None] = {}
        for distribution in self.CANDIDATE_DISTRIBUTIONS:
            try:
                found[distribution] = importlib.metadata.version(distribution)
            except importlib.metadata.PackageNotFoundError:
                found[distribution] = None
        return found

    def capability_state(self) -> dict[str, Any]:
        """The honest, current state of this provider -- call this before
        `embed()` to decide whether to attempt it at all."""
        installed = self._installed()
        missing = sorted(name for name, version in installed.items() if version is None)
        if not missing:
            return {"state": "AVAILABLE", "detail": f"detected: {installed}"}
        return {
            "state": "NOT_CONFIGURED",
            "missing_requirements": missing,
            "detail": (
                "No real local speaker-embedding runtime is installed in this interpreter. "
                "See docs/NEMO.md for the env-nemo build; installing it is a separate, "
                "approval-gated step, not something this provider does on its own."
            ),
        }

    def preprocessing_requirements(self) -> dict[str, Any]:
        return {"sample_rate": 16000, "channels": 1, "min_duration_seconds": 0.5}

    def embed(self, samples: list[int], sample_rate: int, *, bit_depth: int = 16) -> EmbeddingVector:
        state = self.capability_state()
        if state["state"] != "AVAILABLE":
            raise EmbeddingProviderError(
                f"{self.name} is not configured: {state['detail']} "
                f"(missing: {state.get('missing_requirements', [])})"
            )
        # Unreachable in this environment (capability_state() above always
        # returns NOT_CONFIGURED here) -- present only so a future,
        # approved environment that installs nemo_toolkit has a single,
        # obvious place to add the real inference call, rather than this
        # class silently doing nothing.
        raise EmbeddingProviderError(  # pragma: no cover
            f"{self.name} reported AVAILABLE but no inference implementation exists yet — "
            "this is a real defect, not an expected NOT_CONFIGURED path."
        )


#: Provider registry. Real providers register themselves when their
#: environment is built; the base environment only ever sees the synthetic
#: one plus the honestly-NOT_CONFIGURED local-neural boundary above.
_PROVIDERS: dict[str, type[EmbeddingProvider]] = {
    SyntheticEmbeddingProvider.name: SyntheticEmbeddingProvider,
    LocalNeuralEmbeddingProvider.name: LocalNeuralEmbeddingProvider,
}


def register_provider(provider_class: type[EmbeddingProvider]) -> None:
    _PROVIDERS[provider_class.name] = provider_class


def available_providers() -> list[str]:
    return sorted(_PROVIDERS)


def get_provider(name: str) -> EmbeddingProvider:
    if name not in _PROVIDERS:
        raise EmbeddingProviderError(
            f"Unknown embedding provider {name!r}. Available: {available_providers()}. "
            "Real providers are not installed in this environment."
        )
    return _PROVIDERS[name]()


def cosine_similarity(a: EmbeddingVector, b: EmbeddingVector) -> float:
    """Cosine similarity, mapped to 0..1.

    Providers must match: comparing vectors from different providers is
    meaningless, and silently returning a number would invite exactly the
    kind of false confidence this project must avoid.
    """
    if a.provider_name != b.provider_name or a.provider_version != b.provider_version:
        raise EmbeddingProviderError(
            f"Refusing to compare embeddings from different providers: "
            f"{a.provider_name}@{a.provider_version} vs {b.provider_name}@{b.provider_version}"
        )
    if a.dimension != b.dimension:
        raise EmbeddingProviderError(f"dimension mismatch: {a.dimension} vs {b.dimension}")

    dot = sum(x * y for x, y in zip(a.values, b.values, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a.values))
    norm_b = math.sqrt(sum(y * y for y in b.values))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    raw = dot / (norm_a * norm_b)
    # Map [-1, 1] to [0, 1]; clamp guards floating-point overshoot.
    return max(0.0, min(1.0, (raw + 1.0) / 2.0))


def mean_embedding(vectors: list[EmbeddingVector]) -> EmbeddingVector:
    """Average several embeddings into one profile vector."""
    if not vectors:
        raise EmbeddingProviderError("cannot average an empty list of embeddings")
    first = vectors[0]
    for vector in vectors[1:]:
        if vector.provider_name != first.provider_name or vector.dimension != first.dimension:
            raise EmbeddingProviderError("cannot average embeddings from different providers")

    count = len(vectors)
    summed = [sum(v.values[i] for v in vectors) / count for i in range(first.dimension)]
    norm = math.sqrt(sum(x * x for x in summed))
    values = tuple(x / norm for x in summed) if norm > 0 else tuple(summed)

    return EmbeddingVector(
        values=values,
        provider_name=first.provider_name,
        provider_version=first.provider_version,
        provider_kind=first.provider_kind,
        sample_rate=first.sample_rate,
        source_duration_seconds=sum(v.source_duration_seconds for v in vectors),
    )


@dataclass
class StoredEmbedding:
    """A reference to a stored vector. Never contains the vector."""

    embedding_id: str
    relative_path: str
    sha256: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "embedding_id": self.embedding_id,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


class EmbeddingStore:
    """Protected on-disk storage for embedding vectors.

    Vectors are written only under `data/embeddings/`, which the root
    `.gitignore` excludes and a behavioural test verifies. There is
    deliberately **no export function**: no code path writes a vector
    outside the data root.
    """

    def __init__(self, data_root: DataRoot):
        self.data_root = data_root
        self.directory = data_root.root / "embeddings"

    def _path_for(self, embedding_id: str) -> Path:
        return self.directory / f"{embedding_id}.vec"

    def save(self, embedding_id: str, vector: EmbeddingVector) -> StoredEmbedding:
        path = self._path_for(embedding_id)
        # Defence in depth: a path bug must never reach the source tree.
        assert_source_writable(self.data_root, path)
        self.directory.mkdir(parents=True, exist_ok=True)
        path.write_bytes(vector.to_bytes())
        sidecar = self.directory / f"{embedding_id}.meta.json"
        sidecar.write_text(json.dumps(vector.metadata(), indent=2, sort_keys=True), encoding="utf-8")
        return StoredEmbedding(
            embedding_id=embedding_id,
            relative_path=str(path.relative_to(self.data_root.root)),
            sha256=vector.sha256(),
            metadata=vector.metadata(),
        )

    def load(self, embedding_id: str) -> EmbeddingVector:
        path = self._path_for(embedding_id)
        sidecar = self.directory / f"{embedding_id}.meta.json"
        if not path.is_file() or not sidecar.is_file():
            raise EmbeddingProviderError(f"embedding {embedding_id!r} not found in {self.directory}")

        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        raw = path.read_bytes()
        dimension = metadata["dimension"]
        values = struct.unpack(f"<{dimension}d", raw)

        vector = EmbeddingVector(
            values=values,
            provider_name=metadata["provider_name"],
            provider_version=metadata["provider_version"],
            provider_kind=ProviderKind(metadata["provider_kind"]),
            sample_rate=metadata["sample_rate"],
            source_duration_seconds=metadata["source_duration_seconds"],
        )
        if vector.sha256() != metadata["sha256"]:
            raise EmbeddingProviderError(
                f"embedding {embedding_id!r} failed integrity check — stored bytes do not match recorded hash"
            )
        return vector

    def exists(self, embedding_id: str) -> bool:
        return self._path_for(embedding_id).is_file()

    def list_ids(self) -> list[str]:
        if not self.directory.is_dir():
            return []
        return sorted(p.stem for p in self.directory.glob("*.vec"))

    def delete(self, embedding_id: str) -> bool:
        """Permanently remove a vector.

        Returns True if something was removed. The caller is responsible
        for writing the deletion to the audit log — the record of the
        deletion must survive the data.
        """
        removed = False
        for path in (self._path_for(embedding_id), self.directory / f"{embedding_id}.meta.json"):
            if path.is_file():
                path.unlink()
                removed = True
        return removed

    def delete_all(self) -> int:
        return sum(1 for embedding_id in self.list_ids() if self.delete(embedding_id))
