"""Provider-independent VoiceService contract.

This is the FUTURE interface through which AARYA Core would eventually
consume voice models produced by this project (see
docs/MODEL_STRATEGY.md, section 15 of the Phase 0 spec). It is defined
here for architectural planning only:

  - No implementation exists yet (no local TTS engine is wired in).
  - AARYA Core is NOT modified or integrated with in this repository.
  - This module must never be imported by, or import from, an AARYA Core
    or AARYA Frontend codebase.

Concrete providers (e.g. a specific local TTS engine) will subclass
VoiceService in a later phase.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VoiceProfile:
    voice_id: str
    display_name: str
    model_type: str  # "default_voice" | "private_voice"
    language_capability: tuple[str, ...]
    requires_permission: str | None  # e.g. "voice.private.use" for private_voice


@dataclass(frozen=True)
class SynthesisRequest:
    voice_id: str
    text: str
    language: str
    output_format: str = "wav"


@dataclass(frozen=True)
class SynthesisResult:
    audio_bytes: bytes
    sample_rate: int
    format: str
    voice_id: str


@dataclass(frozen=True)
class HealthStatus:
    healthy: bool
    detail: str


class VoiceService(ABC):
    """Abstract contract a local voice provider must implement.

    NOT IMPLEMENTED in Phase 0. Every method raises NotImplementedError
    by design -- this class exists to fix the shape of the future
    interface, not to run anything.
    """

    @abstractmethod
    def list_voice_profiles(self) -> list[VoiceProfile]:
        raise NotImplementedError("Phase 0: no VoiceService provider is implemented yet")

    @abstractmethod
    def get_voice_profile(self, voice_id: str) -> VoiceProfile:
        raise NotImplementedError("Phase 0: no VoiceService provider is implemented yet")

    @abstractmethod
    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        raise NotImplementedError("Phase 0: no VoiceService provider is implemented yet")

    @abstractmethod
    def health(self) -> HealthStatus:
        raise NotImplementedError("Phase 0: no VoiceService provider is implemented yet")

    @abstractmethod
    def get_model_info(self, voice_id: str) -> dict[str, Any]:
        raise NotImplementedError("Phase 0: no VoiceService provider is implemented yet")
