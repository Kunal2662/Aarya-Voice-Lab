"""Stable read contracts for the future Voice Lab Desktop.

The GUI needs to *display* state — profiles, enrollment status,
verification results, review queues, calibration state, provenance, audit
history, pipeline status. It must never reimplement policy: eligibility,
approval rules, and calibration honesty live in Core, and the desktop
renders what Core decides.

Every function here is **read-only** and returns plain JSON-serialisable
dicts. That keeps the GUI free of Python-object coupling and lets the
same contracts back a CLI (`--json`), a local IPC layer, or a future HTTP
surface without changing Core.

Each payload carries the honesty flags — `provider_is_synthetic`,
`calibration_state`, `is_real_identity_claim` — so a UI cannot render a
development result as a real determination without deliberately ignoring
data it was handed.
"""

from __future__ import annotations

from typing import Any

from aarya_voice_lab import __version__
from aarya_voice_lab.core.data_root import DataRoot, list_batches
from aarya_voice_lab.identity.audit import AuditLog
from aarya_voice_lab.identity.calibration import CalibrationRecord, CalibrationState
from aarya_voice_lab.identity.embeddings import EmbeddingStore, any_real_provider_available, available_providers
from aarya_voice_lab.identity.enrollment import describe_strategies
from aarya_voice_lab.identity.preview import preview_loop_state
from aarya_voice_lab.identity.profile import ProfileStore
from aarya_voice_lab.identity.review import IdentityReviewQueue
from aarya_voice_lab.identity.runtime import (
    SYNTHETIC_PROVIDER_CAPABILITY,
    VERIFICATION_ENGINE_CAPABILITY,
    describe_portability,
)
from aarya_voice_lab.identity.verification import VerificationResult
from aarya_voice_lab.pipeline.stages import (
    PHASE_2_STAGES,
    PIPELINE_ORDER,
    SPEAKER_IDENTITY_BOUNDARY,
    is_implemented,
    stage_index,
)

CONTRACT_VERSION = "1.0.0"


def _envelope(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap a payload so consumers can version-check what they received."""
    return {
        "contract": kind,
        "contract_version": CONTRACT_VERSION,
        "processing_version": __version__,
        **payload,
    }


def list_speaker_profiles(data_root: DataRoot) -> dict[str, Any]:
    """All profiles with their current version and usability."""
    store = ProfileStore(data_root)
    profiles = []
    for profile_id in store.list_profiles():
        latest = store.latest(profile_id)
        if latest is None:
            continue
        payload = latest.to_dict()
        payload["all_versions"] = store.versions(profile_id)
        profiles.append(payload)
    return _envelope(
        "speaker_profiles",
        {
            "profiles": profiles,
            "count": len(profiles),
            "usable_count": sum(1 for p in profiles if p["is_usable"]),
        },
    )


def enrollment_status(data_root: DataRoot) -> dict[str, Any]:
    """Enrollment state across all profiles, plus the strategy catalogue."""
    store = ProfileStore(data_root)
    by_state: dict[str, int] = {}
    by_role: dict[str, int] = {}
    for profile_id in store.list_profiles():
        latest = store.latest(profile_id)
        if latest is None:
            continue
        by_state[latest.enrollment_state.value] = by_state.get(latest.enrollment_state.value, 0) + 1
        by_role[latest.role.value] = by_role.get(latest.role.value, 0) + 1
    real_provider_installed = any_real_provider_available()
    return _envelope(
        "enrollment_status",
        {
            "by_state": by_state,
            "by_role": by_role,
            "available_strategies": describe_strategies(),
            "available_providers": available_providers(),
            "real_provider_installed": real_provider_installed,
            "note": (
                "A real embedding provider is installed and loaded on this "
                "machine (see identity.embeddings.any_real_provider_available)."
                if real_provider_installed
                else "No real embedding provider is installed. Only the synthetic "
                "development provider exists in this environment."
            ),
        },
    )


def verification_results_view(results: list[VerificationResult]) -> dict[str, Any]:
    """Verification results with counts the GUI can render directly."""
    by_decision: dict[str, int] = {}
    for result in results:
        by_decision[result.decision.value] = by_decision.get(result.decision.value, 0) + 1
    synthetic = sum(1 for r in results if r.provider_is_synthetic)
    return _envelope(
        "verification_results",
        {
            "results": [r.to_dict() for r in results],
            "count": len(results),
            "by_decision": by_decision,
            "synthetic_count": synthetic,
            "real_identity_claims": sum(1 for r in results if r.is_real_identity_claim),
            "all_synthetic": synthetic == len(results) and bool(results),
        },
    )


def review_queue_view(
    data_root: DataRoot,
    results: list[VerificationResult],
    candidate_index: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The identity review queue plus reviewer-agreement statistics."""
    queue = IdentityReviewQueue(data_root)
    items = queue.build_items(results, candidate_index)
    reviewed = {r["segment_id"] for r in queue.read_all()}
    pending = [i for i in items if i.segment_id not in reviewed]
    return _envelope(
        "review_queue",
        {
            "items": [i.to_dict() for i in items],
            "pending": [i.to_dict() for i in pending],
            "total": len(items),
            "pending_count": len(pending),
            "reviewed_count": len(items) - len(pending),
            "approved_segment_ids": queue.approved_segment_ids(),
            "disagreement": queue.disagreement_rate(),
            "review_type": "identity",
            "note": (
                "Machine eligibility is a recommendation. Every acceptance requires a "
                "human who listened; no confidence level bypasses review."
            ),
        },
    )


def calibration_status(record: CalibrationRecord) -> dict[str, Any]:
    """Calibration state, with its limits stated rather than implied."""
    payload = record.to_dict()
    payload["target_speaker_calibration_possible"] = False
    payload["target_speaker_calibration_note"] = (
        "CALIBRATED is unreachable for the target speaker: calibration requires labelled "
        "held-out data, and every recording of her is inside the dataset being labelled. "
        "This is a property of the data, not a missing feature."
    )
    payload["state_meanings"] = {
        CalibrationState.UNCALIBRATED.value: "No evidence; thresholds are safety defaults.",
        CalibrationState.PROVISIONAL.value: "Evidence exists but supports no statistical claim.",
        CalibrationState.CALIBRATED.value: "Validated against labelled held-out data.",
    }
    return _envelope("calibration_status", payload)


def provenance_chain(
    result: VerificationResult,
    profile_payload: dict[str, Any] | None = None,
    review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The full source → decision chain for one segment."""
    return _envelope(
        "provenance_chain",
        {
            "segment_id": result.segment_id,
            "chain": {
                "source": {
                    "source_file_id": result.source_file_id,
                    "source_sha256": result.source_sha256,
                },
                "candidate": {
                    "segment_id": result.segment_id,
                    "candidate_manifest_sha256": result.candidate_manifest_sha256,
                    "overlap_status": result.overlap_status_inherited,
                },
                "enrollment": (profile_payload or {}).get("provenance"),
                "profile": {
                    "profile_version_key": (profile_payload or {}).get("profile_version_key"),
                    "fingerprint": (profile_payload or {}).get("fingerprint"),
                },
                "embedding": {
                    "embedding_id": (profile_payload or {}).get("embedding_id"),
                    "embedding_sha256": (profile_payload or {}).get("embedding_sha256"),
                    "provider_is_synthetic": result.provider_is_synthetic,
                },
                "verification": {
                    "verification_id": result.verification_id,
                    "fingerprint": result.fingerprint(),
                    "thresholds_hash": result.thresholds_hash,
                    "calibration_state": result.calibration_state.value,
                },
                "decision": {
                    "machine_decision": result.decision.value,
                    "reason": result.reason,
                    "human_decision": (review or {}).get("decision"),
                    "reviewer": (review or {}).get("reviewer"),
                    "listened": (review or {}).get("listened"),
                },
            },
            "is_real_identity_claim": result.is_real_identity_claim,
        },
    )


def audit_history(data_root: DataRoot, subject_id: str | None = None) -> dict[str, Any]:
    """Audit entries, optionally for one subject, plus chain integrity."""
    log = AuditLog(data_root)
    entries = log.history_for(subject_id) if subject_id else log.read_all()
    return _envelope(
        "audit_history",
        {"entries": entries, "subject_id": subject_id, "summary": log.summary()},
    )


def pipeline_status(data_root: DataRoot) -> dict[str, Any]:
    """Stage-by-stage implementation status and the identity boundary."""
    boundary = stage_index(SPEAKER_IDENTITY_BOUNDARY)
    stages = [
        {
            "index": index,
            "name": stage.value,
            "phase": "phase-2" if stage in PHASE_2_STAGES else ("phase-3+" if index >= boundary else "source"),
            "implemented": is_implemented(stage),
            "past_identity_boundary": index >= boundary,
        }
        for index, stage in enumerate(PIPELINE_ORDER)
    ]
    return _envelope(
        "pipeline_status",
        {
            "stages": stages,
            "identity_boundary_index": boundary,
            "identity_boundary_stage": SPEAKER_IDENTITY_BOUNDARY.value,
            "batches": list_batches(data_root),
            "implemented_count": sum(1 for s in stages if s["implemented"]),
        },
    )


def embedding_inventory(data_root: DataRoot) -> dict[str, Any]:
    """What embeddings exist locally. Never returns a vector."""
    store = EmbeddingStore(data_root)
    return _envelope(
        "embedding_inventory",
        {
            "embedding_ids": store.list_ids(),
            "count": len(store.list_ids()),
            "storage_directory": "data/embeddings",
            "git_ignored": True,
            "export_supported": False,
            "note": (
                "Vectors are never returned by any contract. Embeddings are biometric "
                "identifiers and have no export path."
            ),
        },
    )


def runtime_capabilities() -> dict[str, Any]:
    """Component capability declarations, for placement and packaging.

    Vendor-neutral by construction: components declare whether they need
    an accelerator, not which one. Supports VL-D19/D20 portability work
    without hard-coding CUDA anywhere in Core.
    """
    capabilities = [SYNTHETIC_PROVIDER_CAPABILITY, VERIFICATION_ENGINE_CAPABILITY]
    return _envelope(
        "runtime_capabilities",
        {
            "components": [c.to_dict() for c in capabilities],
            "portability": describe_portability(capabilities),
        },
    )


def voice_preview_status() -> dict[str, Any]:
    """VL-V0 preview loop state. Generation is not implemented."""
    return _envelope("voice_preview_status", preview_loop_state([], []))


def desktop_snapshot(data_root: DataRoot) -> dict[str, Any]:
    """One call returning everything the desktop needs on load."""
    return _envelope(
        "desktop_snapshot",
        {
            "profiles": list_speaker_profiles(data_root),
            "enrollment": enrollment_status(data_root),
            "pipeline": pipeline_status(data_root),
            "embeddings": embedding_inventory(data_root),
            "runtime": runtime_capabilities(),
            "preview": voice_preview_status(),
            "audit": audit_history(data_root)["summary"],
        },
    )
