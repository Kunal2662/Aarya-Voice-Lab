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
    #: VL-D18 -- mirrors pipeline.training.TrainingProviderCapabilities'
    #: shape exactly. What this provider actually requires to move past
    #: NOT_CONFIGURED, shown to the operator verbatim rather than a
    #: generic "unavailable".
    missing_requirements: tuple[str, ...] = field(default_factory=tuple)
    #: VL-D18 -- static, honest explanation of the current state. Never
    #: derived from a live credential/network check.
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_state": self.backend_state.value,
            "compute_backend": self.compute_backend.value,
            "supported_controls": sorted(self.supported_controls),
            "missing_requirements": list(self.missing_requirements),
            "detail": self.detail,
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


#: VL-D18 -- static, informational text only. Never derived from a live
#: credential lookup, network request, or HuggingFace availability check
#: -- true (or false) independent of anything installed on this
#: interpreter, so it never claims more than is actually known.
_INDICF5_ACCESS_NOTE = (
    "AI4Bharat IndicF5 is the approved generation candidate (see "
    "docs/TTS_MODELS.md). Its HuggingFace repository is gated -- "
    "downloading the weights requires accepting a contact-sharing "
    "agreement -- and it loads with trust_remote_code=True, which "
    "executes arbitrary code from the model repository; that code has "
    "not undergone the required security review. Neither condition "
    "depends on what is installed in this interpreter."
)


class LocalNeuralVoiceGenerator(VoiceGenerator):
    """Real Voice Model Engine milestone, extended by VL-D18 -- the
    provider boundary for a real, local TTS/voice-cloning backend, with
    genuine capability detection instead of a fabricated result.

    Checks, via `importlib.metadata` (empirically, not assumed), for the
    packages AI4Bharat IndicF5 -- the approved generation candidate, see
    `docs/TTS_MODELS.md` -- actually requires: `transformers`, `torch`,
    and `soundfile`. **None is installed in this interpreter.** Piper
    remains a documented fallback candidate only (`requirements/tts.txt`)
    and is deliberately not checked here -- substituting it is a decision
    this class does not make on its own. Installing any of these is an
    explicitly separate, approval-gated, license-reviewed decision
    (`requirements/tts.txt`'s own "NO MODEL HAS BEEN SELECTED... do not
    install a model merely because it is listed", and
    `configs/default.yaml`'s `environments.env-tts.requires_approval`) --
    never something this class does on its own.

    Even if every dependency above were installed, IndicF5's own
    HuggingFace access gate and unreviewed `trust_remote_code=True`
    requirement (see `_INDICF5_ACCESS_NOTE`) mean real generation would
    still not be possible -- `get_capabilities()` never reports
    `AVAILABLE`, and `generate_preview()` always raises
    `GenerationBlockedError` naming exactly what is missing. It never
    falls back to `SyntheticVoiceGenerator`'s sine tone and never
    produces audio that could be mistaken for a real generated voice.
    """

    name = "local-neural-tts"
    version = "1.0.0"

    #: Distribution name -> what it would provide, for IndicF5 (the
    #: approved candidate). See requirements/tts.txt and docs/TTS_MODELS.md.
    CANDIDATE_DISTRIBUTIONS: dict[str, str] = {
        "transformers": "HuggingFace Transformers (required to load IndicF5)",
        "torch": "PyTorch (required by IndicF5)",
        "soundfile": "soundfile (required for IndicF5 audio I/O)",
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

    def get_capabilities(self) -> GenerationCapabilities:
        installed = self._installed()
        missing = tuple(sorted(name for name, version in installed.items() if version is None))
        if not missing:
            # Every known IndicF5 dependency is importable, but that
            # changes nothing about real generation: no inference
            # implementation exists yet (see generate_preview()), and
            # _INDICF5_ACCESS_NOTE's HuggingFace-gating/trust_remote_code
            # facts are unaffected by local package installation. Report
            # ERROR rather than AVAILABLE, since AVAILABLE would promise
            # a working generation path that does not exist.
            return GenerationCapabilities(
                backend_state=GenerationBackendState.ERROR,
                compute_backend=ComputeBackend.CPU,
                supported_controls=frozenset(),
                missing_requirements=(),
                detail=(
                    "All of IndicF5's known Python dependencies are importable in "
                    "this interpreter, but no real inference implementation exists "
                    f"yet. {_INDICF5_ACCESS_NOTE}"
                ),
            )
        return GenerationCapabilities(
            backend_state=GenerationBackendState.NOT_CONFIGURED,
            compute_backend=ComputeBackend.CPU,
            supported_controls=frozenset(),
            missing_requirements=missing,
            detail=(
                f"Missing IndicF5 dependencies in this interpreter: {', '.join(missing)}. "
                f"{_INDICF5_ACCESS_NOTE}"
            ),
        )

    def validate_request(self, request: dict[str, Any]) -> list[str]:
        capabilities = self.get_capabilities()
        if capabilities.backend_state is not GenerationBackendState.AVAILABLE:
            missing = sorted(name for name, version in self._installed().items() if version is None)
            return [
                f"{self.name} is not configured (state={capabilities.backend_state.value}); "
                f"missing: {missing or 'a working inference implementation'}. "
                "See requirements/tts.txt for the documented, license-reviewed candidates."
            ]
        return []

    def estimate_requirements(self, request: dict[str, Any]) -> dict[str, Any]:
        return {"estimate_basis": "not available -- no real TTS backend is configured"}

    def supports_regeneration(self) -> bool:
        return False

    def generate_preview(self, request: dict[str, Any]) -> PreviewArtifact:
        errors = self.validate_request(request)
        raise GenerationBlockedError("; ".join(errors) if errors else f"{self.name} has no working inference path")


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


class InvalidConcurrencyError(ValueError):
    """Raised when `max_concurrent_generations` is not a positive integer
    or `None` (VL-D8). Never silently clamped -- a bad value is a bug in
    the caller, not something to paper over."""


class GenerationQueue:
    """Mirrors `pipeline.processing.ProcessingQueue`'s shape: sequential
    processing, one broad `except Exception` per item so a single failed
    generation can never stop the rest of the queue (§13).

    `max_concurrent_generations` (VL-D8) is opt-in and defaults to
    `None`, which preserves the exact pre-VL-D8 behaviour: every queued
    item processed in a single batch, in enqueue order. Items are always
    processed one at a time in this process -- "concurrency" here means
    *batch size* for `last_run_stats()`'s bookkeeping, a deterministic,
    honestly-measurable proxy for the setting having taken effect. It is
    not real parallel execution: no threading, no subprocess, no
    additional execution surface is introduced.
    """

    def __init__(self, *, generator: VoiceGenerator, max_concurrent_generations: int | None = None) -> None:
        self._generator = generator
        self._items: dict[str, GenerationItem] = {}
        self._order: list[str] = []
        self._max_concurrent_generations: int | None = None
        self._last_run_stats: dict[str, Any] | None = None
        self.set_max_concurrent_generations(max_concurrent_generations)

    @property
    def max_concurrent_generations(self) -> int | None:
        return self._max_concurrent_generations

    def set_max_concurrent_generations(self, value: int | None) -> None:
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
            raise InvalidConcurrencyError(
                f"max_concurrent_generations must be a positive integer or None, got {value!r}"
            )
        self._max_concurrent_generations = value

    def last_run_stats(self) -> dict[str, Any] | None:
        """Real counts from the most recent `process_all()` call, or
        `None` if it has not run yet. Never fabricated: absent until a
        real run has happened."""
        return dict(self._last_run_stats) if self._last_run_stats is not None else None

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
        """Process every QUEUED item, in enqueue order.

        `max_concurrent_generations=None` (the default) processes
        everything as one batch -- byte-for-byte the same observable
        result (same items, same order, same statuses) as before VL-D8.
        A set value processes the same items in the same order, batched
        for `last_run_stats()`'s bookkeeping only; no item's outcome
        depends on batch size.
        """
        queued_ids = [item_id for item_id in self._order if self._items[item_id].status == GenerationStatus.QUEUED]
        batch_size = self._max_concurrent_generations or len(queued_ids) or 1

        processed: list[GenerationItem] = []
        batch_count = 0
        for start in range(0, len(queued_ids), batch_size):
            batch_count += 1
            for item_id in queued_ids[start : start + batch_size]:
                processed.append(self.process_one(item_id))

        self._last_run_stats = {
            "item_count": len(queued_ids),
            "batch_count": batch_count if queued_ids else 0,
            "max_concurrent_generations": self._max_concurrent_generations,
        }
        return processed

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
