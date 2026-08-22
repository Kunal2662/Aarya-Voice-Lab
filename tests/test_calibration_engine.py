"""VL-D7 -- AI Calibration Engine tests, extended in VL-D8 with the
calibration Application & Validation Loop.

VL-D7 section covers: zero/insufficient/sufficient evidence, strategy
selection, hardware snapshot assembly, run-state/evidence-state
independence, bounded parameter enforcement, invalid-adjustment
rejection, profile versioning, append-only history, rollback,
provenance, readiness assessment, provisional reviewer-feedback
integration, and security boundaries (no real recordings, no
embeddings, no training, no gate bypass).

VL-D8 section covers: bounded generation-queue concurrency, applying a
proposed adjustment (with re-checked bounds), applying without a queue,
repeated application, validating an applied profile's real before/after
queue-batching effect, NOT_MEASURABLE honesty, validation-without-
application rejection, and append-only/provenance guarantees across the
new PROPOSED/APPLIED/VALIDATED axis.
"""

from __future__ import annotations

import inspect

import pytest

from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.identity.calibration import CalibrationEvidence, CalibrationState
from aarya_voice_lab.pipeline import calibration_engine
from aarya_voice_lab.pipeline.calibration_engine import (
    MIN_EVIDENCE_FOR_PROVISIONAL,
    AdjustmentNotFound,
    ApplicationState,
    CalibrationEngineError,
    CalibrationParameterAdjustment,
    CalibrationProfileLog,
    CalibrationProfileNotFound,
    CalibrationReadiness,
    CalibrationRunState,
    CalibrationStrategy,
    HardwareSnapshot,
    ParameterBoundsError,
    RollbackTargetNotFound,
    ValidationWithoutApplicationError,
    apply_adjustment,
    assess_readiness,
    current_profile,
    profile_history,
    propose_hardware_adjustments,
    rollback,
    run_calibration,
    select_strategy,
    validate_calibration,
)
from aarya_voice_lab.pipeline.calibration_prep import (
    summarize_evaluation_calibration_inputs,
    summarize_preview_calibration_inputs,
)
from aarya_voice_lab.pipeline.evaluation import (
    EvaluationCompletionState,
    EvaluationLog,
    ListeningState,
    record_evaluation,
)
from aarya_voice_lab.pipeline.generation import (
    GenerationQueue,
    InvalidConcurrencyError,
    SyntheticVoiceGenerator,
    build_preview_request,
)
from aarya_voice_lab.schemas.base import SchemaName, validate

LISTENED = ListeningState(listened=True, completed_playback=True)


@pytest.fixture
def log(tmp_path):
    return CalibrationProfileLog(tmp_path / "calibration.jsonl")


@pytest.fixture
def evaluation_log(tmp_path):
    return EvaluationLog(tmp_path / "evaluation.jsonl")


def _add_evaluations(log_, output_id, scores_by_reviewer):
    for reviewer, score in scores_by_reviewer.items():
        record_evaluation(
            log_,
            output_id=output_id,
            reviewer=reviewer,
            listening=LISTENED,
            dimension_scores={"NATURALNESS": score},
            completion_state=EvaluationCompletionState.COMPLETED,
        )


# -- vocabulary -------------------------------------------------------------


def test_calibration_run_state_mirrors_frontend_hardware_calibration_domain():
    assert {s.value for s in CalibrationRunState} == {
        "UNCALIBRATED", "NOT_TESTED", "CALIBRATING", "CALIBRATED", "FAILED", "UNKNOWN",
    }


def test_calibration_strategy_has_three_values():
    assert {s.value for s in CalibrationStrategy} == {"NONE", "HARDWARE_ONLY", "HARDWARE_AND_FEEDBACK"}


# -- zero / insufficient / sufficient evidence -------------------------------


def test_zero_evidence_produces_uncalibrated_and_hardware_only(log):
    eval_summary = summarize_evaluation_calibration_inputs(evaluation_log=None)
    preview_summary = summarize_preview_calibration_inputs()
    profile = run_calibration(log, evaluation_summary=eval_summary, preview_summary=preview_summary)

    assert profile["run_state"] == CalibrationRunState.CALIBRATED.value
    assert profile["calibration_state"] == CalibrationState.UNCALIBRATED.value
    assert profile["evidence"] == CalibrationEvidence.NONE.value
    assert profile["strategy"] == CalibrationStrategy.HARDWARE_ONLY.value
    assert profile["agreement_rate"] is None
    assert "no human evaluations recorded yet" in " ".join(profile["limitations"])


def test_single_evidence_case_stays_insufficient(log, evaluation_log):
    _add_evaluations(evaluation_log, "out-1", {"alice": 4})
    eval_summary = summarize_evaluation_calibration_inputs(evaluation_log=evaluation_log)
    profile = run_calibration(
        log, evaluation_log=evaluation_log, evaluation_summary=eval_summary,
        preview_summary=summarize_preview_calibration_inputs(),
    )
    assert profile["calibration_state"] == CalibrationState.UNCALIBRATED.value
    assert profile["strategy"] == CalibrationStrategy.HARDWARE_ONLY.value
    assert any(str(MIN_EVIDENCE_FOR_PROVISIONAL) in reason for reason in profile["limitations"])


def test_sufficient_evidence_produces_provisional_never_calibrated(log, evaluation_log):
    _add_evaluations(evaluation_log, "out-1", {"alice": 4, "bob": 4})
    eval_summary = summarize_evaluation_calibration_inputs(evaluation_log=evaluation_log)
    profile = run_calibration(
        log, evaluation_log=evaluation_log, evaluation_summary=eval_summary,
        preview_summary=summarize_preview_calibration_inputs(),
    )
    assert profile["calibration_state"] == CalibrationState.PROVISIONAL.value
    assert profile["evidence"] == CalibrationEvidence.REVIEWER_FEEDBACK.value
    assert profile["strategy"] == CalibrationStrategy.HARDWARE_AND_FEEDBACK.value
    assert profile["agreement_rate"] == 1.0


def test_calibration_state_is_never_calibrated_regardless_of_agreement(log, evaluation_log):
    """CALIBRATED evidence requires held-out labelled data this engine
    never has access to -- perfect reviewer agreement must not produce it."""
    for i in range(10):
        _add_evaluations(evaluation_log, f"out-{i}", {"alice": 5, "bob": 5})
    eval_summary = summarize_evaluation_calibration_inputs(evaluation_log=evaluation_log)
    profile = run_calibration(
        log, evaluation_log=evaluation_log, evaluation_summary=eval_summary,
        preview_summary=summarize_preview_calibration_inputs(),
    )
    assert profile["agreement_rate"] == 1.0
    assert profile["calibration_state"] != CalibrationState.CALIBRATED.value
    assert profile["calibration_state"] == CalibrationState.PROVISIONAL.value


def test_disagreement_lowers_agreement_rate_but_stays_provisional(log, evaluation_log):
    _add_evaluations(evaluation_log, "out-1", {"alice": 5, "bob": 1})
    _add_evaluations(evaluation_log, "out-2", {"alice": 4, "bob": 4})
    eval_summary = summarize_evaluation_calibration_inputs(evaluation_log=evaluation_log)
    profile = run_calibration(
        log, evaluation_log=evaluation_log, evaluation_summary=eval_summary,
        preview_summary=summarize_preview_calibration_inputs(),
    )
    assert profile["agreement_rate"] == 0.5
    assert profile["calibration_state"] == CalibrationState.PROVISIONAL.value


# -- readiness / strategy selection -----------------------------------------


def test_assess_readiness_zero_evidence():
    readiness = assess_readiness()
    assert readiness.total_evaluations == 0
    assert readiness.evidence_sufficient_for_provisional is False
    assert "no human evaluations recorded yet" in readiness.reasons[0]


def test_assess_readiness_sufficient(evaluation_log):
    _add_evaluations(evaluation_log, "out-1", {"alice": 4, "bob": 4})
    summary = summarize_evaluation_calibration_inputs(evaluation_log=evaluation_log)
    readiness = assess_readiness(evaluation_summary=summary)
    assert readiness.evidence_sufficient_for_provisional is True
    assert readiness.reasons == ()


def test_select_strategy_matches_readiness():
    insufficient = CalibrationReadiness(0, 0, 0, False, ("no evidence",), "note")
    sufficient = CalibrationReadiness(2, 1, 0, True, (), "note")
    assert select_strategy(insufficient) is CalibrationStrategy.HARDWARE_ONLY
    assert select_strategy(sufficient) is CalibrationStrategy.HARDWARE_AND_FEEDBACK


# -- hardware snapshot --------------------------------------------------------


def test_hardware_snapshot_assembly_reuses_environment_audit():
    snapshot = HardwareSnapshot.capture()
    assert snapshot.captured_at
    assert isinstance(snapshot.capabilities, tuple)
    assert len(snapshot.capabilities) > 0
    assert snapshot.detected_backend is None or snapshot.detected_backend.value in {"cuda", "other"}
    assert "nvidia-smi" in snapshot.limitation.lower()


def test_hardware_snapshot_never_claims_confirmed_accelerator_without_evidence():
    """No GPU capability AVAILABLE -> accelerator_confirmed is False and
    detected_backend is None, never fabricated as CPU-confirmed."""
    from aarya_voice_lab.core.capability import Capability, CapabilityState
    from aarya_voice_lab.environment.audit import EnvironmentAudit

    audit = EnvironmentAudit(capabilities=[
        Capability("NVIDIA GPU", CapabilityState.OPTIONAL, "no GPU detected"),
        Capability("CUDA runtime", CapabilityState.UNKNOWN, "torch not installed"),
    ])
    snapshot = HardwareSnapshot.capture(audit=audit)
    assert snapshot.accelerator_confirmed is False
    assert snapshot.detected_backend is None


def test_hardware_snapshot_cuda_confirmed_only_when_both_gpu_and_cuda_available():
    from aarya_voice_lab.core.capability import Capability, CapabilityState
    from aarya_voice_lab.environment.audit import EnvironmentAudit

    audit = EnvironmentAudit(capabilities=[
        Capability("NVIDIA GPU", CapabilityState.AVAILABLE, "1 device"),
        Capability("CUDA runtime", CapabilityState.AVAILABLE, version="12.1"),
    ])
    snapshot = HardwareSnapshot.capture(audit=audit)
    assert snapshot.accelerator_confirmed is True
    assert snapshot.detected_backend.value == "cuda"


def test_hardware_snapshot_confirms_non_nvidia_accelerator_as_other_backend():
    """Hardware-agnostic rule: an AMD/other accelerator reported via the
    new vendor-neutral capability must set accelerator_confirmed=True
    even though the NVIDIA-specific capability stays OPTIONAL -- and
    detected_backend must be OTHER, never a fabricated CUDA/ROCM claim
    with no runtime-level evidence behind it."""
    from aarya_voice_lab.core.capability import Capability, CapabilityState
    from aarya_voice_lab.environment.audit import EnvironmentAudit

    audit = EnvironmentAudit(
        capabilities=[
            Capability("NVIDIA GPU", CapabilityState.OPTIONAL, "no NVIDIA GPU detected"),
            Capability("Accelerator (any vendor)", CapabilityState.AVAILABLE, "1 device via rocm-smi", "AMD"),
            Capability("CUDA runtime", CapabilityState.UNKNOWN, "torch not installed"),
        ]
    )
    snapshot = HardwareSnapshot.capture(audit=audit)
    assert snapshot.accelerator_confirmed is True
    assert snapshot.detected_backend.value == "other"


def test_propose_hardware_adjustments_are_bounded():
    snapshot = HardwareSnapshot.capture()
    adjustments = propose_hardware_adjustments(snapshot)
    assert len(adjustments) == 1
    adj = adjustments[0]
    assert adj.min_bound <= adj.proposed_value <= adj.max_bound
    assert adj.evidence_reference.startswith("hardware_snapshot:")


# -- bounded parameter enforcement -------------------------------------------


def test_parameter_adjustment_rejects_out_of_bounds_value():
    with pytest.raises(ParameterBoundsError):
        CalibrationParameterAdjustment("p", 1.0, 99.0, 0.0, 8.0, "rationale", "evidence:1")


def test_parameter_adjustment_rejects_inverted_bounds():
    with pytest.raises(ParameterBoundsError):
        CalibrationParameterAdjustment("p", 1.0, 4.0, 10.0, 0.0, "rationale", "evidence:1")


def test_parameter_adjustment_accepts_in_bounds_value():
    adj = CalibrationParameterAdjustment("p", 1.0, 4.0, 0.0, 8.0, "rationale", "evidence:1")
    assert adj.to_dict()["proposed_value"] == 4.0


def test_parameter_adjustment_requires_rationale_and_evidence_reference_fields():
    fields_ = {f.name for f in calibration_engine.CalibrationParameterAdjustment.__dataclass_fields__.values()}
    assert {"rationale", "evidence_reference", "min_bound", "max_bound", "previous_value", "proposed_value"} <= fields_


# -- run-state / evidence-state independence ---------------------------------


def test_run_state_calibrated_with_uncalibrated_evidence(log):
    profile = run_calibration(
        log,
        evaluation_summary=summarize_evaluation_calibration_inputs(evaluation_log=None),
        preview_summary=summarize_preview_calibration_inputs(),
    )
    assert profile["run_state"] == "CALIBRATED"
    assert profile["calibration_state"] == "UNCALIBRATED"


def test_run_state_calibrated_with_provisional_evidence(log, evaluation_log):
    _add_evaluations(evaluation_log, "out-1", {"alice": 4, "bob": 4})
    profile = run_calibration(
        log, evaluation_log=evaluation_log,
        evaluation_summary=summarize_evaluation_calibration_inputs(evaluation_log=evaluation_log),
        preview_summary=summarize_preview_calibration_inputs(),
    )
    assert profile["run_state"] == "CALIBRATED"
    assert profile["calibration_state"] == "PROVISIONAL"


def test_run_state_failed_on_hardware_capture_error(log, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(HardwareSnapshot, "capture", staticmethod(_boom))
    profile = run_calibration(log)
    assert profile["run_state"] == "FAILED"
    assert profile["calibration_state"] == "UNCALIBRATED"
    assert "probe exploded" in profile["limitations"][0]


# -- versioning / append-only / provenance -----------------------------------


def test_profile_versions_increment(log):
    p1 = run_calibration(log, evaluation_summary=summarize_evaluation_calibration_inputs(evaluation_log=None))
    p2 = run_calibration(log, evaluation_summary=summarize_evaluation_calibration_inputs(evaluation_log=None))
    assert p1["profile_version"] == 1
    assert p2["profile_version"] == 2
    assert p1["profile_id"] != p2["profile_id"]


def test_profile_log_is_append_only(log):
    run_calibration(log)
    run_calibration(log)
    assert len(profile_history(log)) == 2
    assert current_profile(log)["profile_version"] == 2


def test_profile_carries_provenance_fields(log):
    profile = run_calibration(log)
    for field_name in ("engine_version", "processing_version", "schema_version", "created_at", "hardware_snapshot"):
        assert profile[field_name]


# -- rollback -----------------------------------------------------------------


def test_rollback_appends_never_deletes(log):
    p1 = run_calibration(log)
    run_calibration(log)
    before_count = len(profile_history(log))

    rolled = rollback(log, to_profile_id=p1["profile_id"])

    assert len(profile_history(log)) == before_count + 1
    assert rolled["is_rollback"] is True
    assert rolled["run_state"] == p1["run_state"]
    assert rolled["calibration_state"] == p1["calibration_state"]
    # original record untouched
    original_still_present = log.get(p1["profile_id"])
    assert original_still_present == p1


def test_rollback_supersedes_the_current_active_profile(log):
    p1 = run_calibration(log)
    p2 = run_calibration(log)
    rolled = rollback(log, to_profile_id=p1["profile_id"])
    assert rolled["supersedes"] == p2["profile_id"]


def test_rollback_unknown_target_raises():
    import tempfile
    from pathlib import Path

    tmp_log = CalibrationProfileLog(Path(tempfile.mkdtemp()) / "cal.jsonl")
    with pytest.raises(RollbackTargetNotFound):
        rollback(tmp_log, to_profile_id="cal-profile-nope")


# -- schema validation --------------------------------------------------------


def test_profile_validates_against_schema(log):
    profile = run_calibration(log)
    validate(profile, SchemaName.CALIBRATION_PROFILE)


def test_duplicate_profile_id_rejected(log):
    profile = run_calibration(log)
    with pytest.raises(ValueError):
        log.add(profile)


def test_log_reloads_from_disk(tmp_path):
    path = tmp_path / "cal.jsonl"
    log1 = CalibrationProfileLog(path)
    run_calibration(log1)
    run_calibration(log1)

    log2 = CalibrationProfileLog(path)
    assert len(profile_history(log2)) == 2


# -- security / boundary ------------------------------------------------------


def _code_only_source() -> str:
    """The module's source with every docstring (module, class, and
    function) stripped -- docstrings throughout this module legitimately
    discuss DataRoot.source, AMD/Intel, and embeddings as things it must
    NOT touch (including validate_calibration's own note that it takes a
    queue_factory specifically so it never constructs a DataRoot itself);
    checking code, not prose, is what actually proves the boundary."""
    import ast

    full = inspect.getsource(calibration_engine)
    tree = ast.parse(full)
    lines = full.splitlines(keepends=True)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not (node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)):
            continue
        doc_node = node.body[0]
        if not isinstance(doc_node.value.value, str):
            continue
        for lineno in range(doc_node.lineno, doc_node.end_lineno + 1):
            lines[lineno - 1] = "\n"
    return "".join(lines)


def test_module_never_imports_data_root():
    """This module reads already-computed summaries and detected
    capabilities; it must never reach into DataRoot.source (real
    recordings) or any embeddings/enrollment path."""
    source = _code_only_source()
    assert "DataRoot" not in source
    assert "data_root" not in source
    assert ".embeddings" not in source
    assert ".enrollment" not in source
    top_level_imports = "\n".join(inspect.getsource(calibration_engine).splitlines()[:60])
    assert "core.data_root" not in top_level_imports
    assert "identity.embeddings" not in top_level_imports
    assert "identity.enrollment" not in top_level_imports


def test_module_never_hardcodes_a_specific_gpu_product():
    """The hardware-lock-in this engine must never have: no specific GPU
    product or model number anywhere. NVIDIA/AMD/Intel appear in this
    module only as honest documentation of environment.audit's current
    (NVIDIA-only) probe coverage and identity.runtime's vendor-neutral
    ComputeBackend vocabulary -- decision logic itself only ever branches
    on CapabilityState/ComputeBackend, never a vendor string (see
    test_hardware_snapshot_cuda_confirmed_only_when_both_gpu_and_cuda_available
    and test_hardware_snapshot_never_claims_confirmed_accelerator_without_evidence,
    which prove that behaviourally)."""
    full_source = inspect.getsource(calibration_engine)
    for banned in ("RTX", "3050", "GTX", "GeForce", "Radeon"):
        assert banned not in full_source


def test_no_embedding_or_training_vocabulary_present():
    source = _code_only_source()
    for banned in ("train_model", "fit(", "torch.save", "embedding_vector", "speaker_id"):
        assert banned not in source


def test_calibration_profile_has_no_speaker_identity_fields():
    profile = run_calibration(CalibrationProfileLog(__import__("pathlib").Path(
        __import__("tempfile").mkdtemp()) / "cal.jsonl"))
    forbidden = {"speaker_id", "target_speaker", "voice_id", "embedding", "speaker_name"}
    assert forbidden.isdisjoint(profile.keys())


# =============================================================================
# VL-D8 -- Calibration Application & Validation Loop
# =============================================================================


@pytest.fixture
def data_root(tmp_path):
    root = DataRoot(root=tmp_path / "data")
    root.create()
    return root


def _fixture_queue_factory(data_root, item_count):
    def factory():
        queue = GenerationQueue(generator=SyntheticVoiceGenerator(data_root))
        for i in range(item_count):
            queue.enqueue(
                build_preview_request(
                    text=f"Validation fixture {i}.", voice_profile_id="vp-1", model_id="synthetic-tone-v1"
                )
            )
        return queue

    return factory


# -- GenerationQueue bounded concurrency -------------------------------------


def test_generation_queue_default_concurrency_is_unbounded_single_batch(data_root):
    queue = GenerationQueue(generator=SyntheticVoiceGenerator(data_root))
    for i in range(4):
        queue.enqueue(build_preview_request(text=f"t{i}", voice_profile_id="vp-1", model_id="synthetic-tone-v1"))
    assert queue.max_concurrent_generations is None
    results = queue.process_all()
    assert len(results) == 4
    assert queue.last_run_stats() == {"item_count": 4, "batch_count": 1, "max_concurrent_generations": None}


def test_generation_queue_accepts_valid_bounded_concurrency(data_root):
    queue = GenerationQueue(generator=SyntheticVoiceGenerator(data_root), max_concurrent_generations=2)
    assert queue.max_concurrent_generations == 2
    for i in range(5):
        queue.enqueue(build_preview_request(text=f"t{i}", voice_profile_id="vp-1", model_id="synthetic-tone-v1"))
    queue.process_all()
    # 5 items in batches of 2 -> 3 batches (2, 2, 1)
    assert queue.last_run_stats()["batch_count"] == 3


@pytest.mark.parametrize("invalid", [0, -1, -5, 2.5, "3", True, False])
def test_generation_queue_rejects_invalid_concurrency(data_root, invalid):
    queue = GenerationQueue(generator=SyntheticVoiceGenerator(data_root))
    with pytest.raises(InvalidConcurrencyError):
        queue.set_max_concurrent_generations(invalid)


def test_generation_queue_rejects_invalid_concurrency_at_construction(data_root):
    with pytest.raises(InvalidConcurrencyError):
        GenerationQueue(generator=SyntheticVoiceGenerator(data_root), max_concurrent_generations=0)


def test_generation_queue_process_all_produces_identical_items_regardless_of_batching(data_root):
    """The set and order of processed items must never depend on
    batch size -- only last_run_stats()'s bookkeeping does."""
    unbatched = GenerationQueue(generator=SyntheticVoiceGenerator(data_root))
    batched = GenerationQueue(generator=SyntheticVoiceGenerator(data_root), max_concurrent_generations=2)
    for i in range(5):
        text = f"deterministic {i}"
        kwargs = {"text": text, "voice_profile_id": "vp-1", "model_id": "synthetic-tone-v1", "seed": 42}
        unbatched.enqueue(build_preview_request(**kwargs))
        batched.enqueue(build_preview_request(**kwargs))

    unbatched_results = unbatched.process_all()
    batched_results = batched.process_all()

    assert [r.status for r in unbatched_results] == [r.status for r in batched_results]
    assert [r.artifact["sha256"] for r in unbatched_results] == [r.artifact["sha256"] for r in batched_results]


def test_generation_queue_last_run_stats_is_none_before_any_run(data_root):
    queue = GenerationQueue(generator=SyntheticVoiceGenerator(data_root))
    assert queue.last_run_stats() is None


def test_generation_queue_zero_queued_items_produces_zero_batch_count(data_root):
    queue = GenerationQueue(generator=SyntheticVoiceGenerator(data_root), max_concurrent_generations=2)
    queue.process_all()
    assert queue.last_run_stats() == {"item_count": 0, "batch_count": 0, "max_concurrent_generations": 2}


# -- application ---------------------------------------------------------------


def test_apply_adjustment_creates_new_applied_profile_never_edits_source(tmp_path, data_root):
    log = CalibrationProfileLog(tmp_path / "cal.jsonl")
    proposed = run_calibration(log)

    applied = apply_adjustment(log, profile_id=proposed["profile_id"], parameter_name="max_concurrent_generations")

    assert applied["application_state"] == ApplicationState.APPLIED.value
    assert applied["applied_from_profile_id"] == proposed["profile_id"]
    assert applied["applied_parameter_name"] == "max_concurrent_generations"
    assert applied["applied_value"] is not None
    assert applied["profile_id"] != proposed["profile_id"]
    # source untouched
    assert log.get(proposed["profile_id"]) == proposed
    assert proposed["application_state"] == ApplicationState.PROPOSED.value


def test_apply_adjustment_actually_sets_the_queue_value(tmp_path, data_root):
    log = CalibrationProfileLog(tmp_path / "cal.jsonl")
    proposed = run_calibration(log)
    queue = GenerationQueue(generator=SyntheticVoiceGenerator(data_root))

    applied = apply_adjustment(
        log, profile_id=proposed["profile_id"], parameter_name="max_concurrent_generations", queue=queue
    )

    assert queue.max_concurrent_generations == int(applied["applied_value"])


def test_apply_adjustment_without_a_queue_still_records_applied_state(tmp_path):
    log = CalibrationProfileLog(tmp_path / "cal.jsonl")
    proposed = run_calibration(log)

    applied = apply_adjustment(log, profile_id=proposed["profile_id"], parameter_name="max_concurrent_generations")
    assert applied["application_state"] == ApplicationState.APPLIED.value


def test_apply_adjustment_rechecks_bounds_at_application_time(tmp_path):
    """Never trust an earlier proposal blindly: apply_adjustment
    reconstructs CalibrationParameterAdjustment from the stored record,
    which re-runs its own bounds check."""
    log = CalibrationProfileLog(tmp_path / "cal.jsonl")
    proposed = run_calibration(log)
    # Corrupt the stored proposal directly to simulate a proposal that
    # is no longer self-consistent -- apply_adjustment must catch this,
    # not blindly trust it.
    corrupted = dict(proposed)
    corrupted["adjustments"] = [
        {**proposed["adjustments"][0], "proposed_value": 999.0},
    ]
    corrupted["profile_id"] = "cal-corrupted-00001"
    log.add(corrupted)

    with pytest.raises(ParameterBoundsError):
        apply_adjustment(log, profile_id=corrupted["profile_id"], parameter_name="max_concurrent_generations")


def test_apply_adjustment_unknown_parameter_raises_adjustment_not_found(tmp_path):
    log = CalibrationProfileLog(tmp_path / "cal.jsonl")
    proposed = run_calibration(log)
    with pytest.raises(AdjustmentNotFound):
        apply_adjustment(log, profile_id=proposed["profile_id"], parameter_name="does_not_exist")


def test_apply_adjustment_unknown_profile_raises_profile_not_found(tmp_path):
    log = CalibrationProfileLog(tmp_path / "cal.jsonl")
    with pytest.raises(CalibrationProfileNotFound):
        apply_adjustment(log, profile_id="cal-profile-nope", parameter_name="max_concurrent_generations")


def test_apply_adjustment_unsupported_target_with_queue_raises(tmp_path, data_root):
    """A parameter this engine has no application path for must refuse
    to silently no-op when a queue is supplied."""
    log = CalibrationProfileLog(tmp_path / "cal.jsonl")
    proposed = run_calibration(log)
    corrupted = dict(proposed)
    corrupted["adjustments"] = [
        {**proposed["adjustments"][0], "parameter_name": "some_future_parameter"},
    ]
    corrupted["profile_id"] = "cal-corrupted-00002"
    log.add(corrupted)
    queue = GenerationQueue(generator=SyntheticVoiceGenerator(data_root))

    with pytest.raises(CalibrationEngineError):
        apply_adjustment(log, profile_id=corrupted["profile_id"], parameter_name="some_future_parameter", queue=queue)


def test_apply_adjustment_can_be_repeated_appending_each_time(tmp_path):
    log = CalibrationProfileLog(tmp_path / "cal.jsonl")
    proposed = run_calibration(log)

    first = apply_adjustment(log, profile_id=proposed["profile_id"], parameter_name="max_concurrent_generations")
    second = apply_adjustment(log, profile_id=proposed["profile_id"], parameter_name="max_concurrent_generations")

    assert first["profile_id"] != second["profile_id"]
    assert first["applied_from_profile_id"] == second["applied_from_profile_id"] == proposed["profile_id"]
    assert second["supersedes"] == first["profile_id"]
    assert len(profile_history(log)) == 3


def test_apply_adjustment_validates_against_schema(tmp_path):
    log = CalibrationProfileLog(tmp_path / "cal.jsonl")
    proposed = run_calibration(log)
    applied = apply_adjustment(log, profile_id=proposed["profile_id"], parameter_name="max_concurrent_generations")
    validate(applied, SchemaName.CALIBRATION_PROFILE)


# -- validation ------------------------------------------------------------


def test_validate_calibration_without_application_raises(tmp_path):
    log = CalibrationProfileLog(tmp_path / "cal.jsonl")
    proposed = run_calibration(log)
    with pytest.raises(ValidationWithoutApplicationError):
        validate_calibration(log, profile_id=proposed["profile_id"], queue_factory=lambda: None)


def test_validate_calibration_unknown_profile_raises(tmp_path):
    log = CalibrationProfileLog(tmp_path / "cal.jsonl")
    with pytest.raises(CalibrationProfileNotFound):
        validate_calibration(log, profile_id="cal-profile-nope", queue_factory=lambda: None)


def test_validate_calibration_measures_a_real_before_after_batch_count(tmp_path, data_root):
    log = CalibrationProfileLog(tmp_path / "cal.jsonl")
    proposed = run_calibration(log)
    applied = apply_adjustment(log, profile_id=proposed["profile_id"], parameter_name="max_concurrent_generations")
    factory = _fixture_queue_factory(data_root, item_count=6)

    validated = validate_calibration(log, profile_id=applied["profile_id"], queue_factory=factory)

    assert validated["application_state"] == ApplicationState.VALIDATED.value
    v = validated["validation"]
    assert v["validated"] is True
    assert v["not_measurable"] is False
    import math

    applied_concurrency = int(applied["applied_value"])
    assert v["before_batch_count"] == 6  # baseline concurrency=1 -> one item per batch
    assert v["after_batch_count"] == math.ceil(6 / applied_concurrency)
    assert v["after_batch_count"] < v["before_batch_count"]
    assert v["measured_delta"] == v["before_batch_count"] - v["after_batch_count"]
    assert v["measured_delta"] > 0
    assert "voice-quality" in v["note"] or "voice quality" in v["note"]


def test_validate_calibration_reports_not_measurable_honestly_for_a_too_small_fixture(tmp_path, data_root):
    log = CalibrationProfileLog(tmp_path / "cal.jsonl")
    proposed = run_calibration(log)
    applied = apply_adjustment(log, profile_id=proposed["profile_id"], parameter_name="max_concurrent_generations")
    factory = _fixture_queue_factory(data_root, item_count=1)

    validated = validate_calibration(log, profile_id=applied["profile_id"], queue_factory=factory)

    v = validated["validation"]
    assert v["validated"] is False
    assert v["not_measurable"] is True
    assert v["measured_delta"] is None


def test_validate_calibration_never_overwrites_prior_validation(tmp_path, data_root):
    log = CalibrationProfileLog(tmp_path / "cal.jsonl")
    proposed = run_calibration(log)
    applied = apply_adjustment(log, profile_id=proposed["profile_id"], parameter_name="max_concurrent_generations")
    factory = _fixture_queue_factory(data_root, item_count=6)

    first_validation = validate_calibration(log, profile_id=applied["profile_id"], queue_factory=factory)
    second_validation = validate_calibration(log, profile_id=applied["profile_id"], queue_factory=factory)

    assert first_validation["profile_id"] != second_validation["profile_id"]
    assert log.get(first_validation["profile_id"]) == first_validation  # untouched
    assert len(profile_history(log)) == 4  # proposed, applied, validated x2


def test_validate_calibration_preserves_provenance_chain(tmp_path, data_root):
    log = CalibrationProfileLog(tmp_path / "cal.jsonl")
    proposed = run_calibration(log)
    applied = apply_adjustment(log, profile_id=proposed["profile_id"], parameter_name="max_concurrent_generations")
    factory = _fixture_queue_factory(data_root, item_count=6)
    validated = validate_calibration(log, profile_id=applied["profile_id"], queue_factory=factory)

    assert validated["applied_from_profile_id"] == proposed["profile_id"]
    assert validated["applied_parameter_name"] == "max_concurrent_generations"
    assert validated["supersedes"] == applied["profile_id"]


def test_validate_calibration_validates_against_schema(tmp_path, data_root):
    log = CalibrationProfileLog(tmp_path / "cal.jsonl")
    proposed = run_calibration(log)
    applied = apply_adjustment(log, profile_id=proposed["profile_id"], parameter_name="max_concurrent_generations")
    factory = _fixture_queue_factory(data_root, item_count=6)
    validated = validate_calibration(log, profile_id=applied["profile_id"], queue_factory=factory)
    validate(validated, SchemaName.CALIBRATION_PROFILE)


def test_validate_calibration_after_rollback_of_application_state_raises(tmp_path):
    """Rolling back to a PROPOSED profile makes it the active record
    again; validating that (unapplied) record must still be refused."""
    log = CalibrationProfileLog(tmp_path / "cal.jsonl")
    proposed = run_calibration(log)
    apply_adjustment(log, profile_id=proposed["profile_id"], parameter_name="max_concurrent_generations")
    rolled_back = rollback(log, to_profile_id=proposed["profile_id"])

    assert rolled_back["application_state"] == ApplicationState.PROPOSED.value
    with pytest.raises(ValidationWithoutApplicationError):
        validate_calibration(log, profile_id=rolled_back["profile_id"], queue_factory=lambda: None)


# -- full lifecycle / regression ------------------------------------------


def test_full_propose_apply_validate_lifecycle_is_append_only(tmp_path, data_root):
    log = CalibrationProfileLog(tmp_path / "cal.jsonl")
    proposed = run_calibration(log)
    applied = apply_adjustment(log, profile_id=proposed["profile_id"], parameter_name="max_concurrent_generations")
    factory = _fixture_queue_factory(data_root, item_count=6)
    validated = validate_calibration(log, profile_id=applied["profile_id"], queue_factory=factory)

    history = profile_history(log)
    assert [r["application_state"] for r in history] == ["PROPOSED", "APPLIED", "VALIDATED"]
    assert [r["profile_version"] for r in history] == [1, 2, 3]
    # run_state/calibration_state independence preserved throughout
    assert all(r["run_state"] == "CALIBRATED" for r in history)
    assert all(r["calibration_state"] == "UNCALIBRATED" for r in history)
    # nothing mutated
    assert history[0] == proposed
    assert history[1] == applied
    assert history[2] == validated


def test_vl_d7_default_profiles_default_to_proposed_application_state(tmp_path):
    """Existing VL-D7 callers that never touch application logic still
    get a well-formed, schema-valid record."""
    log = CalibrationProfileLog(tmp_path / "cal.jsonl")
    profile = run_calibration(log)
    assert profile["application_state"] == "PROPOSED"
    assert profile["applied_from_profile_id"] is None
    assert profile["applied_value"] is None
    assert profile["validation"] is None
    validate(profile, SchemaName.CALIBRATION_PROFILE)
