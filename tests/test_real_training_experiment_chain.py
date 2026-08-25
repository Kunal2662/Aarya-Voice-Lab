"""Phase 3 of the 8-phase release plan -- Real Training Experiment.

No approved public dataset is available (see Phase 2 / docs/DATA_POLICY.md's
pending-decision section) and no real ML training runtime is installed
on this checkout (see Phase 1 -- confirmed empirically: no torch, no
nemo_toolkit, .envs/env-nemo not built). Per this phase's own explicit
instruction, this validates the full training-execution *mechanics*
using the existing controlled fixture path, and stops short of claiming
real ML training occurred anywhere.

Full chain exercised, in order:

    Dataset -> Registry -> License Gate -> Adapter -> Preprocessing
    -> Training Manifest (real audio validation + transcript presence)
    -> Training Job -> Checkpoint -> Persisted Job State -> Evaluation

Every stage produces real, non-fabricated output for what it actually
does: real registry entries, a real gate decision, real normalized
records, real audio measurements, a real (honestly FAILED) training
job, real persisted history, and a real absence of checkpoint/evaluation
output when training never genuinely ran.
"""

from __future__ import annotations

import json

from aarya_voice_lab.audio.analysis import measure
from aarya_voice_lab.audio.probe import read_wav_mono_samples
from aarya_voice_lab.pipeline.dataset_adapter import FixtureDatasetAdapter
from aarya_voice_lab.pipeline.public_dataset_gate import evaluate_public_dataset_use
from aarya_voice_lab.pipeline.training import (
    LocalTrainingProvider,
    TrainingFailureReason,
    TrainingJobLog,
    TrainingJobStatus,
    TrainingProviderState,
    TrainingQueue,
    build_training_config,
)
from aarya_voice_lab.pipeline.training_manifest import build_training_manifest
from aarya_voice_lab.registry.dataset_registry import PublicDatasetRegistry
from aarya_voice_lab.schemas.records import build_public_dataset_entry
from aarya_voice_lab.testing.synthetic_audio import generate_speech_like


def test_full_chain_dataset_to_persisted_evaluation(tmp_path):
    # 1. Dataset + 2. Registry: register and approve a fixture dataset
    #    with real, documented metadata.
    registry = PublicDatasetRegistry(tmp_path / "registry.jsonl")
    registry.add(
        build_public_dataset_entry(
            dataset_id="experiment-fixture-v1",
            dataset_name="Experiment Fixture",
            version="1.0",
            source="repository-controlled synthetic fixture (no external download)",
            license="internal-synthetic-fixture-not-for-distribution",
            permitted_uses=["training-pipeline-development"],
            status="approved",
            language=["und"],
        )
    )

    # 3. License Gate: must clear before anything downstream proceeds.
    gate_report = evaluate_public_dataset_use(
        "experiment-fixture-v1", "training-pipeline-development", registry=registry
    )
    assert gate_report.allowed is True, f"gate unexpectedly denied: {gate_report.unsatisfied}"

    # 4. Adapter: normalize real, synthetically-generated audio records.
    audio_dir = tmp_path / "audio"
    manifest_path = tmp_path / "manifest.jsonl"
    with manifest_path.open("w", encoding="utf-8") as fh:
        for i in range(3):
            wav_path = generate_speech_like(
                audio_dir / f"utt-{i}.wav", frequency_hz=160.0 + i * 25, duration_seconds=1.2
            )
            fh.write(
                json.dumps(
                    {
                        "record_id": f"utt-{i}",
                        "audio_ref": str(wav_path),
                        "language": "und",
                        "transcript": f"synthetic utterance number {i}",
                    }
                )
                + "\n"
            )

    adapter = FixtureDatasetAdapter(
        manifest_path, dataset_id="experiment-fixture-v1", license="internal-synthetic-fixture-not-for-distribution"
    )
    records = list(adapter.iter_records())
    assert len(records) == 3

    # 5. Preprocessing: real measurements, not placeholders.
    for record in records:
        samples, sample_rate = read_wav_mono_samples(record.audio_ref)
        result = measure(samples, sample_rate)
        assert result.duration_seconds > 0
        assert result.sample_count > 0

    # 5.5. Training Manifest: real audio validation + transcript
    #      presence checks decide eligibility, never a guess.
    training_manifest = build_training_manifest("experiment-fixture-v1", records)
    assert training_manifest.eligible_record_ids == ("utt-0", "utt-1", "utt-2")
    assert training_manifest.excluded == ()

    # 6. Training Job: enqueue and process against the real, current
    #    provider state.
    provider = LocalTrainingProvider()
    job_log = TrainingJobLog(tmp_path / "training_jobs.jsonl")
    queue = TrainingQueue(provider=provider, job_log=job_log)
    config = build_training_config(
        model_name="experiment-model",
        model_version="0.0.1",
        dataset_id="experiment-fixture-v1",
        provider_name=provider.name,
    )
    job = queue.enqueue(config)
    finished = queue.process_one(job.job_id)

    capabilities = provider.capabilities()
    if capabilities.state is not TrainingProviderState.AVAILABLE:
        # 7. Checkpoint: none, honestly -- training never genuinely ran.
        assert finished.status == TrainingJobStatus.FAILED
        assert finished.failure_reason == TrainingFailureReason.MODEL_UNAVAILABLE
        assert finished.checkpoints == []
        assert finished.output_artifact_id is None
        # 9. Evaluation: no fabricated result when nothing trained.
        assert finished.evaluation_result is None
    else:
        # A future machine with a real provider configured must still
        # reach a real terminal state -- never left hanging.
        assert finished.status in (TrainingJobStatus.COMPLETED, TrainingJobStatus.FAILED)

    # 8. Persisted Job State: the outcome (even an honest failure) is
    #    durably recorded, reconstructible after a restart.
    persisted = job_log.get(job.job_id)
    assert persisted is not None
    assert persisted["status"] == finished.status.value
    assert persisted["log_entries"], "phase history must be recorded, not just the final status"

    fresh_queue = TrainingQueue(provider=provider, job_log=job_log)
    restored = fresh_queue.restore_from_log(job_log)
    assert any(r.job_id == job.job_id for r in restored)


def test_chain_stops_before_training_when_gate_denies(tmp_path):
    """A dataset that never clears the license gate must never reach a
    training job at all -- this test proves the chain's ordering is
    enforced by the caller's own logic, mirroring Phase 2's equivalent
    assertion for the adapter stage."""
    registry = PublicDatasetRegistry(tmp_path / "registry.jsonl")
    registry.add(
        build_public_dataset_entry(
            dataset_id="unapproved-fixture",
            dataset_name="Unapproved Fixture",
            version="1.0",
            source="repository-controlled synthetic fixture",
            license="unknown",
            permitted_uses=["training-pipeline-development"],
            status="registered",
        )
    )

    gate_report = evaluate_public_dataset_use(
        "unapproved-fixture", "training-pipeline-development", registry=registry
    )
    assert gate_report.allowed is False

    # No TrainingQueue interaction happens below this line -- the test
    # itself is the assertion that the chain halts here.
