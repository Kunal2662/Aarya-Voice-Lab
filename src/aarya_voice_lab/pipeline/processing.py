"""Processing queue — VL-D4 §5, §15, §17, §23, §24. Orchestrates one
recording's technical processing (boundary conditioning, normalization,
a noise-conditioning decision, and a before/after quality re-check) into
one derived artifact with a deterministic identity.

This module coordinates existing Phase 2/VL-D3 modules — it reimplements
none of them:

* `audio.analysis.measure()` / `audio.vad.detect_regions()` / `pipeline.quality.assess_quality()`
  for the before/after measurement and decision (unchanged).
* `pipeline.conditioning.condition_boundaries()` for boundary trim (no
  FFmpeg required) and `apply_noise_conditioning()` for the noise-mode
  decision.
* `pipeline.normalization.normalize_file()` for sample-rate/channel/bit-
  depth/loudness conditioning (FFmpeg-gated, honestly blocked when
  unavailable — never silently substituted).
* `pipeline.resume.StageFingerprint` for the derived artifact's identity
  (VL-D4 §17: same input + profile + config + tool/stage version must
  produce a reproducible id — exactly what `StageFingerprint.digest()`
  already computes for pipeline stages generally).

**Source is opened read-only throughout.** Every write lands in
`DataRoot.working()`/`DataRoot.batch_working()`, never in `source/` —
enforced the same way `pipeline.normalization` and `pipeline.conditioning`
already enforce it (`assert_source_writable`), not by this module
re-checking it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from aarya_voice_lab.audio.analysis import AudioMeasurements, measure
from aarya_voice_lab.audio.probe import AudioReadError, read_wav_mono_samples
from aarya_voice_lab.audio.vad import detect_regions
from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.pipeline.conditioning import (
    ConditioningBlocked,
    apply_noise_conditioning,
    condition_boundaries,
)
from aarya_voice_lab.pipeline.contracts import sha256_file
from aarya_voice_lab.pipeline.normalization import NormalizationBlocked, ffmpeg_version, normalize_file
from aarya_voice_lab.pipeline.processing_profile import ProcessingProfile
from aarya_voice_lab.pipeline.quality import QualityDecision, assess_quality
from aarya_voice_lab.pipeline.resume import StageFingerprint

PROCESSING_STAGE = "voice_processing"
PROCESSING_VERSION = "1.0.0"


class ProcessingStatus(StrEnum):
    QUEUED = "QUEUED"
    PREPARING = "PREPARING"
    PROCESSING = "PROCESSING"
    QUALITY_CHECK = "QUALITY_CHECK"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


TERMINAL_STATUSES: frozenset[ProcessingStatus] = frozenset(
    {
        ProcessingStatus.SUCCESS,
        ProcessingStatus.WARNING,
        ProcessingStatus.FAILED,
        ProcessingStatus.BLOCKED,
        ProcessingStatus.CANCELLED,
    }
)


def is_terminal(status: ProcessingStatus) -> bool:
    return status in TERMINAL_STATUSES


class ProcessingDecision(StrEnum):
    NO_PROCESSING = "NO_PROCESSING"
    LIGHT_CONDITIONING = "LIGHT_CONDITIONING"
    STANDARD_CONDITIONING = "STANDARD_CONDITIONING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


@dataclass(frozen=True)
class ProcessingDecisionThresholds:
    """Config-driven boundary between decision tiers (§15) — a separate
    dataclass from `pipeline.quality.QualityThresholds` because it
    decides a *processing* action, not a *quality* pass/fail. Based on
    estimated SNR, the same coarse signal `QualityThresholds` already
    uses for its own review/warning split."""

    min_snr_db_for_no_processing: float = 25.0
    min_snr_db_for_light: float = 12.0
    min_snr_db_for_standard: float = 6.0
    # Below min_snr_db_for_standard -> REVIEW_REQUIRED.


def decide_processing(
    measurements: AudioMeasurements,
    thresholds: ProcessingDecisionThresholds | None = None,
) -> ProcessingDecision:
    """Turn a *measurement* into a processing *decision* — kept strictly
    separate from `decide_processing`'s caller ever computing the
    measurement itself (VL-D4 §15)."""
    thresholds = thresholds or ProcessingDecisionThresholds()
    snr = measurements.estimated_snr_db
    if snr is None:
        return ProcessingDecision.REVIEW_REQUIRED
    if snr >= thresholds.min_snr_db_for_no_processing:
        return ProcessingDecision.NO_PROCESSING
    if snr >= thresholds.min_snr_db_for_light:
        return ProcessingDecision.LIGHT_CONDITIONING
    if snr >= thresholds.min_snr_db_for_standard:
        return ProcessingDecision.STANDARD_CONDITIONING
    return ProcessingDecision.REVIEW_REQUIRED


def build_artifact_fingerprint(
    *,
    source_sha256: str,
    profile: ProcessingProfile,
    tool_version: str | None,
) -> StageFingerprint:
    """Deterministic derived-artifact identity (§17): the same source
    content, profile configuration, and tool version always yields the
    same fingerprint digest — never a filename or a timestamp."""
    return StageFingerprint(
        stage=PROCESSING_STAGE,
        stage_version=PROCESSING_VERSION,
        tool="ffmpeg",
        tool_version=tool_version,
        config_hash=profile.config_hash(),
        input_hashes=(source_sha256,),
    )


class ProcessingBlockedError(RuntimeError):
    """The item cannot be processed at all (source verification failed,
    source unreadable) — distinct from a WARNING (processed with a
    caveat, e.g. an optional tool unavailable) or a FAILED (an
    unexpected error)."""


@dataclass
class ProcessingItem:
    item_id: str
    recording_id: str
    source_path: Path
    source_sha256: str
    profile: ProcessingProfile
    status: ProcessingStatus = ProcessingStatus.QUEUED
    progress: float = 0.0
    current_operation: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    derived_artifact: dict[str, Any] | None = None
    processing_duration_seconds: float | None = None
    quality_before: dict[str, Any] | None = None
    quality_after: dict[str, Any] | None = None
    decision: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "recording_id": self.recording_id,
            "source_sha256": self.source_sha256,
            "profile_id": self.profile.profile_id,
            "status": self.status.value,
            "progress": self.progress,
            "current_operation": self.current_operation,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "derived_artifact": self.derived_artifact,
            "processing_duration_seconds": self.processing_duration_seconds,
            "quality_before": self.quality_before,
            "quality_after": self.quality_after,
            "decision": self.decision,
        }


class ProcessingQueue:
    """Mirrors `pipeline.import_intake.ImportQueue`'s shape: sequential
    processing, one broad `except Exception` per item so a single bad
    recording can never stop the rest of the queue (VL-D4 §5)."""

    def __init__(
        self,
        *,
        data_root: DataRoot,
        working_dir: Path | None = None,
        decision_thresholds: ProcessingDecisionThresholds | None = None,
    ) -> None:
        self._data_root = data_root
        self._working_dir = working_dir or data_root.working
        self._items: dict[str, ProcessingItem] = {}
        self._order: list[str] = []
        self._decision_thresholds = decision_thresholds or ProcessingDecisionThresholds()

    def enqueue(
        self,
        *,
        recording_id: str,
        source_path: Path,
        source_sha256: str,
        profile: ProcessingProfile,
    ) -> ProcessingItem:
        item_id = f"proc-{len(self._order):04d}-{recording_id}"
        item = ProcessingItem(
            item_id=item_id,
            recording_id=recording_id,
            source_path=source_path,
            source_sha256=source_sha256,
            profile=profile,
        )
        self._items[item_id] = item
        self._order.append(item_id)
        return item

    def cancel(self, item_id: str) -> ProcessingItem:
        item = self._items[item_id]
        if item.status == ProcessingStatus.QUEUED:
            item.status = ProcessingStatus.CANCELLED
        return item

    def retry(self, item_id: str, *, profile: ProcessingProfile | None = None) -> ProcessingItem:
        item = self._items[item_id]
        if profile is not None:
            item.profile = profile
        item.status = ProcessingStatus.QUEUED
        item.warnings = []
        item.errors = []
        item.derived_artifact = None
        return self.process_one(item_id)

    def process_one(self, item_id: str) -> ProcessingItem:  # noqa: C901 -- one linear pipeline, kept together for readability
        item = self._items[item_id]
        if item.status == ProcessingStatus.CANCELLED:
            return item

        started = datetime.now(UTC)
        try:
            item.status = ProcessingStatus.PREPARING
            item.current_operation = "verifying source"
            actual = sha256_file(item.source_path)
            if actual != item.source_sha256:
                raise ProcessingBlockedError(
                    f"source hash mismatch for {item.recording_id}: expected {item.source_sha256[:16]}…, "
                    f"found {actual[:16]}…. Source recordings are immutable; processing stopped."
                )

            samples, rate = read_wav_mono_samples(item.source_path)
            duration = len(samples) / rate if rate else 0.0
            before_measurements = measure(samples, rate)
            vad = detect_regions(samples, rate)
            before_assessment = assess_quality(
                item.recording_id, before_measurements, vad, thresholds=item.profile.quality_thresholds
            )
            item.quality_before = before_assessment.to_dict()
            item.decision = decide_processing(before_measurements, self._decision_thresholds).value

            item.status = ProcessingStatus.PROCESSING
            derived_path = item.source_path
            current_sha = item.source_sha256

            item.current_operation = "boundary conditioning"
            boundary_dest = self._working_dir / f"{item.item_id}.boundary.wav"
            boundary_record = condition_boundaries(
                derived_path,
                boundary_dest,
                source_file_id=item.recording_id,
                source_sha256=current_sha,
                vad=vad,
                duration_seconds=duration,
                data_root=self._data_root,
                policy=item.profile.boundary,
            )
            derived_path = boundary_dest
            current_sha = boundary_record.output_sha256

            item.current_operation = "normalization"
            norm_record = None
            norm_dest = self._working_dir / f"{item.item_id}.normalized.wav"
            try:
                norm_record = normalize_file(
                    derived_path,
                    norm_dest,
                    source_file_id=item.recording_id,
                    source_sha256=current_sha,
                    data_root=self._data_root,
                    config=item.profile.normalization,
                )
                if norm_record.status == "completed":
                    derived_path = norm_dest
                    current_sha = norm_record.output_sha256
                else:
                    item.warnings.append(f"normalization failed: {norm_record.note}")
            except NormalizationBlocked as exc:
                item.warnings.append(f"normalization unavailable: {exc}")

            noise_result = apply_noise_conditioning(item.profile.noise_conditioning_mode)
            if noise_result.outcome.value == "not_available":
                item.warnings.append(noise_result.note)

            item.status = ProcessingStatus.QUALITY_CHECK
            item.current_operation = "quality re-check"
            after_samples, after_rate = read_wav_mono_samples(derived_path)
            after_measurements = measure(after_samples, after_rate)
            after_vad = detect_regions(after_samples, after_rate)
            after_assessment = assess_quality(
                item.recording_id, after_measurements, after_vad, thresholds=item.profile.quality_thresholds
            )
            item.quality_after = after_assessment.to_dict()

            fingerprint = build_artifact_fingerprint(
                source_sha256=item.source_sha256, profile=item.profile, tool_version=ffmpeg_version()
            )
            item.derived_artifact = {
                "artifact_id": fingerprint.digest(),
                "fingerprint": fingerprint.to_dict(),
                "output_path": derived_path.name,
                "output_sha256": current_sha,
                "boundary": boundary_record.to_dict(),
                "normalization": norm_record.to_dict() if norm_record else None,
                "noise_conditioning": noise_result.to_dict(),
            }

            if after_assessment.decision == QualityDecision.FAIL:
                item.status = ProcessingStatus.WARNING
                item.warnings.append("derived audio quality re-check is FAIL")
            elif item.warnings:
                item.status = ProcessingStatus.WARNING
            else:
                item.status = ProcessingStatus.SUCCESS
        except (ProcessingBlockedError, ConditioningBlocked, AudioReadError) as exc:
            item.status = ProcessingStatus.BLOCKED
            item.errors.append(str(exc))
        except Exception as exc:  # noqa: BLE001 -- one item's failure must never crash the queue
            item.status = ProcessingStatus.FAILED
            item.errors.append(str(exc))
        finally:
            item.current_operation = None
            item.progress = 1.0
            item.processing_duration_seconds = (datetime.now(UTC) - started).total_seconds()
        return item

    def process_all(self) -> list[ProcessingItem]:
        return [
            self.process_one(item_id)
            for item_id in self._order
            if self._items[item_id].status == ProcessingStatus.QUEUED
        ]

    def list(self) -> list[ProcessingItem]:
        return [self._items[item_id] for item_id in self._order]

    def get(self, item_id: str) -> ProcessingItem | None:
        return self._items.get(item_id)

    def counts(self) -> dict[str, int]:
        counts = dict.fromkeys((s.value for s in ProcessingStatus), 0)
        for item in self.list():
            counts[item.status.value] += 1
        return counts
