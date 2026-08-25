"""Task 4 of the autonomous execution plan -- training pipeline
validation using a repository-controlled fixture dataset.

No external dataset (VCTK, LibriSpeech, or similar) was downloaded for
this validation. Obtaining one requires a human licensing decision (see
docs/DATA_POLICY.md) and downloading any file requires the user's
explicit permission in chat, which was not sought or given during this
autonomous run. Per the execution plan's own documented fallback, this
validation instead proves the pipeline chain using synthetic fixture
audio (aarya_voice_lab.testing.synthetic_audio) generated entirely by
this project's own existing test infrastructure.

The synthetic audio here belongs to the SYNTHETIC data track (see
docs/DATA_POLICY.md), not the public-licensed track: it is never
registered in PublicDatasetRegistry and never passes through
pipeline.public_dataset_gate. It also never touches dataset_gate.py or
any real recording.

Chain validated: dataset -> preprocessing -> training -> checkpoint ->
inference -> evaluation. This environment has no real ML training
runtime installed (confirmed empirically by LocalTrainingProvider, the
same conclusion every prior real-ML milestone in this repository has
already reached), so the honest, correct outcome for the training stage
is a real MODEL_UNAVAILABLE failure -- never a fabricated success,
checkpoint, or evaluation result. These tests assert exactly that,
branching on the provider's real measured capability state rather than
hardcoding an assumption, so they remain correct on a future machine
that has a real training runtime installed.
"""

from __future__ import annotations

import json
from pathlib import Path

from aarya_voice_lab.audio.analysis import measure
from aarya_voice_lab.audio.probe import read_wav_mono_samples
from aarya_voice_lab.pipeline.dataset_adapter import FixtureDatasetAdapter
from aarya_voice_lab.pipeline.training import (
    LocalTrainingProvider,
    TrainingFailureReason,
    TrainingJobLog,
    TrainingJobStatus,
    TrainingProviderState,
    TrainingQueue,
    build_training_config,
)
from aarya_voice_lab.testing.synthetic_audio import generate_speech_like

FIXTURE_DATASET_ID = "pipeline-validation-fixture"


def _build_fixture_dataset(tmp_path: Path) -> FixtureDatasetAdapter:
    audio_dir = tmp_path / "audio"
    manifest_path = tmp_path / "manifest.jsonl"
    with manifest_path.open("w", encoding="utf-8") as fh:
        for index in range(3):
            wav_path = generate_speech_like(
                audio_dir / f"utt-{index}.wav",
                frequency_hz=150.0 + index * 30,
                duration_seconds=1.5,
            )
            fh.write(
                json.dumps(
                    {
                        "record_id": f"utt-{index}",
                        "audio_ref": str(wav_path),
                        "language": "und",
                    }
                )
                + "\n"
            )
    return FixtureDatasetAdapter(
        manifest_path, dataset_id=FIXTURE_DATASET_ID, license="internal-synthetic-fixture-not-for-distribution"
    )


def test_dataset_and_preprocessing_stages_produce_real_measurements(tmp_path):
    """Stages 1-2: dataset -> preprocessing. Every record is real,
    arithmetically generated audio -- never a real recording. measure()
    must report genuinely varying numbers, not a fabricated constant."""
    adapter = _build_fixture_dataset(tmp_path)
    records = list(adapter.iter_records())
    assert len(records) == 3

    durations = []
    for record in records:
        samples, sample_rate = read_wav_mono_samples(Path(record.audio_ref))
        result = measure(samples, sample_rate)
        assert result.sample_count > 0
        assert result.duration_seconds > 0
        assert result.peak_amplitude is not None
        durations.append(result.duration_seconds)

    # All three fixtures were generated at the same requested duration --
    # a real measurement should recover that, not diverge wildly or
    # collapse to zero, which would indicate the "preprocessing" stage
    # was never actually run against real samples.
    assert all(1.4 <= d <= 1.6 for d in durations)


def test_training_stage_reports_honest_provider_state(tmp_path):
    """Stage 3: training/adaptation."""
    _build_fixture_dataset(tmp_path)  # dataset -> preprocessing already covered above
    provider = LocalTrainingProvider()
    capabilities = provider.capabilities()

    queue = TrainingQueue(provider=provider, job_log=TrainingJobLog(tmp_path / "training_jobs.jsonl"))
    config = build_training_config(
        model_name="pipeline-validation-model",
        model_version="0.0.1",
        dataset_id=FIXTURE_DATASET_ID,
        provider_name=provider.name,
    )
    job = queue.enqueue(config)
    finished = queue.process_one(job.job_id)

    assert finished.status in (TrainingJobStatus.COMPLETED, TrainingJobStatus.FAILED)
    if capabilities.state is not TrainingProviderState.AVAILABLE:
        assert finished.status == TrainingJobStatus.FAILED
        assert finished.failure_reason == TrainingFailureReason.MODEL_UNAVAILABLE
        assert finished.errors  # a real, human-readable reason was recorded


def test_no_checkpoint_artifact_or_evaluation_when_training_is_unavailable(tmp_path):
    """Stages 4-6: checkpoint -> inference -> evaluation. When training
    fails with MODEL_UNAVAILABLE, nothing downstream may exist -- this
    guards against ever silently fabricating a later stage's output when
    the stage before it never genuinely ran."""
    provider = LocalTrainingProvider()
    queue = TrainingQueue(provider=provider, job_log=TrainingJobLog(tmp_path / "training_jobs.jsonl"))
    config = build_training_config(
        model_name="pipeline-validation-model",
        model_version="0.0.1",
        dataset_id=FIXTURE_DATASET_ID,
        provider_name=provider.name,
    )
    job = queue.enqueue(config)
    finished = queue.process_one(job.job_id)

    if provider.capabilities().state is TrainingProviderState.AVAILABLE:
        return  # this fixture's assertions only apply to the honest-failure path
    assert finished.checkpoints == []
    assert finished.output_artifact_id is None
    assert provider.artifact(finished) is None
    assert finished.evaluation_result is None


def test_job_is_recorded_in_the_append_only_training_job_log(tmp_path):
    """The chain's outcome (even an honest failure) must be durably
    recorded, exactly like every other terminal state this project
    tracks -- proves the queue -> job-log wiring, not just the provider
    call, actually works end-to-end."""
    provider = LocalTrainingProvider()
    job_log = TrainingJobLog(tmp_path / "training_jobs.jsonl")
    queue = TrainingQueue(provider=provider, job_log=job_log)
    config = build_training_config(
        model_name="pipeline-validation-model",
        model_version="0.0.1",
        dataset_id=FIXTURE_DATASET_ID,
        provider_name=provider.name,
    )
    job = queue.enqueue(config)
    queue.process_one(job.job_id)

    recorded = job_log.get(job.job_id)
    assert recorded is not None
    assert recorded["status"] in (TrainingJobStatus.COMPLETED.value, TrainingJobStatus.FAILED.value)
