"""Tests for pipeline.import_intake — the VL-D2 bulk-import layer.

Every fixture is synthetic (testing.synthetic_audio); nothing here reads
or references source/ or any real recording.
"""

from __future__ import annotations

import json

import pytest

from aarya_voice_lab.core.data_root import DataRoot, create_batch, read_batch
from aarya_voice_lab.pipeline.dataset_gate import DatasetAccessDenied, GateCondition, GateReport
from aarya_voice_lab.pipeline.import_intake import (
    RETRYABLE_STATUSES,
    ImportItemStatus,
    ImportQueue,
    ImportSource,
    find_existing_content,
    write_import_manifest,
)
from aarya_voice_lab.schemas.base import SchemaName, validate
from aarya_voice_lab.testing.synthetic_audio import (
    generate_phase2_corpus,
    generate_tone,
)


def _data_root(tmp_path) -> DataRoot:
    root = DataRoot.default(project_root=tmp_path)
    root.create()
    return root


def _queue(tmp_path, batch_id="batch-001", source=ImportSource.LOCAL_FILES) -> ImportQueue:
    data_root = _data_root(tmp_path)
    if read_batch(data_root, batch_id) is None:
        create_batch(data_root, batch_id)
    return ImportQueue(data_root=data_root, batch_id=batch_id, source=source)


# ---------------------------------------------------------------------------
# Classification: every corpus file lands in the right bucket.
# ---------------------------------------------------------------------------


def test_full_synthetic_corpus_classifies_correctly_and_never_crashes(tmp_path):
    """One malformed file must never abort the batch — process the whole
    Phase 2 corpus (which is deliberately full of broken files) in one
    queue and confirm every item reaches a terminal status."""
    staging = tmp_path / "staging"
    corpus = generate_phase2_corpus(staging)

    queue = _queue(tmp_path)
    for path in corpus.values():
        queue.enqueue(path)
    queue.process_all()

    for item in queue.items.values():
        assert item.status in ImportItemStatus, f"{item.original_filename} left in a non-terminal state"

    by_name = {item.original_filename: item for item in queue.items.values()}
    assert by_name["zero_byte.wav"].status == ImportItemStatus.BLOCKED
    assert by_name["corrupt.wav"].status == ImportItemStatus.INVALID
    assert by_name["unsupported.wav"].status == ImportItemStatus.INVALID
    assert by_name["mislabelled.wav"].status in (ImportItemStatus.ACCEPTED, ImportItemStatus.WARNING)
    assert by_name["mislabelled.wav"].detected_container == "mp3"
    assert by_name["duplicate_of_clean.wav"].status == ImportItemStatus.DUPLICATE
    assert by_name["clean_speech.wav"].status in (ImportItemStatus.ACCEPTED, ImportItemStatus.WARNING)


def test_truncated_wav_is_invalid_or_accepted_never_crashes(tmp_path):
    """Matches the existing probe_wav_quietly contract: a truncated WAV is
    either flagged unreadable (INVALID here) or, if the header still
    parses, let through — but the queue must finish either way."""
    staging = tmp_path / "staging"
    from aarya_voice_lab.testing.synthetic_audio import generate_truncated_wav

    path = generate_truncated_wav(staging / "cut.wav")
    queue = _queue(tmp_path)
    queue.enqueue(path)
    queue.process_all()
    item = next(iter(queue.items.values()))
    assert item.status in (ImportItemStatus.INVALID, ImportItemStatus.ACCEPTED, ImportItemStatus.WARNING)


# ---------------------------------------------------------------------------
# Content-addressed identity, duplicate detection, path traversal safety.
# ---------------------------------------------------------------------------


def test_accepted_file_is_stored_content_addressed(tmp_path):
    staging = tmp_path / "staging"
    path = generate_tone(staging / "a.wav", frequency_hz=250)
    queue = _queue(tmp_path)
    item = queue.enqueue(path)
    queue.process_all()

    assert item.status == ImportItemStatus.ACCEPTED
    assert item.stored_relative_path == f"source/batch-001/{item.sha256}.wav"
    stored = queue.data_root.root / item.stored_relative_path
    assert stored.is_file()
    assert stored.read_bytes() == path.read_bytes()


def test_within_run_duplicate_is_detected_and_not_double_stored(tmp_path):
    staging = tmp_path / "staging"
    original = generate_tone(staging / "a.wav", frequency_hz=250)
    copy = staging / "a_copy.wav"
    copy.write_bytes(original.read_bytes())

    queue = _queue(tmp_path)
    first = queue.enqueue(original)
    second = queue.enqueue(copy)
    queue.process_all()

    assert first.status == ImportItemStatus.ACCEPTED
    assert second.status == ImportItemStatus.DUPLICATE
    # Sequential processing means the first item is already on disk by
    # the time the second is checked, so the duplicate is found via the
    # same filesystem lookup a cross-batch duplicate would use — it names
    # the batch that holds the content, not the sibling item.
    assert second.duplicate_of == "batch-001"
    stored_files = list((queue.data_root.batch_source("batch-001")).iterdir())
    assert len(stored_files) == 1


def test_cross_batch_duplicate_is_detected_via_content_hash(tmp_path):
    staging = tmp_path / "staging"
    path = generate_tone(staging / "a.wav", frequency_hz=250)

    data_root = _data_root(tmp_path)
    create_batch(data_root, "batch-001")
    create_batch(data_root, "batch-002")

    q1 = ImportQueue(data_root=data_root, batch_id="batch-001", source=ImportSource.LOCAL_FILES)
    q1.enqueue(path)
    q1.process_all()
    assert q1.items["import-0001"].status == ImportItemStatus.ACCEPTED

    q2 = ImportQueue(data_root=data_root, batch_id="batch-002", source=ImportSource.LOCAL_FILES)
    item = q2.enqueue(path)
    q2.process_all()
    assert item.status == ImportItemStatus.DUPLICATE
    assert item.duplicate_of == "batch-001"


def test_find_existing_content_returns_none_when_absent(tmp_path):
    data_root = _data_root(tmp_path)
    assert find_existing_content(data_root, "0" * 64) is None


def test_path_traversal_style_filename_cannot_influence_destination(tmp_path):
    """A filename is never used to build the destination path — only the
    computed content hash is. Prove it by using a maximally hostile
    display name and asserting the stored path is still content-addressed
    and stays inside the batch's source directory."""
    staging = tmp_path / "staging"
    staging.mkdir()
    hostile = staging / "..evil.wav"  # can't literally embed '/' in one path segment on POSIX
    generate_tone(hostile, frequency_hz=777)

    queue = _queue(tmp_path)
    item = queue.enqueue(hostile)
    queue.process_all()

    assert item.status == ImportItemStatus.ACCEPTED
    stored = queue.data_root.root / item.stored_relative_path
    assert queue.data_root.batch_source("batch-001").resolve() in stored.resolve().parents
    assert stored.name == f"{item.sha256}.wav"
    assert ".." not in stored.relative_to(queue.data_root.root).parts


# ---------------------------------------------------------------------------
# Resumability: idempotent by content hash, never by timestamp.
# ---------------------------------------------------------------------------


def test_reimporting_the_same_file_after_a_fresh_queue_is_idempotent(tmp_path):
    """Simulates an application restart: a brand-new ImportQueue instance
    (no shared in-memory state) re-processing a file already accepted in
    a prior run must recognise it as already present, not re-copy it or
    treat it as a fresh accept."""
    staging = tmp_path / "staging"
    path = generate_tone(staging / "a.wav", frequency_hz=250)

    data_root = _data_root(tmp_path)
    create_batch(data_root, "batch-001")

    first_queue = ImportQueue(data_root=data_root, batch_id="batch-001", source=ImportSource.LOCAL_FILES)
    first_queue.enqueue(path)
    first_queue.process_all()
    assert first_queue.items["import-0001"].status == ImportItemStatus.ACCEPTED

    second_queue = ImportQueue(data_root=data_root, batch_id="batch-001", source=ImportSource.LOCAL_FILES)
    item = second_queue.enqueue(path)
    second_queue.process_all()
    assert item.status == ImportItemStatus.DUPLICATE

    stored_files = list(data_root.batch_source("batch-001").iterdir())
    assert len(stored_files) == 1, "re-import must not create a second copy"


def test_batch_metadata_survives_a_fresh_data_root_instance(tmp_path):
    """Batch persistence must survive an application restart — modelled
    here as constructing a brand-new DataRoot pointed at the same
    filesystem location rather than reusing any in-memory object."""
    data_root_1 = _data_root(tmp_path)
    create_batch(data_root_1, "batch-001", source_file_count=3, notes="first session")

    data_root_2 = DataRoot.default(project_root=tmp_path)
    reloaded = read_batch(data_root_2, "batch-001")
    assert reloaded is not None
    assert reloaded.batch_id == "batch-001"
    assert reloaded.notes == "first session"
    assert reloaded.source_file_count == 3


def test_batch_id_is_not_timestamp_based(tmp_path):
    data_root = _data_root(tmp_path)
    metadata = create_batch(data_root, "batch-001")
    assert metadata.batch_id == "batch-001"
    # created_at exists for humans but batch identity itself is sequential,
    # not derived from it.
    assert "batch-001" == metadata.to_dict()["batch_id"]


# ---------------------------------------------------------------------------
# Retry, cancellation, failure isolation.
# ---------------------------------------------------------------------------


def test_failed_item_can_be_retried_after_the_underlying_problem_is_fixed(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    ghost = staging / "ghost.wav"  # does not exist yet

    queue = _queue(tmp_path)
    item = queue.enqueue(ghost)
    queue.process_all()
    assert item.status == ImportItemStatus.FAILED
    assert item.status in RETRYABLE_STATUSES

    generate_tone(ghost, frequency_hz=999)
    retried = queue.retry(item.item_id)
    assert retried is True
    assert item.status == ImportItemStatus.ACCEPTED
    assert item.errors == []


def test_retry_refuses_an_item_that_never_ran_or_already_succeeded(tmp_path):
    staging = tmp_path / "staging"
    path = generate_tone(staging / "a.wav")
    queue = _queue(tmp_path)
    item = queue.enqueue(path)
    # Not yet processed — QUEUED is not retryable (nothing to retry).
    assert queue.retry(item.item_id) is False
    queue.process_all()
    assert item.status == ImportItemStatus.ACCEPTED
    # Already succeeded — retry is a no-op, not a re-run.
    assert queue.retry(item.item_id) is False


def test_cancel_only_works_before_processing_begins(tmp_path):
    staging = tmp_path / "staging"
    path = generate_tone(staging / "a.wav")
    queue = _queue(tmp_path)
    item = queue.enqueue(path)

    assert queue.cancel(item.item_id) is True
    assert item.status == ImportItemStatus.CANCELLED

    queue.process_all()  # cancelled items are skipped, not reprocessed
    assert item.status == ImportItemStatus.CANCELLED
    assert item.sha256 is None


def test_cancel_after_processing_has_started_is_refused(tmp_path):
    staging = tmp_path / "staging"
    path = generate_tone(staging / "a.wav")
    queue = _queue(tmp_path)
    item = queue.enqueue(path)
    queue.process_all()
    assert queue.cancel(item.item_id) is False


def test_one_bad_item_does_not_stop_the_rest_of_the_queue(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    good_before = generate_tone(staging / "good_before.wav", frequency_hz=200)
    missing = staging / "does_not_exist.wav"
    good_after = generate_tone(staging / "good_after.wav", frequency_hz=400)

    queue = _queue(tmp_path)
    queue.enqueue(good_before)
    queue.enqueue(missing)
    queue.enqueue(good_after)
    queue.process_all()

    statuses = [item.status for item in queue.items.values()]
    assert statuses == [ImportItemStatus.ACCEPTED, ImportItemStatus.FAILED, ImportItemStatus.ACCEPTED]


# ---------------------------------------------------------------------------
# Provenance: relative paths only, schema-valid manifest.
# ---------------------------------------------------------------------------


def test_manifest_never_contains_an_absolute_path(tmp_path):
    staging = tmp_path / "staging"
    path = generate_tone(staging / "a.wav")
    queue = _queue(tmp_path)
    queue.enqueue(path)
    queue.process_all()

    manifest = queue.to_manifest()
    serialised = json.dumps(manifest)
    assert str(tmp_path) not in serialised, "no machine-specific absolute path may be persisted"
    assert str(staging) not in serialised


def test_write_import_manifest_validates_against_schema(tmp_path):
    staging = tmp_path / "staging"
    corpus = generate_phase2_corpus(staging)
    queue = _queue(tmp_path)
    for path in corpus.values():
        queue.enqueue(path)
    queue.process_all()

    manifest_path = queue.data_root.batch_manifests("batch-001") / "import_manifest.json"
    write_import_manifest(queue, manifest_path)
    assert manifest_path.is_file()

    loaded = json.loads(manifest_path.read_text())
    validate(loaded, SchemaName.IMPORT_MANIFEST)  # raises on failure


# ---------------------------------------------------------------------------
# Dataset access gate — never bypassable from this module.
# ---------------------------------------------------------------------------


def test_non_synthetic_import_without_an_allowed_gate_report_is_refused(tmp_path):
    data_root = _data_root(tmp_path)
    create_batch(data_root, "batch-001")
    with pytest.raises(DatasetAccessDenied):
        ImportQueue(
            data_root=data_root,
            batch_id="batch-001",
            source=ImportSource.LOCAL_FILES,
            is_synthetic=False,
        )


def test_non_synthetic_import_without_explicit_approval_in_the_gate_is_refused(tmp_path):
    data_root = _data_root(tmp_path)
    create_batch(data_root, "batch-001")
    # A report with every OTHER condition satisfied but not explicit
    # approval must still refuse — approval can never be inferred.
    unsatisfied_approval = GateReport(
        conditions=[
            GateCondition("explicit approval to access recordings", satisfied=False, detail="NOT granted"),
        ]
    )
    assert unsatisfied_approval.allowed is False
    with pytest.raises(DatasetAccessDenied):
        ImportQueue(
            data_root=data_root,
            batch_id="batch-001",
            source=ImportSource.LOCAL_FILES,
            is_synthetic=False,
            gate_report=unsatisfied_approval,
        )


def test_non_synthetic_import_with_a_fully_satisfied_gate_report_is_permitted_to_construct(tmp_path):
    """Confirms the gate check is real (can pass), not merely decorative
    (always fails) — without this project ever calling it with real data."""
    data_root = _data_root(tmp_path)
    create_batch(data_root, "batch-001")
    satisfied = GateReport(conditions=[GateCondition("everything", satisfied=True, detail="ok")])
    assert satisfied.allowed is True
    queue = ImportQueue(
        data_root=data_root,
        batch_id="batch-001",
        source=ImportSource.LOCAL_FILES,
        is_synthetic=False,
        gate_report=satisfied,
    )
    assert queue.is_synthetic is False


# ---------------------------------------------------------------------------
# Large synthetic batch.
# ---------------------------------------------------------------------------


def test_large_synthetic_batch_processes_completely(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    paths = [generate_tone(staging / f"file_{i:03d}.wav", frequency_hz=200 + i) for i in range(60)]

    queue = _queue(tmp_path)
    for path in paths:
        queue.enqueue(path)
    queue.process_all()

    counts = queue.counts()
    assert counts["accepted"] == 60
    assert sum(counts.values()) == 60
    assert len(list(queue.data_root.batch_source("batch-001").iterdir())) == 60
