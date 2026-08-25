"""Task 3 of the Phase 4 autonomous execution plan -- resumable training
job engine: TrainingQueue.resume_job() and TrainingQueue.restore_from_log(),
plus TrainingJob.log_entries. No fake training is performed anywhere in
this file; LocalTrainingProvider honestly reports MODEL_UNAVAILABLE in
this environment (no torch/nemo_toolkit installed), and every assertion
below is written against that real, current state.
"""

from __future__ import annotations

from aarya_voice_lab.pipeline.training import (
    LocalTrainingProvider,
    TrainingFailureReason,
    TrainingJobLog,
    TrainingJobStatus,
    TrainingProviderState,
    TrainingQueue,
    build_training_config,
)


def _config(**overrides):
    defaults = dict(
        model_name="test-model",
        model_version="0.0.1",
        dataset_id="fixture-dataset",
        provider_name="local-training-provider",
    )
    defaults.update(overrides)
    return build_training_config(**defaults)


def test_job_records_real_phase_log_entries(tmp_path):
    provider = LocalTrainingProvider()
    queue = TrainingQueue(provider=provider, job_log=TrainingJobLog(tmp_path / "jobs.jsonl"))
    job = queue.enqueue(_config())
    finished = queue.process_one(job.job_id)

    assert finished.log_entries, "process_one() must append real log entries, not leave the log empty"
    messages = [entry["message"] for entry in finished.log_entries]
    assert any("phase: VALIDATING" in m for m in messages)
    # In this environment the provider is NOT_CONFIGURED, so the job
    # fails at VALIDATING and never reaches PREPARING/TRAINING.
    if provider.capabilities().state is not TrainingProviderState.AVAILABLE:
        assert any("failed" in m.lower() for m in messages)
        assert all(entry["level"] in ("INFO", "ERROR") for entry in finished.log_entries)


def test_log_entries_are_timestamped_and_ordered(tmp_path):
    provider = LocalTrainingProvider()
    queue = TrainingQueue(provider=provider, job_log=TrainingJobLog(tmp_path / "jobs.jsonl"))
    job = queue.enqueue(_config())
    finished = queue.process_one(job.job_id)

    timestamps = [entry["timestamp"] for entry in finished.log_entries]
    assert timestamps == sorted(timestamps)
    assert all(isinstance(t, str) and t for t in timestamps)


def test_resume_job_rejects_a_non_cancelled_job(tmp_path):
    provider = LocalTrainingProvider()
    queue = TrainingQueue(provider=provider, job_log=TrainingJobLog(tmp_path / "jobs.jsonl"))
    job = queue.enqueue(_config())
    # Still QUEUED -- never cancelled.
    try:
        queue.resume_job(job.job_id)
        raise AssertionError("expected ValueError for a non-CANCELLED job")
    except ValueError as exc:
        assert "not CANCELLED" in str(exc)


def test_resume_job_calls_the_providers_resume_hook_not_the_full_pipeline(tmp_path):
    """resume_job() must call provider.resume(), never re-run
    validate/prepare from scratch -- this is the real behavior being
    tested, not just that *some* terminal state is reached."""

    calls: list[str] = []

    class RecordingProvider(LocalTrainingProvider):
        def validate(self, config):
            calls.append("validate")
            return super().validate(config)

        def prepare(self, job):
            calls.append("prepare")
            super().prepare(job)

        def resume(self, job):
            calls.append("resume")
            super().resume(job)

    provider = RecordingProvider()
    queue = TrainingQueue(provider=provider, job_log=TrainingJobLog(tmp_path / "jobs.jsonl"))
    job = queue.enqueue(_config())
    queue.cancel(job.job_id)
    assert queue.get(job.job_id).status == TrainingJobStatus.CANCELLED

    resumed = queue.resume_job(job.job_id)

    assert calls == ["resume"], f"resume_job() must call only provider.resume(), got {calls}"
    assert resumed.status == TrainingJobStatus.FAILED
    assert resumed.failure_reason == TrainingFailureReason.MODEL_UNAVAILABLE


def test_resume_job_updates_in_memory_state(tmp_path):
    provider = LocalTrainingProvider()
    job_log = TrainingJobLog(tmp_path / "jobs.jsonl")
    queue = TrainingQueue(provider=provider, job_log=job_log)
    job = queue.enqueue(_config())
    queue.cancel(job.job_id)

    resumed = queue.resume_job(job.job_id)

    assert queue.get(job.job_id).status == resumed.status
    assert resumed.status != TrainingJobStatus.CANCELLED
    # The log's original CANCELLED record is permanent, append-only
    # history -- resuming updates in-memory state, never rewrites it.
    persisted = job_log.get(job.job_id)
    assert persisted["status"] == TrainingJobStatus.CANCELLED.value


def test_restore_from_log_reconstructs_terminal_jobs(tmp_path):
    provider = LocalTrainingProvider()
    job_log = TrainingJobLog(tmp_path / "jobs.jsonl")
    original_queue = TrainingQueue(provider=provider, job_log=job_log)
    job = original_queue.enqueue(_config())
    original_queue.process_one(job.job_id)  # honest FAILED/MODEL_UNAVAILABLE

    # A fresh queue, simulating a new process after a restart -- starts
    # with no in-memory knowledge of the job above.
    fresh_queue = TrainingQueue(provider=provider, job_log=job_log)
    assert fresh_queue.get(job.job_id) is None

    restored = fresh_queue.restore_from_log(job_log)

    assert len(restored) == 1
    assert restored[0].job_id == job.job_id
    assert fresh_queue.get(job.job_id) is not None
    assert fresh_queue.get(job.job_id).status == TrainingJobStatus.FAILED
    assert fresh_queue.get(job.job_id).log_entries  # log history survives restore too


def test_restore_from_log_does_not_duplicate_already_known_jobs(tmp_path):
    provider = LocalTrainingProvider()
    job_log = TrainingJobLog(tmp_path / "jobs.jsonl")
    queue = TrainingQueue(provider=provider, job_log=job_log)
    job = queue.enqueue(_config())
    queue.process_one(job.job_id)

    restored_first = queue.restore_from_log(job_log)
    restored_second = queue.restore_from_log(job_log)

    assert len(restored_first) == 0  # already in-memory before any restore call
    assert len(restored_second) == 0
    assert len(queue.list()) == 1


def test_restore_from_log_on_an_empty_log_returns_nothing(tmp_path):
    provider = LocalTrainingProvider()
    job_log = TrainingJobLog(tmp_path / "jobs.jsonl")
    queue = TrainingQueue(provider=provider, job_log=job_log)
    assert queue.restore_from_log(job_log) == []
    assert queue.list() == []


def test_restored_cancelled_job_can_then_be_resumed(tmp_path):
    """The end-to-end resumability story: cancel, persist, restart
    (simulated via a fresh queue), restore, resume."""
    provider = LocalTrainingProvider()
    job_log = TrainingJobLog(tmp_path / "jobs.jsonl")
    original_queue = TrainingQueue(provider=provider, job_log=job_log)
    job = original_queue.enqueue(_config())
    original_queue.cancel(job.job_id)

    fresh_queue = TrainingQueue(provider=provider, job_log=job_log)
    fresh_queue.restore_from_log(job_log)
    assert fresh_queue.get(job.job_id).status == TrainingJobStatus.CANCELLED

    resumed = fresh_queue.resume_job(job.job_id)
    assert resumed.status == TrainingJobStatus.FAILED
    assert resumed.failure_reason == TrainingFailureReason.MODEL_UNAVAILABLE
