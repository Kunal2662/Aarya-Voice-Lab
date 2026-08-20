"""Voice profiles — VL-D5 §8, §9.

A `VoiceProfile` is deliberately **not** a technical dataset, a
generation profile, a model, or a generated output — VL-D5 §9 requires
those stay separate objects, connected only by id references:

    Dataset -> Processed Dataset -> Voice Profile -> Model
            -> Generation Request -> Generated Output

**This type cannot express a speaker characteristic.** A future voice
profile may eventually carry speaker/accent/pronunciation/prosody
characteristics (§8), but VL-D5 must never auto-infer or populate any of
them — so, exactly like `pipeline.segmentation.CandidateSegment` has no
field capable of expressing a speaker role, `VoiceProfile` simply has no
field for any of those characteristics yet. There is nothing to
accidentally leave `None` and nothing to forget to guard. Only
`style_controls` and `generation_preferences` exist, and both are
operator-configurable generation *knobs* (e.g. "prefer a slower pace"),
never an inferred trait of any speaker.

Every profile starts `SYNTHETIC_PROFILE` or `UNCALIBRATED` and stays
that way in VL-D5 — nothing here ever promotes a profile past that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class VoiceProfileState(StrEnum):
    #: Built entirely from synthetic fixtures/placeholders.
    SYNTHETIC_PROFILE = "SYNTHETIC_PROFILE"
    #: No calibration evidence exists for this profile at all.
    UNCALIBRATED = "UNCALIBRATED"


@dataclass(frozen=True)
class VoiceProfile:
    profile_id: str
    name: str
    version: int
    state: VoiceProfileState = VoiceProfileState.SYNTHETIC_PROFILE
    #: Operator-chosen generation knobs — never an inferred speaker trait.
    style_controls: dict[str, str] = field(default_factory=dict)
    generation_preferences: dict[str, str] = field(default_factory=dict)
    notes: str | None = None
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "name": self.name,
            "version": self.version,
            "state": self.state.value,
            "style_controls": dict(self.style_controls),
            "generation_preferences": dict(self.generation_preferences),
            "notes": self.notes,
            "created_at": self.created_at,
        }


class VoiceProfileRegistry:
    """Mirrors `pipeline.processing_profile.ProcessingProfileRegistry`
    exactly: `create()` refuses a duplicate name; every later change goes
    through `create_version()`, which always appends a new version rather
    than mutating the one before it."""

    def __init__(self) -> None:
        self._versions: dict[str, list[VoiceProfile]] = {}

    def create(self, name: str, **kwargs: Any) -> VoiceProfile:
        if name in self._versions:
            raise ValueError(f"voice profile {name!r} already exists; use create_version() to change it")
        profile = VoiceProfile(profile_id=f"{name}-v1", name=name, version=1, **kwargs)
        self._versions[name] = [profile]
        return profile

    def create_version(self, name: str, **overrides: Any) -> VoiceProfile:
        versions = self._versions.get(name)
        if not versions:
            raise KeyError(f"no voice profile named {name!r}")
        base = versions[-1]
        fields = {
            "state": overrides.pop("state", base.state),
            "style_controls": overrides.pop("style_controls", base.style_controls),
            "generation_preferences": overrides.pop("generation_preferences", base.generation_preferences),
            "notes": overrides.pop("notes", base.notes),
            "created_at": overrides.pop("created_at", None),
        }
        if overrides:
            raise TypeError(f"unknown voice profile field(s): {sorted(overrides)}")
        next_version = base.version + 1
        profile = VoiceProfile(profile_id=f"{name}-v{next_version}", name=name, version=next_version, **fields)
        versions.append(profile)
        return profile

    def latest(self, name: str) -> VoiceProfile:
        versions = self._versions.get(name)
        if not versions:
            raise KeyError(f"no voice profile named {name!r}")
        return versions[-1]

    def get_version(self, name: str, version: int) -> VoiceProfile | None:
        for profile in self._versions.get(name, []):
            if profile.version == version:
                return profile
        return None

    def history(self, name: str) -> list[VoiceProfile]:
        return list(self._versions.get(name, []))

    def names(self) -> list[str]:
        return list(self._versions.keys())

    def all_latest(self) -> list[VoiceProfile]:
        return [versions[-1] for versions in self._versions.values()]
