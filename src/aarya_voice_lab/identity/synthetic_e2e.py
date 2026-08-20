"""Synthetic end-to-end run of the whole Phase 3 architecture.

Exercises every link in the chain without a real recording, a real
speaker model, or a real embedding:

    synthetic audio -> candidate -> enrollment -> profile -> embedding
    -> verification -> score -> threshold -> decision -> audit -> provenance

Every artifact it produces is marked synthetic, so the run proves the
software works while remaining structurally incapable of producing an
identity conclusion about anyone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.identity.audit import AuditEventType, AuditLog
from aarya_voice_lab.identity.calibration import (
    CalibrationRecord,
    provisional_from_synthetic,
    uncalibrated,
)
from aarya_voice_lab.identity.embeddings import (
    EmbeddingStore,
    SyntheticEmbeddingProvider,
)
from aarya_voice_lab.identity.enrollment import (
    EnrollmentEngine,
    EnrollmentSample,
    get_strategy,
)
from aarya_voice_lab.identity.profile import ProfileStore, SpeakerRole
from aarya_voice_lab.identity.review import (
    IdentityDecision,
    IdentityReviewQueue,
    IdentityReviewRecord,
    promote_to_dataset,
)
from aarya_voice_lab.identity.verification import (
    VerificationEngine,
    VerificationResult,
)
from aarya_voice_lab.testing.synthetic_audio import (
    generate_narrowband,
    generate_speech_like,
)

SYNTHETIC_ACTOR = "synthetic-e2e-harness"


@dataclass
class SyntheticE2EResult:
    profiles: dict[str, Any] = field(default_factory=dict)
    verifications: list[VerificationResult] = field(default_factory=list)
    reviews: list[dict[str, Any]] = field(default_factory=list)
    calibration: CalibrationRecord | None = None
    audit_summary: dict[str, Any] = field(default_factory=dict)
    promotions: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        by_decision: dict[str, int] = {}
        for verification in self.verifications:
            by_decision[verification.decision.value] = by_decision.get(verification.decision.value, 0) + 1
        return {
            "profiles": len(self.profiles),
            "verifications": len(self.verifications),
            "by_decision": by_decision,
            "reviews": len(self.reviews),
            "promoted_to_dataset": sum(1 for p in self.promotions if p["promoted"]),
            "calibration_state": self.calibration.state.value if self.calibration else None,
            "audit_entries": self.audit_summary.get("entry_count", 0),
            "audit_chain_intact": self.audit_summary.get("chain_intact"),
            "all_synthetic": all(v.provider_is_synthetic for v in self.verifications),
            "real_identity_claims": sum(1 for v in self.verifications if v.is_real_identity_claim),
        }


def _samples_from(path: Path, sample_id: str, *, channel: str, **kwargs) -> EnrollmentSample:
    from aarya_voice_lab.audio.probe import read_wav_mono_samples

    samples, rate = read_wav_mono_samples(path)
    return EnrollmentSample(
        sample_id=sample_id,
        samples=samples,
        sample_rate=rate,
        channel_condition=channel,
        **kwargs,
    )


def run_synthetic_e2e(workspace: Path, *, data_root: DataRoot | None = None) -> SyntheticE2EResult:
    """Run the full Phase 3 chain on generated audio.

    `workspace` holds the generated fixtures; `data_root` (defaulting to a
    subdirectory of the workspace) holds embeddings, profiles, reviews,
    and the audit log — never the repository's real data root.
    """
    from aarya_voice_lab.audio.probe import read_wav_mono_samples

    workspace.mkdir(parents=True, exist_ok=True)
    data = data_root or DataRoot(root=workspace / "data")
    data.create()

    provider = SyntheticEmbeddingProvider()
    embedding_store = EmbeddingStore(data)
    profile_store = ProfileStore(data)
    audit = AuditLog(data)
    result = SyntheticE2EResult()

    # --- 1. synthetic audio -------------------------------------------------
    audio = workspace / "audio"
    speaker_a_wide = generate_speech_like(audio / "a_wide.wav", frequency_hz=180.0, duration_seconds=3.0)
    speaker_a_alt = generate_speech_like(audio / "a_alt.wav", frequency_hz=182.0, duration_seconds=3.0)
    speaker_a_narrow = generate_narrowband(audio / "a_narrow.wav", duration_seconds=3.0)
    speaker_b_wide = generate_speech_like(audio / "b_wide.wav", frequency_hz=320.0, duration_seconds=3.0)
    speaker_b_alt = generate_speech_like(audio / "b_alt.wav", frequency_hz=318.0, duration_seconds=3.0)

    # --- 2. enrollment ------------------------------------------------------
    engine = EnrollmentEngine(provider, data, embedding_store=embedding_store, profile_store=profile_store)

    # Roles are realistic (OPERATOR / TARGET_SPEAKER) so the full decision
    # tree runs exactly as it would on real data. The audio is generated and
    # the provider is synthetic, so every output is stamped synthetic and the
    # ELIGIBLE -> SYNTHETIC_ONLY guard is exercised rather than bypassed.
    operator = engine.enroll(
        profile_id="synthetic-operator",
        role=SpeakerRole.OPERATOR,
        strategy=get_strategy("direct_recording"),
        samples=[
            _samples_from(speaker_b_wide, "op-1", channel="wideband_16000"),
            _samples_from(speaker_b_alt, "op-2", channel="wideband_16000"),
        ],
        display_name="Synthetic operator stand-in (generated audio)",
    )
    audit.append(
        AuditEventType.ENROLLMENT_CREATED,
        actor=SYNTHETIC_ACTOR,
        subject_id=operator.profile.profile_version_key,
        detail={"strategy": "direct_recording", "samples": len(operator.accepted_samples)},
    )

    # Target enrolled from wideband only, so the narrowband case below is a
    # genuine channel-mismatch test rather than a condition already absorbed
    # into the profile.
    target = engine.enroll(
        profile_id="synthetic-target",
        role=SpeakerRole.TARGET_SPEAKER,
        strategy=get_strategy("direct_recording"),
        samples=[
            _samples_from(speaker_a_wide, "tg-1", channel="wideband_16000"),
            _samples_from(speaker_a_alt, "tg-2", channel="wideband_16000"),
        ],
        display_name="Synthetic target stand-in (generated audio)",
    )
    audit.append(
        AuditEventType.ENROLLMENT_CREATED,
        actor=SYNTHETIC_ACTOR,
        subject_id=target.profile.profile_version_key,
        detail={"strategy": "direct_recording", "samples": len(target.accepted_samples)},
    )
    result.profiles = {
        "operator": operator.profile.to_dict(),
        "target": target.profile.to_dict(),
    }
    result.warnings.extend(operator.warnings + target.warnings)

    # --- 3. provisional calibration from synthetic score distributions ------
    target_vector = embedding_store.load(target.profile.embedding_id)
    genuine, impostor = [], []
    from aarya_voice_lab.identity.embeddings import cosine_similarity

    for path in (speaker_a_wide, speaker_a_alt, speaker_a_narrow):
        samples, rate = read_wav_mono_samples(path)
        genuine.append(cosine_similarity(target_vector, provider.embed(samples, rate)))
    for path in (speaker_b_wide, speaker_b_alt):
        samples, rate = read_wav_mono_samples(path)
        impostor.append(cosine_similarity(target_vector, provider.embed(samples, rate)))

    calibration = provisional_from_synthetic(
        "cal-synthetic-001", genuine, impostor, provider.name, provider.version
    )
    result.calibration = calibration
    audit.append(
        AuditEventType.CALIBRATION_CREATED,
        actor=SYNTHETIC_ACTOR,
        subject_id=calibration.calibration_id,
        detail={"state": calibration.state.value, "evidence": calibration.evidence.value},
    )

    # --- 4. verification ----------------------------------------------------
    # A second store stands in for the independent secondary system, so the
    # two-system agreement path (and the ELIGIBLE -> SYNTHETIC_ONLY guard
    # behind it) is exercised. With real models the secondary would be a
    # different model family in its own environment.
    verifier = VerificationEngine(
        embedding_store=embedding_store,
        calibration=calibration,
        target_profile=target.profile,
        operator_profile=operator.profile,
        secondary_embedding_store=embedding_store,
    )

    cases = [
        ("seg-positive", speaker_a_wide, "NO_OVERLAP_DETECTED", True),
        ("seg-negative", speaker_b_wide, "NO_OVERLAP_DETECTED", True),
        ("seg-channel-mismatch", speaker_a_narrow, "NO_OVERLAP_DETECTED", True),
        ("seg-overlap", speaker_a_alt, "OVERLAP_DETECTED", True),
        ("seg-unknown-overlap", speaker_a_alt, "UNKNOWN", True),
        ("seg-poor-quality", speaker_a_wide, "NO_OVERLAP_DETECTED", False),
    ]
    for segment_id, path, overlap, quality_ok in cases:
        samples, rate = read_wav_mono_samples(path)
        candidate = provider.embed(samples, rate)
        verification = verifier.verify(
            verification_id=f"ver-{segment_id}",
            segment_id=segment_id,
            candidate=candidate,
            duration_seconds=len(samples) / rate,
            overlap_status=overlap,
            quality_acceptable=quality_ok,
            source_file_id=f"src-{segment_id}",
            secondary_candidate=candidate,
        )
        result.verifications.append(verification)
        audit.append(
            AuditEventType.VERIFICATION_RUN,
            actor=SYNTHETIC_ACTOR,
            subject_id=segment_id,
            detail={"decision": verification.decision.value, "synthetic": True},
        )

    # --- 5. review ----------------------------------------------------------
    queue = IdentityReviewQueue(data)
    for verification in result.verifications:
        if verification.decision.value not in queue.REVIEWABLE_DECISIONS:
            continue
        record = IdentityReviewRecord(
            review_id=f"rev-{verification.segment_id}",
            segment_id=verification.segment_id,
            verification_id=verification.verification_id,
            reviewer=SYNTHETIC_ACTOR,
            decision=(
                IdentityDecision.CONFIRM_TARGET
                if verification.decision.value
                in ("eligible", "synthetic_only")
                else IdentityDecision.AMBIGUOUS
            ),
            listened=True,
            listen_duration_seconds=3.0,
            machine_recommendation=verification.decision.value,
            notes="synthetic harness decision; not a human judgement about any person",
        )
        queue.record(record)
        result.reviews.append(record.to_dict())
        audit.append(
            AuditEventType.REVIEW_DECISION,
            actor=SYNTHETIC_ACTOR,
            subject_id=verification.segment_id,
            detail={"decision": record.decision.value, "listened": True},
        )

    # --- 6. promotion attempt (must be refused: synthetic provenance) -------
    for verification in result.verifications:
        review = queue.latest_for(verification.segment_id)
        promoted, reason = promote_to_dataset(verification, review)
        result.promotions.append(
            {"segment_id": verification.segment_id, "promoted": promoted, "reason": reason}
        )

    result.audit_summary = audit.summary()
    return result


def uncalibrated_baseline() -> CalibrationRecord:
    provider = SyntheticEmbeddingProvider()
    return uncalibrated(provider.name, provider.version, is_synthetic=True)
