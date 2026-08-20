"""Resumability: decide whether a completed stage's output can be reused.

Reuse is only safe when *everything* that shaped the output is unchanged.
Timestamps are never consulted — they are trivially wrong after a copy, a
checkout, or a clock change, and a stale-but-newer file would be silently
trusted.

An artifact is reusable only if all of these hold:

    input hashes match
    configuration hash matches
    tool version matches
    stage version matches
    every declared output still exists and re-hashes to its recorded value

Any mismatch means recompute. The default answer is "recompute": that
costs CPU, whereas wrongly reusing an artifact silently corrupts a
dataset built from irreplaceable recordings.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from aarya_voice_lab.pipeline.contracts import (
    StageStatus,
    read_stage_result,
    sha256_file,
)
from aarya_voice_lab.pipeline.stages import PipelineStage


class ReuseDecision(StrEnum):
    REUSE = "reuse"
    RECOMPUTE = "recompute"


@dataclass(frozen=True)
class StageFingerprint:
    """Everything that must match for an artifact to be reusable."""

    stage: str
    stage_version: str
    tool: str | None
    tool_version: str | None
    config_hash: str
    input_hashes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "stage_version": self.stage_version,
            "tool": self.tool,
            "tool_version": self.tool_version,
            "config_hash": self.config_hash,
            "input_hashes": list(self.input_hashes),
        }

    def digest(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass
class ReuseEvaluation:
    decision: ReuseDecision
    reasons: list[str] = field(default_factory=list)

    @property
    def can_reuse(self) -> bool:
        return self.decision is ReuseDecision.REUSE

    def to_dict(self) -> dict[str, Any]:
        return {"decision": self.decision.value, "reasons": list(self.reasons)}


def config_hash(config: Any) -> str:
    """Stable hash of a configuration object."""
    if hasattr(config, "to_dict"):
        payload = config.to_dict()
    elif isinstance(config, dict):
        payload = config
    else:
        payload = {"repr": repr(config)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def build_fingerprint(
    stage: PipelineStage,
    *,
    stage_version: str,
    config: Any,
    input_hashes: list[str],
    tool: str | None = None,
    tool_version: str | None = None,
) -> StageFingerprint:
    return StageFingerprint(
        stage=stage.value,
        stage_version=stage_version,
        tool=tool,
        tool_version=tool_version,
        config_hash=config_hash(config),
        input_hashes=tuple(sorted(input_hashes)),
    )


def evaluate_reuse(
    run_dir: Path,
    stage: PipelineStage,
    fingerprint: StageFingerprint,
) -> ReuseEvaluation:
    """Decide whether the stage's existing output may be reused."""
    record = read_stage_result(run_dir, stage)
    if record is None:
        return ReuseEvaluation(ReuseDecision.RECOMPUTE, ["no previous stage result"])

    reasons: list[str] = []

    if record["status"] != StageStatus.COMPLETED:
        # An interrupted run leaves 'running'; a blocked one leaves 'blocked'.
        # Neither produced trustworthy output.
        return ReuseEvaluation(
            ReuseDecision.RECOMPUTE,
            [f"previous run status was {record['status']!r}, not completed"],
        )

    previous = (record.get("software_versions") or {}).get("stage_fingerprint")
    if previous is None:
        reasons.append("previous result recorded no fingerprint")
    elif previous != fingerprint.digest():
        # Report precisely *what* changed — a bare mismatch is unhelpful
        # when someone is trying to understand why work is repeating.
        if record.get("tool_version") != fingerprint.tool_version:
            reasons.append(
                f"tool version changed: {record.get('tool_version')!r} -> {fingerprint.tool_version!r}"
            )
        recorded_config = (record.get("software_versions") or {}).get("config_hash")
        if recorded_config != fingerprint.config_hash:
            reasons.append("configuration changed")
        recorded_stage_version = (record.get("software_versions") or {}).get("stage_version")
        if recorded_stage_version != fingerprint.stage_version:
            reasons.append(
                f"stage version changed: {recorded_stage_version!r} -> {fingerprint.stage_version!r}"
            )
        recorded_inputs = tuple(sorted(a["sha256"] for a in record.get("inputs", [])))
        if recorded_inputs != fingerprint.input_hashes:
            reasons.append("input content changed")
        if not reasons:
            reasons.append("stage fingerprint changed")

    outputs = record.get("outputs", [])
    if not outputs:
        reasons.append("previous run declared no outputs")
    for artifact in outputs:
        path = run_dir / artifact["path"]
        if not path.is_file():
            reasons.append(f"output missing: {artifact['path']}")
        elif sha256_file(path) != artifact["sha256"]:
            reasons.append(f"output corrupted or modified: {artifact['path']}")

    if reasons:
        return ReuseEvaluation(ReuseDecision.RECOMPUTE, reasons)
    return ReuseEvaluation(ReuseDecision.REUSE, ["all provenance values match and outputs are intact"])


def fingerprint_fields(fingerprint: StageFingerprint) -> dict[str, str]:
    """Fields to store in a StageResult's `software_versions` so a later
    run can evaluate reuse against them."""
    return {
        "stage_fingerprint": fingerprint.digest(),
        "stage_version": fingerprint.stage_version,
        "config_hash": fingerprint.config_hash,
    }
