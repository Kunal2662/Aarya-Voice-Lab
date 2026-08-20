"""Speaker profiles: versioned, provenance-carrying identity records.

A profile is what a candidate segment gets compared against. It holds
metadata and a *reference* to a stored embedding — never the vector
itself, so a profile can be read, logged, and diffed without handling
biometric data.

Profiles are **immutable**. Improving one creates a new version and marks
the old `superseded_by`. Verification records name the exact
`profile_version` they used, so a re-enrollment invalidates dependent
verifications through the fingerprint rather than silently changing what
their scores meant.

The profile is deliberately independent of how it was built: it records
which strategy produced it, but nothing here assumes any particular
enrollment approach. Swapping strategies must not require touching this
module or the verification engine.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from aarya_voice_lab import __version__
from aarya_voice_lab.identity.calibration import CalibrationState

PROFILE_SCHEMA_VERSION = "1.0.0"


class SpeakerRole(StrEnum):
    """Who a profile represents.

    Mirrors `security.speaker_policy.SpeakerRole`, which holds the
    eligibility rules. Kept as a separate enum so profile storage does not
    depend on policy internals, and converted explicitly at the boundary.
    """

    TARGET_SPEAKER = "target_speaker"
    OPERATOR = "operator"
    #: A synthetic stand-in. Never a real person.
    SYNTHETIC_SPEAKER = "synthetic_speaker"
    UNKNOWN = "unknown"


class EnrollmentState(StrEnum):
    #: Created but no embedding attached yet.
    DRAFT = "draft"
    #: Awaiting the human confirmation its strategy requires.
    PENDING_HUMAN_APPROVAL = "pending_human_approval"
    #: Complete and usable for verification.
    ENROLLED = "enrolled"
    #: Replaced by a newer version.
    SUPERSEDED = "superseded"
    #: Withdrawn; must not be used.
    REVOKED = "revoked"


#: States in which a profile may be used to verify anything.
USABLE_ENROLLMENT_STATES: frozenset[EnrollmentState] = frozenset({EnrollmentState.ENROLLED})


class ProfileError(RuntimeError):
    """Raised when a profile is invalid or used in an unusable state."""


@dataclass
class ProfileProvenance:
    """The chain behind a profile: source → candidate → enrollment → profile."""

    strategy_name: str
    strategy_version: str
    #: Candidate segment ids that contributed. Empty for direct recordings.
    seed_segment_ids: list[str] = field(default_factory=list)
    #: Source file ids behind those segments.
    source_file_ids: list[str] = field(default_factory=list)
    #: Hash of the candidate manifest the seeds came from.
    candidate_manifest_sha256: str | None = None
    #: Who approved the seed set. Required by human-anchored strategies.
    approved_by: str | None = None
    approved_at: str | None = None
    processing_version: str = __version__

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "strategy_version": self.strategy_version,
            "seed_segment_ids": list(self.seed_segment_ids),
            "source_file_ids": list(self.source_file_ids),
            "candidate_manifest_sha256": self.candidate_manifest_sha256,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "processing_version": self.processing_version,
        }


@dataclass
class SpeakerProfile:
    """A versioned speaker profile.

    Carries no embedding vector — only `embedding_sha256` and
    `embedding_id`, which resolve through `EmbeddingStore`.
    """

    profile_id: str
    role: SpeakerRole
    version: int
    enrollment_state: EnrollmentState
    provenance: ProfileProvenance
    #: Reference to the stored vector; None while DRAFT.
    embedding_id: str | None = None
    embedding_sha256: str | None = None
    embedding_dimension: int | None = None
    provider_name: str | None = None
    provider_version: str | None = None
    #: Propagates from the provider. Blocks real identity conclusions.
    provider_is_synthetic: bool = True
    calibration_state: CalibrationState = CalibrationState.UNCALIBRATED
    calibration_id: str | None = None
    sample_count: int = 0
    total_duration_seconds: float = 0.0
    #: Channel conditions covered, e.g. ("wideband_16000", "narrowband_8000").
    channel_conditions: list[str] = field(default_factory=list)
    display_name: str | None = None
    notes: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    superseded_by: str | None = None
    schema_version: str = PROFILE_SCHEMA_VERSION

    @property
    def is_usable(self) -> bool:
        return (
            self.enrollment_state in USABLE_ENROLLMENT_STATES
            and self.embedding_sha256 is not None
            and self.superseded_by is None
        )

    @property
    def profile_version_key(self) -> str:
        """Stable identifier for this exact profile version.

        Used in verification fingerprints, so re-enrollment forces
        dependent work to recompute rather than reusing scores measured
        against a profile that no longer exists.
        """
        return f"{self.profile_id}@v{self.version}"

    def require_usable(self) -> None:
        if self.superseded_by is not None:
            raise ProfileError(
                f"Profile {self.profile_version_key} was superseded by {self.superseded_by}; "
                "verification must use the current version."
            )
        if self.enrollment_state is not EnrollmentState.ENROLLED:
            raise ProfileError(
                f"Profile {self.profile_version_key} is {self.enrollment_state.value}, not enrolled. "
                + (
                    "Human approval of the enrollment seed is still outstanding."
                    if self.enrollment_state is EnrollmentState.PENDING_HUMAN_APPROVAL
                    else ""
                )
            )
        if self.embedding_sha256 is None:
            raise ProfileError(f"Profile {self.profile_version_key} has no embedding attached.")

    def fingerprint(self) -> str:
        """Hash of everything that determines what this profile means."""
        payload = json.dumps(
            {
                "profile_id": self.profile_id,
                "version": self.version,
                "role": self.role.value,
                "embedding_sha256": self.embedding_sha256,
                "provider_name": self.provider_name,
                "provider_version": self.provider_version,
                "strategy": self.provenance.strategy_name,
                "strategy_version": self.provenance.strategy_version,
            },
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "role": self.role.value,
            "version": self.version,
            "profile_version_key": self.profile_version_key,
            "enrollment_state": self.enrollment_state.value,
            "embedding_id": self.embedding_id,
            "embedding_sha256": self.embedding_sha256,
            "embedding_dimension": self.embedding_dimension,
            "provider_name": self.provider_name,
            "provider_version": self.provider_version,
            "provider_is_synthetic": self.provider_is_synthetic,
            "calibration_state": self.calibration_state.value,
            "calibration_id": self.calibration_id,
            "sample_count": self.sample_count,
            "total_duration_seconds": round(self.total_duration_seconds, 6),
            "channel_conditions": list(self.channel_conditions),
            "display_name": self.display_name,
            "notes": self.notes,
            "provenance": self.provenance.to_dict(),
            "fingerprint": self.fingerprint(),
            "created_at": self.created_at,
            "superseded_by": self.superseded_by,
            "is_usable": self.is_usable,
        }

    def supersede(self, replacement_key: str) -> SpeakerProfile:
        """Return a copy marked superseded. Profiles are never edited in place."""
        from dataclasses import replace

        return replace(
            self,
            superseded_by=replacement_key,
            enrollment_state=EnrollmentState.SUPERSEDED,
        )


class ProfileStore:
    """JSON-file storage for profiles under `data/enrollment/`.

    Git-ignored: a profile names the segments of a private recording that
    a human identified as a specific person, which is itself sensitive
    even without the vector.
    """

    def __init__(self, data_root):
        self.data_root = data_root
        self.directory = data_root.root / "enrollment"

    def _path(self, profile_id: str, version: int):
        return self.directory / f"{profile_id}.v{version}.json"

    def save(self, profile: SpeakerProfile):
        from aarya_voice_lab.core.data_root import assert_source_writable

        path = self._path(profile.profile_id, profile.version)
        assert_source_writable(self.data_root, path)
        self.directory.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(profile.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        return path

    def load(self, profile_id: str, version: int) -> SpeakerProfile:
        path = self._path(profile_id, version)
        if not path.is_file():
            raise ProfileError(f"profile {profile_id}@v{version} not found")
        return profile_from_dict(json.loads(path.read_text(encoding="utf-8")))

    def versions(self, profile_id: str) -> list[int]:
        if not self.directory.is_dir():
            return []
        found = []
        for path in self.directory.glob(f"{profile_id}.v*.json"):
            try:
                found.append(int(path.stem.rsplit(".v", 1)[1]))
            except (IndexError, ValueError):
                continue
        return sorted(found)

    def latest(self, profile_id: str) -> SpeakerProfile | None:
        versions = self.versions(profile_id)
        return self.load(profile_id, versions[-1]) if versions else None

    def list_profiles(self) -> list[str]:
        if not self.directory.is_dir():
            return []
        return sorted({p.stem.rsplit(".v", 1)[0] for p in self.directory.glob("*.v*.json")})


def profile_from_dict(data: dict[str, Any]) -> SpeakerProfile:
    provenance = ProfileProvenance(**data["provenance"])
    return SpeakerProfile(
        profile_id=data["profile_id"],
        role=SpeakerRole(data["role"]),
        version=data["version"],
        enrollment_state=EnrollmentState(data["enrollment_state"]),
        provenance=provenance,
        embedding_id=data.get("embedding_id"),
        embedding_sha256=data.get("embedding_sha256"),
        embedding_dimension=data.get("embedding_dimension"),
        provider_name=data.get("provider_name"),
        provider_version=data.get("provider_version"),
        provider_is_synthetic=data.get("provider_is_synthetic", True),
        calibration_state=CalibrationState(data.get("calibration_state", "UNCALIBRATED")),
        calibration_id=data.get("calibration_id"),
        sample_count=data.get("sample_count", 0),
        total_duration_seconds=data.get("total_duration_seconds", 0.0),
        channel_conditions=data.get("channel_conditions", []),
        display_name=data.get("display_name"),
        notes=data.get("notes"),
        created_at=data.get("created_at", datetime.now(UTC).isoformat()),
        superseded_by=data.get("superseded_by"),
        schema_version=data.get("schema_version", PROFILE_SCHEMA_VERSION),
    )
