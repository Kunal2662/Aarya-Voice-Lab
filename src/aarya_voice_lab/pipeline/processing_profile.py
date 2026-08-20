"""Processing profiles — VL-D4 §6, §22.

A `ProcessingProfile` bundles every configuration decision a processing
run needs into one versioned, serializable object: a normalization
target (`pipeline.normalization.NormalizationConfig`, reused unmodified),
a boundary policy (`BoundaryPolicy`, new below), a noise-conditioning
mode, and quality re-check thresholds
(`pipeline.quality.QualityThresholds`, reused unmodified). Nothing here
reimplements what those modules already do — a profile only names
*which* configuration to run them with.

**Profiles are immutable once created.** Every field lives on a frozen
dataclass, and `ProcessingProfileRegistry` has no "edit in place" method
at all — `create_version()` is the only way to change a named profile's
configuration, and it always produces a new, independently addressable
version rather than mutating the one before it. This is the same
append-only principle VL-D3's `CandidateReviewLog` applies to review
decisions, applied here to configuration instead.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from aarya_voice_lab.pipeline.normalization import NormalizationConfig
from aarya_voice_lab.pipeline.quality import QualityThresholds

PROCESSING_PROFILE_VERSION = "1.0.0"


class NoiseConditioningMode(StrEnum):
    #: No noise conditioning is attempted.
    OFF = "OFF"
    #: Noise is measured and reported; nothing is altered.
    MEASURE_ONLY = "MEASURE_ONLY"
    #: A light conditioning pass — deliberately not implemented in VL-D4
    #: (no real noise-reduction tool is wired up yet); selecting it
    #: yields an honest NOT_AVAILABLE, never a silent no-op or a fake pass.
    LIGHT = "LIGHT"
    #: A standard conditioning pass — same NOT_AVAILABLE honesty as LIGHT.
    STANDARD = "STANDARD"


#: Modes with a real implementation behind them in VL-D4. LIGHT/STANDARD
#: are real, closed vocabulary values reserved for a future milestone —
#: see pipeline.conditioning.condition_noise() for exactly how they are
#: reported as unavailable rather than silently downgraded to MEASURE_ONLY.
IMPLEMENTED_NOISE_MODES: frozenset[NoiseConditioningMode] = frozenset(
    {NoiseConditioningMode.OFF, NoiseConditioningMode.MEASURE_ONLY}
)


@dataclass(frozen=True)
class BoundaryPolicy:
    trim_leading_silence: bool = True
    trim_trailing_silence: bool = True
    #: Silence shorter than this at an edge is left alone — a natural
    #: short pause before speech should not be stripped away.
    min_trim_seconds: float = 0.1
    #: Silence padding re-added after trimming, so a derived segment
    #: never starts or ends exactly on a speech onset/offset.
    pad_seconds: float = 0.05

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProcessingProfile:
    profile_id: str
    name: str
    version: int
    normalization: NormalizationConfig = field(default_factory=NormalizationConfig)
    boundary: BoundaryPolicy = field(default_factory=BoundaryPolicy)
    noise_conditioning_mode: NoiseConditioningMode = NoiseConditioningMode.MEASURE_ONLY
    quality_thresholds: QualityThresholds = field(default_factory=QualityThresholds)
    created_at: str | None = None
    notes: str | None = None
    profile_schema_version: str = PROCESSING_PROFILE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "name": self.name,
            "version": self.version,
            "normalization": self.normalization.to_dict(),
            "boundary": self.boundary.to_dict(),
            "noise_conditioning_mode": self.noise_conditioning_mode.value,
            "quality_thresholds": asdict(self.quality_thresholds),
            "created_at": self.created_at,
            "notes": self.notes,
            "profile_schema_version": self.profile_schema_version,
            "config_hash": self.config_hash(),
        }

    def config_hash(self) -> str:
        """Deterministic identity for exactly the values that shape a
        processing run — reused by pipeline.processing to build a
        derived artifact's identity (VL-D4 §17), the same "hash
        everything that shaped the output" principle
        pipeline.resume.StageFingerprint already applies to pipeline
        stages generally."""
        payload = {
            "normalization": self.normalization.to_dict(),
            "boundary": self.boundary.to_dict(),
            "noise_conditioning_mode": self.noise_conditioning_mode.value,
            "quality_thresholds": asdict(self.quality_thresholds),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


class ProcessingProfileRegistry:
    """In-memory registry of named, versioned profiles.

    `create()` refuses a name that already exists — every subsequent
    change to that name's configuration must go through
    `create_version()`, which always appends a new, independently
    addressable `ProcessingProfile` rather than altering the one before
    it (§22's "profiles should be immutable... or changes must create a
    new version," implemented as the stronger, unconditional guarantee).
    """

    def __init__(self) -> None:
        self._versions: dict[str, list[ProcessingProfile]] = {}
        self._default_name: str | None = None

    def create(self, name: str, **kwargs: Any) -> ProcessingProfile:
        if name in self._versions:
            raise ValueError(f"profile {name!r} already exists; use create_version() to change it")
        profile = ProcessingProfile(profile_id=f"{name}-v1", name=name, version=1, **kwargs)
        self._versions[name] = [profile]
        if self._default_name is None:
            self._default_name = name
        return profile

    def create_version(self, name: str, **overrides: Any) -> ProcessingProfile:
        versions = self._versions.get(name)
        if not versions:
            raise KeyError(f"no profile named {name!r}")
        base = versions[-1]
        fields = {
            "normalization": overrides.pop("normalization", base.normalization),
            "boundary": overrides.pop("boundary", base.boundary),
            "noise_conditioning_mode": overrides.pop("noise_conditioning_mode", base.noise_conditioning_mode),
            "quality_thresholds": overrides.pop("quality_thresholds", base.quality_thresholds),
            "notes": overrides.pop("notes", base.notes),
            "created_at": overrides.pop("created_at", None),
        }
        if overrides:
            raise TypeError(f"unknown profile field(s): {sorted(overrides)}")
        next_version = base.version + 1
        profile = ProcessingProfile(profile_id=f"{name}-v{next_version}", name=name, version=next_version, **fields)
        versions.append(profile)
        return profile

    def duplicate(self, name: str, new_name: str) -> ProcessingProfile:
        source = self.latest(name)
        return self.create(
            new_name,
            normalization=source.normalization,
            boundary=source.boundary,
            noise_conditioning_mode=source.noise_conditioning_mode,
            quality_thresholds=source.quality_thresholds,
            notes=source.notes,
        )

    def latest(self, name: str) -> ProcessingProfile:
        versions = self._versions.get(name)
        if not versions:
            raise KeyError(f"no profile named {name!r}")
        return versions[-1]

    def get_version(self, name: str, version: int) -> ProcessingProfile | None:
        for profile in self._versions.get(name, []):
            if profile.version == version:
                return profile
        return None

    def history(self, name: str) -> list[ProcessingProfile]:
        return list(self._versions.get(name, []))

    def names(self) -> list[str]:
        return list(self._versions.keys())

    def all_latest(self) -> list[ProcessingProfile]:
        return [versions[-1] for versions in self._versions.values()]

    def set_default(self, name: str) -> None:
        if name not in self._versions:
            raise KeyError(f"no profile named {name!r}")
        self._default_name = name

    def default(self) -> ProcessingProfile | None:
        if self._default_name is None:
            return None
        return self.latest(self._default_name)
