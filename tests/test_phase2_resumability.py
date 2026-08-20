"""Resumability and integrity.

The property under test: a stage may reuse previous output ONLY when
every provenance value matches and the outputs are intact. Wrongly
reusing an artifact silently corrupts a dataset built from irreplaceable
recordings, so every ambiguous case must recompute.
"""

from __future__ import annotations

import json

from aarya_voice_lab.pipeline.contracts import (
    StageResult,
    StageStatus,
    describe_artifact,
    stage_directory,
)
from aarya_voice_lab.pipeline.resume import (
    ReuseDecision,
    build_fingerprint,
    config_hash,
    evaluate_reuse,
    fingerprint_fields,
)
from aarya_voice_lab.pipeline.stages import PipelineStage
from aarya_voice_lab.testing.synthetic_audio import generate_tone

STAGE = PipelineStage.INVENTORY
STAGE_VERSION = "1.0.0"


def _config(threshold: float = 0.5) -> dict:
    return {"threshold": threshold}


def _complete_stage(
    run_dir,
    *,
    stage_version: str = STAGE_VERSION,
    config: dict | None = None,
    input_hashes: list[str] | None = None,
    tool_version: str = "1.0.0",
    output_name: str = "out.json",
    output_content: str = '{"a": 1}',
):
    """Write a completed stage result with a recorded fingerprint."""
    stage_dir = stage_directory(run_dir, STAGE)
    stage_dir.mkdir(parents=True, exist_ok=True)
    artifact = stage_dir / output_name
    artifact.write_text(output_content, encoding="utf-8")

    fingerprint = build_fingerprint(
        STAGE,
        stage_version=stage_version,
        config=config or _config(),
        input_hashes=input_hashes or ["a" * 64],
        tool="synthetic",
        tool_version=tool_version,
    )
    result = StageResult(stage=STAGE, environment_id="base", tool="synthetic", tool_version=tool_version)
    result.inputs = [{"path": "in.bin", "sha256": h, "size_bytes": 1, "kind": None}
                     for h in (input_hashes or ["a" * 64])]
    result.outputs.append(describe_artifact(artifact, run_dir))
    result.software_versions.update(fingerprint_fields(fingerprint))
    result.mark_completed()
    result.write(run_dir)
    return fingerprint, artifact


def test_reuse_when_everything_matches(tmp_path):
    run_dir = tmp_path / "run"
    fingerprint, _ = _complete_stage(run_dir)
    assert evaluate_reuse(run_dir, STAGE, fingerprint).can_reuse


def test_recompute_when_no_previous_run(tmp_path):
    fingerprint = build_fingerprint(
        STAGE, stage_version=STAGE_VERSION, config=_config(), input_hashes=["a" * 64]
    )
    evaluation = evaluate_reuse(tmp_path / "run", STAGE, fingerprint)
    assert evaluation.decision is ReuseDecision.RECOMPUTE
    assert "no previous stage result" in evaluation.reasons[0]


def test_recompute_when_input_changed(tmp_path):
    run_dir = tmp_path / "run"
    _complete_stage(run_dir, input_hashes=["a" * 64])
    changed = build_fingerprint(
        STAGE,
        stage_version=STAGE_VERSION,
        config=_config(),
        input_hashes=["b" * 64],
        tool="synthetic",
        tool_version="1.0.0",
    )
    evaluation = evaluate_reuse(run_dir, STAGE, changed)
    assert not evaluation.can_reuse
    assert any("input content changed" in r for r in evaluation.reasons)


def test_recompute_when_configuration_changed(tmp_path):
    run_dir = tmp_path / "run"
    _complete_stage(run_dir, config=_config(0.5))
    changed = build_fingerprint(
        STAGE,
        stage_version=STAGE_VERSION,
        config=_config(0.9),
        input_hashes=["a" * 64],
        tool="synthetic",
        tool_version="1.0.0",
    )
    evaluation = evaluate_reuse(run_dir, STAGE, changed)
    assert not evaluation.can_reuse
    assert any("configuration changed" in r for r in evaluation.reasons)


def test_recompute_when_tool_version_changed(tmp_path):
    run_dir = tmp_path / "run"
    _complete_stage(run_dir, tool_version="1.0.0")
    changed = build_fingerprint(
        STAGE,
        stage_version=STAGE_VERSION,
        config=_config(),
        input_hashes=["a" * 64],
        tool="synthetic",
        tool_version="2.0.0",
    )
    evaluation = evaluate_reuse(run_dir, STAGE, changed)
    assert not evaluation.can_reuse
    assert any("tool version changed" in r for r in evaluation.reasons)


def test_recompute_when_stage_version_changed(tmp_path):
    run_dir = tmp_path / "run"
    _complete_stage(run_dir, stage_version="1.0.0")
    changed = build_fingerprint(
        STAGE,
        stage_version="2.0.0",
        config=_config(),
        input_hashes=["a" * 64],
        tool="synthetic",
        tool_version="1.0.0",
    )
    evaluation = evaluate_reuse(run_dir, STAGE, changed)
    assert not evaluation.can_reuse
    assert any("stage version changed" in r for r in evaluation.reasons)


def test_recompute_when_output_corrupted(tmp_path):
    """A modified output must never be trusted, even with matching provenance."""
    run_dir = tmp_path / "run"
    fingerprint, artifact = _complete_stage(run_dir)
    artifact.write_text('{"a": 999}', encoding="utf-8")
    evaluation = evaluate_reuse(run_dir, STAGE, fingerprint)
    assert not evaluation.can_reuse
    assert any("corrupted" in r for r in evaluation.reasons)


def test_recompute_when_output_missing(tmp_path):
    run_dir = tmp_path / "run"
    fingerprint, artifact = _complete_stage(run_dir)
    artifact.unlink()
    evaluation = evaluate_reuse(run_dir, STAGE, fingerprint)
    assert not evaluation.can_reuse
    assert any("missing" in r for r in evaluation.reasons)


def test_recompute_after_interrupted_run(tmp_path):
    """An interrupted stage leaves status 'running' — never reusable."""
    run_dir = tmp_path / "run"
    stage_dir = stage_directory(run_dir, STAGE)
    stage_dir.mkdir(parents=True)
    result = StageResult(stage=STAGE, environment_id="base")
    result.status = StageStatus.RUNNING
    result.write(run_dir)

    fingerprint = build_fingerprint(
        STAGE, stage_version=STAGE_VERSION, config=_config(), input_hashes=["a" * 64]
    )
    evaluation = evaluate_reuse(run_dir, STAGE, fingerprint)
    assert not evaluation.can_reuse
    assert any("not completed" in r for r in evaluation.reasons)


def test_recompute_after_blocked_run(tmp_path):
    """A blocked stage produced no trustworthy output."""
    run_dir = tmp_path / "run"
    result = StageResult(stage=STAGE, environment_id="base")
    result.mark_blocked("missing_dependency", "FFmpeg absent")
    result.write(run_dir)

    fingerprint = build_fingerprint(
        STAGE, stage_version=STAGE_VERSION, config=_config(), input_hashes=["a" * 64]
    )
    assert not evaluate_reuse(run_dir, STAGE, fingerprint).can_reuse


def test_recompute_when_no_outputs_declared(tmp_path):
    run_dir = tmp_path / "run"
    result = StageResult(stage=STAGE, environment_id="base")
    fingerprint = build_fingerprint(
        STAGE, stage_version=STAGE_VERSION, config=_config(), input_hashes=["a" * 64]
    )
    result.software_versions.update(fingerprint_fields(fingerprint))
    result.mark_completed()
    result.write(run_dir)
    assert not evaluate_reuse(run_dir, STAGE, fingerprint).can_reuse


def test_rerun_after_successful_run_reuses(tmp_path):
    """The normal resume path: nothing changed, so nothing is redone."""
    run_dir = tmp_path / "run"
    fingerprint, _ = _complete_stage(run_dir)
    for _ in range(3):
        assert evaluate_reuse(run_dir, STAGE, fingerprint).can_reuse


def test_timestamps_are_not_used_for_reuse(tmp_path):
    """Touching a file must not affect the decision — only hashes count."""
    import os
    import time

    run_dir = tmp_path / "run"
    fingerprint, artifact = _complete_stage(run_dir)
    future = time.time() + 10_000
    os.utime(artifact, (future, future))
    assert evaluate_reuse(run_dir, STAGE, fingerprint).can_reuse


def test_config_hash_is_stable_and_order_independent():
    assert config_hash({"a": 1, "b": 2}) == config_hash({"b": 2, "a": 1})
    assert config_hash({"a": 1}) != config_hash({"a": 2})


def test_fingerprint_digest_changes_with_any_field():
    base = build_fingerprint(
        STAGE, stage_version="1", config={"x": 1}, input_hashes=["a" * 64], tool_version="1"
    )
    variants = [
        build_fingerprint(STAGE, stage_version="2", config={"x": 1}, input_hashes=["a" * 64], tool_version="1"),
        build_fingerprint(STAGE, stage_version="1", config={"x": 2}, input_hashes=["a" * 64], tool_version="1"),
        build_fingerprint(STAGE, stage_version="1", config={"x": 1}, input_hashes=["b" * 64], tool_version="1"),
        build_fingerprint(STAGE, stage_version="1", config={"x": 1}, input_hashes=["a" * 64], tool_version="2"),
    ]
    for variant in variants:
        assert variant.digest() != base.digest()


def test_input_hash_order_does_not_matter():
    a = build_fingerprint(STAGE, stage_version="1", config={}, input_hashes=["a" * 64, "b" * 64])
    b = build_fingerprint(STAGE, stage_version="1", config={}, input_hashes=["b" * 64, "a" * 64])
    assert a.digest() == b.digest()


def test_real_artifact_hashing_detects_change(tmp_path):
    """End-to-end with a generated WAV rather than a synthetic hash."""
    run_dir = tmp_path / "run"
    stage_dir = stage_directory(run_dir, STAGE)
    stage_dir.mkdir(parents=True)
    audio = generate_tone(stage_dir / "clip.wav", duration_seconds=0.2)

    fingerprint = build_fingerprint(
        STAGE, stage_version=STAGE_VERSION, config=_config(), input_hashes=["a" * 64]
    )
    result = StageResult(stage=STAGE, environment_id="base")
    result.outputs.append(describe_artifact(audio, run_dir))
    result.software_versions.update(fingerprint_fields(fingerprint))
    result.mark_completed()
    result.write(run_dir)

    assert evaluate_reuse(run_dir, STAGE, fingerprint).can_reuse
    generate_tone(audio, duration_seconds=0.3)
    assert not evaluate_reuse(run_dir, STAGE, fingerprint).can_reuse


def test_stage_result_with_fingerprint_validates(tmp_path):
    """Fingerprint fields must fit the existing stage_result schema."""
    from aarya_voice_lab.schemas.base import SchemaName, validate

    run_dir = tmp_path / "run"
    fingerprint, _ = _complete_stage(run_dir)
    record = json.loads((stage_directory(run_dir, STAGE) / "result.json").read_text(encoding="utf-8"))
    validate(record, SchemaName.STAGE_RESULT)
    assert record["software_versions"]["stage_fingerprint"] == fingerprint.digest()
