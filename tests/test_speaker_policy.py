"""Tests for the conservative speaker-safety policy.

The critical property under test: the operator's voice can never be
classified ELIGIBLE, and no uncertain case is auto-accepted.
"""

from __future__ import annotations

import itertools

import pytest

from aarya_voice_lab.security.speaker_policy import (
    ConfidenceLevel,
    EligibilityDecision,
    OverlapStatus,
    SpeakerRole,
    SpeakerVerificationInput,
    classify_confidence,
    decide_eligibility,
)


def make_input(**overrides) -> SpeakerVerificationInput:
    defaults = dict(
        primary_role=SpeakerRole.TARGET_FEMALE_SPEAKER,
        primary_confidence=0.99,
        secondary_role=SpeakerRole.TARGET_FEMALE_SPEAKER,
        secondary_confidence=0.99,
        overlap_status=OverlapStatus.NONE,
        audio_quality_acceptable=True,
    )
    defaults.update(overrides)
    return SpeakerVerificationInput(**defaults)


def test_two_system_agreement_high_confidence_is_eligible():
    decision, _ = decide_eligibility(make_input())
    assert decision is EligibilityDecision.ELIGIBLE


def test_operator_voice_is_always_rejected():
    decision, _ = decide_eligibility(make_input(primary_role=SpeakerRole.OPERATOR_VOICE))
    assert decision is EligibilityDecision.REJECT


def test_operator_voice_rejected_even_with_target_secondary():
    """A secondary system claiming 'target' must not override a primary
    identification of the operator's voice."""
    decision, _ = decide_eligibility(
        make_input(primary_role=SpeakerRole.OPERATOR_VOICE, secondary_role=SpeakerRole.TARGET_FEMALE_SPEAKER)
    )
    assert decision is EligibilityDecision.REJECT


def test_overlap_is_rejected_by_default():
    decision, _ = decide_eligibility(make_input(overlap_status=OverlapStatus.OVERLAP))
    assert decision is EligibilityDecision.REJECT


def test_unknown_overlap_goes_to_manual_review():
    decision, _ = decide_eligibility(make_input(overlap_status=OverlapStatus.UNKNOWN))
    assert decision is EligibilityDecision.MANUAL_REVIEW


def test_unknown_speaker_goes_to_manual_review():
    decision, _ = decide_eligibility(make_input(primary_role=SpeakerRole.UNKNOWN))
    assert decision is EligibilityDecision.MANUAL_REVIEW


def test_conflicting_systems_go_to_manual_review():
    decision, _ = decide_eligibility(make_input(secondary_role=SpeakerRole.OPERATOR_VOICE))
    assert decision is EligibilityDecision.MANUAL_REVIEW


def test_missing_secondary_verification_is_never_eligible():
    decision, _ = decide_eligibility(make_input(secondary_role=None, secondary_confidence=None))
    assert decision is EligibilityDecision.MANUAL_REVIEW


def test_medium_confidence_goes_to_manual_review():
    decision, _ = decide_eligibility(make_input(primary_confidence=0.75, secondary_confidence=0.80))
    assert decision is EligibilityDecision.MANUAL_REVIEW


def test_low_confidence_is_rejected():
    decision, _ = decide_eligibility(make_input(primary_confidence=0.30, secondary_confidence=0.40))
    assert decision is EligibilityDecision.REJECT


def test_marginal_audio_quality_goes_to_manual_review():
    decision, _ = decide_eligibility(make_input(audio_quality_acceptable=False))
    assert decision is EligibilityDecision.MANUAL_REVIEW


def test_confidence_uses_the_weakest_system():
    inp = make_input(primary_confidence=0.99, secondary_confidence=0.50)
    assert classify_confidence(inp) is ConfidenceLevel.LOW


@pytest.mark.parametrize(
    "primary_role,secondary_role,overlap",
    list(itertools.product(SpeakerRole, list(SpeakerRole) + [None], OverlapStatus)),
)
def test_eligible_requires_target_speaker_agreement_and_no_overlap(primary_role, secondary_role, overlap):
    """Exhaustive guard: across every role/overlap combination, ELIGIBLE is
    only ever reachable when both systems agree on the target speaker and
    no overlap was detected."""
    inp = make_input(
        primary_role=primary_role,
        secondary_role=secondary_role,
        secondary_confidence=None if secondary_role is None else 0.99,
        overlap_status=overlap,
    )
    decision, _ = decide_eligibility(inp)
    if decision is EligibilityDecision.ELIGIBLE:
        assert primary_role is SpeakerRole.TARGET_FEMALE_SPEAKER
        assert secondary_role is SpeakerRole.TARGET_FEMALE_SPEAKER
        assert overlap is OverlapStatus.NONE
