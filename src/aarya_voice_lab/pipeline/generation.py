"""Voice generation abstraction — VL-D5 §4–§7, §13, §17.

Builds directly on `identity.preview`'s VL-V0 contracts (`PreviewProvider`,
`PreviewArtifact`, `PreviewKind`) rather than a second, competing
generation interface — those types were written specifically so "later
phases can implement against a stable interface," and VL-D5 is that
later phase for the *preview* half of the loop (real generation of the
final voice is still out of scope; see the module docstring in
`identity/preview.py`).

`VoiceGenerator` is `PreviewProvider` plus three methods VL-D5's richer
workspace needs that Phase 3's contract-only stub never required:
`get_capabilities()`, `validate_request()`, `estimate_requirements()`.
No implementation here assumes a vendor, a GPU, or one inference engine
— `GenerationCapabilities.compute_backend` is
`identity.runtime.ComputeBackend`, the same vendor-neutral vocabulary
every other phase already uses.

`SyntheticVoiceGenerator` is the one concrete backend VL-D5 ships: it
writes a mathematically generated sine tone (via
`testing.synthetic_audio.generate_tone`, the project's one sanctioned
non-fixture-adjacent synthetic-audio generator) and returns a
`PreviewArtifact` with `kind=SYNTHETIC_FIXTURE`. **It never claims to
represent a real person's voice, and its output must never be confused
with `PreviewKind.GENERATED_SPEECH`** (still "PLANNED — never generated
yet," exactly as `identity/preview.py` already states).
"""

from __future__ import annotations

import hashlib
import json
from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from aarya_voice_lab.core.data_root import DataRoot, assert_source_writable
from aarya_voice_lab.identity.preview import PreviewArtifact, PreviewKind, PreviewProvider
from aarya_voice_lab.identity.runtime import ComputeBackend
from aarya_voice_lab.pipeline.contracts import sha256_file
from aarya_voice_lab.pipeline.resume import StageFingerprint
from aarya_voice_lab.testing.synthetic_audio import generate_tone

GENERATION_STAGE = "voice_generation"
GENERATION_VERSION = "1.0.0"
MAX_TEXT_LENGTH = 5000
SUPPORTED_SAMPLE_RATES = (16000, 22050, 44100)


class GenerationBackendState(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


class GenerationStatus(StrEnum):
    QUEUED = "QUEUED"
    PREPARING = "PREPARING"
    GENERATING = "GENERATING"
    POST_PROCESSING = "POST_PROCESSING"
    READY = "READY"
    WARNING = "WARNING"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


TERMINAL_STATUSES: frozenset[GenerationStatus] = frozenset(
    {
        GenerationStatus.READY,
        GenerationStatus.WARNING,
        GenerationStatus.FAILED,
        GenerationStatus.CANCELLED,
        GenerationStatus.BLOCKED,
    }
)


def is_terminal(status: GenerationStatus) -> bool:
    return status in TERMINAL_STATUSES


#: The full control surface VL-D5 §12 lists. A backend's
#: GenerationCapabilities.supported_controls is a subset of this — a
#: control absent from that subset must render NOT AVAILABLE, never a
#: fabricated default.
GENERATION_CONTROLS: frozenset[str] = frozenset(
    {"voice", "model", "speed", "pitch", "style", "expressiveness", "seed", "output_format"}
)


@dataclass(frozen=True)
class GenerationCapabilities:
    backend_state: GenerationBackendState
    compute_backend: ComputeBackend
    supported_controls: frozenset[str] = field(default_factory=frozenset)

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_state": self.backend_state.value,
            "compute_backend": self.compute_backend.value,
            "supported_controls": sorted(self.supported_controls),
        }


def _config_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PreviewRequest:
    """A versioned generation request. `request_id` is a sequential id,
    never derived from or dependent on a timestamp (§7)."""

    request_id: str
    text: str
    voice_profile_id: str
    model_id: str
    generation_profile_id: str | None = None
    sample_rate: int = 16000
    output_format: str = "wav"
    seed: int | None = None
    controls: dict[str, str] = field(default_factory=dict)

    @property
    def config_hash(self) -> str:
        return _config_hash(
            {
                "voice_profile_id": self.voice_profile_id,
                "generation_profile_id": self.generation_profile_id,
                "model_id": self.model_id,
                "sample_rate": self.sample_rate,
                "output_format": self.output_format,
                "seed": self.seed,
                "controls": self.controls,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "text": self.text,
            "voice_profile_id": self.voice_profile_id,
            "generation_profile_id": self.generation_profile_id,
            "model_id": self.model_id,
            "sample_rate": self.sample_rate,
            "output_format": self.output_format,
            "seed": self.seed,
            "controls": dict(self.controls),
            "config_hash": self.config_hash,
        }


_request_counter = 0


def build_preview_request(
    *,
    text: str,
    voice_profile_id: str,
    model_id: str,
    generation_profile_id: str | None = None,
    sample_rate: int = 16000,
    output_format: str = "wav",
    seed: int | None = None,
    controls: dict[str, str] | None = None,
) -> PreviewRequest:
    global _request_counter
    _request_counter += 1
    return PreviewRequest(
        request_id=f"preview-req-{_request_counter:05d}",
        text=text,
        voice_profile_id=voice_profile_id,
        model_id=model_id,
        generation_profile_id=generation_profile_id,
        sample_rate=sample_rate,
        output_format=output_format,
        seed=seed,
        controls=dict(controls or {}),
    )


class GenerationBlockedError(RuntimeError):
    """The request cannot be generated at all (backend unavailable,
    validation failed before generation began) — distinct from a
    WARNING (generated with a caveat) or FAILED (an unexpected error)."""


class VoiceGenerator(PreviewProvider):
    """`identity.preview.PreviewProvider`, extended with the capability/
    validation/estimation surface VL-D5's workspace needs. Still
    implements no real voice generation — see `identity/preview.py`."""

    @abstractmethod
    def get_capabilities(self) -> GenerationCapabilities:
        raise NotImplementedError

    @abstractmethod
    def validate_request(self, request: dict[str, Any]) -> list[str]:
        """Return validation error messages; an empty list means valid."""
        raise NotImplementedError

    @abstractmethod
    def estimate_requirements(self, request: dict[str, Any]) -> dict[str, Any]:
        """Return an honest estimate (e.g. duration), never a guarantee."""
        raise NotImplementedError


class SyntheticVoiceGenerator(VoiceGenerator):
    """The one concrete backend VL-D5 ships: a deterministic sine tone,
    clearly synthetic, never claimed to be anyone's voice."""

    name = "synthetic-tone"
    version = "0.1.0"

    def __init__(self, data_root: DataRoot) -> None:
        self._data_root = data_root

    def get_capabilities(self) -> GenerationCapabilities:
        return GenerationCapabilities(
            backend_state=GenerationBackendState.AVAILABLE,
            compute_backend=ComputeBackend.CPU,
            supported_controls=frozenset({"speed", "seed", "output_format"}),
        )

    def validate_request(self, request: dict[str, Any]) -> list[str]:
        errors = []
        text = request.get("text", "")
        if not text or not text.strip():
            errors.append("text must not be empty")
        elif len(text) > MAX_TEXT_LENGTH:
            errors.append(f"text exceeds {MAX_TEXT_LENGTH} characters")
        if request.get("sample_rate") not in SUPPORTED_SAMPLE_RATES:
            errors.append(f"sample_rate must be one of {SUPPORTED_SAMPLE_RATES}")
        controls = request.get("controls") or {}
        unsupported = set(controls) - self.get_capabilities().supported_controls
        if unsupported:
            errors.append(f"unsupported control(s): {sorted(unsupported)}")
        return errors

    def estimate_requirements(self, request: dict[str, Any]) -> dict[str, Any]:
        text = request.get("text", "") or ""
        word_count = len(text.split())
        # A rough, honestly-labelled heuristic (average speech rate) --
        # never presented as an exact duration (§11's "do not claim
        # exact duration unless backed by the backend").
        estimated_duration_seconds = round(word_count / 2.5, 2) if word_count else 0.0
        return {
            "word_count": word_count,
            "character_count": len(text),
            "estimated_duration_seconds": estimated_duration_seconds,
            "estimate_basis": "heuristic word-rate estimate, not measured",
        }

    def supports_regeneration(self) -> bool:
        return True

    def generate_preview(self, request: dict[str, Any]) -> PreviewArtifact:
        errors = self.validate_request(request)
        if errors:
            raise GenerationBlockedError("; ".join(errors))

        request_id = request["request_id"]
        seed = request.get("seed")
        text = request["text"]
        sample_rate = request["sample_rate"]

        # Deterministic per (text, config, seed) -- same request always
        # produces the same tone, never a random one.
        basis = seed if seed is not None else int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
        frequency_hz = 220.0 + (basis % 440)
        duration_seconds = min(max(len(text.split()) / 2.5, 0.5), 10.0)

        destination = self._data_root.previews / f"{request_id}.wav"
        assert_source_writable(self._data_root, destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise GenerationBlockedError(f"a preview already exists at {destination.name}; refusing to overwrite")

        generate_tone(
            destination, frequency_hz=frequency_hz, duration_seconds=duration_seconds, sample_rate=sample_rate
        )

        return PreviewArtifact(
            preview_id=f"{request_id}-preview",
            kind=PreviewKind.SYNTHETIC_FIXTURE,
            relative_path=f"previews/{destination.name}",
            sha256=sha256_file(destination),
            duration_seconds=duration_seconds,
            sample_rate=sample_rate,
            origin_id=request_id,
            model_name=self.name,
            model_version=self.version,
            is_synthetic=True,
        )


class UnavailableVoiceGenerator(VoiceGenerator):
    """A backend that is honestly never available — used to exercise and
    demonstrate the NOT_AVAILABLE/BLOCKED path without a fabricated
    partial success (VL-D5 §5, §33's "missing backend" fixture)."""

    name = "unavailable-backend"
    version = "0.0.0"

    def get_capabilities(self) -> GenerationCapabilities:
        return GenerationCapabilities(
            backend_state=GenerationBackendState.UNAVAILABLE,
            compute_backend=ComputeBackend.CPU,
            supported_controls=frozenset(),
        )

    def validate_request(self, request: dict[str, Any]) -> list[str]:
        return ["backend is unavailable"]

    def estimate_requirements(self, request: dict[str, Any]) -> dict[str, Any]:
        return {"estimate_basis": "not available -- backend is unavailable"}

    def supports_regeneration(self) -> bool:
        return False

    def generate_preview(self, request: dict[str, Any]) -> PreviewArtifact:
        raise GenerationBlockedError("backend is unavailable — no generation transport exists")


@dataclass
class GenerationItem:
    item_id: str
    request: PreviewRequest
    status: GenerationStatus = GenerationStatus.QUEUED
    progress: float = 0.0
    current_operation: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    artifact: dict[str, Any] | None = None
    generation_duration_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "request": self.request.to_dict(),
            "status": self.status.value,
            "progress": self.progress,
            "current_operation": self.current_operation,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "artifact": self.artifact,
            "generation_duration_seconds": self.generation_duration_seconds,
        }


def build_artifact_fingerprint(*, request: PreviewRequest, tool: str, tool_version: str) -> StageFingerprint:
    text_hash = hashlib.sha256(request.text.encode("utf-8")).hexdigest()
    return StageFingerprint(
        stage=GENERATION_STAGE,
        stage_version=GENERATION_VERSION,
        tool=tool,
        tool_version=tool_version,
        config_hash=request.config_hash,
        input_hashes=(text_hash,),
    )


class GenerationQueue:
    """Mirrors `pipeline.processing.ProcessingQueue`'s shape: sequential
    processing, one broad `except Exception` per item so a single failed
    generation can never stop the rest of the queue (§13)."""

    def __init__(self, *, generator: VoiceGenerator) -> None:
        self._generator = generator
        self._items: dict[str, GenerationItem] = {}
        self._order: list[str] = []

    def enqueue(self, request: PreviewRequest) -> GenerationItem:
        item_id = f"gen-{len(self._order):04d}-{request.request_id}"
        item = GenerationItem(item_id=item_id, request=request)
        self._items[item_id] = item
        self._order.append(item_id)
        return item

    def cancel(self, item_id: str) -> GenerationItem:
        item = self._items[item_id]
        if item.status == GenerationStatus.QUEUED:
            item.status = GenerationStatus.CANCELLED
        return item

    def retry(self, item_id: str, *, generator: VoiceGenerator | None = None) -> GenerationItem:
        item = self._items[item_id]
        if generator is not None:
            self._generator = generator
        item.status = GenerationStatus.QUEUED
        item.warnings = []
        item.errors = []
        item.artifact = None
        return self.process_one(item_id)

    def process_one(self, item_id: str) -> GenerationItem:
        item = self._items[item_id]
        if item.status == GenerationStatus.CANCELLED:
            return item

        started = datetime.now(UTC)
        try:
            item.status = GenerationStatus.PREPARING
            item.current_operation = "validating request"
            errors = self._generator.validate_request(item.request.to_dict())
            if errors:
                item.status = GenerationStatus.BLOCKED
                item.errors.extend(errors)
                return item

            item.status = GenerationStatus.GENERATING
            item.current_operation = "generating audio"
            artifact = self._generator.generate_preview(item.request.to_dict())

            item.status = GenerationStatus.POST_PROCESSING
            item.current_operation = "finalizing artifact"
            fingerprint = build_artifact_fingerprint(
                request=item.request, tool=self._generator.name, tool_version=self._generator.version
            )
            item.artifact = {
                **artifact.to_dict(),
                "artifact_id": fingerprint.digest(),
                "fingerprint": fingerprint.to_dict(),
            }

            item.status = GenerationStatus.WARNING if item.warnings else GenerationStatus.READY
        except GenerationBlockedError as exc:
            item.status = GenerationStatus.BLOCKED
            item.errors.append(str(exc))
        except Exception as exc:  # noqa: BLE001 -- one item's failure must never crash the queue
            item.status = GenerationStatus.FAILED
            item.errors.append(str(exc))
        finally:
            item.current_operation = None
            item.progress = 1.0
            item.generation_duration_seconds = (datetime.now(UTC) - started).total_seconds()
        return item

    def process_all(self) -> list[GenerationItem]:
        return [
            self.process_one(item_id)
            for item_id in self._order
            if self._items[item_id].status == GenerationStatus.QUEUED
        ]

    def list(self) -> list[GenerationItem]:
        return [self._items[item_id] for item_id in self._order]

    def get(self, item_id: str) -> GenerationItem | None:
        return self._items.get(item_id)

    def counts(self) -> dict[str, int]:
        counts = dict.fromkeys((s.value for s in GenerationStatus), 0)
        for item in self.list():
            counts[item.status.value] += 1
        return counts


def build_ab_comparison(artifact_a: dict[str, Any], artifact_b: dict[str, Any]) -> dict[str, Any]:
    """Metadata-only comparison (§16). Never claims acoustic similarity —
    that requires a validated evaluation engine this project does not
    have yet."""
    duration_a = artifact_a.get("duration_seconds")
    duration_b = artifact_b.get("duration_seconds")
    return {
        "duration_diff_seconds": (
            round(abs(duration_a - duration_b), 6) if duration_a is not None and duration_b is not None else None
        ),
        "sample_rate_match": artifact_a.get("sample_rate") == artifact_b.get("sample_rate"),
        "kind_match": artifact_a.get("kind") == artifact_b.get("kind"),
        "both_synthetic": bool(artifact_a.get("is_synthetic")) and bool(artifact_b.get("is_synthetic")),
        "note": "Metadata comparison only -- no acoustic similarity claim is made.",
    }
