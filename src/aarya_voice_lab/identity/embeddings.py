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
from aarya_voice_lab.core.paths import PROJECT_ROOT

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


#: The isolated env-nemo interpreter this provider bridges to. Never
#: imported directly -- nemo_toolkit is deliberately not a base-interpreter
#: dependency (see module docstring). Communication happens entirely
#: through scripts/ml_workers/nemo_embedding_worker.py and two JSON files.
_ENV_NEMO_PYTHON = PROJECT_ROOT / ".envs" / "env-nemo" / "bin" / "python"
_NEMO_WORKER_SCRIPT = PROJECT_ROOT / "scripts" / "ml_workers" / "nemo_embedding_worker.py"

#: Telemetry opt-out, mirrored from scripts/disable_telemetry.sh so every
#: subprocess this provider launches carries it too, not only interactive
#: shells that remembered to `source` that script.
_NEMO_SUBPROCESS_ENV: dict[str, str] = {
    "WANDB_MODE": "offline",
    "WANDB_DISABLED": "true",
    "SENTRY_DSN": "",
    "NEMO_TELEMETRY_OPT_OUT": "1",
    "NVIDIA_ONE_LOGGER_DISABLED": "1",
    "OTEL_SDK_DISABLED": "true",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
}


class LocalNeuralEmbeddingProvider(EmbeddingProvider):
    """Real Voice Model Engine milestone -- a real, local speaker-
    embedding provider, bridging to NVIDIA NeMo's TitaNet-large model
    running in the isolated `.envs/env-nemo` interpreter (see
    `docs/NEMO.md`).

    This class performs no arithmetic of its own and imports nothing
    from `nemo_toolkit`/`torch` into the base interpreter -- exactly the
    isolation this module's docstring has always described ("real
    providers... communicate through the filesystem contract... never
    imported into the base interpreter"). Every call to `embed()` or
    `capability_state()` launches `_ENV_NEMO_PYTHON` as a subprocess
    running `scripts/ml_workers/nemo_embedding_worker.py`, with a
    controlled argv (no shell), a bounded timeout, a temp working
    directory, and captured stdout/stderr.

    `capability_state()` does not merely check that `nemo_toolkit` is
    importable -- it actually asks the worker to load TitaNet-large and
    reports AVAILABLE only if that succeeds (per the "the actual model
    must load successfully" rule). This costs several seconds; callers
    that need a cheap existence check should look at whether
    `_ENV_NEMO_PYTHON` exists first.

    If `.envs/env-nemo` was never built, or the worker cannot load the
    model, `embed()` raises `EmbeddingProviderError` naming exactly what
    failed -- it never falls back to `SyntheticEmbeddingProvider`'s
    arithmetic and never fabricates a vector.
    """

    name = "local-neural-embedding"
    version = "1.0.0"
    kind = ProviderKind.NEURAL
    #: TitaNet-large's real, published embedding dimension -- confirmed
    #: by actually loading the model (see docs/REAL_VOICE_MODEL_ENGINE.md).
    dimension = 192
    model_name = "titanet_large"
    #: Real, measured wall-clock model-load cost on the CPU-only host
    #: this was verified against (see docs/REAL_VOICE_MODEL_ENGINE.md) --
    #: informational only, never used to short-circuit a real check.
    PROBE_TIMEOUT_SECONDS = 90
    EMBED_TIMEOUT_SECONDS = 90

    def _run_worker(self, request: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        """The one place this class touches a subprocess. Controlled
        argv, controlled cwd, bounded timeout, captured output -- see
        module docstring and docs/REAL_VOICE_MODEL_ENGINE.md's security
        section."""
        import os
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory(prefix="nemo-embed-") as scratch:
            request_path = Path(scratch) / "request.json"
            response_path = Path(scratch) / "response.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")

            # Inherit the real environment (PATH etc. -- torch/NeMo's own
            # startup needs it) and layer the telemetry opt-outs on top,
            # never replace it wholesale.
            subprocess_env = {**os.environ, **_NEMO_SUBPROCESS_ENV}
            try:
                result = subprocess.run(  # noqa: S603 -- fixed argv, no shell, no untrusted input in argv itself
                    [str(_ENV_NEMO_PYTHON), str(_NEMO_WORKER_SCRIPT), str(request_path), str(response_path)],
                    cwd=scratch,
                    env=subprocess_env,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as exc:
                raise EmbeddingProviderError(
                    f"{self.name}: worker timed out after {timeout}s"
                ) from exc

            if not response_path.is_file():
                raise EmbeddingProviderError(
                    f"{self.name}: worker exited {result.returncode} with no response file — "
                    f"stderr: {result.stderr[-2000:]}"
                )
            response = json.loads(response_path.read_text(encoding="utf-8"))
            if not response.get("ok"):
                raise EmbeddingProviderError(f"{self.name}: {response.get('error', 'unknown worker failure')}")
            return response

    def capability_state(self) -> dict[str, Any]:
        """The honest, current state of this provider -- call this before
        `embed()` to decide whether to attempt it at all. Actually loads
        the real model in the isolated interpreter; this is not a cheap
        check."""
        if not _ENV_NEMO_PYTHON.is_file():
            return {
                "state": "NOT_CONFIGURED",
                "missing_requirements": ["env-nemo"],
                "detail": "`.envs/env-nemo` has not been built. Run `scripts/install_env.sh env-nemo --cpu` first.",
            }
        try:
            response = self._run_worker({"mode": "probe"}, timeout=self.PROBE_TIMEOUT_SECONDS)
        except EmbeddingProviderError as exc:
            return {"state": "ERROR", "detail": str(exc)}
        return {
            "state": "AVAILABLE",
            "detail": f"{response['model_name']} loaded in {response['model_load_seconds']}s",
            "model_load_seconds": response["model_load_seconds"],
        }

    def preprocessing_requirements(self) -> dict[str, Any]:
        return {"sample_rate": 16000, "channels": 1, "min_duration_seconds": 0.5}

    def embed(self, samples: list[int], sample_rate: int, *, bit_depth: int = 16) -> EmbeddingVector:
        errors = self.validate_samples(samples, sample_rate)
        if errors:
            raise EmbeddingProviderError(f"{self.name}: {'; '.join(errors)}")
        if bit_depth != 16:
            # Real limitation, stated honestly rather than risking a
            # mis-packed WAV file: every fixture/caller in this codebase
            # today uses 16-bit PCM (see testing.synthetic_audio), and
            # this bridge has only been verified against that width.
            raise EmbeddingProviderError(f"{self.name}: only 16-bit PCM is currently supported (got {bit_depth})")
        if not _ENV_NEMO_PYTHON.is_file():
            raise EmbeddingProviderError(
                f"{self.name} is not configured: `.envs/env-nemo` has not been built. "
                "Run `scripts/install_env.sh env-nemo --cpu` first."
            )

        import tempfile
        import wave

        with tempfile.TemporaryDirectory(prefix="nemo-embed-wav-") as scratch:
            wav_path = Path(scratch) / "input.wav"
            with wave.open(str(wav_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(bit_depth // 8)
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(struct.pack(f"<{len(samples)}h", *samples))

            response = self._run_worker(
                {"mode": "embed", "wav_path": str(wav_path)}, timeout=self.EMBED_TIMEOUT_SECONDS
            )

        return EmbeddingVector(
            values=tuple(response["values"]),
            provider_name=self.name,
            provider_version=self.version,
            provider_kind=self.kind,
            sample_rate=sample_rate,
            source_duration_seconds=len(samples) / sample_rate,
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


def any_real_provider_available() -> bool:
    """True only when a real (non-synthetic) embedding provider is
    genuinely installed and loadable on THIS interpreter right now.

    Never inferred from a provider class merely being registered --
    `LocalNeuralEmbeddingProvider` is always registered (see
    `_PROVIDERS` above) whether or not `.envs/env-nemo` was ever built,
    exactly so callers must ask each provider for its own real,
    current `capability_state()` rather than assuming installation from
    presence in this registry."""
    for name in available_providers():
        provider = get_provider(name)
        if provider.is_synthetic:
            continue
        state = provider.capability_state() if hasattr(provider, "capability_state") else None
        if state is not None and state.get("state") == "AVAILABLE":
            return True
    return False


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
