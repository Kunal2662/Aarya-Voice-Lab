"""VL-D7 -- AI Calibration Engine tests.

Covers: zero/insufficient/sufficient evidence, strategy selection,
hardware snapshot assembly, run-state/evidence-state independence,
bounded parameter enforcement, invalid-adjustment rejection, profile
versioning, append-only history, rollback, provenance, readiness
assessment, provisional reviewer-feedback integration, and security
boundaries (no real recordings, no embeddings, no training, no gate
bypass).
"""

from __future__ import annotations

import inspect

import pytest

from aarya_voice_lab.identity.calibration import CalibrationEvidence, CalibrationState
from aarya_voice_lab.pipeline import calibration_engine
from aarya_voice_lab.pipeline.calibration_engine import (
    MIN_EVIDENCE_FOR_PROVISIONAL,
    CalibrationParameterAdjustment,
    CalibrationProfileLog,
    CalibrationReadiness,
    CalibrationRunState,
    CalibrationStrategy,
    HardwareSnapshot,
    ParameterBoundsError,
    RollbackTargetNotFound,
    assess_readiness,
    current_profile,
    profile_history,
    propose_hardware_adjustments,
    rollback,
    run_calibration,
    select_strategy,
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
    """The module's source with its docstring stripped -- the docstring
    legitimately discusses DataRoot.source, AMD/Intel, and embeddings as
    things this module must NOT touch; checking code, not prose, is what
    actually proves it."""
    full = inspect.getsource(calibration_engine)
    first = full.index('"""')
    second = full.index('"""', first + 3)
    return full[second + 3 :]


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
