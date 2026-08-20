"""End-to-end synthetic pipeline: discovery, manifests, stage boundaries,
handoff, resumability, and failure handling.

Every byte of audio here is generated from sine waves by
aarya_voice_lab.testing.synthetic_audio. No real recording is read, and
nothing is written inside the repository tree.
"""

from __future__ import annotations

import json
import wave

import pytest

from aarya_voice_lab.core.paths import PROJECT_ROOT
from aarya_voice_lab.environment.specs import EnvironmentId
from aarya_voice_lab.pipeline.contracts import (
    StageContractError,
    StageResult,
    StageStatus,
    describe_artifact,
    is_stage_complete,
    read_stage_result,
    require_predecessor,
    sha256_file,
    stage_directory,
    verify_inputs_unchanged,
)
from aarya_voice_lab.pipeline.inventory import (
    PrivateSourceAccessError,
    build_inventory,
    discover_audio_files,
    require_synthetic_or_approved,
)
from aarya_voice_lab.pipeline.runner import (
    OFFLINE_ENV,
    TELEMETRY_OFF_ENV,
    EnvironmentPaths,
    StageBlocked,
    build_subprocess_env,
    preflight,
    run_stage,
)
from aarya_voice_lab.pipeline.stages import PipelineStage
from aarya_voice_lab.schemas.base import SchemaName, validate
from aarya_voice_lab.testing.synthetic_audio import (
    SPEAKER_A,
    SPEAKER_B,
    generate_corpus,
    generate_silence,
    generate_tone,
    generate_two_speaker_file,
)

# --------------------------------------------------------------------------
# Synthetic audio generation
# --------------------------------------------------------------------------


def test_generated_tone_is_a_readable_wav(tmp_path):
    path = generate_tone(tmp_path / "tone.wav", duration_seconds=0.5)
    with wave.open(str(path), "rb") as fh:
        assert fh.getnchannels() == 1
        assert fh.getframerate() == 16_000
        assert fh.getnframes() == 8000


def test_generated_audio_is_deterministic(tmp_path):
    """Reproducibility: the same fixture twice must be byte-identical."""
    a = generate_tone(tmp_path / "a.wav", frequency_hz=440.0, duration_seconds=0.25)
    b = generate_tone(tmp_path / "b.wav", frequency_hz=440.0, duration_seconds=0.25)
    assert sha256_file(a) == sha256_file(b)


def test_two_speaker_file_reports_ground_truth_turns(tmp_path):
    path, turns = generate_two_speaker_file(tmp_path / "two.wav")
    assert path.is_file()
    labels = {turn.speaker for turn in turns}
    assert labels == {SPEAKER_A.label, SPEAKER_B.label}
    assert any(turn.overlapping for turn in turns)


def test_two_speaker_file_without_overlap(tmp_path):
    _, turns = generate_two_speaker_file(tmp_path / "clean.wav", include_overlap=False)
    assert not any(turn.overlapping for turn in turns)


def test_silence_generation(tmp_path):
    path = generate_silence(tmp_path / "silence.wav", duration_seconds=0.1)
    assert path.stat().st_size > 0


def test_synthetic_audio_is_gitignored():
    """Generated audio must never become committable."""
    import subprocess

    result = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "check-ignore", "-q", "synthetic_000.wav"],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, "generated .wav files are not git-ignored"


# --------------------------------------------------------------------------
# Discovery / inventory
# --------------------------------------------------------------------------


def test_discovery_finds_generated_corpus(tmp_path):
    generate_corpus(tmp_path / "corpus", count=3)
    found = discover_audio_files(tmp_path / "corpus")
    assert len(found) == 3


def test_discovery_ignores_non_audio(tmp_path):
    directory = tmp_path / "mixed"
    directory.mkdir()
    generate_tone(directory / "a.wav")
    (directory / "notes.txt").write_text("not audio", encoding="utf-8")
    assert [p.name for p in discover_audio_files(directory)] == ["a.wav"]


def test_inventory_records_hash_and_duration(tmp_path):
    directory = tmp_path / "corpus"
    generate_corpus(directory, count=2)
    inventory = build_inventory(directory)
    assert len(inventory.files) == 2
    for record in inventory.files:
        assert len(record.sha256) == 64
        assert record.duration_seconds and record.duration_seconds > 0
        assert record.sample_rate == 16_000


def test_inventory_paths_are_relative(tmp_path):
    """Records must not embed absolute paths that could leak private locations."""
    directory = tmp_path / "corpus"
    generate_corpus(directory, count=1)
    for record in build_inventory(directory).files:
        assert not record.path.startswith("/")
        assert str(tmp_path) not in record.path


def test_inventory_refuses_the_private_source_tree():
    """The central Phase 1 guard: no path into source/ may be inventoried."""
    with pytest.raises(PrivateSourceAccessError):
        require_synthetic_or_approved(PROJECT_ROOT / "source")


def test_inventory_refuses_nested_private_paths():
    with pytest.raises(PrivateSourceAccessError):
        require_synthetic_or_approved(PROJECT_ROOT / "source" / "nested" / "deep")


def test_inventory_allows_private_tree_only_with_explicit_approval():
    """The flag exists so a later approved phase can proceed deliberately."""
    require_synthetic_or_approved(PROJECT_ROOT / "source", approved=True)


def test_inventory_allows_ordinary_directories(tmp_path):
    require_synthetic_or_approved(tmp_path)


def test_inventory_on_missing_directory_raises(tmp_path):
    with pytest.raises(NotADirectoryError):
        build_inventory(tmp_path / "nope")


# --------------------------------------------------------------------------
# Stage contracts
# --------------------------------------------------------------------------


def test_stage_result_validates_against_schema(tmp_path):
    result = StageResult(stage=PipelineStage.INVENTORY, environment_id="base")
    result.mark_completed()
    validate(result.to_dict(), SchemaName.STAGE_RESULT)


def test_stage_result_roundtrips_through_disk(tmp_path):
    result = StageResult(stage=PipelineStage.INVENTORY, environment_id="base")
    result.mark_completed()
    result.write(tmp_path)
    loaded = read_stage_result(tmp_path, PipelineStage.INVENTORY)
    assert loaded["status"] == StageStatus.COMPLETED
    assert loaded["environment_id"] == "base"


def test_stage_completion_detection(tmp_path):
    assert not is_stage_complete(tmp_path, PipelineStage.INVENTORY)
    result = StageResult(stage=PipelineStage.INVENTORY, environment_id="base")
    result.mark_completed()
    result.write(tmp_path)
    assert is_stage_complete(tmp_path, PipelineStage.INVENTORY)


def test_failed_stage_is_not_complete(tmp_path):
    result = StageResult(stage=PipelineStage.INVENTORY, environment_id="base")
    result.mark_failed("execution_error", "boom")
    result.write(tmp_path)
    assert not is_stage_complete(tmp_path, PipelineStage.INVENTORY)


def test_blocked_status_is_distinct_from_failed(tmp_path):
    """A stop condition is not a bug — the distinction must survive to disk."""
    result = StageResult(stage=PipelineStage.TRANSCRIPTION, environment_id="env-whisperx")
    result.mark_blocked("credential_required", "token needed", "obtain approval")
    result.write(tmp_path)
    loaded = read_stage_result(tmp_path, PipelineStage.TRANSCRIPTION)
    assert loaded["status"] == StageStatus.BLOCKED
    assert loaded["error"]["kind"] == "credential_required"
    assert loaded["error"]["remediation"]


def test_predecessor_required_before_downstream_stage(tmp_path):
    with pytest.raises(StageContractError, match="requires"):
        require_predecessor(tmp_path, PipelineStage.AUDIO_VALIDATION)


def test_predecessor_must_be_completed_not_merely_present(tmp_path):
    failed = StageResult(stage=PipelineStage.INVENTORY, environment_id="base")
    failed.mark_failed("execution_error", "boom")
    failed.write(tmp_path)
    with pytest.raises(StageContractError, match="completed"):
        require_predecessor(tmp_path, PipelineStage.AUDIO_VALIDATION)


def test_first_stage_has_no_predecessor(tmp_path):
    assert require_predecessor(tmp_path, PipelineStage.SOURCE) is None


def test_predecessor_accepted_when_completed(tmp_path):
    done = StageResult(stage=PipelineStage.INVENTORY, environment_id="base")
    done.mark_completed()
    done.write(tmp_path)
    record = require_predecessor(tmp_path, PipelineStage.AUDIO_VALIDATION)
    assert record["status"] == StageStatus.COMPLETED


def test_artifact_hash_detects_tampering(tmp_path):
    """Resumability depends on hashes actually catching changed content."""
    stage_dir = stage_directory(tmp_path, PipelineStage.INVENTORY)
    stage_dir.mkdir(parents=True)
    artifact = stage_dir / "out.json"
    artifact.write_text('{"a": 1}', encoding="utf-8")

    result = StageResult(stage=PipelineStage.INVENTORY, environment_id="base")
    result.outputs.append(describe_artifact(artifact, tmp_path))
    result.mark_completed()
    result.write(tmp_path)

    record = read_stage_result(tmp_path, PipelineStage.INVENTORY)
    assert verify_inputs_unchanged(tmp_path, record) == []

    artifact.write_text('{"a": 2}', encoding="utf-8")
    problems = verify_inputs_unchanged(tmp_path, record)
    assert problems and "changed" in problems[0]


def test_missing_output_is_detected(tmp_path):
    stage_dir = stage_directory(tmp_path, PipelineStage.INVENTORY)
    stage_dir.mkdir(parents=True)
    artifact = stage_dir / "out.json"
    artifact.write_text("{}", encoding="utf-8")
    result = StageResult(stage=PipelineStage.INVENTORY, environment_id="base")
    result.outputs.append(describe_artifact(artifact, tmp_path))
    result.mark_completed()
    result.write(tmp_path)

    artifact.unlink()
    record = read_stage_result(tmp_path, PipelineStage.INVENTORY)
    assert any("missing" in p for p in verify_inputs_unchanged(tmp_path, record))


def test_artifact_paths_are_relative_to_run_dir(tmp_path):
    stage_dir = stage_directory(tmp_path, PipelineStage.INVENTORY)
    stage_dir.mkdir(parents=True)
    artifact = stage_dir / "out.json"
    artifact.write_text("{}", encoding="utf-8")
    described = describe_artifact(artifact, tmp_path)
    assert not described["path"].startswith("/")


# --------------------------------------------------------------------------
# Runner: environment invocation & failure handling
# --------------------------------------------------------------------------


def test_subprocess_env_disables_telemetry():
    """NeMo pulls in wandb, sentry, nv-one-logger and OTLP exporters; a
    local-first project must switch them off for every stage."""
    env = build_subprocess_env()
    for key, value in TELEMETRY_OFF_ENV.items():
        assert env[key] == value


def test_subprocess_env_is_offline_by_default():
    env = build_subprocess_env()
    for key, value in OFFLINE_ENV.items():
        assert env[key] == value


def test_subprocess_env_can_allow_downloads_explicitly():
    env = build_subprocess_env(offline=False)
    assert "HF_HUB_OFFLINE" not in env or env.get("HF_HUB_OFFLINE") != "1"
    # Telemetry stays off even when downloads are permitted.
    assert env["WANDB_MODE"] == "offline"


def test_preflight_blocks_unbuilt_environment(tmp_path):
    from aarya_voice_lab.environment.specs import get_spec

    with pytest.raises(StageBlocked) as exc:
        preflight(
            PipelineStage.SPEAKER_DIARIZATION,
            get_spec(EnvironmentId.NEMO),
            EnvironmentPaths(root=tmp_path / "missing-env"),
        )
    assert exc.value.kind == "incompatible_environment"


def test_preflight_blocks_environment_requiring_approval(tmp_path):
    from aarya_voice_lab.environment.specs import get_spec

    with pytest.raises(StageBlocked) as exc:
        preflight(
            PipelineStage.TRANSCRIPTION,
            get_spec(EnvironmentId.WHISPERX),
            EnvironmentPaths(root=tmp_path),
        )
    assert exc.value.kind in ("gated_model", "credential_required", "external_service_required")


def test_preflight_blocks_on_missing_ffmpeg(tmp_path, monkeypatch):
    from aarya_voice_lab.environment.specs import get_spec
    from aarya_voice_lab.pipeline import runner as runner_module

    env_root = tmp_path / "env"
    (env_root / "bin").mkdir(parents=True)
    (env_root / "bin" / "python").write_text("", encoding="utf-8")
    monkeypatch.setattr(runner_module.shutil, "which", lambda name: None)

    with pytest.raises(StageBlocked) as exc:
        preflight(
            PipelineStage.TRANSCRIPTION,
            get_spec(EnvironmentId.NEMO),
            EnvironmentPaths(root=env_root),
            require_ffmpeg=True,
        )
    assert exc.value.kind == "missing_dependency"
    assert exc.value.remediation


def test_run_stage_records_block_instead_of_raising(tmp_path):
    """A blocked stage must still produce a readable result record."""
    run_dir = tmp_path / "run"
    result = run_stage(
        PipelineStage.SOURCE,
        EnvironmentId.NEMO,
        ["-c", "pass"],
        run_dir,
        env_paths=EnvironmentPaths(root=tmp_path / "not-built"),
        require_predecessor_complete=False,
    )
    assert result.status == StageStatus.BLOCKED
    assert read_stage_result(run_dir, PipelineStage.SOURCE)["status"] == StageStatus.BLOCKED


def test_run_stage_executes_in_a_real_interpreter(tmp_path):
    """The cross-environment mechanism itself: launch a stage as a subprocess
    using a venv-shaped python path. Uses the current interpreter standing in
    for a built environment, so the test needs no ML install."""
    import sys

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    env_root = tmp_path / "fake-env"
    (env_root / "bin").mkdir(parents=True)
    (env_root / "bin" / "python").symlink_to(sys.executable)

    stage_dir = stage_directory(run_dir, PipelineStage.SOURCE)
    stage_dir.mkdir(parents=True)

    result = run_stage(
        PipelineStage.SOURCE,
        EnvironmentId.NEMO,
        ["-c", f"open({str(stage_dir / 'produced.json')!r}, 'w').write('{{}}')"],
        run_dir,
        env_paths=EnvironmentPaths(root=env_root),
        require_predecessor_complete=False,
    )
    assert result.status == StageStatus.COMPLETED
    assert any(a["path"].endswith("produced.json") for a in result.outputs)


def test_run_stage_records_nonzero_exit_as_failure(tmp_path):
    import sys

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    env_root = tmp_path / "fake-env"
    (env_root / "bin").mkdir(parents=True)
    (env_root / "bin" / "python").symlink_to(sys.executable)

    result = run_stage(
        PipelineStage.SOURCE,
        EnvironmentId.NEMO,
        ["-c", "import sys; sys.exit(7)"],
        run_dir,
        env_paths=EnvironmentPaths(root=env_root),
        require_predecessor_complete=False,
    )
    assert result.status == StageStatus.FAILED
    assert result.error["kind"] == "execution_error"


def test_run_stage_records_contract_violation(tmp_path):
    """Missing predecessor is recorded, not raised, so the run stays inspectable."""
    result = run_stage(
        PipelineStage.SPEAKER_DIARIZATION,
        EnvironmentId.NEMO,
        ["-c", "pass"],
        tmp_path / "run",
        env_paths=EnvironmentPaths(root=tmp_path / "env"),
        require_predecessor_complete=True,
    )
    assert result.status == StageStatus.FAILED
    assert result.error["kind"] == "invalid_input"


# --------------------------------------------------------------------------
# Full synthetic handoff
# --------------------------------------------------------------------------


def test_full_synthetic_handoff_between_two_stages(tmp_path):
    """Stage 1 writes an inventory; stage 2 consumes it via the filesystem
    contract and verifies the hash — the pattern real stages will follow
    across incompatible Python environments."""
    corpus = tmp_path / "corpus"
    generate_corpus(corpus, count=2)
    run_dir = tmp_path / "run"

    inventory = build_inventory(corpus)
    stage_dir = stage_directory(run_dir, PipelineStage.INVENTORY)
    stage_dir.mkdir(parents=True)
    manifest_path = stage_dir / "inventory.json"
    manifest_path.write_text(json.dumps(inventory.to_dict(), indent=2), encoding="utf-8")

    first = StageResult(stage=PipelineStage.INVENTORY, environment_id="base", tool="stdlib")
    first.outputs.append(describe_artifact(manifest_path, run_dir, kind="manifest"))
    first.mark_completed()
    first.write(run_dir)

    predecessor = require_predecessor(run_dir, PipelineStage.AUDIO_VALIDATION)
    assert predecessor["outputs"][0]["kind"] == "manifest"
    assert verify_inputs_unchanged(run_dir, predecessor) == []

    second = StageResult(stage=PipelineStage.AUDIO_VALIDATION, environment_id="base")
    second.inputs.append(describe_artifact(manifest_path, run_dir, kind="manifest"))
    second.mark_blocked("missing_dependency", "FFmpeg not installed for non-WAV containers")
    second.write(run_dir)

    loaded = read_stage_result(run_dir, PipelineStage.AUDIO_VALIDATION)
    assert loaded["status"] == StageStatus.BLOCKED
    assert loaded["inputs"][0]["sha256"] == predecessor["outputs"][0]["sha256"]
    assert loaded["environment_id"] == "base"


def test_handoff_detects_modified_intermediate(tmp_path):
    corpus = tmp_path / "corpus"
    generate_corpus(corpus, count=1)
    run_dir = tmp_path / "run"

    stage_dir = stage_directory(run_dir, PipelineStage.INVENTORY)
    stage_dir.mkdir(parents=True)
    manifest_path = stage_dir / "inventory.json"
    manifest_path.write_text(json.dumps(build_inventory(corpus).to_dict()), encoding="utf-8")

    first = StageResult(stage=PipelineStage.INVENTORY, environment_id="base")
    first.outputs.append(describe_artifact(manifest_path, run_dir, kind="manifest"))
    first.mark_completed()
    first.write(run_dir)

    manifest_path.write_text('{"tampered": true}', encoding="utf-8")
    record = require_predecessor(run_dir, PipelineStage.AUDIO_VALIDATION)
    assert verify_inputs_unchanged(run_dir, record)
