"""Pluggable enrollment engine.

Enrollment turns audio into a `SpeakerProfile`. *How* it does that is a
strategy, chosen at call time and replaceable without touching the
verification engine, the profile model, or storage.

That replaceability is deliberate, not speculative. The right enrollment
approach for the target speaker is an open architectural question — the
readiness report set out why it is circular (her only recordings are the
ones being labelled) and recommended a human-anchored seed. Hard-coding
any strategy now would bake in an answer that has not been decided.

## Strategies shipped

* `SyntheticEnrollmentStrategy` — development and testing. Enrolls from
  generated audio, producing a profile marked synthetic throughout.
* `DirectRecordingEnrollmentStrategy` — for a speaker who can record
  fresh audio. This is the operator path; its provenance is unambiguous
  because the audio was captured for the purpose.
* `HumanAnchoredEnrollmentStrategy` — for a speaker who cannot record.
  Requires explicitly human-approved seed segments and refuses to
  complete without them. This is the interface the target-speaker path
  will use; the seed selection itself is a human act, never an algorithm.

A future strategy registers itself and becomes available immediately.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.identity.calibration import CalibrationState
from aarya_voice_lab.identity.embeddings import (
    EmbeddingProvider,
    EmbeddingStore,
    EmbeddingVector,
    mean_embedding,
)
from aarya_voice_lab.identity.profile import (
    EnrollmentState,
    ProfileProvenance,
    ProfileStore,
    SpeakerProfile,
    SpeakerRole,
)


class EnrollmentError(RuntimeError):
    """Raised when enrollment cannot proceed."""


class HumanApprovalRequired(EnrollmentError):
    """Raised when a strategy requires human approval that is absent.

    A stop condition, not a bug: the operator must act before enrollment
    can complete.
    """


@dataclass
class EnrollmentSample:
    """One piece of audio offered for enrollment.

    Carries the Phase 2 context so a strategy can enforce its own
    admission rules — and so the profile's provenance can name exactly
    which segments contributed.
    """

    sample_id: str
    samples: list[int] = field(repr=False)
    sample_rate: int
    bit_depth: int = 16
    segment_id: str | None = None
    source_file_id: str | None = None
    #: Phase 2 verdicts, carried forward rather than recomputed.
    overlap_status: str | None = None
    quality_status: str | None = None
    duration_seconds: float | None = None
    channel_condition: str | None = None
    #: True only when a human listened and confirmed this sample.
    human_confirmed: bool = False
    confirmed_by: str | None = None

    @property
    def effective_duration(self) -> float:
        if self.duration_seconds is not None:
            return self.duration_seconds
        return len(self.samples) / self.sample_rate if self.sample_rate else 0.0


@dataclass
class EnrollmentResult:
    profile: SpeakerProfile
    embedding_id: str
    accepted_samples: list[str] = field(default_factory=list)
    rejected_samples: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.to_dict(),
            "embedding_id": self.embedding_id,
            "accepted_samples": list(self.accepted_samples),
            "rejected_samples": list(self.rejected_samples),
            "warnings": list(self.warnings),
        }


class EnrollmentStrategy(ABC):
    """Contract every enrollment strategy satisfies."""

    name: str = "abstract"
    version: str = "0.0.0"
    #: Whether completing enrollment requires explicit human approval.
    requires_human_approval: bool = False
    #: Roles this strategy may enroll. Empty means any.
    permitted_roles: frozenset[SpeakerRole] = frozenset()

    @abstractmethod
    def admit(self, sample: EnrollmentSample) -> tuple[bool, str | None]:
        """Decide whether a sample may contribute. Returns (admitted, reason)."""

    def validate_role(self, role: SpeakerRole) -> None:
        if self.permitted_roles and role not in self.permitted_roles:
            raise EnrollmentError(
                f"Strategy {self.name!r} cannot enroll role {role.value!r}; "
                f"permitted: {sorted(r.value for r in self.permitted_roles)}"
            )

    def minimum_samples(self) -> int:
        return 1

    def minimum_total_seconds(self) -> float:
        return 0.5

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "requires_human_approval": self.requires_human_approval,
            "permitted_roles": sorted(r.value for r in self.permitted_roles) or ["any"],
            "minimum_samples": self.minimum_samples(),
            "minimum_total_seconds": self.minimum_total_seconds(),
        }


class SyntheticEnrollmentStrategy(EnrollmentStrategy):
    """Development strategy: enrolls generated audio with no gates.

    Only ever produces `SYNTHETIC_SPEAKER` profiles, so a synthetic
    enrollment can never be mistaken for a real person's profile.
    """

    name = "synthetic"
    version = "1.0.0"
    requires_human_approval = False
    permitted_roles = frozenset({SpeakerRole.SYNTHETIC_SPEAKER})

    def admit(self, sample: EnrollmentSample) -> tuple[bool, str | None]:
        if not sample.samples:
            return False, "empty sample"
        if sample.effective_duration < 0.1:
            return False, f"too short: {sample.effective_duration:.3f}s"
        return True, None


class DirectRecordingEnrollmentStrategy(EnrollmentStrategy):
    """For a speaker who can record fresh audio — the operator path.

    Provenance is unambiguous: the audio was captured for enrollment, so
    no seed-selection problem arises. Encourages covering multiple channel
    conditions, because matching a wideband profile against narrowband
    call audio is a known source of false rejections.
    """

    name = "direct_recording"
    version = "1.0.0"
    requires_human_approval = False
    permitted_roles = frozenset({SpeakerRole.OPERATOR, SpeakerRole.TARGET_SPEAKER})

    def admit(self, sample: EnrollmentSample) -> tuple[bool, str | None]:
        if not sample.samples:
            return False, "empty sample"
        if sample.effective_duration < 1.0:
            return False, f"too short for a stable embedding: {sample.effective_duration:.2f}s"
        return True, None

    def minimum_samples(self) -> int:
        return 1

    def minimum_total_seconds(self) -> float:
        return 5.0


class HumanAnchoredEnrollmentStrategy(EnrollmentStrategy):
    """For a speaker who cannot record — the target-speaker path.

    Every seed must be a segment a human listened to and confirmed. The
    strategy enforces the conditions from the readiness report:

    * `human_confirmed` is true and names a confirmer
    * Phase 2 overlap status is `NO_OVERLAP_DETECTED` — never `UNKNOWN`
    * Phase 2 quality status is `PASS`
    * duration is comfortably above the minimum

    It refuses to complete without approval rather than degrading to a
    best guess, because a contaminated seed propagates silently into every
    downstream decision.
    """

    name = "human_anchored"
    version = "1.0.0"
    requires_human_approval = True
    permitted_roles = frozenset({SpeakerRole.TARGET_SPEAKER, SpeakerRole.OPERATOR})

    #: Only this overlap verdict is admissible. UNKNOWN is not "probably fine".
    REQUIRED_OVERLAP_STATUS = "NO_OVERLAP_DETECTED"
    REQUIRED_QUALITY_STATUS = "PASS"
    MIN_SEED_SECONDS = 1.5

    def admit(self, sample: EnrollmentSample) -> tuple[bool, str | None]:
        if not sample.human_confirmed:
            return False, "not confirmed by a human"
        if not sample.confirmed_by:
            return False, "human confirmation records no confirmer"
        if sample.overlap_status != self.REQUIRED_OVERLAP_STATUS:
            return False, (
                f"overlap status is {sample.overlap_status!r}; only "
                f"{self.REQUIRED_OVERLAP_STATUS!r} may seed a profile"
            )
        if sample.quality_status != self.REQUIRED_QUALITY_STATUS:
            return False, f"quality status is {sample.quality_status!r}, not PASS"
        if sample.effective_duration < self.MIN_SEED_SECONDS:
            return False, (
                f"too short to seed: {sample.effective_duration:.2f}s "
                f"(minimum {self.MIN_SEED_SECONDS}s)"
            )
        return True, None

    def minimum_samples(self) -> int:
        # More than one, so a single mislabelled segment cannot define the
        # profile on its own.
        return 2

    def minimum_total_seconds(self) -> float:
        return 5.0


_STRATEGIES: dict[str, type[EnrollmentStrategy]] = {
    SyntheticEnrollmentStrategy.name: SyntheticEnrollmentStrategy,
    DirectRecordingEnrollmentStrategy.name: DirectRecordingEnrollmentStrategy,
    HumanAnchoredEnrollmentStrategy.name: HumanAnchoredEnrollmentStrategy,
}


def register_strategy(strategy_class: type[EnrollmentStrategy]) -> None:
    """Register a new strategy. No other module needs changing."""
    _STRATEGIES[strategy_class.name] = strategy_class


def available_strategies() -> list[str]:
    return sorted(_STRATEGIES)


def get_strategy(name: str) -> EnrollmentStrategy:
    if name not in _STRATEGIES:
        raise EnrollmentError(f"Unknown enrollment strategy {name!r}. Available: {available_strategies()}")
    return _STRATEGIES[name]()


def describe_strategies() -> list[dict[str, Any]]:
    """Strategy catalogue, for the CLI and the future desktop UI."""
    return [get_strategy(name).describe() for name in available_strategies()]


class EnrollmentEngine:
    """Runs a strategy against samples and produces a stored profile.

    The engine owns the mechanics — admission, averaging, storage,
    versioning — while the strategy owns the policy. Adding a strategy
    requires no change here.
    """

    def __init__(
        self,
        provider: EmbeddingProvider,
        data_root: DataRoot,
        *,
        embedding_store: EmbeddingStore | None = None,
        profile_store: ProfileStore | None = None,
    ):
        self.provider = provider
        self.data_root = data_root
        self.embedding_store = embedding_store or EmbeddingStore(data_root)
        self.profile_store = profile_store or ProfileStore(data_root)

    def enroll(
        self,
        *,
        profile_id: str,
        role: SpeakerRole,
        strategy: EnrollmentStrategy | str,
        samples: list[EnrollmentSample],
        approved_by: str | None = None,
        candidate_manifest_sha256: str | None = None,
        display_name: str | None = None,
        notes: str | None = None,
        version: int | None = None,
    ) -> EnrollmentResult:
        strategy = get_strategy(strategy) if isinstance(strategy, str) else strategy
        strategy.validate_role(role)

        if not samples:
            raise EnrollmentError("no enrollment samples supplied")

        accepted: list[EnrollmentSample] = []
        rejected: list[dict[str, str]] = []
        for sample in samples:
            admitted, reason = strategy.admit(sample)
            if admitted:
                accepted.append(sample)
            else:
                rejected.append({"sample_id": sample.sample_id, "reason": reason or "rejected"})

        if len(accepted) < strategy.minimum_samples():
            raise EnrollmentError(
                f"Strategy {strategy.name!r} requires at least {strategy.minimum_samples()} "
                f"admissible sample(s); {len(accepted)} were admitted. "
                f"Rejections: {rejected}"
            )

        total_seconds = sum(s.effective_duration for s in accepted)
        if total_seconds < strategy.minimum_total_seconds():
            raise EnrollmentError(
                f"Strategy {strategy.name!r} requires at least "
                f"{strategy.minimum_total_seconds()}s of audio; got {total_seconds:.2f}s"
            )

        if strategy.requires_human_approval and not approved_by:
            raise HumanApprovalRequired(
                f"Strategy {strategy.name!r} requires explicit human approval of the "
                "enrollment seed. Pass approved_by with the identity of the person who "
                "listened to and confirmed these samples. This cannot be defaulted: an "
                "unreviewed seed can silently define the wrong person's profile."
            )

        vectors: list[EmbeddingVector] = [
            self.provider.embed(s.samples, s.sample_rate, bit_depth=s.bit_depth) for s in accepted
        ]
        profile_vector = mean_embedding(vectors) if len(vectors) > 1 else vectors[0]

        resolved_version = version if version is not None else self._next_version(profile_id)
        embedding_id = f"{profile_id}-v{resolved_version}"
        stored = self.embedding_store.save(embedding_id, profile_vector)

        warnings: list[str] = []
        channel_conditions = sorted({s.channel_condition for s in accepted if s.channel_condition})
        if len(channel_conditions) < 2:
            warnings.append(
                "Enrollment covers a single channel condition. Matching against audio "
                "recorded on a different channel is a known source of false rejections; "
                "consider enrolling narrowband and wideband material where possible."
            )
        if len({s.source_file_id for s in accepted if s.source_file_id}) == 1 and len(accepted) > 1:
            warnings.append(
                "All seeds come from one source file, so the profile may encode that "
                "recording's channel characteristics rather than the voice."
            )

        provenance = ProfileProvenance(
            strategy_name=strategy.name,
            strategy_version=strategy.version,
            seed_segment_ids=[s.segment_id for s in accepted if s.segment_id],
            source_file_ids=sorted({s.source_file_id for s in accepted if s.source_file_id}),
            candidate_manifest_sha256=candidate_manifest_sha256,
            approved_by=approved_by,
            approved_at=datetime.now(UTC).isoformat() if approved_by else None,
        )

        profile = SpeakerProfile(
            profile_id=profile_id,
            role=role,
            version=resolved_version,
            enrollment_state=EnrollmentState.ENROLLED,
            provenance=provenance,
            embedding_id=embedding_id,
            embedding_sha256=stored.sha256,
            embedding_dimension=profile_vector.dimension,
            provider_name=self.provider.name,
            provider_version=self.provider.version,
            provider_is_synthetic=self.provider.is_synthetic,
            calibration_state=CalibrationState.UNCALIBRATED,
            sample_count=len(accepted),
            total_duration_seconds=total_seconds,
            channel_conditions=channel_conditions,
            display_name=display_name,
            notes=notes,
        )
        self.profile_store.save(profile)

        return EnrollmentResult(
            profile=profile,
            embedding_id=embedding_id,
            accepted_samples=[s.sample_id for s in accepted],
            rejected_samples=rejected,
            warnings=warnings,
        )

    def _next_version(self, profile_id: str) -> int:
        versions = self.profile_store.versions(profile_id)
        return (versions[-1] + 1) if versions else 1

    def supersede(self, profile_id: str, new_version: int) -> SpeakerProfile | None:
        """Mark every earlier version superseded by `new_version`."""
        replacement = f"{profile_id}@v{new_version}"
        latest_superseded = None
        for version in self.profile_store.versions(profile_id):
            if version >= new_version:
                continue
            profile = self.profile_store.load(profile_id, version)
            if profile.superseded_by is None:
                superseded = profile.supersede(replacement)
                self.profile_store.save(superseded)
                latest_superseded = superseded
        return latest_superseded
